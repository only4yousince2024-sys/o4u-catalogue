"""Writes the reports. Everything printed or saved goes through redact() first. Nothing here reads a secret."""
from __future__ import annotations

import json
import re
from pathlib import Path

from lib import redact

HERE = Path(__file__).resolve().parent
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

PREFACE = """# O4U API error contract

What the website and Stockroom actually receive over HTTP when something goes wrong. **Generated** by `backend/api_tests/run_local_stack.py`
(the full suite, test D5 plus the observed limit cases of F1/F2) against PostgREST in front of the migrations 0001-0009 - do not edit by hand;
rerun the suite to refresh it. Values are the exact status / `code` / `message` / `details` / `hint` of the JSON error body. Random ids in
`details` are shown as `<uuid>`. Local PostgREST version and test run: see `backend/api_tests/README.md`. A hosted Supabase project runs PostgREST
too, so database-error bodies are expected to have the same shape - NOT yet verified on the hosted project; gateway-level errors (missing apikey,
platform limits) are not covered here.

## Rules for the front ends

1. **Branch on HTTP status and `code`, show `message` only where listed below.** `code` is the PostgreSQL SQLSTATE (`P0001`, `PT429`, `42501` ...)
   or a PostgREST `PGRSTnnn` code. `message` for `P0001` / `PT429` from the three public functions is written for people and is safe to show.
2. **Never show** `details`, `hint`, or any message from `22xxx`, `23xxx`, `25xxx`, `57xxx`, `42xxx` or `PGRST*`: they carry table, constraint and key
   names (`23505` details include internal ids and UPI references). Show a generic "something went wrong, please try again or WhatsApp us".
3. **`PT429` = HTTP 429 = a limit, not a fault.** Show its message, do not retry automatically, offer WhatsApp. (Before migration 0009 this arrived
   as HTTP 500 with code `P0429`.)
4. **A token problem (`PGRST301`, HTTP 401) breaks PUBLIC calls too.** PostgREST checks the Authorization header before anything else, so a stale
   staff token sent with `get_availability` or `place_order_request` is rejected. The website should send only the anon key; Stockroom should
   refresh the session and retry once, then ask the person to sign in again.
5. `401` + `42501` = not signed in (or token for the anon role); `403` + `42501` = signed in but not allowed (message says which rank is needed).
6. Unknown order reference and wrong phone number produce the **same** `order not found` response on purpose. Do not try to tell them apart.
7. Replaying a request with the same idempotency key returns the first answer (HTTP 200); it is never an error. Use a new key only for a new user action.
8. Statement timeouts (`57014`) arrive as HTTP 500: treat as "try again shortly", fall back to "Check availability".

"""


def clean(v):
    if v is None:
        return ""
    v = UUID.sub("<uuid>", str(v))
    v = re.sub(r"UPI[0-9a-f]{10}", "<upi-ref>", v)
    v = re.sub(r"upi[0-9a-f]{10}", "<upi-ref>", v)
    return v.replace("|", "\\|").replace("\n", " ")


def contract_md(contract: dict) -> str:
    out = [PREFACE]
    groups = [("rpc", "Our own functions (public website calls and staff actions)"), ("postgrest", "PostgREST / gateway-level errors")]
    for gid, title in groups:
        rows = [(k, v) for k, v in contract.items() if v.get("group", "rpc") == gid and v.get("status", 0) >= 400]
        if not rows:
            continue
        out.append(f"\n## {title}\n\n| Case | What happened | HTTP | `code` | `message` | `details` | `hint` | What the page should do |\n|---|---|---|---|---|---|---|---|")
        for k, v in rows:
            out.append(f"| {k} | {clean(v.get('desc', ''))} | {v['status']} | `{v['code']}` | {clean(v['message'])} | {clean(v['details'])} | {clean(v['hint'])} | {clean(v.get('site', ''))} |")
    ok = [(k, v) for k, v in contract.items() if v.get("status", 0) < 400]
    if ok:
        out.append("\n## Success responses recorded (for contrast)\n\n" + ", ".join(f"`{k}` → HTTP {v['status']}" for k, v in ok))
    return redact("\n".join(out) + "\n")


def write_local(res, tool, X, partial=False, name="local"):
    d = HERE / "reports"
    d.mkdir(exist_ok=True)
    (d / f"{name}_report.json").write_text(redact(json.dumps({"tool": tool, "results": res}, indent=1, default=str)), encoding="utf-8")
    n = {s: sum(1 for r in res if r["status"] == s) for s in ("PASS", "FAIL", "SKIP")}
    lines = [f"# Local API test run", "", f"{n['PASS']} passed, {n['FAIL']} failed, {n['SKIP']} skipped", "", "```", json.dumps(tool, indent=1), "```", "",
             "| id | result | test |", "|---|---|---|"]
    for r in res:
        lines.append(f"| {r['id']} | {r['status']} | {r['title']} |")
    for r in res:
        if r["status"] != "PASS" and r["detail"]:
            lines += ["", f"### {r['id']} {r['status']}", "```", r["detail"][:3000], "```"]
    lines += ["", "## Observations", ""]
    for r in res:
        for k, v in r["observations"]:
            lines += [f"**{r['id']} {k}**", "```json", json.dumps(v, indent=1, default=str)[:6000], "```", ""]
    (d / f"{name}_report.md").write_text(redact("\n".join(lines)), encoding="utf-8")
    if not partial and X.contract:
        (HERE / "ERROR_CONTRACT.md").write_text(contract_md(X.contract), encoding="utf-8")
