"""Shared, source-independent record. Capture times retain their unknown timezone."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def number(value, integer=False):
    try:
        result = float(value)
        if not math.isfinite(result) or (integer and not result.is_integer()):
            return None
        return int(result) if integer else result
    except (TypeError, ValueError, OverflowError):
        return None


def upload_date(value):
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError, OSError):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            # Do not invent a timezone for historical date strings.
            return parsed.isoformat()
        except ValueError:
            return None


def capture_date(value):
    try:
        return datetime.fromisoformat(str(value)).isoformat(sep=" ")
    except (ValueError, TypeError):
        return None


@dataclass
class Photo:
    photo_id: str
    source: str
    title: str
    latitude: float | None
    longitude: float | None
    uploaded_at: str | None
    captured_at: str | None
    capture_granularity: str | None
    capture_unknown: bool | None
    views: int | None
    tags: list[str]
    license_id: str | None
    license_name: str | None
    license_url: str | None
    owner_id: str | None
    photo_url: str | None
    collected_at: str
    raw: dict
    region: str | None = None

    def to_dict(self):
        return asdict(self)


def normalize(raw, source, licenses=None):
    if source not in {"flickr_live", "afaq_historical"}:
        raise ValueError("Unknown record source")
    photo_id = raw.get("id", raw.get("photo_id"))
    if photo_id is None or not str(photo_id).strip():
        raise ValueError("Missing photo ID")
    photo_id = str(photo_id).strip()
    latitude = number(raw.get("latitude", raw.get("lat")))
    longitude = number(raw.get("longitude", raw.get("lon")))
    if latitude is None or longitude is None or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        latitude = longitude = None
    tags = raw.get("tags") or []
    if isinstance(tags, str):
        tags = tags.split()
    elif isinstance(tags, dict):
        tags = [tag.get("raw", tag.get("_content", "")) for tag in tags.get("tag", []) if isinstance(tag, dict)]
    if not isinstance(tags, list):
        tags = []
    tags = [str(tag) for tag in tags if isinstance(tag, (str, int))]
    dates = raw.get("dates") if isinstance(raw.get("dates"), dict) else {}
    license_id = raw.get("license", raw.get("license_id"))
    license_id = str(license_id) if license_id is not None else None
    license_info = (licenses or {}).get(license_id, {})
    owner = raw.get("owner", raw.get("owner_id"))
    if isinstance(owner, dict):
        owner = owner.get("nsid")
    title = raw.get("title") or ""
    if isinstance(title, dict):
        title = title.get("_content", "")
    unknown = raw.get("datetakenunknown", dates.get("takenunknown"))
    views = number(raw.get("views"), integer=True)
    return Photo(
        photo_id, source, str(title), latitude, longitude,
        upload_date(raw.get("dateupload", raw.get("date_upload", raw.get("uploaded_at", dates.get("posted"))))),
        capture_date(raw.get("datetaken", raw.get("date_taken", raw.get("captured_at", dates.get("taken"))))),
        str(raw.get("datetakengranularity", dates.get("takengranularity"))) if raw.get("datetakengranularity", dates.get("takengranularity")) is not None else None,
        str(unknown) == "1" if unknown is not None else None,
        views if views is None or views >= 0 else None, list(dict.fromkeys(tags)),
        license_id, license_info.get("name"), license_info.get("url"),
        str(owner) if owner else None,
        f"https://www.flickr.com/photos/{owner}/{photo_id}/" if owner else None,
        utc_now(), raw.copy(),
    )
