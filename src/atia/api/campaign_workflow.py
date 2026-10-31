"""Versioned human edits, scoped paid jobs, and approved-only planning.

No publishing/scheduler integrations. Original model content/evidence never changes.
"""
import copy
import os
import json
from datetime import date,timedelta
from typing import Literal
from uuid import UUID,uuid4
from fastapi import HTTPException
from pydantic import BaseModel,Field,ConfigDict
from atia.models import utc_now
from atia.destinations.evidence import exists
from atia.opportunities.store import CAMPAIGN_PREFIX,initialize as initialize_opportunities
from .data import parse,public


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS campaign_edits (
      edit_id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL,revision INTEGER NOT NULL,
      created_at TEXT NOT NULL,editor TEXT NOT NULL,content_json TEXT NOT NULL,dates_json TEXT NOT NULL,
      UNIQUE(campaign_id,revision),FOREIGN KEY(campaign_id) REFERENCES agent_campaigns(campaign_id));
    CREATE TABLE IF NOT EXISTS campaign_review_events (
      review_id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL,revision INTEGER NOT NULL,
      decision TEXT NOT NULL CHECK(decision IN ('APPROVED','REJECTED','REVISION_REQUESTED')),
      reviewer TEXT NOT NULL,notes TEXT NOT NULL,reviewed_at TEXT NOT NULL,
      FOREIGN KEY(campaign_id) REFERENCES agent_campaigns(campaign_id));
    CREATE TABLE IF NOT EXISTS campaign_preparation_jobs (
      job_id TEXT PRIMARY KEY,idempotency_key TEXT NOT NULL UNIQUE,entity_id TEXT,
      created_at TEXT NOT NULL,completed_at TEXT,status TEXT NOT NULL,
      progress TEXT NOT NULL,run_id TEXT,campaign_id TEXT,outcome TEXT,message TEXT);
    ''')
    initialize_opportunities(db)
    with db:db.execute("UPDATE campaign_preparation_jobs SET status='interrupted',completed_at=?,message='Server restarted. No paid retry was made.' WHERE status IN ('queued','running')",(utc_now(),))


def event_tables(campaign_id):
    """Opportunity drafts have no verified entity, so their history sits in sibling tables."""
    return ('opportunity_campaign_edits','opportunity_review_events') if campaign_id.startswith(CAMPAIGN_PREFIX) else ('campaign_edits','campaign_review_events')


def overlay(db,campaign_id,content,base_status,base_review):
    revision=0;dates={};editor=None;edits,reviews=event_tables(campaign_id)
    if exists(db,edits):
        row=db.execute(f'SELECT * FROM {edits} WHERE campaign_id=? ORDER BY revision DESC LIMIT 1',(campaign_id,)).fetchone()
        if row:revision=row['revision'];content=parse(row['content_json'],content);dates=parse(row['dates_json'],{});editor=row['editor']
    review=base_review if revision==0 else None
    if exists(db,reviews):
        row=db.execute(f'SELECT * FROM {reviews} WHERE campaign_id=? AND revision=? ORDER BY rowid DESC LIMIT 1',(campaign_id,revision)).fetchone()
        if row:review=dict(row)
    return {'content':content,'revision':revision,'edited_by':editor,'publishing_dates':dates,'review':review,
            'status':review['decision'] if review else base_status}


class BilingualEdit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    en:str=Field(min_length=1,max_length=4000)
    ar:str=Field(min_length=1,max_length=4000,pattern='[\u0621-\u064a]')


class KpiEdit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    metric:BilingualEdit
    measurement_plan:BilingualEdit
    proposed_target_hypothesis:BilingualEdit


class ClaimEdit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    claim:str=Field(min_length=1,max_length=1000)
    evidence_refs:list[str]=Field(min_length=1,max_length=20)


class EvidenceEdit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    recommendation:str=Field(min_length=1,max_length=2000)
    claims:list[ClaimEdit]=Field(min_length=1,max_length=20)
    uncertainties:list[str]=Field(min_length=1,max_length=20)


class EditRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision:int=Field(ge=0)
    editor:str=Field(min_length=1,max_length=120)
    confirmed:Literal[True]
    title:BilingualEdit|None=None
    description:BilingualEdit|None=None
    creative_direction:BilingualEdit|None=None
    captions:dict[str,BilingualEdit]=Field(default_factory=dict,max_length=30)
    publishing_dates:dict[str,date]=Field(default_factory=dict,max_length=30)
    positioning:BilingualEdit|None=None
    opportunity_hypothesis:BilingualEdit|None=None
    target_audience:BilingualEdit|None=None
    audience_rationale_hypothesis:BilingualEdit|None=None
    objectives:list[BilingualEdit]|None=Field(default=None,min_length=1,max_length=20)
    key_messages:list[BilingualEdit]|None=Field(default=None,min_length=1,max_length=20)
    risks_uncertainties_validation:list[BilingualEdit]|None=Field(default=None,min_length=1,max_length=20)
    schedule_activities:dict[str,BilingualEdit]=Field(default_factory=dict,max_length=30)
    kpis:list[KpiEdit]|None=Field(default=None,min_length=1,max_length=20)
    evidence:EvidenceEdit|None=None


class CampaignReview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    decision:Literal['APPROVED','REJECTED','REVISION_REQUESTED']
    reviewer:str=Field(default='Local reviewer',min_length=1,max_length=120)
    notes:str=Field(default='',max_length=2000)
    revision:int=Field(default=0,ge=0)
    launch_date:date|None=None
    confirmed:Literal[True]


class PreparationRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    entity_id:str|None=Field(default=None,min_length=1,max_length=100)
    opportunity_id:str|None=Field(default=None,min_length=1,max_length=100)
    idempotency_key:UUID
    confirmed:Literal[True]


def job_value(row):
    value=dict(row);value['progress']=parse(value['progress'],[]);return public(value)


OPENAI_FAILURES={'AuthenticationError':'OpenAI rejected the API key. Check OPENAI_API_KEY in .env and restart the server.',
    'PermissionDeniedError':'OpenAI refused this request for the configured key.',
    'RateLimitError':'OpenAI reported a rate limit or exhausted quota. Try again later.',
    'APITimeoutError':'OpenAI did not answer in time. The request may still be billed, so it was not retried.',
    'APIConnectionError':'ATIA could not reach OpenAI. Check the network and try again.'}


def outcome_message(result,campaign_id,decision):
    """Says what actually stopped a draft, so a person can tell a setup problem from a validation rejection."""
    errors=result.get('errors') or []
    if errors:
        error=str(errors[0])
        if error.startswith('Not sent: '):return f"No campaign was created and no OpenAI request was sent: {error[10:]}"
        if error.startswith('Draft rejected: '):return f"ATIA's checks rejected the AI draft, so nothing was saved: {error[16:]}"
        name=next((n for n in OPENAI_FAILURES if n in error),None)
        return 'No campaign was created. '+(OPENAI_FAILURES[name] if name else 'The OpenAI request failed and was not retried.')
    if campaign_id:
        validation=result.get('validation') or {}
        if validation.get('blocking'):return f"Draft saved for correction. It cannot be approved until {len(validation['blocking'])} blocking issue(s) are fixed."
        if validation.get('warnings'):return f"Draft saved with {len(validation['warnings'])} warning(s) for you to review."
        return 'Campaign prepared for human review.'
    recommendation=result.get('decision',{}).get('recommendation')
    if decision=='INVESTIGATE':return f'The model did not draft a campaign: {recommendation}' if recommendation else 'More evidence is needed before a campaign can be justified.'
    return f'The model did not draft a campaign: {recommendation}' if recommendation else 'No justified campaign opportunity was identified.'


def register(app,connect,gate,executor,agent_runner=None,opportunity_runner=None):
    from .workspace import WorkspaceData

    def find(db,identifier):
        table='opportunity_campaigns' if identifier.startswith(CAMPAIGN_PREFIX) else 'agent_campaigns'
        if not exists(db,table) or not db.execute(f'SELECT 1 FROM {table} WHERE campaign_id=?',(identifier,)).fetchone():raise HTTPException(404,'Campaign not found')
        value=next((c for c in WorkspaceData(db).campaigns() if c['id']==identifier and c['kind']=='campaign'),None)
        if not value:raise HTTPException(409,'Campaign photographs or evidence require reassessment.')
        return value

    @app.post('/api/campaigns/{campaign_id}/edit')
    def edit(campaign_id:str,body:EditRequest):
        with connect(True) as db:
            db.execute('BEGIN IMMEDIATE');c=find(db,campaign_id)
            if body.revision!=c['revision']:raise HTTPException(409,'The campaign changed. Refresh before editing.')
            if c['status'] not in ('PENDING_APPROVAL','REVISION_REQUESTED'):raise HTTPException(409,'Request revision before editing a final reviewed campaign.')
            content=copy.deepcopy(c['content']);dates={k:v.isoformat() for k,v in body.publishing_dates.items()}
            posts={p['post_id']:p for p in content.get('social_posts',[])}
            if set(body.captions)-set(posts) or set(dates)-set(posts):raise HTTPException(422,'Edits must reference saved content posts.')
            for field,key in (('title','campaign_name'),('description','central_concept'),('creative_direction','creative_direction')):
                value=getattr(body,field)
                if value is not None:content[key]=value.model_dump()
            for key,value in body.captions.items():posts[key]['caption']=value.model_dump()
            for key in ('positioning','opportunity_hypothesis','target_audience','audience_rationale_hypothesis'):
                value=getattr(body,key)
                if value is not None:content[key]=value.model_dump()
            for key in ('objectives','key_messages','risks_uncertainties_validation'):
                value=getattr(body,key)
                if value is not None:content[key]=[item.model_dump() for item in value]
            schedule={s['post_id']:s for s in content.get('publishing_schedule',[])}
            if set(body.schedule_activities)-set(schedule):raise HTTPException(422,'Edits must reference saved content posts.')
            for key,value in body.schedule_activities.items():schedule[key]['activity']=value.model_dump()
            if body.kpis is not None:
                # Baselines stay UNMEASURED: a person can reword a measure but not record a result.
                content['kpis_and_measurement']=[{**item.model_dump(),'baseline':'UNMEASURED'} for item in body.kpis]
            if body.evidence is not None:
                known=set((c.get('evidence_review') or {}).get('allowed_refs',[]))
                if any(ref not in known for claim in body.evidence.claims for ref in claim.evidence_refs):raise HTTPException(422,'Claims must cite supplied Flickr or research evidence.')
                content['review_evidence']=body.evidence.model_dump()
            if content==c['content'] and dates==c['publishing_dates']:return c
            rev=c['revision']+1
            with db:db.execute(f'INSERT INTO {event_tables(campaign_id)[0]} VALUES(?,?,?,?,?,?,?)',
                ('edit-'+uuid4().hex,campaign_id,rev,utc_now(),body.editor.strip() or 'Local editor',json.dumps(content,ensure_ascii=False),json.dumps(dates)))
            return public(find(db,campaign_id))

    @app.post('/api/campaigns/{campaign_id}/review')
    def review(campaign_id:str,body:CampaignReview):
        with connect(True) as db:
            db.execute('BEGIN IMMEDIATE');c=find(db,campaign_id)
            if body.revision!=c['revision']:raise HTTPException(409,'The draft changed. Review the current revision.')
            if body.decision=='APPROVED' and (c.get('validation') or {}).get('blocking'):raise HTTPException(409,'Fix the blocking issues in this draft before approving it.')
            if body.decision=='APPROVED' and c['media_validation_required']:raise HTTPException(409,'Image usage rights and reviewed destination associations must be verified before approval.')
            if c['review'] and c['status']==body.decision:return public(c['review'])
            if c['status']!='PENDING_APPROVAL' and body.decision!='REVISION_REQUESTED':raise HTTPException(409,'This revision has already received a final review. Request revision before changing it.')
            item={'review_id':'review-'+uuid4().hex,'campaign_id':campaign_id,'revision':body.revision,'decision':body.decision,
                  'reviewer':body.reviewer.strip() or 'Local reviewer','notes':body.notes,'reviewed_at':utc_now()}
            # A launch date turns relative days into calendar dates; opportunity drafts only.
            if campaign_id.startswith(CAMPAIGN_PREFIX):item['launch_date']=body.launch_date.isoformat() if body.launch_date and body.decision=='APPROVED' else None
            with db:db.execute(f"INSERT INTO {event_tables(campaign_id)[1]} VALUES({','.join('?'*len(item))})",tuple(item.values()))
            return public(item)

    @app.get('/api/calendar')
    def calendar():
        with connect() as db:
            entries=[]
            for c in WorkspaceData(db).campaigns():
                if c['kind']!='campaign' or c['status']!='APPROVED' or c['media_validation_required']:continue
                posts={p['post_id']:p for p in c['content'].get('social_posts',[])}
                launch=(c.get('review') or {}).get('launch_date')
                for s in c['content'].get('publishing_schedule',[]):
                    derived=(date.fromisoformat(launch)+timedelta(days=s['days_after_human_approved_launch'])).isoformat() if launch else None
                    entries.append({'campaign_id':c['id'],'campaign_name':c['content']['campaign_name'],'status':'APPROVED_PLAN',
                        'proposed_date':c['publishing_dates'].get(s['post_id']) or derived,'post_id':s['post_id'],'platform':s['channel'],
                        'local_time':s['local_time'],'timezone':s['timezone'],'relative_day':s['days_after_human_approved_launch'],
                        'caption':posts.get(s['post_id'],{}).get('caption'),'media':c['media'][:1]})
            return public({'entries':entries,'external_scheduling':False})

    def worker(identifier,entity_id,opportunity_id=None):
        def progress(_):
            with connect(True) as db:
                row=db.execute('SELECT progress FROM campaign_preparation_jobs WHERE job_id=?',(identifier,)).fetchone()
                events=parse(row['progress'],[])
                if not events:events.append({'at':utc_now(),'message':'Reviewing approved destination evidence and existing research.'})
                with db:db.execute('UPDATE campaign_preparation_jobs SET progress=? WHERE job_id=?',(json.dumps(events),identifier))
        try:
            with connect(True) as db:
                with db:db.execute("UPDATE campaign_preparation_jobs SET status='running' WHERE job_id=?",(identifier,))
            from atia.storage.sqlite import PhotoStore
            from atia.agents.runner import run_agent
            from atia.agents.contracts import Limits
            with connect() as db:path=db.execute('PRAGMA database_list').fetchone()[2]
            with PhotoStore(path) as store:
                if opportunity_id:
                    from atia.opportunities.generate import run_opportunity
                    result=(opportunity_runner or run_opportunity)(store,opportunity_id,limits=Limits.load(),progress=progress)
                else:
                    result=(agent_runner or run_agent)(store,target_entity_id=entity_id,limits=Limits.load(),progress=progress)
            with connect(True) as db:
                campaign_id=result.get('campaign_id')
                if not campaign_id and entity_id and not opportunity_id:
                    existing=next((c for c in WorkspaceData(db).campaigns() if c['kind']=='campaign' and c['content']['destination']['entity_id']==entity_id and c['status']!='REJECTED'),None)
                    campaign_id=existing['id'] if existing else None
                decision=result.get('decision',{}).get('decision','INVESTIGATE')
                message=outcome_message(result,campaign_id,decision)
                with db:db.execute('UPDATE campaign_preparation_jobs SET status=?,completed_at=?,run_id=?,campaign_id=?,outcome=?,message=? WHERE job_id=?',
                    ('needs_review' if result.get('errors') else 'completed',utc_now(),result.get('run_id'),campaign_id,decision,message,identifier))
        except Exception:
            with connect(True) as db:
                with db:db.execute("UPDATE campaign_preparation_jobs SET status='failed',completed_at=?,message=? WHERE job_id=?",
                    (utc_now(),'Investigation failed safely. No automatic paid retry was made.',identifier))

    @app.post('/api/campaign-requests',status_code=202)
    def prepare(body:PreparationRequest):
        from atia.agents.contracts import Limits
        with gate,connect(True) as db:
            db.execute('BEGIN IMMEDIATE')
            from atia.opportunities.generate import next_opportunity
            from atia.opportunities.store import OpportunityStore
            prior=db.execute('SELECT * FROM campaign_preparation_jobs WHERE idempotency_key=?',(str(body.idempotency_key),)).fetchone()
            if prior:
                if prior['entity_id'] not in (body.entity_id,body.opportunity_id) and (body.entity_id or body.opportunity_id):raise HTTPException(409,'Request key belongs to another destination')
                return job_value(prior)
            workspace=WorkspaceData(db).snapshot()
            curated=OpportunityStore(db).opportunities()
            opportunity_id=body.opportunity_id
            # Without a chosen target, ATIA picks the strongest curated opportunity still lacking a draft.
            if not opportunity_id and not body.entity_id and curated:
                chosen=next_opportunity(db)
                if not chosen:return {'status':'existing','progress':[],'message':'Every current opportunity already has a draft. No paid request was made.'}
                opportunity_id=chosen['opportunity_id']
            if opportunity_id:
                if not any(o['opportunity_id']==opportunity_id for o in curated):raise HTTPException(409,'That opportunity is not available.')
                existing=next((c for c in workspace['campaigns'] if c.get('opportunity_id')==opportunity_id and c['status']!='REJECTED'),None)
                if existing:return {'status':'existing','campaign_id':existing['id'],'progress':[],'message':'A draft already exists. No paid request was made.'}
            if body.entity_id:
                eligible=[a for a in workspace['areas'] if any(e['entity_id']==body.entity_id and e['verification_status']=='authoritative_source_name_confirmed' and e['entity_type'] in ('destination','attraction') for e in a['entities'])]
                from atia.agents.discovery_tools import candidate_pool
                from types import SimpleNamespace
                pool=candidate_pool(SimpleNamespace(connection=db))
                if not eligible or not any(any(e['entity_id']==body.entity_id for e in p['candidate_names']) for p in pool):raise HTTPException(409,'A verified destination with eligible geographic evidence is required.')
                existing=next((c for c in workspace['campaigns'] if c['kind']=='campaign' and c['content']['destination']['entity_id']==body.entity_id and c['status']!='REJECTED'),None)
                if existing:return {'status':'existing','campaign_id':existing['id'],'entity_id':body.entity_id,'progress':[],'message':'An existing campaign is available. No paid request was made.'}
            if db.execute("SELECT 1 FROM campaign_preparation_jobs WHERE status IN ('queued','running')").fetchone() or db.execute("SELECT 1 FROM dashboard_agent_jobs WHERE status IN ('queued','running')").fetchone():raise HTTPException(409,'An investigation is already active.')
            Limits.load()
            # Checked before queueing, so the person sees the reason where they asked.
            runner=opportunity_runner if opportunity_id else agent_runner
            if not runner and not os.getenv('OPENAI_API_KEY','').strip():raise HTTPException(503,'Live AI generation requires configuration: set OPENAI_API_KEY in .env and restart the server. No request was sent and nothing was charged. Saved campaigns stay available.')
            item={'job_id':'preparation-'+uuid4().hex,'idempotency_key':str(body.idempotency_key),'entity_id':opportunity_id or body.entity_id,'created_at':utc_now(),
                  'completed_at':None,'status':'queued','progress':'[]','run_id':None,'campaign_id':None,'outcome':None,'message':'Investigation queued.'}
            with db:db.execute('INSERT INTO campaign_preparation_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?)',tuple(item.values()))
            executor.submit(worker,item['job_id'],body.entity_id,opportunity_id)
            return public(item|{'progress':[]})

    @app.get('/api/campaign-requests')
    def jobs():
        with connect() as db:return {'jobs':[job_value(r) for r in db.execute('SELECT * FROM campaign_preparation_jobs ORDER BY created_at DESC LIMIT 10')]}

    @app.get('/api/campaign-requests/{job_id}')
    def job(job_id:str):
        with connect() as db:
            row=db.execute('SELECT * FROM campaign_preparation_jobs WHERE job_id=?',(job_id,)).fetchone()
            if not row:raise HTTPException(404,'Campaign request not found')
            return job_value(row)
