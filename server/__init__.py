"""Multi-tenant web platform (v1): Google auth, per-user DB, React SPA API."""
# Load a local .env into the process environment BEFORE any submodule reads os.environ
# (auth.py, db.py, etc. read config at import time). In production the container already has
# env injected (docker-compose env_file) and there's no .env file — load_dotenv is a no-op there,
# and it never overrides variables already set.
from pathlib import Path as _Path

try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(_Path(__file__).resolve().parent.parent / '.env')
except Exception:
    pass
