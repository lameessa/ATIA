from collections import Counter,defaultdict
from datetime import datetime
import json
from atia.models import number


def exists(db,table):return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone())


def bounds(records,field):
    supplied=[r[field] for r in records if r.get(field)]
    values=[]
    for value in supplied:
        try:datetime.fromisoformat(value)
        except (ValueError,TypeError):continue
        values.append(value)
    return {'minimum_as_recorded':min(values) if values else None,'maximum_as_recorded':max(values) if values else None,
            'available_photos':len(values),'missing_photos':len(records)-len(supplied),'invalid_photos':len(supplied)-len(values),
            'timezone_unknown_photos':sum(datetime.fromisoformat(value).tzinfo is None for value in values),
            'note':'As-recorded timestamps; capture dates are not replaced by upload dates or inferred lighting.'}


class EvidenceIndex:
    def __init__(self,db,records):
        self.db=db;self.records={(r['source'],r['photo_id']):r for r in records}
        self.screen={};self.dimensions={};self.legacy=set();self.reviews={}
        if exists(db,'tourism_relevance'):
            for r in db.execute('SELECT * FROM tourism_relevance ORDER BY analyzed_at DESC'):
                self.screen.setdefault((r['source'],r['photo_id']),dict(r))
        if exists(db,'visual_dimension_analyses'):
            for r in db.execute('SELECT * FROM visual_dimension_analyses ORDER BY analyzed_at DESC'):
                self.dimensions.setdefault((r['source'],r['photo_id'],r['dimension']),dict(r))
        if exists(db,'visual_analyses'):
            self.legacy={(r['source'],r['photo_id']) for r in db.execute('SELECT DISTINCT source,photo_id FROM visual_analyses')}
        if exists(db,'visual_review_labels'):
            for r in db.execute('SELECT * FROM visual_review_labels ORDER BY reviewed_at DESC'):
                self.reviews.setdefault((r['source'],r['photo_id']),dict(r))
        self.comments={};self.comments_by_photo=defaultdict(list);self.sentiments={};self.sentiment_model=None;self.fetch_status={}
        if exists(db,'comment_observations'):
            for r in db.execute('''SELECT o.*,v.clean_text FROM comment_observations o JOIN comment_versions v
                USING(photo_id,comment_id,content_hash) ORDER BY CASE origin WHEN 'flickr_live' THEN 0 ELSE 1 END,observed_at DESC'''):
                self.comments.setdefault((r['photo_source'],r['photo_id'],r['comment_id']),dict(r))
            for (source,photo_id,_),comment in self.comments.items():self.comments_by_photo[(source,photo_id)].append(comment)
            for r in db.execute('SELECT * FROM comment_fetches ORDER BY fetched_at DESC,fetch_id DESC'):
                self.fetch_status.setdefault((r['photo_source'],r['photo_id']),dict(r))
            model=db.execute('''SELECT analysis_version,model_id,model_revision,MAX(analyzed_at) AS latest FROM comment_sentiments
                GROUP BY analysis_version ORDER BY latest DESC,analysis_version LIMIT 1''').fetchone()
            if model:
                self.sentiment_model=dict(model)
                self.sentiments={(r['photo_id'],r['comment_id'],r['content_hash']):dict(r) for r in db.execute('SELECT * FROM comment_sentiments WHERE analysis_version=?',(model['analysis_version'],))}

    def aggregate(self,points):
        records=[self.records[(p['source'],p['photo_id'])] for p in points]
        # Deduplicate identical Flickr IDs across source observations for counts,
        # views and sentiment; source observation counts remain explicit.
        unique={}
        for r in sorted(records,key=lambda r:(r['source']=='flickr_live',r['collected_at']),reverse=True):unique.setdefault(r['photo_id'],r)
        photos=list(unique.values());authors={r['owner_id'] for r in photos if r['owner_id']}
        screen_counts=Counter();env=Counter();elements=Counter();uncertain_env=Counter();visual_photos=0;legacy=0;review_counts=Counter();suppressed=0;visual_versions={}
        for r in photos:
            identity=(r['source'],r['photo_id']);screen=self.screen.get(identity)
            decision=screen['decision'] if screen else 'not_evaluated';screen_counts[decision]+=1
            review=self.reviews.get(identity)
            if review:review_counts[(review['review_type'],review['label'])]+=1
            legacy+=identity in self.legacy
            if decision=='irrelevant':suppressed+=1;continue
            if screen and screen['detail_result']:
                d=json.loads(screen['detail_result']);visual_photos+=1
                provenance={key:screen[key] for key in ('model_key','model_spec','screen_version','detail_version','policy_version')}
                visual_versions[json.dumps(provenance,sort_keys=True)]=provenance
                label=d['environment'].get('label')
                if label:env[label]+=1
                else:uncertain_env[d['environment']['strongest_match']]+=1
                elements.update(d['elements']['possible_matches'])
            else:
                e=self.dimensions.get((*identity,'environment'));el=self.dimensions.get((*identity,'elements'))
                if e or el:visual_photos+=1
                for observation in (e,el):
                    if observation:
                        provenance={key:observation[key] for key in ('model_name','pretrained','library_version','prompt_version','threshold_version')}
                        visual_versions[json.dumps(provenance,sort_keys=True)]=provenance
                if e:
                    interpreted=json.loads(e['interpretation'])
                    if interpreted.get('label'):env[interpreted['label']]+=1
                    else:uncertain_env[interpreted['strongest_match']]+=1
                if el:elements.update(json.loads(el['interpretation']).get('possible_matches',[]))
        views=[r['views'] for r in photos if r['views'] is not None]
        favorites=[]
        for r in photos:
            raw=json.loads(r['raw']);payload=raw.get('favorites',{})
            payload=payload if isinstance(payload,dict) else {}
            favorite_photo=payload.get('photo')
            value=number(favorite_photo.get('total'),integer=True) if payload.get('stat')=='ok' and isinstance(favorite_photo,dict) else None
            if value is not None and value>=0:favorites.append(value)
        observations={}
        for r in records:
            for comment in self.comments_by_photo.get((r['source'],r['photo_id']),[]):
                key=(comment['photo_id'],comment['comment_id']);old=observations.get(key)
                if old is None or (comment['origin']=='flickr_live',comment['observed_at'])>(old['origin']=='flickr_live',old['observed_at']):observations[key]=comment
        sentiments=Counter();languages=Counter();comment_status=Counter()
        for comment in observations.values():
            analysis=self.sentiments.get((comment['photo_id'],comment['comment_id'],comment['content_hash']))
            if analysis is None:comment_status['not_analyzed_current_version']+=1;continue
            comment_status[analysis['status']]+=1
            if analysis['status']=='analyzed':sentiments[analysis['sentiment']]+=1;languages[analysis['language']]+=1
        fetches=[self.fetch_status.get((r['source'],r['photo_id'])) for r in photos]
        return {'photo_count':len(photos),'source_observation_count':len(records),'distinct_photographers':len(authors),
            'missing_photographer_photos':sum(not r['owner_id'] for r in photos),'sources':dict(Counter(r['source'] for r in records)),
            'historical_curated_observations':sum(r['source']=='afaq_historical' for r in records),
            'relevance_coverage':dict(screen_counts),'review_annotations':[{'review_type':t,'label':label,'count':count} for (t,label),count in review_counts.items()],
            'visual':{'photos_with_dimensional_evidence':visual_photos,'missing_dimensional_photos':len(photos)-visual_photos-suppressed,
                      'suppressed_screened_irrelevant_photos':suppressed,'legacy_ranked_observation_photos':legacy,
                      'possible_environment_counts':dict(env),'possible_element_counts':dict(elements),'model_and_prompt_versions':list(visual_versions.values()),
                      'uncertain_environment_top_ranks':dict(uncertain_env),'note':'Uncertain ranks are not accepted labels; historical/cultural labels do not verify age or significance.'},
            'engagement':{'views_sum_observed':sum(views) if views else None,'views_available_photos':len(views),
                          'favorites_sum_observed':sum(favorites) if favorites else None,'favorites_available_photos':len(favorites),
                          'missing_views_photos':len(photos)-len(views),'missing_favorites_photos':len(photos)-len(favorites),
                          'note':'Observed snapshots, not synchronized or measures of demand. Favorites use API total, never a partial person-list length.'},
            'sentiment':{'observed_unique_comments':len(observations),'classified_comments':sum(sentiments.values()),'distribution':dict(sentiments),
                         'languages_analyzed':dict(languages),'comment_statuses':dict(comment_status),'model':self.sentiment_model,
                         'photos_without_fetch_evidence':sum(x is None for x in fetches),'latest_fetch_statuses':dict(Counter(x['status'] for x in fetches if x)),
                         'historical_only_comments':sum(x['origin']=='afaq_historical' for x in observations.values()),
                         'note':'Observed evidence union, latest live text preferred. Missing comments are not assumed deleted; no-data is not neutral.'},
            'upload_dates':bounds(photos,'uploaded_at'),'capture_dates':bounds(photos,'captured_at'),
            'capture_unknown_flags':sum(r['capture_unknown']==1 for r in photos),'capture_granularity':dict(Counter(str(r['capture_granularity']) for r in photos)),
            'interpretation':'Evidence inventory only: photo/photographer counts, favorites, views and comment sentiment do not prove tourism demand.'}
