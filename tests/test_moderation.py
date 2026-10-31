"""Quarantine, independent decisions, removal, and no image egress in tests."""
from pathlib import Path
import hashlib
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from atia.storage.sqlite import PhotoStore
from atia.models import normalize,utc_now
from atia.destinations.pipeline import build_destinations
from atia.api.dashboard import create_app
from atia.moderation.policy import allowed,presentation_connection,clean_evidence,VERSION
from atia.moderation.actions import inspect_labels,review,retire_confident,summary,export_queue
from atia.agents.tools import context
from display_fixtures import approve


@pytest.fixture
def content(tmp_path):
    path=tmp_path/'moderation.sqlite3'
    with PhotoStore(path) as s:
        for ident,source,lat in [('historic','afaq_historical',24.7),('live','flickr_live',25.7)]:
            s.save(normalize({'id':ident,'title':'test image','latitude':lat,'longitude':46.7,'accuracy':16,
                'country_verification':{'_content':'Saudi Arabia'}},source))
        report=build_destinations(s)
        from PIL import Image
        image=tmp_path/'cached.img';Image.new('RGB',(100,100),'blue').save(image,format='JPEG')
        sha=hashlib.sha256(image.read_bytes()).hexdigest()
        e={'photo_id':'live','region':'Central','completed':True,'image_sha256':sha,'policy_version':VERSION,
            'relevance':'uncertain','relevance_explanation':'Mock local assessment','safety':{'status':'pass','model':'mock-local','scores':{'nsfw':.001}},'manual_approval':False}
        with s.connection:
            s.connection.execute('UPDATE photo_moderation SET safety=?,evaluation_json=? WHERE photo_id=?',('pass',json.dumps(e),'live'))
            s.connection.execute('INSERT INTO moderation_asset_cache VALUES(?,?,?,?)',('live',sha,str(image),'https://live.staticflickr.com/test.jpg'))
        yield s,path,sha,image,report


def inspection(sha,relevance='relevant',safety='pass',confidence='clear'):
    return {'photo_id':'live','image_sha256':sha,'relevance':relevance,'safety':safety,'confidence':confidence,
            'reason':'Test-only visual content inspection, no production label.','reviewer':'Test inspector','inspection_type':'assistant_visual_inspection_not_user_approval'}


def import_one(s,tmp_path,item):
    path=tmp_path/'labels.json';path.write_text(json.dumps([item]));return inspect_labels(s,path)


def test_new_live_defaults_quarantined_and_fail_closed_when_no_moderation_table(content,tmp_path):
    s,path,sha,image,report=content
    assert not allowed(s.connection,'flickr_live','live') and allowed(s.connection,'afaq_historical','historic')
    with TestClient(create_app(path)) as client:
        assert client.get('/photos?source=flickr_live').json()=={'photos':[]}
        assert client.get('/api/overview').json()['photo_count']==1
        assert client.get('/api/images/flickr_live/live').status_code==404
        areas=client.get('/api/destinations').json()['areas'];assert len(areas)==1
        assert client.get('/api/destinations/'+areas[0]['cluster_id']).json()['photos'][0]['source']=='afaq_historical'
    assert s.connection.execute('SELECT count(*) FROM photos').fetchone()[0]==2


def test_two_pass_dimensions_never_auto_approve_and_explicit_user_action_required(content,tmp_path):
    s,_,sha,_,_=content
    import_one(s,tmp_path,inspection(sha))
    assert summary(s)['awaiting_approval']==1 and summary(s)['approved']==0
    assert not allowed(s.connection,'flickr_live','live')
    with pytest.raises(ValueError):review(s,'live',True,'Tester','Checked',confirm=False)
    review(s,'live',True,'User test reviewer','I reviewed this exact image for tourism and professional safety.',confirm=True)
    assert allowed(s.connection,'flickr_live','live') and summary(s)['approved']==1


def test_ambiguous_classification_cannot_be_approved_or_permanently_removed(content,tmp_path):
    s,_,sha,image,_=content
    import_one(s,tmp_path,inspection(sha,'uncertain','uncertain','uncertain'))
    with pytest.raises(ValueError):review(s,'live',True,'Tester','Review',True)
    assert retire_confident(s,tmp_path)['removed']==0 and image.exists()
    assert s.contains('flickr_live','live')


def test_confident_removal_minimal_tombstone_cache_cleanup_and_recollection_prevention(content,tmp_path):
    s,_,sha,image,_=content
    before=dict(s.connection.execute("SELECT * FROM photos WHERE source='afaq_historical'").fetchone())
    import_one(s,tmp_path,inspection(sha,'irrelevant','unsafe'))
    retired=retire_confident(s,tmp_path)
    assert retired['removed']==1 and not image.exists()
    assert not s.contains('flickr_live','live') and s.contains_any('live')
    assert [r[1] for r in s.connection.execute('PRAGMA table_info(photo_removal_audit)')]==['photo_id','reason','removed_at']
    assert not s.save(normalize({'id':'live'},'flickr_live'))
    assert dict(s.connection.execute("SELECT * FROM photos WHERE source='afaq_historical'").fetchone())==before
    assert s.connection.execute("SELECT count(*) FROM destination_photo_assignments WHERE source='flickr_live'").fetchone()[0]==0
    assert not s.connection.execute('PRAGMA foreign_key_check').fetchall()
    assert s.connection.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert summary(s)['evaluated_records']==1 and summary(s)['removed']==1


def test_agent_rejects_quarantine_only_cluster_and_hides_old_evidence(content):
    s,_,_,_,report=content
    cluster=next(g['destination_id'] for g in report['destinations'] if g['photo_ids']==['live'])
    with pytest.raises(ValueError,match='no approved'):context(s,cluster)
    assert not clean_evidence(s.connection,{'photo_id':'live','image_url':'https://live.staticflickr.com/live.jpg'})


def test_wrong_hash_and_missing_assets_cannot_be_released(content,tmp_path):
    s,_,sha,image,_=content
    with pytest.raises(ValueError,match='hash'):import_one(s,tmp_path,inspection('wrong-hash'))
    import_one(s,tmp_path,inspection(sha));image.unlink()
    with pytest.raises(OSError):review(s,'live',True,'User','Review',True)
    assert not allowed(s.connection,'flickr_live','live')


def test_private_queue_outside_frontend_and_no_uncertain_previews(content,tmp_path):
    s,_,sha,_,_=content
    q=export_queue(s,tmp_path/'private')
    assert q['candidates']==0 and '<img' not in Path(q['queue']).read_text()
    import_one(s,tmp_path,inspection(sha));q=export_queue(s,tmp_path/'private')
    assert q['candidates']==1 and summary(s)['approved']==0


def test_approved_delivery_uses_exact_reviewed_pixels_and_rejects_replacement(content,tmp_path):
    s,path,sha,image,_=content
    import_one(s,tmp_path,inspection(sha));review(s,'live',True,'User test','Reviewed this exact photograph',True)
    with TestClient(create_app(path)) as client:
        # Moderation approval clears evidence use only; display needs its own image review.
        assert client.get('/api/images/flickr_live/live').status_code==404
    approve(s.connection,'flickr_live','live')
    with TestClient(create_app(path)) as client:
        response=client.get('/api/images/flickr_live/live');assert response.status_code==200
        assert hashlib.sha256(response.content).hexdigest()==sha and response.headers['cache-control']=='no-store'
        assert client.get('/photos?source=flickr_live').json()['photos'][0]['photo_url']=='/api/images/flickr_live/live'
        image.write_bytes(b'unapproved replacement')
        assert client.get('/api/images/flickr_live/live').status_code==404


def test_explicit_rejection_persists_and_queue_removes_stale_preview(content,tmp_path):
    s,path,sha,_,_=content
    import_one(s,tmp_path,inspection(sha))
    queue=tmp_path/'private';export_queue(s,queue)
    assert (queue/'live.jpg').exists()
    decision=review(s,'live',False,'User','Reject this shortlist image',True)
    assert decision['status']=='REJECTED'
    row=s.connection.execute('SELECT status,review_status FROM photo_moderation WHERE photo_id=?',('live',)).fetchone()
    assert row['review_status']=='REJECTED' and not allowed(s.connection,'flickr_live','live')
    updated=export_queue(s,queue)
    assert updated['candidates']==0 and not (queue/'live.jpg').exists()
    assert 'live.jpg' not in (queue/'index.html').read_text()
    assert summary(s)['regions']['Central']['candidates']==0 and summary(s)['rejected']==1
    with pytest.raises(ValueError,match='rejection'):review(s,'live',True,'User','Automatic retry',True)
    with pytest.raises(ValueError,match='override'):import_one(s,tmp_path,inspection(sha))
    with TestClient(create_app(path)) as client:
        assert client.get('/api/images/flickr_live/live').status_code==404


def test_pending_replacement_does_not_change_other_review_decisions(content,tmp_path):
    s,path,sha,image,_=content
    import_one(s,tmp_path,inspection(sha));review(s,'live',False,'User','User rejection',True)
    original=dict(s.connection.execute('SELECT * FROM photo_moderation WHERE photo_id=?',('live',)).fetchone())
    s.save(normalize({'id':'replacement','latitude':24.8,'longitude':46.7},'flickr_live'))
    evaluation=json.loads(original['evaluation_json']);evaluation['photo_id']='replacement'
    with s.connection:
        s.connection.execute('UPDATE photo_moderation SET evaluation_json=?,safety=? WHERE photo_id=?',(json.dumps(evaluation),'pass','replacement'))
        s.connection.execute('INSERT INTO moderation_asset_cache VALUES(?,?,?,?)',('replacement',sha,str(image),'https://live.staticflickr.com/replacement.jpg'))
    item=inspection(sha);item['photo_id']='replacement'
    import_one(s,tmp_path,item)
    manifest=export_queue(s,tmp_path/'queue')
    selected=json.loads((tmp_path/'queue'/'manifest.json').read_text())
    assert selected[0]['photo_id']=='replacement' and selected[0]['status']=='PENDING_REVIEW'
    assert not allowed(s.connection,'flickr_live','replacement') and summary(s)['approved']==0
    assert dict(s.connection.execute('SELECT * FROM photo_moderation WHERE photo_id=?',('live',)).fetchone())==original
