"""Precommitted, geographically stratified development sample, not a population survey."""
import hashlib
import json
import time
from pathlib import Path
from atia.models import utc_now
from atia.vision.dimensions import fingerprint
from atia.vision.images import ImageUnavailable,ImageAsset
from atia.vision.screen_storage import ScreeningStore

REGIONS=('North','South','East','West','Central')
AUDIT_IDS=('55354696504','55354696509','55358677872','55359604186','55359765713',
           '55359798024','55365818208','55365861304','55503674714','55520699393')


def load_asset(record):
    from PIL import Image,ImageOps
    path=Path(record['image_path'])
    content=path.read_bytes()
    if hashlib.sha256(content).hexdigest()!=record['image_sha256']:
        raise ImageUnavailable('Cached image checksum mismatch')
    with Image.open(path) as image:
        converted=ImageOps.exif_transpose(image).convert('RGB');converted.load()
    return ImageAsset(converted,record['image_url'],record['image_sha256'],str(path),converted.width,converted.height)


def previous_asset(db,record):
    # Only reuse immutable snapshots already downloaded for this same source/ID.
    for table in ('tourism_relevance','visual_dimension_analyses','visual_analyses'):
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():continue
        row=db.execute(f'SELECT image_sha256,image_path,image_url FROM {table} WHERE source=? AND photo_id=? ORDER BY analyzed_at DESC LIMIT 1',
                       (record['source'],record['photo_id'])).fetchone()
        if row:
            try:return load_asset(dict(row))
            except (ImageUnavailable,OSError):pass
    return None


def prepare_sample(store,fetcher,per_region=3,seed='atia-review-v1',include_audit=True,progress=print,source=None):
    try:
        import PIL
    except ImportError:
        raise RuntimeError('Install optional image dependencies: pip install -r requirements-vision.txt') from None
    started=time.monotonic()
    if per_region<1:raise ValueError('per_region must be positive')
    screening=ScreeningStore(store)
    protocol={'per_region':per_region,'seed':seed,'include_audit':include_audit,**({'source_filter':source} if source else {}),
              'selection':'one live then historical/live alternation, stable hashed order, unique IDs; availability replacements only',
              'region_basis':'stored live coordinate zone or historical region label (not independently reverified)'}
    sample_id='regional-'+fingerprint(protocol)[:16]
    with store.connection:
        store.connection.execute('INSERT OR IGNORE INTO review_samples VALUES(?,?,?,?)',(sample_id,seed,json.dumps(protocol),utc_now()))
    existing=screening.members(sample_id)
    used={r['photo_id'] for r in existing if r['status']=='available'}
    count=sum(r['status']=='available' for r in existing)
    # Known audit IDs remain in a separate regression stratum, never the regional sample.
    records=[dict(r) for r in store.connection.execute('SELECT * FROM photos')]
    if source:records=[r for r in records if r['source']==source]
    for r in records:
        r['sample_region']=r['region'] or json.loads(r['raw']).get('historical_region')
        r['region_basis']='coordinate_zone' if r['region'] else 'historical_region_label'
    ordinal=len(existing)
    def add(record,stratum):
        nonlocal ordinal,count
        exists=store.connection.execute('SELECT status FROM review_sample_members WHERE sample_id=? AND source=? AND photo_id=?',
                                       (sample_id,record['source'],record['photo_id'])).fetchone()
        if exists:return exists['status']=='available'
        progress(f"[{record['sample_region']}/{stratum}] Preparing {record['photo_id']}")
        asset=None;error=None
        try:
            asset=previous_asset(store.connection,record) or fetcher.fetch(record)
            values=(asset.sha256,asset.path,asset.url,asset.width,asset.height,'available',None)
        except ImageUnavailable as exc:
            error=str(exc);values=(None,None,None,None,None,'unavailable',error)
        with store.connection:
            store.connection.execute('INSERT INTO review_sample_members VALUES('+','.join('?' for _ in range(14))+')',
                (sample_id,record['source'],record['photo_id'],record['sample_region'],record['region_basis'],stratum,*values,ordinal))
        ordinal+=1
        if asset:
            asset.image.close();used.add(record['photo_id']);count+=1
        return error is None
    for region in REGIONS:
        current=sum(r['status']=='available' and r['region']==region and r['stratum']=='regional' for r in existing)
        pools={source:sorted([r for r in records if r['source']==source and r['sample_region']==region and r['photo_id'] not in AUDIT_IDS],
               key=lambda r:hashlib.sha256((seed+r['source']+r['photo_id']).encode()).hexdigest()) for source in ('flickr_live','afaq_historical')}
        while current<per_region and any(pools.values()):
            preferred='flickr_live' if current==0 or current%3==0 else 'afaq_historical'
            pool=pools[preferred] or pools['afaq_historical' if preferred=='flickr_live' else 'flickr_live']
            record=pool.pop(0)
            if record['photo_id'] in used:continue
            if add(record,'regional'):current+=1
    if include_audit:
        for photo_id in AUDIT_IDS:
            record=next((r for r in records if r['photo_id']==photo_id and r['source']=='flickr_live'),None)
            if record and photo_id not in used:add(record,'audit_regression')
    members=screening.members(sample_id)
    return {'sample_id':sample_id,'protocol':protocol,'available':sum(r['status']=='available' for r in members),
            'regions':{region:sum(r['status']=='available' and r['region']==region and r['stratum']=='regional' for r in members) for region in REGIONS},
            'unavailable':sum(r['status']=='unavailable' for r in members),'elapsed_seconds':round(time.monotonic()-started,2)}
