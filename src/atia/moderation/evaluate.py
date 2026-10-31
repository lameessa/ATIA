"""All-live evaluation: local CLIP evidence plus a local pretrained NSFW model.

Neither a CLIP match nor a moderation pass constitutes manual/public approval.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import time
import uuid
from atia.models import utc_now
from atia.collectors.regions import region_for
from atia.vision.review_sample import previous_asset,load_asset
from atia.vision.images import FlickrImageFetcher
from atia.collectors.flickr import live_client
from .policy import VERSION,initialize,exists

MODEL='Falconsai/nsfw_image_detection'
MODEL_REVISION='96cb0d0342c7afb80cab76ecc58b265fa44da256'
SAFETY_POLICY={'unsafe_minimum':.995,'review_minimum':.05,'image_only':True,'professional_approval':'mandatory human review'}


class LocalSafetyModerator:
    def __init__(self):
        from transformers import AutoImageProcessor,AutoModelForImageClassification
        import torch
        self.torch=torch;self.calls=0
        self.processor=AutoImageProcessor.from_pretrained(MODEL,revision=MODEL_REVISION,cache_dir='data/moderation-models',trust_remote_code=False,use_fast=False)
        self.model=AutoModelForImageClassification.from_pretrained(MODEL,revision=MODEL_REVISION,cache_dir='data/moderation-models',trust_remote_code=False,use_safetensors=True)
        self.model.eval();self.model.requires_grad_(False)
        self.revision=getattr(self.model.config,'_commit_hash',None)

    def evaluate(self,asset):
        self.calls+=1
        with self.torch.inference_mode():
            values=self.model(**self.processor(images=asset.image,return_tensors='pt')).logits.softmax(-1)[0].tolist()
        scores={str(self.model.config.id2label[i]).lower():float(v) for i,v in enumerate(values)}
        if 'nsfw' not in scores:raise ValueError('Unexpected local moderation label mapping')
        score=scores['nsfw'];status='unsafe' if score>=SAFETY_POLICY['unsafe_minimum'] else 'uncertain' if score>=SAFETY_POLICY['review_minimum'] else 'pass'
        return {'status':status,'model':MODEL,'revision':self.revision,'scores':scores,'policy':SAFETY_POLICY,
            'reason':('Very high NSFW classifier signal; professional presentation unsuitable.' if status=='unsafe' else
                      'Possible NSFW content; manual review required.' if status=='uncertain' else
                      'Local NSFW screening below review threshold; NOT comprehensive professional/cultural safety certification.'),
            'limitations':['NSFW softmax is uncalibrated; does not comprehensively detect violence, hate, drugs, consent or cultural suitability.',
                          'All live images still require explicit user review; never automatically approved.'],
            'input':'Locally decoded pixels; no image uploaded to any external inference provider.'}


def suspect_child_sexual_metadata(record):
    text=(record['title']+' '+record['tags']).casefold()
    return bool(re.search(r'\b(child|children|minor|underage|teen)\b',text) and re.search(r'\b(nude|naked|sex|porn)\b',text))


def visual_reference(db,record,sha):
    if not exists(db,'visual_review_labels'):return None
    row=db.execute('SELECT label,reason,review_type,reviewer FROM visual_review_labels WHERE source=? AND photo_id=? AND image_sha256=? ORDER BY reviewed_at DESC LIMIT 1',
        ('flickr_live',record['photo_id'],sha)).fetchone()
    return dict(row) if row else None


def evaluate_all(store,progress=print,moderator=None,analyzer_factory=None,fetcher_factory=None,batch_size=8):
    from atia.vision.screen_model import ScreeningAnalyzer,model_spec
    from atia.vision.screen_storage import ScreeningStore
    from atia.vision.relevance_prompts import screen_decision,SCREEN_VERSION,POLICY_VERSION
    from atia.vision.dimensions import fingerprint
    started=time.monotonic();db=store.connection;initialize(db);screenstore=ScreeningStore(store)
    records=[dict(r) for r in db.execute("SELECT * FROM photos WHERE source='flickr_live' ORDER BY region,photo_id")]
    identifier='moderation-'+uuid.uuid4().hex
    with db:db.execute('INSERT INTO moderation_runs VALUES(?,?,NULL,NULL)',(identifier,utc_now()))
    moderator=moderator or LocalSafetyModerator();spec=model_spec();key=fingerprint(spec);model=None;results=[]
    for offset in range(0,len(records),batch_size):
        batch=records[offset:offset+batch_size];assets={};errors={}
        missing=[]
        for r in batch:
            prior=db.execute('SELECT * FROM photo_moderation WHERE photo_id=?',(r['photo_id'],)).fetchone()
            if prior['review_status'] in ('REJECTED','APPROVED'):
                if prior['evaluation_json']:results.append(json.loads(prior['evaluation_json']))
                progress(f"{r['photo_id']}: explicit user decision retained; no reprocessing")
                continue
            if prior['evaluation_json']:
                saved=json.loads(prior['evaluation_json'])
                if saved.get('policy_version')==VERSION and saved.get('completed'):
                    results.append(saved);progress(f"[{len(results)}/{len(records)}] {r['photo_id']}: cached evaluation");continue
            try:
                row=db.execute('SELECT * FROM moderation_asset_cache WHERE photo_id=?',(r['photo_id'],)).fetchone()
                asset=load_asset(dict(row)) if row else previous_asset(db,r)
                if asset:assets[r['photo_id']]=asset
                else:missing.append(r)
            except Exception:missing.append(r)
        def fetch(record):
            factory=fetcher_factory or (lambda:FlickrImageFetcher(live_client(os.getenv('FLICKR_API_KEY','')),cache_dir='data/quarantine/images'))
            try:return record['photo_id'],factory().fetch(record),None
            except Exception as exc:return record['photo_id'],None,'Image retrieval/validation unavailable ('+type(exc).__name__+'); cause unknown, not assumed deleted.'
        with ThreadPoolExecutor(max_workers=4) as pool:
            for photo_id,asset,error in pool.map(fetch,missing):
                if asset:assets[photo_id]=asset
                else:errors[photo_id]=error
        for photo_id,asset in assets.items():
            with db:db.execute('INSERT OR REPLACE INTO moderation_asset_cache VALUES(?,?,?,?)',(photo_id,asset.sha256,asset.path,asset.url))
        scores={};need=[]
        for r in batch:
            asset=assets.get(r['photo_id'])
            if not asset:continue
            cached=db.execute('SELECT screen_result FROM tourism_relevance WHERE source=? AND photo_id=? AND image_sha256=? AND screen_version=? AND policy_version=? ORDER BY analyzed_at DESC LIMIT 1',
                ('flickr_live',r['photo_id'],asset.sha256,SCREEN_VERSION,POLICY_VERSION)).fetchone()
            if cached:scores[r['photo_id']]=json.loads(cached['screen_result'])
            else:need.append(r)
        if need:
            try:
                if model is None:
                    progress('Loading cached pretrained OpenCLIP; no training or paid LLM generation.');model=(analyzer_factory or ScreeningAnalyzer)()
                vectors=[];new=[]
                for r in need:
                    vector=screenstore.embedding(assets[r['photo_id']].sha256,key)
                    if vector is None:new.append(r)
                    else:vectors.append((r,vector))
                if new:
                    encoded=model.encode_images([assets[r['photo_id']].image for r in new])
                    for r,vector in zip(new,encoded):
                        screenstore.save_embedding(assets[r['photo_id']].sha256,spec,vector);vectors.append((r,vector))
                import numpy as np
                raw=model.compare(np.stack([v for _,v in vectors]),'screen')
                for (r,_),value in zip(vectors,raw):scores[r['photo_id']]=screen_decision(value)
            except Exception as exc:
                for r in need:errors[r['photo_id']]='Local visual analysis unavailable ('+type(exc).__name__+')'
        for r in batch:
            asset=assets.get(r['photo_id'])
            if r['photo_id'] not in assets and r['photo_id'] not in errors:continue # already cached
            visual=scores.get(r['photo_id']);reference=visual_reference(db,r,asset.sha256) if asset else None
            relevance='uncertain';reason='Insufficient independently reviewed destination evidence; CLIP scores alone do not prove relevance.'
            if reference and visual and reference['label']==visual['decision'] and reference['label'] in ('relevant','irrelevant'):
                relevance=reference['label'];reason='Matching image-hash visual inspection and local contrastive screening: '+reference['reason']
            safety={'status':'uncertain','model':MODEL,'reason':'No valid image content moderation result.'}
            if asset:
                if suspect_child_sexual_metadata(r):safety['reason']='Restricted child-safety concern in metadata; specialist review required. No external upload.'
                else:
                    try:safety=moderator.evaluate(asset)
                    except Exception as exc:safety['reason']='Image moderation unavailable ('+type(exc).__name__+'); retained in quarantine.'
            region=r['region'] or (region_for(r['latitude'],r['longitude']) if r['latitude'] is not None and r['longitude'] is not None else None)
            result={'photo_id':r['photo_id'],'region':region,'policy_version':VERSION,'evaluated_at':utc_now(),
                'completed':bool(asset and visual and safety.get('scores')),'image_sha256':asset.sha256 if asset else None,
                'relevance':relevance,'relevance_explanation':reason,'clip_evidence':visual,'visual_reference':reference,
                'visual_model':spec,'relevance_prompt_version':SCREEN_VERSION,'safety':safety,
                'error':errors.get(r['photo_id']),'manual_approval':False}
            status='awaiting_approval' if relevance=='relevant' and safety['status']=='pass' else 'quarantined'
            with db:db.execute('UPDATE photo_moderation SET status=?,relevance=?,safety=?,evaluation_json=? WHERE photo_id=?',
                (status,relevance,safety['status'],json.dumps(result,ensure_ascii=False),r['photo_id']))
            results.append(result);progress(f"[{len(results)}/{len(records)}] {r['photo_id']}: relevance={relevance}; safety={safety['status']}; {status}")
        for asset in assets.values():asset.image.close()
    report={'run_id':identifier,'attempted':len(results),'requested':len(records),'completed':sum(r['completed'] for r in results),
        'relevance':dict(Counter(r['relevance'] for r in results)),'safety':dict(Counter(r['safety']['status'] for r in results)),
        'relevant_and_screen_pass':sum(r['relevance']=='relevant' and r['safety']['status']=='pass' for r in results),
        'local_moderation_images':moderator.calls,'external_image_uploads':0,'paid_generation_requests':0,'elapsed_seconds':round(time.monotonic()-started,2)}
    with db:db.execute('UPDATE moderation_runs SET completed_at=?,report=? WHERE run_id=?',(utc_now(),json.dumps(report),identifier))
    return report
