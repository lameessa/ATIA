"""All OpenAI calls are mocked; these tests never spend API credits."""
import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from atia.storage.sqlite import PhotoStore
from atia.models import normalize
from atia.destinations.pipeline import build_destinations
from atia.research.identity import research_locations
from atia.research.providers import Source
from atia.agents.contracts import Limits,PROPOSAL
from atia.agents.runner import run_agent,make_client,compact_history
from atia.agents.storage import AgentStore


@pytest.fixture
def location(tmp_path):
    with PhotoStore(tmp_path/'agent.sqlite3') as store:
        store.save(normalize({'id':'1','title':'untrusted photo text','latitude':24.7,'longitude':46.7,'accuracy':16,
            'country_verification':{'_content':'Saudi Arabia'}},'afaq_historical'))
        cluster=build_destinations(store)['destinations'][0]['destination_id']
        yield store,cluster


def response(tool=None,args=None,decision=None,number=1,status='completed'):
    items=[]
    if tool:
        value={'type':'function_call','name':tool,'arguments':json.dumps(args or {}),'call_id':f'call-{number}'}
        items=[SimpleNamespace(**value,model_dump=lambda **kw:value)]
    usage=SimpleNamespace(input_tokens=100,output_tokens=50,model_dump=lambda:{'input_tokens':100,'output_tokens':50})
    return SimpleNamespace(id=f'resp-{number}',status=status,usage=usage,output=items,output_text=json.dumps(decision) if decision else '')


def investigate(cluster):
    return {'decision':'INVESTIGATE','explanation':'The inspected cluster needs authoritative attraction mapping.',
            'claims':[{'claim':'This is a geographic photo cluster.','evidence_refs':['cluster:'+cluster]}],
            'uncertainties':['Exact attraction mapping is unconfirmed.'],'next_actions':['Review location evidence.'],
            'previous_proposal_id':None,'proposal':None}


def client_with(*responses):
    client=Mock();client.responses.create.side_effect=list(responses);return client


def test_dynamic_tools_receive_results_persist_memory_and_zero_cost_replay(location):
    store,cluster=location;before=store.connection.execute('SELECT * FROM photos').fetchall()
    calls=[]
    def choose(**kwargs):
        calls.append(len(kwargs['input']))
        if len(calls)==1:return response('get_candidates')
        output=json.loads(kwargs['input'][-1]['output'])
        if len(calls)==2:
            # The mocked model branches on the actual previous tool output.
            assert output['identity']['status']=='not_researched'
            return response('get_memory',number=2)
        assert output['runs']==[]
        return response(decision=investigate(cluster),number=3)
    client=Mock();client.responses.create.side_effect=choose
    result=run_agent(store,cluster,client=client)
    assert result['decision']['decision']=='INVESTIGATE' and not result['errors']
    assert result['llm_requests']==3 and result['tool_calls']==2
    assert len(AgentStore(store).memory(cluster)['runs'])==1
    replay=run_agent(store,cluster,client=client)
    assert replay['cached'] and replay['replay_llm_requests']==0 and client.responses.create.call_count==3
    assert [dict(r) for r in before]==[dict(r) for r in store.connection.execute('SELECT * FROM photos')]
    assert store.connection.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert not store.connection.execute('PRAGMA foreign_key_check').fetchall()


def test_insufficient_evidence_and_fabricated_citations_never_create_draft(location):
    store,cluster=location;bad=investigate(cluster)
    bad['decision']='CREATE';bad['claims'][0]['evidence_refs']=['https://invented.invalid/source']
    client=client_with(response('get_candidates'),response(decision=bad,number=2))
    result=run_agent(store,cluster,client=client)
    assert result['decision']['decision']=='INVESTIGATE' and result['errors']
    assert AgentStore(store).memory(cluster)['proposals']==[]


def test_real_reference_does_not_validate_unsubstantiated_popularity(location):
    store,cluster=location;bad=investigate(cluster)
    bad['claims'][0]['claim']='This is a popular tourist destination.'
    result=run_agent(store,cluster,client=client_with(response('get_candidates'),response(decision=bad,number=2)))
    assert result['decision']['decision']=='INVESTIGATE' and result['errors']


def test_request_budget_prevents_any_api_call(location):
    store,cluster=location;client=Mock()
    result=run_agent(store,cluster,limits=Limits(run_budget_usd=.0000001),client=client)
    assert result['llm_requests']==0 and result['decision']['decision']=='INVESTIGATE'
    client.responses.create.assert_not_called()


def test_strict_steps_tools_and_final_request_disables_tools(location):
    store,cluster=location
    client=client_with(response('get_candidates'),response('get_memory',number=2))
    result=run_agent(store,cluster,limits=Limits(max_steps=2,max_tool_calls=1),client=client)
    assert result['llm_requests']==2 and result['tool_calls']==1
    assert client.responses.create.call_args.kwargs['tool_choice']=='none'
    assert result['decision']['decision']=='INVESTIGATE' and result['errors']


def test_unknown_tool_and_invalid_arguments_are_safe_tool_outputs(location):
    store,cluster=location
    client=client_with(response('run_shell',{'cmd':'bad'}),response('inspect_evidence',{'view':'invalid'},number=2),response(decision=investigate(cluster),number=3))
    result=run_agent(store,cluster,client=client)
    assert all(t['status']=='error' for t in result['trace'])
    assert result['decision']['decision']=='INVESTIGATE'


def test_missing_credentials_and_api_error_never_expose_remote_body(location,monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    with pytest.raises(ValueError,match='OPENAI_API_KEY'):make_client(Limits())
    store,cluster=location
    client=Mock();client.responses.create.side_effect=RuntimeError('secret-example-must-not-leak')
    result=run_agent(store,cluster,client=client)
    assert 'secret-example-must-not-leak' not in json.dumps(result)
    assert result['conservative_ledger_charge_usd']>0 and result['llm_requests']==1


def test_lifetime_reservation_survives_errors_and_next_runs(location):
    store,cluster=location;client=Mock();client.responses.create.side_effect=TimeoutError('remote')
    limits=Limits(lifetime_budget_usd=.002)
    first=run_agent(store,cluster,client=client,limits=limits)
    second=run_agent(store,cluster,client=client,limits=limits)
    assert first['llm_requests']<=1 and second['llm_requests']==0


def test_rate_limit_retry_is_bounded_and_counts_against_steps(location):
    store,cluster=location
    error=RuntimeError('do not log');error.status_code=429
    client=client_with(error,response('get_candidates',number=2),response(decision=investigate(cluster),number=3))
    result=run_agent(store,cluster,client=client,pause=lambda _:None)
    assert result['llm_requests']==3 and result['conservative_ledger_charge_usd']>result['estimated_api_cost_usd']


def add_verified(store,cluster):
    provider=Mock(name='tavily');provider.name='mock_tavily';provider.cache_identity='mock';provider.network_calls=0;provider.cache_hits=0;provider.observations=[]
    url='https://www.experiencealula.com/en/places-to-go/maraya'
    provider.search.return_value=[Source('Maraya','https://www.experiencealula.com/en/places-to-go/maraya','Experience AlUla',
        'Maraya is a visitor attraction and mirrored venue with guided experiences in AlUla.',access='tavily_search_content').validate()]
    plan={'locations':[{'cluster_id':cluster,'association_notes':'Unverified photo association',
        'options':[{'name':'Maraya','aliases':['Maraya'],'entity_type':'attraction'}]}]}
    research_locations(store,provider,plan,limit=3)
    return url


def proposal_decision(cluster,url):
    d=investigate(cluster);d['decision']='CREATE'
    d['explanation']='A hypothetical visitor-information concept can be reviewed using official source evidence.'
    d['claims']=[{'claim':'Maraya is a visitor attraction.','evidence_refs':[url]}]
    d['proposal']={key:{'en':'Hypothesis: Maraya visitor information, subject to validation.','ar':'فرضية: معلومات زيارة مرايا، تحتاج إلى التحقق.'}
                   for key in PROPOSAL['properties'] if key!='supporting_evidence'}
    d['proposal']['supporting_evidence']=[url]
    return d


def test_bilingual_pending_drafts_and_repeated_evidence_deduplication(location):
    store,cluster=location;url=add_verified(store,cluster);d=proposal_decision(cluster,url)
    client=client_with(response('inspect_evidence',{'view':'research'}),response(decision=d,number=2))
    first=run_agent(store,cluster,client=client)
    assert not first['errors'] and first['proposal_status']=='PENDING_APPROVAL'
    second=run_agent(store,cluster,client=client_with(response('inspect_evidence',{'view':'research'}),response(decision=d,number=2)),refresh=True)
    assert second['decision']['decision']=='NO_ACTION'
    assert len(AgentStore(store).memory(cluster)['proposals'])==1


def test_update_requires_real_previous_proposal_and_new_evidence(location):
    store,cluster=location;url=add_verified(store,cluster);d=proposal_decision(cluster,url)
    d['decision']='UPDATE';d['previous_proposal_id']='invented-proposal'
    result=run_agent(store,cluster,client=client_with(response('inspect_evidence',{'view':'research'}),response(decision=d,number=2)))
    assert result['decision']['decision']=='INVESTIGATE' and not result['proposal_id']


def test_changed_photo_evidence_invalidates_completed_run_cache(location):
    store,cluster=location
    run_agent(store,cluster,client=client_with(response('get_candidates'),response(decision=investigate(cluster),number=2)))
    with store.connection:store.connection.execute("UPDATE photos SET title='changed metadata' WHERE photo_id='1'")
    result=run_agent(store,cluster,client=client_with(response('get_candidates'),response(decision=investigate(cluster),number=2)))
    assert not result['cached']


def test_compaction_removes_only_repeated_reference_payloads():
    value={'evidence_ref':'research:1','sources':[{'url':'https://example.org','content':'original retrieved evidence'}]}
    history=[{'type':'function_call_output','call_id':'a','output':json.dumps({'research':value})},
             {'type':'function_call_output','call_id':'b','output':json.dumps({'research':value,'other':'keep this'})}]
    compact=compact_history(history)
    assert json.loads(compact[0]['output'])['research']==value
    assert json.loads(compact[1]['output'])=={'research':{'previously_returned_evidence_ref':'research:1'},'other':'keep this'}
    assert compact_history(compact)==compact


def test_persisted_request_limit_and_unsafe_resume_fail_closed(location):
    store,cluster=location;limits=Limits(max_steps=1)
    first=run_agent(store,cluster,client=client_with(response(decision=investigate(cluster))),limits=limits)
    memory=AgentStore(store)
    with pytest.raises(RuntimeError,match='request limit'):
        memory.reserve(first['run_id'],2,.00001,limits)
    with pytest.raises(ValueError,match='resume safely'):
        run_agent(store,cluster,client=Mock(),limits=limits,resume_run_id=first['run_id'])


def test_sourced_observations_persist_and_unsourced_ones_fail(location):
    store,cluster=location
    client=client_with(response('get_candidates'),response('save_observation',{
        'content':'Review exact location before promotion.','evidence_refs':['cluster:'+cluster]},number=2),
        response(decision=investigate(cluster),number=3))
    result=run_agent(store,cluster,client=client)
    assert not result['errors']
    observations=AgentStore(store).memory(cluster)['observations']
    assert len(observations)==1 and json.loads(observations[0]['evidence_refs'])==['cluster:'+cluster]


def test_live_research_wrapper_uses_mocked_existing_provider_and_keeps_provenance(location):
    store,cluster=location;url=add_verified(store,cluster)
    provider=Mock();provider.observations=[{'observation_id':'tavily-test','cache_hit':False,'request_id':'test-request'}]
    provider.search.return_value=[Source('Maraya',url,'Experience AlUla','A mirrored venue and visitor attraction in AlUla.',access='tavily_search_content').validate()]
    d=investigate(cluster);d['claims']=[{'claim':'An official Maraya source is available.','evidence_refs':[url]}]
    result=run_agent(store,cluster,client=client_with(response('research_live',{'query':'Maraya visitor access'}),
        response(decision=d,number=2)),provider=provider)
    assert result['additional_tavily_searches']==1 and not result['errors']
    stored=store.connection.execute('SELECT result_json FROM agent_tool_calls WHERE run_id=?',(result['run_id'],)).fetchone()[0]
    assert json.loads(stored)['provenance']['request_id']=='test-request'


@pytest.mark.parametrize('kwargs',[{'max_steps':99},{'max_tool_calls':0},{'run_budget_usd':5},{'lifetime_budget_usd':5},
    {'model':'unpriced-model'},{'run_budget_usd':float('nan')},{'max_searches':10}])
def test_unsafe_or_unpriced_limits_fail_closed(kwargs):
    with pytest.raises(ValueError):Limits(**kwargs)
