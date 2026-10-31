"""Model-selected discovery tools over approved data and traceable Tavily evidence."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import uuid
from atia.models import utc_now
from atia.moderation.display import can_display
from atia.moderation.policy import allowed,clean_evidence
from atia.destinations.storage import DestinationStore
from atia.destinations.evidence import EvidenceIndex,exists
from atia.research.identity import IdentityStore,DOMAINS,verify_sources,normalized
from atia.research.tavily import TavilySearch
from .tools import AgentTools,function,context
from .contracts import STRING,STRINGS
from .storage import digest,encode

TOOLS=[
    function('list_candidates','Retrieve eligible geographic areas and associated verified entities. Counts describe evidence, NEVER hiddenness. Offset paginates.',{'offset':{'type':'integer','minimum':0}}),
    function('inspect_candidate','Choose any eligible area; inspect approved photos, identity/coverage evidence, counterevidence and memory in one economical dossier.',{'cluster_id':STRING}),
    function('research_candidate','Use one cached-or-live Tavily search for identity or promotional coverage. Optional proposed name/type is confirmed ONLY if actual authoritative title/content supports it; no photo mapping is inferred.',
       {'cluster_id':STRING,'query':STRING,'purpose':{'type':'string','enum':['identity','promotional_coverage']},
        'proposed_name':{'type':['string','null']},'entity_type':{'type':['string','null'],'enum':['destination','attraction',None]}}),
    function('get_memory','Read previous decisions/campaigns for any eligible candidate; interpretations are not new evidence.',{'cluster_id':STRING}),
    function('save_observation','Save a sourced interpretation, not an independently verified fact.',{'cluster_id':STRING,'content':STRING,'evidence_refs':STRINGS}),
]


def eligible(db,r):
    if not allowed(db,r['source'],r['photo_id']):return False
    if exists(db,'visual_review_labels'):
        label=db.execute('SELECT label FROM visual_review_labels WHERE source=? AND photo_id=? ORDER BY reviewed_at DESC LIMIT 1',(r['source'],r['photo_id'])).fetchone()
        if label and label['label'] in ('uncertain','irrelevant'):return False
    return True


def candidate_pool(store):
    db=store.connection
    try:groups=DestinationStore(store).inspect()['destinations']
    except ValueError:return []
    records=[dict(r) for r in db.execute('SELECT * FROM photos ORDER BY source,photo_id') if eligible(db,r)]
    index=EvidenceIndex(db,records);by_id={}
    for r in records:by_id.setdefault(r['photo_id'],[]).append(r)
    identities=IdentityStore(store);latest={}
    for assessment in identities.inspect():
        if clean_evidence(db,assessment):latest.setdefault(assessment['cluster_id'],assessment)
    pool=[]
    for g in groups:
        members=[r for i in g['photo_ids'] for r in by_id.get(i,[])]
        if not members:continue
        e=index.aggregate(members);assessment=latest.get(g['destination_id']);entities=(assessment or {}).get('entities',[])
        pool.append({'cluster_id':g['destination_id'],'original_name':g['name'],
            'candidate_names':[{'entity_id':v['entity_id'],'name':v['verified_name'],'type':v['entity_type']} for v in entities],
            'association':assessment['association_status'] if assessment else g['name_status'],
            'approved_photo_count':e['photo_count'],'tourism_basis':e['sources'],
            'visual_environments':e['visual']['possible_environment_counts'],
            'place_context':[v['name'] for v in g.get('reported_localities',[]) if v.get('name')],
            'coordinates':{'latitude':sum(r['latitude'] for r in members)/len(members),
                           'longitude':sum(r['longitude'] for r in members)/len(members)},'photo_ids':[r['photo_id'] for r in members],
            'selection_note':'Source approval/curation and geographic grouping; not evidence of being overlooked.'})
    # Only evidence-completeness orders the catalogue; no popularity/hiddenness rank.
    return sorted(pool,key=lambda p:(not bool(p['candidate_names']),not bool(p['visual_environments']),p['cluster_id']))


def discovery_fingerprint(store,data=None):
    db=store.connection;tables={}
    # Full relevant records, not just counts; include moderation changes even when
    # a revoked asset is no longer returned by the candidate catalogue.
    for table in ('photos','photo_moderation','photo_removal_audit','visual_review_labels','tourism_relevance',
                  'visual_dimension_analyses','comment_sentiments','comment_observations','comment_fetches',
                  'destination_runs','authoritative_entity_verifications','live_location_research','tavily_search_observations'):
        if exists(db,table):tables[table]=[dict(r) for r in db.execute('SELECT * FROM '+table+' ORDER BY rowid')]
    return digest(tables)


class DiscoveryTools:
    def __init__(self,store,memory,run_id,cluster_id,data,limits,provider=None):
        self.store=store;self.memory=memory;self.run_id=run_id;self.cluster_id=None;self.data=data;self.pool=data['candidates']
        self.limits=limits;self.provider=provider;self.searches=0;self.refs={};self.considered=[];self.inspected={};self.assets={}
        self.source_observations=[];self.asset_paths={};self.target_entity_id=data.get('target_entity_id')

    reference=AgentTools.reference
    validate_refs=AgentTools.validate_refs

    def select(self,cluster_id):
        if cluster_id not in {p['cluster_id'] for p in self.pool}:raise ValueError('Unknown or ineligible geographic cluster ID. Copy the exact cluster_id from list_candidates; entity_id is different.')
        if cluster_id not in self.inspected:
            d=context(self.store,cluster_id);db=self.memory.db
            records=[dict(r) for r in db.execute('SELECT * FROM photos') if r['photo_id'] in d['cluster']['photo_ids'] and eligible(db,r)]
            if not records:raise ValueError('Candidate no longer has eligible approved photos')
            d['cluster']['photo_ids']=sorted({r['photo_id'] for r in records});d['current_evidence']=EvidenceIndex(db,records).aggregate(records)
            d['cluster']['centroid']={'latitude':sum(r['latitude'] for r in records)/len(records),'longitude':sum(r['longitude'] for r in records)/len(records)}
            valid={(r['source'],r['photo_id']) for r in records};d['photos']=[p for p in d['photos'] if (p['source'],p['photo_id']) in valid]
            self.inspected[cluster_id]=d
        self.cluster_id=cluster_id;self.data=self.inspected[cluster_id]
        return self.data

    def assets_for(self,d):
        db=self.memory.db;result=[]
        for p in d['photos']:
            if not can_display(db,p['source'],p['photo_id']):continue
            row=None
            tables=('moderation_asset_cache',) if p['source']=='flickr_live' else ('photo_image_cache','tourism_relevance','visual_dimension_analyses','visual_analyses')
            for table in tables:
                if not exists(db,table):continue
                query=f'SELECT image_sha256,image_path FROM {table} WHERE photo_id=?';args=[p['photo_id']]
                if table!='moderation_asset_cache':query+=' AND source=?';args.append(p['source'])
                row=db.execute(query+' LIMIT 1',args).fetchone()
                if row:break
            if not row:continue
            path=Path(row['image_path']).resolve()
            filename=db.execute('PRAGMA database_list').fetchone()[2]
            root=Path(filename).resolve().parent if filename else Path('data').resolve()
            if not path.is_file() or not path.is_relative_to(root):continue
            if hashlib.sha256(path.read_bytes()).hexdigest()!=row['image_sha256']:continue
            reference='asset:'+p['source']+':'+p['photo_id']+':'+row['image_sha256']
            item={'source':p['source'],'photo_id':p['photo_id'],'image_sha256':row['image_sha256'],
                  'approval_basis':'historical_user_curation' if p['source']=='afaq_historical' else 'explicit_user_approval',
                  'identity_mappings':[]}
            naming=d['cluster'].get('name_reference')
            for entity in (d['assessment'] or {}).get('entities',[]):
                if naming and d['cluster'].get('name_status')=='reviewer_verified_reference' and normalized(naming['name'])==normalized(entity['verified_name']):
                    mapping='mapping:'+p['source']+':'+p['photo_id']+':'+entity['entity_id']
                    evidence={'photo_id':p['photo_id'],'source':p['source'],'entity_id':entity['entity_id'],
                              'reviewer':naming['reviewer'],'source_url':naming['evidence_url'],'basis':'explicit existing reviewer-verified photo/place annotation'}
                    self.reference(mapping,evidence);item['identity_mappings'].append({'entity_id':entity['entity_id'],'reference':mapping})
            self.reference(reference,item);self.assets[reference]=item;self.asset_paths[reference]=path;result.append({'evidence_ref':reference,**item})
        return result

    def execute(self,name,args):
        if name=='list_candidates':
            page=self.pool[args['offset']:args['offset']+8]
            self.considered.extend(p['cluster_id'] for p in page if p['cluster_id'] not in self.considered)
            compact=[{k:v for k,v in p.items() if k not in ('photo_ids','selection_note')} for p in page]
            ref=self.reference('catalogue:'+str(args['offset']),compact)
            return {'evidence_ref':ref,'total_eligible_areas':len(self.pool),'candidates':compact,
                    'next_offset':args['offset']+8 if args['offset']+8<len(self.pool) else None,
                    'note':'Counts measure evidence availability, never hiddenness/popularity. Candidate names do not verify photo-to-attraction mapping.'}
        cluster_id=args['cluster_id'];d=self.select(cluster_id)
        child=AgentTools(self.store,self.memory,self.run_id,cluster_id,d,self.limits,self.provider);child.refs=self.refs
        if name=='inspect_candidate':
            before=set(self.refs)
            research=child.research()
            # Preserve publisher diversity within a small context budget.
            chosen=[];publishers=set()
            for source in research.get('sources',[]):
                if len(chosen)>=4:break
                if source['publisher'] not in publishers:
                    chosen.append(source);publishers.add(source['publisher'])
            for source in research.get('sources',[]):
                if len(chosen)>=4:break
                if source not in chosen:chosen.append(source)
            returned={s['url'] for s in chosen}
            for ref in list(self.refs):
                if ref.startswith('https://') and ref not in before and ref not in returned:del self.refs[ref]
            if research.get('sources'):
                research['additional_sources_not_shown']=len(research['sources'])-len(chosen)
                research['sources']=chosen
            e=d['current_evidence'];g=d['cluster']
            ref=self.reference('cluster:'+cluster_id,{'cluster_id':cluster_id,'photo_ids':g['photo_ids'],'name_status':g['name_status'],'name_reference':g['name_reference'],'centroid':g['centroid']})
            evidence={'photo_count':e['photo_count'],'sources':e['sources'],'visual':{
                'environments':e['visual']['possible_environment_counts'],'elements':e['visual']['possible_element_counts'],
                'uncertain_ranks':e['visual']['uncertain_environment_top_ranks']},'engagement':e['engagement'],
                'sentiment':{k:e['sentiment'][k] for k in ('distribution','classified_comments','languages_analyzed')},
                'note':'No engagement or sentiment value establishes demand or hidden-gem status.'}
            eref=self.reference('evidence:'+cluster_id,evidence)
            memory=self.memory.memory(cluster_id)
            photo_summary=[{k:p[k] for k in ('source','photo_id','title','photo_url','uploaded_at','captured_at','relevance')} for p in d['photos'][:3]]
            return {'evidence_ref':ref,'cluster_id':cluster_id,'approved_photos':photo_summary,
                    'evidence':{'evidence_ref':eref,**evidence},'research':research,'assets':self.assets_for(d),
                    'memory':memory,'limitations':['Photo-source approval is separate from verified attraction association.',
                        'No explicit mapping reference means no location-specific campaign photo can be used.']}
        if name=='get_memory':return child.execute('get_memory',{})
        if name=='save_observation':
            self.validate_refs(args['evidence_refs'])
            if not 1<=len(args['content'])<=2000:raise ValueError('Observation must contain 1–2000 characters')
            if not clean_evidence(self.memory.db,args):raise ValueError('Blocked image evidence')
            identifier='discovery-note-'+uuid.uuid4().hex
            with self.memory.db:self.memory.db.execute('INSERT INTO agent_discovery_observations VALUES(?,?,?,?,?,?)',
                (identifier,self.run_id,cluster_id,utc_now(),args['content'],encode(args['evidence_refs'])))
            return {'observation_id':identifier,'kind':'sourced_interpretation_not_independent_fact'}
        if name=='research_candidate':
            if self.searches>=self.limits.max_searches:raise ValueError('Additional Tavily search limit reached')
            query=args['query'];lat=d['cluster']['centroid']['latitude'];lon=d['cluster']['centroid']['longitude']
            names=[e['verified_name'] for e in (d['assessment'] or {}).get('entities',[])]
            places=[str(v.get('name','')) for v in d['cluster'].get('reported_localities',[]) if v.get('name')]
            grounded=any(n.casefold() in query.casefold() for n in names+places)
            if not grounded and not (f'{lat:.3f}' in query and f'{lon:.3f}' in query):
                raise ValueError('Query must reference stored entity/locality context or the displayed three-decimal coordinates')
            self.searches+=1
            if self.provider is None:self.provider=TavilySearch(self.store,os.getenv('TAVILY_API_KEY'))
            sources=self.provider.search(query,domains=DOMAINS)
            sources=[s for s in sources if clean_evidence(self.memory.db,s)]
            returned=[]
            for s in sources:
                item={k:s.get(k) for k in ('title','url','publisher','access','observed_at')};item['content_excerpt']=s['evidence'][:900]
                self.reference(s['url'],item);returned.append(item)
            verification=None
            if args['proposed_name'] and args['entity_type']:
                option={'name':args['proposed_name'],'aliases':[args['proposed_name']],'entity_type':args['entity_type']}
                official=verify_sources(option,sources)
                if official:
                    known=next((e for e in (d['assessment'] or {}).get('entities',[]) if normalized(e['verified_name'])==normalized(option['name'])),None)
                    verification=known or IdentityStore(self.store).save_verification(option,official)
                    if not known:
                        d['assessment']=d['assessment'] or {'association_status':'unresolved_photo_mapping','assessment_id':'discovery:'+self.run_id,
                            'research_status':'insufficient_evidence','limitations':['Source confirms named entity existence, not photograph association.'],'source_origin':'live_tavily_api','assessed_at':utc_now(),'sources':sources,'entities':[]}
                        d['assessment']['entities'].append(verification)
            provenance=self.provider.observations[-1];self.source_observations.append(provenance)
            return {'cluster_id':cluster_id,'sources':returned,'provenance':provenance,'verified_entity':verification,
                    'photo_identity_mapping_confirmed':False,'note':'Search/source evidence, not automatic proof of hiddenness, promotional gaps or photo identity.'}
        raise ValueError('Unknown discovery tool')
