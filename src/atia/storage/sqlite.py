import json
from pathlib import Path
import sqlite3
from atia.models import Photo


class PhotoStore:
    """One row per (source, photo ID); repeated imports never inflate counts."""

    def __init__(self, path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("""CREATE TABLE IF NOT EXISTS photos (
            source TEXT NOT NULL, photo_id TEXT NOT NULL,
            title TEXT NOT NULL, latitude REAL, longitude REAL,
            uploaded_at TEXT, captured_at TEXT, capture_granularity TEXT,
            capture_unknown INTEGER, views INTEGER, tags TEXT NOT NULL,
            license_id TEXT, license_name TEXT, license_url TEXT,
            owner_id TEXT, photo_url TEXT, collected_at TEXT NOT NULL,
            raw TEXT NOT NULL, PRIMARY KEY(source, photo_id))""")
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(photos)")}
        if "region" not in columns:
            self.connection.execute("ALTER TABLE photos ADD COLUMN region TEXT")
        self.connection.commit()
        from atia.moderation.policy import initialize
        initialize(self.connection)

    def save(self, photo: Photo):
        if photo.source=='flickr_live' and self.connection.execute('SELECT 1 FROM photo_removal_audit WHERE photo_id=?',(photo.photo_id,)).fetchone():
            return False
        record = photo.to_dict()
        record["tags"] = json.dumps(record["tags"], ensure_ascii=False)
        record["raw"] = json.dumps(record["raw"], ensure_ascii=False)
        columns = list(record)
        with self.connection:
            cursor = self.connection.execute(
                f"INSERT OR IGNORE INTO photos ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                list(record.values()))
            if photo.source=='flickr_live':
                from atia.models import utc_now
                self.connection.execute("INSERT OR IGNORE INTO photo_moderation(photo_id,status,quarantined_at) VALUES(?,'quarantined',?)",(photo.photo_id,utc_now()))
        return cursor.rowcount == 1

    def contains(self, source, photo_id):
        return self.connection.execute("SELECT 1 FROM photos WHERE source=? AND photo_id=?", (source, photo_id)).fetchone() is not None

    def contains_any(self, photo_id):
        return bool(self.connection.execute("SELECT 1 FROM photos WHERE photo_id=? UNION ALL SELECT 1 FROM photo_removal_audit WHERE photo_id=? LIMIT 1", (photo_id,photo_id)).fetchone())

    def counts(self):
        return dict(self.connection.execute("SELECT source, COUNT(*) FROM photos GROUP BY source").fetchall())

    def list_photos(self, limit=50, source=None):
        query = "SELECT * FROM photos"
        params = []
        if source:
            query += " WHERE source=?"
            params.append(source)
        query += " ORDER BY collected_at DESC, photo_id LIMIT ?"
        params.append(limit)
        records = [dict(row) for row in self.connection.execute(query, params)]
        for record in records:
            record["tags"] = json.loads(record["tags"])
            record["raw"] = json.loads(record["raw"])
        return records

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
