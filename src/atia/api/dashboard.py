"""Local dashboard API. Read projections are separate from explicit mutations."""
import os
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager,contextmanager
from pathlib import Path
import json
import sqlite3
import threading
from typing import Literal
from urllib.parse import quote
from uuid import UUID,uuid4
from fastapi import FastAPI,HTTPException,Request,Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel,Field
from atia.config import Settings
from atia.models import utc_now
from atia.agents.contracts import Limits
from .data import DashboardData,public,parse

ORIGINS={'http://localhost:5173','http://127.0.0.1:5173','http://localhost:8000','http://127.0.0.1:8000'}


def review_origins(value):
    """Extra local dev-server origins, for a review copy on another port. Never a remote host."""
    allowed=set()
    for item in (value or '').split(','):
        item=item.strip()
        if not item:continue
        if not re.fullmatch(r'http://(127\.0\.0\.1|localhost):\d{2,5}',item):raise ValueError('ATIA_REVIEW_ORIGINS accepts only local http origins')
        allowed.add(item)
    return allowed


class RunRequest(BaseModel):
    cluster_id:str=Field(min_length=1,max_length=100)
    confirmed:Literal[True]
    idempotency_key:UUID


class ReviewRequest(BaseModel):
    decision:Literal['APPROVED','REJECTED']
    reviewer:str=Field(default='Local reviewer',min_length=1,max_length=120)
    notes:str=Field(default='',max_length=2000)
    confirmed:Literal[True]


def create_app(db_path=None,agent_runner=None,opportunity_runner=None):
    settings=Settings.load();path=Path(db_path or settings.db_path).resolve()
    origins=ORIGINS|review_origins(os.getenv('ATIA_REVIEW_ORIGINS'))
    executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='atia-dashboard')
    gate=threading.Lock()

    @contextmanager
    def connect(write=False):
        if not path.is_file():raise HTTPException(503,'ATIA database is unavailable. Configure ATIA_DB_PATH and run ingestion first.')
        db=sqlite3.connect(f'file:{quote(str(path))}?mode={"rw" if write else "ro"}',uri=True,timeout=10)
        db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON')
        if not write:
            from atia.moderation.policy import presentation_connection
            presentation_connection(db)
            db.execute('PRAGMA query_only=ON')
        try:yield db
        finally:db.close()

    @asynccontextmanager
    async def lifespan(app):
        if path.is_file():
            with connect(True) as db:
                db.executescript('''
                CREATE TABLE IF NOT EXISTS dashboard_proposal_reviews (
                  review_id TEXT PRIMARY KEY,proposal_id TEXT NOT NULL UNIQUE,decision TEXT NOT NULL CHECK(decision IN ('APPROVED','REJECTED')),
                  reviewer TEXT NOT NULL,notes TEXT NOT NULL,reviewed_at TEXT NOT NULL,
                  FOREIGN KEY(proposal_id) REFERENCES agent_proposals(proposal_id));
                CREATE TABLE IF NOT EXISTS dashboard_agent_jobs (
                  job_id TEXT PRIMARY KEY,idempotency_key TEXT NOT NULL UNIQUE,cluster_id TEXT NOT NULL,
                  created_at TEXT NOT NULL,completed_at TEXT,status TEXT NOT NULL,run_id TEXT,
                  progress TEXT NOT NULL,error TEXT);
                ''')
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_campaigns'").fetchone():
                    db.execute('''CREATE TABLE IF NOT EXISTS dashboard_campaign_reviews (
                      review_id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL UNIQUE,
                      decision TEXT NOT NULL CHECK(decision IN ('APPROVED','REJECTED')),
                      reviewer TEXT NOT NULL,notes TEXT NOT NULL,reviewed_at TEXT NOT NULL,
                      FOREIGN KEY(campaign_id) REFERENCES agent_campaigns(campaign_id))''')
                    db.commit()
                from .campaign_workflow import initialize as initialize_campaign_workflow
                initialize_campaign_workflow(db)
                with db:db.execute("UPDATE dashboard_agent_jobs SET status='interrupted',completed_at=?,error='Server restarted; no automatic retry was made.' WHERE status IN ('queued','running')",(utc_now(),))
        yield
        executor.shutdown(wait=True,cancel_futures=True)

    app=FastAPI(title='ATIA Tourism Intelligence',version='0.7.0',lifespan=lifespan)
    app.add_middleware(CORSMiddleware,allow_origins=sorted(origins),allow_methods=['GET','POST'],
                       allow_headers=['Content-Type','X-ATIA-Action'])

    @app.middleware('http')
    async def local_mutations(request:Request,call_next):
        if request.method=='POST':
            from fastapi.responses import JSONResponse
            if request.headers.get('origin') not in origins|{None} or request.headers.get('X-ATIA-Action')!='confirmed':
                return JSONResponse({'detail':'Explicit local dashboard confirmation is required.'},status_code=403)
        response=await call_next(request)
        response.headers.setdefault('Cache-Control','no-store')
        response.headers['X-Content-Type-Options']='nosniff'
        return response

    @app.exception_handler(sqlite3.Error)
    async def database_error(request,exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail':'Stored data is temporarily unavailable; no paid request was retried.'},status_code=503)

    @app.exception_handler(ValueError)
    async def configuration_error(request,exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail':'Local configuration or stored evidence needs review. No automatic paid retry was made.'},status_code=503)

    def read(method,*args):
        with connect() as db:return public(getattr(DashboardData(db),method)(*args))

    @app.get('/health')
    def health():return {'status':'ok','database_available':path.is_file()}

    @app.get('/photos')
    def photos(limit:int=Query(50,ge=1,le=250),source:Literal['flickr_live','afaq_historical']|None=None):
        with connect() as db:
            query='SELECT source,photo_id,title,latitude,longitude,uploaded_at,captured_at,views,photo_url,region FROM photos'
            args=[]
            if source:query+=' WHERE source=?';args.append(source)
            args.append(limit)
            rows=[dict(r) for r in db.execute(query+' ORDER BY collected_at DESC,photo_id LIMIT ?',args)]
            for r in rows:
                if r['source']=='flickr_live':r['photo_url']=f"/api/images/flickr_live/{r['photo_id']}"
            return public({'photos':rows})

    @app.get('/api/overview')
    def overview():return read('overview')

    @app.get('/api/workspace')
    def workspace():
        from .workspace import WorkspaceData
        with connect() as db:return public(WorkspaceData(db).snapshot())

    @app.get('/api/destinations')
    def destinations():return {'areas':read('areas'),'entities':read('catalogue')['verified_entities']}

    @app.get('/api/destinations/{cluster_id}')
    def destination(cluster_id:str):
        value=read('cluster',cluster_id)
        if value is None:raise HTTPException(404,'Geographic cluster not found')
        return value

    @app.get('/api/research')
    def research():return read('research')

    @app.get('/api/images/{source}/{photo_id}')
    def image(source:Literal['flickr_live','afaq_historical'],photo_id:str):
        from fastapi.responses import FileResponse
        from .media import cached_photo
        with connect() as db:
            target=cached_photo(db,source,photo_id)
        if target is None:raise HTTPException(404,'Approved stored preview unavailable')
        with target.open('rb') as handle:header=handle.read(16)
        kind='image/jpeg' if header.startswith(b'\xff\xd8\xff') else 'image/png' if header.startswith(b'\x89PNG') else 'image/webp' if header.startswith(b'RIFF') and header[8:12]==b'WEBP' else None
        if not kind:raise HTTPException(404,'Preview format unavailable')
        return FileResponse(target,media_type=kind,headers={'Cache-Control':'no-store'})

    @app.get('/api/intelligence')
    def intelligence(kind:Literal['named_destination','regional_experience','tourism_theme']|None=None):
        from atia.intelligence.store import IntelligenceStore
        with connect() as db:return public(IntelligenceStore(db).snapshot(kind))

    @app.get('/api/agent/runs')
    def runs():return {'runs':read('runs')}

    @app.get('/api/agent/runs/{run_id}')
    def run(run_id:str):
        rows=read('runs',run_id)
        if not rows:raise HTTPException(404,'Agent run not found')
        return rows[0]

    @app.get('/api/agent/policy')
    def policy():
        limits=Limits.load()
        return {'openai_configured':bool(os.getenv('OPENAI_API_KEY','').strip()),'limits':limits.to_dict(),'scope':'One geographic cluster; no publishing. Cached decisions may be reused.',
                'cost_note':'Local estimates and ledger, not account balance. Tavily usage is separate.'}

    @app.get('/api/proposals')
    def proposals():return {'proposals':read('proposals')}

    @app.post('/api/proposals/{proposal_id}/review')
    def review(proposal_id:str,body:ReviewRequest):
        with connect(True) as db:
            if not db.execute('SELECT 1 FROM agent_proposals WHERE proposal_id=?',(proposal_id,)).fetchone():raise HTTPException(404,'Proposal not found')
            if not any(p['proposal_id']==proposal_id for p in DashboardData(db).proposals()):
                raise HTTPException(409,'Proposal evidence contains unapproved or removed photographs; reassessment required.')
            db.execute('BEGIN IMMEDIATE')
            previous=db.execute('SELECT * FROM dashboard_proposal_reviews WHERE proposal_id=?',(proposal_id,)).fetchone()
            if previous:
                db.rollback()
                if previous['decision']!=body.decision:raise HTTPException(409,'This draft has already received a final review.')
                return public(dict(previous))
            item={'review_id':'review-'+uuid4().hex,'proposal_id':proposal_id,'decision':body.decision,
                  'reviewer':body.reviewer.strip() or 'Local reviewer','notes':body.notes,'reviewed_at':utc_now()}
            with db:db.execute('INSERT INTO dashboard_proposal_reviews VALUES(?,?,?,?,?,?)',tuple(item.values()))
            return public(item)

    def worker(job_id,cluster_id):
        def progress(message):
            with connect(True) as db:
                row=db.execute('SELECT progress FROM dashboard_agent_jobs WHERE job_id=?',(job_id,)).fetchone()
                items=parse(row['progress'],[]);items.append({'at':utc_now(),'message':public(message)})
                with db:db.execute('UPDATE dashboard_agent_jobs SET progress=? WHERE job_id=?',(json.dumps(items[-30:]),job_id))
        try:
            with connect(True) as db:
                with db:db.execute("UPDATE dashboard_agent_jobs SET status='running' WHERE job_id=?",(job_id,))
            from atia.storage.sqlite import PhotoStore
            from atia.agents.runner import run_agent
            with PhotoStore(path) as store:
                result=(agent_runner or run_agent)(store,cluster_id,limits=Limits.load(),progress=progress)
            if result.get('cached'):
                progress('Existing cached decision reused; no new LLM requests or tool calls.')
            with connect(True) as db:
                with db:db.execute('UPDATE dashboard_agent_jobs SET status=?,completed_at=?,run_id=?,error=? WHERE job_id=?',
                    ('needs_review' if result.get('errors') else 'completed',utc_now(),result.get('run_id'),
                     'Agent stopped safely; inspect the run for details.' if result.get('errors') else None,job_id))
        except Exception:
            with connect(True) as db:
                with db:db.execute("UPDATE dashboard_agent_jobs SET status='failed',completed_at=?,error=? WHERE job_id=?",
                    (utc_now(),'Agent could not complete. Check server configuration and stored run evidence; no automatic retry was made.',job_id))

    @app.post('/api/agent/run',status_code=202)
    def execute(body:RunRequest):
        with gate,connect(True) as db:
            prior=db.execute('SELECT * FROM dashboard_agent_jobs WHERE idempotency_key=?',(str(body.idempotency_key),)).fetchone()
            if prior:
                if prior['cluster_id']!=body.cluster_id:raise HTTPException(409,'Request key belongs to a different location')
                return public(dict(prior)|{'progress':parse(prior['progress'],[])})
            if not any(g['destination_id']==body.cluster_id for g in DashboardData(db).groups()):raise HTTPException(404,'Geographic cluster not found')
            if db.execute("SELECT 1 FROM campaign_preparation_jobs WHERE status IN ('queued','running')").fetchone() or db.execute("SELECT 1 FROM dashboard_agent_jobs WHERE status IN ('queued','running')").fetchone():raise HTTPException(409,'An agent run is already active. Wait for it to finish.')
            Limits.load()
            item={'job_id':'job-'+uuid4().hex,'idempotency_key':str(body.idempotency_key),'cluster_id':body.cluster_id,
                'created_at':utc_now(),'completed_at':None,'status':'queued','run_id':None,'progress':'[]','error':None}
            with db:db.execute('INSERT INTO dashboard_agent_jobs VALUES(?,?,?,?,?,?,?,?,?)',tuple(item.values()))
            executor.submit(worker,item['job_id'],body.cluster_id)
            return public(item|{'progress':[]})

    @app.get('/api/agent/jobs')
    def jobs():
        with connect() as db:
            rows=[dict(r) for r in db.execute('SELECT * FROM dashboard_agent_jobs ORDER BY created_at DESC LIMIT 20')]
            for r in rows:r['progress']=parse(r['progress'],[])
            return public({'jobs':rows})

    @app.get('/api/agent/jobs/{job_id}')
    def job(job_id:str):
        with connect() as db:
            row=db.execute('SELECT * FROM dashboard_agent_jobs WHERE job_id=?',(job_id,)).fetchone()
            if not row:raise HTTPException(404,'Agent job not found')
            return public(dict(row)|{'progress':parse(row['progress'],[])})

    from .campaign_workflow import register
    register(app,connect,gate,executor,agent_runner,opportunity_runner)
    return app
