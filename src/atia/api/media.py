"""Provider-neutral presentation media. No search, downloads or ingestion here.

Future providers must return the same provenance/rights/approval contract. External
assets are not accepted or automatically approved by this read-only Flickr adapter.
"""
from typing import Protocol
from pathlib import Path
import hashlib
from atia.destinations.evidence import exists
from atia.moderation.display import can_display,displayable_file,earlier_review
from atia.intelligence.licences import attribution_text,interpret
from .data import parse


class MediaProvider(Protocol):
    def asset(self,source:str,photo_id:str)->dict|None: ...


def cached_photo(db,source,photo_id):
    """Only reviewed, unchanged local snapshots; neither redirects nor remote fallbacks."""
    return displayable_file(db,source,photo_id)


class FlickrMedia:
    def __init__(self,db):self.db=db

    def licence(self,row):
        """The licence Flickr last reported. can_display has already required a reusable one."""
        status=self.db.execute('SELECT current_license_id,checked_at FROM photo_flickr_status WHERE source=? AND photo_id=?',(row['source'],row['photo_id'])).fetchone()
        return {**interpret(status['current_license_id']),'checked_at':status['checked_at']}

    def asset(self,source,photo_id):
        if not can_display(self.db,source,photo_id):return None
        row=self.db.execute('SELECT * FROM main.photos WHERE source=? AND photo_id=?',(source,photo_id)).fetchone()
        if not row:return None
        raw=parse(row['raw'],{});raw=raw if isinstance(raw,dict) else {}
        info=raw.get('info',{});info=info.get('photo',{}) if isinstance(info,dict) else {}
        owner=info.get('owner',{}) if isinstance(info,dict) else {};owner=owner if isinstance(owner,dict) else {}
        # Searched photos carry the name in the status record or Flickr's search extras.
        status=self.db.execute('SELECT owner_name FROM photo_flickr_status WHERE source=? AND photo_id=?',(source,photo_id)).fetchone() if exists(self.db,'photo_flickr_status') else None
        photographer=owner.get('realname') or owner.get('username') or (status['owner_name'] if status else None) or raw.get('ownername')
        licence=self.licence(row)
        return {'media_id':source+':'+photo_id,'provider':'flickr','source':source,'photo_id':photo_id,
                'preview_url':f'/api/images/{source}/{photo_id}',
                'source_url':f'https://www.flickr.com/photo.gne?id={photo_id}',
                'title':row['title'] or 'Curated archive photograph',
                'attribution':photographer or row['owner_id'] or 'Photographer not recorded',
                'license_name':licence['name'],'license_url':licence['url'],'license_checked_at':licence.get('checked_at'),
                'attribution_text':attribution_text(row['title'],photographer,licence,row['photo_url']),
                'rights_status':'reusable_with_attribution' if licence['campaign_eligible'] else 'permission_not_verified',
                'usage_scope':'internal_reference_only','association_status':'geographic_context_only',
                'approval_status':'APPROVED',
                'review_basis':'Assistant visual review' if earlier_review(source,photo_id) else 'Reviewed by a person',
                'entity_id':None}
