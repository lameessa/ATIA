"""Full selected-destination workflow, with mocked Responses API and real temp SQLite."""
import json
import sqlite3
import time
from pathlib import Path
from uuid import uuid4
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from atia.api.dashboard import create_app
from atia.agents.runner import run_agent
from atia.agents.discovery_storage import DiscoveryStore
from atia.storage.sqlite import PhotoStore
from test_discovery import prepared,autonomous_client
from test_dashboard_api import HEADERS


def poll(client,identifier):
    for _ in range(200):
        value=client.get('/api/campaign-requests/'+identifier).json()
        if value['status'] not in ('queued','running'):return value
        time.sleep(.01)
    pytest.fail('Mock campaign job did not finish')


def setup(prepared):
    s,cluster,_=prepared()
    with s:
        with s.connection:s.connection.execute("UPDATE photos SET license_name='Attribution',license_url='https://creativecommons.org/licenses/by/4.0/' WHERE photo_id='1001'")
        entity=s.connection.execute('SELECT entity_id FROM verified_location_entities').fetchone()[0]
        path=s.connection.execute('pragma database_list').fetchone()[2]
    return path,entity,cluster


def mock_runner(store,target_entity_id,limits,progress):
    return run_agent(store,target_entity_id=target_entity_id,limits=limits,progress=progress,client=autonomous_client())


def test_discover_create_edit_approve_calendar_with_mocked_openai(prepared):
    path,entity,cluster=setup(prepared);runner=Mock(side_effect=mock_runner)
    with TestClient(create_app(path,runner)) as client:
        assert client.get('/api/destinations/'+cluster).status_code==200
        assert client.get('/api/calendar').json()['entries']==[]
        body={'entity_id':entity,'confirmed':True,'idempotency_key':str(uuid4())}
        assert client.post('/api/campaign-requests',json=body).status_code==403
        assert client.post('/api/campaign-requests',headers=HEADERS,json={**body,'confirmed':False}).status_code==422
        queued=client.post('/api/campaign-requests',headers=HEADERS,json=body)
        assert queued.status_code==202
        job=poll(client,queued.json()['job_id']);assert job['status']=='completed' and job['outcome']=='CREATE'
        identifier=job['campaign_id'];assert identifier
        assert client.get('/api/calendar').json()['entries']==[]
        assert client.post('/api/campaign-requests',headers=HEADERS,json=body).json()['job_id']==job['job_id']
        existing=client.post('/api/campaign-requests',headers=HEADERS,json={**body,'idempotency_key':str(uuid4())}).json()
        assert existing['status']=='existing' and existing['campaign_id']==identifier and runner.call_count==1
        campaign=client.get('/api/workspace').json()['campaigns'][0];original=campaign['content']
        edit={'confirmed':True,'editor':'Test human','revision':0,'title':{'en':'Human-edited title','ar':'عنوان معدل'},'publishing_dates':{'p1':'2026-11-03','p2':'2026-11-06'},'captions':{'p1':{'en':'Human English caption','ar':'تعليق عربي معدل'}}}
        response=client.post(f'/api/campaigns/{identifier}/edit',headers=HEADERS,json=edit)
        assert response.status_code==200,response.text
        revised=response.json();assert revised['revision']==1 and revised['content']['campaign_name']['en']=='Human-edited title'
        assert revised['content']['source_refs']==original['source_refs']
        assert client.post(f'/api/campaigns/{identifier}/edit',headers=HEADERS,json=edit).status_code==409
        assert client.post(f'/api/campaigns/{identifier}/review',headers=HEADERS,json={'confirmed':True,'decision':'APPROVED','revision':0}).status_code==409
        review={'confirmed':True,'decision':'APPROVED','revision':1,'reviewer':'Test human'}
        assert client.post(f'/api/campaigns/{identifier}/review',headers=HEADERS,json=review).status_code==200
        entries=client.get('/api/calendar').json()['entries'];assert len(entries)==2
        assert entries[0]['proposed_date']=='2026-11-03' and entries[0]['caption']['en']=='Human English caption'
        assert client.post(f'/api/campaigns/{identifier}/edit',headers=HEADERS,json={**edit,'revision':1}).status_code==409
        assert client.post(f'/api/campaigns/{identifier}/review',headers=HEADERS,json={**review,'decision':'REVISION_REQUESTED'}).status_code==200
        assert client.get('/api/calendar').json()['entries']==[]
        response=client.post(f'/api/campaigns/{identifier}/edit',headers=HEADERS,json={**edit,'revision':1,'title':{'en':'Second edit','ar':'تعديل ثان'}})
        assert response.status_code==200 and response.json()['status']=='PENDING_APPROVAL'
    with PhotoStore(path) as s:
        memory=DiscoveryStore(s).campaigns()[0]
        assert memory['campaign']==original and memory['effective_status']=='PENDING_APPROVAL'
        assert s.connection.execute('select count(*) from campaign_edits').fetchone()[0]==2
        assert s.connection.execute('pragma foreign_key_check').fetchall()==[]
        assert s.connection.execute('pragma integrity_check').fetchone()[0]=='ok'


def test_insufficient_evidence_and_unverified_identity_never_force_campaign(prepared):
    path,entity,_=setup(prepared)
    def investigate(store,**kwargs):return run_agent(store,client=autonomous_client(create=False),**kwargs)
    runner=Mock(side_effect=investigate)
    with TestClient(create_app(path,runner)) as client:
        body={'entity_id':'not-verified','confirmed':True,'idempotency_key':str(uuid4())}
        assert client.post('/api/campaign-requests',headers=HEADERS,json=body).status_code==409
        assert runner.call_count==0
        queued=client.post('/api/campaign-requests',headers=HEADERS,json={**body,'entity_id':entity}).json()
        job=poll(client,queued['job_id']);assert job['outcome']=='INVESTIGATE' and not job['campaign_id']
        assert client.get('/api/workspace').json()['campaigns']==[]


def test_failure_and_restart_do_not_retry_paid_jobs(prepared):
    path,entity,_=setup(prepared);runner=Mock(side_effect=RuntimeError('secret service error'))
    with TestClient(create_app(path,runner)) as client:
        body={'entity_id':entity,'confirmed':True,'idempotency_key':str(uuid4())}
        queued=client.post('/api/campaign-requests',headers=HEADERS,json=body).json();job=poll(client,queued['job_id'])
        assert job['status']=='failed' and 'secret' not in json.dumps(job)
    db=sqlite3.connect(path)
    with db:db.execute("UPDATE campaign_preparation_jobs SET status='running'")
    db.close()
    with TestClient(create_app(path,runner)) as client:
        assert client.get('/api/campaign-requests').json()['jobs'][0]['status']=='interrupted'
    assert runner.call_count==1


def test_edit_cannot_change_evidence_or_destination(prepared):
    path,entity,_=setup(prepared)
    with TestClient(create_app(path,mock_runner)) as client:
        job=poll(client,client.post('/api/campaign-requests',headers=HEADERS,json={'entity_id':entity,'confirmed':True,'idempotency_key':str(uuid4())}).json()['job_id'])
        url=f"/api/campaigns/{job['campaign_id']}/edit"
        base={'confirmed':True,'editor':'Human','revision':0}
        for payload in ({'source_refs':['invented']},{'destination':{'name':'other'}},{'captions':{'unknown':{'en':'Test','ar':'اختبار'}}},{'publishing_dates':{'p1':'not-a-date'}},{'title':{'en':'Title','ar':'not Arabic'}}):
            assert client.post(url,headers=HEADERS,json={**base,**payload}).status_code==422


def test_autonomous_destination_free_request_is_still_available(prepared):
    path,_,_=setup(prepared)
    with TestClient(create_app(path,mock_runner)) as client:
        job=poll(client,client.post('/api/campaign-requests',headers=HEADERS,json={'confirmed':True,'idempotency_key':str(uuid4())}).json()['job_id'])
        assert job['entity_id'] is None and job['outcome']=='CREATE'


def test_selected_destination_tools_accept_only_real_cluster_ids(prepared):
    path,entity,cluster=setup(prepared);client=autonomous_client()
    with PhotoStore(path) as store:
        result=run_agent(store,target_entity_id=entity,client=client)
        assert result['campaign_id'] and result['selected_cluster_id']==cluster
    first=client.responses.create.call_args_list[0].kwargs
    for tool in first['tools']:
        if 'cluster_id' in tool['parameters']['properties']:
            assert tool['parameters']['properties']['cluster_id']['enum']==[cluster]
    assert entity not in first['instructions'].split('Use the exact cluster_id')[0] or 'Entity IDs' in first['instructions']
