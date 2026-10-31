"""A small licence-filtered Flickr search for campaign images. Free API calls only.

Candidates stay hidden. Accepting one links it to an opportunity; display needs a person's image review.
"""
import re
from atia.intelligence.images import DISPLAY_EDGE, current_status
from atia.intelligence.licences import LICENCES, CAMPAIGN_ELIGIBLE, interpret
from atia.intelligence.store import IntelligenceStore
from atia.intelligence.taxonomy import normalize
from atia.models import normalize as normalize_photo, utc_now
from atia.moderation.display import can_display
from atia.moderation.policy import initialize as initialize_moderation
from atia.vision.images import FlickrImageFetcher, ImageUnavailable
from .store import OpportunityStore, initialize

SAUDI_WOEID = '23424938'
MIN_EDGE = 640
MAX_PER_OWNER = 4
ELIGIBLE_LICENSE_IDS = ','.join(key for key, value in LICENCES.items() if value[2] == CAMPAIGN_ELIGIBLE)


def search_licensed(client, query, per_page=100):
    """Flickr filters by licence and safety; the bbox and getLocation check keep it to Saudi Arabia.
    One short query at a time, because Flickr requires every word in a text search to match."""
    seen = {}
    for text in query['queries']:
        payload = client.call('flickr.photos.search', text=text, bbox=query['bbox'], license=ELIGIBLE_LICENSE_IDS, has_geo=1, safe_search=1, content_types=0, media='photos',
                              sort='relevance', page=1, per_page=per_page, extras='geo,date_upload,date_taken,views,tags,license,owner_name,description')
        for raw in (payload.get('photos') or {}).get('photo') or []:
            seen.setdefault(str(raw.get('id')), raw)
    return list(seen.values())


def relevant(raw, terms):
    description = raw.get('description')
    description = description.get('_content') if isinstance(description, dict) else description
    text = normalize(' '.join(str(v or '') for v in (raw.get('title'), raw.get('tags'), description)))
    return any(re.search(r'(?<![a-z])' + re.escape(normalize(term)), text) for term in terms)


def find_images(store, client, wanted=8, fetcher=None, opportunity_id=None):
    db = store.connection
    initialize(db)
    initialize_moderation(db)
    IntelligenceStore(db).initialize()
    fetcher = fetcher or FlickrImageFetcher(client, preferred_edge=DISPLAY_EDGE)
    report = {}
    for opportunity in OpportunityStore(db).opportunities():
        query = opportunity.get('image_search')
        if not query or (opportunity_id and opportunity['opportunity_id'] != opportunity_id):
            continue
        result = {'searched': 0, 'already_in_archive': 0, 'off_topic': 0, 'not_saudi': 0, 'failed': 0, 'candidates': []}
        owners = {}
        for raw in search_licensed(client, query):
            if len(result['candidates']) >= wanted:
                break
            result['searched'] += 1
            photo_id, owner = str(raw.get('id')), raw.get('owner')
            if owners.get(owner, 0) >= MAX_PER_OWNER:
                continue
            if db.execute("SELECT 1 FROM photos WHERE source='afaq_historical' AND photo_id=?", (photo_id,)).fetchone():
                result['already_in_archive'] += 1
                continue
            if not relevant(raw, query['must_match']):
                result['off_topic'] += 1
                continue
            location = client.verify_location(photo_id, SAUDI_WOEID)
            if not location:
                result['not_saudi'] += 1
                continue
            status = current_status(client, photo_id)
            if status['api_status'] != 'ok' or not interpret(status.get('current_license_id'))['campaign_eligible']:
                result['failed'] += 1
                continue
            try:
                asset = fetcher.fetch({'source': 'flickr_live', 'photo_id': photo_id})
            except ImageUnavailable:
                result['failed'] += 1
                continue
            if max(asset.width, asset.height) < MIN_EDGE:
                result['failed'] += 1
                continue
            photo = normalize_photo({**raw, 'country_verification': location.get('country')}, 'flickr_live', {key: {'name': value[0], 'url': value[1]} for key, value in LICENCES.items()})
            store.save(photo)
            now = utc_now()
            with db:
                db.execute('INSERT OR REPLACE INTO moderation_asset_cache VALUES(?,?,?,?)', (photo_id, asset.sha256, asset.path, asset.url))
                db.execute("INSERT OR IGNORE INTO photo_moderation(photo_id,status,quarantined_at) VALUES(?,'quarantined',?)", (photo_id, now))
                db.execute('INSERT OR REPLACE INTO photo_flickr_status VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', ('flickr_live', photo_id, now, status['api_status'], None, photo.license_id, status.get('current_license_id'),
                           status.get('safety_level'), status.get('owner_nsid'), status.get('owner_name'), status.get('photo_page_url'), 'cached', None))
                db.execute("INSERT OR IGNORE INTO opportunity_images(opportunity_id,source,photo_id,status,found_at) VALUES(?,'flickr_live',?,'candidate',?)", (opportunity['opportunity_id'], photo_id, now))
            owners[owner] = owners.get(owner, 0) + 1
            result['candidates'].append({'photo_id': photo_id, 'title': photo.title, 'license': interpret(status.get('current_license_id'))['name'], 'owner': status.get('owner_name'), 'path': asset.path})
        report[opportunity['opportunity_id']] = result
    return report


def review_image(db, opportunity_id, photo_id, accept, reviewer, reason):
    """Decides whether a photo suits this opportunity. It says nothing about safety and shows nothing:
    display still needs a person's review through `atia images review`."""
    if not reviewer.strip() or not reason.strip():
        raise ValueError('Image review needs a reviewer and a reason')
    row = db.execute('SELECT * FROM opportunity_images WHERE opportunity_id=? AND photo_id=?', (opportunity_id, photo_id)).fetchone()
    if not row:
        raise ValueError('Not a candidate for this opportunity')
    if accept:
        status = db.execute("SELECT current_license_id FROM photo_flickr_status WHERE source='flickr_live' AND photo_id=? AND api_status='ok'", (photo_id,)).fetchone()
        if not status or not interpret(status['current_license_id'])['campaign_eligible']:
            raise ValueError('Licence is not eligible for campaign use')
    with db:
        db.execute('UPDATE opportunity_images SET status=?, reviewer=?, reason=?, reviewed_at=? WHERE opportunity_id=? AND photo_id=?', ('accepted' if accept else 'rejected', reviewer, reason, utc_now(), opportunity_id, photo_id))
    return {'opportunity_id': opportunity_id, 'photo_id': photo_id, 'status': 'accepted' if accept else 'rejected', 'displayable': False if not accept else can_display(db, 'flickr_live', photo_id)}
