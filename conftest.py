"""Put the repo root on sys.path so `import radar` / `import server` work when pytest collects the
tests from tests/ (pytest's default import mode doesn't add the rootdir)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
