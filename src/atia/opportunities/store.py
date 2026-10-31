"""Additive tables. Regional experiences have no verified entity, so drafts live beside
agent_campaigns rather than inventing one to satisfy its foreign keys."""
import json
import uuid
from atia.models import utc_now
from atia.moderation.policy import exists

SCHEMA = '''
CREATE TABLE IF NOT EXISTS marketing_opportunities (
  opportunity_id TEXT PRIMARY KEY, signal_id TEXT NOT NULL, position INTEGER NOT NULL, updated_at TEXT NOT NULL, record TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS opportunity_images (
  opportunity_id TEXT NOT NULL, source TEXT NOT NULL, photo_id TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('candidate','accepted','rejected')),
  found_at TEXT NOT NULL, reviewer TEXT, reason TEXT, reviewed_at TEXT, PRIMARY KEY (opportunity_id, source, photo_id));
CREATE TABLE IF NOT EXISTS opportunity_campaigns (
  campaign_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, opportunity_id TEXT NOT NULL, created_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status='PENDING_APPROVAL'), evidence_fingerprint TEXT NOT NULL, campaign_json TEXT NOT NULL, evidence_json TEXT NOT NULL,
  UNIQUE(opportunity_id, evidence_fingerprint));
CREATE TABLE IF NOT EXISTS opportunity_campaign_edits (
  edit_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, revision INTEGER NOT NULL, created_at TEXT NOT NULL, editor TEXT NOT NULL,
  content_json TEXT NOT NULL, dates_json TEXT NOT NULL, UNIQUE(campaign_id, revision), FOREIGN KEY(campaign_id) REFERENCES opportunity_campaigns(campaign_id));
CREATE TABLE IF NOT EXISTS opportunity_review_events (
  review_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, revision INTEGER NOT NULL,
  decision TEXT NOT NULL CHECK(decision IN ('APPROVED','REJECTED','REVISION_REQUESTED')), reviewer TEXT NOT NULL, notes TEXT NOT NULL, reviewed_at TEXT NOT NULL, launch_date TEXT,
  FOREIGN KEY(campaign_id) REFERENCES opportunity_campaigns(campaign_id));
'''
CAMPAIGN_PREFIX = 'oppcampaign-'


def initialize(db):
    db.executescript(SCHEMA)
    if 'launch_date' not in {r[1] for r in db.execute('PRAGMA table_info(opportunity_review_events)')}:
        db.execute('ALTER TABLE opportunity_review_events ADD COLUMN launch_date TEXT')


class OpportunityStore:
    def __init__(self, db):
        self.db = db

    def opportunities(self):
        if not exists(self.db, 'marketing_opportunities'):
            return []
        return [json.loads(r['record']) for r in self.db.execute('SELECT record FROM marketing_opportunities ORDER BY position')]

    def opportunity(self, opportunity_id):
        return next((o for o in self.opportunities() if o['opportunity_id'] == opportunity_id), None)

    def accepted_images(self, opportunity_id):
        if not exists(self.db, 'opportunity_images'):
            return []
        return [dict(r) for r in self.db.execute("SELECT source, photo_id FROM opportunity_images WHERE opportunity_id=? AND status='accepted' ORDER BY reviewed_at, rowid", (opportunity_id,))]

    def campaigns(self):
        if not exists(self.db, 'opportunity_campaigns'):
            return []
        return [{**dict(r), 'campaign': json.loads(r['campaign_json']), 'evidence': json.loads(r['evidence_json'])}
                for r in self.db.execute('SELECT * FROM opportunity_campaigns ORDER BY created_at DESC')]

    def save_campaign(self, run_id, opportunity_id, campaign, fingerprint, evidence):
        old = self.db.execute('SELECT campaign_id FROM opportunity_campaigns WHERE opportunity_id=? AND evidence_fingerprint=?', (opportunity_id, fingerprint)).fetchone()
        if old:
            return old['campaign_id'], False
        identifier = CAMPAIGN_PREFIX + uuid.uuid4().hex
        with self.db:
            self.db.execute('INSERT INTO opportunity_campaigns VALUES(?,?,?,?,?,?,?,?)', (identifier, run_id, opportunity_id, utc_now(), 'PENDING_APPROVAL', fingerprint,
                            json.dumps(campaign, ensure_ascii=False), json.dumps(evidence, ensure_ascii=False)))
        return identifier, True
