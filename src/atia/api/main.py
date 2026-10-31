"""Run locally: uvicorn atia.api.main:app --host 127.0.0.1 --port 8000."""
from .dashboard import create_app

app=create_app()
