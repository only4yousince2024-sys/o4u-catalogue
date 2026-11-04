"""A PERSISTENT throwaway PostgreSQL for the spike (data lives in ./.data/pg, gitignored). Local only, invented data only."""
from __future__ import annotations
import glob, os, pwd, shutil, subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / ".data"
PG = DATA / "pg"
PORT = 54329
DBNAME = "stockroom_spike"


def _bin() -> Path:
    c = sorted(glob.glob("/usr/lib/postgresql/*/bin"))
    if not c:
        raise SystemExit("No OS PostgreSQL found (apt install postgresql-16)")
    return Path(c[-1])


def _run(args, check=True):
    pre = ["runuser", "-u", "postgres", "--"] if os.geteuid() == 0 else []
    return subprocess.run(pre + [str(a) for a in args], check=check, capture_output=True, text=True)


def conninfo(db: str = DBNAME) -> str:
    return f"host={PG} port={PORT} dbname={db} user=postgres"


def running() -> bool:
    return _run([_bin() / "pg_ctl", "-D", PG / "data", "status"], check=False).returncode == 0


def start() -> None:
    DATA.mkdir(exist_ok=True)
    PG.mkdir(exist_ok=True)
    if os.geteuid() == 0:
        u = pwd.getpwnam("postgres")
        os.chmod(DATA, 0o755)
        shutil.chown(PG, u.pw_uid, u.pw_gid)
    b = _bin()
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
    if running():
        _run([_bin() / "pg_ctl", "-D", PG / "data", "-m", mode, "-w", "stop"])
