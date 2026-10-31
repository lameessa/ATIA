import hashlib
import json
from unittest.mock import Mock
import pytest
np=pytest.importorskip('numpy')
Image=pytest.importorskip('PIL.Image')
from atia.models import normalize
from atia.storage.sqlite import PhotoStore
from atia.vision.dimensions import fingerprint
from atia.vision.screen_storage import ScreeningStore
from atia.vision.screen_pipeline import screen_sample
from atia.vision.relevance_prompts import text_catalog,screen_decision,detail_decision,POLICY_VERSION
from atia.vision.relevance_review import import_labels,evaluate_rows


def screen_flat(positive=0.1,negative=0.1):
    return {key:(positive if key.startswith('screen/destination/') else negative)
            for key in text_catalog() if key.startswith('screen/')}


def test_relevance_uses_strength_and_positive_negative_margin():
    assert screen_decision(screen_flat(.4,.1))['destination_status']=='eligible'
    assert screen_decision(screen_flat(.1,.4))['destination_status']=='excluded'
    assert screen_decision(screen_flat(.2,.1))['decision']=='uncertain'
    assert screen_decision(screen_flat(.4,.39))['destination_status']=='needs_review'


def test_invalid_scores_cannot_be_saved_as_uncertain():
    values=screen_flat();values[next(iter(values))]=float('nan')
    with pytest.raises(ValueError):screen_decision(values)


def test_details_compare_alternatives_and_allow_multiple_elements():
    flat={key:.1 for key in text_catalog() if not key.startswith('screen/')}
    for key in flat:
        if key.startswith('environment/urban/') or key.startswith('elements/trees/positive/') or key.startswith('elements/people/positive/') or key.startswith('conditions/daytime/'):
            flat[key]=.5
    result=detail_decision(flat)
    assert result['environment']['label']=='urban'
    assert set(result['elements']['possible_matches'])=={'trees','people'}
    assert result['conditions']['lighting_label']=='daytime'
    flat['controls/scene/0']=.6
    assert detail_decision(flat)['environment']['label'] is None


def sample_store(tmp_path):
    store=PhotoStore(tmp_path/'test.sqlite3');screening=ScreeningStore(store)
    store.connection.execute("INSERT INTO review_samples VALUES('sample','seed','{}','now')")
    for index in range(3):
        record=normalize({'id':str(index+1),'datetaken':'2020-01-01 12:00:00'},'flickr_live');store.save(record)
        path=tmp_path/f'{index}.jpg';Image.new('RGB',(240,240),(index*80,50,80)).save(path)
        sha=hashlib.sha256(path.read_bytes()).hexdigest()
        store.connection.execute('INSERT INTO review_sample_members VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            ('sample','flickr_live',str(index+1),'North','test','regional',sha,str(path),'https://live.staticflickr.com/test.jpg',240,240,'available',None,index))
    store.connection.commit();return store


def mock_model():
    model=Mock()
    model.encode_images.side_effect=lambda images:np.eye(512,dtype='float32')[:len(images)]
    def compare(vectors,stage):
        if stage=='screen':return [screen_flat(.1,.4),screen_flat(.2,.2),screen_flat(.4,.1)][:len(vectors)]
        return [{key:.1 for key in text_catalog() if not key.startswith('screen/')} for _ in vectors]
    model.compare.side_effect=compare
    return model


def test_gate_cache_and_embedding_reuse(tmp_path):
    with sample_store(tmp_path) as store:
        before=[dict(r) for r in store.connection.execute('SELECT * FROM photos')]
        model=mock_model();spec={'model_name':'test','pretrained':'test','libraries':{}}
        report=screen_sample(store,'sample',batch_size=3,analyzer_factory=lambda:model,progress=lambda _:None,spec=spec)
        assert report['complete'] and report['counts']=={'irrelevant':1,'uncertain':1,'relevant':1}
        assert model.compare.call_args_list[1].args[0].shape==(1,512)
        rows=list(store.connection.execute('SELECT decision,detail_result FROM tourism_relevance'))
        assert sum(r['detail_result'] is not None for r in rows)==1
        assert store.connection.execute('SELECT COUNT(*) FROM destination_dimension_analyses').fetchone()[0]==3
        assert [dict(r) for r in store.connection.execute('SELECT * FROM photos')]==before
        fail=Mock(side_effect=AssertionError('Must not load model'))
        cached=screen_sample(store,'sample',3,fail,lambda _:None,spec)
        assert cached['cached']==3 and cached['images_encoded']==0
        fail.assert_not_called()
        store.connection.execute('DELETE FROM destination_dimension_analyses')
        store.connection.execute('DELETE FROM tourism_relevance');store.connection.commit()
        model.encode_images.side_effect=AssertionError('Must reuse embeddings')
        reused=screen_sample(store,'sample',3,lambda:model,lambda _:None,spec)
        assert reused['embeddings_reused']==3 and reused['images_encoded']==0


def test_labels_require_exact_snapshot_and_preserve_reviewer(tmp_path):
    with sample_store(tmp_path) as store:
        member=ScreeningStore(store).members('sample')[0]
        label={'reviewer':'test-reviewer','review_type':'test_review','labels':[{'photo_id':member['photo_id'],'image_sha256':member['image_sha256'],'label':'uncertain','reason':'Insufficient context'}]}
        path=tmp_path/'labels.json';path.write_text(json.dumps(label))
        assert import_labels(store,'sample',path)['labels']==1
        label['labels'][0]['label']='relevant';path.write_text(json.dumps(label))
        with pytest.raises(ValueError,match='immutable'):import_labels(store,'sample',path)
        label['labels'][0]['image_sha256']='wrong';path.write_text(json.dumps(label))
        with pytest.raises(ValueError,match='checksum'):import_labels(store,'sample',path)


def test_evaluation_separates_abstentions_from_decisive_errors():
    rows=[{'photo_id':'1','region':'North','review_label':'relevant','decision':'uncertain'},
          {'photo_id':'2','region':'South','review_label':'irrelevant','decision':'relevant'}]
    result=evaluate_rows(rows)
    assert len(result['decisive_disagreements'])==len(result['abstentions_on_decisive_labels'])==1


def test_regional_sample_is_stable_and_replaces_only_unavailable_candidates(tmp_path):
    from atia.vision.review_sample import prepare_sample,REGIONS
    from atia.vision.images import ImageAsset,ImageUnavailable
    with PhotoStore(tmp_path/'selection.sqlite3') as store:
        for index,region in enumerate(REGIONS):
            live=normalize({'id':str(100+index)},'flickr_live');live.region=region;store.save(live)
            for offset in range(3):
                store.save(normalize({'id':str(1000+10*index+offset),'historical_region':region},'afaq_historical'))
        calls=[]
        def fetch(record):
            calls.append(record['photo_id'])
            if record['photo_id']=='100':raise ImageUnavailable('Unavailable; cause unknown')
            path=tmp_path/f"image-{record['photo_id']}.jpg"
            Image.new('RGB',(240,240),'blue').save(path)
            return ImageAsset(Image.new('RGB',(240,240),'blue'),'https://live.staticflickr.com/test.jpg',hashlib.sha256(path.read_bytes()).hexdigest(),str(path),240,240)
        fetcher=Mock();fetcher.fetch.side_effect=fetch
        result=prepare_sample(store,fetcher,include_audit=False,progress=lambda _:None)
        assert result['regions']=={region:3 for region in REGIONS}
        assert result['available']==15 and result['unavailable']==1
        count=len(calls)
        replay=prepare_sample(store,fetcher,include_audit=False,progress=lambda _:None)
        assert replay['sample_id']==result['sample_id'] and len(calls)==count
        assert store.counts()=={'flickr_live':5,'afaq_historical':15}
