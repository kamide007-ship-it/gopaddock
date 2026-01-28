"""Go Paddock preflight (local sanity check)
Run: python scripts/preflight.py
"""
import os
import sys
from pathlib import Path

# add project root to sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app import create_app  # noqa

app = create_app()
endpoints = sorted({r.endpoint for r in app.url_map.iter_rules()})

required = ["login", "register", "healthz", "version"]
missing = [e for e in required if e not in endpoints]

print("APP OK. endpoints:", len(endpoints))
print("Missing required endpoints:", missing)

# ensure url building works
from flask import url_for
with app.test_request_context("/"):
    for ep in ["login", "register"]:
        print(ep, url_for(ep))
print("preflight done")
