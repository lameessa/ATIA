"""Additive tables only: original photo, analysis and research records are never rewritten."""
import json
from atia.moderation.display import can_display
from atia.moderation.policy import exists

SCHEMA = '''
CREATE TABLE IF NOT EXISTS photo_flickr_status (
  source TEXT NOT NULL, photo_id TEXT NOT NULL, checked_at TEXT NOT NULL,
  api_status TEXT NOT NULL CHECK(api_status IN ('ok','not_found','no_permission','restricted','error')),
  error_code TEXT, recorded_license_id TEXT, current_license_id TEXT, safety_level TEXT,
  owner_nsid TEXT, owner_name TEXT, photo_page_url TEXT, image_status TEXT, image_message TEXT,
  PRIMARY KEY (source, photo_id));
CREATE TABLE IF NOT EXISTS photo_image_cache (
  source TEXT NOT NULL, photo_id TEXT NOT NULL, image_sha256 TEXT NOT NULL, image_path TEXT NOT NULL,
  image_url TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL, fetched_at TEXT NOT NULL,
  PRIMARY KEY (source, photo_id));
CREATE TABLE IF NOT EXISTS intelligence_runs (
  run_id TEXT PRIMARY KEY, version TEXT NOT NULL, created_at TEXT NOT NULL, summary TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS photo_intelligence (
  run_id TEXT NOT NULL, source TEXT NOT NULL, photo_id TEXT NOT NULL, displayable INTEGER NOT NULL,
  campaign_image_eligible INTEGER NOT NULL, subset_rank INTEGER, quality_score INTEGER NOT NULL, record TEXT NOT NULL,
  PRIMARY KEY (run_id, source, photo_id));
CREATE TABLE IF NOT EXISTS opportunity_signals (
  run_id TEXT NOT NULL, signal_id TEXT NOT NULL, kind TEXT NOT NULL, strength TEXT NOT NULL, position INTEGER NOT NULL,
  record TEXT NOT NULL, PRIMARY KEY (run_id, signal_id));
'''


class IntelligenceStore:
    def __init__(self, db):
        self.db = db

    def initialize(self):
        self.db.executescript(SCHEMA)

    def latest_run(self):
        if not exists(self.db, 'intelligence_runs'):
            return None
        return self.db.execute('SELECT * FROM intelligence_runs ORDER BY created_at DESC, rowid DESC LIMIT 1').fetchone()

    def save(self, run_id, version, created_at, summary, photos, signals):
        with self.db:
            self.db.execute('INSERT INTO intelligence_runs VALUES(?,?,?,?)', (run_id, version, created_at, json.dumps(summary, ensure_ascii=False)))
            self.db.executemany('INSERT INTO photo_intelligence VALUES(?,?,?,?,?,?,?,?)', [
                (run_id, p['source'], p['photo_id'], int(p['displayable']), int(p['campaign_image_eligible']), p['subset_rank'],
                 p['quality']['score'], json.dumps(p, ensure_ascii=False)) for p in photos])
            self.db.executemany('INSERT INTO opportunity_signals VALUES(?,?,?,?,?,?)', [
                (run_id, s['signal_id'], s['kind'], s['strength'], index, json.dumps(s, ensure_ascii=False)) for index, s in enumerate(signals)])

    def _summary(self, run):
        summary = json.loads(run['summary'])
        count = sum(can_display(self.db, r[0], r[1]) for r in self.db.execute('SELECT source, photo_id FROM photo_intelligence WHERE run_id=?', (run['run_id'],)))
        summary.update(displayable=count, campaign_image_eligible=count, images_note='Counts of photos a person has approved for display. Metadata counts are unaffected.')
        return summary

    def snapshot(self, kind=None):
        run = self.latest_run()
        if not run:
            return {'available': False, 'signals': [], 'subset': [], 'summary': None}
        query, args = 'SELECT record FROM opportunity_signals WHERE run_id=?', [run['run_id']]
        if kind:
            query += ' AND kind=?'
            args.append(kind)
        signals = [json.loads(r['record']) for r in self.db.execute(query + ' ORDER BY position', args)]
        subset = [json.loads(r['record']) for r in self.db.execute(
            'SELECT record FROM photo_intelligence WHERE run_id=? AND subset_rank IS NOT NULL ORDER BY subset_rank', (run['run_id'],))]
        # Stored runs may predate a review or revocation, so display state is never read from them.
        for signal in signals:
            shown = [i for i in signal['photo_ids'] if can_display(self.db, 'afaq_historical', i)]
            images = signal['images']
            images.update(displayable=len(shown), campaign_eligible=len(shown), campaign_eligible_photo_ids=shown,
                          representative=[r for r in images['representative'] if can_display(self.db, r['source'], r['photo_id'])])
        for photo in subset:
            can = can_display(self.db, photo['source'], photo['photo_id'])
            photo.update(displayable=can, campaign_image_eligible=can, preview_url=photo['preview_url'] if can else None)
        return {'available': True, 'run_id': run['run_id'], 'version': run['version'], 'created_at': run['created_at'],
                'summary': self._summary(run), 'signals': signals, 'subset': subset}
