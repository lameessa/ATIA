"""Small campaign-first projections over existing stores. No paid operations."""
from atia.destinations.evidence import exists
from atia.moderation.display import reviewed_images
from atia.moderation.policy import clean_evidence
from atia.agents.discovery_storage import DiscoveryStore
from .data import DashboardData,parse
from .media import FlickrMedia
from atia.opportunities.generate import build_dossier,review_validation
from atia.opportunities.store import OpportunityStore
from .campaign_workflow import overlay


class WorkspaceData:
    def __init__(self,db):
        self.db=db;self.data=DashboardData(db);self.media=FlickrMedia(db)

    def campaigns(self):
        result=[]
        if exists(self.db,'agent_campaigns'):
            for item in DiscoveryStore(self.data.store,initialize=False).campaigns():
                review=None
                if exists(self.db,'dashboard_campaign_reviews'):
                    row=self.db.execute('SELECT * FROM dashboard_campaign_reviews WHERE campaign_id=?',(item['campaign_id'],)).fetchone()
                    if row:review=dict(row)
                assets=[]
                for a in item['campaign'].get('approved_photo_assets',[]):
                    asset=self.media.asset(a['source'],a['photo_id'])
                    # Campaign material must have a reviewed entity mapping AND usable rights.
                    mapping=item['evidence'].get('references',{}).get(a['identity_mapping_ref'],{})
                    if asset and asset['rights_status']=='reusable_with_attribution' and mapping.get('entity_id')==item['entity_id']:
                        assets.append({**asset,'association_status':'reviewed_entity_mapping','entity_id':item['entity_id'],'usage_scope':'campaign_draft'})
                current=overlay(self.db,item['campaign_id'],item['campaign'],item['status'],review)
                result.append({**current,'id':item['campaign_id'],'kind':'campaign','cluster_id':item['cluster_id'],
                    'created_at':item['created_at'],'media':assets,
                    'sources':self.sources(item['evidence'].get('references',{})),
                    'opportunity':item['evidence'].get('hidden_gem',{}),
                    'media_validation_required':len(assets)!=len(item['campaign'].get('approved_photo_assets',[]))})
        result.extend(self.opportunity_campaigns())
        for p in self.data.proposals():
            result.append({'id':p['proposal_id'],'kind':'legacy_proposal','cluster_id':p['cluster_id'],
                'created_at':p['created_at'],'status':p['effective_status'],'content':p['proposal'],
                'media':[],'review':p['review'],'sources':[],'media_validation_required':False})
        return sorted(result,key=lambda p:p['created_at'],reverse=True)

    def opportunity_assets(self,opportunity):
        """Only images whose licence allows campaign use. Named places show them as Flickr-labelled, not reviewed."""
        ids=[('afaq_historical',i) for i in opportunity['photo_ids']]
        ids+=[(r['source'],r['photo_id']) for r in OpportunityStore(self.db).accepted_images(opportunity['opportunity_id'])]
        assets=[]
        for source,photo_id in ids:
            asset=self.media.asset(source,photo_id)
            if asset and asset['rights_status']=='reusable_with_attribution':
                assets.append({**asset,'usage_scope':'campaign_draft','association_status':'flickr_metadata_unreviewed'})
        return assets

    def opportunity_campaigns(self):
        store=OpportunityStore(self.db);result=[]
        for item in store.campaigns():
            opportunity=store.opportunity(item['opportunity_id'])
            if not opportunity or not clean_evidence(self.db,item['evidence']):continue
            current=overlay(self.db,item['campaign_id'],item['campaign'],item['status'],None)
            dossier=item['evidence']['dossier']
            sources=[{'title':p['title'] or 'Flickr photograph','url':p['photo_url'],'publisher':'Flickr · '+(p['photographer'] or 'photographer not recorded')} for p in dossier['photos'] if p['photo_url']]
            sources+=[{'title':r['title'],'url':r['url'],'publisher':r['publisher']} for r in dossier['stored_research']]
            result.append({**current,'validation':review_validation(current['content'],item['evidence']),'evidence_review':self.evidence_review(current['content'],item['evidence']),'id':item['campaign_id'],'kind':'campaign','opportunity_id':item['opportunity_id'],'cluster_id':item['opportunity_id'],'created_at':item['created_at'],
                'media':self.opportunity_assets(opportunity),'sources':sources,'media_validation_required':False,
                'opportunity':{'hypothesis':item['evidence']['recommendation'],'limitations':item['evidence']['uncertainties']}})
        return result

    @staticmethod
    def evidence_review(content,evidence):
        """What a reviewer needs before approving: each claim beside the records it cites."""
        dossier=evidence['dossier'];records={}
        for p in dossier['photos']:
            records[p['evidence_ref']]={'title':p['title'] or 'Flickr photograph','url':p['photo_url'],'publisher':'Flickr · '+(p['photographer'] or 'photographer not recorded')}
        for r in dossier['stored_research']:
            records[r['evidence_ref']]={'title':r['title'],'url':r['url'],'publisher':r['publisher']}
        def resolved(claims):
            return [{'claim':c['claim'],'sources':[records[r] for r in c['evidence_refs'] if r in records]} for c in claims]
        edited=content.get('review_evidence')
        current=edited or evidence
        return {'recommendation':current['recommendation'],'claims':resolved(current['claims']),'raw_claims':current['claims'],'uncertainties':current['uncertainties'],'allowed_refs':sorted(records),
                'edited':bool(edited),'original':{'recommendation':evidence['recommendation'],'claims':[c['claim'] for c in evidence['claims']],'uncertainties':evidence['uncertainties']} if edited else None}

    def opportunities(self,campaigns):
        result=[]
        for o in OpportunityStore(self.db).opportunities():
            licensed=self.opportunity_assets(o)
            gallery=licensed
            draft=next((c for c in campaigns if c.get('opportunity_id')==o['opportunity_id'] and c['status']!='REJECTED'),None)
            dossier=build_dossier(self.db,o)
            result.append({'id':o['opportunity_id'],'kind':o['kind'],'title':o['title'],'angle':o['angle'],'evidence_strength':o['evidence_strength'],'evidence_label':o['evidence_label'],
                'evidence':o['evidence'],'regions':o['geography']['regions'],'localities':o['geography']['localities'],'identity_status':(o.get('identity') or {}).get('status'),
                'media':gallery[0] if gallery else None,'gallery':gallery[:6],'licensed_images':len(licensed),'evidence_photos':dossier['photos'],'research':dossier['stored_research'],
                'not_assessed':o['assessment'],'sensitive_note':o.get('sensitive_note'),'campaign_id':draft['id'] if draft else None,'campaign_status':draft['status'] if draft else None})
        return result

    @staticmethod
    def sources(evidence):
        return [v for k,v in evidence.items() if k.startswith('https://') and isinstance(v,dict) and v.get('url')]

    def activity(self):
        result=[]
        for table,kind in (('agent_discovery_cycles','discovery'),('agent_runs','legacy')):
            if not exists(self.db,table):continue
            for row in self.db.execute(f'SELECT * FROM {table} ORDER BY created_at DESC LIMIT 12'):
                r=parse(row['result_json'],{});d=r.get('decision',{})
                value={'id':row['run_id'],'kind':kind,'cluster_id':row['cluster_id'],'created_at':row['created_at'],
                       'status':row['status'],'decision':d.get('decision'),'summary':d.get('explanation') or 'Investigation in progress.',
                       'uncertainties':d.get('uncertainties',[]),'errors':bool(r.get('errors')),
                       'hidden_gem':d.get('hidden_gem',{}),'sources':self.sources(r.get('evidence_registry',{}))}
                if clean_evidence(self.db,value):result.append(value)
        return sorted(result,key=lambda r:r['created_at'],reverse=True)

    def snapshot(self):
        campaigns=self.campaigns();activity=self.activity();areas=self.data.areas();archive=[]
        groups={g['destination_id']:g for g in self.data.groups()}
        for area in areas:
            area['hidden_gem_candidate']=any(c['status']!='REJECTED' and c['cluster_id']==area['cluster_id'] and c.get('opportunity',{}).get('classification')=='potential_hidden_gem' for c in campaigns)
            g=groups[area['cluster_id']];media=[]
            for photo_id in g['photo_ids']:
                for row in self.db.execute('SELECT source FROM photos WHERE photo_id=?',(photo_id,)):
                    asset=self.media.asset(row['source'],photo_id)
                    if not asset:continue
                    # Only explicit reviewer annotations can tie pixels to an entity.
                    naming=g.get('name_reference')
                    if naming and g.get('name_status')=='reviewer_verified_reference':
                        for entity in area['entities']:
                            if entity['verified_name'].casefold()==naming.get('name','').casefold():
                                asset={**asset,'association_status':'reviewed_entity_mapping','entity_id':entity['entity_id']}
                    media.append(asset)
            # A verified name does not make the area photograph a verified attraction image.
            area['media']=next((m for m in media if m['entity_id'] and m['rights_status']=='reusable_with_attribution'),None) if area['entities'] else next(iter(media),None)
            area['context_media']=media[:6]
        # The Studio archive is contextual Saudi imagery, never campaign material.
        for item in reviewed_images():
            m=self.media.asset(item['source'],item['photo_id']) if item['collection']=='regional_50' else None
            if m:archive.append(m)
        if exists(self.db,'tourism_relevance'):
            for row in self.db.execute("SELECT t.source,t.photo_id FROM tourism_relevance t JOIN photos p ON p.source=t.source AND p.photo_id=t.photo_id WHERE p.source='afaq_historical' AND t.decision='relevant' ORDER BY t.analyzed_at DESC"):
                m=self.media.asset(row['source'],row['photo_id'])
                if m and m['media_id'] not in {a['media_id'] for a in archive}:archive.append(m)
        areas.sort(key=lambda a:(not bool(a['entities']),len(a['entities'])!=1,
                                 a['entities'][0]['verified_name'] if len(a['entities'])==1 else a['cluster_id']))
        active=any(r['status']=='running' for r in activity)
        if exists(self.db,'dashboard_agent_jobs'):
            active=active or bool(self.db.execute("SELECT 1 FROM dashboard_agent_jobs WHERE status IN ('queued','running')").fetchone())
        if exists(self.db,'campaign_preparation_jobs'):
            active=active or bool(self.db.execute("SELECT 1 FROM campaign_preparation_jobs WHERE status IN ('queued','running')").fetchone())
        pending=sum(c['status']=='PENDING_APPROVAL' for c in campaigns)
        return {'campaigns':campaigns,'opportunities':self.opportunities(campaigns),'areas':areas,'entities':self.data.catalogue()['verified_entities'],
                'activity':activity[:8],'archive':archive[:3],
                'agent_status':'investigating' if active else 'awaiting_approval' if pending else 'idle'}

    def destination(self,cluster_id):
        detail=self.data.cluster(cluster_id)
        if detail is None:return None
        return {'research':detail['research'],'evidence':detail['evidence']}
