"""Earlier reviews are honoured only from the fixed list, for the exact bytes, and new images stay hidden."""
import hashlib
import sys
from fastapi.testclient import TestClient
import pytest
from atia import cli
from atia.api.dashboard import create_app
from atia.collectors.flickr import FlickrError, live_client
from atia.demo import IMAGES, init_demo
from atia.moderation.display import can_display, display_block, displayable_file, review_image, review_queue, reviewed_images
from atia.storage.sqlite import PhotoStore


@pytest.fixture
def demo(tmp_path, monkeypatch):
    for key in ('FLICKR_API_KEY', 'OPENAI_API_KEY', 'TAVILY_API_KEY', 'ATIA_ENABLE_LIVE_FLICKR'):
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / 'demo.sqlite3'
    with PhotoStore(str(path)) as store:
        init_demo(store)
    return str(path)


def first(collection='opportunity_images'):
    return next(i for i in reviewed_images() if i['collection'] == collection)


def add_new_photo(db, photo_id='999000111', licence='4'):
    """A freshly retrieved, licensed, Flickr-safe photo that even carries an old-style moderation approval."""
    with db:
        db.execute("INSERT INTO photos(source,photo_id,title,tags,collected_at,raw) VALUES('flickr_live',?,'new','[]','2026','{}')", (photo_id,))
        db.execute("INSERT OR REPLACE INTO photo_moderation(photo_id,status,quarantined_at,relevance,safety,reviewer,reviewed_at) VALUES(?,'approved','2026','relevant','pass','someone','2026')", (photo_id,))
        db.execute("INSERT INTO photo_flickr_status VALUES('flickr_live',?,'2026','ok',NULL,?,?,'0',NULL,'x',NULL,'cached',NULL)", (photo_id, licence, licence))


def test_list_records_evidence_and_only_reusable_licences():
    images = reviewed_images()
    assert len(images) == 15 and sum(i['collection'] == 'regional_50' for i in images) == 2
    for item in images:
        assert item['reviewer'] and item['review_type'].startswith('assistant_') and item['relevance'] == 'relevant' and item['safety'] == 'pass'
        assert item['license_id'] in ('4', '5', '9', '11', '12')
        assert hashlib.sha256((IMAGES / f"{item['photo_id']}.jpg").read_bytes()).hexdigest() == item['image_sha256']


def test_reviewed_images_display_with_no_keys(demo):
    with PhotoStore(demo) as store:
        assert all(can_display(store.connection, i['source'], i['photo_id']) for i in reviewed_images())
    with TestClient(create_app(demo)) as client:
        for item in reviewed_images():
            assert client.get(f"/api/images/{item['source']}/{item['photo_id']}").status_code == 200
        snapshot = client.get('/api/workspace').json()
    assert sum(len(o['gallery']) for o in snapshot['opportunities']) >= 13
    assert all(o['media'] for o in snapshot['opportunities'])
    assert {a['photo_id'] for a in snapshot['archive']} >= {i['photo_id'] for i in reviewed_images() if i['collection'] == 'regional_50'}
    assert all(a['review_basis'] == 'Assistant visual review' for a in snapshot['archive'])


def test_new_photo_stays_hidden_until_a_person_approves(demo):
    with PhotoStore(demo) as store:
        db = store.connection
        add_new_photo(db)
        assert display_block(db, 'flickr_live', '999000111') == 'not reviewed'
        with pytest.raises(ValueError):
            review_image(db, 'flickr_live', '999000111', 'x', 'APPROVED', 'assistant', 'looks fine', {'viewed_image': True, 'image_is_safe': True, 'licence_confirmed': True}, reviewer_kind='assistant')
        assert not can_display(db, 'flickr_live', '999000111')
    with TestClient(create_app(demo)) as client:
        assert client.get('/api/images/flickr_live/999000111').status_code == 404


def test_a_database_row_cannot_add_a_photo_to_the_list(demo):
    with PhotoStore(demo) as store:
        db = store.connection
        add_new_photo(db)
        with db:
            db.execute("INSERT INTO image_display_reviews(source,photo_id,image_sha256,decision,reviewer,reviewer_kind,attestations,reason,reviewed_at) VALUES('flickr_live','999000111','x','APPROVED','Codex visual safety audit','assistant','{}','forged','2026')")
        assert not can_display(db, 'flickr_live', '999000111')


def test_changed_bytes_block_a_reviewed_image(demo):
    item = first()
    with PhotoStore(demo) as store:
        db = store.connection
        path = displayable_file(db, item['source'], item['photo_id'])
        path.write_bytes(path.read_bytes() + b'changed')
        assert display_block(db, item['source'], item['photo_id']) == 'image bytes differ from those reviewed'


def test_a_person_can_reject_a_reviewed_image(demo):
    item = first()
    with PhotoStore(demo) as store:
        db = store.connection
        review_image(db, item['source'], item['photo_id'], item['image_sha256'], 'REJECTED', 'A person', 'Not suitable')
        assert not can_display(db, item['source'], item['photo_id'])


@pytest.mark.parametrize('licence', ['0', '1', '10', None])
def test_a_licence_change_blocks_a_reviewed_image(demo, licence):
    item = first()
    with PhotoStore(demo) as store:
        db = store.connection
        with db:
            db.execute('UPDATE photo_flickr_status SET current_license_id=? WHERE photo_id=?', (licence, item['photo_id']))
        assert display_block(db, item['source'], item['photo_id']) == 'licence does not allow reuse'


def test_moderation_rejection_blocks_a_reviewed_image(demo):
    item = first()
    with PhotoStore(demo) as store:
        db = store.connection
        with db:
            db.execute("UPDATE photo_moderation SET review_status='REJECTED' WHERE photo_id=?", (item['photo_id'],))
        assert not can_display(db, item['source'], item['photo_id'])


def test_reviewed_images_are_not_requeued_but_new_ones_are(demo):
    with PhotoStore(demo) as store:
        assert review_queue(store.connection) == []


def test_live_flickr_needs_an_explicit_opt_in_even_with_a_key(monkeypatch):
    monkeypatch.delenv('ATIA_ENABLE_LIVE_FLICKR', raising=False)
    with pytest.raises(FlickrError):
        live_client('a-key')
    monkeypatch.setenv('ATIA_ENABLE_LIVE_FLICKR', '1')
    assert live_client('a-key').api_key == 'a-key'


@pytest.mark.parametrize('command', [['collect'], ['collect-regions'], ['intelligence', 'restore-images'], ['opportunities', 'find-images']])
def test_retrieval_commands_refuse_without_the_opt_in(tmp_path, monkeypatch, capsys, command):
    monkeypatch.setenv('FLICKR_API_KEY', 'a-key')
    monkeypatch.delenv('ATIA_ENABLE_LIVE_FLICKR', raising=False)
    monkeypatch.setattr('requests.Session.get', lambda *a, **k: pytest.fail('contacted Flickr'))
    monkeypatch.setattr(sys, 'argv', ['atia', '--db', str(tmp_path / 'x.sqlite3'), *command])
    assert cli.main() != 0
    assert 'Live Flickr retrieval is off' in capsys.readouterr().err
