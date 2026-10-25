"""Throwaway PostgreSQL clusters for the checks. TEST TOOLING ONLY: nothing here talks to a network or to Supabase.

Preferred: a real Linux PostgreSQL (initdb + pg_ctl from the OS packages, e.g. /usr/lib/postgresql/16/bin). As root the
server is started as the `postgres` OS user (PostgreSQL refuses to run as root). `preload_cron=True` loads pg_cron
(package `postgresql-16-cron`) so the scheduler migration can be exercised for real; False gives a cluster where pg_cron
is not loaded, which is how the 'no-op where unavailable' path is proven.
Fallback (Windows/macOS or no OS PostgreSQL): the `pgserver` pip package, without pg_cron.
"""
from __future__ import annotations

import glob
import os
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

try:
    import pwd                      # Unix only; on Windows the pgserver fallback is used
except ImportError:
    pwd = None


def find_bin() -> Path | None:
    env = os.environ.get("O4U_PG_BIN")
    if env and (Path(env) / "initdb").exists():
        return Path(env)
    cands = sorted(glob.glob("/usr/lib/postgresql/*/bin"), key=lambda p: int(Path(p).parent.name) if Path(p).parent.name.isdigit() else 0)
    return Path(cands[-1]) if cands and (Path(cands[-1]) / "initdb").exists() else None


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class SystemCluster:
    def __init__(self, bindir: Path, preload_cron: bool, dbname: str = "o4utest", cron_db: str | None = None):
        self.bin, self.dbname, self.preload_cron, self.cron_db = bindir, dbname, preload_cron, cron_db or dbname
        self.root = Path(tempfile.mkdtemp(prefix="o4u-pg-"))
        self.data = self.root / "data"
        self.port = _free_port()
        self.as_root = hasattr(os, "geteuid") and os.geteuid() == 0
        if self.as_root:
            pg = pwd.getpwnam("postgres")
            os.chmod(self.root, 0o755)
            shutil.chown(self.root, pg.pw_uid, pg.pw_gid)

    def _run(self, args: list[str], **kw):
        cmd = (["runuser", "-u", "postgres", "--"] if self.as_root else []) + args
        return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)

    def start(self):
        self._run([str(self.bin / "initdb"), "-D", str(self.data), "--auth=trust", "-U", "postgres", "--encoding=UTF8", "--locale=C.UTF-8"])
        conf = [f"port = {self.port}", f"unix_socket_directories = '{self.root}'", "listen_addresses = ''", "fsync = off", "max_connections = 100",
                "synchronous_commit = off", "full_page_writes = off"]
        if self.preload_cron:
            conf += ["shared_preload_libraries = 'pg_cron'", f"cron.database_name = '{self.cron_db}'", "cron.use_background_workers = on", "max_worker_processes = 16"]
        with open(self.data / "postgresql.conf", "a") as f:
            f.write("\n".join(conf) + "\n")
        self._run([str(self.bin / "pg_ctl"), "-D", str(self.data), "-l", str(self.root / "server.log"), "-w", "-t", "60", "start"])
        self._run([str(self.bin / "createdb"), "-h", str(self.root), "-p", str(self.port), "-U", "postgres", self.dbname])

    @property
    def uri(self) -> str:
        return f"host={self.root} port={self.port} dbname={self.dbname} user=postgres"

    def cleanup(self):
        try:
            self._run([str(self.bin / "pg_ctl"), "-D", str(self.data), "-m", "immediate", "-w", "stop"])
        except Exception:      # noqa: BLE001
            pass
        shutil.rmtree(self.root, ignore_errors=True)

    @property
    def log(self) -> str:
        p = self.root / "server.log"
        return p.read_text(errors="replace") if p.exists() else ""


class PgserverCluster:
    """Fallback for machines without an OS PostgreSQL. No pg_cron."""
    preload_cron = False

    def __init__(self):
        import pgserver
        self.root = tempfile.mkdtemp(prefix="o4u-pg-")
        self.server = pgserver.get_server(self.root, cleanup_mode="stop")

    def start(self):
        pass

    @property
    def uri(self) -> str:
        return self.server.get_uri()

    def cleanup(self):
        self.server.cleanup()


def make_cluster(preload_cron: bool = False, cron_db: str | None = None):
    b = find_bin() if pwd is not None else None
    c = SystemCluster(b, preload_cron, cron_db=cron_db) if b else PgserverCluster()
    c.start()
    return c
