"""Hosted DEVELOPMENT project: reduced, non-destructive API checks. The OWNER runs this on their own computer.

    set O4U_API_URL=https://<your-dev-project>.supabase.co            (Windows: set / PowerShell: $env:O4U_API_URL="...")
    set O4U_ANON_KEY=<the project's PUBLIC anon / publishable key>
    python backend/api_tests/run_hosted.py                            # asks for sign-in e-mails and passwords (hidden)
    python backend/api_tests/run_hosted.py --interactive-ban          # also checks "banned user's token stops working"

What it does:  reads the URL and the PUBLIC key from environment variables; asks for the passwords at run time with a hidden prompt;
               signs in with Supabase Auth (the same call the apps make) and keeps the tokens ONLY in memory; runs the checks that are
               read-only or always refused; writes ONE report with PASS/FAIL lines and no keys, tokens, passwords, e-mail addresses or URL.
What it never does: read a secret from a file or argument, print or log a key or token, use the service-role key (it never asks for it),
               write to the database (every call is a read, or a call that is refused or fails validation and rolls back), or run against
               a database that does not look like the development project (it first asks `get_availability` and refuses unless it lists
               at least one product and EVERY product id starts with `dev-`).
Needs only Python 3.10+ (standard library).
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from ctx import Ctx      # noqa: E402
from lib import Fail, TESTS, register_secret, redact, request      # noqa: E402
import runner      # noqa: E402

ROLE_RANK = {"owner": 3, "manager": 2, "staff": 1, "stranger": None}
ROLE_PROMPT = {"owner": "OWNER (rank 3)", "manager": "MANAGER (rank 2)", "staff": "STAFF (rank 1)",
               "stranger": "a signed-in account that is NOT on the staff list (optional; press Enter to skip)"}


def gate(rest: str, anon_key: str) -> list[str]:
    """Refuse unless this is the development project: products exist and every id starts with dev-."""
    r = request("POST", rest + "/rpc/get_availability", {"apikey": anon_key, "Authorization": "Bearer " + anon_key, "Content-Type": "application/json"}, "{}", 30)
    if r.status != 200 or not isinstance(r.json, list):
        raise SystemExit(f"REFUSED: could not read get_availability (HTTP {r.status}). Check O4U_API_URL and O4U_ANON_KEY (the PUBLIC key).")
    ids = sorted({row["product_id"] for row in r.json})
    if not ids:
        raise SystemExit("REFUSED: the database lists no products, so it cannot be recognised as the development project.")
    notdev = [i for i in ids if not i.startswith("dev-")]
    if notdev:
        raise SystemExit(f"REFUSED: {len(notdev)} of {len(ids)} product ids do not start with 'dev-'. This does not look like the development project. Nothing was run.")
    return ids


def sign_in(base: str, anon_key: str, email: str, password: str):
    r = request("POST", base + "/auth/v1/token?grant_type=password", {"apikey": anon_key, "Content-Type": "application/json"},
                json.dumps({"email": email, "password": password}), 30)
    if r.status != 200 or not isinstance(r.json, dict) or "access_token" not in r.json:
        return None, r.status
    return r.json["access_token"], 200


def collect_accounts(base, anon_key, ask_email, ask_password, log) -> dict:
    tokens = {}
    for role in ("owner", "manager", "staff", "stranger"):
        email = ask_email(f"E-mail of the {ROLE_PROMPT[role]}: ").strip()
        if not email:
            log(f"  {role}: skipped")
            continue
        pw = ask_password(f"Password for that account (hidden, never stored): ")
        register_secret(pw)
        register_secret(email)
        tok, status = sign_in(base, anon_key, email, pw)
        del pw
        if not tok:
            log(f"  {role}: sign-in failed (HTTP {status}); this role will be skipped")
            continue
        register_secret(tok)
        tokens[role] = tok
        log(f"  {role}: signed in")
    return tokens


def check_roles(X: Ctx, log):
    """Each account must really have the rank the prompt said, or the matrix would blame the wrong thing."""
    for role in list(X.tokens):
        r = X.rpc("current_role_rank", {}, role)
        got = r.json if r.status == 200 else "error"
        if got != ROLE_RANK[role]:
            log(f"  {role}: this account has rank {got!r}, not {ROLE_RANK[role]!r}; skipping it so results are not misleading")
            del X.tokens[role]


def interactive_ban(X: Ctx, ask_enter, log) -> list[dict]:
    """A token that is still valid must stop working at once when the account is banned in the dashboard. The owner does the clicking."""
    out = []
    if "staff" not in X.tokens:
        return [{"id": "C6h", "area": "C JWT handling", "title": "Banned account's token stops working", "status": "SKIP", "detail": "needs a signed-in STAFF account", "seconds": 0, "observations": []}]

    def probe():
        r = X.rpc("current_role_rank", {}, "staff")
        c = X.rpc("confirm_and_reserve", {"p_idem_key": X.key(), "p_order": "00000000-0000-0000-0000-000000000000", "p_delivery_paise": 1, "p_discount_paise": 0}, "staff")
        return r, c

    def add(status, detail):
        out.append({"id": "C6h", "area": "C JWT handling", "title": "Banned/unbanned STAFF account: the SAME token loses and regains access at once", "status": status,
                    "detail": detail, "seconds": 0, "observations": []})
    r, c = probe()
    if r.json != 1:
        add("FAIL", f"baseline: staff account should have rank 1, got {r.err() if r.status >= 400 else r.json}")
        return out
    ask_enter("In the Supabase dashboard: Authentication > Users > the STAFF test user > ... > Ban user (24 hours). Press Enter when it says banned: ")
    time.sleep(2)
    r, c = probe()
    banned_ok = r.status == 200 and r.json is None and c.status == 403 and c.code == "42501"
    ask_enter("Now Unban that user in the dashboard. Press Enter when done: ")
    time.sleep(2)
    r2, c2 = probe()
    restored = r2.status == 200 and r2.json == 1
    if banned_ok and restored:
        add("PASS", "while banned the old token had no rank and staff functions answered 403; after the unban it worked again")
    else:
        add("FAIL", f"banned: rank={r.json if r.status == 200 else r.status}, confirm={c.status}/{c.code}; after unban rank={r2.json if r2.status == 200 else r2.status}")
    return out


def write_report(path: Path, results, meta):
    n = {s: sum(1 for r in results if r["status"] == s) for s in ("PASS", "FAIL", "SKIP")}
    L = ["# Hosted development project - API check report", "", f"Run at {meta['when']} UTC. Roles signed in: {', '.join(meta['roles']) or 'none'}. "
         f"{len(meta['dev_products'])} dev- products seen.", "", f"**{n['PASS']} PASS, {n['FAIL']} FAIL, {n['SKIP']} SKIP**", "",
         "No keys, tokens, passwords, e-mail addresses or project URL are in this file.", "", "| id | result | check |", "|---|---|---|"]
    for r in results:
        L.append(f"| {r['id']} | {r['status']} | {r['title']} |")
    for r in results:
        if r["status"] != "PASS" and r["detail"]:
            L += ["", f"### {r['id']} {r['status']}", "```", r["detail"][:1200], "```"]
    cors = [(k, v) for r in results if r["id"] in ("E1", "E2", "A8") for k, v in r["observations"]]
    if cors:
        L += ["", "## Gateway answers worth keeping (CORS and apikey)", "```json", json.dumps(dict(cors), indent=1)[:12000], "```"]
    path.write_text(redact("\n".join(L) + "\n"), encoding="utf-8")


def run(url, anon_key, *, ask_email, ask_password, ask_enter, out_dir: Path, ban=False, site_origin=None, log=print) -> int:
    base = url.rstrip("/")
    u = urllib.parse.urlsplit(base)
    if u.scheme != "https" and u.hostname not in ("127.0.0.1", "localhost"):
        raise SystemExit("REFUSED: O4U_API_URL must start with https://")
    register_secret(anon_key)
    register_secret(u.hostname)
    register_secret(u.hostname.split(".")[0] if u.hostname else None)
    rest = base + "/rest/v1"
    log("Checking that this is the development project ...")
    ids = gate(rest, anon_key)
    log(f"  OK: {len(ids)} products, all ids start with 'dev-'.")
    log("Sign-in (passwords are typed hidden and kept in memory only):")
    tokens = collect_accounts(base, anon_key, ask_email, ask_password, log)
    X = Ctx(local=False, rest=rest, anon_key=anon_key, tokens=tokens)
    check_roles(X, log)
    if site_origin:
        os.environ["O4U_SITE_ORIGIN"] = site_origin
    log(f"Running the hosted profile with: {', '.join(X.tokens) or 'no signed-in roles'} ...")
    results = runner.run(X, "hosted", log=log)
    if ban:
        results += interactive_ban(X, ask_enter, log)
        for r in results[-1:]:
            log(f"  {r['status']:4}  {r['id']:4} {r['title']}")
    out_dir.mkdir(exist_ok=True)
    meta = {"when": time.strftime("%Y-%m-%d %H:%M", time.gmtime()), "roles": list(X.tokens), "dev_products": ids}
    report = out_dir / "hosted_report.md"
    write_report(report, results, meta)
    n = {s: sum(1 for r in results if r["status"] == s) for s in ("PASS", "FAIL", "SKIP")}
    log(f"\n{n['PASS']} PASS, {n['FAIL']} FAIL, {n['SKIP']} SKIP. Report written to {report}")
    log("You can send that file to Claude: it contains no secrets.")
    return 1 if n["FAIL"] else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--interactive-ban", action="store_true", help="also test that a banned user's token stops working (you click Ban/Unban in the dashboard)")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    url, key = os.environ.get("O4U_API_URL", "").strip(), os.environ.get("O4U_ANON_KEY", "").strip()
    if not url or not key:
        print("Set O4U_API_URL (https://<project>.supabase.co) and O4U_ANON_KEY (the PUBLIC anon/publishable key) first. Never the service-role key.")
        return 2
    if key.startswith("sb_secret_"):
        print("REFUSED: that looks like a SECRET key. Use the public anon / publishable key. Nothing was run.")
        return 2
    try:
        import base64
        parts = key.split(".")
        if len(parts) == 3:
            role = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))).get("role")
            if role != "anon":
                print(f"REFUSED: this key has role '{role}', not 'anon'. Nothing was run.")
                return 2
    except Exception:      # noqa: BLE001 - not a JWT-shaped key (new publishable keys): fine
        pass
    return run(url, key, ask_email=input, ask_password=getpass.getpass, ask_enter=lambda m: input(m), out_dir=HERE / "reports",
               ban=a.interactive_ban, site_origin=os.environ.get("O4U_SITE_ORIGIN") or None)


if __name__ == "__main__":
    sys.exit(main())
