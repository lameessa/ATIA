"""The one gate for showing a photograph. Everything here fails closed.

Using a photo's metadata as evidence (policy.allowed) and showing its pixels are separate
permissions. A photograph is displayable only when all of these hold at the moment of the request:

- it may be used as evidence and has no uncertain or irrelevant visual review
- Flickr last reported it available, at safety level 0, under a licence that allows reuse
- a person's latest review approves these exact image bytes and attests to viewing them,
  to their safety and to the licence, or config/reviewed-images.json records an earlier visual
  review of these exact bytes and no later review overrides it

A reviewer name alone proves nothing, so approval is refused unless the automated checks pass first.
Source is never a reason to trust an image: archive and collected photos follow the same rules.
The reviewed list is a fixed file in version control. Nothing at runtime adds to it, so newly
retrieved photographs always wait for a person.
"""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sqlite3
from atia.intelligence.licences import interpret
from atia.models import utc_now
from .policy import allowed, exists

SAFE_FLICKR_LEVEL = '0'
ATTESTATIONS = ('viewed_image', 'image_is_safe', 'licence_confirmed')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS image_display_reviews (
  review_id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, photo_id TEXT NOT NULL, image_sha256 TEXT NOT NULL,
  decision TEXT NOT NULL CHECK(decision IN ('APPROVED','REJECTED','UNCERTAIN')), reviewer TEXT NOT NULL,
  reviewer_kind TEXT NOT NULL CHECK(reviewer_kind IN ('human','assistant')), attestations TEXT NOT NULL,
  license_id TEXT, reason TEXT NOT NULL, reviewed_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS image_display_latest ON image_display_reviews(source, photo_id, review_id);
'''
REVIEWED_IMAGES = Path(__file__).resolve().parents[3] / 'config' / 'reviewed-images.json'
_CACHE_TABLES = {'flickr_live': ('moderation_asset_cache',), 'afaq_historical': ('photo_image_cache', 'tourism_relevance', 'visual_dimension_analyses', 'visual_analyses')}


def initialize(db):
    db.executescript(SCHEMA)


@lru_cache(maxsize=1)
def _reviewed_images():
    """A missing or unreadable list grants nothing."""
    try:
        images = json.loads(REVIEWED_IMAGES.read_text(encoding='utf-8'))['images']
        return {(item['source'], item['photo_id']): item for item in images}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def earlier_review(source, photo_id):
    return _reviewed_images().get((source, photo_id))


def reviewed_images():
    return list(_reviewed_images().values())


def _rows(db, table, source, photo_id):
    if not exists(db, table):
        return []
    query, args = f'SELECT image_path, image_sha256 FROM {table} WHERE photo_id=?', [photo_id]
    if table != 'moderation_asset_cache':
        query += ' AND source=?'
        args.append(source)
    return db.execute(query + ' ORDER BY rowid DESC', args).fetchall()


def cached_file(db, source, photo_id, sha256=None):
    """A cached image inside the data folder whose bytes match its recorded hash. No display decision."""
    root = Path(db.execute('PRAGMA database_list').fetchone()[2]).resolve().parent
    for table in _CACHE_TABLES.get(source, ()):
        for row in _rows(db, table, source, photo_id):
            path = Path(row[0]).resolve()
            if (sha256 is None or row[1] == sha256) and path.is_relative_to(root) and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == row[1]:
                return path, row[1]
    return None, None


def automated_block(db, source, photo_id):
    """Why the automated checks refuse this photo, or None. These apply before and after review."""
    if source not in _CACHE_TABLES:
        return 'unknown source'
    if not allowed(db, source, photo_id) and not earlier_review(source, photo_id):
        return 'not cleared as evidence'
    if source == 'flickr_live' and exists(db, 'photo_moderation') and db.execute("SELECT 1 FROM photo_moderation WHERE photo_id=? AND (status='removed' OR review_status='REJECTED')", (photo_id,)).fetchone():
        return 'rejected in moderation'
    if exists(db, 'photo_removal_audit') and source == 'flickr_live' and db.execute('SELECT 1 FROM photo_removal_audit WHERE photo_id=?', (photo_id,)).fetchone():
        return 'retired'
    if exists(db, 'visual_review_labels'):
        label = db.execute('SELECT label FROM visual_review_labels WHERE source=? AND photo_id=? ORDER BY reviewed_at DESC LIMIT 1', (source, photo_id)).fetchone()
        if label and label[0] in ('uncertain', 'irrelevant'):
            return f'visual review: {label[0]}'
    if not exists(db, 'photo_flickr_status'):
        return 'Flickr status not checked'
    status = db.execute('SELECT api_status, safety_level, current_license_id FROM photo_flickr_status WHERE source=? AND photo_id=?', (source, photo_id)).fetchone()
    if not status:
        return 'Flickr status not checked'
    if status[0] != 'ok':
        return f'Flickr status: {status[0]}'
    if str(status[1]) != SAFE_FLICKR_LEVEL:
        return 'Flickr safety level is not safe'
    if not interpret(status[2])['campaign_eligible']:
        return 'licence does not allow reuse'
    return None


def latest_review(db, source, photo_id):
    if not exists(db, 'image_display_reviews'):
        return None
    return db.execute('SELECT * FROM image_display_reviews WHERE source=? AND photo_id=? ORDER BY review_id DESC LIMIT 1', (source, photo_id)).fetchone()


def display_block(db, source, photo_id):
    """Why this photo must not be shown, or None. Any failure to establish safety blocks it."""
    try:
        reason = automated_block(db, source, photo_id)
        if reason:
            return reason
        review = latest_review(db, source, photo_id)
        if not review:
            earlier = earlier_review(source, photo_id)
            if not earlier:
                return 'not reviewed'
            return None if cached_file(db, source, photo_id, earlier['image_sha256'])[0] else 'image bytes differ from those reviewed'
        decision, kind, sha, attested = review[4], review[6], review[3], json.loads(review[7])
        if decision != 'APPROVED':
            return f'review: {decision.lower()}'
        if kind != 'human':
            return 'not reviewed by a person'
        if not all(attested.get(item) is True for item in ATTESTATIONS):
            return 'review attestations incomplete'
        if cached_file(db, source, photo_id, sha)[0] is None:
            return 'image bytes differ from those reviewed'
        return None
    except (sqlite3.Error, OSError, ValueError, TypeError, IndexError):
        return 'safety could not be established'


def can_display(db, source, photo_id):
    return display_block(db, source, photo_id) is None


def displayable_file(db, source, photo_id):
    if not can_display(db, source, photo_id):
        return None
    review = latest_review(db, source, photo_id)
    return cached_file(db, source, photo_id, review[3] if review else earlier_review(source, photo_id)['image_sha256'])[0]


def review_image(db, source, photo_id, sha256, decision, reviewer, reason, attestations=None, reviewer_kind='human'):
    """Append a review. Approval needs a person, the exact image hash, all attestations and passing automated checks."""
    initialize(db)
    if decision not in ('APPROVED', 'REJECTED', 'UNCERTAIN'):
        raise ValueError('Unknown decision')
    if not reviewer.strip() or not reason.strip():
        raise ValueError('A review needs a reviewer and a reason')
    attestations = attestations or {}
    _, current = cached_file(db, source, photo_id)
    if decision == 'APPROVED':
        if reviewer_kind != 'human':
            raise ValueError('Only a person can approve an image for display')
        blocked = automated_block(db, source, photo_id)
        if blocked:
            raise ValueError(f'Cannot approve: {blocked}')
        if current is None:
            raise ValueError('Cannot approve: no valid cached image')
        if sha256 != current:
            raise ValueError('Cannot approve: this hash is not the current image')
        if not all(attestations.get(item) is True for item in ATTESTATIONS):
            raise ValueError('Cannot approve: confirm you viewed the image, that it is safe and that the licence is correct')
    status = db.execute('SELECT current_license_id FROM photo_flickr_status WHERE source=? AND photo_id=?', (source, photo_id)).fetchone() if exists(db, 'photo_flickr_status') else None
    with db:
        db.execute('INSERT INTO image_display_reviews(source,photo_id,image_sha256,decision,reviewer,reviewer_kind,attestations,license_id,reason,reviewed_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (source, photo_id, sha256 or current or '', decision, reviewer.strip(), reviewer_kind, json.dumps(attestations), status[0] if status else None, reason.strip(), utc_now()))
    return {'source': source, 'photo_id': photo_id, 'decision': decision, 'displayable': can_display(db, source, photo_id)}


def review_queue(db, limit=None):
    """Photos whose automated checks pass and that still need a person. Paths are local and never served."""
    queue = []
    for row in db.execute('SELECT source, photo_id, title FROM photos ORDER BY source, photo_id'):
        source, photo_id = row[0], row[1]
        if automated_block(db, source, photo_id) or latest_review(db, source, photo_id) or earlier_review(source, photo_id):
            continue
        path, sha = cached_file(db, source, photo_id)
        if path:
            queue.append({'source': source, 'photo_id': photo_id, 'title': row[2], 'image_sha256': sha, 'local_file': str(path)})
    return queue[:limit] if limit else queue
