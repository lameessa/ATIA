import hashlib
import json
import math
from atia.models import utc_now,upload_date
from atia.sentiment.text import clean_comment,LANGUAGE_VERSION
from atia.sentiment.model import MODEL_ID,PREPROCESS_VERSION


class CommentStore:
    def __init__(self,store):
        self.db=store.connection
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS comment_versions (
          photo_id TEXT NOT NULL,comment_id TEXT NOT NULL,content_hash TEXT NOT NULL,
          raw_text TEXT NOT NULL,clean_text TEXT NOT NULL,created_at TEXT,raw_metadata TEXT NOT NULL,
          PRIMARY KEY(photo_id,comment_id,content_hash));
        CREATE TABLE IF NOT EXISTS comment_observations (
          photo_source TEXT NOT NULL,photo_id TEXT NOT NULL,comment_id TEXT NOT NULL,content_hash TEXT NOT NULL,
          origin TEXT NOT NULL,observed_at TEXT NOT NULL,
          PRIMARY KEY(photo_source,photo_id,comment_id,content_hash,origin),
          FOREIGN KEY(photo_source,photo_id) REFERENCES photos(source,photo_id),
          FOREIGN KEY(photo_id,comment_id,content_hash) REFERENCES comment_versions(photo_id,comment_id,content_hash));
        CREATE TABLE IF NOT EXISTS comment_fetches (
          fetch_id INTEGER PRIMARY KEY,photo_source TEXT NOT NULL,photo_id TEXT NOT NULL,origin TEXT NOT NULL,
          status TEXT NOT NULL,comment_count INTEGER,message TEXT,fetched_at TEXT NOT NULL,
          FOREIGN KEY(photo_source,photo_id) REFERENCES photos(source,photo_id));
        CREATE TABLE IF NOT EXISTS comment_sentiments (
          photo_id TEXT NOT NULL,comment_id TEXT NOT NULL,content_hash TEXT NOT NULL,
          analysis_version TEXT NOT NULL,language TEXT NOT NULL,language_confidence REAL,language_status TEXT NOT NULL,
          sentiment TEXT,confidence REAL,scores TEXT,status TEXT NOT NULL,
          model_id TEXT NOT NULL,model_revision TEXT NOT NULL,preprocess_version TEXT NOT NULL,
          language_version TEXT NOT NULL,runtime TEXT,truncated INTEGER NOT NULL,analyzed_at TEXT NOT NULL,
          PRIMARY KEY(photo_id,comment_id,content_hash,analysis_version),
          FOREIGN KEY(photo_id,comment_id,content_hash) REFERENCES comment_versions(photo_id,comment_id,content_hash));
        CREATE TABLE IF NOT EXISTS sentiment_destinations (
          destination_id TEXT PRIMARY KEY,name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sentiment_photo_destinations (
          photo_source TEXT NOT NULL,photo_id TEXT NOT NULL,destination_id TEXT NOT NULL,
          PRIMARY KEY(photo_source,photo_id),
          FOREIGN KEY(photo_source,photo_id) REFERENCES photos(source,photo_id),
          FOREIGN KEY(destination_id) REFERENCES sentiment_destinations(destination_id));
        ''');self.db.commit()

    def ingest(self,record,comments,origin):
        report={'inserted':0,'duplicates':0,'malformed':0}
        if not isinstance(comments,list):raise ValueError('Comments must be a list')
        with self.db:
            for raw in comments:
                if not isinstance(raw,dict) or not isinstance(raw.get('id'),(str,int)) or isinstance(raw.get('id'),bool) or not str(raw.get('id','')).strip():
                    report['malformed']+=1;continue
                comment_id=str(raw['id']).strip()
                text=raw.get('_content','')
                if not isinstance(text,str):text=''
                digest=hashlib.sha256(text.encode()).hexdigest()
                cursor=self.db.execute('INSERT OR IGNORE INTO comment_versions VALUES(?,?,?,?,?,?,?)',
                    (record['photo_id'],comment_id,digest,text,clean_comment(text),upload_date(raw.get('datecreate')),json.dumps(raw,ensure_ascii=False)))
                report['inserted' if cursor.rowcount else 'duplicates']+=1
                self.db.execute('INSERT OR IGNORE INTO comment_observations VALUES(?,?,?,?,?,?)',
                    (record['source'],record['photo_id'],comment_id,digest,origin,utc_now()))
        return report

    def fetch_status(self,record,origin,status,count=None,message=None):
        with self.db:self.db.execute('INSERT INTO comment_fetches(photo_source,photo_id,origin,status,comment_count,message,fetched_at) VALUES(?,?,?,?,?,?,?)',
                    (record['source'],record['photo_id'],origin,status,count,message,utc_now()))

    def latest_fetch(self,record,origin='flickr_live'):
        row=self.db.execute('SELECT * FROM comment_fetches WHERE photo_source=? AND photo_id=? AND origin=? ORDER BY fetch_id DESC LIMIT 1',
                            (record['source'],record['photo_id'],origin)).fetchone()
        return dict(row) if row else None

    def evidence(self,record):
        # Live versions take precedence. Historical-only observations remain evidence,
        # never guessed deleted merely because absent from a subsequent API response.
        rows=self.db.execute('''SELECT v.*,o.origin,o.observed_at FROM comment_observations o JOIN comment_versions v
           USING(photo_id,comment_id,content_hash) WHERE o.photo_source=? AND o.photo_id=?
           ORDER BY CASE o.origin WHEN 'flickr_live' THEN 0 ELSE 1 END,o.observed_at DESC,v.content_hash''',
           (record['source'],record['photo_id'])).fetchall()
        unique={}
        for row in rows:unique.setdefault(row['comment_id'],dict(row))
        return list(unique.values())

    def cached(self,comment,analysis_version):
        row=self.db.execute('SELECT * FROM comment_sentiments WHERE photo_id=? AND comment_id=? AND content_hash=? AND analysis_version=?',
                            (comment['photo_id'],comment['comment_id'],comment['content_hash'],analysis_version)).fetchone()
        return dict(row) if row else None

    def save(self,comment,analysis_version,language,revision,result=None,status=None,runtime=None):
        if result:
            values=result['scores']
            if set(values)!={'positive','negative','neutral'} or not all(math.isfinite(v) and 0<=v<=1 for v in values.values()) or abs(sum(values.values())-1)>1e-4:
                raise ValueError('Invalid sentiment softmax scores')
            if result['label']!=max(values,key=values.get) or abs(result['confidence']-values[result['label']])>1e-6:
                raise ValueError('Inconsistent sentiment label/confidence')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO comment_sentiments VALUES('+','.join('?' for _ in range(18))+')',
                (comment['photo_id'],comment['comment_id'],comment['content_hash'],analysis_version,
                 language['language'],language['confidence'],language['status'],
                 result['label'] if result else None,result['confidence'] if result else None,json.dumps(result['scores']) if result else None,
                 status or ('analyzed' if result else language['status']),MODEL_ID,revision,PREPROCESS_VERSION,LANGUAGE_VERSION,
                 json.dumps(runtime or {}),int(result.get('truncated',False)) if result else 0,utc_now()))
