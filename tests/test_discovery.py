"""Full discovery/campaign workflows use mocked model/search responses only.

Synthetic evidence lives in temporary test databases, never the real workspace.
"""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from PIL import Image
from atia.models import normalize
from atia.storage.sqlite import PhotoStore
from atia.destinations.pipeline import build_destinations
from atia.research.identity import research_locations
from atia.research.providers import Source
from atia.vision.storage import AnalysisStore
from atia.agents.contracts import Limits
from atia.agents.discovery_contracts import CAMPAIGN
from atia.agents.discovery_storage import DiscoveryStore
from atia.agents.discovery_tools import candidate_pool
from atia.agents.runner import run_agent
from atia.agents.storage import AgentStore
from test_agent import response,client_with

URL1='https://saudipedia.com/en/test-heritage-valley'
URL2='https://www.spa.gov.sa/en/test-heritage-valley'
TEXT1='Example Heritage Valley is a lesser-known destination with stone trails and heritage buildings.'
from display_fixtures import approve
TEXT2='Example Heritage Valley offers a small visitor heritage route and cultural experiences.'


@pytest.fixture
def prepared(tmp_path):
    def make(mapped=True):
        path=tmp_path/('mapped.sqlite3' if mapped else 'unmapped.sqlite3')
        s=PhotoStore(path)
        for i,lat in [('1001',24.7),('1002',27.5)]:
            s.save(normalize({'id':i,'title':'Test heritage scenery','latitude':lat,'longitude':46.7,'accuracy':16,
                'country_verification':{'_content':'Saudi Arabia'}},'afaq_historical'))
        annotations=tmp_path/'places.json'
        annotations.write_text(json.dumps([{'source':'afaq_historical','photo_id':'1001','place_id':'fixture-place',
            'name':'Example Heritage Valley','level':'individual_attraction','verified':True,
            'evidence_url':URL1,'reviewer':'Human test-fixture reviewer'}]))
        report=build_destinations(s,places_path=annotations if mapped else None)
        cluster=next(g['destination_id'] for g in report['destinations'] if g['photo_ids']==['1001'])
        sources=[Source('Example Heritage Valley',URL1,'Saudipedia',TEXT1,access='tavily_search_content').validate(),
                 Source('Example Heritage Valley',URL2,'Saudi Press Agency',TEXT2,access='tavily_search_content').validate()]
        provider=Mock();provider.name='mock_tavily';provider.cache_identity='fixture';provider.network_calls=0;provider.cache_hits=0;provider.observations=[]
        provider.search.return_value=sources
        plan={'locations':[{'cluster_id':cluster,'association_notes':'Test-only provisional assessment',
                           'options':[{'name':'Example Heritage Valley','aliases':['Example Heritage Valley'],'entity_type':'destination'}]}]}
        research_locations(s,provider,plan,limit=3)
        image=tmp_path/'approved-test.jpg';Image.new('RGB',(100,100),'green').save(image)
        sha=hashlib.sha256(image.read_bytes()).hexdigest()
        model=SimpleNamespace(model_name='mock-visual',pretrained='mock',prompt_version='mock',prompts={'heritage':'test'},library_version='mock',device='cpu')
        asset=SimpleNamespace(sha256=sha,url='https://live.staticflickr.com/1001_test.jpg',path=str(image),width=100,height=100)
        AnalysisStore(s).save({'source':'afaq_historical','photo_id':'1001'},model,asset,{'heritage':.3},'fixture-visual-run')
        approve(s.connection,'afaq_historical','1001')
        return s,cluster,sources
    return make


def decision(cluster,inspect_output,create=True):
    research=inspect_output['research'];entity=research['entities'][0]
    result={'selected_cluster_id':cluster,'selection_reason':'Select the source-supported heritage candidate for investigation.',
        'decision':'CREATE' if create else 'INVESTIGATE','explanation':'Source evidence supports a limited lesser-known hypothesis; proposed tactics require validation.',
        'claims':[{'claim':'The source describes a lesser-known heritage destination.','evidence_refs':[URL1]}],
        'hidden_gem':{'classification':'potential_hidden_gem' if create else 'unresolved','hypothesis':'Potential discovery opportunity, not proven demand.',
            'supporting_evidence':[{'source_ref':URL1,'quote':TEXT1},{'source_ref':URL2,'quote':TEXT2}],
            'contradicting_evidence':[],'limitations':['Source excerpts and no measured audience baseline.']},
        'uncertainties':['All audience and performance assumptions need human validation.'],'next_actions':['Review evidence and rights before any launch.'],
        'previous_campaign_id':None,'campaign':None}
    if not create:return result
    bilingual={'en':'Hypothesis: a small heritage discovery pilot; validate before launch.','ar':'فرضية: تجربة صغيرة لاستكشاف التراث وتحتاج إلى التحقق قبل الإطلاق.'}
    campaign={k:copy.deepcopy(bilingual) for k in ('campaign_name','central_concept','opportunity_hypothesis','target_audience','audience_rationale_hypothesis','creative_direction')}
    campaign['destination']={'entity_id':entity['entity_id'],'name':{'en':'Example Heritage Valley','ar':'وادي التراث التجريبي'},
        'verified_location':{'en':'Example Heritage Valley, Saudi Arabia','ar':'وادي التراث التجريبي في السعودية'},'verification_refs':[URL1]}
    for key in ('objectives','key_messages','recommended_activities','risks_uncertainties_validation'):campaign[key]=[copy.deepcopy(bilingual)]
    campaign['social_posts']=[{'post_id':'p1','channel':'Instagram','caption':copy.deepcopy(bilingual)},
                              {'post_id':'p2','channel':'Instagram','caption':copy.deepcopy(bilingual)}]
    campaign['suggested_channels']=['Instagram']
    campaign['publishing_schedule']=[{'post_id':f'p{i+1}','days_after_human_approved_launch':i*3,'local_time':'18:30','timezone':'Asia/Riyadh','channel':'Instagram','activity':copy.deepcopy(bilingual)} for i in range(2)]
    campaign['kpis_and_measurement']=[{'metric':copy.deepcopy(bilingual),'measurement_plan':copy.deepcopy(bilingual),
        'baseline':'UNMEASURED','proposed_target_hypothesis':copy.deepcopy(bilingual)}]
    campaign['source_refs']=[URL1,URL2]
    asset=inspect_output['assets'][0]
    mapping=asset['identity_mappings'][0]['reference'] if asset['identity_mappings'] else 'unverified-map'
    campaign['approved_photo_assets']=[{'source':asset['source'],'photo_id':asset['photo_id'],'image_sha256':asset['image_sha256'],
        'identity_mapping_ref':mapping,'usage_hypothesis':copy.deepcopy(bilingual)}]
    result['campaign']=campaign
    return result


def autonomous_client(transform=None,create=True):
    client=Mock();state={}
    def choose(**kwargs):
        outputs=[v for v in kwargs['input'] if v.get('type')=='function_call_output']
        if not outputs:return response('list_candidates',{'offset':0})
        payload=json.loads(outputs[-1]['output'])
        if 'candidates' in payload:
            # The mock's choice depends on actual tool output, not user input.
            candidate=next(c for c in payload['candidates'] if c['candidate_names'])
            state['cluster']=candidate['cluster_id']
            return response('inspect_candidate',{'cluster_id':state['cluster']},number=2)
        d=decision(state['cluster'],payload,create=create)
        if transform:d=transform(d,payload)
        return response(decision=d,number=3)
    client.responses.create.side_effect=choose
    return client


def test_destination_free_cycle_llm_selects_and_creates_full_bilingual_pending_campaign(prepared):
    s,cluster,_=prepared()
    with s:
        result=run_agent(s,client=autonomous_client())
        assert not result['errors'] and result['selected_cluster_id']==cluster
        assert result['decision']['decision']=='CREATE' and result['campaign_status']=='PENDING_APPROVAL'
        assert result['llm_requests']==3 and [t['tool'] for t in result['trace']]==['list_candidates','inspect_candidate']
        campaigns=DiscoveryStore(s).campaigns();assert len(campaigns)==1
        assert set(campaigns[0]['campaign'])==set(CAMPAIGN['properties'])
        assert campaigns[0]['campaign']['kpis_and_measurement'][0]['baseline']=='UNMEASURED'
        assert s.connection.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not s.connection.execute('PRAGMA foreign_key_check').fetchall()


def test_cache_and_forced_repeat_do_not_duplicate_campaigns(prepared):
    s,cluster,_=prepared()
    with s:
        client=autonomous_client();first=run_agent(s,client=client)
        replay=run_agent(s,client=client)
        assert replay['cached'] and replay['replay_llm_requests']==0 and client.responses.create.call_count==3
        repeated=run_agent(s,client=autonomous_client(),refresh=True)
        assert repeated['decision']['decision']=='NO_ACTION' and len(DiscoveryStore(s).campaigns())==1
        assert DiscoveryStore(s).memory(cluster)['campaigns'][0]['campaign_id']==first['campaign_id']


def test_provisional_photo_identity_cannot_generate_campaign(prepared):
    s,_,_=prepared(mapped=False)
    with s:
        result=run_agent(s,client=autonomous_client())
        assert result['decision']['decision']=='INVESTIGATE' and result['errors']
        assert DiscoveryStore(s).campaigns()==[]


@pytest.mark.parametrize('error',['fake_quote','missing_positive_evidence','one_publisher','fake_baseline','missing_caption','invented_photo','missing_arabic','bad_schedule','missing_verified_location'])
def test_campaign_validation_rejects_unsupported_or_incomplete_material(prepared,error):
    s,_,_=prepared()
    def corrupt(d,payload):
        if error=='fake_quote':d['hidden_gem']['supporting_evidence'][0]['quote']='Fabricated tourism demand statistics never returned by any source.'
        elif error=='missing_positive_evidence':d['hidden_gem']['supporting_evidence']=[]
        elif error=='one_publisher':d['hidden_gem']['supporting_evidence']=d['hidden_gem']['supporting_evidence'][:1]
        elif error=='fake_baseline':d['campaign']['kpis_and_measurement'][0]['baseline']='10000 visitors'
        elif error=='missing_caption':d['campaign']['social_posts']=d['campaign']['social_posts'][:1]
        elif error=='invented_photo':d['campaign']['approved_photo_assets'][0]['photo_id']='999999'
        elif error=='missing_arabic':d['campaign']['central_concept']['ar']='English only'
        elif error=='bad_schedule':d['campaign']['publishing_schedule'][0]['local_time']='99:99'
        else:d['campaign']['destination']['verification_refs']=[]
        return d
    with s:
        result=run_agent(s,client=autonomous_client(corrupt));assert result['errors']
        assert result['decision']['decision']=='INVESTIGATE' and not DiscoveryStore(s).campaigns()


def test_no_eligible_candidates_costs_nothing(tmp_path,monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    with PhotoStore(tmp_path/'empty.sqlite3') as s:
        client=Mock();r=run_agent(s,client=client)
        assert r['decision']['decision']=='NO_ACTION' and r['llm_requests']==0
        client.responses.create.assert_not_called()


def test_moderation_and_uncertain_reviews_are_excluded_without_changing_historical_data(prepared):
    s,_,_=prepared()
    with s:
        before=s.connection.execute("SELECT count(*) FROM photos WHERE source='afaq_historical'").fetchone()[0]
        s.save(normalize({'id':'2001','latitude':25.1,'longitude':46.7,'accuracy':16,'country_verification':{'_content':'Saudi Arabia'}},'flickr_live'))
        build_destinations(s)
        assert all('2001' not in p['photo_ids'] for p in candidate_pool(s))
        assert s.connection.execute("SELECT count(*) FROM photos WHERE source='afaq_historical'").fetchone()[0]==before


def test_shared_spending_limit_covers_destination_and_discovery_requests(prepared):
    s,cluster,_=prepared()
    with s:
        r=run_agent(s,client=autonomous_client())
        cycle=DiscoveryStore(s)
        with s.connection:s.connection.execute('UPDATE agent_discovery_requests SET charged_usd=.1')
        legacy=AgentStore(s)
        with s.connection:s.connection.execute('INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?,?,?,?)',('legacy',cluster,'test','2026-01-01',None,'key','running','gpt-4o-mini','{}',None))
        with pytest.raises(RuntimeError,match='spending'):legacy.reserve('legacy',1,.01,Limits(lifetime_budget_usd=.25))


def revise_source(s,text):
    row=s.connection.execute('SELECT assessment_id,result FROM live_location_research ORDER BY assessed_at DESC LIMIT 1').fetchone()
    value=json.loads(row['result']);value['sources'][0]['evidence']+=' '+text
    with s.connection:s.connection.execute('UPDATE live_location_research SET result=? WHERE assessment_id=?',(json.dumps(value),row['assessment_id']))


def test_update_persists_new_draft_and_preserves_original_when_actual_source_changes(prepared):
    s,_,_=prepared()
    with s:
        original=run_agent(s,client=autonomous_client())
        revise_source(s,'A newly documented heritage walking route adds a visitor experience.')
        def update(d,payload):
            d['decision']='UPDATE';d['previous_campaign_id']=original['campaign_id']
            d['campaign']['central_concept']['en']='Hypothesis: revise the discovery pilot to test the documented walking route.'
            d['claims'].append({'claim':'A source now documents a heritage walking route.','evidence_refs':[URL1]})
            return d
        revised=run_agent(s,client=autonomous_client(update))
        assert not revised['errors'] and revised['decision']['decision']=='UPDATE'
        rows=DiscoveryStore(s).campaigns();assert len(rows)==2 and all(r['status']=='PENDING_APPROVAL' for r in rows)
        latest=next(r for r in rows if r['campaign_id']==revised['campaign_id'])
        assert latest['previous_campaign_id']==original['campaign_id']


def test_established_counterevidence_cannot_be_ignored(prepared):
    s,_,_=prepared()
    with s:
        revise_source(s,'It is a world-famous and popular attraction with established promotion.')
        r=run_agent(s,client=autonomous_client())
        assert r['decision']['decision']=='INVESTIGATE' and 'counterevidence' in r['errors'][0]
        assert not DiscoveryStore(s).campaigns()


def test_dynamic_tavily_research_uses_existing_provider_and_persists_actual_tool_provenance(prepared):
    s,cluster,sources=prepared();state={}
    provider=Mock();provider.search.return_value=sources;provider.network_calls=0;provider.cache_hits=1
    provider.observations=[{'observation_id':'mock-cached-search','request_id':'mock-request','cache_hit':True}]
    def choose(**kwargs):
        outputs=[v for v in kwargs['input'] if v.get('type')=='function_call_output']
        if not outputs:return response('list_candidates',{'offset':0})
        payload=json.loads(outputs[-1]['output'])
        if len(outputs)==1:
            selected=next(c for c in payload['candidates'] if c['candidate_names']);state['cluster']=selected['cluster_id']
            return response('inspect_candidate',{'cluster_id':state['cluster']},number=2)
        if len(outputs)==2:
            state['dossier']=payload
            return response('research_candidate',{'cluster_id':state['cluster'],'query':'Example Heritage Valley official lesser-known visitor destination',
                'purpose':'promotional_coverage','proposed_name':None,'entity_type':None},number=3)
        assert payload['provenance']['cache_hit'] is True
        return response(decision=decision(cluster,state['dossier'],create=False),number=4)
    client=Mock();client.responses.create.side_effect=choose
    with s:
        r=run_agent(s,client=client,provider=provider)
        assert not r['errors'] and r['llm_requests']==4 and r['tool_calls']==3
        assert r['tavily_cache_hits']==1 and r['tavily_source_observations'][0]['request_id']=='mock-request'
        provider.search.assert_called_once()


def test_saved_campaign_hidden_when_snapshot_changes(prepared):
    s,_,_=prepared()
    with s:
        run_agent(s,client=autonomous_client())
        memory=DiscoveryStore(s)
        assert len(memory.campaigns())==1
        image=Path(s.connection.execute('SELECT image_path FROM visual_analyses LIMIT 1').fetchone()[0])
        image.write_bytes(b'changed snapshot')
        assert memory.campaigns()==[]
        assert s.connection.execute('SELECT count(*) FROM agent_campaigns').fetchone()[0]==1


def test_general_marketing_opportunity_needs_source_described_visitor_experience(prepared):
    s,_,_=prepared()
    def general(d,_):
        d['hidden_gem']['classification']='supported_marketing_opportunity'
        return d
    with s:
        result=run_agent(s,client=autonomous_client(transform=general))
        assert result['decision']['decision']=='CREATE'
        assert result['decision']['hidden_gem']['classification']=='supported_marketing_opportunity'


def test_general_opportunity_cannot_claim_hidden_gem_status(prepared):
    s,_,_=prepared()
    def invalid(d,_):
        d['hidden_gem']['classification']='supported_marketing_opportunity'
        d['campaign']['campaign_name']['en']='An overlooked hidden gem'
        return d
    with s:
        result=run_agent(s,client=autonomous_client(transform=invalid))
        assert result['decision']['decision']=='INVESTIGATE' and not result['campaign_id']
