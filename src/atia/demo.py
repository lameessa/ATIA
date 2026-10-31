"""Builds a local demo database from demo/seed.json, and the licensed demo photographs, with no API keys."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
from atia.agents.discovery_storage import DiscoveryStore
from atia.api.campaign_workflow import initialize as initialize_workflow
from atia.destinations.storage import DestinationStore
from atia.intelligence.store import IntelligenceStore
from atia.moderation.display import reviewed_images
from atia.moderation.policy import initialize as initialize_moderation
from atia.opportunities.store import initialize as initialize_opportunities
from atia.opportunities.generate import EDITOR_ONLY, guard_decision

SEED = Path(__file__).resolve().parents[2] / 'demo' / 'seed.json'
IMAGES = SEED.parent / 'images'


def load_seed(path=SEED):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _install_images(db):
    """Copies each reviewed photograph beside the database. A file that differs from its review is skipped."""
    initialize_moderation(db)
    initialize_opportunities(db)
    target = Path(db.execute('PRAGMA database_list').fetchone()[2]).resolve().parent / 'demo-images'
    target.mkdir(exist_ok=True)
    installed = 0
    for item in reviewed_images():
        photo_id, file = item['photo_id'], IMAGES / f"{item['photo_id']}.jpg"
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != item['image_sha256']:
            continue
        path = shutil.copyfile(file, target / file.name)
        linked = item['opportunity_id'] is not None
        with db:
            db.execute("INSERT INTO photos(source,photo_id,title,tags,photo_url,collected_at,raw,region,license_id) VALUES('flickr_live',?,?,'[]',?,?,'{}',?,?)", (photo_id, item['title'], item['photo_page_url'], item['license_checked_at'], item['region'], item['license_id']))
            db.execute('INSERT OR REPLACE INTO photo_moderation(photo_id,status,quarantined_at,relevance,safety,reviewer,reviewed_at,review_reason) VALUES(?,?,?,?,?,?,?,?)',
                       (photo_id, 'approved' if linked else 'awaiting_approval', item['license_checked_at'], item['relevance'], item['safety'], item['reviewer'] if linked else None, item['reviewed_at'] if linked else None, item['reason'] if linked else None))
            db.execute('INSERT INTO moderation_asset_cache VALUES(?,?,?,?)', (photo_id, item['image_sha256'], str(path), ''))
            db.execute("INSERT INTO photo_flickr_status VALUES('flickr_live',?,?,'ok',NULL,?,?,'0',NULL,?,?,'cached',NULL)", (photo_id, item['license_checked_at'], item['license_id'], item['license_id'], item['photographer'], item['photo_page_url']))
            if linked:
                db.execute("INSERT INTO opportunity_images(opportunity_id,source,photo_id,status,found_at,reviewer,reason,reviewed_at) VALUES(?,'flickr_live',?,'accepted',?,?,?,?)", (item['opportunity_id'], photo_id, item['reviewed_at'], item['reviewer'], item['reason'], item['reviewed_at']))
        installed += 1
    return installed


def init_demo(store, path=SEED):
    db = store.connection
    if db.execute('SELECT 1 FROM photos LIMIT 1').fetchone():
        raise ValueError('This database already holds photos. The demo only initializes an empty database.')
    seed = load_seed(path)
    DestinationStore(store)
    DiscoveryStore(store)
    IntelligenceStore(db).initialize()
    initialize_workflow(db)
    enc = lambda value: json.dumps(value, ensure_ascii=False)
    with db:
        db.execute('INSERT INTO intelligence_runs VALUES(?,?,?,?)', (seed['run_id'], seed['version'], seed['created_at'], enc(seed['summary'])))
        db.executemany('INSERT INTO photo_intelligence VALUES(?,?,?,?,?,?,?,?)', [(seed['run_id'], p['source'], p['photo_id'], 0, 0, None, 0, enc(p)) for p in seed['photos']])
        db.executemany('INSERT INTO marketing_opportunities VALUES(?,?,?,?,?)', [(o['opportunity_id'], o['signal_id'], o['position'], seed['created_at'], enc(o)) for o in seed['opportunities']])
        for run in seed['runs']:
            db.execute('INSERT INTO agent_discovery_cycles VALUES(?,?,?,?,?,?,?,?,?,?)', (run['run_id'], None, run['goal'], run['created_at'], run['completed_at'], run['cache_key'], run['status'], run['model'], enc(run['limits']), enc(run['result'])))
        for c in seed['campaigns']:
            db.execute('INSERT INTO opportunity_campaigns VALUES(?,?,?,?,?,?,?,?)', (c['campaign_id'], c['run_id'], c['opportunity_id'], c['created_at'], c['status'], c['evidence_fingerprint'], enc(c['campaign']), enc(c['evidence'])))
            if e := c['edit']:
                db.execute('INSERT INTO opportunity_campaign_edits VALUES(?,?,?,?,?,?,?)', (e['edit_id'], c['campaign_id'], e['revision'], e['created_at'], e['editor'], enc(e['content']), enc(e['dates'])))
            if r := c['review']:
                db.execute('INSERT INTO opportunity_review_events(review_id,campaign_id,revision,decision,reviewer,notes,reviewed_at,launch_date) VALUES(?,?,?,?,?,?,?,?)', (r['review_id'], c['campaign_id'], r['revision'], r['decision'], r['reviewer'], r['notes'], r['reviewed_at'], r['launch_date']))
    return {'opportunities': len(seed['opportunities']), 'evidence_records': len(seed['photos']), 'campaigns': len(seed['campaigns']), 'images': _install_images(db)}


def _decision(campaign, recommendation, angle, claims, uncertainties):
    return {'decision': 'CREATE', 'recommendation': recommendation, 'marketing_angle': angle, 'claims': claims, 'uncertainties': uncertainties, 'next_actions': [],
            'campaign': copy.deepcopy({k: v for k, v in campaign.items() if k not in EDITOR_ONLY})}


def _verdict(decision, dossier):
    try:
        guard_decision(decision, dossier)
        return 'ACCEPTED'
    except ValueError as exc:
        return f'REJECTED: {exc}'


def validate_demo(path=SEED):
    """Runs the real validator on the stored draft and its correction. Makes no model call."""
    seed = load_seed(path)
    corrected_campaign = next(c for c in seed['campaigns'] if c['edit'])
    evidence, original, corrected = corrected_campaign['evidence'], corrected_campaign['campaign'], corrected_campaign['edit']['content']
    review = corrected['review_evidence']
    return {'model_call': False,
            'original_ai_draft': _verdict(_decision(original, evidence['recommendation'], evidence['marketing_angle'], evidence['claims'], evidence['uncertainties']), evidence['dossier']),
            'corrected_revision': _verdict(_decision(corrected, review['recommendation'], evidence['marketing_angle'], review['claims'], review['uncertainties']), evidence['dossier']),
            'note': 'A person or editor corrected the draft. ATIA did not rewrite it, and validation does not replace human approval.'}
