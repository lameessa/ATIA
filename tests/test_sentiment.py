import hashlib
import json
from unittest.mock import Mock
import pytest
pytest.importorskip('langid')
from atia.models import normalize
from atia.storage.sqlite import PhotoStore
from atia.sentiment.storage import CommentStore
from atia.sentiment.text import clean_comment,LanguageDetector
from atia.sentiment.comments import extract_comments,retrieve_comments
from atia.sentiment.pipeline import run_sentiment,aggregate,analysis_key
from atia.sentiment.model import MODEL_REVISION
from atia.collectors.flickr import FlickrError


def photo(store,photo_id='1'):
    p=normalize({'id':photo_id,'historical_region':'North'},'afaq_historical');store.save(p);return p.to_dict()


def test_cleaning_language_and_nonlinguistic_content():
    assert clean_comment('<b>Great</b><br>photo &amp; view<script>bad()</script>')=='Great photo & view'
    detector=LanguageDetector()
    assert detector.detect('صورة جميلة جدا، أحببت هذا المنظر')['language']=='ar'
    assert detector.detect('What a beautiful landscape and photograph!')['language']=='en'
    assert detector.detect('Bonjour tout le monde')['status']=='unsupported_language'
    assert detector.detect('صورة beautiful')['language']=='mixed'
    assert detector.detect('😀')['status']=='empty_or_nonlinguistic'
    assert detector.detect('Hi')['status']=='language_uncertain'


def test_comment_provenance_duplicates_and_edits(tmp_path):
    with PhotoStore(tmp_path/'comments.sqlite3') as store:
        p=photo(store);comments=CommentStore(store)
        raw={'id':'c1','_content':'Great photo','datecreate':'1700000000','author_is_deleted':'1'}
        assert comments.ingest(p,[raw],'afaq_historical')['inserted']==1
        assert comments.ingest(p,[raw],'flickr_live')['duplicates']==1
        assert len(comments.evidence(p))==1
        assert comments.ingest(p,[{**raw,'_content':'Edited text'}],'flickr_live')['inserted']==1
        assert comments.evidence(p)[0]['raw_text']=='Edited text'
        assert comments.db.execute('SELECT COUNT(*) FROM comment_versions').fetchone()[0]==2
        assert comments.ingest(p,[{},None],'flickr_live')['malformed']==2


def test_empty_and_failed_retrieval_does_not_mean_neutral_or_deleted(tmp_path):
    with PhotoStore(tmp_path/'comments.sqlite3') as store:
        p=photo(store);comments=CommentStore(store);client=Mock()
        client.call.return_value={'comments':{'photo_id':'1'}}
        result=retrieve_comments(client,comments,p)
        assert result['accessible'] and result['count']==0
        assert retrieve_comments(client,comments,p)['cached']
        client.call.side_effect=FlickrError('Temporary issue',code='105')
        assert not retrieve_comments(client,comments,p,refresh=True)['accessible']
        assert comments.db.execute('SELECT COUNT(*) FROM comment_sentiments').fetchone()[0]==0
        assert extract_comments({'comments':{'comment':{'id':'one'}}})==[{'id':'one'}]


def test_pipeline_batches_caches_and_aggregates_without_engagement(tmp_path):
    with PhotoStore(tmp_path/'pipeline.sqlite3') as store:
        p=photo(store);client=Mock()
        client.call.return_value={'comments':{'comment':[{'id':'1','_content':'Wonderful photograph!'},
                                                        {'id':'2','_content':'منظر رائع وجميل جدا'},
                                                        {'id':'3','_content':''}]}}
        detector=Mock()
        detector.detect.side_effect=lambda text: {'language':'ar' if 'منظر' in text else 'en' if text else 'und','confidence':.99 if text else None,'status':'ready' if text else 'empty_or_nonlinguistic'}
        model=Mock(runtime={'test':True})
        model.predict.side_effect=lambda texts:[{'label':'positive','confidence':.8,'scores':{'positive':.8,'negative':.1,'neutral':.1},'truncated':False} for text in texts]
        before=[dict(r) for r in store.connection.execute('SELECT * FROM photos')]
        report=run_sentiment(store,client,limit=1,batch_size=2,historical_path=None,model_factory=lambda:model,detector_factory=lambda:detector)
        assert report['comments_analyzed_total']==2 and report['newly_skipped']==1
        assert report['analyzed_language_distribution']=={'ar':1,'en':1}
        assert report['aggregates']['per_photo'][0]['sentiment_distribution']=={'positive':2}
        fail=Mock(side_effect=AssertionError('Must not load cached model'))
        cached=run_sentiment(store,client,limit=1,historical_path=None,model_factory=fail,detector_factory=fail)
        assert cached['cached_comments']==3 and cached['newly_analyzed']==0
        assert client.call.call_count==1
        assert [dict(r) for r in store.connection.execute('SELECT * FROM photos')]==before
        fail.assert_not_called()
        comments=CommentStore(store)
        store.connection.execute("INSERT INTO sentiment_destinations VALUES('place','Reviewed destination')")
        store.connection.execute("INSERT INTO sentiment_photo_destinations VALUES('afaq_historical','1','place')");store.connection.commit()
        grouped=aggregate(comments,[p],analysis_key(MODEL_REVISION))
        assert grouped['per_destination'][0]['analyzed_comments']==2
        assert 'views' not in json.dumps(grouped) and 'favorites' not in json.dumps(grouped)


def test_cache_keys_change_for_content_and_model_revision(tmp_path):
    with PhotoStore(tmp_path/'cache.sqlite3') as store:
        p=photo(store);comments=CommentStore(store)
        comments.ingest(p,[{'id':'c1','_content':'First text'}],'flickr_live')
        first=comments.evidence(p)[0];key=analysis_key(MODEL_REVISION)
        language={'language':'und','confidence':None,'status':'language_uncertain'}
        comments.save(first,key,language,MODEL_REVISION)
        assert comments.cached(first,key)
        assert comments.cached(first,analysis_key('a'*40)) is None
        comments.ingest(p,[{'id':'c1','_content':'New text'}],'flickr_live')
        assert comments.cached(comments.evidence(p)[0],key) is None


def test_historical_import_preserves_failed_and_empty_responses(tmp_path):
    from atia.sentiment.comments import import_afaq_comments
    path=tmp_path/'Afaq_RawData.json'
    path.write_text(json.dumps({'North':{
        '1':{'comments':{'stat':'ok','comments':{'comment':[{'id':'c1','_content':'Great photo'}]}}},
        '2':{'comments':{'stat':'ok','comments':{}}},
        '3':{'comments':{'stat':'fail','code':1,'message':'Unavailable'}}}}))
    with PhotoStore(tmp_path/'history.sqlite3') as store:
        for photo_id in ('1','2','3'):photo(store,photo_id)
        comments=CommentStore(store)
        first=import_afaq_comments(path,comments)
        assert first['comments_inserted']==1 and first['failed_responses']==1
        assert import_afaq_comments(path,comments)['photos']==0
        assert comments.db.execute('SELECT COUNT(*) FROM comment_fetches').fetchone()[0]==3
        statuses=dict(comments.db.execute('SELECT photo_id,status FROM comment_fetches'))
        assert statuses=={'1':'ok','2':'empty','3':'unavailable'}
        assert comments.ingest({'source':'afaq_historical','photo_id':'1'},[{'id':None,'_content':'text'}],'flickr_live')['malformed']==1
