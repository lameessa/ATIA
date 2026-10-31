from dataclasses import dataclass,asdict
import json
import math
from atia.models import number

ALGORITHM_VERSION='complete-link-metadata-v1'


@dataclass(frozen=True)
class GeoPolicy:
    distance_km:float=1.0
    min_accuracy:int=12

    def __post_init__(self):
        if not math.isfinite(self.distance_km) or not 0<self.distance_km<=50:raise ValueError('distance-km must be in (0,50]')
        if isinstance(self.min_accuracy,bool) or not isinstance(self.min_accuracy,int) or not 1<=self.min_accuracy<=16:raise ValueError('min-accuracy must be an integer from 1 to 16')

    def to_dict(self):return {**asdict(self),'algorithm':ALGORITHM_VERSION,'country':'Saudi Arabia','country_evidence':'Flickr metadata, not independent border verification'}


def distance(a,b):
    lat1,lon1,lat2,lon2=map(math.radians,(a['latitude'],a['longitude'],b['latitude'],b['longitude']))
    h=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371.0088*2*math.asin(min(1,math.sqrt(h)))


def place(value):
    if not isinstance(value,dict):return None
    raw_name=value.get('_content',value.get('name',''))
    name=raw_name.strip() if isinstance(raw_name,str) else ''
    identifier=value.get('woeid')
    return {'name':name or None,'woeid':str(identifier) if identifier not in (None,0,'0') else None} if name or identifier else None


def extract_geo(record,policy):
    raw=json.loads(record['raw']) if isinstance(record['raw'],str) else record['raw']
    envelope=raw.get('info')
    info=envelope.get('photo',raw) if isinstance(envelope,dict) else raw
    if not isinstance(info,dict):info={}
    location=info.get('location') if isinstance(info.get('location'),dict) else {}
    result={'source':record['source'],'photo_id':record['photo_id'],'title':record['title'],
            'latitude':number(record['latitude']),'longitude':number(record['longitude']),
            'accuracy':number(location.get('accuracy',info.get('accuracy')),integer=True),
            'country':place(location.get('country') or raw.get('country_verification')),
            'locality':place(location.get('locality')),'region':place(location.get('region')),
            'neighbourhood':place(location.get('neighbourhood')),
            'macro_region':record.get('region') or raw.get('historical_region'),
            'flickr_place_id':info.get('place_id'),'flickr_woeid':info.get('woeid')}
    lat,lon=result['latitude'],result['longitude']
    reason=None
    if lat is None or lon is None:reason='missing_or_invalid_coordinates'
    elif not (-90<=lat<=90 and -180<=lon<=180) or (lat==0 and lon==0):reason='invalid_coordinates'
    elif not (16<=lat<=33 and 34<=lon<=56):reason='outside_saudi_candidate_extent'
    else:
        country=result['country']
        if not country:reason='missing_country_evidence'
        elif country['woeid'] and country['woeid']!='23424938':reason='non_saudi_country_metadata'
        elif not country['woeid'] and str(country['name']).strip(' ,').casefold() not in {'saudi arabia','السعودية','المملكة العربية السعودية'}:reason='non_saudi_country_metadata'
        elif result['accuracy'] is None or not 1<=result['accuracy']<=16:reason='missing_or_invalid_geo_accuracy'
        elif result['accuracy']<policy.min_accuracy:reason='coarse_geo_accuracy'
    result['unassigned_reason']=reason
    return result


def compatible(a,b):
    # Locality IDs are stronger than spellings; different scripts/names alone
    # are flagged later rather than assumed to be contradictory geographies.
    x,y=a.get('locality'),b.get('locality')
    if x and y and x['woeid'] and y['woeid'] and x['woeid']!=y['woeid']:return False
    x,y=a.get('verified_place'),b.get('verified_place')
    if x and y and x['place_id']!=y['place_id']:return False
    return True


def cluster(points,policy):
    groups=[]
    for point in sorted(points,key=lambda p:(p['photo_id'],p['source'])):
        options=[]
        for index,group in enumerate(groups):
            distances=[distance(point,member) for member in group]
            if all(d<=policy.distance_km for d in distances) and all(compatible(point,member) for member in group):
                options.append((max(distances),index))
        if options:groups[min(options)[1]].append(point)
        else:groups.append([point])
    return groups
