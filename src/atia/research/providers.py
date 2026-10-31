from dataclasses import dataclass,asdict
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlparse
import requests


class ResearchUnavailable(RuntimeError):pass
class ResearchFailed(RuntimeError):pass


def public_url(url):
    try:
        p=urlparse(url)
        import ipaddress
        if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):return False
        try:ipaddress.ip_address(p.hostname);return False
        except ValueError:pass
        return '.' in p.hostname and not p.hostname.endswith('.local') and p.hostname!='localhost'
    except (TypeError,ValueError):return False


@dataclass
class Source:
    title:str
    url:str
    publisher:str
    evidence:str
    access:str='search_index_excerpt'
    kind:str='unclassified_search_result'
    subject_match:bool=False
    scope:str='unverified'
    observed_at:str|None=None

    def validate(self):
        if not all(isinstance(v,str) and v.strip() for v in (self.title,self.publisher,self.evidence)) or not public_url(self.url):raise ResearchFailed('Malformed source evidence')
        if not isinstance(self.subject_match,bool) or self.scope not in {'specific_destination','broader_destination','unverified'}:raise ResearchFailed('Invalid source match/scope')
        if self.kind not in {'promotional_coverage','identity_reference','unclassified_search_result'}:raise ResearchFailed('Unknown source evidence kind')
        if self.access not in {'page_read','search_index_excerpt','official_map_link','tavily_search_content'}:raise ResearchFailed('Unsupported source access provenance')
        return asdict(self)


class BraveSearch:
    name='brave_search_api_v1'
    def __init__(self,api_key=None,session=None,pause=time.sleep):
        self.api_key=api_key;self.session=session or requests.Session();self.pause=pause
        self.cache_identity=self.name+':configured='+str(bool(api_key))

    def search(self,query):
        if not self.api_key:raise ResearchUnavailable('BRAVE_SEARCH_API_KEY is not configured; no search was performed')
        for attempt in range(3):
            try:
                response=self.session.get('https://api.search.brave.com/res/v1/web/search',params={'q':query,'count':5,'search_lang':'en'},
                    headers={'X-Subscription-Token':self.api_key,'Accept':'application/json'},timeout=(10,25))
                if response.status_code==429 or response.status_code>=500:
                    if attempt<2:self.pause(2**attempt);continue
                    raise ResearchFailed('Search service rate-limited or unavailable after retries')
                if response.status_code in (401,403):raise ResearchUnavailable('Search API credentials or permissions were rejected')
                if response.status_code!=200:raise ResearchFailed(f'Search HTTP status {response.status_code}')
                payload=response.json();rows=payload.get('web',{}).get('results',[])
                if not isinstance(rows,list):raise ResearchFailed('Malformed search results')
                sources=[]
                for row in rows:
                    if not isinstance(row,dict) or not public_url(row.get('url')):continue
                    source=Source(row.get('title',''),row['url'],urlparse(row['url']).hostname,row.get('description',''))
                    if source.evidence and source.title:sources.append(source.validate())
                return sources
            except requests.RequestException:
                if attempt<2:self.pause(2**attempt);continue
                raise ResearchFailed('Search network failure or timeout') from None
            except ValueError:raise ResearchFailed('Search returned invalid JSON') from None
        raise ResearchFailed('Search did not complete')


class EvidenceFileSearch:
    """Replay recorded search-tool observations; never pretend this file performs live searches."""
    name='recorded_permitted_search_evidence_v1'
    def __init__(self,path):
        content=Path(path).read_bytes();self.document=json.loads(content)
        if not self.document.get('provenance') or not self.document.get('recorded_at'):raise ValueError('Recorded evidence requires provenance and timestamp')
        self.cache_identity=self.name+':'+hashlib.sha256(content).hexdigest()

    def search(self,query):
        entry=self.document.get('queries',{}).get(query)
        if entry is None:raise ResearchUnavailable('No recorded external search observation exists for this exact query')
        if entry.get('status')=='unavailable':raise ResearchUnavailable(entry.get('message','External access unavailable'))
        if entry.get('status')!='ok':raise ResearchFailed(entry.get('message','Recorded search failed'))
        sources=[]
        for raw in entry.get('results',[]):
            raw={**raw,'observed_at':raw.get('observed_at') or self.document['recorded_at']}
            source=Source(**raw);sources.append(source.validate())
        return sources
