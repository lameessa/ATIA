import sqlite3
from unittest.mock import Mock
import pytest
from atia.collectors.regional import collect_regions
from atia.collectors.regions import REGIONS, region_for
from atia.collectors.flickr import FlickrError
from atia.models import normalize
from atia.storage.sqlite import PhotoStore

POINTS = {"North": (28, 40), "South": (18, 43), "East": (26, 50),
          "West": (24, 39), "Central": (24, 46)}


def make_raw(photo_id, region):
    lat, lon = POINTS[region]
    return {"id": str(photo_id), "latitude": lat, "longitude": lon,
            "dateupload": "1700000000", "datetaken": "2020-01-01 12:00:00"}


def make_client(rows):
    client = Mock()
    client.saudi_woe_id.return_value = "23424938"
    client.licenses.return_value = {}
    client.search_candidates.side_effect = lambda bbox, page, size: {"pages": 1, "photo": rows[bbox]}
    raw_by_id = {raw['id']: raw for items in rows.values() for raw in items}
    client.verify_location.side_effect = lambda photo_id, country: {
        "latitude": raw_by_id[photo_id]['latitude'], "longitude": raw_by_id[photo_id]['longitude'],
        "country": {"_content": "Saudi Arabia"}}
    return client


def test_zone_assignment_and_boundaries():
    for name, point in POINTS.items():
        assert region_for(*point) == name
    assert region_for(21, 42) == 'Central'
    assert region_for(27, 42) == 'North'
    assert region_for(18, 48) == 'East'
    assert region_for(0, 0) is None


def test_quotas_global_dedup_and_historical_preservation(tmp_path):
    path = tmp_path / 'photos.sqlite3'
    rows = {r.query_bbox: [make_raw(index*100+i, r.name) for i in range(1, 14)]
            for index, r in enumerate(REGIONS)}
    client = make_client(rows)
    with PhotoStore(path) as store:
        historical = normalize(make_raw(1, 'North'), 'afaq_historical')
        store.save(historical)
        before = dict(store.connection.execute("SELECT * FROM photos WHERE source='afaq_historical'").fetchone())
        report = collect_regions(client, store)
        assert report['inserted'] == 50
        assert report['regions']['North']['duplicates'] == 1
        assert all(r['inserted'] == 10 for r in report['regions'].values())
        assert dict(store.connection.execute("SELECT * FROM photos WHERE source='afaq_historical'").fetchone()) == before
        assert not store.contains('flickr_live', '1')
    with PhotoStore(path) as store:
        report = collect_regions(make_client(rows), store, per_region=1)
        assert report['inserted'] == 5
        assert report['duplicates'] >= 50
        assert store.counts() == {'afaq_historical': 1, 'flickr_live': 55}


def test_shortfalls_wrong_country_and_verified_region():
    rows = {r.query_bbox: [make_raw(index+1, r.name)] for index, r in enumerate(REGIONS)}
    client = make_client(rows)
    client.verify_location.side_effect = [None, {'latitude': 28, 'longitude': 40, 'country': {}},
                                         None, None, None]
    messages = []
    with PhotoStore(':memory:') as store:
        report = collect_regions(client, store, progress=messages.append)
        assert report['inserted'] == 0
        assert all(r['shortfall'] == 10 for r in report['regions'].values())
        assert all(r['skipped'] == 1 for r in report['regions'].values())
        assert messages


def test_region_api_failure_does_not_discard_other_regions():
    rows = {r.query_bbox: [make_raw(index+1, r.name)] for index, r in enumerate(REGIONS)}
    client = make_client(rows)
    search = client.search_candidates.side_effect
    client.search_candidates.side_effect = lambda bbox, page, size: (_ for _ in ()).throw(FlickrError('temporary')) if bbox == REGIONS[0].query_bbox else search(bbox, page, size)
    with PhotoStore(':memory:') as store:
        report = collect_regions(client, store, per_region=1)
        assert report['regions']['North']['stop_reason'] == 'api_error'
        assert report['inserted'] == 4


def test_time_budget_stops_regions(monkeypatch):
    from atia.collectors import regional
    counter = iter(range(1000))
    monkeypatch.setattr(regional.time, 'monotonic', lambda: next(counter))
    client = Mock()
    client.licenses.return_value = {}
    with PhotoStore(':memory:') as store:
        result = collect_regions(client, store, region_seconds=0.1)
        assert all(r['stop_reason'] == 'time_budget' for r in result['regions'].values())
        client.search_candidates.assert_not_called()


def test_region_column_migrates_existing_database(tmp_path):
    path = tmp_path / 'old.sqlite3'
    with PhotoStore(path) as store:
        store.save(normalize(make_raw(1, 'Central'), 'afaq_historical'))
        store.connection.execute('ALTER TABLE photos DROP COLUMN region')
        store.connection.commit()
    with PhotoStore(path) as store:
        assert store.counts() == {'afaq_historical': 1}
        assert store.list_photos()[0]['region'] is None
