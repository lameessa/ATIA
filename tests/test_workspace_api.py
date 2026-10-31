"""Campaign-first API validation; temporary data and mocked AI only."""
import json
import sqlite3
from unittest.mock import Mock
from fastapi.testclient import TestClient
from atia.api.dashboard import create_app
from atia.api.media import FlickrMedia
from atia.agents.runner import run_agent
from atia.models import normalize
from test_discovery import prepared,autonomous_client
from test_dashboard_api import dataset,HEADERS
from display_fixtures import flickr_status


def test_workspace_empty_campaigns_and_real_discovery_activity_are_read_only(dataset):
    path,_=dataset
    runner=Mock(side_effect=AssertionError('No paid requests permitted'))
    with TestClient(create_app(path,runner)) as client:
        before=sqlite3.connect(path).execute('select count(*) from photos').fetchone()[0]
        value=client.get('/api/workspace').json()
        assert len(value['campaigns'])==1 and value['campaigns'][0]['kind']=='legacy_proposal'
        assert value['campaigns'][0]['media']==[]
        assert value['agent_status']=='awaiting_approval' and len(value['activity'])==1
        assert value['areas'][0]['hidden_gem_candidate'] is False
        assert 'raw' not in value and 'tools' not in value['activity'][0]
        assert sqlite3.connect(path).execute('select count(*) from photos').fetchone()[0]==before
    runner.assert_not_called()


def campaign_database(prepared,rights=True):
    s,_,_=prepared()
    with s:
        result=run_agent(s,client=autonomous_client());assert result['campaign_id']
        # A licence that stops qualifying after drafting removes the image and blocks approval.
        if not rights:flickr_status(s.connection,'afaq_historical','1001','0')
        path=s.connection.execute('PRAGMA database_list').fetchone()[2]
    return path,result['campaign_id']


def test_complete_campaign_review_requires_confirmation_and_preserves_original(prepared):
    path,campaign=campaign_database(prepared)
    with TestClient(create_app(path)) as client:
        c=client.get('/api/workspace').json()['campaigns'][0]
        assert c['kind']=='campaign' and c['status']=='PENDING_APPROVAL'
        assert len(c['media'])==1 and c['media'][0]['association_status']=='reviewed_entity_mapping'
        assert len(c['sources'])>=2 and not c['media_validation_required']
        body={'decision':'APPROVED','confirmed':True,'reviewer':'Human test reviewer'}
        url=f'/api/campaigns/{campaign}/review'
        assert client.post(url,json=body).status_code==403
        assert client.post(url,json=body,headers={**HEADERS,'Origin':'https://untrusted.example'}).status_code==403
        assert client.post(url,json={**body,'confirmed':False},headers=HEADERS).status_code==422
        first=client.post(url,json=body,headers=HEADERS);assert first.status_code==200
        assert client.post(url,json=body,headers=HEADERS).json()==first.json()
        assert client.post(url,json={**body,'decision':'REJECTED'},headers=HEADERS).status_code==409
        assert client.get('/api/workspace').json()['campaigns'][0]['status']=='APPROVED'
    db=sqlite3.connect(path)
    assert db.execute('select status from agent_campaigns').fetchone()[0]=='PENDING_APPROVAL'
    assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
    assert db.execute('pragma foreign_key_check').fetchall()==[]


def test_campaign_rights_missing_blocks_approval_but_allows_rejection(prepared):
    path,campaign=campaign_database(prepared,rights=False)
    with TestClient(create_app(path)) as client:
        c=client.get('/api/workspace').json()['campaigns'][0]
        assert c['media']==[] and c['media_validation_required']
        url=f'/api/campaigns/{campaign}/review';body={'decision':'APPROVED','confirmed':True}
        assert client.post(url,json=body,headers=HEADERS).status_code==409
        assert client.post(url,json={**body,'decision':'REJECTED'},headers=HEADERS).status_code==200


def test_changed_campaign_snapshot_cannot_be_reviewed_or_shown(prepared):
    path,campaign=campaign_database(prepared)
    db=sqlite3.connect(path)
    with db:db.execute("UPDATE visual_analyses SET image_sha256='changed'")
    db.close()
    with TestClient(create_app(path)) as client:
        assert client.get('/api/workspace').json()['campaigns']==[]
        assert client.post(f'/api/campaigns/{campaign}/review',headers=HEADERS,json={'decision':'APPROVED','confirmed':True}).status_code==409


def test_quarantined_live_media_cannot_appear_even_with_cached_image(prepared):
    s,_,_=prepared()
    with s:
        s.save(normalize({'id':'999999','title':'Quarantined test photograph','latitude':24.7,'longitude':46.7},'flickr_live'))
        db=s.connection
        assert FlickrMedia(db).asset('flickr_live','999999') is None
        path=db.execute('pragma database_list').fetchone()[2]
    with TestClient(create_app(path)) as client:
        assert '999999' not in client.get('/api/workspace').text
        assert client.get('/api/images/flickr_live/999999').status_code==404


def test_reviewed_archive_image_keeps_provisional_association_explicit(prepared):
    s,_,_=prepared(mapped=False)
    with s:
        asset=FlickrMedia(s.connection).asset('afaq_historical','1001')
        assert asset and asset['approval_status']=='APPROVED'
        assert asset['rights_status']=='reusable_with_attribution'
        assert asset['usage_scope']=='internal_reference_only'
        assert asset['association_status']=='geographic_context_only'
        path=s.connection.execute('pragma database_list').fetchone()[2]
    with TestClient(create_app(path)) as client:
        area=next(a for a in client.get('/api/workspace').json()['areas'] if a['entities'])
        assert area['media'] is None and len(area['context_media'])==1
