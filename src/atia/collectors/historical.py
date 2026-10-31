"""Historical ingestion never requests Flickr or treats records as live evidence."""
import json
from pathlib import Path
from atia.models import normalize


def extract_records(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("photos", "records", "data", "photo"):
            if key in payload:
                return extract_records(payload[key])
        if payload and all(isinstance(rows, dict) and rows and
                           all(str(key).isdigit() and isinstance(value, dict) and "info" in value
                               for key, value in rows.items()) for rows in payload.values()):
            return [{"id": photo_id, "historical_region": region, **value}
                    for region, rows in payload.items() for photo_id, value in rows.items()]
        if payload and all(isinstance(value, dict) for value in payload.values()):
            return [{"id": key, **value} for key, value in payload.items()]
    raise ValueError("Expected a photo list, photos.photo/data/records wrapper, or ID-keyed object")


def import_historical(path, store):
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    records = extract_records(payload)
    report = {"source": "afaq_historical", "inserted": 0, "duplicates": 0, "skipped": 0}
    for raw in records:
        if not isinstance(raw, dict):
            report["skipped"] += 1
            continue
        try:
            metadata = raw
            if isinstance(raw.get("info"), dict):
                info = raw["info"]
                details = info.get("photo") if info.get("stat") == "ok" else None
                metadata = {"id": raw.get("id")}
                if isinstance(details, dict):
                    metadata.update(details)
                    location = details.get("location")
                    if isinstance(location, dict):
                        metadata.update({key: location.get(key) for key in ("latitude", "longitude")})
            photo = normalize(metadata, "afaq_historical")
            # Retain original region and all API responses, including failures.
            photo.raw = raw.copy()
        except (ValueError, TypeError):
            report["skipped"] += 1
            continue
        report["inserted" if store.save(photo) else "duplicates"] += 1
    return report
