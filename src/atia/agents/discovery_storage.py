"""Discovery cycles have no selected destination until the LLM chooses one.

The existing spending-reservation service is reused across both request ledgers.
"""
import json
import uuid
import hashlib
from pathlib import Path
from atia.models import utc_now
from atia.moderation.policy import clean_evidence
from .storage import AgentStore,encode


class DiscoveryStore(AgentStore):
    run_table='agent_discovery_cycles'
    request_table='agent_discovery_requests'
    tool_table='agent_discovery_tool_calls'

    def __init__(self,store,initialize=True):
        super().__init__(store,initialize=initialize)
        if not initialize:return
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS agent_discovery_cycles (
          run_id TEXT PRIMARY KEY,cluster_id TEXT,goal TEXT NOT NULL,created_at TEXT NOT NULL,
          completed_at TEXT,cache_key TEXT NOT NULL,status TEXT NOT NULL,model TEXT NOT NULL,
          limits_json TEXT NOT NULL,result_json TEXT,
          FOREIGN KEY(cluster_id) REFERENCES destination_entities(destination_id));
        CREATE INDEX IF NOT EXISTS discovery_cache ON agent_discovery_cycles(cache_key,completed_at);
        CREATE TABLE IF NOT EXISTS agent_discovery_requests (
          request_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,step INTEGER NOT NULL,reserved_usd REAL NOT NULL,
          charged_usd REAL NOT NULL,status TEXT NOT NULL,response_id TEXT,usage_json TEXT,
          FOREIGN KEY(run_id) REFERENCES agent_discovery_cycles(run_id));
        CREATE TABLE IF NOT EXISTS agent_discovery_tool_calls (
          run_id TEXT NOT NULL,call_id TEXT NOT NULL,name TEXT NOT NULL,arguments_json TEXT NOT NULL,
          result_json TEXT NOT NULL,called_at TEXT NOT NULL,PRIMARY KEY(run_id,call_id),
          FOREIGN KEY(run_id) REFERENCES agent_discovery_cycles(run_id));
        CREATE TABLE IF NOT EXISTS agent_discovery_observations (
          observation_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,cluster_id TEXT NOT NULL,created_at TEXT NOT NULL,
          content TEXT NOT NULL,evidence_refs TEXT NOT NULL,FOREIGN KEY(run_id) REFERENCES agent_discovery_cycles(run_id));
        CREATE TABLE IF NOT EXISTS agent_campaigns (
          campaign_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,cluster_id TEXT NOT NULL,entity_id TEXT NOT NULL,
          created_at TEXT NOT NULL,status TEXT NOT NULL CHECK(status='PENDING_APPROVAL'),previous_campaign_id TEXT,
          evidence_fingerprint TEXT NOT NULL,campaign_json TEXT NOT NULL,evidence_json TEXT NOT NULL,
          UNIQUE(entity_id,evidence_fingerprint),FOREIGN KEY(run_id) REFERENCES agent_discovery_cycles(run_id),
          FOREIGN KEY(cluster_id) REFERENCES destination_entities(destination_id),
          FOREIGN KEY(entity_id) REFERENCES verified_location_entities(entity_id),
          FOREIGN KEY(previous_campaign_id) REFERENCES agent_campaigns(campaign_id));
        ''');self.db.commit()

    def campaigns(self,cluster_id=None):
        rows=self.db.execute('SELECT * FROM agent_campaigns'+(' WHERE cluster_id=?' if cluster_id else '')+' ORDER BY created_at DESC',(cluster_id,) if cluster_id else ())
        result=[]
        for row in rows:
            item=dict(row);item['campaign']=json.loads(item.pop('campaign_json'));item['evidence']=json.loads(item.pop('evidence_json'))
            item['effective_status']=item['status']
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dashboard_campaign_reviews'").fetchone():
                review=self.db.execute('SELECT decision,reviewer,notes,reviewed_at FROM dashboard_campaign_reviews WHERE campaign_id=?',(item['campaign_id'],)).fetchone()
                if review:item['review']=dict(review);item['effective_status']=review['decision']
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='campaign_edits'").fetchone():
                revision=self.db.execute('SELECT coalesce(max(revision),0) FROM campaign_edits WHERE campaign_id=?',(item['campaign_id'],)).fetchone()[0]
                item['revision']=revision
                if revision:item.pop('review',None);item['effective_status']='PENDING_APPROVAL'
                review=self.db.execute('SELECT decision,reviewer,notes,reviewed_at FROM campaign_review_events WHERE campaign_id=? AND revision=? ORDER BY rowid DESC LIMIT 1',(item['campaign_id'],revision)).fetchone()
                if review:item['review']=dict(review);item['effective_status']=review['decision']
            if clean_evidence(self.db,item) and self.current_assets(item['campaign']):result.append(item)
        return result

    def current_assets(self,campaign):
        """Recheck current eligibility and snapshots before exposing an old draft."""
        from .discovery_tools import eligible,exists
        for asset in campaign.get('approved_photo_assets',[]):
            row=self.db.execute('SELECT * FROM photos WHERE source=? AND photo_id=?',
                                (asset['source'],asset['photo_id'])).fetchone()
            if row is None or not eligible(self.db,row):return False
            valid=False
            for table in ('moderation_asset_cache','photo_image_cache','tourism_relevance','visual_dimension_analyses','visual_analyses'):
                if not exists(self.db,table):continue
                query=f'SELECT image_path,image_sha256 FROM {table} WHERE photo_id=?'
                args=[asset['photo_id']]
                if table!='moderation_asset_cache':query+=' AND source=?';args.append(asset['source'])
                for cached in self.db.execute(query,args):
                    path=Path(cached['image_path'])
                    if cached['image_sha256']==asset['image_sha256'] and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==asset['image_sha256']:
                        valid=True;break
                if valid:break
            if not valid:return False
        return True

    def memory(self,cluster_id):
        # Original decisions/research are retained, not rewritten into discoveries.
        legacy=super().memory(cluster_id) if cluster_id else {'runs':[],'proposals':[],'observations':[]}
        sql='SELECT run_id,cluster_id,completed_at,result_json FROM agent_discovery_cycles WHERE result_json IS NOT NULL'
        args=()
        if cluster_id:sql+=' AND cluster_id=?';args=(cluster_id,)
        rows=self.db.execute(sql+' ORDER BY created_at DESC LIMIT 5',args)
        cycles=[]
        for row in rows:
            value=json.loads(row['result_json'])
            d=value['decision']
            item={'run_id':row['run_id'],'cluster_id':row['cluster_id'],'completed_at':row['completed_at'],
                  'decision':{'decision':d['decision'],'explanation':d['explanation'][:350],
                              'hidden_gem':d['hidden_gem']['classification']},'campaign_id':value.get('campaign_id')}
            if clean_evidence(self.db,item):cycles.append(item)
        campaigns=[{k:c[k] for k in ('campaign_id','cluster_id','entity_id','status','effective_status','evidence_fingerprint','created_at')} for c in self.campaigns(cluster_id)]
        observations=[dict(r) for r in self.db.execute('SELECT * FROM agent_discovery_observations'+(' WHERE cluster_id=?' if cluster_id else '')+' ORDER BY created_at DESC LIMIT 5',(cluster_id,) if cluster_id else ())]
        return {**legacy,'discovery_cycles':cycles,'campaigns':campaigns,
                'discovery_observations':[o for o in observations if clean_evidence(self.db,o)]}

    def inspect(self,run_id=None):
        result=[]
        rows=self.db.execute('SELECT * FROM agent_discovery_cycles'+(' WHERE run_id=?' if run_id else ' ORDER BY created_at DESC LIMIT 20'),(run_id,) if run_id else ())
        for row in rows:
            item=dict(row);item['result']=json.loads(item.pop('result_json')) if item['result_json'] else None
            item['limits']=json.loads(item.pop('limits_json'))
            item['tools']=[dict(t) for t in self.db.execute('SELECT * FROM agent_discovery_tool_calls WHERE run_id=? ORDER BY called_at',(row['run_id'],))]
            if clean_evidence(self.db,item):result.append(item)
        return result

    def save_campaign(self,run_id,cluster_id,campaign,evidence_key,evidence,previous_id):
        old=self.db.execute('SELECT campaign_id FROM agent_campaigns WHERE entity_id=? AND evidence_fingerprint=?',
                            (campaign['destination']['entity_id'],evidence_key)).fetchone()
        if old:return old['campaign_id'],False
        identifier='campaign-'+uuid.uuid4().hex
        with self.db:self.db.execute('INSERT INTO agent_campaigns VALUES(?,?,?,?,?,?,?,?,?,?)',
            (identifier,run_id,cluster_id,campaign['destination']['entity_id'],utc_now(),'PENDING_APPROVAL',previous_id,
             evidence_key,encode(campaign),encode(evidence)))
        return identifier,True
