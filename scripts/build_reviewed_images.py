"""Maintainer tool: writes config/reviewed-images.json and demo/images from a private database, read-only.

An entry needs a recorded visual review of these exact bytes that found the image relevant and safe, and a
licence Flickr reported as reusable. This records earlier reviews; it never creates one. Usage:
scripts/build_reviewed_images.py DATABASE INSPECTIONS.json REGIONAL_BASELINE_DATABASE
"""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
from atia.intelligence.licences import interpret

ROOT = Path(__file__).resolve().parents[1]
INSPECTION_TYPE = 'assistant_visual_inspection_not_user_approval'
OPPORTUNITY_REVIEW_TYPE = 'assistant_visual_check_not_user_approval'


def entry(db, photo_id, sha256, collection, reviewer, review_type, reviewed_at, reason, opportunity_id=None):
    status = db.execute("SELECT * FROM photo_flickr_status WHERE source='flickr_live' AND photo_id=?", (photo_id,)).fetchone()
    cache = db.execute('SELECT image_sha256, image_path FROM moderation_asset_cache WHERE photo_id=?', (photo_id,)).fetchone()
    if not status or status['api_status'] != 'ok' or str(status['safety_level']) != '0' or not interpret(status['current_license_id'])['campaign_eligible']:
        return None
    if not cache or cache['image_sha256'] != sha256 or hashlib.sha256(Path(cache['image_path']).read_bytes()).hexdigest() != sha256:
        return None
    photo = db.execute("SELECT title, region FROM photos WHERE source='flickr_live' AND photo_id=?", (photo_id,)).fetchone()
    return {'source': 'flickr_live', 'photo_id': photo_id, 'image_sha256': sha256, 'collection': collection, 'reviewer': reviewer, 'review_type': review_type,
            'reviewed_at': reviewed_at, 'reason': reason, 'relevance': 'relevant', 'safety': 'pass', 'license_id': status['current_license_id'], 'license_checked_at': status['checked_at'],
            'title': photo['title'], 'photographer': status['owner_name'], 'photo_page_url': status['photo_page_url'], 'region': photo['region'], 'opportunity_id': opportunity_id}, cache['image_path']


def main(database, inspections, baseline):
    db = sqlite3.connect(f'file:{database}?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    regional = {r[0] for r in sqlite3.connect(f'file:{baseline}?mode=ro', uri=True).execute("SELECT photo_id FROM photos WHERE source='flickr_live' AND region IS NOT NULL")}
    found = []
    for item in json.loads(Path(inspections).read_text(encoding='utf-8')):
        if item['photo_id'] in regional and item['relevance'] == 'relevant' and item['safety'] == 'pass' and item['inspection_type'] == INSPECTION_TYPE:
            moderation = db.execute('SELECT evaluation_json FROM photo_moderation WHERE photo_id=?', (item['photo_id'],)).fetchone()
            evaluated_at = json.loads(moderation[0])['evaluated_at'] if moderation and moderation[0] else None
            found.append(entry(db, item['photo_id'], item['image_sha256'], 'regional_50', item['reviewer'], item['inspection_type'], evaluated_at, item['reason']))
    for row in db.execute("SELECT * FROM opportunity_images WHERE status='accepted' ORDER BY opportunity_id, photo_id"):
        cache = db.execute('SELECT image_sha256 FROM moderation_asset_cache WHERE photo_id=?', (row['photo_id'],)).fetchone()
        found.append(entry(db, row['photo_id'], cache[0], 'opportunity_images', row['reviewer'], OPPORTUNITY_REVIEW_TYPE, row['reviewed_at'], row['reason'], row['opportunity_id']))
    found = [item for item in found if item]
    images = ROOT / 'demo' / 'images'
    images.mkdir(parents=True, exist_ok=True)
    for item, path in found:
        shutil.copyfile(path, images / f"{item['photo_id']}.jpg")
    records = [item for item, _ in found]
    (ROOT / 'config' / 'reviewed-images.json').write_text(json.dumps({'note': 'Earlier visual reviews honoured by the display gate. Reviews were by assistants, not people. A later rejection, changed bytes or changed licence still blocks an image. New photographs are never added automatically.', 'images': records}, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    credits = ['# Photo credits', '', 'These unmodified photographs are redistributed under the licences listed. Each licence applies to its photograph only, not to the ATIA code. Exact place identities are unverified.', '']
    for item in records:
        licence = interpret(item['license_id'])
        credits.append(f"- `{item['photo_id']}.jpg`: “{item['title']}” by {item['photographer']}. [{licence['name']}]({licence['url']}). [Flickr page]({item['photo_page_url']}). Licence as reported by Flickr on {item['license_checked_at'][:10]}.")
    (images / 'ATTRIBUTION.md').write_text('\n'.join(credits) + '\n', encoding='utf-8')
    print(f'{len(records)} images')


if __name__ == '__main__':
    main(*sys.argv[1:])
