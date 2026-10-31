from collections import Counter
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import time
import uuid
from urllib.parse import urlparse
from atia.models import utc_now
from atia.destinations.storage import DestinationStore
from atia.research.providers import Source,ResearchFailed,ResearchUnavailable,public_url

VERSION='promotional-research-v1'
AUTHORITATIVE=('visitsaudi.com','experiencealula.com','whc.unesco.org','unesco.org','spa.gov.sa','saudipedia.com','ncw.gov.sa','moc.gov.sa','rcu.gov.sa')


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def authoritative(url):
    if not public_url(url):return False
    host=urlparse(url).hostname
    return any(host==domain or host.endswith('.'+domain) for domain in AUTHORITATIVE)


def queries_for(name):
    return [f'"{name}" (site:visitsaudi.com OR site:experiencealula.com OR site:spa.gov.sa)',
            f'"{name}" Saudi Arabia tourism visitor attraction']


class ResearchStore:
    def __init__(self,store):
        self.db=store.connection;self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS promotional_research (
          research_id TEXT PRIMARY KEY,destination_run_id TEXT NOT NULL,destination_id TEXT NOT NULL,
          cache_key TEXT NOT NULL,provider TEXT NOT NULL,research_timestamp TEXT NOT NULL,
          verified_name TEXT,identity_status TEXT NOT NULL,coverage_status TEXT NOT NULL,
          resolution TEXT NOT NULL,queries TEXT NOT NULL,limitations TEXT NOT NULL,result TEXT NOT NULL,
          FOREIGN KEY(destination_run_id,destination_id) REFERENCES destination_snapshots(run_id,destination_id));
        CREATE INDEX IF NOT EXISTS promotional_research_cache ON promotional_research(cache_key,research_timestamp);
        CREATE TABLE IF NOT EXISTS promotional_research_sources (
          research_id TEXT NOT NULL,url TEXT NOT NULL,title TEXT NOT NULL,publisher TEXT NOT NULL,
          evidence TEXT NOT NULL,kind TEXT NOT NULL,access TEXT NOT NULL,subject_match INTEGER NOT NULL,
          scope TEXT NOT NULL,source_observed_at TEXT,
          PRIMARY KEY(research_id,url),FOREIGN KEY(research_id) REFERENCES promotional_research(research_id));
        ''');self.db.commit()

    def inspect(self,destination_id=None):
        query='SELECT result FROM promotional_research';params=[]
        if destination_id:query+=' WHERE destination_id=?';params.append(destination_id)
        query+=' ORDER BY research_timestamp DESC'
        return [json.loads(row['result']) for row in self.db.execute(query,params)]


def select_candidates(store,limit=5,ids=None):
    if not 1<=limit<=5:raise ValueError('Research batch limit must be between 1 and 5')
    report=DestinationStore(store).inspect()
    candidates=[]
    for group in report['destinations']:
        e=group['evidence']
        if not (e['historical_curated_observations'] or e['relevance_coverage'].get('relevant')):continue
        if e['relevance_coverage'].get('irrelevant'):continue
        candidates.append(group)
    if ids:
        allowed={g['destination_id']:g for g in candidates}
        if len(set(ids))!=len(ids) or any(identifier not in allowed for identifier in ids):raise ValueError('Selected destinations require curated/relevant evidence and no screened-irrelevant members')
        if len(ids)>limit:raise ValueError('More destinations selected than batch limit')
        candidates=[allowed[identifier] for identifier in ids]
    else:
        # Readiness, not demand or marketing potential. Never rank by views or sentiment.
        candidates.sort(key=lambda g:(-bool(g['evidence']['relevance_coverage'].get('relevant')),
                            -bool(g['reported_localities']),-min(g['evidence']['historical_curated_observations'],2),g['destination_id']))
    return report['run_id'],candidates[:limit]


def validate_resolution(group,resolution):
    if not resolution or resolution.get('status')!='resolved':return None
    name=resolution.get('verified_name')
    if not isinstance(name,str) or not name.strip() or name.startswith(('dest-','Unidentified')):raise ValueError('Neutral cluster identifiers cannot be verified attraction names')
    if not resolution.get('match_basis') or not resolution.get('association_scope'):raise ValueError('Identity requires geographic/metadata match basis and scope')
    references=resolution.get('sources',[])
    if not references or not any(authoritative(row.get('url')) and row.get('kind')=='identity_reference' for row in references):raise ValueError('Identity requires a recorded authoritative reference')
    for row in references:Source(**row).validate()
    if resolution.get('destination_id')!=group['destination_id']:raise ValueError('Identity belongs to another destination')
    return name.strip()


def research_destination(store,destination_id,provider,resolution=None,run_id=None,ttl_hours=168,refresh=False):
    """Agent-callable JSON tool; provider.search(query) returns sourced observations.

    No LLM, page scraping, or invented gap scoring. Explicit name verification is
    separate from a search hit; provider snippets alone never resolve an identity.
    """
    if ttl_hours<=0:raise ValueError('Cache TTL must be positive')
    storage=ResearchStore(store)
    snapshot=DestinationStore(store).inspect(run_id)
    group=next((g for g in snapshot['destinations'] if g['destination_id']==destination_id),None)
    if group is None:raise ValueError('Unknown destination in selected snapshot')
    name=validate_resolution(group,resolution)
    scope={field:group.get(field) for field in ('destination_id','photo_ids','centroid','bbox','name_reference')}
    key=digest({'version':VERSION,'geographic_scope':scope,'resolution':resolution,'provider':provider.cache_identity})
    if not refresh:
        row=storage.db.execute('SELECT result,research_timestamp FROM promotional_research WHERE cache_key=? ORDER BY research_timestamp DESC LIMIT 1',(key,)).fetchone()
        if row and json.loads(row['result'])['research_status'] not in {'research_unavailable','research_failed'} and datetime.fromisoformat(row['research_timestamp'])>=datetime.now(timezone.utc)-timedelta(hours=ttl_hours):
            result=json.loads(row['result']);result['cached']=True;result['requested_destination_run_id']=snapshot['run_id'];return result
    started=time.monotonic();sources={};failures=[];completed=[];queries=queries_for(name) if name else []
    limitations=['Bounded searched sources/languages/date; absence in results is not proof of no promotion or underpromotion.',
                 'Flickr counts, views, favorites and sentiment are not promotional coverage evidence.',
                 'Verifying a real entity name does not independently authenticate every photograph or cluster boundary.']
    if resolution:limitations.extend(resolution.get('limitations',[]))
    for source in (resolution or {}).get('sources',[]):sources[source['url']]=Source(**source).validate()
    for query in queries:
        try:
            results=provider.search(query)
            for row in results:
                row=Source(**row).validate();sources[row['url']]=row
            completed.append(query)
        except ResearchUnavailable as exc:failures.append({'query':query,'type':'unavailable','message':str(exc)})
        except ResearchFailed as exc:failures.append({'query':query,'type':'failed','message':str(exc)})
    matches=[s for s in sources.values() if s['kind']=='promotional_coverage' and s['subject_match'] and s['scope'] in {'specific_destination','broader_destination'}]
    # An API description is a lead until content/subject is explicitly reviewed.
    if not name:status='insufficient_evidence';identity='unresolved'
    elif matches:status='coverage_found';identity='verified_name_with_scoped_association'
    elif not completed:status='research_failed' if any(f['type']=='failed' for f in failures) else 'research_unavailable';identity='verified_name_with_scoped_association'
    elif failures or any(s['kind']=='unclassified_search_result' for s in sources.values()):status='insufficient_evidence';identity='verified_name_with_scoped_association'
    else:status='no_coverage_found_within_searched_sources';identity='verified_name_with_scoped_association'
    if failures:limitations.append('Some external requests were unavailable/failed; coverage is incomplete.')
    if any(s['access']=='search_index_excerpt' for s in sources.values()):limitations.append('Some evidence is indexed search text; full source text was not accessible/read. Do not infer current completeness.')
    if matches and all(s['scope']=='broader_destination' for s in matches):limitations.append('Coverage is of the broader named destination, not a dedicated page for the precise photo cluster.')
    if not name:limitations.append('No uniquely verified destination identity; promotional coverage cannot be attributed to this cluster.')
    result={'research_id':'research-'+uuid.uuid4().hex,'destination_run_id':snapshot['run_id'],'destination_id':destination_id,
            'verified_name':name,'identity_status':identity,'research_status':status,'research_timestamp':utc_now(),
            'provider':provider.name,'resolution':resolution,'queries_planned':queries,'queries_completed':completed,
            'sources':list(sources.values()),'coverage_evidence_urls':[s['url'] for s in matches] if name else [],
            'failures':failures,'limitations':limitations,'promotional_gap_claim':None,'cached':False,
            'elapsed_seconds':round(time.monotonic()-started,4)}
    with storage.db:
        storage.db.execute('INSERT INTO promotional_research VALUES('+','.join('?' for _ in range(13))+')',
            (result['research_id'],snapshot['run_id'],destination_id,key,provider.name,result['research_timestamp'],name,identity,status,
             json.dumps(resolution),json.dumps(queries),json.dumps(limitations),json.dumps(result)))
        for source in sources.values():
            storage.db.execute('INSERT INTO promotional_research_sources VALUES(?,?,?,?,?,?,?,?,?,?)',
              (result['research_id'],source['url'],source['title'],source['publisher'],source['evidence'],source['kind'],source['access'],int(source['subject_match']),source['scope'],source['observed_at']))
    return result


def run_research(store,provider,resolutions=None,ids=None,limit=5,refresh=False,progress=None):
    started=time.monotonic();emit=progress or (lambda message:None)
    run_id,groups=select_candidates(store,limit,ids);resolutions=resolutions or {}
    results=[]
    for group in groups:
        identifier=group['destination_id'];emit(f'Researching {identifier} (verified names only)...')
        results.append(research_destination(store,identifier,provider,resolutions.get(identifier),run_id,refresh=refresh))
    return {'destination_run_id':run_id,'provider':provider.name,'investigated':len(results),
            'status_counts':dict(Counter(r['research_status'] for r in results)),
            'results':results,'elapsed_seconds':round(time.monotonic()-started,4)}


def write_report(report,path='PROMOTIONAL_RESEARCH.md'):
    lines=['# ATIA promotional coverage research','',f"Destination snapshot: `{report['destination_run_id']}`. Provider: `{report['provider']}`.",
           '', 'This is source-grounded, bounded coverage research. No underpromotion or marketing-opportunity score is inferred.',
           '', '| Candidate | Verified name | Status | Evidence |','|---|---|---|---|']
    for r in report['results']:lines.append(f"| {r['destination_id']} | {r['verified_name'] or 'unresolved'} | {r['research_status']} | {len(r['coverage_evidence_urls'])} promotional sources |")
    for r in report['results']:
        lines+=['',f"## {r['verified_name'] or r['destination_id']+' — unresolved'}",'',f"Research timestamp: {r['research_timestamp']}. Identity: {r['identity_status']}. Cached: {r['cached']}.",
                '', 'Association: '+str((r['resolution'] or {}).get('match_basis','No verified association.')),'', '### Sources']
        for source in r['sources']:lines.append(f"- [{source['title']}]({source['url']}) — {source['publisher']}; {source['kind']}, {source['access']}, scope {source['scope']}. {source['evidence']}")
        lines+=['','### Limitations']+['- '+text for text in r['limitations']]
        lines+=['','Queries:']+['- `'+q+'`' for q in r['queries_planned']]
        if r['failures']:lines+=['','Request failures: `'+json.dumps(r['failures'])+'`']
    lines+=['','## Execution and access','',f"Python pipeline elapsed: {report['elapsed_seconds']} seconds. Recorded-evidence replay time excludes the preceding web research and source review. Live API results are leads until subject/promotion evidence is reviewed; empty bounded searches do not establish absence online.",
            '', 'No LLM orchestration, scraping around restrictions, model training, frontend, or Phase 6 work is implemented. Original destinations and all prior records are preserved.']
    Path(path).write_text('\n'.join(lines)+'\n')
