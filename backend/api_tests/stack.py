"""Local real-HTTP stack: throwaway PostgreSQL + the official PostgREST binary, configured like a Supabase project.

What matches Supabase:   `authenticator` login role (NOINHERIT) that SET LOCAL ROLEs into anon / authenticated / service_role from the
                         JWT `role` claim; schema `public` exposed; anon role `anon`; HS256 JWT verification; per-role statement
                         timeouts (anon 3 s, authenticated 8 s, as on hosted projects); auth.uid() reading request.jwt.claims.
What does NOT match:     Supabase's API gateway (Kong): apikey checking, its own CORS handling, rate limits and request-size
                         limits are NOT here. GoTrue (sign-in, ban, delete) is NOT here: tokens are minted with the throwaway
                         secret, and ban/delete are done on the shim's auth.users table.
The JWT secret is generated fresh for every run, held in memory and in the PostgREST config inside the temp folder, and deleted.
"""
from __future__ import annotations

import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "tests"))
import pgcluster      # noqa: E402

import psycopg        # noqa: E402

MIGRATIONS = sorted((ROOT / "migrations").glob("*.sql"))


def find_postgrest() -> Path:
    env = os.environ.get("O4U_POSTGREST")
    if env and Path(env).exists():
        return Path(env)
    w = shutil.which("postgrest")
    if w:
        return Path(w)
    raise SystemExit("PostgREST binary not found. Download the official static release from "
                     "https://github.com/PostgREST/postgrest/releases and set O4U_POSTGREST=/path/to/postgrest (see README).")


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class LocalStack:
    def __init__(self, with_cron: bool = False, extra_pgrst: dict | None = None):
        self.cluster = pgcluster.make_cluster(preload_cron=with_cron, cron_db="o4ucron")
        self.secret = secrets.token_urlsafe(48)           # throwaway; never reused, never written outside the temp folder
        self.port = free_port()
        self.admin_port = free_port()
        self.proc = None
        self.extra = extra_pgrst or {}
        self.pgrst_bin = find_postgrest()
        self.root = Path(self.cluster.root)

    # -- database ---------------------------------------------------------------------------------
    @property
    def db_uri(self) -> str:
        return self.cluster.uri

    def prepare_db(self, migrations=None, notices=None):
        c = psycopg.connect(self.db_uri, autocommit=True)
        if notices is not None:
            c.add_notice_handler(lambda d: notices.append(f"{d.severity}: {d.message_primary}"))
        c.execute((ROOT / "tests" / "supabase_shim.sql").read_text(encoding="utf-8"))
        for m in (migrations or MIGRATIONS):
            c.execute(m.read_text(encoding="utf-8"))
        # hosted projects give these roles statement timeouts; copy them so a runaway request is cut like it would be there
        c.execute("alter role anon set statement_timeout = '3s'")
        c.execute("alter role authenticated set statement_timeout = '8s'")
        c.execute("alter role authenticator set statement_timeout = '8s'")
        c.close()

    def version(self) -> str:
        c = psycopg.connect(self.db_uri, autocommit=True)
        v = c.execute("select version()").fetchone()[0].split(",")[0]
        c.close()
        return v

    # -- PostgREST --------------------------------------------------------------------------------
    def start_postgrest(self):
        sock_dir = str(self.cluster.root)
        dbname = self.cluster.dbname
        conf = {
            "db-uri": f"postgresql://authenticator@/{dbname}?host={sock_dir}&port={self.cluster.port}",
            "db-schemas": "public",
            "db-anon-role": "anon",
            "db-pool": "20",
            "db-max-rows": "1000",
            "db-extra-search-path": "public",
            "jwt-secret": self.secret,
            "role-claim-key": ".role",
            "server-host": "127.0.0.1",
            "server-port": str(self.port),
            "admin-server-port": str(self.admin_port),
            "openapi-mode": "follow-privileges",
            "log-level": "warn",
        }
        conf.update(self.extra)
        cfg = self.root / "postgrest.conf"
        cfg.write_text("".join(f'{k} = "{v}"\n' for k, v in conf.items()))
        os.chmod(cfg, 0o600)
        self.log_path = self.root / "postgrest.log"
        self.proc = subprocess.Popen([str(self.pgrst_bin), str(cfg)], stdout=open(self.log_path, "w"), stderr=subprocess.STDOUT)
        t0 = time.time()
        while time.time() - t0 < 30:
            try:
                s = socket.create_connection(("127.0.0.1", self.admin_port), timeout=1)
                s.sendall(b"GET /ready HTTP/1.0\r\n\r\n")
                if b" 200 " in s.recv(100):
                    s.close()
                    return
                s.close()
            except OSError:
                pass
            if self.proc.poll() is not None:
                raise RuntimeError("PostgREST exited: " + self.log_path.read_text()[-800:])
            time.sleep(0.2)
        raise RuntimeError("PostgREST did not become ready: " + self.log_path.read_text()[-800:])

    def reload_schema(self):
        """Tell PostgREST to re-read the schema cache (needed after DDL such as a new migration)."""
        self.proc.send_signal(signal.SIGUSR1)
        time.sleep(1.0)

    def postgrest_version(self) -> str:
        return subprocess.run([str(self.pgrst_bin), "--version"], capture_output=True, text=True).stdout.strip()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.cluster.cleanup()          # removes the temp folder, including postgrest.conf (and with it the throwaway secret)
