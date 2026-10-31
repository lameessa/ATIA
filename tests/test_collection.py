import json
from unittest.mock import Mock

import pytest
import requests

from atia.collectors.flickr import FlickrClient, FlickrError, collect
from atia.collectors.historical import import_historical
from atia.models import normalize
from atia.storage.sqlite import PhotoStore


def raw(photo_id="1", **kwargs):
    return {"id": photo_id, "latitude": "24.7", "longitude": "46.7",
            "dateupload": "1700000000", "datetaken": "2020-02-03 12:00:00", **kwargs}


def response(payload=None, status=200):
    result = Mock(status_code=status)
    result.json.return_value = payload
    return result


def client_with(*responses):
    session = Mock()
    session.get.side_effect = responses
    return FlickrClient("test-only-key", session=session, pause=lambda _: None)


def test_normalize_preserves_dates_and_license():
    photo = normalize(raw(views="0", tags="saudi desert saudi", license="0"), "flickr_live",
                      {"0": {"name": "All Rights Reserved", "url": "https://example.org/license"}})
    assert photo.uploaded_at == "2023-11-14T22:13:20+00:00"
    assert photo.captured_at == "2020-02-03 12:00:00"
    assert photo.views == 0
    assert photo.tags == ["saudi", "desert"]
    assert photo.license_id == "0"
    assert photo.license_name == "All Rights Reserved"


def test_missing_and_malformed_metadata():
    photo = normalize({"id": 12, "latitude": "nan", "views": "unknown",
                       "datetaken": "0000-00-00 00:00:00", "dateupload": "invalid"}, "afaq_historical")
    assert photo.photo_id == "12"
    assert photo.latitude is photo.longitude is photo.views is None
    assert photo.captured_at is photo.uploaded_at is None
    assert photo.tags == []
    with pytest.raises(ValueError):
        normalize({}, "flickr_live")


def test_persistent_dedup_and_source_isolation(tmp_path):
    path = tmp_path / "nested" / "photos.sqlite3"
    with PhotoStore(path) as store:
        assert store.save(normalize(raw(), "flickr_live"))
        assert not store.save(normalize(raw(), "flickr_live"))
        assert store.save(normalize(raw(), "afaq_historical"))
    with PhotoStore(path) as store:
        assert store.counts() == {"flickr_live": 1, "afaq_historical": 1}
        assert store.list_photos(source="flickr_live")[0]["raw"]["id"] == "1"


def test_retry_network_rate_limit_and_service_error():
    client = client_with(requests.Timeout("secret URL"), response(status=429), response({"stat": "ok"}))
    assert client.call("test") == {"stat": "ok"}
    client = client_with(response({"stat": "fail", "code": 105}), response({"stat": "ok"}))
    assert client.call("test")["stat"] == "ok"


def test_invalid_key_not_retried_or_exposed():
    client = client_with(response({"stat": "fail", "code": 100, "message": "test-only-key"}))
    with pytest.raises(FlickrError, match="100") as error:
        client.call("test")
    assert "test-only-key" not in str(error.value)
    assert client.session.get.call_count == 1


def test_bad_json_and_unavailable_photo():
    bad = response()
    bad.json.side_effect = ValueError("bad")
    client = client_with(bad, bad, bad)
    with pytest.raises(FlickrError, match="invalid JSON"):
        client.call("test")
    client = client_with(response({"stat": "fail", "code": 1}))
    with pytest.raises(FlickrError):
        client.call("flickr.photos.getInfo", photo_id="deleted")


def test_country_and_search_parameters():
    client = client_with(response({"stat": "ok", "places": {"place": [
        {"place_type": "locality", "_content": "Saudi Arabia", "woeid": "1"},
        {"place_type": "country", "_content": "Saudi Arabia", "woeid": "23424938"}]} }),
        response({"stat": "ok", "photos": {"photo": [], "pages": 0}}))
    country = client.saudi_woe_id()
    client.search(country, 1, 250)
    params = client.session.get.call_args.kwargs["params"]
    assert params["bbox"] == "34,16,56,33"
    assert params["has_geo"] == 1
    assert params["min_upload_date"] == 0
    assert "date_taken" in params["extras"] and "date_upload" in params["extras"]


def test_country_resolution_fails_closed():
    client = client_with(response({"stat": "ok", "places": {"place": []}}),
                         response({"stat": "ok", "place": {}}))
    with pytest.raises(FlickrError, match="resolve"):
        client.saudi_woe_id()


def test_collect_50_new_unique_rows_with_pagination():
    client = Mock()
    client.saudi_woe_id.return_value = "23424938"
    client.licenses.return_value = {}
    client.search.side_effect = [
        {"pages": 2, "photo": [raw("existing"), {}, raw("bad", latitude="bad")] + [raw(str(i)) for i in range(25)]},
        {"pages": 2, "photo": [raw(str(i)) for i in range(25, 60)]}]
    with PhotoStore(":memory:") as store:
        store.save(normalize(raw("existing"), "flickr_live"))
        report = collect(client, store)
        assert report["complete"]
        assert report["inserted"] == 50
        assert report["duplicates"] == 1
        assert report["skipped"] == 2
        assert store.counts()["flickr_live"] == 51


def test_exhaustion_and_license_failure():
    client = Mock()
    client.licenses.side_effect = FlickrError("unavailable")
    client.search.return_value = {"pages": 1, "photo": []}
    with PhotoStore(":memory:") as store:
        result = collect(client, store)
    assert not result["complete"]
    assert result["warnings"]


@pytest.mark.parametrize("wrapper", [lambda rows: rows, lambda rows: {"photos": {"photo": rows}},
                                         lambda rows: {"data": rows}])
def test_historical_import(tmp_path, wrapper):
    path = tmp_path / "Afaq_RawData.json"
    path.write_text(json.dumps(wrapper([raw(), raw(), {}, None])), encoding="utf-8")
    with PhotoStore(":memory:") as store:
        result = import_historical(path, store)
        assert result == {"source": "afaq_historical", "inserted": 1, "duplicates": 1, "skipped": 2}
        assert store.counts() == {"afaq_historical": 1}


def test_id_keyed_import(tmp_path):
    path = tmp_path / "history.json"
    path.write_text(json.dumps({"987": {"title": "Old photo"}}))
    with PhotoStore(":memory:") as store:
        assert import_historical(path, store)["inserted"] == 1
        assert store.list_photos()[0]["photo_id"] == "987"


def test_verified_country_fallback():
    client = client_with(response({"stat": "ok", "places": {"place": []}}),
                         response({"stat": "ok", "place": {"woeid": 23424938, "woe_name": "السعودية"}}))
    assert client.saudi_woe_id() == "23424938"


def test_regional_historical_api_envelopes(tmp_path):
    path = tmp_path / "history.json"
    path.write_text(json.dumps({"North": {
        "123": {"info": {"stat": "ok", "photo": {"id": "123", "dates": {"posted": "1700000000", "taken": "2020-02-03 12:00:00"}, "location": {"latitude": "24.7", "longitude": "46.7"}}}},
        "124": {"info": {"stat": "fail", "code": 1}}
    }}))
    with PhotoStore(":memory:") as store:
        assert import_historical(path, store)["inserted"] == 2
        records = {r["photo_id"]: r for r in store.list_photos()}
        assert records["123"]["latitude"] == 24.7
        assert records["123"]["uploaded_at"] is not None
        assert records["124"]["latitude"] is None
        assert records["124"]["raw"]["info"]["stat"] == "fail"
        assert records["124"]["raw"]["historical_region"] == "North"


def test_bbox_candidates_require_saudi_country_verification():
    client = client_with(
        response({"stat": "ok", "photos": {"photo": [raw("1"), raw("2")], "pages": 1}}),
        response({"stat": "ok", "photo": {"location": {"country": {"_content": "Saudi Arabia"}}}}),
        response({"stat": "ok", "photo": {"location": {"country": {"woeid": "other"}}}}))
    result = client.search("23424938", 1, 50)
    assert [p["id"] for p in result["photo"]] == ["1"]
    assert result["candidate_count"] == 2
