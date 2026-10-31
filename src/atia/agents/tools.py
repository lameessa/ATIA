"""Small wrappers over existing destination, visual, sentiment and Tavily services."""
import json
import os
import uuid
from atia.models import utc_now
from atia.destinations.storage import DestinationStore
from atia.destinations.evidence import EvidenceIndex,exists
from atia.research.identity import IdentityStore,DOMAINS
from atia.research.tavily import TavilySearch
from .contracts import obj,STRING,STRINGS
from .storage import encode,digest


def function(name,description,properties):
    return {'type':'function','name':name,'description':description,'parameters':obj(properties),'strict':True}


TOOLS=[
    function('get_candidates','Read the selected geographic cluster and associated verified entities; associations are provisional.',{}),
    function('inspect_evidence','Read stored evidence for this cluster. dossier bundles all views efficiently; photos includes visual summaries and Flickr URLs.',
             {'view':{'type':'string','enum':['dossier','photos','engagement_sentiment','research']}}),
    function('get_memory','Retrieve previous decisions, draft proposals and sourced LLM observations; these are not independent facts.',{}),
    function('research_live','One additional cached-or-live Tavily search, only if existing evidence is insufficient. Does not establish cluster identity.',{'query':STRING}),
    function('save_observation','Persist a sourced interpretation, never promote it to an independently verified fact.',{'content':STRING,'evidence_refs':STRINGS}),
]


def context(store,cluster_id):
    group=DestinationStore(store).inspect(destination_id=cluster_id)
    identities=IdentityStore(store).inspect(cluster_id)
    assessment=identities[0] if identities else None
    # Include current evidence rather than relying only on an old cluster snapshot.
    run=DestinationStore(store).inspect()['run_id']
    records=[dict(r) for r in store.connection.execute('''SELECT p.* FROM photos p JOIN destination_photo_assignments a
        ON a.source=p.source AND a.photo_id=p.photo_id WHERE a.run_id=? AND a.destination_id=? ORDER BY p.source,p.photo_id''',(run,cluster_id))]
    from atia.moderation.policy import allowed,visible_group,clean_evidence
    records=[r for r in records if allowed(store.connection,r['source'],r['photo_id'])]
    if not records:raise ValueError('This area has no approved presentation photographs')
    group=visible_group(store.connection,group)
    if assessment and not clean_evidence(store.connection,assessment):assessment=None
    index=EvidenceIndex(store.connection,records)
    evidence=index.aggregate(records)
    photos=[]
    for r in records[:10]:
        photo={k:r[k] for k in ('photo_id','source','title','photo_url','latitude','longitude','uploaded_at','captured_at','region')}
        screen=index.screen.get((r['source'],r['photo_id']))
        photo['relevance']=screen['decision'] if screen else 'not_evaluated'
        photo['visual_detail']=json.loads(screen['detail_result']) if screen and screen['detail_result'] else None
        photos.append(photo)
    return {'cluster':group,'current_evidence':evidence,'photos':photos,'assessment':assessment}


class AgentTools:
    def __init__(self,store,memory,run_id,cluster_id,data,limits,provider=None):
        self.store=store;self.memory=memory;self.run_id=run_id;self.cluster_id=cluster_id
        self.data=data;self.limits=limits;self.provider=provider;self.searches=0;self.refs={}

    def reference(self,ref,payload):
        self.refs[ref]=payload
        return ref

    def validate_refs(self,refs):
        if not refs or any(not isinstance(r,str) or r not in self.refs for r in refs):
            raise ValueError('Evidence references must have been returned by a tool in this run')

    def research(self):
        assessment=self.data['assessment']
        if not assessment:return {'status':'not_researched','evidence_refs':[]}
        ref=self.reference('research:'+assessment['assessment_id'],{'assessment_id':assessment['assessment_id'],
            'association_status':assessment['association_status'],'status':assessment['research_status'],
            'limitations':assessment['limitations'],
            'entities':[{k:e.get(k) for k in ('verified_name','entity_type','parent_name','verification_status')} for e in assessment['entities']]})
        sources=[]
        for s in assessment['sources'][:12]:
            value={k:s.get(k) for k in ('title','url','publisher','access','observed_at')}
            value['content_excerpt']=s['evidence'][:500]
            self.reference(s['url'],value);sources.append(value)
        entities=[{k:e.get(k) for k in ('entity_id','verified_name','entity_type','parent_name','parent_status','coverage_status','verification_status')}
                  for e in assessment['entities']]
        return {'evidence_ref':ref,'source_origin':assessment['source_origin'],'researched_at':assessment['assessed_at'],
                'association_status':assessment['association_status'],'confirmed_cluster_name':None,'entities':entities,
                'coverage_status':assessment['research_status'],'sources':sources,'limitations':assessment['limitations']}

    def execute(self,name,args):
        if name=='get_candidates':
            g=self.data['cluster']
            payload={k:g[k] for k in ('destination_id','name','centroid','photo_ids','warnings')}
            ref=self.reference('cluster:'+self.cluster_id,payload)
            a=self.data['assessment']
            identity=({'status':'not_researched'} if a is None else {
                'association_status':a['association_status'],'confirmed_cluster_name':None,
                'entities':[{k:e.get(k) for k in ('verified_name','entity_type','parent_name','verification_status')} for e in a['entities']],
                'coverage_status':a['research_status'],'note':'Use inspect_evidence/research for source content and citations.'})
            return {'evidence_ref':ref,'geographic_cluster':payload,'identity':identity}
        if name=='inspect_evidence':
            view=args['view'];g=self.data['cluster'];e=self.data['current_evidence'];out={}
            if view in ('dossier','photos'):
                ref=self.reference('photos:'+self.cluster_id,self.data['photos'])
                out['photographs']={'evidence_ref':ref,'items':self.data['photos'],'preview_limit':10,
                    'total_cluster_photos':e['photo_count'],'note':'Geographic membership does not authenticate attraction identity.'}
            if view in ('dossier','engagement_sentiment'):
                ref=self.reference('evidence:'+self.cluster_id,e)
                out['evidence']={'evidence_ref':ref,**e}
            if view in ('dossier','research'):out['research']=self.research()
            return out
        if name=='get_memory':
            result=self.memory.memory(self.cluster_id)
            ref=self.reference('memory:'+self.cluster_id,result)
            return {'evidence_ref':ref,**result,'note':'Previous decisions/observations are interpretations; original evidence still required.'}
        if name=='research_live':
            if self.searches>=self.limits.max_searches:raise ValueError('Additional Tavily search limit reached')
            query=args['query']
            names=[e['verified_name'] for e in (self.data['assessment'] or {}).get('entities',[])]
            if not names or not any(n.casefold() in query.casefold() for n in names):
                raise ValueError('Search must name an associated verified entity; no arbitrary destinations')
            self.searches+=1
            if self.provider is None:self.provider=TavilySearch(self.store,os.getenv('TAVILY_API_KEY'))
            sources=self.provider.search(query,domains=DOMAINS)
            out=[]
            for s in sources:
                from atia.moderation.policy import clean_evidence
                if not clean_evidence(self.memory.db,s):continue
                value={k:s.get(k) for k in ('title','url','publisher','access','observed_at')}
                value['content_excerpt']=s['evidence'][:700];self.reference(s['url'],value);out.append(value)
            observation=self.provider.observations[-1]
            return {'sources':out,'provenance':observation,'identity_verified':False,
                    'note':'Retrieved excerpts, not authority confirmation of Flickr cluster/site association.'}
        if name=='save_observation':
            self.validate_refs(args['evidence_refs'])
            if not args['content'].strip() or len(args['content'])>2000:raise ValueError('Observation must contain 1–2000 characters')
            identifier='observation-'+uuid.uuid4().hex
            with self.memory.db:self.memory.db.execute('INSERT INTO agent_observations VALUES(?,?,?,?,?,?)',
                (identifier,self.run_id,self.cluster_id,utc_now(),args['content'],encode(args['evidence_refs'])))
            return {'observation_id':identifier,'status':'saved_sourced_interpretation','evidence_refs':args['evidence_refs']}
        raise ValueError('Unknown agent tool')


def fingerprint(store,data):
    # Full current AI/comment evidence participates, even if summary counts match.
    db=store.connection;ids=set(data['cluster']['photo_ids']);analyses={}
    for table in ('visual_analyses','visual_dimension_analyses','tourism_relevance','comment_sentiments','comment_observations','comment_fetches'):
        if exists(db,table):
            analyses[table]=[dict(r) for r in db.execute('SELECT * FROM '+table) if r['photo_id'] in ids]
    names=[e['verified_name'].casefold() for e in (data['assessment'] or {}).get('entities',[])]
    research=[]
    if exists(db,'tavily_search_observations'):
        research=[dict(r) for r in db.execute('SELECT * FROM tavily_search_observations ORDER BY requested_at,observation_id')
                  if any(n in r['query'].casefold() for n in names)]
    return digest({'data':data,'analyses':analyses,'additional_research':research})
