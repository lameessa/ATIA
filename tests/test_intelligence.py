"""Offline tests: synthetic records and mocked Flickr; no network, model or paid service."""
import json
from types import SimpleNamespace
from fastapi.testclient import TestClient
import pytest
from atia.api.dashboard import create_app
from atia.api.media import FlickrMedia, cached_photo
from atia.collectors.flickr import FlickrError
from atia.intelligence.extract import find_places, find_themes, photo_facts, resolve_geography
from atia.intelligence.images import restore_images
from atia.intelligence.licences import LICENCES, attribution_text, interpret, interpret_recorded
from atia.intelligence.signals import build_signals, select_subset
from atia.intelligence.store import IntelligenceStore
from atia.storage.sqlite import PhotoStore
from atia.vision.images import ImageUnavailable
from display_fixtures import approve

JPEG = b'\xff\xd8\xff\xe0' + b'0' * 32


def facts(title='', tags=(), description='', **geo):
    base = dict(latitude=None, longitude=None, accuracy=None, neighbourhood=None, locality=None, county=None, flickr_region=None, macro_sampling_region='Central')
    return {'title': title, 'tags': list(tags), 'description': description, **base, **geo}


def names(value):
    return [p['name'] for p in find_places(value)]


# Licences
@pytest.mark.parametrize('license_id', ['4', '5', '9', '11', '12'])
def test_open_licences_are_eligible(license_id):
    assert interpret(license_id)['campaign_eligible'] is True


@pytest.mark.parametrize('license_id', ['0', '1', '2', '3', '6', '7', '8', '10', '13', '14', '15', '16'])
def test_restrictive_or_uncertain_licences_are_never_eligible(license_id):
    licence = interpret(license_id)
    assert licence['campaign_eligible'] is False and licence['reason']


@pytest.mark.parametrize('license_id', [None, '', '99', 'unknown'])
def test_missing_or_unrecognized_licence_is_unknown(license_id):
    assert interpret(license_id)['campaign_status'] == 'unknown'
    assert interpret(license_id)['campaign_eligible'] is False


def test_every_licence_id_has_a_decision():
    assert set(LICENCES) == {str(i) for i in range(17)}


def test_recorded_licence_resolves_by_id_then_exact_url():
    assert interpret_recorded('9')['name'] == 'CC0 1.0'
    assert interpret_recorded(None, 'https://creativecommons.org/licenses/by/2.0/')['campaign_eligible'] is True
    assert interpret_recorded(None, 'https://example.com/free-to-use/')['campaign_status'] == 'unknown'


def test_attribution_uses_only_recorded_values():
    assert attribution_text('Namar Valley', 'Maher Najm', interpret('9'), 'https://flickr.com/x') == '“Namar Valley” by Maher Najm · CC0 1.0 · https://flickr.com/x'
    assert 'photographer not recorded' in attribution_text('', None, interpret(None), None)


# Place extraction, using real title shapes from the archive
@pytest.mark.parametrize('title,expected', [
    ('Namar Valley', ['Wadi Namar']), ('وادي نمار', ['Wadi Namar']), ('Wadi Hanifa at sunset', ['Wadi Hanifa']),
    ('The Bajda Rock', ['Bajda Rock']), ('Wadi Laban park Riyadh', ['Wadi Laban']), ('The Masmak fort', ['Al Masmak Palace']),
    ('Thee Ain - The Marble village', ['Dhi Ain Village']), ('جامع الراجحي بـ حائل', ['جامع الراجحي']), ('Saudi Arabia Al-Dessa valley II', ['Wadi Al Disah']),
])
def test_named_places_are_found(title, expected):
    assert names(facts(title)) == expected


@pytest.mark.parametrize('title', ['Old fort', 'Rock mountain', 'The parents Mosque', 'Desert', 'Jeddah', 'Sunset 2', 'Jeddah Downtown', 'الرياض', 'IMG_1579'])
def test_generic_titles_and_cities_are_not_destinations(title):
    assert [p for p in find_places(facts(title)) if p['specificity'] == 'specific_place'] == []


@pytest.mark.parametrize('title', ['Jeddah Beach.', 'Khobar beach', 'غروب شاطئ الدمام'])
def test_shared_city_features_stay_out_of_named_destinations(title):
    assert [p['specificity'] for p in find_places(facts(title))] == ['city_feature']


def test_free_text_patterns_do_not_invent_places_from_descriptions():
    assert names(facts('Sunset', description='A lovely Sunny Beach and Great Valley near town')) == []
    assert names(facts('Sunset', description='Taken at Wadi Tayyib is lovely')) == ['Wadi Tayyib']


def test_trailing_words_are_removed_from_prefixed_names():
    assert names(facts('Palace Ghiad Is')) == ['Palace Ghiad']


# Themes
def themes(value, **kwargs):
    return {t['theme']: t['strength'] for t in find_themes(value, **kwargs)}


def test_palm_trees_support_agriculture_without_a_named_farm():
    value = facts('Palm - نخلة', flickr_region='القصيم')
    assert themes(value, region='qassim')['agricultural_tourism'] == 'metadata'
    assert resolve_geography(value)['region'] == 'qassim'


def test_palms_at_the_beach_are_not_agriculture():
    assert themes(facts('Jeddah sunset', tags=['beach', 'palm']))['agricultural_tourism'] == 'weak_mention'
    assert themes(facts('Palm grove', tags=['beach', 'palm']))['agricultural_tourism'] == 'metadata'


def test_description_only_and_tag_spam_are_weak():
    assert themes(facts('Sunset', description='near the beach'))['coastal_marine'] == 'weak_mention'
    assert themes(facts('Sunset', tags=['beach'] + [f't{i}' for i in range(25)]))['coastal_marine'] == 'weak_mention'


def test_coastal_tags_on_inland_photos_are_weak_unless_titled():
    assert themes(facts('Valley', tags=['sea']), region='riyadh')['coastal_marine'] == 'weak_mention'
    assert themes(facts('Dead sea view', tags=[]), region='riyadh')['coastal_marine'] == 'metadata'


def test_stored_openclip_label_only_counts_when_supplied():
    assert 'desert_adventure' not in themes(facts('Photo'))
    result = find_themes(facts('Photo'), visual_environment='desert')
    assert result[0]['evidence'] == [{'source': 'openclip_stored', 'terms': ['desert']}] and result[0]['strength'] == 'visual'


@pytest.mark.parametrize('title', ['Spring in Saudi Arabia 2016', 'Date with friends', 'Sensational sunset', 'Seaside'])
def test_vague_words_do_not_create_themes(title):
    assert themes(facts(title)) == {}


# Geography
def test_geotag_precision_and_region_basis_are_recorded():
    geo = resolve_geography(facts('Photo', latitude=24.5, longitude=46.6, accuracy=16, flickr_region='Ar Riyāḑ'))
    assert (geo['precision'], geo['region'], geo['region_basis']) == ('precise_geotag', 'riyadh', 'flickr_location')
    assert resolve_geography(facts('Photo', latitude=24.5, longitude=46.6, accuracy=6))['precision'] == 'coarse_geotag'


def test_missing_coordinates_keep_regional_context_without_inventing_a_point():
    geo = resolve_geography(facts('مزارع الاحساء'))
    assert (geo['precision'], geo['region'], geo['latitude']) == ('region_only', 'eastern', None)


def test_conflicting_mentions_leave_the_region_unset_and_sampling_group_is_kept():
    geo = resolve_geography(facts('Tabuk to Abha'))
    assert geo['region'] is None and geo['mentioned_regions'] == ['asir', 'tabuk'] and geo['macro_sampling_region'] == 'Central'
    assert geo['precision'] == 'macro_sampling_only'


def test_non_saudi_metadata_is_flagged():
    geo = resolve_geography(facts('Photo', flickr_region='المنامة'))
    assert geo['outside_saudi_metadata'] is True and geo['region'] is None


# Stored records
def raw(photo_id, title, tags=(), license_id='0', owner='o1', views=100, favorites=2, description='', location=None, region='Central', deleted=False):
    if deleted:
        return {'id': photo_id, 'historical_region': region, 'info': {'stat': 'fail', 'code': 1}, 'favorites': {'stat': 'fail'}}
    return {'id': photo_id, 'historical_region': region, 'favorites': {'photo': {'total': favorites}},
            'info': {'stat': 'ok', 'photo': {'id': photo_id, 'server': '1', 'secret': 's', 'originalsecret': 'orig', 'originalformat': 'jpg', 'license': license_id,
                     'owner': {'nsid': owner, 'realname': f'Name {owner}'}, 'comments': {'_content': '3'}, 'description': {'_content': description}, 'location': location or {}}}}


def add(db, photo_id, title, tags=(), license_id='0', owner='o1', views=100, latitude=None, longitude=None, **kwargs):
    record = raw(photo_id, title, tags, license_id, owner, views, **kwargs)
    db.execute('INSERT INTO photos(source,photo_id,title,latitude,longitude,views,tags,license_id,owner_id,photo_url,collected_at,raw) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
               ('afaq_historical', photo_id, title, latitude, longitude, None if kwargs.get('deleted') else views, json.dumps(list(tags)), None if kwargs.get('deleted') else license_id,
                None if kwargs.get('deleted') else owner, f'https://www.flickr.com/photos/x/{photo_id}/', '2026-01-01T00:00:00+00:00', json.dumps(record)))


class Client:
    def __init__(self, licences=None, missing=(), restricted=()):
        self.licences, self.missing, self.restricted, self.calls = licences or {}, set(missing), set(restricted), []

    def call(self, method, photo_id=None, **_):
        self.calls.append(photo_id)
        if photo_id in self.missing:
            raise FlickrError('Flickr API error 1.', code='1')
        return {'photo': {'license': self.licences.get(photo_id, '0'), 'safety_level': '2' if photo_id in self.restricted else '0', 'media': 'photo',
                          'owner': {'nsid': 'o', 'realname': 'Current Owner'}, 'urls': {'url': [{'type': 'photopage', '_content': f'https://flickr.com/{photo_id}'}]}}}


class Fetcher:
    def __init__(self, root, failing=(), width=1024):
        self.root, self.failing, self.width, self.fetched = root, set(failing), width, []

    def fetch(self, record):
        self.fetched.append(record['photo_id'])
        if record['photo_id'] in self.failing:
            raise ImageUnavailable('No accessible, sufficiently large Flickr photo size.')
        import hashlib
        sha = hashlib.sha256(JPEG + record['photo_id'].encode()).hexdigest()
        path = self.root / f'{sha}.img'
        path.write_bytes(JPEG + record['photo_id'].encode())
        return SimpleNamespace(sha256=sha, path=str(path), url=f"https://live.staticflickr.com/1/{record['photo_id']}_b.jpg", width=self.width, height=self.width // 2)


@pytest.fixture
def store(tmp_path):
    with PhotoStore(str(tmp_path / 'db.sqlite3')) as value:
        yield value


def restore(store, tmp_path, client=None, **kwargs):
    fetcher = kwargs.pop('fetcher', Fetcher(tmp_path))
    return restore_images(store, client or Client(), fetcher=fetcher, pause=lambda _: None, **kwargs), fetcher


# Image retrieval
def test_restore_records_status_and_caches_valid_images(store, tmp_path):
    add(store.connection, '1', 'Namar Valley', license_id='9')
    report, _ = restore(store, tmp_path, Client({'1': '9'}))
    assert report['images_cached'] == 1 and report['api_status'] == {'ok': 1}
    assert cached_photo(store.connection, 'afaq_historical', '1') is None
    approve(store.connection, 'afaq_historical', '1', '9', keep_status=True)
    assert cached_photo(store.connection, 'afaq_historical', '1').is_file()


def test_deleted_or_restricted_photos_are_not_fetched(store, tmp_path):
    add(store.connection, 'gone', 'A')
    add(store.connection, 'safe2', 'B')
    report, fetcher = restore(store, tmp_path, Client(missing=['gone'], restricted=['safe2']))
    assert fetcher.fetched == [] and report['api_status'] == {'not_found': 1, 'restricted': 1}


def test_failed_image_is_recorded_and_retried_while_complete_ones_are_skipped(store, tmp_path):
    add(store.connection, '1', 'A')
    add(store.connection, '2', 'B')
    report, _ = restore(store, tmp_path, fetcher=Fetcher(tmp_path, failing=['2']))
    assert report['image_failures'] == {'No accessible, sufficiently large Flickr photo size.': 1}
    client = Client()
    report, fetcher = restore(store, tmp_path, client, fetcher=Fetcher(tmp_path))
    assert fetcher.fetched == ['2'] and client.calls == ['2'] and report['already_complete'] == 1


def test_cached_pixels_are_withheld_after_flickr_reports_deletion(store, tmp_path):
    add(store.connection, '1', 'A')
    restore(store, tmp_path)
    approve(store.connection, 'afaq_historical', '1', '4')
    assert cached_photo(store.connection, 'afaq_historical', '1') is not None
    with store.connection:
        store.connection.execute("UPDATE photo_flickr_status SET api_status='not_found'")
    assert cached_photo(store.connection, 'afaq_historical', '1') is None


def test_tampered_cached_image_is_rejected(store, tmp_path):
    add(store.connection, '1', 'A')
    restore(store, tmp_path)
    approve(store.connection, 'afaq_historical', '1', '4')
    cached_photo(store.connection, 'afaq_historical', '1').write_bytes(b'changed')
    assert cached_photo(store.connection, 'afaq_historical', '1') is None


# Rights in the media contract
def test_archive_licence_needs_a_flickr_recheck_before_it_counts(store, tmp_path):
    add(store.connection, '1', 'A', license_id='9')
    store.connection.commit()
    db = store.connection
    media = FlickrMedia(db)
    assert media.asset('afaq_historical', '1') is None
    restore(store, tmp_path, Client({'1': '9'}))
    assert media.asset('afaq_historical', '1') is None
    approve(db, 'afaq_historical', '1', '9', keep_status=True)
    assert media.asset('afaq_historical', '1')['rights_status'] == 'reusable_with_attribution'
    assert media.asset('afaq_historical', '1')['license_name'] == 'CC0 1.0'
    assert media.asset('afaq_historical', '1')['license_checked_at']


def test_current_flickr_licence_overrides_a_permissive_archive_value(store, tmp_path):
    add(store.connection, '1', 'A', license_id='9')
    restore(store, tmp_path, Client({'1': '0'}))
    with pytest.raises(ValueError, match='licence'):
        approve(store.connection, 'afaq_historical', '1', '0', keep_status=True)
    assert FlickrMedia(store.connection).asset('afaq_historical', '1') is None


# Signals
def seed_archive(db):
    add(db, 'a1', 'Namar Valley', owner='o1', license_id='9', latitude=24.57, longitude=46.68, location={'accuracy': '16', 'region': {'_content': 'الرياض'}})
    add(db, 'a2', 'وادي نمار', owner='o2')
    add(db, 'b1', 'Swaj mountain  جبل سواج', owner='o3', location={'region': {'_content': 'القصيم'}})
    add(db, 'c1', 'Date farm in AlQassim', owner='o4', location={'region': {'_content': 'القصيم'}})
    add(db, 'c2', 'Palm - نخلة', owner='o5', tags=['Qassim'])
    add(db, 'd1', 'Jeddah Beach.', owner='o6')
    add(db, 'e1', 'taif 339', owner='o7')
    add(db, 'gone', '', deleted=True)
    db.commit()


def built(store, tmp_path, licences=None, subset=50):
    seed_archive(store.connection)
    restore(store, tmp_path, Client(licences or {'a1': '9'}, missing=['gone']))
    return build_signals(store.connection, subset)


def signal(result, kind, key):
    return next(s for s in result['signals'] if s['kind'] == kind and s['key'] == key)


def test_alias_and_same_title_names_merge_into_one_destination(store, tmp_path):
    result = built(store, tmp_path)
    namar = signal(result, 'named_destination', 'wadi namar')
    assert namar['title'] == {'en': 'Wadi Namar', 'ar': 'وادي نمار'} and namar['photo_ids'] == ['a1', 'a2'] and namar['evidence']['distinct_photographers'] == 2
    swaj = [s for s in result['signals'] if s['title']['en'] == 'Swaj Mountain']
    assert len(swaj) == 1 and swaj[0]['title']['ar'] == 'جبل سواج'


def test_unconfirmed_names_stay_unverified_and_verified_means_existence_only(store, tmp_path):
    db = store.connection
    db.execute('CREATE TABLE verified_location_entities (entity_id TEXT, verified_name TEXT, entity_type TEXT, verification_status TEXT, first_verified_at TEXT)')
    db.execute("INSERT INTO verified_location_entities VALUES('e1','Wadi Namar','attraction','authoritative_source_name_confirmed','now')")
    result = built(store, tmp_path)
    assert signal(result, 'named_destination', 'wadi namar')['identity']['status'] == 'verified_entity_exists'
    assert 'not that these photos show it' in signal(result, 'named_destination', 'wadi namar')['identity']['note']
    swaj = next(s for s in result['signals'] if s['title']['en'] == 'Swaj Mountain')
    assert swaj['identity']['status'] == 'unverified_metadata_name' and 'identity_unverified' in swaj['gaps']


def test_regional_experience_exists_without_any_named_place(store, tmp_path):
    result = built(store, tmp_path)
    qassim = signal(result, 'regional_experience', 'qassim:agricultural_tourism')
    assert qassim['title']['en'] == 'Agricultural and farm tourism in Al Qassim' and qassim['photo_ids'] == ['c1', 'c2'] and qassim['identity'] is None


def test_city_features_support_a_regional_experience_not_a_destination(store, tmp_path):
    result = built(store, tmp_path)
    assert not [s for s in result['signals'] if s['kind'] == 'named_destination' and 'Beach' in (s['title']['en'] or '')]
    assert 'Jeddah Beach' in signal(result, 'regional_experience', 'makkah:coastal_marine')['features_mentioned']


def test_signals_do_not_claim_research_or_hiddenness(store, tmp_path):
    result = built(store, tmp_path)
    for item in result['signals']:
        assert item['assessment'] == {'promotional_coverage': 'not_researched', 'underrepresentation': 'not_assessed', 'demand': 'not_assessed'}
        assert 'promotional_coverage_not_researched' in item['gaps'] and item['status'] == 'signal_not_researched'
    assert 'hidden' not in json.dumps(result['signals']).casefold()


def test_counts_separate_display_from_campaign_use(store, tmp_path):
    result = built(store, tmp_path)
    assert result['summary']['archive_photos'] == 8 and result['summary']['flickr_status'] == {'ok': 7, 'not_found': 1}
    assert result['summary']['images_cached'] == 7 and result['summary']['displayable'] == 0
    namar = signal(result, 'named_destination', 'wadi namar')
    assert namar['evidence']['photo_count'] == 2 and namar['images']['displayable'] == 0
    approve(store.connection, 'afaq_historical', 'a1', '9', keep_status=True)
    namar = signal(build_signals(store.connection), 'named_destination', 'wadi namar')
    assert (namar['images']['displayable'], namar['images']['campaign_eligible']) == (1, 1)
    assert namar['images']['representative'][0]['photo_id'] == 'a1'


def test_missing_engagement_is_not_counted_as_zero(store, tmp_path):
    result = built(store, tmp_path)
    gone = next(p for p in result['photos'] if p['photo_id'] == 'gone')
    assert gone['engagement'] == {'views': None, 'favorites': None, 'comments': None} and gone['displayable'] is False


def test_openclip_absent_means_no_visual_claim(store, tmp_path):
    result = built(store, tmp_path)
    assert result['summary']['stored_openclip_photos'] == 0
    assert all(s['visual']['photos_with_stored_result'] == 0 for s in result['signals'])


def test_review_labels_block_display(store, tmp_path):
    db = store.connection
    db.execute('CREATE TABLE visual_review_labels (source TEXT, photo_id TEXT, label TEXT, reviewed_at TEXT)')
    db.execute("INSERT INTO visual_review_labels VALUES('afaq_historical','a1','uncertain','now')")
    result = built(store, tmp_path)
    assert next(p for p in result['photos'] if p['photo_id'] == 'a1')['displayable'] is False


def test_subset_keeps_full_archive_and_requires_evidence(store, tmp_path):
    result = built(store, tmp_path)
    assert len(result['photos']) == 8
    assert 'e1' not in {p['photo_id'] for p in result['subset']}
    assert [p['subset_rank'] for p in result['subset']] == list(range(1, len(result['subset']) + 1))


def subset_photo(photo_id, owner='o', place='Place', region='Central', score=5, width=1024):
    return {'photo_id': photo_id, 'owner_id': owner, 'displayable': True, 'subset_rank': None, 'quality': {'score': score}, 'image': {'width': width, 'height': 500},
            'themes': [], 'places': [{'name': place, 'specificity': 'specific_place'}], 'geography': {'macro_sampling_region': region}}


def test_subset_caps_photographers_and_places_and_filters_small_images():
    same_owner = [subset_photo(str(i), owner='one', place=f'P{i}') for i in range(6)]
    assert len(select_subset(same_owner, 50)) == 3
    same_place = [subset_photo(str(i), owner=f'o{i}') for i in range(6)]
    assert len(select_subset(same_place, 50)) == 2
    assert select_subset([subset_photo('small', width=320)], 50) == []


def test_subset_needs_a_cached_image_and_grants_no_display_permission():
    blocked = {**subset_photo('none'), 'image': None}
    assert [p['photo_id'] for p in select_subset([blocked, subset_photo('kept', place='Other')], 50)] == ['kept']
    assert select_subset([blocked], 50) == []


def test_subset_spreads_across_regions_and_is_deterministic():
    photos = [subset_photo(f'{r}{i}', owner=f'{r}{i}', place=f'{r}{i}', region=r, score=10 - i) for r in 'ABC' for i in range(4)]
    first = [p['photo_id'] for p in select_subset(photos, 3)]
    assert first == ['A0', 'B0', 'C0'] and first == [p['photo_id'] for p in select_subset(photos, 3)]


def test_rebuild_adds_a_run_and_keeps_signal_ids_stable(store, tmp_path):
    first = built(store, tmp_path)
    second = build_signals(store.connection)
    assert {s['signal_id'] for s in first['signals']} == {s['signal_id'] for s in second['signals']}
    assert store.connection.execute('SELECT COUNT(*) FROM intelligence_runs').fetchone()[0] == 2


def test_photos_table_is_never_modified(store, tmp_path):
    seed_archive(store.connection)
    before = [dict(r) for r in store.connection.execute('SELECT * FROM photos ORDER BY photo_id')]
    restore(store, tmp_path, Client(missing=['gone']))
    build_signals(store.connection)
    assert before == [dict(r) for r in store.connection.execute('SELECT * FROM photos ORDER BY photo_id')]


# API
def test_api_reports_absence_then_serves_signals_and_images(tmp_path):
    path = tmp_path / 'db.sqlite3'
    with PhotoStore(str(path)) as value:
        add(value.connection, 'a1', 'Namar Valley', license_id='9', owner='o1')
        value.connection.commit()
    with TestClient(create_app(str(path))) as client:
        assert client.get('/api/intelligence').json()['available'] is False
    with PhotoStore(str(path)) as value:
        restore(value, tmp_path, Client({'a1': '9'}))
        build_signals(value.connection)
    with TestClient(create_app(str(path))) as client:
        assert client.get('/api/intelligence').json()['summary']['displayable'] == 0
    with PhotoStore(str(path)) as value:
        approve(value.connection, 'afaq_historical', 'a1', '9', keep_status=True)
        build_signals(value.connection)
    with TestClient(create_app(str(path))) as client:
        body = client.get('/api/intelligence').json()
        assert body['available'] is True and body['summary']['campaign_image_eligible'] == 1
        assert 'raw' not in json.dumps(body)
        kinds = client.get('/api/intelligence', params={'kind': 'named_destination'}).json()['signals']
        assert {s['kind'] for s in kinds} == {'named_destination'}
        assert client.get(body['signals'][0]['images']['representative'][0]['preview_url']).headers['content-type'] == 'image/jpeg'
        assert client.post('/api/intelligence', json={}).status_code in (403, 405)
