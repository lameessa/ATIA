"""The public repository must demonstrate the workflow with no key and no private data, showing only licensed images."""
from pathlib import Path
import json
import re
import subprocess
from fastapi.testclient import TestClient
import pytest
from atia.api.dashboard import create_app
from atia.demo import SEED, init_demo, load_seed, validate_demo
from atia.moderation.display import reviewed_images
from atia.storage.sqlite import PhotoStore

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {'X-ATIA-Action': 'confirmed'}


@pytest.fixture
def demo(tmp_path, monkeypatch):
    for key in ('FLICKR_API_KEY', 'OPENAI_API_KEY', 'TAVILY_API_KEY'):
        monkeypatch.setenv(key, '')
    path = tmp_path / 'demo.sqlite3'
    with PhotoStore(str(path)) as store:
        init_demo(store)
    return str(path)


def test_seed_holds_no_images_image_urls_raw_data_or_reviews():
    text = SEED.read_text(encoding='utf-8')
    for forbidden in ('staticflickr', '/api/images/', 'data/images', 'image_sha256', '"raw"', 'owner_nsid', 'claude-basic-visual-check', 'rejected_output'):
        assert forbidden not in text
    assert all(not p['displayable'] and p['preview_url'] is None and p['description'] == '' for p in load_seed()['photos'])
    assert {c['review']['reviewer'] for c in load_seed()['campaigns'] if c['review']} == {'Project reviewer'}


def test_demo_refuses_a_database_that_already_has_photos(tmp_path):
    with PhotoStore(str(tmp_path / 'real.sqlite3')) as store:
        store.connection.execute("INSERT INTO photos(source,photo_id,title,tags,collected_at,raw) VALUES('afaq_historical','1','t','[]','now','{}')")
        with pytest.raises(ValueError, match='empty'):
            init_demo(store)


def test_discover_keeps_real_evidence_classifications_with_images(demo):
    with TestClient(create_app(demo)) as client:
        found = {o['id']: o for o in client.get('/api/workspace').json()['opportunities']}
    assert (found['farasan-islands']['evidence_label'], found['farasan-islands']['evidence']['photo_count'], found['farasan-islands']['evidence']['distinct_photographers']) == ('Strong evidence', 10, 8)
    assert (found['qassim-agritourism']['evidence_label'], found['qassim-agritourism']['evidence']['photo_count']) == ('Moderate evidence', 3)
    assert (found['najran-rock-art']['evidence_label'], found['najran-rock-art']['evidence']['photo_count']) == ('Exploratory', 1)
    assert all(o['media'] and o['licensed_images'] == len(o['gallery']) for o in found.values())


def test_validation_rejects_the_original_draft_and_accepts_the_correction_offline():
    result = validate_demo()
    assert result['model_call'] is False and result['original_ai_draft'].startswith('REJECTED') and result['corrected_revision'] == 'ACCEPTED'


def test_all_five_saved_campaigns_keep_their_state(demo):
    with TestClient(create_app(demo)) as client:
        found = {c['opportunity_id']: c for c in client.get('/api/workspace').json()['campaigns']}
        assert {k: (c['status'], c['validation']['state']) for k, c in found.items()} == {
            'qassim-agritourism': ('APPROVED', 'READY'), 'farasan-islands': ('PENDING_APPROVAL', 'WARNINGS'), 'rijal-almaa': ('PENDING_APPROVAL', 'WARNINGS'),
            'najran-rock-art': ('PENDING_APPROVAL', 'WARNINGS'), 'riyadh-waterscapes': ('PENDING_APPROVAL', 'NEEDS_CORRECTION')}
        assert found['qassim-agritourism']['revision'] == 1 and found['qassim-agritourism']['evidence_review']['original']['claims']
        assert all(c['media'] for c in found.values())


def test_review_and_calendar_work_with_no_keys(demo):
    with TestClient(create_app(demo)) as client:
        found = {c['opportunity_id']: c for c in client.get('/api/workspace').json()['campaigns']}
        names = lambda: {e['campaign_name']['en'] for e in client.get('/api/calendar').json()['entries']}
        assert names() == {'Al Qassim Among the Palms'}
        approve = {'decision': 'APPROVED', 'revision': 0, 'reviewer': 'Person', 'launch_date': '2026-11-10', 'confirmed': True}
        assert client.post(f"/api/campaigns/{found['riyadh-waterscapes']['id']}/review", headers=HEADERS, json=approve).status_code == 409
        assert client.post(f"/api/campaigns/{found['farasan-islands']['id']}/review", headers=HEADERS, json=approve).status_code == 200
        assert names() == {'Al Qassim Among the Palms', 'Farasan Islands'}


def tracked():
    out = subprocess.run(['git', 'ls-files', '-co', '--exclude-standard'], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines() if (ROOT / p).is_file()]


def test_public_tree_has_no_databases_images_or_env_files():
    bad = [p for p in tracked() if re.search(r'(^|/)\.env$|\.(sqlite3?|db|img|jpe?g|png|webp|gif|heic)$|Afaq_RawData|(^|/)data/(?!\.gitkeep)', p, re.I)]
    allowed = {f"demo/images/{i['photo_id']}.jpg" for i in reviewed_images()}
    assert sorted(set(bad) - allowed) == []


def test_public_docs_have_no_personal_paths_or_photo_ids():
    docs = [p for p in tracked() if p.endswith('.md') and p != 'demo/images/ATTRIBUTION.md']
    home = re.compile(r'/Users/\w+|/home/\w+')
    ids = re.compile(r'(?<![\w.\-/])\d{9,12}(?![\w\-])|\d{5,}@N\d\d')
    assert [p for p in docs if home.search((ROOT / p).read_text(encoding='utf-8')) or ids.search((ROOT / p).read_text(encoding='utf-8'))] == []
