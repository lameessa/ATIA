"""Read-only projections over ATIA's stored evidence; never calls an AI/search API."""
from atia.moderation.display import can_display
from collections import Counter
import json
import os
import re
from urllib.parse import urlparse
from types import SimpleNamespace
from atia.destinations.storage import DestinationStore
from atia.destinations.evidence import EvidenceIndex,exists
from atia.research.identity import IdentityStore
from atia.agents.storage import AgentStore


def parse(value,default=None):
    try:return json.loads(value) if value else default
    except (ValueError,TypeError):return default


def public(value):
    """Defense in depth: raw metadata/private reasoning/credentials stay server-side."""
    if isinstance(value,dict):
        return {k:public(v) for k,v in value.items() if k.lower() not in {
            'api_key','authorization','raw','reasoning','chain_of_thought','unvalidated_model_decision','image_url','image_path','original_url'}}
    if isinstance(value,list):return [public(v) for v in value]
    if isinstance(value,str):
        for name in ('OPENAI_API_KEY','TAVILY_API_KEY','FLICKR_API_KEY','BRAVE_SEARCH_API_KEY'):
            key=os.getenv(name,'').strip()
            if key:value=value.replace(key,'[REDACTED]')
    return value


class DashboardData:
    def __init__(self,db):self.db=db;self.store=SimpleNamespace(connection=db);self._groups=None

    def groups(self):
        # Request-local only: avoid rebuilding every evidence aggregate for each
        # section of a single read projection. Never shared across connections.
        if self._groups is None:self._groups=self._read_groups()
        return self._groups

    def _read_groups(self):
        if not exists(self.db,'destination_runs'):return []
        try:
            from atia.moderation.policy import visible_group
            return [v for g in DestinationStore(self.store,initialize=False).inspect()['destinations'] if (v:=visible_group(self.db,g))]
        except ValueError:return []

    def catalogue(self):
        groups=self.groups()
        if not groups:
            return {'geographic_clusters':[],'verified_entities':[],'unresolved_locations':[]}
        if not exists(self.db,'verified_location_entities'):
            return {'geographic_clusters':[{'cluster_id':g['destination_id'],'association_status':'not_researched','candidate_entity_ids':[]} for g in groups],
                    'verified_entities':[],'unresolved_locations':[]}
        result=IdentityStore(self.store,initialize=False).catalogue();ids={g['destination_id'] for g in groups}
        result['geographic_clusters']=[g for g in result['geographic_clusters'] if g['cluster_id'] in ids]
        result['unresolved_locations']=[g for g in result['unresolved_locations'] if g['cluster_id'] in ids]
        for entity in result['verified_entities']:
            entity['direct_cluster_ids']=[i for i in entity['direct_cluster_ids'] if i in ids]
            entity['provisionally_associated_via_children']=[i for i in entity['provisionally_associated_via_children'] if i in ids]
        return result

    def research(self,include_queries=True):
        live=[];historical=[];queries=[]
        if exists(self.db,'live_location_research'):
            seen=set()
            for row in self.db.execute('SELECT result FROM live_location_research ORDER BY assessed_at DESC'):
                r=parse(row['result'],{})
                if not r or r.get('cluster_id') in seen:continue
                seen.add(r['cluster_id']);live.append({**r,'provenance_label':'Live Tavily API (stored observation)'})
        if exists(self.db,'promotional_research'):
            for row in self.db.execute('SELECT result FROM promotional_research ORDER BY research_timestamp DESC'):
                r=parse(row['result'],{})
                historical.append({**r,'provenance_label':'Historical recorded research; not a fresh Tavily request'})
        if include_queries and exists(self.db,'tavily_search_observations'):
            for row in self.db.execute('SELECT observation_id,query,requested_at,request_id,result FROM tavily_search_observations ORDER BY requested_at DESC LIMIT 50'):
                result=parse(row['result'],{})
                queries.append({'observation_id':row['observation_id'],'query':row['query'],'requested_at':row['requested_at'],
                    'request_id':row['request_id'],'provider':result.get('provider','tavily_live_api_v1'),
                    'sources':result.get('sources',[]),'research_status':'retrieved_sources',
                    'provenance_label':'Stored Tavily API search response; not an identity or coverage assessment',
                    'limitations':['Retrieved source excerpts alone do not authenticate a geographic cluster or establish a promotional gap.']})
        from atia.moderation.policy import clean_evidence
        return {'live':[r for r in live if clean_evidence(self.db,r)],
                'historical':[r for r in historical if clean_evidence(self.db,r)],
                'queries':[r for r in queries if clean_evidence(self.db,r)]}

    def proposals(self):
        if not exists(self.db,'agent_proposals'):return []
        result=[]
        for row in self.db.execute('SELECT * FROM agent_proposals ORDER BY created_at DESC'):
            item=dict(row);item['proposal']=parse(item.pop('proposal_json'),{})
            from atia.moderation.policy import clean_evidence
            if not clean_evidence(self.db,item):continue
            review=None
            if exists(self.db,'dashboard_proposal_reviews'):
                r=self.db.execute('SELECT * FROM dashboard_proposal_reviews WHERE proposal_id=?',(item['proposal_id'],)).fetchone()
                if r:review=dict(r)
            item['review']=review;item['effective_status']=review['decision'] if review else item['status'];result.append(item)
        return result

    def runs(self,run_id=None):
        if not exists(self.db,'agent_runs'):return []
        result=AgentStore(self.store,initialize=False).inspect(run_id)
        from atia.moderation.policy import clean_evidence
        result=[r for r in result if clean_evidence(self.db,r)]
        for r in result:
            for tool in r['tools']:
                tool['arguments']=parse(tool.pop('arguments_json'),{})
                tool['result']=parse(tool.pop('result_json'),{})
        return result

    def areas(self):
        catalogue=self.catalogue();by_id={g['cluster_id']:g for g in catalogue['geographic_clusters']}
        entities={e['entity_id']:e for e in catalogue['verified_entities']}
        result=[]
        for g in self.groups():
            status=by_id.get(g['destination_id'],{});e=g['evidence']
            result.append({'cluster_id':g['destination_id'],'name':g['name'],'centroid':g['centroid'],
                'regions':g['sampling_macro_regions'],'localities':g['reported_localities'],
                'photo_count':e['photo_count'],'relevance_coverage':e['relevance_coverage'],
                'association_status':status.get('association_status','not_researched'),
                'entities':[entities[i] for i in status.get('candidate_entity_ids',[]) if i in entities]})
        return result

    def cluster(self,cluster_id):
        group=next((g for g in self.groups() if g['destination_id']==cluster_id),None)
        if not group:return None
        records=[dict(r) for r in self.db.execute('''SELECT p.* FROM photos p JOIN destination_photo_assignments a
          ON a.source=p.source AND a.photo_id=p.photo_id WHERE a.run_id=(SELECT run_id FROM destination_runs ORDER BY created_at DESC LIMIT 1)
          AND a.destination_id=? ORDER BY p.source,p.photo_id''',(cluster_id,))]
        index=EvidenceIndex(self.db,records);photos=[]
        for r in records:
            item={k:r[k] for k in ('source','photo_id','title','latitude','longitude','uploaded_at','captured_at','views','photo_url','region','license_name','license_url')}
            screen=index.screen.get((r['source'],r['photo_id']))
            item['relevance']=screen['decision'] if screen else 'not_evaluated'
            item['visual']=parse(screen['detail_result']) if screen else None
            item['visual_dimensions']=[{'dimension':dimension,'scores':parse(v['scores']),
                'interpretation':parse(v['interpretation']),'model':v['model_name'],'prompt_version':v['prompt_version']}
                for (source,photo_id,dimension),v in index.dimensions.items() if (source,photo_id)==(r['source'],r['photo_id'])]
            # A page link is a citation. Image URLs exist only for photos that pass the display gate.
            item['preview_url']=f"/api/images/{r['source']}/{r['photo_id']}" if can_display(self.db,r['source'],r['photo_id']) else None
            item['flickr_url']=f"https://www.flickr.com/photo.gne?id={r['photo_id']}"
            photos.append(item)
        return {'cluster':group,'photos':photos,'evidence':index.aggregate(records),
                'research':next((r for r in self.research(False)['live'] if r.get('cluster_id')==cluster_id),None)}

    def overview(self):
        count=lambda t:self.db.execute('SELECT count(*) FROM '+t).fetchone()[0] if exists(self.db,t) else 0
        groups=self.groups();catalogue=self.catalogue();runs=self.runs();proposals=self.proposals()
        # Each photo is one source observation; region/source buckets sum to the total.
        regions=dict(self.db.execute("SELECT coalesce(region,'Unspecified'),count(*) FROM photos GROUP BY region")) if exists(self.db,'photos') else {}
        sources=dict(self.db.execute('SELECT source,count(*) FROM photos GROUP BY source')) if exists(self.db,'photos') else {}
        screen={}
        if exists(self.db,'tourism_relevance'):
            latest={}
            for row in self.db.execute('SELECT t.source,t.photo_id,t.decision FROM tourism_relevance t JOIN photos p ON p.source=t.source AND p.photo_id=t.photo_id ORDER BY t.analyzed_at DESC'):
                latest.setdefault((row['source'],row['photo_id']),row['decision'])
            screen=dict(Counter(latest.values()))
        screen['not_evaluated']=max(0,count('photos')-sum(screen.values()))
        last_run=self.db.execute('SELECT report FROM destination_runs ORDER BY created_at DESC LIMIT 1').fetchone() if exists(self.db,'destination_runs') else None
        report=parse(last_run['report'],{}) if last_run else {}
        all_decisions=Counter((r.get('result') or {}).get('decision',{}).get('decision') for r in runs if (r.get('result') or {}).get('decision',{}).get('decision'))
        assigned=sum(g['evidence']['source_observation_count'] for g in groups)
        return {'photo_count':count('photos'),'photo_sources':sources,'regions':regions,'geographic_clusters':len(groups),
            'verified_entities':dict(Counter(e['entity_type'] for e in catalogue['verified_entities'])),
            'assigned_photos':assigned,'unassigned_photos':max(0,count('photos')-assigned),
            'association_states':dict(Counter(g['association_status'] for g in catalogue['geographic_clusters'])),
            'relevance':screen,'agent_run_count':len(runs),'decisions':dict(all_decisions),
            'pending_proposals':sum(p['effective_status']=='PENDING_APPROVAL' for p in proposals),
            'proposal_count':len(proposals),'recent_runs':runs[:3],
            'local_agent_ledger_usd':self.db.execute('SELECT coalesce(sum(charged_usd),0) FROM agent_requests').fetchone()[0] if exists(self.db,'agent_requests') else 0,
            'note':'Photo counts are source observations. Clusters are not verified attractions. Engagement and sentiment do not establish tourism demand.'}
