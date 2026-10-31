import json
from dataclasses import asdict
from atia.models import utc_now
from atia.vision.dimensions import DIMENSION_PROMPTS, DIMENSION_PROMPT_VERSION, interpret
from atia.vision.dimensional_model import DimensionalAnalyzer


class DimensionStore:
    def __init__(self, photo_store):
        self.db = photo_store.connection
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS visual_dimension_analyses (
                source TEXT NOT NULL, photo_id TEXT NOT NULL, dimension TEXT NOT NULL,
                model_name TEXT NOT NULL, pretrained TEXT NOT NULL, library_version TEXT NOT NULL,
                prompt_version TEXT NOT NULL, prompts TEXT NOT NULL,
                threshold_version TEXT NOT NULL, thresholds TEXT NOT NULL,
                scores TEXT NOT NULL, interpretation TEXT NOT NULL,
                score_type TEXT NOT NULL, image_sha256 TEXT NOT NULL,
                image_url TEXT NOT NULL, image_path TEXT NOT NULL,
                width INTEGER NOT NULL, height INTEGER NOT NULL, device TEXT NOT NULL,
                analyzed_at TEXT NOT NULL, run_id TEXT NOT NULL,
                PRIMARY KEY(source,photo_id,dimension,model_name,pretrained,prompt_version,threshold_version),
                FOREIGN KEY(source,photo_id) REFERENCES photos(source,photo_id)
            );
        ''')
        self.db.commit()

    def candidates(self, maximum, source=None):
        query = 'SELECT * FROM photos'
        params = []
        if source:
            query += ' WHERE source=?'
            params.append(source)
        query += " ORDER BY CASE source WHEN 'flickr_live' THEN 0 ELSE 1 END,collected_at DESC,photo_id LIMIT ?"
        params.append(maximum)
        return [dict(row) for row in self.db.execute(query, params)]

    def cached(self, record, thresholds=None):
        query = '''SELECT * FROM visual_dimension_analyses WHERE source=? AND photo_id=?
                   AND model_name=? AND pretrained=? AND prompt_version=?'''
        params = [record['source'], record['photo_id'], DimensionalAnalyzer.model_name,
                  DimensionalAnalyzer.pretrained, DIMENSION_PROMPT_VERSION]
        if thresholds:
            query += ' AND threshold_version=?'
            params.append(thresholds.version)
        query += ' ORDER BY analyzed_at DESC'
        rows = list(self.db.execute(query, params))
        if not rows:
            return None
        # Never mix snapshots from different images or configurations.
        first = rows[0]
        rows = [row for row in rows if row['image_sha256'] == first['image_sha256'] and row['threshold_version'] == first['threshold_version']]
        if {row['dimension'] for row in rows} != set(DIMENSION_PROMPTS):
            return None
        return {row['dimension']: dict(row) for row in rows}

    def save(self, record, metadata, scores, thresholds, run_id):
        if set(scores) != set(DIMENSION_PROMPTS):
            raise ValueError('Expected all three dimensions')
        interpreted = {dimension: interpret(dimension, values, thresholds) for dimension, values in scores.items()}
        # Three dimensions are committed together. Historical/legacy analyses and
        # capture timestamps remain untouched.
        with self.db:
            for dimension in DIMENSION_PROMPTS:
                row = {**metadata, 'source': record['source'], 'photo_id': record['photo_id'],
                       'dimension': dimension, 'model_name': DimensionalAnalyzer.model_name,
                       'pretrained': DimensionalAnalyzer.pretrained,
                       'prompt_version': DIMENSION_PROMPT_VERSION,
                       'prompts': json.dumps(DIMENSION_PROMPTS[dimension]),
                       'threshold_version': thresholds.version, 'thresholds': json.dumps(asdict(thresholds)),
                       'scores': json.dumps(scores[dimension], allow_nan=False),
                       'interpretation': json.dumps(interpreted[dimension], allow_nan=False),
                       'score_type': 'cosine_similarity', 'analyzed_at': utc_now(), 'run_id': run_id}
                self.db.execute(f"INSERT OR IGNORE INTO visual_dimension_analyses ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", list(row.values()))
        return interpreted


def asset_metadata(asset, model):
    return {'library_version': model.library_version, 'device': model.device,
            'image_sha256': asset.sha256, 'image_url': asset.url, 'image_path': asset.path,
            'width': asset.width, 'height': asset.height}


def cached_metadata(rows):
    row = next(iter(rows.values()))
    return {key: row[key] for key in ('library_version','device','image_sha256','image_url','image_path','width','height')}
