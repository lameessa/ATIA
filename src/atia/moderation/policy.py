import json
import re
from atia.models import utc_now

VERSION='quarantine-two-dimensions-manual-release-v1'


def exists(db,table):
    return bool(db.execute("SELECT 1 FROM main.sqlite_master WHERE type='table' AND name=?",(table,)).fetchone())


def initialize(db):
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS photo_moderation (
      photo_id TEXT PRIMARY KEY,status TEXT NOT NULL CHECK(status IN ('quarantined','awaiting_approval','approved','removed')),
      quarantined_at TEXT NOT NULL,relevance TEXT NOT NULL DEFAULT 'not_evaluated',
      safety TEXT NOT NULL DEFAULT 'not_evaluated',evaluation_json TEXT,reviewer TEXT,reviewed_at TEXT,review_reason TEXT);
    CREATE TABLE IF NOT EXISTS photo_removal_audit (
      photo_id TEXT PRIMARY KEY,reason TEXT NOT NULL,removed_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS moderation_asset_cache (
      photo_id TEXT PRIMARY KEY,image_sha256 TEXT NOT NULL,image_path TEXT NOT NULL,image_url TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS moderation_runs (
      run_id TEXT PRIMARY KEY,started_at TEXT NOT NULL,completed_at TEXT,report TEXT);
    ''')
    columns={r[1] for r in db.execute('PRAGMA table_info(photo_moderation)')}
    if 'review_status' not in columns:
        db.execute("ALTER TABLE photo_moderation ADD COLUMN review_status TEXT CHECK(review_status IN ('REJECTED','PENDING_REVIEW','APPROVED') OR review_status IS NULL)")
    with db:
        db.execute("INSERT OR IGNORE INTO photo_moderation(photo_id,status,quarantined_at) SELECT photo_id,'quarantined',? FROM photos WHERE source='flickr_live'",(utc_now(),))
    from .display import initialize as initialize_display
    initialize_display(db)
    view=db.execute("SELECT sql FROM sqlite_master WHERE type='view' AND name='active_photos'").fetchone()
    if view and ('reviewed_at' not in view[0] or 'review_status' not in view[0]):
        db.execute('DROP VIEW IF EXISTS active_destination_photo_assignments');db.execute('DROP VIEW active_photos')
    db.executescript('''CREATE VIEW IF NOT EXISTS active_photos AS SELECT p.* FROM photos p
      WHERE p.source='afaq_historical' OR (p.source='flickr_live' AND EXISTS
      (SELECT 1 FROM photo_moderation m WHERE m.photo_id=p.photo_id AND m.status='approved' AND m.relevance='relevant' AND m.safety='pass' AND m.reviewer IS NOT NULL AND m.reviewed_at IS NOT NULL AND coalesce(m.review_status,'')!='REJECTED'));''')
    if exists(db,'destination_photo_assignments'):
        db.execute('''CREATE VIEW IF NOT EXISTS active_destination_photo_assignments AS SELECT a.* FROM destination_photo_assignments a
          JOIN active_photos p ON p.source=a.source AND p.photo_id=a.photo_id''')


def visible_sql(db,alias='p'):
    curated=f"{alias}.source='afaq_historical'"
    if not exists(db,'photo_moderation'):return '('+curated+')'
    if 'review_status' not in {r[1] for r in db.execute('PRAGMA main.table_info(photo_moderation)')}:return '('+curated+')'
    return f"({curated} OR ({alias}.source='flickr_live' AND EXISTS (SELECT 1 FROM main.photo_moderation m WHERE m.photo_id={alias}.photo_id AND m.status='approved' AND m.relevance='relevant' AND m.safety='pass' AND m.reviewer IS NOT NULL AND m.reviewed_at IS NOT NULL AND coalesce(m.review_status,'')!='REJECTED')) )"


def allowed(db,source,photo_id):
    """May this photo's metadata count as evidence? This never permits showing it: see display.py."""
    if source=='afaq_historical':return True
    if source!='flickr_live' or not exists(db,'photo_moderation'):return False
    if 'review_status' not in {r[1] for r in db.execute('PRAGMA main.table_info(photo_moderation)')}:return False
    return bool(db.execute("SELECT 1 FROM photo_moderation WHERE photo_id=? AND status='approved' AND relevance='relevant' AND safety='pass' AND reviewer IS NOT NULL AND reviewed_at IS NOT NULL AND coalesce(review_status,'')!='REJECTED'",(photo_id,)).fetchone())


def blocked_ids(db):
    ids={r[0] for r in db.execute("SELECT photo_id FROM main.photos WHERE source='flickr_live'") if not allowed(db,'flickr_live',r[0])}
    if exists(db,'photo_removal_audit'):ids.update(r[0] for r in db.execute('SELECT photo_id FROM photo_removal_audit'))
    # An archive record with the same ID keeps its metadata as evidence; display.py still governs its pixels.
    ids.difference_update(r[0] for r in db.execute("SELECT photo_id FROM main.photos WHERE source='afaq_historical'"))
    return ids


def clean_evidence(db,value):
    text=json.dumps(value,ensure_ascii=False,default=str)
    return not any(re.search(r'(?<!\d)'+re.escape(str(i))+r'(?!\d)',text) for i in blocked_ids(db))


def presentation_connection(db):
    """TEMP projection shadows raw photos on this presentation-only connection."""
    db.execute('CREATE TEMP VIEW photos AS SELECT p.* FROM main.photos p WHERE '+visible_sql(db))


def visible_group(db,group):
    from atia.destinations.evidence import EvidenceIndex
    records=[dict(r) for r in db.execute('SELECT p.* FROM main.photos p WHERE '+visible_sql(db)+' ORDER BY p.source,p.photo_id') if r['photo_id'] in group['photo_ids']]
    if not records:return None
    result=dict(group)
    result['photo_ids']=sorted({r['photo_id'] for r in records})
    result['evidence']=EvidenceIndex(db,records).aggregate(records)
    valid=[r for r in records if r['latitude'] is not None and r['longitude'] is not None]
    if valid:
        result['centroid']={'latitude':sum(r['latitude'] for r in valid)/len(valid),'longitude':sum(r['longitude'] for r in valid)/len(valid),'note':'Approved/curated photograph centroid, not a verified attraction.'}
        result['bbox']=[min(r['longitude'] for r in valid),min(r['latitude'] for r in valid),max(r['longitude'] for r in valid),max(r['latitude'] for r in valid)]
    from collections import Counter
    result['sampling_macro_regions']=dict(Counter(r['region'] or json.loads(r['raw']).get('historical_region') or 'unknown' for r in records))
    result['warnings']=[w for w in group.get('warnings',[]) if w not in ('screened_irrelevant_content_present','reviewed_irrelevant_content_present')]
    result['warnings'].append('presentation_evidence_excludes_unapproved_live_photographs')
    return result
