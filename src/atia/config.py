import os
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    api_key: str
    db_path: str

    @classmethod
    def load(cls):
        load_dotenv()
        return cls(os.getenv("FLICKR_API_KEY", "").strip(),
                   os.getenv("ATIA_DB_PATH", "data/atia.sqlite3"))
