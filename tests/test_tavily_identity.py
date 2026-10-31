import json
from unittest.mock import Mock
import pytest
from atia.models import normalize
from atia.storage.sqlite import PhotoStore
from atia.destinations.pipeline import build_destinations
from atia.research.providers import Source,ResearchUnavailable,ResearchFailed
from atia.research.tavily import TavilySearch
from atia.research.identity import verify_sources,supports_parent,research_locations


def response(status=200,body=None):
    r=Mock(status_code=status,headers={})
    r.json.return_value=body or {'request_id':'request-test','results':[{'title':'Al Masmak Palace','url':'https://saudipedia.com/en/al-masmak-palace','content':'Al Masmak Palace is a museum in the city of Riyadh and welcomes visitors.'}]}
    return r


def test_live_http_auth_cache_and_credentials_never_persist(tmp_path):
    with PhotoStore(tmp_path/'api.sqlite3') as store:
        session=Mock();session.post.return_value=response()
        provider=TavilySearch(store,'test-private-key',session=session)
        first=provider.search('Masmak',domains=['saudipedia.com'])
        assert provider.network_calls==1 and first[0]['access']=='tavily_search_content'
        call=session.post.call_args
        assert call.args[0]=='https://api.tavily.com/search'
        assert call.kwargs['headers']['Authorization']=='Bearer test-private-key'
        assert call.kwargs['json']['include_answer'] is False
        assert 'api_key' not in call.kwargs['json'] and call.kwargs['allow_redirects'] is False
        assert provider.search('Masmak',domains=['saudipedia.com'])==first
        assert provider.cache_hits==1 and session.post.call_count==1
        assert 'test-private-key' not in '\n'.join(store.connection.iterdump())
        offline=TavilySearch(store,session=Mock())
        assert offline.search('Masmak',domains=['saudipedia.com'])==first
        assert offline.network_calls==0


@pytest.mark.parametrize('status,error',[(401,ResearchUnavailable),(402,ResearchUnavailable),(403,ResearchUnavailable),(400,ResearchFailed)])
def test_api_failures_have_safe_messages(status,error):
    with PhotoStore(':memory:') as store:
        session=Mock();session.post.return_value=response(status)
        with pytest.raises(error) as caught:TavilySearch(store,'test-private-key',session=session).search('q')
        assert 'test-private-key' not in str(caught.value)
        assert store.connection.execute('SELECT COUNT(*) FROM tavily_search_observations').fetchone()[0]==0


def test_missing_key_rate_limits_and_malformed_response():
    with PhotoStore(':memory:') as store:
        with pytest.raises(ResearchUnavailable):TavilySearch(store).search('q')
        session=Mock();session.post.side_effect=[response(429),response()]
        provider=TavilySearch(store,'test',session=session,pause=lambda _:None)
        assert provider.search('q') and provider.network_calls==2
        session=Mock();session.post.return_value=response(body={'results':None})
        with pytest.raises(ResearchFailed):TavilySearch(store,'test',session=session).search('bad-query')


def option(name='Maraya'):
    return {'name':name,'aliases':[name],'entity_type':'attraction','parent':{'name':'AlUla','aliases':['AlUla'],'entity_type':'destination'}}


def source(name='Maraya',url='https://www.experiencealula.com/en/places-to-go/maraya',access='tavily_search_content'):
    return Source(name+' Tour',url,'Experience AlUla',name+' is a visitor attraction located in AlUla with guided tours and a mirrored hall.',access=access).validate()


def test_identity_requires_actual_authority_title_content_and_type():
    assert verify_sources(option(),[source()])
    assert not verify_sources(option(),[source(url='https://experiencealula.com.evil.example/page')])
    assert not verify_sources(option(),[source(access='search_index_excerpt')])
    navigation=source();navigation['title']='General travel navigation'
    assert not verify_sources(option(),[navigation])
    tiny=source();tiny['evidence']='Maraya'
    assert not verify_sources(option(),[tiny])
    assert supports_parent(option(),source())
    irrelevant=source();irrelevant['title']='Maraya';irrelevant['evidence']='AlUla navigation links and unrelated promotional references only.'
    assert not supports_parent(option(),irrelevant)


def fake_store():
    store=PhotoStore(':memory:')
    raw={'id':'1','latitude':24.7,'longitude':46.7,'accuracy':16,'country_verification':{'_content':'Saudi Arabia'}}
    store.save(normalize(raw,'afaq_historical'));report=build_destinations(store)
    return store,report['destinations'][0]['destination_id']


def fake_provider():
    provider=Mock();provider.name='tavily_live_api_v1';provider.cache_identity='test-tavily';provider.network_calls=0;provider.cache_hits=0;provider.observations=[]
    def search(query,domains=None):
        if query.startswith('AlUla'):return [Source('AlUla Destination','https://www.experiencealula.com/en','Experience AlUla','AlUla is a tourism destination and city with many visitor attractions and natural landscapes.',access='tavily_search_content').validate()]
        name='Other Venue' if query.startswith('Other Venue') else 'Maraya'
        return [source(name)]
    provider.search.side_effect=search
    return provider


def test_verified_entity_parent_provisional_cluster_and_cached_terminal_workflow():
    store,cluster_id=fake_store()
    with store:
        before=[dict(row) for row in store.connection.execute('SELECT * FROM photos')]
        provider=fake_provider();plan={'locations':[{'cluster_id':cluster_id,'association_notes':'Unverified metadata hint','options':[option()]}]}
        report=research_locations(store,provider,plan,limit=3)
        row=report['locations'][0]
        assert row['entities'][0]['verified_name']=='Maraya'
        assert row['entities'][0]['entity_type']=='attraction'
        assert row['entities'][0]['parent_name']=='AlUla'
        assert row['entities'][0]['parent_status']=='source_supported'
        assert row['confirmed_cluster_name'] is None
        assert row['association_status']=='provisional_metadata_match_not_authoritatively_mapped'
        assert row['research_status']=='coverage_found'
        count=provider.search.call_count
        replay=research_locations(store,provider,plan,limit=3)
        assert replay['assessment_cache_hits']==1 and provider.search.call_count==count
        assert before==[dict(row) for row in store.connection.execute('SELECT * FROM photos')]
        assert not store.connection.execute('PRAGMA foreign_key_check').fetchall()


def test_nearby_distinct_attractions_stay_distinct_and_cluster_unresolved():
    store,cluster_id=fake_store()
    with store:
        provider=fake_provider();plan={'locations':[{'cluster_id':cluster_id,'association_notes':'Mixed attraction titles','options':[option(),option('Other Venue')]}]}
        report=research_locations(store,provider,plan,limit=3)
        row=report['locations'][0]
        assert len(row['entities'])==2
        assert len({e['entity_id'] for e in row['entities']})==2
        assert row['association_status']=='unresolved_multiple_attractions'
        assert row['research_status']=='insufficient_evidence'
        assert row['confirmed_cluster_name'] is None


def test_no_live_authority_evidence_does_not_verify_a_hint():
    store,cluster_id=fake_store()
    with store:
        provider=fake_provider();provider.search.side_effect=lambda query,domains=None:[]
        plan={'locations':[{'cluster_id':cluster_id,'association_notes':'Flickr title only','options':[option()]}]}
        row=research_locations(store,provider,plan,limit=3)['locations'][0]
        assert row['entities']==[] and row['confirmed_cluster_name'] is None
        assert row['association_status']=='unresolved_no_authoritative_entity_confirmation'
        assert store.connection.execute('SELECT COUNT(*) FROM verified_location_entities').fetchone()[0]==0


def test_type_markers_are_words_not_comfort_substrings():
    candidate={'name':'Example','aliases':['Example'],'entity_type':'attraction'}
    data=source('Example');data['title']='Example';data['evidence']='This is a comfortable subject discussed without any classification in this returned content.'
    assert verify_sources(candidate,[data])==[]
