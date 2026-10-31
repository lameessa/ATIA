import json
from pathlib import Path
from atia.collectors.flickr import FlickrError


def extract_comments(payload):
    wrapper=payload.get('comments')
    if not isinstance(wrapper,dict):raise ValueError('Missing Flickr comments wrapper')
    rows=wrapper.get('comment',[])
    if isinstance(rows,dict):rows=[rows]
    if not isinstance(rows,list):raise ValueError('Invalid Flickr comment list')
    return rows


def import_afaq_comments(path,store):
    dataset=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    report={'photos':0,'comments_inserted':0,'duplicates':0,'failed_responses':0,'malformed':0}
    for region,photos in dataset.items():
        for photo_id,envelope in photos.items():
            record={'source':'afaq_historical','photo_id':str(photo_id)}
            if not store.db.execute('SELECT 1 FROM photos WHERE source=? AND photo_id=?',(record['source'],record['photo_id'])).fetchone():continue
            # Import an immutable historical snapshot once; do not duplicate fetch logs on replay.
            if store.latest_fetch(record,'afaq_historical'):continue
            payload=envelope.get('comments',{})
            report['photos']+=1
            if payload.get('stat')!='ok':
                report['failed_responses']+=1;store.fetch_status(record,'afaq_historical','unavailable',message='Historical response unavailable; cause not inferred');continue
            try:comments=extract_comments(payload)
            except ValueError as exc:
                report['malformed']+=1;store.fetch_status(record,'afaq_historical','malformed',message=str(exc));continue
            counts=store.ingest(record,comments,'afaq_historical')
            report['comments_inserted']+=counts['inserted'];report['duplicates']+=counts['duplicates'];report['malformed']+=counts['malformed']
            store.fetch_status(record,'afaq_historical','ok' if comments else 'empty',len(comments))
    return report


def retrieve_comments(client,store,record,refresh=False):
    cached=store.latest_fetch(record)
    if not refresh and cached and cached['status'] in {'ok','empty'}:return {'accessible':True,'cached':True,'count':cached['comment_count']}
    try:
        payload=client.call('flickr.photos.comments.getList',photo_id=record['photo_id'])
        comments=extract_comments(payload)
    except (FlickrError,ValueError) as exc:
        if isinstance(exc,FlickrError) and exc.code=='100':raise
        store.fetch_status(record,'flickr_live','unavailable',message=str(exc))
        return {'accessible':False,'cached':False,'error':str(exc)}
    counts=store.ingest(record,comments,'flickr_live')
    store.fetch_status(record,'flickr_live','ok' if comments else 'empty',len(comments))
    return {'accessible':True,'cached':False,'count':len(comments),**counts}
