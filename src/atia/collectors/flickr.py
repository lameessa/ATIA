"""Official REST API only. Never log request URLs containing credentials."""
import os
import time
import requests
from atia.models import normalize


class FlickrError(RuntimeError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def live_client(api_key):
    """Manual commands only. A key alone never enables retrieval."""
    if os.getenv("ATIA_ENABLE_LIVE_FLICKR", "").strip() != "1":
        raise FlickrError("Live Flickr retrieval is off. Set ATIA_ENABLE_LIVE_FLICKR=1 for this command. New images stay hidden until a person reviews them.")
    return FlickrClient(api_key)


class FlickrClient:
    endpoint = "https://www.flickr.com/services/rest/"

    def __init__(self, api_key, session=None, attempts=3, pause=time.sleep):
        if not api_key:
            raise FlickrError("Set FLICKR_API_KEY in your local .env before collecting.")
        self.api_key = api_key
        self.session = session or requests.Session()
        self.attempts = max(1, attempts)
        self.pause = pause

    def call(self, method, **params):
        for attempt in range(self.attempts):
            retry = False
            try:
                response = self.session.get(self.endpoint, params={
                    **params, "method": method, "api_key": self.api_key,
                    "format": "json", "nojsoncallback": 1}, timeout=(10, 30))
                if response.status_code == 429 or response.status_code >= 500:
                    retry = True
                    error = FlickrError("Flickr temporarily unavailable or rate limited.")
                elif response.status_code != 200:
                    raise FlickrError(f"Flickr HTTP error {response.status_code}.")
                else:
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise FlickrError("Unexpected Flickr response structure.")
                    if payload.get("stat") == "ok":
                        return payload
                    code = str(payload.get("code", "unknown"))
                    # Do not surface remote messages that could echo secrets.
                    error = FlickrError(f"Flickr API error {code}.", code=code)
                    retry = code in {"10", "105", "106"}
            except requests.RequestException:
                error = FlickrError("Unable to reach Flickr (network or timeout).")
                retry = True
            except ValueError:
                error = FlickrError("Flickr returned invalid JSON.")
                retry = True
            if not retry or attempt + 1 == self.attempts:
                raise error from None
            self.pause(2 ** attempt)
        raise FlickrError("Flickr request failed.")

    def saudi_woe_id(self):
        payload = self.call("flickr.places.find", query="Saudi Arabia")
        for place in payload.get("places", {}).get("place", []):
            if str(place.get("place_type")) == "country" and str(place.get("woeid", "")).isdigit():
                # Exact country match prevents accidentally selecting a locality.
                if place.get("_content", "").strip().casefold() == "saudi arabia":
                    return str(place["woeid"])
        # Flickr name search can return no results for this country. Verify its
        # stable WOE identifier against getInfo rather than widening the search.
        place = self.call("flickr.places.getInfo", woe_id="23424938").get("place", {})
        name = str(place.get("woe_name", place.get("name", ""))).strip(" ,")
        if str(place.get("woeid")) == "23424938" and name.casefold() in {"saudi arabia", "السعودية", "المملكة العربية السعودية"}:
            return "23424938"
        raise FlickrError("Flickr did not resolve Saudi Arabia to a country; collection stopped.")

    def licenses(self):
        items = self.call("flickr.photos.licenses.getInfo").get("licenses", {}).get("license", [])
        return {str(item["id"]): item for item in items if "id" in item}

    def search(self, country, page, per_page):
        payload = self.call("flickr.photos.search", bbox="34,16,56,33", has_geo=1,
            media="photos", content_types=0, safe_search=1, min_upload_date=0,
            sort="date-posted-desc", page=page, per_page=per_page,
            extras="geo,date_upload,date_taken,views,tags,license,owner_name")
        photos = payload.get("photos")
        if not isinstance(photos, dict) or not isinstance(photos.get("photo"), list):
            raise FlickrError("Unexpected Flickr search response.")
        verified = []
        for raw in photos["photo"]:
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            location = self.verify_location(raw["id"], country)
            if location:
                verified.append({**raw, "country_verification": location["country"]})
        return {**photos, "photo": verified, "candidate_count": len(photos["photo"])}

    def search_candidates(self, bbox, page, per_page=50):
        payload = self.call("flickr.photos.search", bbox=bbox, has_geo=1,
            media="photos", content_types=0, safe_search=1, min_upload_date=0,
            sort="date-posted-desc", page=page, per_page=per_page,
            extras="geo,date_upload,date_taken,views,tags,license,owner_name")
        result = payload.get("photos")
        if not isinstance(result, dict) or not isinstance(result.get("photo"), list):
            raise FlickrError("Unexpected Flickr search response.")
        return result

    def verify_location(self, photo_id, country):
        try:
            location = self.call("flickr.photos.geo.getLocation", photo_id=photo_id).get("photo", {}).get("location", {})
        except FlickrError as exc:
            if exc.code in {"1", "2"}:
                return None
            raise
        if not isinstance(location, dict):
            return None
        country_info = location.get("country")
        if not isinstance(country_info, dict):
            return None
        country_name = str(country_info.get("_content", "")).strip().casefold()
        matches = str(country_info.get("woeid")) == str(country)
        if country_info.get("woeid") is None:
            matches = country_name in {"saudi arabia", "السعودية", "المملكة العربية السعودية"}
        return location if matches else None


def collect(client, store, limit=50, max_pages=16):
    """Target newly stored rows, including on repeated runs; bounded by API search cap."""
    if limit < 1 or max_pages < 1:
        raise ValueError("limit and max_pages must be positive")
    report = {"requested": limit, "inserted": 0, "duplicates": 0, "skipped": 0,
              "pages": 0, "warnings": [], "complete": False}
    country = client.saudi_woe_id()
    try:
        licenses = client.licenses()
    except FlickrError:
        licenses = {}
        report["warnings"].append("License names unavailable; license IDs retained where present.")
    for page in range(1, min(max_pages, 16) + 1):
        # 250 * 16 matches Flickr's documented 4,000-result search cap.
        result = client.search(country, page, min(250, limit))
        report["pages"] += 1
        for raw in result["photo"]:
            if not isinstance(raw, dict):
                report["skipped"] += 1
                continue
            try:
                photo = normalize(raw, "flickr_live", licenses)
            except (ValueError, TypeError):
                report["skipped"] += 1
                continue
            if photo.latitude is None or (photo.latitude == 0 and photo.longitude == 0):
                report["skipped"] += 1
                continue
            if store.save(photo):
                report["inserted"] += 1
            else:
                report["duplicates"] += 1
            if report["inserted"] == limit:
                report["complete"] = True
                return report
        try:
            pages = int(result.get("pages", 1))
        except (ValueError, TypeError):
            raise FlickrError("Invalid Flickr pagination metadata.") from None
        if result.get("candidate_count", len(result["photo"])) == 0 or page >= pages:
            break
    return report
