"""Real-browser CORS check against the LOCAL stack: starts PostgREST on a throwaway database and drives browser_cors_check.html in Chromium
(Playwright) from a different origin. Local PostgREST's CORS only - NOT Supabase's gateway. Needs node + Playwright (`npm i playwright`) and
a Chromium; the owner's hosted check is the same page opened by hand (README).

    python3 backend/api_tests/local_browser_check.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import psycopg      # noqa: E402

import stack      # noqa: E402
from lib import anon_claims, mint      # noqa: E402

import os
# O4U_CORS_ORIGINS=https://x.example makes local PostgREST refuse other origins - used to prove this page can show BLOCKED
st = stack.LocalStack(extra_pgrst={"server-cors-allowed-origins": os.environ["O4U_CORS_ORIGINS"]} if os.environ.get("O4U_CORS_ORIGINS") else None)
try:
    st.prepare_db()
    st.start_postgrest()
    key = mint(st.secret, anon_claims())          # throwaway key for this run only
    r = subprocess.run(["node", str(HERE / "run_browser_check.js"), st.base, key, ""], capture_output=True, text=True, timeout=180)
    print(r.stdout.replace(key, "[anon-key]"))
    print(r.stderr[-1500:].replace(key, "[anon-key]"))
    rc = r.returncode
finally:
    st.stop()
sys.exit(rc)
