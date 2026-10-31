"""Bounded regional collection with immediate persistence and safe progress."""
import time
import uuid
from atia.collectors.flickr import FlickrError
from atia.collectors.regions import REGIONS, REGION_SCHEME, region_for
from atia.models import normalize, number


def collect_regions(client, store, per_region=10, max_pages=16,
                    region_seconds=180, progress=None):
    if per_region < 1 or max_pages < 1 or region_seconds <= 0:
        raise ValueError("Quotas, page limits, and time budget must be positive")
    started = time.monotonic()
    emit = progress or (lambda message: None)
    report = {"run_id": str(uuid.uuid4()), "scheme": REGION_SCHEME,
              "requested": per_region * len(REGIONS), "regions": {}, "warnings": []}
    emit("Resolving Saudi country identity...")
    country = client.saudi_woe_id()
    try:
        licenses = client.licenses()
    except FlickrError:
        licenses = {}
        report["warnings"].append("License names unavailable; supplied license IDs retained.")
    for region in REGIONS:
        region_start = time.monotonic()
        result = {"target": per_region, "inserted": 0, "duplicates": 0,
                  "skipped": 0, "checked": 0, "errors": 0, "pages": 0, "bbox": list(region.bbox),
                  "photo_ids": [], "stop_reason": "page_limit"}
        report["regions"][region.name] = result
        emit(f"[{region.name}] Starting; target {per_region}; bbox {region.query_bbox}")
        seen = set()
        try:
            for page in range(1, min(max_pages, 16) + 1):
                if time.monotonic() - region_start >= region_seconds:
                    result["stop_reason"] = "time_budget"
                    break
                emit(f"[{region.name}] Searching page {page}; saved {result['inserted']}/{per_region}")
                candidates = client.search_candidates(region.query_bbox, page, 50)
                result["pages"] += 1
                for raw in candidates["photo"]:
                    if time.monotonic() - region_start >= region_seconds:
                        result["stop_reason"] = "time_budget"
                        break
                    if not isinstance(raw, dict) or not str(raw.get("id", "")).isdigit():
                        result["skipped"] += 1
                        continue
                    photo_id = str(raw["id"])
                    if photo_id in seen or store.contains_any(photo_id):
                        result["duplicates"] += 1
                        continue
                    seen.add(photo_id)
                    # Reject invalid/out-of-zone search coordinates before spending
                    # another API call. Verified location coordinates decide storage.
                    candidate = normalize(raw, "flickr_live", licenses)
                    if candidate.latitude is None or region_for(candidate.latitude, candidate.longitude) != region.name:
                        result["skipped"] += 1
                        continue
                    if result["checked"] % 10 == 0:
                        emit(f"[{region.name}] Checking locations; checked {result['checked']}; saved {result['inserted']}/{per_region}")
                    result["checked"] += 1
                    try:
                        location = client.verify_location(photo_id, country)
                    except FlickrError as exc:
                        if exc.code == "100":
                            raise
                        result["errors"] += 1
                        emit(f"[{region.name}] Location check failed; continuing ({result['errors']}/3)")
                        if result["errors"] >= 3:
                            result["stop_reason"] = "api_errors"
                            break
                        continue
                    if not location:
                        result["skipped"] += 1
                        continue
                    lat, lon = number(location.get("latitude")), number(location.get("longitude"))
                    if lat is None or lon is None or region_for(lat, lon) != region.name:
                        result["skipped"] += 1
                        continue
                    candidate = normalize({**raw, "latitude": lat, "longitude": lon,
                        "country_verification": location["country"],
                        "collection_region": region.name, "region_scheme": REGION_SCHEME,
                        "collection_run_id": report["run_id"]}, "flickr_live", licenses)
                    candidate.region = region.name
                    if store.save(candidate):
                        result["inserted"] += 1
                        result["photo_ids"].append(photo_id)
                        emit(f"[{region.name}] Saved {result['inserted']}/{per_region}")
                    else:
                        result["duplicates"] += 1
                    if result["inserted"] >= per_region:
                        result["stop_reason"] = "quota_reached"
                        break
                if result["stop_reason"] in {"quota_reached", "time_budget", "api_errors"}:
                    break
                try:
                    pages = int(candidates.get("pages", 1))
                except (ValueError, TypeError):
                    raise FlickrError("Invalid Flickr pagination metadata.") from None
                if not candidates["photo"] or page >= pages:
                    result["stop_reason"] = "exhausted"
                    break
        except FlickrError as exc:
            result["errors"] += 1
            result["stop_reason"] = "api_error"
            result["error"] = str(exc)
        result["shortfall"] = per_region - result["inserted"]
        result["elapsed_seconds"] = round(time.monotonic() - region_start, 2)
        emit(f"[{region.name}] Finished: {result['inserted']}/{per_region}; "
             f"duplicates {result['duplicates']}; shortfall {result['shortfall']}; "
             f"{result['elapsed_seconds']}s ({result['stop_reason']})")
    report["inserted"] = sum(row["inserted"] for row in report["regions"].values())
    report["duplicates"] = sum(row["duplicates"] for row in report["regions"].values())
    report["complete"] = report["inserted"] == report["requested"]
    report["elapsed_seconds"] = round(time.monotonic() - started, 2)
    return report
