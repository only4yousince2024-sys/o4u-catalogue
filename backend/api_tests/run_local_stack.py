"""Local real-HTTP API tests: throwaway PostgreSQL + the official PostgREST binary + a throwaway HS256 secret, invented data only.

    python3 backend/api_tests/run_local_stack.py                 # full suite (about a minute or two)
    O4U_POSTGREST=/path/to/postgrest python3 backend/api_tests/run_local_stack.py --only A,B
    python3 backend/api_tests/run_local_stack.py --without-0009  # prove which checks fail on the migrations as they were (0001-0008)

Needs: Python 3.10+, `pip install "psycopg[binary]"`, an OS PostgreSQL (see backend/README.md) and the PostgREST release binary.
Writes backend/api_tests/reports/local_report.md/.json (git-ignored) and, when the whole suite ran, ERROR_CONTRACT.md.
Nothing here contacts Supabase or any other host.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from ctx import MANAGER, OWNER, STAFF, STRANGER, Ctx      # noqa: E402
from lib import anon_claims, mint, register_secret, user_claims      # noqa: E402
import runner      # noqa: E402
import stack      # noqa: E402
import psycopg      # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated test ids or title words, e.g. A,B3,jwt")
    ap.add_argument("--without-0009", action="store_true", help="apply only migrations 0001-0008 (to show what 0009 fixes)")
    ap.add_argument("--write-contract", action="store_true", help="rewrite ERROR_CONTRACT.md even for a partial run")
    ap.add_argument("--gotrue", action="store_true", help="run the 'gotrue' profile: REAL GoTrue (O4U_GOTRUE=/path/to/gotrue) issues the tokens; repeats the role/JWT/format checks and adds R1-R7")
    ap.add_argument("--pgrst-conf", action="append", default=[], metavar="KEY=VALUE", help="extra PostgREST setting, e.g. jwt-aud=authenticated")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    migs = [m for m in stack.MIGRATIONS if not (a.without_0009 and m.name.startswith("0009"))]
    extra = dict(x.split("=", 1) for x in a.pgrst_conf)
    st = stack.LocalStack(extra_pgrst=extra, gotrue=a.gotrue)
    rc = 1
    try:
        st.prepare_db(migrations=migs)
        st.start_postgrest()
        if a.gotrue:
            st.start_gotrue()
        tool = {"postgresql": st.version(), "postgrest": st.postgrest_version(), "python": sys.version.split()[0], "psycopg": psycopg.__version__,
                "migrations": [m.name for m in migs], "target": "LOCAL stack: PostgREST in front of a throwaway PostgreSQL (not Supabase's gateway)" + (" + REAL GoTrue " + st.gotrue_version() if a.gotrue else ", tokens minted locally (no GoTrue)")}
        print(json.dumps(tool, indent=1))
        sec = st.secret
        register_secret(sec)
        anon = mint(sec, anon_claims())
        db = psycopg.connect(st.db_uri, autocommit=True)
        if a.gotrue:
            from lib import request      # noqa: PLC0415
            admin = mint(sec, {"role": "service_role", "iss": "supabase-demo", "iat": int(time.time()), "exp": int(time.time()) + 6 * 3600})
            toks, uids = {}, {}
            for role in ("owner", "manager", "staff", "stranger"):
                h = {"apikey": anon, "Content-Type": "application/json"}
                c = request("POST", st.auth_base + "/admin/users", dict(h, Authorization="Bearer " + admin),
                            json.dumps({"email": f"{role}@example.invalid", "password": f"invented-pass-{role}", "email_confirm": True}))
                if c.status != 200:
                    raise SystemExit(f"GoTrue admin create user failed: {c.status} {c.text[:200]}")
                uids[role] = c.json["id"]
                t = request("POST", st.auth_base + "/token?grant_type=password", h, json.dumps({"email": f"{role}@example.invalid", "password": f"invented-pass-{role}"}))
                toks[role] = t.json["access_token"]
            X = Ctx(local=True, rest=st.base, anon_key=anon, tokens=toks, db=db, secret=sec, stack=st, real_auth=True, uids=uids, auth_base=st.auth_base, admin_token=admin)
        else:
            toks = {r: mint(sec, user_claims(u)) for r, u in (("owner", OWNER), ("manager", MANAGER), ("staff", STAFF), ("stranger", STRANGER))}
            X = Ctx(local=True, rest=st.base, anon_key=anon, tokens=toks, db=db, secret=sec, stack=st)
        t0 = time.time()
        res = runner.run(X, "gotrue" if a.gotrue else "local", a.only)
        print(f"\n{runner.summary(res)} in {time.time() - t0:.1f}s")
        import os
        if os.environ.get('O4U_DUMP'):
            json.dump(X.contract, open(os.environ['O4U_DUMP'], 'w'), indent=1)
        import report      # noqa: PLC0415
        report.write_local(res, tool, X, partial=(bool(a.only) and not a.write_contract) or a.without_0009 or a.gotrue, name="gotrue" if a.gotrue else "local")
        rc = 0 if all(r["status"] != "FAIL" for r in res) and res else 1
    finally:
        st.stop()
    return rc


if __name__ == "__main__":
    sys.exit(main())
