from collections import Counter,defaultdict
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import time
from atia.sentiment.comments import import_afaq_comments,retrieve_comments
from atia.sentiment.model import SentimentModel,SentimentError,MODEL_ID,MODEL_REVISION,PREPROCESS_VERSION
from atia.sentiment.text import LanguageDetector,LANGUAGE_VERSION
from atia.sentiment.storage import CommentStore


def analysis_key(revision):
    return hashlib.sha256(json.dumps({'model':MODEL_ID,'revision':revision,'preprocess':PREPROCESS_VERSION,
                                     'language_policy':LANGUAGE_VERSION,'langid':version('langid')},sort_keys=True).encode()).hexdigest()


def candidates(store):
    rows=[dict(r) for r in store.connection.execute('SELECT * FROM photos ORDER BY photo_id')]
    relevant={(r['source'],r['photo_id']) for r in store.connection.execute("SELECT DISTINCT source,photo_id FROM tourism_relevance WHERE decision='relevant'")} if store.connection.execute("SELECT 1 FROM sqlite_master WHERE name='tourism_relevance'").fetchone() else set()
    first=[r for r in rows if (r['source'],r['photo_id']) in relevant]
    historical=[r for r in rows if r['source']=='afaq_historical' and (r['source'],r['photo_id']) not in relevant]
    # Spread the remaining curated sample over region labels; never rank by views/favorites.
    groups=defaultdict(list)
    for r in historical:groups[json.loads(r['raw']).get('historical_region','unknown')].append(r)
    ordered=[]
    while any(groups.values()):
        for region in sorted(groups):
            if groups[region]:ordered.append(groups[region].pop(0))
    seen=set()
    result=[]
    for r in first+ordered:
        if r['photo_id'] not in seen:result.append(r);seen.add(r['photo_id'])
    return result


def aggregate(store,records,key):
    per_photo=[];destination_rows=defaultdict(dict)
    for record in records:
        evidence=store.evidence(record);analyses=[(comment,store.cached(comment,key)) for comment in evidence]
        counts=Counter(a['sentiment'] for _,a in analyses if a and a['status']=='analyzed')
        languages=Counter(a['language'] for _,a in analyses if a)
        statuses=Counter(a['status'] if a else 'not_processed' for _,a in analyses)
        mapping=store.db.execute('SELECT d.destination_id,d.name FROM sentiment_photo_destinations m JOIN sentiment_destinations d USING(destination_id) WHERE m.photo_source=? AND m.photo_id=?',(record['source'],record['photo_id'])).fetchone()
        result={'source':record['source'],'photo_id':record['photo_id'],'observed_comments':len(evidence),'sentiment_distribution':dict(counts),
                'analyzed_comments':sum(counts.values()),'languages':dict(languages),'statuses':dict(statuses),
                'historical_only_comments':sum(c['origin']=='afaq_historical' for c in evidence),
                'destination_id':mapping['destination_id'] if mapping else None}
        per_photo.append(result)
        if mapping:
            for comment,analysis in analyses:
                if analysis and analysis['status']=='analyzed':
                    destination_rows[(mapping['destination_id'],mapping['name'])][(comment['photo_id'],comment['comment_id'])]=analysis
    return {'per_photo':per_photo,'per_destination':[{'destination_id':identifier,'name':name,'analyzed_comments':len(rows),
        'sentiment_distribution':dict(Counter(a['sentiment'] for a in rows.values()))} for (identifier,name),rows in destination_rows.items()],
        'destination_note':'Only explicit destination mappings are used; regions and engagement are not destination or sentiment evidence.'}


def map_destinations(store,path):
    rows=json.loads(Path(path).read_text())
    with store.db:
        for row in rows:
            store.db.execute('INSERT OR IGNORE INTO sentiment_destinations VALUES(?,?)',(row['destination_id'],row['name']))
            store.db.execute('INSERT OR IGNORE INTO sentiment_photo_destinations VALUES(?,?,?)',(row['source'],str(row['photo_id']),row['destination_id']))


def run_sentiment(photo_store,client,limit=10,batch_size=16,historical_path='Afaq_RawData.json',revision=MODEL_REVISION,
                  refresh=False,progress=None,model_factory=None,detector_factory=LanguageDetector,destination_map=None):
    if limit<1 or batch_size<1:raise ValueError('limit and batch-size must be positive')
    started=time.monotonic();emit=progress or (lambda message:None)
    store=CommentStore(photo_store);key=analysis_key(revision)
    report={'model_id':MODEL_ID,'model_revision':revision,'analysis_version':key,'requested_photos':limit,
            'photos':[],'errors':[],'newly_analyzed':0,'cached_comments':0,'newly_skipped':0,'sentiment_batches':0}
    if destination_map:map_destinations(store,destination_map)
    if historical_path and Path(historical_path).exists():
        emit('Importing historical comment snapshots without changing photo records...')
        report['historical_import']=import_afaq_comments(historical_path,store)
    else:report['historical_import']={'warning':'Historical JSON not found; existing stored evidence remains usable.'}
    records=[]
    report['max_photo_attempts']=max(30,limit*3)
    for record in candidates(photo_store)[:report['max_photo_attempts']]:
        emit(f"[{len(records)}/{limit}] Retrieving comments for {record['source']} photo {record['photo_id']}...")
        fetched=retrieve_comments(client,store,record,refresh)
        if not fetched['accessible']:
            report['errors'].append({'photo_id':record['photo_id'],'stage':'retrieval','message':fetched['error']});continue
        records.append(record);report['photos'].append({'source':record['source'],'photo_id':record['photo_id'],'fetch':fetched})
        if len(records)==limit:break
    detector=None;model=None;pending=[]
    def flush():
        nonlocal model
        if not pending:return
        try:
            if model is None:
                emit('Loading pinned pretrained Arabic/English sentiment model...')
                model=(model_factory or (lambda:SentimentModel(revision)))()
            emit(f'Analyzing {len(pending)} comments in one batch...')
            predictions=model.predict([comment['clean_text'] for comment,language in pending])
            if len(predictions)!=len(pending):raise SentimentError('Unexpected sentiment result count')
            report['sentiment_batches']+=1
            for (comment,language),result in zip(pending,predictions):
                store.save(comment,key,language,revision,result,runtime=model.runtime)
                report['newly_analyzed']+=1
        except (SentimentError,ValueError) as exc:
            report['errors'].append({'stage':'inference','comments':len(pending),'message':str(exc)})
        finally:pending.clear()
    seen=set()
    for record in records:
        comments=store.evidence(record)
        emit(f"Photo {record['photo_id']}: {len(comments)} unique observed comments; empty photos remain valid.")
        for comment in comments:
            identity=(comment['photo_id'],comment['comment_id'],comment['content_hash'])
            if identity in seen:continue
            seen.add(identity)
            cached=store.cached(comment,key)
            if cached:report['cached_comments']+=1;continue
            if detector is None:detector=detector_factory()
            language=detector.detect(comment['clean_text'])
            if language['status']!='ready':
                store.save(comment,key,language,revision);report['newly_skipped']+=1;continue
            pending.append((comment,language))
            if len(pending)>=batch_size:flush()
    flush()
    report['aggregates']=aggregate(store,records,key)
    distributions=Counter();languages=Counter();all_detected=Counter();statuses=Counter()
    for record in records:
        for comment in store.evidence(record):
            result=store.cached(comment,key)
            if not result:statuses['inference_pending_or_error']+=1;continue
            statuses[result['status']]+=1;all_detected[result['language']]+=1
            if result['status']=='analyzed':distributions[result['sentiment']]+=1;languages[result['language']]+=1
    report.update({'accessible_photos':len(records),'comments_analyzed_total':sum(distributions.values()),'analyzed_language_distribution':dict(languages),
                   'detected_language_distribution':dict(all_detected),'sentiment_distribution':dict(distributions),'comment_statuses':dict(statuses),
                   'elapsed_seconds':round(time.monotonic()-started,2),'complete':len(records)==limit and not any(e.get('stage')=='inference' for e in report['errors'])})
    return report
