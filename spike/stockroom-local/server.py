"""Local-only spike server: serves the UNMODIFIED Stockroom page with a runtime shim injected, plus a tiny JSON API on a local PostgreSQL.

    python spike/stockroom-local/server.py [--port 8780] [--html stockroom/stockroom-v44-original.html]

Nothing here reaches the internet, Supabase or any real data. The Stockroom HTML is read from disk and rewritten IN MEMORY
(one script tag added, the JSZip CDN URL pointed at a local copy); the file itself is never changed.
Persistence: documents + leases + asset metadata in PostgreSQL (./.data/pg), photo bytes as files in ./.data/blobs.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import re
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import psycopg
from psycopg.types.json import Jsonb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import pgdev  # noqa: E402

BLOBS = pgdev.DATA / "blobs"
MAX_ASSET = 20 * 1024 * 1024
MAX_BYTES_TOTAL = 500 * 1024 * 1024
CDN_JSZIP = "https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"
HTML_FILES = {"v44": ROOT / "stockroom" / "stockroom-v44-original.html", "dev2": ROOT / "stockroom" / "stockroom-dev-v2.html"}

SUBS: list[queue.Queue] = []
SUBS_LOCK = threading.Lock()


def db():
    return psycopg.connect(pgdev.conninfo(), autocommit=True)


def listener():
    """LISTEN on the database's own change notifications and push each one to every open page (server-sent events)."""
    while True:
        try:
            with db() as c:
                c.execute("listen spike_changes")
                for n in c.notifies():
                    with SUBS_LOCK:
                        for q in SUBS:
                            q.put(n.payload)
        except Exception as e:      # noqa: BLE001
            print("listener restarting:", e, file=sys.stderr)
            time.sleep(1)


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    html_key = "v44"

    def log_message(self, fmt, *a):
        if os.environ.get("SPIKE_VERBOSE"):
            super().log_message(fmt, *a)

    # ---- helpers
    def send(self, code, body=b"", ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def json_body(self):
        return json.loads(self.body() or b"{}")

    # ---- routing
    def do_GET(self):
        u = urlparse(self.path)
        p, qs = u.path, parse_qs(u.query)
        try:
            if p in ("/", "/stockroom"):
                return self.page(qs)
            if p.startswith("/spike/"):
                f = HERE / "static" / Path(p[7:]).name
                return self.send(200, f.read_bytes(), "text/javascript" if f.suffix == ".js" else "text/html") if f.exists() else self.send(404, {"error": "not found"})
            if p == "/vendor/jszip.min.js":
                f = HERE / "node_modules" / "jszip" / "dist" / "jszip.min.js"
                return self.send(200, f.read_bytes(), "text/javascript") if f.exists() else self.send(404, {"error": "run npm install in spike/stockroom-local"})
            if p.startswith("/_blob/"):
                return self.blob(p[7:])
            if p == "/api/events":
                return self.events()
            if p == "/api/assets":
                return self.asset_list()
            m = re.fullmatch(r"/api/col/([\w-]+)", p)
            if m:
                return self.col(m.group(1), qs)
            m = re.fullmatch(r"/api/doc/([\w-]+)/([^/]+)", p)
            if m:
                with db() as c:
                    r = c.execute("select data from spike_docs where collection=%s and id=%s", (m.group(1), unquote(m.group(2)))).fetchone()
                return self.send(200, {"exists": r is not None, "data": r[0] if r else None})
            return self.send(404, {"error": "not found"})
        except Exception as e:      # noqa: BLE001
            return self.send(500, {"error": str(e)})

    def do_PUT(self):
        return self.write("PUT")

    def do_PATCH(self):
        return self.write("PATCH")

    def do_DELETE(self):
        p = urlparse(self.path).path
        m = re.fullmatch(r"/api/doc/([\w-]+)/([^/]+)", p)
        if m:
            with db() as c:
                c.execute("delete from spike_docs where collection=%s and id=%s", (m.group(1), unquote(m.group(2))))
            return self.send(200, {"ok": True})
        m = re.fullmatch(r"/api/assets/([\w-]+)", p)
        if m:
            with db() as c:
                c.execute("delete from spike_assets where id=%s", (m.group(1),))
            (BLOBS / m.group(1)).unlink(missing_ok=True)
            return self.send(200, {"ok": True})
        return self.send(404, {"error": "not found"})

    def do_POST(self):
        p = urlparse(self.path).path
        try:
            m = re.fullmatch(r"/api/lease/([\w-]+)/([^/]+)", p)
            if m:
                return self.lease(m.group(1), unquote(m.group(2)))
            if p == "/api/assets":
                return self.asset_put()
            if p == "/api/_spike/reset":
                return self.reset()
            if p == "/api/_spike/bulk":
                return self.bulk()
            return self.send(404, {"error": "not found"})
        except Exception as e:      # noqa: BLE001
            return self.send(500, {"error": str(e)})

    # ---- page
    def page(self, qs):
        key = (qs.get("v") or [self.html_key])[0]
        html = HTML_FILES[key].read_text(encoding="utf-8")
        html = html.replace(CDN_JSZIP, "/vendor/jszip.min.js")
        html = html.replace("<head>", '<head><script src="/spike/claude-shim.js"></script>', 1)
        return self.send(200, html, "text/html; charset=utf-8")

    # ---- documents
    def col(self, name, qs):
        sql, args = "select id, data from spike_docs where collection=%s", [name]
        for w in qs.get("where", []):
            f, op, v = w.split("|", 2)
            if op != "==":
                return self.send(400, {"error": "only == is supported in the spike"})
            sql += " and data->%s = %s::jsonb"
            args += [f, v]
        if qs.get("orderBy"):
            sql += " order by data->%s " + ("desc" if (qs.get("dir") or ["asc"])[0] == "desc" else "asc") + ", id"
            args.append(qs["orderBy"][0])
        else:
            sql += " order by id"
        if qs.get("limit"):
            sql += " limit %s"
            args.append(int(qs["limit"][0]))
        with db() as c:
            rows = c.execute(sql, args).fetchall()
        return self.send(200, {"docs": [{"id": r[0], "data": r[1]} for r in rows]})

    def write(self, verb):
        m = re.fullmatch(r"/api/doc/([\w-]+)/([^/]+)", urlparse(self.path).path)
        if not m:
            return self.send(404, {"error": "not found"})
        col, did = m.group(1), unquote(m.group(2))
        data = self.json_body()
        with db() as c:
            if verb == "PUT":
                c.execute("insert into spike_docs (collection,id,data) values (%s,%s,%s) on conflict (collection,id) do update set data=excluded.data, updated_at=now()", (col, did, Jsonb(data)))
            else:   # shallow merge of top-level keys, like a document update
                n = c.execute("update spike_docs set data = data || %s, updated_at=now() where collection=%s and id=%s", (Jsonb(data), col, did)).rowcount
                if n == 0:
                    return self.send(404, {"code": "not_found", "error": "no such document"})
        return self.send(200, {"ok": True})

    # ---- a real lock: one row per document, taken atomically in the database, expires by itself
    def lease(self, col, did):
        b = self.json_body()
        holder, ttl = str(b.get("holder") or ""), int(b.get("ttlMs") or 0)
        if not holder or ttl < 1 or ttl > 60000:
            return self.send(400, {"code": "invalid_argument", "error": "holder and ttlMs (1..60000) required"})
        with db() as c:
            r = c.execute(
                """insert into spike_leases (collection,id,holder,expires_at) values (%s,%s,%s, now() + %s * interval '1 millisecond')
                   on conflict (collection,id) do update set holder=excluded.holder, expires_at=excluded.expires_at
                   where spike_leases.expires_at < now() or spike_leases.holder = excluded.holder
                   returning holder""", (col, did, holder, ttl)).fetchone()
        return self.send(200, {"acquired": r is not None})

    # ---- photos: real bytes on disk, metadata in the database
    def asset_put(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_ASSET:
            self.rfile.read(n)
            return self.send(413, {"code": "too_large", "error": "20 MB max"})
        data = self.rfile.read(n)
        ctype = self.headers.get("Content-Type") or "application/octet-stream"
        if not ctype.startswith("image/"):
            return self.send(415, {"code": "invalid_argument", "error": "images only"})
        with db() as c:
            used = c.execute("select coalesce(sum(bytes),0) from spike_assets").fetchone()[0]
            if used + n > MAX_BYTES_TOTAL:
                return self.send(507, {"code": "quota_or_state", "error": "storage full"})
            aid = uuid.uuid4().hex
            BLOBS.mkdir(parents=True, exist_ok=True)
            (BLOBS / aid).write_bytes(data)
            c.execute("insert into spike_assets (id, content_type, bytes) values (%s,%s,%s)", (aid, ctype, n))
        return self.send(200, {"id": aid, "bytes": n, "type": ctype})

    def blob(self, aid):
        if not re.fullmatch(r"[\w-]+", aid):
            return self.send(404, {"error": "not found"})
        with db() as c:
            r = c.execute("select content_type from spike_assets where id=%s", (aid,)).fetchone()
        f = BLOBS / aid
        if not r or not f.exists():
            return self.send(404, {"error": "not found"})
        return self.send(200, f.read_bytes(), r[0], {"Cache-Control": "private, max-age=3600"})

    def asset_list(self):
        with db() as c:
            rows = c.execute("select id, content_type, bytes, created_at from spike_assets order by created_at").fetchall()
        total = sum(r[2] for r in rows)
        return self.send(200, {"assets": [{"id": r[0], "type": r[1], "bytes": r[2], "createdAt": r[3].isoformat()} for r in rows],
                               "usage": {"files": len(rows), "bytes": total, "maxBytes": MAX_BYTES_TOTAL}})

    # ---- server-sent events (page re-reads a collection when the database says it changed)
    def events(self):
        q: queue.Queue = queue.Queue()
        with SUBS_LOCK:
            SUBS.append(q)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(b": hello\n\n")
            self.wfile.flush()
            while True:
                try:
                    payload = q.get(timeout=15)
                    self.wfile.write(f"data: {payload}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with SUBS_LOCK:
                SUBS.remove(q)
            self.close_connection = True

    # ---- spike-only helpers (tests use them to load INVENTED data)
    def reset(self):
        with db() as c:
            c.execute("truncate spike_docs, spike_leases, spike_assets")
        for f in BLOBS.glob("*"):
            f.unlink()
        return self.send(200, {"ok": True})

    def bulk(self):
        data = self.json_body()
        n = 0
        with db() as c:
            for col, docs in data.items():
                for did, d in docs.items():
                    c.execute("insert into spike_docs (collection,id,data) values (%s,%s,%s) on conflict (collection,id) do update set data=excluded.data", (col, did, Jsonb(d)))
                    n += 1
        return self.send(200, {"written": n})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8780)
    a = ap.parse_args()
    pgdev.start()
    with db() as c:
        c.execute((HERE / "schema.sql").read_text())
    BLOBS.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=listener, daemon=True).start()
    ThreadingHTTPServer.request_queue_size = 128      # the default (5) resets connections when a few dozen arrive together
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    srv.daemon_threads = True
    print(f"spike server on http://127.0.0.1:{a.port}/stockroom (local only)", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
