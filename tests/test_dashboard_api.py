"""Dashboard tests use temporary SQLite databases and mocked agent execution only."""
import json
import sqlite3
import threading
import time
from uuid import uuid4
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from atia.models import normalize,utc_now
from atia.storage.sqlite import PhotoStore
from atia.destinations.pipeline import build_destinations
from atia.agents.storage import AgentStore,encode
from atia.api.dashboard import create_app
from atia.api.data import DashboardData

HEADERS={'X-ATIA-Action':'confirmed','Origin':'http://127.0.0.1:5173'}


@pytest.fixture
def dataset(tmp_path):
    path=tmp_path/'dashboard.sqlite3'
    with PhotoStore(path) as store:
        store.save(normalize({'id':'100','title':'Stored photograph','latitude':24.7,'longitude':46.7,'accuracy':16,
            'country_verification':{'_content':'Saudi Arabia'},'dateupload':'1700000000','datetaken':'2020-01-02 03:04:05'},'afaq_historical'))
        group=build_destinations(store)['destinations'][0]['destination_id'];AgentStore(store)
        decision={'decision':'INVESTIGATE','explanation':'Mocked test decision, not production evidence.','claims':[],
                  'uncertainties':['Test fixture only'],'next_actions':[]}
        result={'decision':decision,'estimated_api_cost_usd':0,'llm_requests':0,'tool_calls':0,'elapsed_seconds':0,
                'evidence_registry':{},'errors':[],'proposal_id':None,'evidence_fingerprint':'fixture'}
        with store.connection:
            store.connection.execute('INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?,?,?,?)',
                ('run-test',group,'Mock test goal',utc_now(),utc_now(),'cache-test','completed','mock-model','{}',encode(result)))
            bilingual={'destination':{'en':'Test fixture only','ar':'اختبار فقط'},'supporting_evidence':[]}
            store.connection.execute('INSERT INTO agent_proposals VALUES(?,?,?,?,?,?,?,?)',
                ('proposal-test','run-test',group,utc_now(),'PENDING_APPROVAL',None,'fixture',encode(bilingual)))
    return path,group


def wait_job(client,identifier):
    for _ in range(100):
        value=client.get('/api/agent/jobs/'+identifier).json()
        if value['status'] not in ('queued','running'):return value
        time.sleep(.01)
    pytest.fail('Mocked job did not finish')


def test_read_views_match_database_are_side_effect_free_and_never_run_agent(dataset):
    path,group=dataset;runner=Mock(side_effect=AssertionError('Must not call a paid service'))
    c=sqlite3.connect(path);before={t:list(c.execute('SELECT * FROM '+t)) for t in ('photos','destination_photo_assignments','agent_runs','agent_proposals')};c.close()
    with TestClient(create_app(path,runner)) as client:
        overview=client.get('/api/overview').json()
        assert overview['photo_count']==1 and overview['photo_sources']=={'afaq_historical':1}
        assert overview['geographic_clusters']==1 and overview['assigned_photos']==1
        assert overview['association_states']=={'not_researched':1}
        assert overview['relevance']=={'not_evaluated':1} and overview['pending_proposals']==1
        assert overview['decisions']=={'INVESTIGATE':1}
        assert client.get('/api/research').json()['queries']==[]
        for endpoint in ('/health','/photos','/api/destinations','/api/destinations/'+group,
                         '/api/research','/api/agent/runs','/api/agent/runs/run-test','/api/agent/policy','/api/proposals','/api/agent/jobs'):
            assert client.get(endpoint).status_code==200,endpoint
        photo=client.get('/api/destinations/'+group).json()['photos'][0]
        assert photo['uploaded_at']!=photo['captured_at'] and photo['relevance']=='not_evaluated'
        assert 'raw' not in client.get('/photos').text
    runner.assert_not_called()
    c=sqlite3.connect(path)
    assert all(list(c.execute('SELECT * FROM '+t))==v for t,v in before.items())
    assert c.execute('pragma integrity_check').fetchone()[0]=='ok' and c.execute('pragma foreign_key_check').fetchall()==[]
    c.close()


@pytest.mark.parametrize('decision',['APPROVED','REJECTED'])
def test_review_persists_without_overwriting_draft_and_is_idempotent(dataset,decision):
    path,_=dataset
    with TestClient(create_app(path)) as client:
        body={'decision':decision,'reviewer':'Test reviewer','notes':'Test evidence reviewed','confirmed':True}
        first=client.post('/api/proposals/proposal-test/review',json=body,headers=HEADERS)
        assert first.status_code==200
        assert client.post('/api/proposals/proposal-test/review',json=body,headers=HEADERS).json()['review_id']==first.json()['review_id']
        assert client.get('/api/proposals').json()['proposals'][0]['effective_status']==decision
        assert client.get('/api/overview').json()['pending_proposals']==0
        opposite='REJECTED' if decision=='APPROVED' else 'APPROVED'
        assert client.post('/api/proposals/proposal-test/review',json={**body,'decision':opposite},headers=HEADERS).status_code==409
    c=sqlite3.connect(path)
    assert c.execute('select status from agent_proposals').fetchone()[0]=='PENDING_APPROVAL'
    assert c.execute('select count(*) from dashboard_proposal_reviews').fetchone()[0]==1
    c.close()
    with PhotoStore(path) as store:
        remembered=AgentStore(store).memory(dataset[1])['proposals'][0]
        assert remembered['effective_status']==decision and remembered['review']['reviewer']=='Test reviewer'
    with TestClient(create_app(path)) as client:
        assert client.get('/api/proposals').json()['proposals'][0]['effective_status']==decision


def test_agent_explicit_confirmation_limits_progress_and_idempotency(dataset):
    path,group=dataset
    def fake(store,cluster_id,limits,progress):
        assert cluster_id==group and limits.max_steps<=4 and limits.run_budget_usd<=.05
        progress('Mocked agent progress for API testing only')
        return {'run_id':'run-test','errors':[],'cached':True}
    runner=Mock(side_effect=fake)
    with TestClient(create_app(path,runner)) as client:
        body={'cluster_id':group,'confirmed':True,'idempotency_key':str(uuid4())}
        assert client.post('/api/agent/run',json=body).status_code==403
        assert client.post('/api/agent/run',json=body,headers={**HEADERS,'Origin':'https://untrusted.example'}).status_code==403
        assert client.post('/api/agent/run',json={**body,'confirmed':False},headers=HEADERS).status_code==422
        queued=client.post('/api/agent/run',json=body,headers=HEADERS)
        assert queued.status_code==202
        job=wait_job(client,queued.json()['job_id']);assert job['status']=='completed' and len(job['progress'])==2
        assert 'no new LLM requests' in job['progress'][-1]['message']
        duplicate=client.post('/api/agent/run',json=body,headers=HEADERS)
        assert duplicate.json()['job_id']==job['job_id'] and runner.call_count==1


def test_agent_concurrency_and_sanitized_failures(dataset,monkeypatch):
    path,group=dataset;started=threading.Event();release=threading.Event()
    monkeypatch.setenv('OPENAI_API_KEY','private-test-key')
    def fake(*args,**kwargs):
        started.set();release.wait(2);raise RuntimeError('private-test-key confidential remote error')
    with TestClient(create_app(path,fake)) as client:
        body={'cluster_id':group,'confirmed':True,'idempotency_key':str(uuid4())}
        queued=client.post('/api/agent/run',json=body,headers=HEADERS).json();assert started.wait(1)
        assert client.post('/api/agent/run',json={**body,'idempotency_key':str(uuid4())},headers=HEADERS).status_code==409
        release.set();job=wait_job(client,queued['job_id'])
        assert job['status']=='failed' and 'private-test-key' not in json.dumps(job)
        assert client.get('/api/agent/jobs').json()['jobs'][0]['status']=='failed'


def test_missing_database_and_unknown_ids_are_graceful(tmp_path,dataset):
    with TestClient(create_app(tmp_path/'missing.sqlite3')) as client:
        assert client.get('/health').json()['database_available'] is False
        assert client.get('/api/overview').status_code==503
    path,_=dataset
    with TestClient(create_app(path)) as client:
        for endpoint in ('/api/destinations/unknown','/api/agent/runs/unknown','/api/agent/jobs/unknown'):
            assert client.get(endpoint).status_code==404
        assert client.post('/api/proposals/missing/review',json={'decision':'APPROVED','confirmed':True},headers=HEADERS).status_code==404


def test_secrets_and_private_reasoning_are_redacted(dataset,monkeypatch):
    path,_=dataset;monkeypatch.setenv('TAVILY_API_KEY','private-tavily-test')
    c=sqlite3.connect(path)
    with c:c.execute("UPDATE photos SET title='private-tavily-test'")
    c.close()
    with TestClient(create_app(path)) as client:
        text=client.get('/photos').text
        assert 'private-tavily-test' not in text and '[REDACTED]' in text
        run=client.get('/api/agent/runs/run-test').json()
        assert 'reasoning' not in run and 'api_key' not in str(run)


def test_read_connection_enforces_sqlite_query_only(dataset,monkeypatch):
    path,_=dataset
    def bad(self):self.db.execute("UPDATE photos SET title='should fail'")
    monkeypatch.setattr(DashboardData,'overview',bad)
    with TestClient(create_app(path)) as client:assert client.get('/api/overview').status_code==503
    c=sqlite3.connect(path);assert c.execute('select title from photos').fetchone()[0]=='Stored photograph';c.close()


def test_restart_interrupts_jobs_without_automatically_resuming_paid_work(dataset):
    path,group=dataset;runner=Mock()
    with TestClient(create_app(path)):pass
    c=sqlite3.connect(path)
    with c:c.execute('INSERT INTO dashboard_agent_jobs VALUES(?,?,?,?,?,?,?,?,?)',
        ('interrupted-job',str(uuid4()),group,utc_now(),None,'running',None,'[]',None))
    c.close()
    with TestClient(create_app(path,runner)) as client:
        job=client.get('/api/agent/jobs/interrupted-job').json()
        assert job['status']=='interrupted' and 'no automatic retry' in job['error']
    runner.assert_not_called()


def test_unsafe_budget_config_cannot_queue_agent_and_images_have_no_path_parameter(dataset,monkeypatch):
    path,group=dataset;runner=Mock()
    monkeypatch.setenv('ATIA_AGENT_RUN_BUDGET_USD','5')
    with TestClient(create_app(path,runner)) as client:
        assert client.get('/api/agent/policy').status_code==503
        assert client.post('/api/agent/run',headers=HEADERS,json={
            'cluster_id':group,'confirmed':True,'idempotency_key':str(uuid4())}).status_code==503
        assert client.get('/api/agent/jobs').json()['jobs']==[]
        assert client.get('/api/images/afaq_historical/100').status_code==404
    runner.assert_not_called()
