"""Manual command: check each archive photo's Flickr state and cache its image. Free Flickr calls only.

Caching makes nothing visible. A restored photo waits in `atia images queue` for a person's review.
"""
import os
import time
from pathlib import Path
from atia.collectors.flickr import FlickrError
from atia.models import utc_now
from atia.vision.images import FlickrImageFetcher, ImageUnavailable
from .store import IntelligenceStore

DISPLAY_EDGE = 1024


def current_status(client, photo_id):
    try:
        photo = client.call('flickr.photos.getInfo', photo_id=photo_id).get('photo') or {}
    except FlickrError as exc:
        status = {'1': 'not_found', '2': 'no_permission'}.get(exc.code, 'error')
        return {'api_status': status, 'error_code': exc.code}
    owner = photo.get('owner') if isinstance(photo.get('owner'), dict) else {}
    urls = (photo.get('urls') or {}).get('url') or []
    page = next((u.get('_content') for u in urls if u.get('type') == 'photopage'), None)
    # Flickr safety levels above 0 are moderate or restricted; only a safe photo may be shown.
    restricted = str(photo.get('safety_level', '0')) != '0' or photo.get('media') not in (None, 'photo')
    return {'api_status': 'restricted' if restricted else 'ok', 'current_license_id': str(photo.get('license')) if photo.get('license') is not None else None,
            'safety_level': str(photo.get('safety_level')) if photo.get('safety_level') is not None else None,
            'owner_nsid': owner.get('nsid'), 'owner_name': owner.get('realname') or owner.get('username') or None, 'photo_page_url': page}


def restore_images(store, client, limit=None, refresh=False, fetcher=None, progress=None, pause=time.sleep):
    db = store.connection
    IntelligenceStore(db).initialize()
    emit = progress or (lambda message: None)
    database = db.execute('PRAGMA database_list').fetchone()[2]
    cache = Path(database).resolve().parent / 'images'
    fetcher = fetcher or FlickrImageFetcher(client, cache_dir=cache, preferred_edge=DISPLAY_EDGE)
    done = set() if refresh else {(r['source'], r['photo_id']) for r in db.execute(
        "SELECT s.source, s.photo_id FROM photo_flickr_status s JOIN photo_image_cache c ON c.source=s.source AND c.photo_id=s.photo_id WHERE s.api_status='ok'")}
    rows = [dict(r) for r in db.execute("SELECT * FROM photos WHERE source='afaq_historical' ORDER BY photo_id") if (r['source'], r['photo_id']) not in done]
    rows = rows[:limit] if limit else rows
    report = {'checked': 0, 'images_cached': 0, 'already_complete': len(done), 'api_status': {}, 'image_failures': {}}
    for index, row in enumerate(rows, 1):
        status = current_status(client, row['photo_id'])
        image_status, image_message = 'not_attempted', None
        if status['api_status'] == 'ok':
            try:
                asset = fetcher.fetch(row)
                path = os.path.relpath(asset.path)
                with db:
                    db.execute('INSERT OR REPLACE INTO photo_image_cache VALUES(?,?,?,?,?,?,?,?)', (row['source'], row['photo_id'], asset.sha256, path, asset.url, asset.width, asset.height, utc_now()))
                image_status = 'cached'
                report['images_cached'] += 1
            except ImageUnavailable as exc:
                image_status, image_message = 'failed', str(exc)
                report['image_failures'][str(exc)] = report['image_failures'].get(str(exc), 0) + 1
        with db:
            db.execute('INSERT OR REPLACE INTO photo_flickr_status VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', (
                row['source'], row['photo_id'], utc_now(), status['api_status'], status.get('error_code'), row['license_id'], status.get('current_license_id'),
                status.get('safety_level'), status.get('owner_nsid'), status.get('owner_name'), status.get('photo_page_url'), image_status, image_message))
        report['checked'] += 1
        report['api_status'][status['api_status']] = report['api_status'].get(status['api_status'], 0) + 1
        if index % 20 == 0:
            emit(f'{index}/{len(rows)} checked; {report["images_cached"]} images cached')
        pause(0.25)
    return report
