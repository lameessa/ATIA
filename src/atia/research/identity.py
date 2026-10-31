"""Authoritative entity verification is distinct from Flickr-cluster association."""
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import re
import time
import uuid
from collections import Counter
from atia.models import utc_now
from atia.destinations.storage import DestinationStore
from atia.research.tool import authoritative,digest,queries_for
from atia.research.providers import ResearchFailed,ResearchUnavailable
from atia.research.tavily import TavilySearch

RULE_VERSION='authoritative-entities-and-provisional-associations-v3'
DOMAINS=['visitsaudi.com','experiencealula.com','saudipedia.com','spa.gov.sa','whc.unesco.org','rcu.gov.sa','ncw.gov.sa','vision2030.gov.sa']
TYPE_MARKERS={
 'attraction':['palace','fort','museum','attraction','venue','hall','entertainment','landmark','قصر','حصن','متحف','معلم','قاعة','ترفيه'],
 'destination':['destination','destinations','city','cities','district','districts','island','islands','archipelago','town','oasis','tourism','visit','مدينة','وجهة','جزر','جزيرة','سياح'],
 'region':['region','province','منطقة'],
}
PROMOTIONAL=['visit','visitor','visitors','tour','tours','ticket','tickets','experience','experiences','explore','discover','attraction','attractions','museum','museums','سياح','زوار','زيارة','استكشف']


def normalized(text):return re.sub(r'[^\w]+',' ',str(text).casefold()).strip()


def contains(text,aliases):
    text=' '+normalized(text)+' '
    return any(' '+normalized(alias)+' ' in text for alias in aliases if normalized(alias))


def verify_sources(option,sources):
    """Conservative and auditable: exact candidate alias in authoritative title,
    substantive source content, and type evidence. Generic navigation mentions
    and a name supplied in a Flickr title never suffice. No generated API answer.
    """
    verified=[]
    for source in sources:
        if source.get('access')!='tavily_search_content' or not authoritative(source['url']):continue
        title,content=source['title'],source['evidence']
        if not contains(title,option['aliases']):continue
        if len(content.strip())<40:continue
        if not contains(title+' '+content,TYPE_MARKERS[option['entity_type']]):continue
        verified.append({**source,'verification_rule':RULE_VERSION,'verification_scope':'source confirms named entity and type; no cluster-boundary authentication'})
    return verified


def supports_parent(option,source):
    parent=option.get('parent')
    if not parent:return False
    text=source['title']+' '+source['evidence']
    if not contains(text,parent['aliases']):return False
    relations=['located in','situated in','in the city of','district of','in jeddah','in alula','in riyadh','in jazan','in jizan',
               "alula's","alula’s","riyadh's","riyadh’s",'city of','within','في','يقع','بمدينة']
    if any(contains(text,[phrase]) for phrase in relations):return True
    # Explicit possessive context, e.g. Jeddah's historic district, supports a
    # parent relationship without treating mere navigation co-occurrence as proof.
    if any(contains(text,[alias+"'s historic district"]) for alias in parent['aliases']):return True
    # A tourism authority's explicit URL taxonomy can also support a parent.
    from urllib.parse import urlparse
    parsed=urlparse(source['url'])
    if parsed.hostname and (parsed.hostname=='visitsaudi.com' or parsed.hostname.endswith('.visitsaudi.com')):
        return any('/'+normalized(alias).replace(' ','-')+'/' in parsed.path.lower() for alias in parent['aliases'] if alias.isascii())
    return False



def coverage_sources(option,sources):
    return [source for source in verify_sources(option,sources)
            if contains(source['title']+' '+source['evidence'],PROMOTIONAL)]


class IdentityStore:
    def __init__(self,store,initialize=True):
        self.db=store.connection;self.db.execute('PRAGMA foreign_keys=ON')
        if not initialize:return
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS verified_location_entities (
          entity_id TEXT PRIMARY KEY,verified_name TEXT NOT NULL,entity_type TEXT NOT NULL,
          verification_status TEXT NOT NULL,first_verified_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS authoritative_entity_verifications (
          verification_id TEXT PRIMARY KEY,entity_id TEXT NOT NULL,parent_entity_id TEXT,parent_status TEXT NOT NULL,
          verified_at TEXT NOT NULL,provider TEXT NOT NULL,rule_version TEXT NOT NULL,sources TEXT NOT NULL,
          FOREIGN KEY(entity_id) REFERENCES verified_location_entities(entity_id),
          FOREIGN KEY(parent_entity_id) REFERENCES verified_location_entities(entity_id));
        CREATE TABLE IF NOT EXISTS cluster_entity_associations (
          association_id TEXT PRIMARY KEY,destination_run_id TEXT NOT NULL,cluster_id TEXT NOT NULL,
          entity_id TEXT,verification_id TEXT,association_status TEXT NOT NULL,reason TEXT NOT NULL,assessed_at TEXT NOT NULL,
          FOREIGN KEY(destination_run_id,cluster_id) REFERENCES destination_snapshots(run_id,destination_id),
          FOREIGN KEY(entity_id) REFERENCES verified_location_entities(entity_id),
          FOREIGN KEY(verification_id) REFERENCES authoritative_entity_verifications(verification_id));
        CREATE TABLE IF NOT EXISTS live_location_research (
          assessment_id TEXT PRIMARY KEY,destination_run_id TEXT NOT NULL,cluster_id TEXT NOT NULL,
          cache_key TEXT NOT NULL,provider TEXT NOT NULL,assessed_at TEXT NOT NULL,result TEXT NOT NULL,
          FOREIGN KEY(destination_run_id,cluster_id) REFERENCES destination_snapshots(run_id,destination_id));
        CREATE INDEX IF NOT EXISTS live_location_cache ON live_location_research(cache_key,assessed_at);
        CREATE TABLE IF NOT EXISTS historical_research_identity_audits (
          research_id TEXT PRIMARY KEY,audited_at TEXT NOT NULL,assessment TEXT NOT NULL,
          FOREIGN KEY(research_id) REFERENCES promotional_research(research_id));
        ''');self.db.commit()

    def entity(self,option):
        identifier='entity-'+uuid.uuid5(uuid.NAMESPACE_URL,'atia:'+option['entity_type']+':'+normalized(option['name'])).hex[:20]
        self.db.execute('INSERT OR IGNORE INTO verified_location_entities VALUES(?,?,?,?,?)',
                        (identifier,option['name'],option['entity_type'],'authoritative_source_name_confirmed',utc_now()))
        return identifier

    def save_verification(self,option,sources,parent=None,parent_sources=None):
        with self.db:
            identifier=self.entity(option);parent_id=None;parent_status='not_established'
            if parent and parent_sources and any(supports_parent(option,source) for source in sources):
                parent_id=self.entity(parent);parent_status='source_supported'
                # Record the parent's own authoritative sources too.
                self.db.execute('INSERT INTO authoritative_entity_verifications VALUES(?,?,?,?,?,?,?,?)',
                    ('verify-'+uuid.uuid4().hex,parent_id,None,'not_established',utc_now(),'tavily_live_api_v1',RULE_VERSION,json.dumps(parent_sources,ensure_ascii=False)))
            verification_id='verify-'+uuid.uuid4().hex
            self.db.execute('INSERT INTO authoritative_entity_verifications VALUES(?,?,?,?,?,?,?,?)',
                (verification_id,identifier,parent_id,parent_status,utc_now(),'tavily_live_api_v1',RULE_VERSION,json.dumps(sources,ensure_ascii=False)))
        return {'entity_id':identifier,'verification_id':verification_id,'verified_name':option['name'],
                'entity_type':option['entity_type'],'verification_status':'authoritative_source_name_confirmed',
                'parent_entity_id':parent_id,'parent_name':parent['name'] if parent_id else None,'parent_candidate':parent['name'] if parent else None,
                'parent_type':parent['entity_type'] if parent_id else None,'parent_status':parent_status,
                'verified_at':utc_now(),'sources':sources}

    def audit_historical(self):
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='promotional_research'").fetchone():return
        for row in self.db.execute('SELECT research_id,result FROM promotional_research').fetchall():
            result=json.loads(row['result'])
            scope_note=('Already correctly unresolved; no verified cluster name was asserted.' if not result.get('verified_name') else
                        'Source-reviewed entity name with scoped association; retain as historical evidence, not official cluster naming or live Tavily verification.')
            audit={'original_provider':result['provider'],'original_identity_status':result['identity_status'],
                   'interpretation':'Historical source-review observation, not a live Tavily result or authoritative cluster identity.',
                   'verified_name_scope':scope_note,'original_records_modified':False}
            with self.db:self.db.execute('''INSERT INTO historical_research_identity_audits VALUES(?,?,?)
                ON CONFLICT(research_id) DO UPDATE SET audited_at=excluded.audited_at,assessment=excluded.assessment''',
                (row['research_id'],utc_now(),json.dumps(audit)))

    def catalogue(self):
        snapshot_row=self.db.execute('SELECT report FROM destination_runs ORDER BY created_at DESC LIMIT 1').fetchone()
        if snapshot_row is None:raise ValueError('No geographic destination snapshot exists')
        snapshot=json.loads(snapshot_row['report'])
        latest={}
        for assessment in self.inspect():latest.setdefault(assessment['cluster_id'],assessment)
        clusters=[]
        for group in snapshot['destinations']:
            assessment=latest.get(group['destination_id'])
            clusters.append({'cluster_id':group['destination_id'],'original_name':group['name'],'classification':'geographic_cluster',
                'association_status':assessment['association_status'] if assessment else 'not_researched',
                'official_cluster_name':None,'candidate_entity_ids':[e['entity_id'] for e in assessment['entities']] if assessment else []})
        entities=[]
        for row in self.db.execute('SELECT * FROM verified_location_entities ORDER BY entity_type,verified_name'):
            item=dict(row)
            verification=self.db.execute('SELECT * FROM authoritative_entity_verifications WHERE entity_id=? ORDER BY verified_at DESC LIMIT 1',(row['entity_id'],)).fetchone()
            if verification:
                item['parent_entity_id']=verification['parent_entity_id'];item['parent_status']=verification['parent_status']
                item['sources']=json.loads(verification['sources']);item['verification_timestamp']=verification['verified_at']
                item['provider']=verification['provider'];item['verification_rule']=verification['rule_version']
            entities.append(item)
        for entity in entities:
            entity['direct_cluster_ids']=[c['cluster_id'] for c in clusters if entity['entity_id'] in c['candidate_entity_ids']]
            children={e['entity_id'] for e in entities if e.get('parent_entity_id')==entity['entity_id']}
            entity['provisionally_associated_via_children']=[c['cluster_id'] for c in clusters if children.intersection(c['candidate_entity_ids'])]
        return {'destination_run_id':snapshot['run_id'],'geographic_clusters':clusters,'verified_entities':entities,
                'unresolved_locations':[c for c in clusters if c['association_status'].startswith('unresolved')],
                'note':'An authoritative entity name is not an officially confirmed Flickr-cluster name. not_researched does not mean unresolvable.'}

    def inspect(self,cluster_id=None):
        query='SELECT result FROM live_location_research';params=[]
        if cluster_id:query+=' WHERE cluster_id=?';params.append(cluster_id)
        query+=' ORDER BY assessed_at DESC'
        return [json.loads(row['result']) for row in self.db.execute(query,params)]


def identity_query(option):
    parent=option.get('parent',{}).get('name','Saudi Arabia')
    return f"{option['name']} {parent} official tourism {option.get('query_context',option['entity_type'])}"


def research_locations(store,provider,candidates,ids=None,limit=5,refresh=False,progress=None):
    if not 3<=limit<=5:raise ValueError('Validation limit must be between 3 and 5 locations')
    started=time.monotonic();emit=progress or (lambda _:None);storage=IdentityStore(store);storage.audit_historical()
    snapshot=DestinationStore(store).inspect();groups={g['destination_id']:g for g in snapshot['destinations']}
    plans=candidates['locations']
    if ids:
        if any(identifier not in {p['cluster_id'] for p in plans} for identifier in ids):raise ValueError('No candidate hints supplied for selected cluster')
        plans=[p for p in plans if p['cluster_id'] in ids]
    plans=plans[:limit];results=[]
    for plan in plans:
        group=groups.get(plan['cluster_id'])
        if group is None:raise ValueError('Candidate does not exist in current geographic snapshot')
        if not (group['evidence']['historical_curated_observations'] or group['evidence']['relevance_coverage'].get('relevant')):raise ValueError('Candidate lacks curated or relevant tourism evidence')
        key=digest({'rule':RULE_VERSION,'plan':plan,'provider':provider.cache_identity,
                    'geography':{field:group[field] for field in ('destination_id','photo_ids','centroid','bbox')}})
        previous=storage.db.execute('SELECT result,assessed_at FROM live_location_research WHERE cache_key=? ORDER BY assessed_at DESC LIMIT 1',(key,)).fetchone()
        if not refresh and previous and datetime.fromisoformat(previous['assessed_at'])>=datetime.now(timezone.utc)-timedelta(hours=168):
            cached=json.loads(previous['result'])
            if not cached['errors']:
                cached['cached']=True;results.append(cached);emit(f"{plan['cluster_id']}: cached Tavily assessment");continue
        emit(f"{plan['cluster_id']}: verifying candidate names against live Tavily sources...")
        observation_start=len(provider.observations);entities=[];unconfirmed=[];errors=[];sources=[]
        for option in plan['options']:
            if option['entity_type'] not in TYPE_MARKERS or not option.get('aliases'):raise ValueError('Invalid entity type/aliases')
            try:
                raw=provider.search(identity_query(option),domains=DOMAINS);sources.extend(raw)
                official=verify_sources(option,raw)
                if not official:unconfirmed.append({'candidate_name':option['name'],'reason':'No authoritative title/content/type confirmation in returned results'});continue
                parent=option.get('parent');parent_official=[]
                if parent:
                    parent_raw=provider.search(identity_query(parent),domains=DOMAINS);sources.extend(parent_raw)
                    parent_official=verify_sources(parent,parent_raw)
                entity=storage.save_verification(option,official,parent,parent_official)
                promo=provider.search(f"{option['name']} official visit tour visitor experience Saudi Arabia",domains=DOMAINS)
                sources.extend(promo);matches=coverage_sources(option,official+promo)
                entity['coverage_status']='coverage_found' if matches else 'insufficient_evidence'
                entity['coverage_sources']={s['url']:s for s in matches};entities.append(entity)
            except (ResearchUnavailable,ResearchFailed) as exc:
                errors.append({'candidate_name':option['name'],'error_type':type(exc).__name__,'message':str(exc)})
        # Even one confirmed real entity does not establish cluster/site identity.
        if len(plan['options'])>1:association='unresolved_multiple_attractions'
        elif entities:association='provisional_metadata_match_not_authoritatively_mapped'
        else:association='unresolved_no_authoritative_entity_confirmation'
        status='insufficient_evidence' if not entities or len(plan['options'])>1 else entities[0]['coverage_status']
        if not entities and errors:status='research_unavailable' if all(e['error_type']=='ResearchUnavailable' for e in errors) else 'research_failed'
        result={'assessment_id':'live-research-'+uuid.uuid4().hex,'cluster_id':plan['cluster_id'],'destination_run_id':snapshot['run_id'],
                'cluster_name':group['name'],'cluster_type':'geographic_cluster','association_status':association,
                'confirmed_cluster_name':None,'entities':entities,'unconfirmed_candidates':unconfirmed,'research_status':status,
                'provider':provider.name,'source_origin':'live_tavily_api','assessed_at':utc_now(),'cached':False,
                'source_observations':provider.observations[observation_start:],'sources':list({s['url']:s for s in sources}.values()),
                'association_notes':plan['association_notes'],'errors':errors,'promotional_gap_claim':None,
                'limitations':['Authoritative entity names/types are separate from a confirmed cluster identity.',
                    'No source independently maps these Flickr photo IDs or the full cluster boundary to an attraction.',
                    'Tavily returns retrieved source excerpts; no generated answer is used and full page completeness is not established.',
                    'Limited source domains and English queries; no absence, underpromotion, demand, or reach inference.']}
        with storage.db:
            storage.db.execute('INSERT INTO live_location_research VALUES(?,?,?,?,?,?,?)',
                (result['assessment_id'],snapshot['run_id'],plan['cluster_id'],key,provider.name,result['assessed_at'],json.dumps(result,ensure_ascii=False)))
            for entity in entities or [None]:
                storage.db.execute('INSERT INTO cluster_entity_associations VALUES(?,?,?,?,?,?,?,?)',
                    ('association-'+uuid.uuid4().hex,snapshot['run_id'],plan['cluster_id'],entity['entity_id'] if entity else None,
                     entity['verification_id'] if entity else None,association,plan['association_notes'],utc_now()))
        results.append(result)
    return {'provider':provider.name,'locations':results,'investigated':len(results),'network_requests':provider.network_calls,
            'query_cache_hits':provider.cache_hits,'assessment_cache_hits':sum(r['cached'] for r in results),
            'elapsed_seconds':round(time.monotonic()-started,3),'note':'All new sources come from direct Python Tavily requests or their explicit local cache; no Codex web observations are imported.'}


def write_audit_report(report,path='AUTHORITATIVE_RESEARCH_AUDIT.md'):
    lines=['# Phase 4/5 correction and live Tavily validation','',
      'Geographic clusters remain neutral, unchanged groups of geotagged photos. A verified destination is a named broader tourism entity; a verified attraction is a specific landmark. Regions are geographic context. Unresolved locations and provisional associations are not officially named clusters.',
      '',f"Provider: `{report['provider']}`. {report['network_requests']} live HTTP requests; {report['query_cache_hits']} query-cache hits; {report['assessment_cache_hits']} assessment-cache hits. Execution: {report['elapsed_seconds']} seconds.",
      '', '| Original cluster | Authoritatively confirmed entities | Parent destination/region | Association status | Coverage |', '|---|---|---|---|---|']
    for row in report['locations']:
        lines.append(f"| {row['cluster_id']} | {', '.join(e['verified_name']+' ('+e['entity_type']+')' for e in row['entities']) or 'unresolved'} | {', '.join(e['parent_name'] or 'not established' for e in row['entities'])} | {row['association_status']} | {row['research_status']} |")
    for row in report['locations']:
        lines+=['',f"## {row['cluster_id']}",'',row['association_notes'],
                '',f"Original cluster name: {row['cluster_name']}. Confirmed official cluster name: **none**. Source origin: {row['source_origin']}. Timestamp: {row['assessed_at']}."]
        for entity in row['entities']:
            lines+=['',f"### {entity['verified_name']} — {entity['entity_type']}",'',
                f"Status: {entity['verification_status']}. Parent: {entity['parent_name'] or 'not established'} ({entity['parent_status']}). Coverage: {entity['coverage_status']}."]
            for source in entity['sources']:
                lines.append(f"- [{source['title']}]({source['url']}) — {source['publisher']}; live Tavily retrieved content. Name/type confirmation does not authenticate the cluster.")
            for source in entity['coverage_sources'].values():lines.append(f"- Coverage evidence: [{source['title']}]({source['url']}) — {source['publisher']}.")
        if row['unconfirmed_candidates']:lines+=['','Unconfirmed candidates: `'+json.dumps(row['unconfirmed_candidates'])+'`']
        if row['errors']:lines+=['','Errors: `'+json.dumps(row['errors'])+'`']
        lines+=['']+['- '+item for item in row['limitations']]
    lines+=['','## Audit conclusions','',
       'Already correct: bounded complete-link geographic clustering; neutral IDs; unassigned missing/coarse geotags; immutable snapshots; scoped coverage statuses; recorded-versus-live provenance; no underpromotion claim.',
       '', 'Fixed: the old research field verified_name could conflate existence of an attraction with identification of a cluster. New authoritative entities, verification records, parent links, and provisional/unresolved cluster associations separate those concepts. Old records are preserved and annotated in an additive audit table. No Flickr title, OpenCLIP category, or approximate coordinate alone verifies an identity.',
       '', 'Verification uses authoritative URL boundaries, an entity alias in the returned source title, meaningful source content, and source-supported type markers. This is an auditable rule, not independent field verification. Generic navigation mentions are not accepted as identity proof. Parent links require a separately confirmed parent and child-source location context.',
       '', 'Python calls the real Tavily HTTPS API with bearer authentication loaded from .env; no connected Codex tool is needed at runtime. Credentials are never placed in logs or stored responses. Only successful responses are cached. Credentials/quota errors, rate limiting, timeouts, and malformed results are handled explicitly. Old Codex-observation findings are not reused as live proof.',
       '', 'No models trained, no Phase 6, no frontend, no push.']
    Path(path).write_text('\n'.join(lines)+'\n')
