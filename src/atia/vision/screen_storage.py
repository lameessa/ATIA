import json
import sqlite3
from atia.models import utc_now
from atia.vision.dimensions import fingerprint
from atia.vision.relevance_prompts import SCREEN_VERSION,DETAIL_VERSION,POLICY_VERSION,POLICY,RELEVANCE,DETAILS


class ScreeningStore:
    def __init__(self, store):
        self.db=store.connection
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS review_samples (
          sample_id TEXT PRIMARY KEY, seed TEXT NOT NULL, protocol TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS review_sample_members (
          sample_id TEXT NOT NULL, source TEXT NOT NULL, photo_id TEXT NOT NULL,
          region TEXT NOT NULL, region_basis TEXT NOT NULL, stratum TEXT NOT NULL,
          image_sha256 TEXT, image_path TEXT, image_url TEXT, width INTEGER, height INTEGER,
          status TEXT NOT NULL, error TEXT, ordinal INTEGER NOT NULL,
          PRIMARY KEY(sample_id,source,photo_id),
          FOREIGN KEY(sample_id) REFERENCES review_samples(sample_id),
          FOREIGN KEY(source,photo_id) REFERENCES photos(source,photo_id));
        CREATE TABLE IF NOT EXISTS image_embeddings (
          image_sha256 TEXT NOT NULL, model_key TEXT NOT NULL, model_spec TEXT NOT NULL,
          dimensions INTEGER NOT NULL, vector BLOB NOT NULL, created_at TEXT NOT NULL,
          PRIMARY KEY(image_sha256,model_key));
        CREATE TABLE IF NOT EXISTS tourism_relevance (
          source TEXT NOT NULL, photo_id TEXT NOT NULL, image_sha256 TEXT NOT NULL,
          model_key TEXT NOT NULL, model_spec TEXT NOT NULL,
          screen_version TEXT NOT NULL, detail_version TEXT NOT NULL, policy_version TEXT NOT NULL,
          policy TEXT NOT NULL, relevance_prompts TEXT NOT NULL, detail_prompts TEXT NOT NULL,
          decision TEXT NOT NULL, destination_status TEXT NOT NULL,
          screen_result TEXT NOT NULL, detail_result TEXT,
          image_path TEXT NOT NULL, image_url TEXT NOT NULL, analyzed_at TEXT NOT NULL,
          PRIMARY KEY(source,photo_id,image_sha256,model_key,screen_version,detail_version,policy_version),
          FOREIGN KEY(source,photo_id) REFERENCES photos(source,photo_id));
        CREATE TABLE IF NOT EXISTS destination_dimension_analyses (
          source TEXT NOT NULL, photo_id TEXT NOT NULL, image_sha256 TEXT NOT NULL,
          model_key TEXT NOT NULL, screen_version TEXT NOT NULL, detail_version TEXT NOT NULL, policy_version TEXT NOT NULL,
          dimension TEXT NOT NULL, result TEXT NOT NULL, prompts TEXT NOT NULL, model_spec TEXT NOT NULL,
          PRIMARY KEY(source,photo_id,image_sha256,model_key,screen_version,detail_version,policy_version,dimension),
          FOREIGN KEY(source,photo_id,image_sha256,model_key,screen_version,detail_version,policy_version)
            REFERENCES tourism_relevance(source,photo_id,image_sha256,model_key,screen_version,detail_version,policy_version));
        CREATE TABLE IF NOT EXISTS visual_review_labels (
          sample_id TEXT NOT NULL, source TEXT NOT NULL, photo_id TEXT NOT NULL,
          image_sha256 TEXT NOT NULL, label TEXT NOT NULL CHECK(label IN ('relevant','irrelevant','uncertain')),
          reviewer TEXT NOT NULL, review_type TEXT NOT NULL, reason TEXT NOT NULL, reviewed_at TEXT NOT NULL,
          PRIMARY KEY(sample_id,source,photo_id,reviewer),
          FOREIGN KEY(sample_id,source,photo_id) REFERENCES review_sample_members(sample_id,source,photo_id));
        ''')
        self.db.commit()
        # Materialize separately addressable dimensions from existing cached results;
        # no inference or updates to the earlier analysis tables are required.
        with self.db:
            for row in self.db.execute("SELECT * FROM tourism_relevance WHERE decision='relevant' AND detail_result IS NOT NULL").fetchall():
                self._dimensions(dict(row),json.loads(row['detail_result']))

    def _dimensions(self,row,details):
        saved_definitions=json.loads(row['detail_prompts']) if row.get('detail_prompts') else DETAILS
        for dimension in ('environment','elements','conditions'):
            definition = {'positive_and_alternative_prompts':saved_definitions[dimension],
                          'controls':saved_definitions['controls']}
            keys=('source','photo_id','image_sha256','model_key','screen_version','detail_version','policy_version')
            self.db.execute('INSERT OR IGNORE INTO destination_dimension_analyses VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (*[row[key] for key in keys],dimension,json.dumps(details[dimension],allow_nan=False),
                 json.dumps(definition),row['model_spec']))

    def members(self,sample_id):
        return [dict(row) for row in self.db.execute('SELECT m.*,p.photo_url FROM review_sample_members m JOIN photos p USING(source,photo_id) WHERE sample_id=? ORDER BY ordinal',(sample_id,))]

    def embedding(self,sha,key):
        row=self.db.execute('SELECT * FROM image_embeddings WHERE image_sha256=? AND model_key=?',(sha,key)).fetchone()
        if row is None:return None
        import numpy as np
        vector=np.frombuffer(row['vector'],dtype='<f4').copy()
        if vector.size!=row['dimensions'] or not np.isfinite(vector).all() or abs(float(np.linalg.norm(vector))-1)>0.01:
            raise ValueError('Invalid cached image embedding')
        return vector

    def save_embedding(self,sha,spec,vector):
        import numpy as np
        vector=np.asarray(vector,dtype='<f4')
        if vector.ndim!=1 or not np.isfinite(vector).all() or abs(float(np.linalg.norm(vector))-1)>0.01:
            raise ValueError('Expected normalized image embedding')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO image_embeddings VALUES(?,?,?,?,?,?)',
                (sha,fingerprint(spec),json.dumps(spec,sort_keys=True),vector.size,sqlite3.Binary(vector.tobytes()),utc_now()))

    def cached(self,record,key):
        row=self.db.execute('''SELECT * FROM tourism_relevance WHERE source=? AND photo_id=? AND image_sha256=? AND model_key=?
            AND screen_version=? AND detail_version=? AND policy_version=?''',
            (record['source'],record['photo_id'],record['image_sha256'],key,SCREEN_VERSION,DETAIL_VERSION,POLICY_VERSION)).fetchone()
        return dict(row) if row else None

    def save(self,record,spec,screen,details):
        if (screen['decision']=='relevant') != (details is not None):
            raise ValueError('Only eligible images must have complete destination classification')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO tourism_relevance VALUES('+','.join('?' for _ in range(18))+')',
              (record['source'],record['photo_id'],record['image_sha256'],fingerprint(spec),json.dumps(spec,sort_keys=True),
               SCREEN_VERSION,DETAIL_VERSION,POLICY_VERSION,json.dumps(POLICY),json.dumps(RELEVANCE),json.dumps(DETAILS),
               screen['decision'],screen['destination_status'],json.dumps(screen,allow_nan=False),
               json.dumps(details,allow_nan=False) if details is not None else None,record['image_path'],record['image_url'],utc_now()))
            if details is not None:
                row={'source':record['source'],'photo_id':record['photo_id'],'image_sha256':record['image_sha256'],
                     'model_key':fingerprint(spec),'screen_version':SCREEN_VERSION,'detail_version':DETAIL_VERSION,
                     'policy_version':POLICY_VERSION,'model_spec':json.dumps(spec,sort_keys=True)}
                self._dimensions(row,details)
