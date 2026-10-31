"""Additive memory and a persisted pre-request budget ledger."""
import hashlib
import json
import uuid
from atia.models import utc_now


def encode(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


class AgentStore:
    run_table='agent_runs'
    request_table='agent_requests'
    tool_table='agent_tool_calls'
    def __init__(self,store,initialize=True):
        self.db=store.connection
        self.db.execute('PRAGMA foreign_keys=ON')
        if not initialize:return
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS agent_runs (
          run_id TEXT PRIMARY KEY,cluster_id TEXT NOT NULL,goal TEXT NOT NULL,created_at TEXT NOT NULL,
          completed_at TEXT,cache_key TEXT NOT NULL,status TEXT NOT NULL,model TEXT NOT NULL,
          limits_json TEXT NOT NULL,result_json TEXT,
          FOREIGN KEY(cluster_id) REFERENCES destination_entities(destination_id));
        CREATE INDEX IF NOT EXISTS agent_run_cache ON agent_runs(cache_key,created_at);
        CREATE TABLE IF NOT EXISTS agent_requests (
          request_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,step INTEGER NOT NULL,reserved_usd REAL NOT NULL,
          charged_usd REAL NOT NULL,status TEXT NOT NULL,response_id TEXT,usage_json TEXT,
          FOREIGN KEY(run_id) REFERENCES agent_runs(run_id));
        CREATE TABLE IF NOT EXISTS agent_tool_calls (
          run_id TEXT NOT NULL,call_id TEXT NOT NULL,name TEXT NOT NULL,arguments_json TEXT NOT NULL,
          result_json TEXT NOT NULL,called_at TEXT NOT NULL,PRIMARY KEY(run_id,call_id),
          FOREIGN KEY(run_id) REFERENCES agent_runs(run_id));
        CREATE TABLE IF NOT EXISTS agent_observations (
          observation_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,cluster_id TEXT NOT NULL,created_at TEXT NOT NULL,
          content TEXT NOT NULL,evidence_refs TEXT NOT NULL,FOREIGN KEY(run_id) REFERENCES agent_runs(run_id));
        CREATE TABLE IF NOT EXISTS agent_proposals (
          proposal_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,cluster_id TEXT NOT NULL,created_at TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status='PENDING_APPROVAL'),previous_proposal_id TEXT,
          evidence_fingerprint TEXT NOT NULL,proposal_json TEXT NOT NULL,
          UNIQUE(cluster_id,evidence_fingerprint),FOREIGN KEY(run_id) REFERENCES agent_runs(run_id),
          FOREIGN KEY(previous_proposal_id) REFERENCES agent_proposals(proposal_id));
        ''')
        self.db.commit()

    def memory(self,cluster_id):
        runs=[dict(r) for r in self.db.execute('SELECT run_id,goal,completed_at,status,result_json FROM agent_runs WHERE cluster_id=? AND completed_at IS NOT NULL ORDER BY created_at DESC LIMIT 5',(cluster_id,))]
        for r in runs:
            saved=json.loads(r.pop('result_json'))
            r['result']={k:saved[k] for k in ('decision','proposal_id','evidence_fingerprint','errors')}
        proposals=[dict(r) for r in self.db.execute('SELECT * FROM agent_proposals WHERE cluster_id=? ORDER BY created_at DESC LIMIT 5',(cluster_id,))]
        for p in proposals:
            p['proposal']=json.loads(p.pop('proposal_json'))
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dashboard_proposal_reviews'").fetchone():
                review=self.db.execute('SELECT decision,reviewer,notes,reviewed_at FROM dashboard_proposal_reviews WHERE proposal_id=?',(p['proposal_id'],)).fetchone()
                if review:
                    p['review']=dict(review);p['effective_status']=review['decision']
        observations=[dict(r) for r in self.db.execute('SELECT * FROM agent_observations WHERE cluster_id=? ORDER BY created_at DESC LIMIT 5',(cluster_id,))]
        from atia.moderation.policy import clean_evidence
        runs=[r for r in runs if clean_evidence(self.db,r)]
        proposals=[p for p in proposals if clean_evidence(self.db,p)]
        observations=[o for o in observations if clean_evidence(self.db,o)]
        return {'runs':runs,'proposals':proposals,'observations':observations}

    def inspect(self,run_id=None):
        rows=self.db.execute('SELECT * FROM agent_runs'+(' WHERE run_id=?' if run_id else ' ORDER BY created_at DESC LIMIT 20'),(run_id,) if run_id else ())
        result=[]
        for r in rows:
            item=dict(r);item['result']=json.loads(item.pop('result_json')) if item['result_json'] else None
            item['limits']=json.loads(item.pop('limits_json'))
            item['tools']=[dict(x) for x in self.db.execute('SELECT * FROM agent_tool_calls WHERE run_id=? ORDER BY called_at',(item['run_id'],))]
            result.append(item)
        return result

    def reserve(self,run_id,step,usd,limits):
        # Pending/failed calls retain their upper-bound charge even after a crash.
        self.db.execute('BEGIN IMMEDIATE')
        try:
            total=self.db.execute('SELECT coalesce(sum(charged_usd),0) FROM agent_requests').fetchone()[0]
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='agent_discovery_requests'").fetchone():
                total+=self.db.execute('SELECT coalesce(sum(charged_usd),0) FROM agent_discovery_requests').fetchone()[0]
            local=self.db.execute(f'SELECT coalesce(sum(charged_usd),0) FROM {self.request_table} WHERE run_id=?',(run_id,)).fetchone()[0]
            count=self.db.execute(f'SELECT count(*) FROM {self.request_table} WHERE run_id=?',(run_id,)).fetchone()[0]
            if count>=limits.max_steps:raise RuntimeError('Persisted request limit reached before request')
            if total+usd>limits.lifetime_budget_usd or local+usd>limits.run_budget_usd:
                raise RuntimeError('Local OpenAI spending limit reached before request')
            identifier='request-'+uuid.uuid4().hex
            self.db.execute(f'INSERT INTO {self.request_table} VALUES(?,?,?,?,?,?,?,?)',
                (identifier,run_id,step,usd,usd,'reserved',None,None))
            self.db.commit();return identifier
        except Exception:
            self.db.rollback();raise

    def finish_request(self,identifier,response,prices):
        usage=response.usage
        usd=(usage.input_tokens*prices[0]+usage.output_tokens*prices[1])/1_000_000
        with self.db:self.db.execute(f'UPDATE {self.request_table} SET charged_usd=?,status=?,response_id=?,usage_json=? WHERE request_id=?',
            (usd,'completed',response.id,encode(usage.model_dump()),identifier))
        return usd
