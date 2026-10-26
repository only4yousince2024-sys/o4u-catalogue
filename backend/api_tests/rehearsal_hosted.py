"""Dress rehearsal for run_hosted.py: runs it for real, but against a LOCAL FAKE of a hosted project.

The fake gateway listens on 127.0.0.1, serves /rest/v1/* by forwarding to the local PostgREST (and refuses requests without an apikey header,
as Supabase's gateway does) and /auth/v1/token?grant_type=password by checking invented passwords and returning a token minted with the
throwaway secret. It proves run_hosted.py's own logic (the dev- gate, sign-in, role checks, report with no secrets). It proves NOTHING about
the real Supabase gateway, Auth or CORS.

    python3 backend/api_tests/rehearsal_hosted.py            # gate passes (dev- ids) and the hosted profile runs
    python3 backend/api_tests/rehearsal_hosted.py --not-dev  # the gate must refuse (non dev- ids)
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import psycopg      # noqa: E402

import run_hosted      # noqa: E402
import stack      # noqa: E402
from ctx import MANAGER, OWNER, STAFF, STRANGER      # noqa: E402
from lib import anon_claims, mint, request, user_claims      # noqa: E402

PASSWORDS = {"owner@example.invalid": ("invented-pass-1", OWNER), "manager@example.invalid": ("invented-pass-2", MANAGER),
             "staff@example.invalid": ("invented-pass-3", STAFF), "stranger@example.invalid": ("invented-pass-4", STRANGER)}


def seed(db, prefix):
    db.execute("""truncate sale_lines, sales, payments, refunds, payment_reports, order_events, order_lines, orders, stock_events,
                  idempotency, stock_levels, variants, products, staff, auth.users, store_outages, expiry_failures restart identity cascade""")
    for em, (_, uid) in PASSWORDS.items():
        db.execute("insert into auth.users (id, email) values (%s, %s)", (uid, em))
    db.execute("insert into staff values (%s,'Rehearsal owner','owner'), (%s,'Rehearsal manager','manager'), (%s,'Rehearsal staff','staff')", (OWNER, MANAGER, STAFF))
    for pid, size in ((f"{prefix}-a-pink", "M"), (f"{prefix}-b-blue", "L")):
        db.execute("insert into products (id, article, name, brand, category, colour, price_paise, published) values (%s,'T','Test','','tshirts','x',10000,true)", (pid,))
        vid = db.execute("insert into variants (product_id, size) values (%s,%s) returning id", (pid, size)).fetchone()[0]
        db.execute("insert into stock_levels (variant_id, on_hand) values (%s, 5)", (vid,))
    db.execute("update store_status set last_heartbeat = now()")


def gateway(st, anon_key, secret):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, status, headers, body):
            self.send_response(status)
            for k, v in headers.items():
                if k.lower() not in ("transfer-encoding", "connection", "content-length", "date", "server"):
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def handle_any(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n) if n else None
            if self.path.startswith("/auth/v1/token"):
                d = json.loads(body or b"{}")
                pw = PASSWORDS.get(d.get("email"))
                if self.headers.get("apikey") != anon_key or not pw or pw[0] != d.get("password"):
                    return self._send(400, {"Content-Type": "application/json"}, b'{"code":400,"error_code":"invalid_credentials","msg":"Invalid login credentials"}')
                tok = mint(secret, user_claims(pw[1]))
                return self._send(200, {"Content-Type": "application/json"}, json.dumps({"access_token": tok, "token_type": "bearer", "expires_in": 3600}).encode())
            if not self.path.startswith("/rest/v1"):
                return self._send(404, {}, b"{}")
            if self.command != "OPTIONS" and self.headers.get("apikey") != anon_key:
                return self._send(401, {"Content-Type": "application/json"}, b'{"message":"No API key found in request","hint":"No `apikey` request header or url param was found."}')
            fwd = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length", "connection")}
            r = request(self.command, st.base + self.path[len("/rest/v1"):], fwd, body, 60)
            self._send(r.status, r.headers, r.body)
        do_GET = do_POST = do_PATCH = do_DELETE = do_PUT = do_OPTIONS = do_HEAD = handle_any
    ThreadingHTTPServer.request_queue_size = 256
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--not-dev", action="store_true")
    ap.add_argument("--ban", action="store_true", help="also rehearse the interactive ban step (the fake 'dashboard click' is done by this script)")
    a = ap.parse_args()
    st = stack.LocalStack()
    try:
        st.prepare_db()
        db = psycopg.connect(st.db_uri, autocommit=True)
        seed(db, "tst" if a.not_dev else "dev")
        st.start_postgrest()
        anon = mint(st.secret, anon_claims())
        srv = gateway(st, anon, st.secret)
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        creds = iter(["owner@example.invalid", "manager@example.invalid", "staff@example.invalid", "stranger@example.invalid"])
        pws = iter(["invented-pass-1", "invented-pass-2", "invented-pass-3", "invented-pass-4"])

        def enter(msg):
            print("   [rehearsal] " + msg.split(":")[0][:90])
            if "Ban user" in msg:
                db.execute("update auth.users set banned_until = now() + interval '1 day' where id = %s", (STAFF,))
            else:
                db.execute("update auth.users set banned_until = null where id = %s", (STAFF,))
        import contextlib
        import io
        import re
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = run_hosted.run(url, anon, ask_email=lambda m: next(creds), ask_password=lambda m: next(pws), ask_enter=enter, out_dir=HERE / "reports", ban=a.ban)
        except SystemExit as e:
            print(buf.getvalue() + str(e))
            print("exit code", 3 if a.not_dev else 4)
            return 3 if a.not_dev else 4
        out = buf.getvalue()
        print(out)
        # leak scan: nothing secret may appear in what was printed or in the report file
        report = (HERE / "reports" / "hosted_report.md").read_text(encoding="utf-8")
        secrets_ = [v[0] for v in PASSWORDS.values()] + list(PASSWORDS) + [anon, st.secret, str(srv.server_address[1]), "127.0.0.1"]
        leaks = [("printed" if x in out else "report", x[:6] + "...") for x in secrets_ if x in out or x in report]
        leaks += [("printed" if re.search(r"eyJ[A-Za-z0-9_-]{6,}\.", out) else "report", "jwt-shaped text") for _ in [0] if re.search(r"eyJ[A-Za-z0-9_-]{6,}\.", out + report)]
        print("LEAK SCAN:", "FOUND " + str(leaks) if leaks else "clean (no password, e-mail, key, token, secret or address in the output or the report)")
        print("exit code", rc)
        return 5 if leaks else rc
    finally:
        st.stop()


if __name__ == "__main__":
    sys.exit(main())
