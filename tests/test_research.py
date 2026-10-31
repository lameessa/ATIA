import json
from unittest.mock import Mock
import pytest
from atia.models import normalize
from atia.storage.sqlite import PhotoStore
from atia.destinations.pipeline import build_destinations
from atia.research.providers import BraveSearch,Source,EvidenceFileSearch,ResearchUnavailable,ResearchFailed,public_url
from atia.research.tool import research_destination,run_research,select_candidates


def setup(store):
    record=normalize({'id':'1','latitude':24.7,'longitude':46.7,'accuracy':16,'country_verification':{'_content':'Saudi Arabia'}},'afaq_historical')
    store.save(record);report=build_destinations(store)
    return report['destinations'][0]['destination_id']


def source(kind='identity_reference'):
    return Source('Official test attraction','https://www.visitsaudi.com/en/test','Visit Saudi','Test fixture evidence, not a real observation.',kind=kind,subject_match=True,scope='specific_destination').validate()


def resolution(identifier):
    return {'destination_id':identifier,'status':'resolved','verified_name':'Test attraction','association_scope':'specific_destination',
            'match_basis':'Explicit mocked geographic evidence','sources':[source()]}


def provider(results=None,error=None):
    result=Mock(name='provider');result.name='mock';result.cache_identity='mock-v1'
    result.search.return_value=results or []
    if error:result.search.side_effect=error
    return result


def test_found_and_cache_preserve_prior_records():
    with PhotoStore(':memory:') as store:
        identifier=setup(store);before=[dict(r) for r in store.connection.execute('SELECT * FROM photos')]
        external=provider([source('promotional_coverage')])
        result=research_destination(store,identifier,external,resolution(identifier))
        assert result['research_status']=='coverage_found' and result['promotional_gap_claim'] is None
        assert external.search.call_count==2
        cached=research_destination(store,identifier,external,resolution(identifier))
        assert cached['cached'] and external.search.call_count==2
        assert before==[dict(r) for r in store.connection.execute('SELECT * FROM photos')]
        assert not store.connection.execute('PRAGMA foreign_key_check').fetchall()


@pytest.mark.parametrize('error,status',[(ResearchUnavailable('No credential'),'research_unavailable'),(ResearchFailed('Timeout'),'research_failed')])
def test_missing_access_not_empty_search_and_failures_retry(error,status):
    with PhotoStore(':memory:') as store:
        identifier=setup(store);external=provider(error=error)
        result=research_destination(store,identifier,external,resolution(identifier))
        assert result['research_status']==status
        research_destination(store,identifier,external,resolution(identifier))
        assert external.search.call_count==4


def test_empty_search_is_scoped_and_not_underpromotion():
    with PhotoStore(':memory:') as store:
        identifier=setup(store)
        result=research_destination(store,identifier,provider(),resolution(identifier))
        assert result['research_status']=='no_coverage_found_within_searched_sources'
        assert result['promotional_gap_claim'] is None
        assert any('absence' in text for text in result['limitations'])


def test_unreviewed_search_hit_is_insufficient():
    with PhotoStore(':memory:') as store:
        identifier=setup(store)
        result=research_destination(store,identifier,provider([source('unclassified_search_result')]),resolution(identifier))
        assert result['research_status']=='insufficient_evidence'


def test_unresolved_name_prevents_attributing_promotional_results():
    with PhotoStore(':memory:') as store:
        identifier=setup(store);external=provider([source('promotional_coverage')])
        result=research_destination(store,identifier,external,{'status':'unresolved','verified_name':None})
        assert result['identity_status']=='unresolved' and result['research_status']=='insufficient_evidence'
        external.search.assert_not_called()


def test_neutral_ids_and_false_official_hosts_cannot_verify_names():
    with PhotoStore(':memory:') as store:
        identifier=setup(store);r=resolution(identifier);r['verified_name']='Unidentified destination area'
        with pytest.raises(ValueError):research_destination(store,identifier,provider(),r)
        r=resolution(identifier);r['sources'][0]['url']='https://visitsaudi.com.evil.example/page'
        with pytest.raises(ValueError):research_destination(store,identifier,provider(),r)


def test_brave_uses_legitimate_api_and_does_not_log_secrets():
    session=Mock();response=Mock(status_code=200)
    response.json.return_value={'web':{'results':[{'title':'A result','url':'https://example.org/page','description':'Search description'}]}}
    session.get.return_value=response
    api=BraveSearch('test-only-key',session=session)
    result=api.search('tourism')
    assert result[0]['kind']=='unclassified_search_result'
    args=session.get.call_args
    assert args.args[0]=='https://api.search.brave.com/res/v1/web/search'
    assert args.kwargs['headers']['X-Subscription-Token']=='test-only-key'
    assert 'api_key' not in args.kwargs['params']
    with pytest.raises(ResearchUnavailable):BraveSearch().search('query')


def test_recorded_file_requires_real_provenance_and_exact_query(tmp_path):
    path=tmp_path/'evidence.json';path.write_text(json.dumps({'recorded_at':'2026-10-30T12:00:00+00:00','provenance':'Explicit mock test fixture','queries':{'q':{'status':'ok','results':[source('promotional_coverage')]}}}))
    external=EvidenceFileSearch(path)
    assert len(external.search('q'))==1
    with pytest.raises(ResearchUnavailable):external.search('never-recorded')
    assert external.search('q')[0]['observed_at']=='2026-10-30T12:00:00+00:00'


def test_candidate_limit_and_unknown_id_are_validated():
    with PhotoStore(':memory:') as store:
        identifier=setup(store)
        assert len(select_candidates(store)[1])==1
        with pytest.raises(ValueError):select_candidates(store,6)
        with pytest.raises(ValueError):select_candidates(store,5,['invented'])


@pytest.mark.parametrize('url',['http://example.org','https://127.0.0.1/page','https://localhost/x','https://user:pass@example.org/x','https://example.org:99/x'])
def test_disallowed_source_urls(url):assert not public_url(url)
