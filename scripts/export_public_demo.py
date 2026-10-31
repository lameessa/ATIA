"""Maintainer tool: writes demo/seed.json from a private database, opened read-only.

Keeps real evidence counts, citations and the stored Al Qassim draft. Leaves out image URLs,
raw Flickr responses, descriptions, tags, owner IDs and comments. A reviewer's name is replaced by a role.
"""
import json
from pathlib import Path
import sqlite3
import sys


def photo(record):
    geography = record['geography']
    return {'source': record['source'], 'photo_id': record['photo_id'], 'title': record['title'], 'description': '', 'tags': [], 'photographer': record['photographer'],
            'owner_id': None, 'photo_url': record['photo_url'], 'captured_at': record['captured_at'], 'uploaded_at': None, 'metadata_available': True, 'flickr_status': 'not_checked',
            'license': {'license_id': None, 'name': None, 'url': None, 'campaign_status': 'unknown', 'campaign_eligible': False, 'reason': 'Not included in the public demo.'},
            'license_recorded_id': None, 'license_checked_at': None, 'displayable': False, 'campaign_image_eligible': False, 'engagement': record['engagement'],
            'geography': {'precision': geography['precision'], 'region': geography['region'], 'locality': geography['locality']}, 'places': [], 'themes': record['themes'],
            'openclip': record['openclip'], 'review_label': None, 'image': None, 'preview_url': None, 'subset_rank': None, 'quality': {'score': 0, 'reasons': []}}


def clean_dossier(dossier):
    for item in dossier['photos']:
        item.update(description='', tags=[])
    return dossier


def main(database, output):
    db = sqlite3.connect(f'file:{database}?mode=ro&immutable=1', uri=True)
    db.row_factory = sqlite3.Row
    run = db.execute('SELECT * FROM intelligence_runs ORDER BY created_at DESC, rowid DESC LIMIT 1').fetchone()
    opportunities = [json.loads(r['record']) for r in db.execute('SELECT record FROM marketing_opportunities ORDER BY position')]
    ids = {i for o in opportunities for i in o['photo_ids']}
    records = [json.loads(r['record']) for r in db.execute('SELECT record FROM photo_intelligence WHERE run_id=?', (run['run_id'],))]
    for item in opportunities:
        item['images'] = {'displayable': 0, 'campaign_eligible': 0, 'campaign_eligible_photo_ids': [], 'representative': []}
        item.pop('image_search', None)
    campaigns = []
    for row in db.execute('SELECT * FROM opportunity_campaigns ORDER BY created_at'):
        evidence = json.loads(row['evidence_json'])
        evidence['dossier'] = clean_dossier(evidence['dossier'])
        edit = db.execute('SELECT * FROM opportunity_campaign_edits WHERE campaign_id=? ORDER BY revision DESC LIMIT 1', (row['campaign_id'],)).fetchone()
        review = db.execute('SELECT * FROM opportunity_review_events WHERE campaign_id=? ORDER BY rowid DESC LIMIT 1', (row['campaign_id'],)).fetchone()
        campaigns.append({'campaign_id': row['campaign_id'], 'run_id': row['run_id'], 'opportunity_id': row['opportunity_id'], 'created_at': row['created_at'], 'status': row['status'], 'evidence_fingerprint': row['evidence_fingerprint'], 'campaign': json.loads(row['campaign_json']), 'evidence': evidence,
                          'edit': edit and {'edit_id': edit['edit_id'], 'revision': edit['revision'], 'created_at': edit['created_at'], 'editor': edit['editor'], 'content': json.loads(edit['content_json']), 'dates': json.loads(edit['dates_json'])},
                          'review': review and {'review_id': review['review_id'], 'revision': review['revision'], 'decision': review['decision'], 'reviewer': 'Project reviewer', 'notes': review['notes'], 'reviewed_at': review['reviewed_at'], 'launch_date': review['launch_date']}})
    runs = []
    for cycle in db.execute("SELECT * FROM agent_discovery_cycles WHERE goal LIKE 'Investigate the marketing opportunity%' ORDER BY created_at"):
        result = json.loads(cycle['result_json'])
        # Attempts stopped before reaching the model produced nothing worth showing.
        if not result.get('usage', {}).get('output_tokens'):
            continue
        decision = result['decision']
        runs.append({'run_id': cycle['run_id'], 'goal': cycle['goal'], 'created_at': cycle['created_at'], 'completed_at': cycle['completed_at'], 'cache_key': cycle['cache_key'], 'status': cycle['status'], 'model': cycle['model'], 'limits': json.loads(cycle['limits_json']),
                     'result': {'decision': {k: decision.get(k) for k in ('decision', 'explanation', 'uncertainties', 'claims', 'hidden_gem')}, 'errors': result['errors'], 'estimated_api_cost_usd': result['estimated_api_cost_usd'], 'usage': result['usage'], 'llm_requests': result['llm_requests'], 'tool_calls': 0, 'evidence_registry': {}}})
    summary = json.loads(run['summary'])
    seed = {'provenance': 'Exported from the ATIA research database. Real counts and five stored GPT-4o-mini drafts with their review state. Photographs are in demo/images.',
            'summary': {k: summary[k] for k in ('archive_photos', 'metadata_available', 'geography', 'with_region', 'stored_openclip_photos', 'with_named_place', 'with_theme', 'signals', 'signal_strength', 'version', 'openclip_note')},
            'version': run['version'], 'run_id': run['run_id'], 'created_at': run['created_at'], 'photos': [photo(r) for r in records if r['photo_id'] in ids], 'opportunities': opportunities, 'runs': runs,
            'campaigns': campaigns}
    Path(output).write_text(json.dumps(seed, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f"{len(seed['photos'])} evidence records, {len(opportunities)} opportunities, {len(campaigns)} campaigns, {len(runs)} AI runs")


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
