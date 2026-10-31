"""Approves test images through the real review path, so tests cannot bypass the display gate."""
from atia.intelligence.store import IntelligenceStore
from atia.moderation.display import ATTESTATIONS, cached_file, review_image
from atia.models import utc_now


def flickr_status(db, source, photo_id, license_id='11', api_status='ok', safety='0'):
    IntelligenceStore(db).initialize()
    with db:
        db.execute('INSERT OR REPLACE INTO photo_flickr_status VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (source, photo_id, utc_now(), api_status, None, license_id, license_id, safety, 'owner', 'Current Owner', 'https://www.flickr.com/photos/x/1/', 'cached', None))


def approve(db, source, photo_id, license_id='11', keep_status=False):
    if not keep_status:
        flickr_status(db, source, photo_id, license_id)
    sha = cached_file(db, source, photo_id)[1]
    return review_image(db, source, photo_id, sha, 'APPROVED', 'Test person', 'Viewed in test', dict.fromkeys(ATTESTATIONS, True))
