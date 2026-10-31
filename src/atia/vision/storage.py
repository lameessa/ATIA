import json
import math
from atia.models import utc_now


class AnalysisStore:
    def __init__(self, photo_store):
        self.db = photo_store.connection
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS visual_analyses (
                source TEXT NOT NULL, photo_id TEXT NOT NULL,
                model_name TEXT NOT NULL, pretrained TEXT NOT NULL,
                prompt_version TEXT NOT NULL, prompts TEXT NOT NULL,
                score_type TEXT NOT NULL, scores TEXT NOT NULL, top_categories TEXT NOT NULL,
                image_sha256 TEXT NOT NULL, image_url TEXT NOT NULL, image_path TEXT NOT NULL,
                width INTEGER NOT NULL, height INTEGER NOT NULL,
                library_version TEXT NOT NULL, device TEXT NOT NULL,
                analyzed_at TEXT NOT NULL, run_id TEXT NOT NULL,
                PRIMARY KEY(source,photo_id,model_name,pretrained,prompt_version),
                FOREIGN KEY(source,photo_id) REFERENCES photos(source,photo_id)
            );
            CREATE TABLE IF NOT EXISTS visual_attempts (
                attempt_id INTEGER PRIMARY KEY, run_id TEXT NOT NULL,
                source TEXT NOT NULL, photo_id TEXT NOT NULL,
                status TEXT NOT NULL, message TEXT, attempted_at TEXT NOT NULL,
                FOREIGN KEY(source,photo_id) REFERENCES photos(source,photo_id)
            );
        ''')
        self.db.commit()

    def candidates(self, model, max_candidates, source=None):
        # Stable ordering prioritizes currently collected live metadata. A successful
        # analysis is skipped for this exact model/checkpoint/prompt combination.
        query = '''SELECT p.* FROM photos p WHERE NOT EXISTS (
            SELECT 1 FROM visual_analyses a WHERE a.source=p.source AND a.photo_id=p.photo_id
            AND a.model_name=? AND a.pretrained=? AND a.prompt_version=?)'''
        params = [model.model_name, model.pretrained, model.prompt_version]
        if source:
            query += ' AND p.source=?'
            params.append(source)
        query += " ORDER BY CASE p.source WHEN 'flickr_live' THEN 0 ELSE 1 END, p.collected_at DESC, p.photo_id LIMIT ?"
        params.append(max_candidates)
        return [dict(row) for row in self.db.execute(query, params)]

    def attempt(self, run_id, record, status, message=None):
        with self.db:
            self.db.execute('INSERT INTO visual_attempts(run_id,source,photo_id,status,message,attempted_at) VALUES(?,?,?,?,?,?)',
                            (run_id, record['source'], record['photo_id'], status, message, utc_now()))

    def save(self, record, model, asset, scores, run_id):
        if set(scores) != set(model.prompts) or not all(math.isfinite(v) and -1.0001 <= v <= 1.0001 for v in scores.values()):
            raise ValueError('Invalid similarity scores')
        top = [{'category': key, 'similarity': value} for key, value in sorted(scores.items(), key=lambda item: item[1], reverse=True)[:3]]
        row = {
            'source': record['source'], 'photo_id': record['photo_id'],
            'model_name': model.model_name, 'pretrained': model.pretrained,
            'prompt_version': model.prompt_version, 'prompts': json.dumps(model.prompts),
            'score_type': 'cosine_similarity', 'scores': json.dumps(scores, allow_nan=False),
            'top_categories': json.dumps(top, allow_nan=False), 'image_sha256': asset.sha256,
            'image_url': asset.url, 'image_path': asset.path, 'width': asset.width, 'height': asset.height,
            'library_version': model.library_version, 'device': model.device,
            'analyzed_at': utc_now(), 'run_id': run_id,
        }
        with self.db:
            self.db.execute(f"INSERT INTO visual_analyses ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", list(row.values()))
        return top
