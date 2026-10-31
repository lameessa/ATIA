"""Turn a small hand-picked list into opportunities, with evidence drawn only from real signals."""
import json
from pathlib import Path
from atia.intelligence.store import IntelligenceStore
from atia.models import utc_now
from .store import initialize

CONFIG = 'config/mvp-opportunities.json'
EVIDENCE_LABELS = {'strong': 'Strong evidence', 'moderate': 'Moderate evidence', 'thin': 'Exploratory'}


def build_opportunities(db, config_path=CONFIG):
    initialize(db)
    snapshot = IntelligenceStore(db).snapshot()
    if not snapshot['available']:
        raise ValueError('Run "atia intelligence build" first.')
    config = json.loads(Path(config_path).read_text(encoding='utf-8'))
    signals = {(s['kind'], s['key']): s for s in snapshot['signals']}
    records, missing = [], []
    for position, item in enumerate(config['opportunities']):
        signal = signals.get((item['signal_kind'], item['signal_key']))
        if not signal:
            missing.append(item['slug'])
            continue
        records.append({'opportunity_id': item['slug'], 'signal_id': signal['signal_id'], 'kind': signal['kind'], 'title': signal['title'], 'angle': item['angle'],
                        'evidence_strength': signal['strength'], 'evidence_label': EVIDENCE_LABELS[signal['strength']], 'theme': signal['theme'], 'region': signal['region'],
                        'identity': signal['identity'], 'evidence': signal['evidence'], 'geography': signal['geography'], 'visual': signal['visual'], 'assessment': signal['assessment'],
                        'sensitive_note': signal['sensitive_note'], 'gaps': signal['gaps'], 'photo_ids': signal['photo_ids'], 'images': signal['images'], 'image_search': item.get('image_search'), 'position': position})
    with db:
        db.execute('DELETE FROM marketing_opportunities')
        db.executemany('INSERT INTO marketing_opportunities VALUES(?,?,?,?,?)', [(r['opportunity_id'], r['signal_id'], r['position'], utc_now(), json.dumps(r, ensure_ascii=False)) for r in records])
    return {'opportunities': [{'id': r['opportunity_id'], 'strength': r['evidence_strength'], 'photos': r['evidence']['photo_count'], 'photographers': r['evidence']['distinct_photographers']} for r in records], 'missing_signals': missing}
