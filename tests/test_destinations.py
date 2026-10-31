import json
import math
from pathlib import Path
import pytest
from atia.models import normalize
from atia.storage.sqlite import PhotoStore
from atia.destinations.geo import GeoPolicy,extract_geo,cluster,distance
from atia.destinations.pipeline import build_destinations
from atia.destinations.storage import DestinationStore


def add(store,photo_id,lat=24.7,lon=46.7,accuracy=16,locality_id=None,country='Saudi Arabia',source='flickr_live',views=None):
    raw={'id':str(photo_id),'latitude':lat,'longitude':lon,'accuracy':accuracy,'owner':'author-'+str(photo_id),
         'dateupload':'1700000000','datetaken':'2020-01-02 03:04:05','views':views,
         'location':{'accuracy':accuracy,'country':{'_content':country}}}
    if locality_id:raw['location']['locality']={'_content':'Reported city','woeid':locality_id}
    p=normalize(raw,source);store.save(p)
    return dict(store.connection.execute('SELECT * FROM photos WHERE source=? AND photo_id=?',(source,str(photo_id))).fetchone())


def test_complete_link_prevents_transitive_chains():
    with PhotoStore(':memory:') as store:
        points=[extract_geo(add(store,i,lon=46.7+offset),GeoPolicy()) for i,offset in enumerate((0,.008,.016))]
        assert distance(points[0],points[1])<1 and distance(points[1],points[2])<1
        assert distance(points[0],points[2])>1
        groups=cluster(points,GeoPolicy())
        assert len(groups)==2
        assert all(distance(a,b)<=1 for group in groups for a in group for b in group)


def test_metadata_conflicts_and_far_same_environment_do_not_merge():
    with PhotoStore(':memory:') as store:
        add(store,'1',locality_id='city-a');add(store,'2',lon=46.7001,locality_id='city-b')
        add(store,'3',lon=47.7)
        report=build_destinations(store)
        assert report['destination_groups']==3
        assert all(g['name']=='Unidentified destination area' for g in report['destinations'])


def test_missing_coarse_and_foreign_coordinates_unassigned():
    with PhotoStore(':memory:') as store:
        add(store,'1',lat=None,lon=None);add(store,'2',accuracy=7);add(store,'3',country='Bahrain')
        add(store,'4')
        report=build_destinations(store)
        assert report['assigned_photo_records']==1 and report['unassigned_photo_records']==3
        assert report['unassigned_reasons']=={'missing_or_invalid_coordinates':1,'coarse_geo_accuracy':1,'non_saudi_country_metadata':1}
        assert store.connection.execute('PRAGMA foreign_key_check').fetchall()==[]


def test_stable_ids_on_replay_and_new_earlier_photo(tmp_path):
    with PhotoStore(tmp_path/'stable.sqlite3') as store:
        add(store,'20');add(store,'30',lon=46.701)
        first=build_destinations(store)
        second=build_destinations(store)
        identifier=first['destinations'][0]['destination_id']
        assert second['destinations'][0]['destination_id']==identifier
        add(store,'1',lon=46.7005)
        third=build_destinations(store)
        assert third['destinations'][0]['destination_id']==identifier
        assert third['destinations'][0]['parent_destination_ids']==[identifier]
        assert DestinationStore(store).inspect(first['run_id'])['assigned_photo_records']==2
        assert DestinationStore(store).inspect(destination_id=identifier)['evidence']['photo_count']==3


def test_engagement_sources_dates_and_unevaluated_status_are_preserved():
    with PhotoStore(':memory:') as store:
        add(store,'1',views=10)
        raw={'id':'2','latitude':24.7,'longitude':46.7,'accuracy':16,'location':{'accuracy':16,'country':{'_content':'Saudi Arabia'}},
             'favorites':{'stat':'ok','photo':{'total':21,'person':[{'id':'one'}]}}}
        store.save(normalize(raw,'afaq_historical'))
        before=[dict(r) for r in store.connection.execute('SELECT * FROM photos')]
        report=build_destinations(store);e=report['destinations'][0]['evidence']
        assert e['photo_count']==2 and e['distinct_photographers']==1 and e['missing_photographer_photos']==1
        assert e['engagement']['views_sum_observed']==10 and e['engagement']['missing_views_photos']==1
        assert e['engagement']['favorites_sum_observed']==21
        assert e['relevance_coverage']=={'not_evaluated':2}
        assert e['sentiment']['classified_comments']==0 and e['sentiment']['distribution']=={}
        assert e['capture_dates']['timezone_unknown_photos']==1
        assert e['capture_dates']['minimum_as_recorded']!=e['upload_dates']['minimum_as_recorded']
        assert before==[dict(r) for r in store.connection.execute('SELECT * FROM photos')]


def test_identical_id_across_sources_deduplicates_metrics():
    with PhotoStore(':memory:') as store:
        add(store,'1',views=10);add(store,'1',source='afaq_historical',views=8)
        report=build_destinations(store);e=report['destinations'][0]['evidence']
        assert report['assigned_photo_records']==2 and report['assigned_unique_photo_ids']==1
        assert e['source_observation_count']==2 and e['photo_count']==1
        assert e['engagement']['views_sum_observed']==10


def test_conflicting_duplicate_location_versions_are_not_guessed():
    with PhotoStore(':memory:') as store:
        add(store,'1');add(store,'1',source='afaq_historical',lon=48)
        report=build_destinations(store)
        assert report['assigned_photo_records']==0
        assert report['unassigned_reasons']=={'conflicting_photo_location_versions':2}


def test_attraction_requires_explicit_reviewed_reference(tmp_path):
    with PhotoStore(':memory:') as store:
        add(store,'1')
        path=tmp_path/'places.json'
        path.write_text(json.dumps([{'source':'flickr_live','photo_id':'1','place_id':'reviewed-place','name':'Reviewed attraction',
                                   'level':'individual_attraction','verified':True,'reviewer':'test reviewer','evidence_url':'https://example.org/official-place'}]))
        report=build_destinations(store,places_path=path)
        group=report['destinations'][0]
        assert group['name']=='Reviewed attraction' and group['level']=='individual_attraction'
        assert group['name_reference']['evidence_url']=='https://example.org/official-place'


@pytest.mark.parametrize('value',[0,-1,float('nan'),float('inf'),51])
def test_invalid_distance_threshold(value):
    with pytest.raises(ValueError):GeoPolicy(distance_km=value)


def test_comment_sentiment_is_deduplicated_and_original_tables_unchanged(tmp_path):
    pytest.importorskip('langid')
    from atia.sentiment.storage import CommentStore
    from atia.sentiment.pipeline import analysis_key
    from atia.sentiment.model import MODEL_REVISION
    with PhotoStore(tmp_path/'evidence.sqlite3') as store:
        live=add(store,'1');history=add(store,'1',source='afaq_historical')
        comments=CommentStore(store)
        raw={'id':'comment','_content':'A wonderful photograph!'}
        comments.ingest(history,[raw],'afaq_historical');comments.ingest(live,[raw],'flickr_live')
        comment=comments.evidence(live)[0]
        comments.save(comment,analysis_key(MODEL_REVISION),{'language':'en','confidence':.99,'status':'ready'},MODEL_REVISION,
                      {'label':'positive','confidence':.8,'scores':{'positive':.8,'neutral':.1,'negative':.1}})
        before=[dict(r) for r in store.connection.execute('SELECT * FROM comment_sentiments')]
        report=build_destinations(store)
        sentiment=report['destinations'][0]['evidence']['sentiment']
        assert sentiment['observed_unique_comments']==1 and sentiment['classified_comments']==1
        assert sentiment['distribution']=={'positive':1}
        assert [dict(r) for r in store.connection.execute('SELECT * FROM comment_sentiments')]==before


def test_bad_date_metadata_does_not_crash_grouping():
    with PhotoStore(':memory:') as store:
        add(store,'1')
        store.connection.execute("UPDATE photos SET captured_at='invalid-date' WHERE photo_id='1'");store.connection.commit()
        report=build_destinations(store)
        assert report['destinations'][0]['evidence']['capture_dates']['invalid_photos']==1
