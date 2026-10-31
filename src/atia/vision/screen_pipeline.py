import json
import time
from collections import Counter
from atia.vision.dimensions import fingerprint
from atia.vision.model import VisionError
from atia.vision.images import ImageUnavailable
from atia.vision.review_sample import load_asset
from atia.vision.screen_storage import ScreeningStore
from atia.vision.screen_model import ScreeningAnalyzer,model_spec
from atia.vision.relevance_prompts import screen_decision,detail_decision


def screen_sample(store,sample_id,batch_size=4,analyzer_factory=ScreeningAnalyzer,progress=print,spec=None,limit=None):
    if limit is not None and limit<1:raise ValueError('limit must be positive')
    if batch_size<1:raise ValueError('batch_size must be positive')
    started=time.monotonic();storage=ScreeningStore(store)
    members=[r for r in storage.members(sample_id) if r['status']=='available']
    if limit is not None:members=members[:limit]
    if not members:raise ValueError('Sample has no available members; run prepare-review first')
    spec=spec or model_spec();key=fingerprint(spec)
    report={'sample_id':sample_id,'requested':limit or len(members),'model':spec,'results':[],'errors':[],'cached':0,'embeddings_reused':0,'images_encoded':0,'image_batches':0}
    model=None
    def analyzer():
        nonlocal model
        if model is None:
            progress('Loading pretrained model and versioned positive/alternative text prompts...');model=analyzer_factory()
        return model
    pending=[]
    def score_pending():
        if not pending:return
        try:
            import numpy as np
            vectors=np.stack([vector for _,vector in pending])
            screen_scores=analyzer().compare(vectors,'screen')
            if len(screen_scores)!=len(pending):raise VisionError('Incorrect relevance result count')
            screens=[screen_decision(scores) for scores in screen_scores]
            relevant=[i for i,s in enumerate(screens) if s['decision']=='relevant']
            details={}
            if relevant:
                detail_scores=analyzer().compare(vectors[relevant],'detail')
                if len(detail_scores)!=len(relevant):raise VisionError('Incorrect detail result count')
                details={i:detail_decision(scores) for i,scores in zip(relevant,detail_scores)}
            for i,((record,_),screen) in enumerate(zip(pending,screens)):
                storage.save(record,spec,screen,details.get(i))
                report['results'].append({'photo_id':record['photo_id'],'source':record['source'],'region':record['region'],'stratum':record['stratum'],
                                         'decision':screen['decision'],'destination_status':screen['destination_status'],'mode':'inferred',
                                         'screen':screen,'details':details.get(i)})
                progress(f"[{record['region']}/{record['stratum']}] {record['photo_id']}: {screen['decision']}")
        except (VisionError,ValueError) as exc:
            report['errors'].extend({'photo_id':record['photo_id'],'message':str(exc)} for record,_ in pending)
        finally:pending.clear()
    for offset in range(0,len(members),batch_size):
        batch=members[offset:offset+batch_size];needs_encoding=[]
        for record in batch:
            cached=storage.cached(record,key)
            if cached:
                report['cached']+=1
                report['results'].append({'photo_id':record['photo_id'],'source':record['source'],'region':record['region'],'stratum':record['stratum'],
                  'decision':cached['decision'],'destination_status':cached['destination_status'],'mode':'cached',
                  'screen':json.loads(cached['screen_result']),'details':json.loads(cached['detail_result']) if cached['detail_result'] else None})
                continue
            vector=storage.embedding(record['image_sha256'],key)
            if vector is not None:
                report['embeddings_reused']+=1;pending.append((record,vector))
            else:
                try:needs_encoding.append((record,load_asset(record)))
                except (ImageUnavailable,OSError,ValueError) as exc:report['errors'].append({'photo_id':record['photo_id'],'message':str(exc)})
        if needs_encoding:
            try:
                progress(f'Encoding {len(needs_encoding)} cached images in one batch...')
                vectors=analyzer().encode_images([asset.image for _,asset in needs_encoding])
                if len(vectors)!=len(needs_encoding):raise VisionError('Incorrect embedding count')
                report['image_batches']+=1
                for (record,_),vector in zip(needs_encoding,vectors):
                    storage.save_embedding(record['image_sha256'],spec,vector)
                    report['images_encoded']+=1;pending.append((record,vector))
            except (VisionError,ValueError) as exc:
                report['errors'].extend({'photo_id':r['photo_id'],'message':str(exc)} for r,_ in needs_encoding)
            finally:
                for _,asset in needs_encoding:asset.image.close()
        score_pending()
    report['counts']=dict(Counter(r['decision'] for r in report['results']))
    report['by_stratum']={s:dict(Counter(r['decision'] for r in report['results'] if r['stratum']==s)) for s in sorted({r['stratum'] for r in report['results']})}
    report['elapsed_seconds']=round(time.monotonic()-started,2)
    report['shortfall']=report['requested']-len(report['results'])
    report['complete']=len(report['results'])==report['requested'] and not report['errors']
    return report
