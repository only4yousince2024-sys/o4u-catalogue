"""Runs the registered tests against a Ctx and produces the PASS/FAIL/SKIP list and the report text (secrets redacted)."""
from __future__ import annotations

import json
import time
import traceback

from lib import TESTS, Fail, Skip, redact


def load_all():
    import tests_surface, tests_jwt, tests_formats, tests_cors, tests_abuse, tests_concurrency, tests_gotrue     # noqa: F401,E401,PLC0415


# with real GoTrue behind the tokens these existing checks are repeated (they only use the role names, never the invented ids)
GOTRUE_REUSE = {"A1", "A2", "A3", "A4", "A5", "A6", "A7", "B1", "B2", "B3", "B4", "B5", "C1", "C2", "C3", "D1", "D2", "D3", "D4", "D6", "F3", "G1", "G2"}


def run(X, profile: str, only: str | None = None, log=print) -> list[dict]:
    load_all()
    out = []
    for t in TESTS:
        if profile == "gotrue":
            if "gotrue" not in t["where"] and t["id"] not in GOTRUE_REUSE:
                continue
        elif profile not in t["where"]:
            continue
        if only and not any(o in t["id"] or o in t["title"].lower() for o in only.split(",")):
            continue
        X.obs = []
        t0 = time.time()
        status, detail = "PASS", ""
        try:
            t["fn"](X)
        except Skip as e:
            status, detail = "SKIP", str(e)
        except Fail as e:
            status, detail = "FAIL", str(e)
        except Exception as e:      # noqa: BLE001
            status, detail = "FAIL", f"{type(e).__name__}: {e}"
            if profile == "local":
                detail += "\n" + traceback.format_exc(limit=4)
        detail = redact(detail)
        res = {"id": t["id"], "area": t["area"], "title": t["title"], "status": status, "detail": detail, "seconds": round(time.time() - t0, 1),
               "observations": [(k, json.loads(redact(json.dumps(v, default=str)))) for k, v in X.obs]}
        out.append(res)
        log(f"  {status:4}  {t['id']:4} {t['title']}" + (f"\n          {detail.splitlines()[0][:300]}" if detail and status != "PASS" else ""))
    return out


def summary(results: list[dict]) -> str:
    n = {s: sum(1 for r in results if r["status"] == s) for s in ("PASS", "FAIL", "SKIP")}
    return f"{n['PASS']} passed, {n['FAIL']} failed, {n['SKIP']} skipped"
