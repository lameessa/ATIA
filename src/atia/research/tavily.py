"""Direct Tavily HTTP search with SQLite response caching. Never stores credentials."""
from datetime import datetime,timedelta,timezone
import hashlib
import json
import time
from urllib.parse import urlparse
import requests
from atia.models import utc_now
from atia.research.providers import Source,ResearchUnavailable,ResearchFailed,public_url

PUBLISHERS={'visitsaudi.com':'Visit Saudi / Saudi Tourism Authority','experiencealula.com':'Experience AlUla / Royal Commission for AlUla',
 'saudipedia.com':'Saudipedia','spa.gov.sa':'Saudi Press Agency','whc.unesco.org':'UNESCO World Heritage Centre',
 'unesco.org':'UNESCO','rcu.gov.sa':'Royal Commission for AlUla','ncw.gov.sa':'National Center for Wildlife',
 'vision2030.gov.sa':'Saudi Vision 2030','heritage.moc.gov.sa':'Saudi Heritage Commission','moc.gov.sa':'Saudi Ministry of Culture'}


def publisher(url):
    host=(urlparse(url).hostname or '').lower()
    for domain,name in sorted(PUBLISHERS.items(),key=lambda item:-len(item[0])):
        if host==domain or host.endswith('.'+domain):return name
    return host


class TavilySearch:
    name='tavily_live_api_v1'
    cache_identity='tavily_live_api_v1-basic-content-v1'
    def __init__(self,store,api_key=None,session=None,pause=time.sleep,ttl_hours=168,refresh=False):
        self.db=store.connection;self.api_key=api_key;self.session=session or requests.Session();self.pause=pause
        if ttl_hours<=0:raise ValueError('Cache TTL must be positive')
        self.ttl_hours=ttl_hours;self.refresh=refresh;self.network_calls=0;self.cache_hits=0;self.observations=[]
        self.db.execute('''CREATE TABLE IF NOT EXISTS tavily_search_observations (
            observation_id TEXT PRIMARY KEY,cache_key TEXT NOT NULL,query TEXT NOT NULL,parameters TEXT NOT NULL,
            requested_at TEXT NOT NULL,request_id TEXT,result TEXT NOT NULL)''')
        self.db.execute('CREATE INDEX IF NOT EXISTS tavily_query_cache ON tavily_search_observations(cache_key,requested_at)')
        self.db.commit()

    def search(self,query,domains=None):
        if not isinstance(query,str) or not query.strip() or len(query)>400:raise ValueError('Tavily query must contain 1–400 characters')
        params={'query':query,'topic':'general','search_depth':'basic','max_results':5,'include_answer':False,'include_raw_content':False}
        if domains:params['include_domains']=sorted(set(domains))
        key=hashlib.sha256(json.dumps(params,sort_keys=True).encode()).hexdigest()
        row=self.db.execute('SELECT * FROM tavily_search_observations WHERE cache_key=? ORDER BY requested_at DESC LIMIT 1',(key,)).fetchone()
        if not self.refresh and row and datetime.fromisoformat(row['requested_at'])>=datetime.now(timezone.utc)-timedelta(hours=self.ttl_hours):
            payload=json.loads(row['result']);self.cache_hits+=1
            self.observations.append({'observation_id':row['observation_id'],'request_id':row['request_id'],'query':query,'requested_at':row['requested_at'],'cache_hit':True})
            return payload['sources']
        if not self.api_key:raise ResearchUnavailable('TAVILY_API_KEY is missing; no live request was made')
        for attempt in range(3):
            try:
                self.network_calls+=1
                response=self.session.post('https://api.tavily.com/search',headers={'Authorization':'Bearer '+self.api_key,'Content-Type':'application/json'},
                    json=params,timeout=(10,40),allow_redirects=False)
                if response.status_code in (401,402,403):raise ResearchUnavailable('Tavily rejected credentials, permissions, or available quota')
                if response.status_code==429 or response.status_code>=500:
                    if attempt<2:
                        try:delay=min(5,max(0,float(response.headers.get('Retry-After',2**attempt))))
                        except (ValueError,TypeError):delay=2**attempt
                        self.pause(delay);continue
                    raise ResearchFailed('Tavily rate limit or service failure after bounded retries')
                if response.status_code!=200:raise ResearchFailed(f'Tavily HTTP status {response.status_code}')
                raw=response.json()
                if not isinstance(raw,dict) or not isinstance(raw.get('results'),list):raise ResearchFailed('Malformed Tavily search response')
                now=utc_now();sources=[]
                for item in raw['results']:
                    if not isinstance(item,dict) or not public_url(item.get('url')):continue
                    title,content=item.get('title'),item.get('content')
                    if not isinstance(title,str) or not title.strip() or not isinstance(content,str) or not content.strip():continue
                    # Content supplied by the API, not an AI-generated answer or claim of direct page access.
                    sources.append(Source(title,item['url'],publisher(item['url']),content[:12000],access='tavily_search_content',observed_at=now).validate())
                import uuid
                identifier='tavily-'+uuid.uuid4().hex
                request_id=raw.get('request_id') if isinstance(raw.get('request_id'),str) else None
                result={'sources':sources,'provider':self.name,'request_id':request_id,'response_time':raw.get('response_time'),
                        'note':'Actual Tavily API results; publisher organization inferred from source host, otherwise host retained.'}
                with self.db:self.db.execute('INSERT INTO tavily_search_observations VALUES(?,?,?,?,?,?,?)',
                    (identifier,key,query,json.dumps(params),now,request_id,json.dumps(result,ensure_ascii=False)))
                self.observations.append({'observation_id':identifier,'request_id':request_id,'query':query,'requested_at':now,'cache_hit':False})
                return sources
            except requests.RequestException:
                if attempt<2:self.pause(2**attempt);continue
                raise ResearchFailed('Tavily network request failed or timed out') from None
            except ValueError:raise ResearchFailed('Tavily returned invalid JSON') from None
        raise ResearchFailed('Tavily search did not complete')
