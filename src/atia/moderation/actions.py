"""Private review/export and narrowly authorized confident retirement."""
from collections import Counter
import html
import json
from pathlib import Path
from atia.models import utc_now
from .policy import initialize,exists

REGIONS=('North','South','East','West','Central')


def summary(store):
    db=store.connection;initialize(db)
    current=[dict(r) for r in db.execute('SELECT m.*,p.region AS stored_region FROM photo_moderation m JOIN photos p ON p.photo_id=m.photo_id AND p.source=?',('flickr_live',))]
    evaluations=[json.loads(r['evaluation_json']) for r in current if r['evaluation_json']]
    removed=[dict(r) for r in db.execute('SELECT * FROM photo_removal_audit')]
    relevant_safe=[r for r in current if r['relevance']=='relevant' and r['safety']=='pass' and r['review_status']!='REJECTED']
    by_region={region:[] for region in REGIONS}
    for r in relevant_safe:
        e=json.loads(r['evaluation_json']);region=e.get('region')
        if region in by_region:by_region[region].append(r)
    counts={'evaluated_records':len(evaluations)+len(removed),'successful_image_evaluations':sum(r.get('completed',False) for r in evaluations)+len(removed),
        'live_records_remaining':len(current),'relevant_and_screen_pass':len(relevant_safe),
        'irrelevant':sum(r['relevance']=='irrelevant' for r in current)+sum('relevance=irrelevant;' in r['reason'] for r in removed),
        'unsafe':sum(r['safety']=='unsafe' for r in current)+sum('safety=unsafe;' in r['reason'] for r in removed),
        'uncertain_or_manual_review':sum(r['status']=='quarantined' and r['review_status']!='REJECTED' for r in current),
        'rejected':sum(r['review_status']=='REJECTED' for r in current),
        'removed':len(removed),'awaiting_approval':sum(r['status']=='awaiting_approval' for r in current),
        'approved':sum(r['status']=='approved' for r in current),
        'historical_preserved':db.execute("SELECT count(*) FROM photos WHERE source='afaq_historical'").fetchone()[0],
        'regions':{region:{'target':2,'candidates':len(rows),'awaiting_approval':sum(r['status']=='awaiting_approval' for r in rows),
                  'approved':sum(r['status']=='approved' for r in rows),'shortfall':max(0,2-len(rows))} for region,rows in by_region.items()}}
    return counts


def review(store,photo_id,approve,reviewer,reason,confirm=False):
    if not confirm or not reviewer.strip() or not reason.strip():raise ValueError('Explicit --confirm, reviewer and explanation are required')
    db=store.connection;initialize(db)
    row=db.execute('SELECT * FROM photo_moderation WHERE photo_id=?',(photo_id,)).fetchone()
    if not row:raise ValueError('Live photograph is missing or was removed')
    if approve:
        if row['review_status']=='REJECTED':raise ValueError('Explicit rejection must not be overridden by approval or automatic selection')
        if row['status'] not in ('awaiting_approval','approved') or row['relevance']!='relevant' or row['safety']!='pass':
            raise ValueError('Cannot approve: relevant image inspection and safety screening must pass first. Uncertain photographs remain quarantined.')
        e=json.loads(row['evaluation_json'])
        if not e.get('visual_inspection') or e['visual_inspection'].get('image_sha256')!=e['image_sha256']:
            raise ValueError('Hash-matched professional visual inspection required before approval')
        from atia.vision.review_sample import load_asset
        asset_row=db.execute('SELECT * FROM moderation_asset_cache WHERE photo_id=?',(photo_id,)).fetchone()
        if not asset_row:raise ValueError('Review asset missing; evaluate again')
        asset=load_asset(dict(asset_row));asset.image.close()
        region=e.get('region')
        if region not in REGIONS:raise ValueError('Geographic region unresolved')
        approved=summary(store)['regions'][region]['approved']
        if row['status']!='approved' and approved>=2:raise ValueError('Two photographs already approved in this region')
    decision='APPROVED' if approve else 'REJECTED'
    with db:db.execute('UPDATE photo_moderation SET status=?,review_status=?,reviewer=?,reviewed_at=?,review_reason=? WHERE photo_id=?',
        ('approved' if approve else 'quarantined',decision,reviewer,utc_now(),reason,photo_id))
    return {'photo_id':photo_id,'status':decision,'reviewer':reviewer,'reason':reason}


def inspect_labels(store,path):
    """Import hash-pinned visual observations. This NEVER approves a photograph."""
    rows=json.loads(Path(path).read_text());db=store.connection
    for item in rows:
        if item.get('relevance') not in ('relevant','irrelevant','uncertain') or item.get('safety') not in ('pass','unsafe','uncertain'):
            raise ValueError('Both independent dimensions required')
        if not item.get('reason') or not item.get('reviewer') or not item.get('inspection_type'):raise ValueError('Inspection provenance and explanation required')
        row=db.execute('SELECT * FROM photo_moderation WHERE photo_id=?',(str(item['photo_id']),)).fetchone()
        if not row or not row['evaluation_json']:raise ValueError('Run complete local evaluation before visual review')
        if row['review_status'] in ('REJECTED','APPROVED'):raise ValueError('Visual inference cannot override an explicit user review decision')
        e=json.loads(row['evaluation_json'])
        if not e['completed'] or item.get('image_sha256')!=e.get('image_sha256'):raise ValueError('Visual review must match the evaluated image hash')
        from atia.vision.review_sample import load_asset
        asset_row=db.execute('SELECT * FROM moderation_asset_cache WHERE photo_id=?',(str(item['photo_id']),)).fetchone()
        if not asset_row:raise ValueError('Visual review asset is missing')
        verified_asset=load_asset(dict(asset_row));verified_asset.image.close()
        e['visual_inspection']={**item,'at':utc_now()}
        relevance=item['relevance']
        # A pass requires BOTH an independent visual assessment and a low-risk
        # classifier result. Visual review cannot override an NSFW concern.
        human_override=item['inspection_type']=='user_manual_review' and e['safety']['status']!='unsafe'
        safety='unsafe' if item['safety']=='unsafe' else 'pass' if item['safety']=='pass' and (e['safety']['status']=='pass' or human_override) else 'uncertain'
        e['relevance']=relevance;e['relevance_explanation']=item['reason'];e['safety']['final_assessment']=safety
        status='awaiting_approval' if relevance=='relevant' and safety=='pass' else 'quarantined'
        with db:db.execute('UPDATE photo_moderation SET status=?,review_status=?,relevance=?,safety=?,evaluation_json=? WHERE photo_id=?',
            (status,'PENDING_REVIEW' if status=='awaiting_approval' else None,relevance,safety,json.dumps(e,ensure_ascii=False),str(item['photo_id'])))
    return {'visual_inspections_imported':len(rows),'approved':0}


def export_queue(store,output='data/private-review'):
    db=store.connection;root=Path(output).resolve();root.mkdir(parents=True,exist_ok=True)
    if Path('frontend').resolve() in root.parents:raise ValueError('Private review must remain outside the frontend tree')
    cards=[];manifest=[]
    for region in REGIONS:
        eligible=[]
        for r in db.execute("SELECT m.*,p.title FROM photo_moderation m JOIN photos p ON p.photo_id=m.photo_id AND p.source='flickr_live' WHERE m.status='awaiting_approval' AND coalesce(m.review_status,'')!='REJECTED' ORDER BY m.photo_id"):
            e=json.loads(r['evaluation_json'])
            if e.get('region')==region and e.get('visual_inspection'):eligible.append((r,e))
        cards.append(f'<h2>{region}: {len(eligible)} candidates (target 2; shortfall {max(0,2-len(eligible))})</h2>')
        eligible.sort(key=lambda pair:(pair[1]['visual_inspection'].get('priority',100),pair[0]['photo_id']))
        for r,e in eligible[:2]:
            asset=db.execute('SELECT * FROM moderation_asset_cache WHERE photo_id=?',(r['photo_id'],)).fetchone()
            if not asset:continue
            from atia.vision.review_sample import load_asset
            loaded=load_asset(dict(asset));loaded.image.close()
            # Copies are only created for independently reviewed, screened candidates.
            import shutil
            image=root/(r['photo_id']+'.jpg');shutil.copyfile(asset['image_path'],image)
            manifest.append({'photo_id':r['photo_id'],'region':region,'image_sha256':e['image_sha256'],'status':r['review_status'] or 'PENDING_REVIEW'})
            cards.append(f'<article><img src="{image.name}" alt="Private candidate"><h3>{html.escape(r["photo_id"])}</h3><strong>{html.escape(r["review_status"] or "PENDING_REVIEW")}</strong><p>{html.escape(e["relevance_explanation"])}</p><p>Automated safety screening passed; your professional review and explicit CLI approval remain required. No automatic approval.</p></article>')
    page='<!doctype html><meta charset="utf-8"><title>ATIA PRIVATE REVIEW</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto;background:#f5f5f1;color:#243c31}article{display:inline-block;vertical-align:top;background:white;border:1px solid #ccc;border-radius:8px;margin:10px;padding:16px;width:320px}img{width:100%;height:240px;object-fit:contain}h2{clear:both}p{line-height:1.7}</style><h1>PRIVATE · Live photograph approval queue</h1><p>Not served by the presentation dashboard. Nothing here is approved. Regional shortages are retained.</p>'+''.join(cards)
    (root/'index.html').write_text(page);(root/'manifest.json').write_text(json.dumps(manifest,indent=2))
    selected={item['photo_id'] for item in manifest}
    for stale in root.glob('*.jpg'):
        if stale.stem not in selected:stale.unlink()
    return {'queue':str(root/'index.html'),'candidates':len(manifest),'summary':summary(store)}


def retire_confident(store,root='data'):
    db=store.connection;initialize(db);removed=[];paths=set();hashes=set()
    for row in db.execute("SELECT * FROM photo_moderation WHERE status!='approved'").fetchall():
        if not row['evaluation_json']:continue
        e=json.loads(row['evaluation_json']);inspection=e.get('visual_inspection')
        # Ambiguous or classifier-only decisions cannot trigger destruction.
        if not inspection or inspection.get('confidence')!='clear':continue
        if row['relevance']!='irrelevant' and row['safety']!='unsafe':continue
        photo_id=row['photo_id']
        tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            cols={r[1] for r in db.execute('PRAGMA table_info("'+table+'")')}
            if 'image_path' in cols and 'photo_id' in cols:
                source='source' if 'source' in cols else 'photo_source' if 'photo_source' in cols else None
                query=f'SELECT image_path FROM "{table}" WHERE photo_id=?'+(f" AND {source}='flickr_live'" if source else '')
                paths.update(r[0] for r in db.execute(query,(photo_id,)) if r[0])
        if e.get('image_sha256'):hashes.add(e['image_sha256'])
        reason=f"relevance={row['relevance']};safety={row['safety']}; "+inspection['reason']+'; local model='+e['safety']['model']
        with db:
            # Explicit child-first order; foreign keys remain enabled throughout.
            for table in ('destination_dimension_analyses','visual_review_labels','review_sample_members','tourism_relevance',
                          'visual_dimension_analyses','visual_analyses','visual_attempts','destination_photo_assignments',
                          'comment_fetches','comment_observations','sentiment_photo_destinations'):
                if not exists(db,table):continue
                cols={r[1] for r in db.execute('PRAGMA table_info('+table+')')}
                source='source' if 'source' in cols else 'photo_source'
                db.execute(f"DELETE FROM {table} WHERE {source}='flickr_live' AND photo_id=?",(photo_id,))
            if not db.execute("SELECT 1 FROM photos WHERE source='afaq_historical' AND photo_id=?",(photo_id,)).fetchone():
                for table in ('comment_sentiments','comment_versions'):
                    if exists(db,table):db.execute(f'DELETE FROM {table} WHERE photo_id=?',(photo_id,))
            db.execute("DELETE FROM photos WHERE source='flickr_live' AND photo_id=?",(photo_id,))
            db.execute('DELETE FROM moderation_asset_cache WHERE photo_id=?',(photo_id,))
            db.execute('DELETE FROM photo_moderation WHERE photo_id=?',(photo_id,))
            db.execute('INSERT OR IGNORE INTO photo_removal_audit VALUES(?,?,?)',(photo_id,reason,utc_now()))
        removed.append(photo_id)
    # Retain any shared image that is still referenced by a curated/retained photo.
    references=set()
    for table in [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]:
        cols={r[1] for r in db.execute('PRAGMA table_info("'+table+'")')}
        if 'image_path' in cols:references.update(str(Path(r[0]).resolve()) for r in db.execute(f'SELECT image_path FROM "{table}" WHERE image_path IS NOT NULL'))
    deleted_files=0;data=Path(root).resolve()
    for name in paths:
        p=Path(name).resolve()
        if p.is_relative_to(data) and str(p) not in references and p.is_file():p.unlink();deleted_files+=1
    # Old derived HTML/contact sheets may contain embedded pixels; discard only
    # derived reports containing a retired ID, not curated original image files.
    for p in data.rglob('*'):
        if not p.is_file() or p.suffix.lower() not in ('.html','.jpg','.png','.jpeg','.webp'):continue
        retire=any(i in p.stem for i in removed)
        if removed and p.parent==data/'quarantine'/'inspection':retire=True
        if p.suffix=='.html':
            try:retire=any(i in p.read_text() for i in removed)
            except (OSError,UnicodeError):pass
        if retire and str(p.resolve()) not in references:p.unlink();deleted_files+=1
    for sha in hashes:
        if exists(db,'image_embeddings') and not any(Path(ref).stem==sha for ref in references):
            with db:db.execute('DELETE FROM image_embeddings WHERE image_sha256=?',(sha,))
    return {'removed':len(removed),'removed_ids':removed,'cached_and_derived_files_deleted':deleted_files}
