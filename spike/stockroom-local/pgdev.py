"""A PERSISTENT throwaway PostgreSQL for the spike (data lives in ./.data/pg, gitignored). Local only, invented data only.

Linux with an OS PostgreSQL (initdb/pg_ctl): used directly, as before. Anywhere else (Windows, macOS, no OS PostgreSQL): the `pgserver` pip package,
a real PostgreSQL started from the same data folder. The OS-PostgreSQL path is unchanged from the Cloud spike (not re-run on this computer)."""
from __future__ import annotations
import glob, os, shutil, subprocess
from pathlib import Path

try:
    import pwd              # Unix only
except ImportError:
    pwd = None

HERE = Path(__file__).resolve().parent
DATA = HERE / ".data"
PG = DATA / "pg"
PORT = 54329
DBNAME = "stockroom_spike"
_PGS = None                 # the pgserver handle when that fallback is used


def _bin():
    c = sorted(glob.glob("/usr/lib/postgresql/*/bin"))
    return Path(c[-1]) if c and (Path(c[-1]) / "initdb").exists() else None


def _run(args, check=True):
    pre = ["runuser", "-u", "postgres", "--"] if hasattr(os, "geteuid") and os.geteuid() == 0 else []
    return subprocess.run(pre + [str(a) for a in args], check=check, capture_output=True, text=True)


def _pgserver():
    global _PGS
    if _PGS is None:
        import pgserver
        _PGS = pgserver.get_server(PG, cleanup_mode=None)       # keeps running data between runs; stop() ends it
    return _PGS


def conninfo(db: str = DBNAME) -> str:
    if _bin() is None:
        return _pgserver().get_uri(db)
    return f"host={PG} port={PORT} dbname={db} user=postgres"


def running() -> bool:
    if _bin() is None:
        return _PGS is not None
    return _run([_bin() / "pg_ctl", "-D", PG / "data", "status"], check=False).returncode == 0


def start() -> None:
    DATA.mkdir(exist_ok=True)
    PG.mkdir(exist_ok=True)
    b = _bin()
    if b is None:
        import psycopg
        srv = _pgserver()
        with psycopg.connect(srv.get_uri("postgres"), autocommit=True) as c:
            if not c.execute("select 1 from pg_database where datname=%s", (DBNAME,)).fetchone():
                c.execute(f'create database "{DBNAME}"')
        return
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        u = pwd.getpwnam("postgres")
        os.chmod(DATA, 0o755)
        shutil.chown(PG, u.pw_uid, u.pw_gid)
    first = not (PG / "data" / "PG_VERSION").exists()
    if first:
        _run([b / "initdb", "-D", PG / "data", "--auth=trust", "-U", "postgres", "--encoding=UTF8", "--locale=C.UTF-8"])
        with open(PG / "data" / "postgresql.conf", "a") as f:
            f.write(f"port = {PORT}\nunix_socket_directories = '{PG}'\nlisten_addresses = ''\n")
    if not running():
        _run([b / "pg_ctl", "-D", PG / "data", "-l", PG / "server.log", "-w", "-t", "60", "start"])
    if first:
        _run([b / "createdb", "-h", PG, "-p", PORT, "-U", "postgres", DBNAME])


def stop(mode: str = "fast") -> None:
    global _PGS
    if _bin() is None:
        if _PGS is not None:
            _PGS.cleanup()
            _PGS = None
        return
    if running():
        _run([_bin() / "pg_ctl", "-D", PG / "data", "-m", mode, "-w", "stop"])
