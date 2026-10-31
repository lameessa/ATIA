"""Regression tests: no route to a photograph's pixels or image URL without the display gate."""
import json
import socket
import sqlite3
from unittest.mock import patch
from fastapi.testclient import TestClient
import pytest
from atia.api.dashboard import create_app
from atia.api.media import FlickrMedia, cached_photo
from atia.destinations.pipeline import build_destinations
from atia.intelligence.signals import build_signals
from atia.moderation.display import ATTESTATIONS, can_display, cached_file, display_block, review_image, review_queue
from atia.moderation.policy import allowed
from atia.storage.sqlite import PhotoStore
from display_fixtures import approve, flickr_status
from test_intelligence import Client, Fetcher, add, restore

ALL = dict.fromkeys(ATTESTATIONS, True)
GEO = {'accuracy': '16', 'region': {'_content': 'الرياض'}, 'country': {'_content': 'Saudi Arabia', 'woeid': 23424938}}


@pytest.fixture
def store(tmp_path):
    with PhotoStore(str(tmp_path / 'db.sqlite3')) as value:
        yield value


def restored(store, tmp_path, license_id='9'):
    add(store.connection, '1', 'Namar Valley', license_id=license_id)
    store.connection.commit()
    restore(store, tmp_path, Client({'1': license_id}))
    return store.connection


def sha(db):
    return cached_file(db, 'afaq_historical', '1')[1]


def test_restore_images_cannot_bypass_review(store, tmp_path):
    db = restored(store, tmp_path)
    assert cached_file(db, 'afaq_historical', '1')[0] is not None
    assert not can_display(db, 'afaq_historical', '1') and cached_photo(db, 'afaq_historical', '1') is None
    assert FlickrMedia(db).asset('afaq_historical', '1') is None and display_block(db, 'afaq_historical', '1') == 'not reviewed'


def test_archive_metadata_stays_evidence_without_display_permission(store, tmp_path):
    db = restored(store, tmp_path)
    assert allowed(db, 'afaq_historical', '1') is True and not can_display(db, 'afaq_historical', '1')


def test_collected_and_archive_photos_follow_the_same_rule(store):
    assert not can_display(store.connection, 'flickr_live', 'anything') and not can_display(store.connection, 'afaq_historical', 'anything')


def test_a_reviewer_name_alone_cannot_approve(store, tmp_path):
    db = restored(store, tmp_path)
    with pytest.raises(ValueError, match='confirm'):
        review_image(db, 'afaq_historical', '1', sha(db), 'APPROVED', 'Someone', 'Looks fine', {})
    assert not can_display(db, 'afaq_historical', '1')


def test_an_assistant_cannot_approve_and_a_forged_row_does_not_count(store, tmp_path):
    db = restored(store, tmp_path)
    with pytest.raises(ValueError, match='person'):
        review_image(db, 'afaq_historical', '1', sha(db), 'APPROVED', 'Assistant', 'Looks fine', ALL, reviewer_kind='assistant')
    with db:
        db.execute("INSERT INTO image_display_reviews(source,photo_id,image_sha256,decision,reviewer,reviewer_kind,attestations,reason,reviewed_at) VALUES('afaq_historical','1',?,'APPROVED','x','assistant',?,'r','now')", (sha(db), json.dumps(ALL)))
    assert display_block(db, 'afaq_historical', '1') == 'not reviewed by a person'


def test_missing_attestations_in_a_stored_row_block_display(store, tmp_path):
    db = restored(store, tmp_path)
    with db:
        db.execute("INSERT INTO image_display_reviews(source,photo_id,image_sha256,decision,reviewer,reviewer_kind,attestations,reason,reviewed_at) VALUES('afaq_historical','1',?,'APPROVED','x','human','{}','r','now')", (sha(db),))
    assert not can_display(db, 'afaq_historical', '1')


@pytest.mark.parametrize('license_id', ['0', '1', '7', '10', None])
def test_unlicensed_images_cannot_be_approved(store, tmp_path, license_id):
    db = restored(store, tmp_path, license_id or '0')
    flickr_status(db, 'afaq_historical', '1', license_id)
    with pytest.raises(ValueError, match='licence'):
        review_image(db, 'afaq_historical', '1', sha(db), 'APPROVED', 'Person', 'Looks fine', ALL)


def test_approval_binds_to_the_exact_image(store, tmp_path):
    db = restored(store, tmp_path)
    with pytest.raises(ValueError, match='hash'):
        review_image(db, 'afaq_historical', '1', 'f' * 64, 'APPROVED', 'Person', 'Looks fine', ALL)


@pytest.mark.parametrize('later', ['REJECTED', 'UNCERTAIN'])
def test_rejected_or_uncertain_after_approval_blocks_display(store, tmp_path, later):
    db = restored(store, tmp_path)
    approve(db, 'afaq_historical', '1', '9', keep_status=True)
    assert can_display(db, 'afaq_historical', '1')
    review_image(db, 'afaq_historical', '1', sha(db), later, 'Person', 'Second look')
    assert not can_display(db, 'afaq_historical', '1')


@pytest.mark.parametrize('change', [{'api_status': 'not_found'}, {'safety': '2'}, {'license_id': '0'}])
def test_later_flickr_changes_revoke_approval(store, tmp_path, change):
    db = restored(store, tmp_path)
    approve(db, 'afaq_historical', '1', '9', keep_status=True)
    flickr_status(db, 'afaq_historical', '1', **{'license_id': '9', **change})
    assert not can_display(db, 'afaq_historical', '1')


def test_uncertain_visual_label_blocks_an_approved_image(store, tmp_path):
    db = restored(store, tmp_path)
    approve(db, 'afaq_historical', '1', '9', keep_status=True)
    db.execute('CREATE TABLE visual_review_labels (source TEXT, photo_id TEXT, label TEXT, reviewed_at TEXT)')
    db.execute("INSERT INTO visual_review_labels VALUES('afaq_historical','1','uncertain','now')")
    assert not can_display(db, 'afaq_historical', '1')


def test_changed_bytes_after_approval_block_display(store, tmp_path):
    db = restored(store, tmp_path)
    approve(db, 'afaq_historical', '1', '9', keep_status=True)
    cached_file(db, 'afaq_historical', '1')[0].write_bytes(b'different')
    assert not can_display(db, 'afaq_historical', '1')


@pytest.mark.parametrize('table', ['photo_flickr_status', 'image_display_reviews'])
def test_fails_closed_when_safety_tables_are_missing(store, tmp_path, table):
    db = restored(store, tmp_path)
    approve(db, 'afaq_historical', '1', '9', keep_status=True)
    db.execute(f'DROP TABLE {table}')
    assert not can_display(db, 'afaq_historical', '1')


def test_fails_closed_on_database_errors(store, tmp_path):
    db = restored(store, tmp_path)
    approve(db, 'afaq_historical', '1', '9', keep_status=True)
    with db:
        db.execute("UPDATE image_display_reviews SET attestations='not json'")
    assert display_block(db, 'afaq_historical', '1') == 'safety could not be established'
    closed = sqlite3.connect(':memory:')
    closed.close()
    assert not can_display(closed, 'afaq_historical', '1')


def test_queue_lists_only_licensed_unreviewed_images_and_stops_after_review(store, tmp_path):
    db = restored(store, tmp_path)
    queue = review_queue(db)
    assert [q['photo_id'] for q in queue] == ['1'] and queue[0]['image_sha256'] == sha(db)
    review_image(db, 'afaq_historical', '1', sha(db), 'REJECTED', 'Person', 'No')
    assert review_queue(db) == []


def api_dataset(tmp_path, license_id='9'):
    path = tmp_path / 'db.sqlite3'
    with PhotoStore(str(path)) as value:
        add(value.connection, '1', 'Namar Valley', license_id=license_id, latitude=24.57, longitude=46.68, location=GEO)
        value.connection.commit()
        restore(value, tmp_path, Client({'1': license_id}))
        cluster = build_destinations(value)['destinations'][0]['destination_id']
        build_signals(value.connection)
    return path, cluster


def walk_strings(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_strings(item)
    elif isinstance(value, str):
        yield value


def exposed_image_urls(body):
    return [s for s in walk_strings(body) if 'staticflickr' in s or s.startswith('/api/images/') or s.startswith('data/images')]


def test_no_api_exposes_an_unreviewed_image_or_image_url(tmp_path):
    path, cluster = api_dataset(tmp_path)
    with TestClient(create_app(str(path))) as client:
        assert client.get('/api/images/afaq_historical/1').status_code == 404
        detail = client.get(f'/api/destinations/{cluster}').json()
        assert detail['photos'] and detail['photos'][0]['preview_url'] is None and detail['photos'][0]['title'] == 'Namar Valley'
        for route in (f'/api/destinations/{cluster}', '/api/workspace', '/api/intelligence', '/api/destinations', '/photos', '/api/overview'):
            response = client.get(route)
            assert response.status_code == 200, route
            assert exposed_image_urls(response.json()) == [], route


def test_destination_detail_offers_the_image_only_after_approval_and_only_locally(tmp_path):
    path, cluster = api_dataset(tmp_path)
    with PhotoStore(str(path)) as value:
        approve(value.connection, 'afaq_historical', '1', '9', keep_status=True)
    with TestClient(create_app(str(path))) as client:
        assert client.get(f'/api/destinations/{cluster}').json()['photos'][0]['preview_url'] == '/api/images/afaq_historical/1'
        assert client.get('/api/images/afaq_historical/1').status_code == 200
    with PhotoStore(str(path)) as value:
        review_image(value.connection, 'afaq_historical', '1', cached_file(value.connection, 'afaq_historical', '1')[1], 'REJECTED', 'Person', 'Second look')
    with TestClient(create_app(str(path))) as client:
        assert client.get('/api/images/afaq_historical/1').status_code == 404
        assert client.get(f'/api/destinations/{cluster}').json()['photos'][0]['preview_url'] is None


def test_metadata_evidence_counts_survive_when_nothing_can_be_displayed(tmp_path):
    path, cluster = api_dataset(tmp_path)
    with TestClient(create_app(str(path))) as client:
        detail = client.get(f'/api/destinations/{cluster}').json()
        summary = client.get('/api/intelligence').json()['summary']
    assert detail['evidence']['photo_count'] == 1 and summary['archive_photos'] == 1 and summary['displayable'] == 0


@pytest.mark.parametrize('key', ['', 'configured-test-key'])
def test_startup_and_reads_make_no_network_calls_with_or_without_a_flickr_key(tmp_path, monkeypatch, key):
    path, cluster = api_dataset(tmp_path)
    monkeypatch.setenv('FLICKR_API_KEY', key)
    calls = []
    with patch.object(socket.socket, 'connect', lambda self, address: calls.append(address) or (_ for _ in ()).throw(OSError('blocked'))):
        with TestClient(create_app(str(path))) as client:
            for route in ('/health', '/api/workspace', '/api/calendar', '/api/campaign-requests', f'/api/destinations/{cluster}', '/api/images/afaq_historical/1'):
                client.get(route)
    assert calls == []
