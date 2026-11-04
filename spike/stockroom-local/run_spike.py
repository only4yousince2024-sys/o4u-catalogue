"""Run the whole local Stockroom feasibility spike and print PASS / FAIL / BLOCKED per item. Local only, invented data only.

    python spike/stockroom-local/run_spike.py        (needs: OS PostgreSQL, `pip install psycopg[binary]`, node + playwright,
                                                      `npm install --no-save jszip@3.10.1` inside spike/stockroom-local)
Steps: start PostgreSQL + the spike server; HTTP-level lease checks; browser checks (browser_tests.js main); validate the downloaded
CSV/ZIP files independently in Python; restart the server AND PostgreSQL; browser checks again (after-restart). Nothing is pushed or deployed.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pgdev  # noqa: E402

BASE = "http://127.0.0.1:8780"
REPORTS = HERE / "reports"
RESULTS: list[tuple[str, str, str]] = []
server = None


def rec(i, status, detail=""):
    RESULTS.append((i, status, detail))
    print(f"  {status:7s} {i}  {detail}", flush=True)


def req(method, path, body=None, raw=None, ctype="application/json"):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    r = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": ctype} if data is not None else {})
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def start_server():
    global server
    env = dict(os.environ)
    server = subprocess.Popen([sys.executable, str(HERE / "server.py")], stdout=open(REPORTS / "server.log", "a"), stderr=subprocess.STDOUT, env=env)
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/api/assets", timeout=1).read()
            return
        except Exception:      # noqa: BLE001
            time.sleep(0.5)
    raise SystemExit("server did not start; see reports/server.log")


def stop_server():
    global server
    if server:
        server.terminate()
        server.wait(10)
        server = None


def check(i, fn):
    try:
        d = fn()
        rec(i, "PASS", d or "")
    except AssertionError as e:
        rec(i, "FAIL", str(e)[:300])
    except Exception as e:      # noqa: BLE001
        rec(i, "FAIL", repr(e)[:300])


# ───────────── HTTP-level lease checks (a real lock in PostgreSQL) ─────────────
def lease(doc, holder, ttl=5000):
    st, j = req("POST", f"/api/lease/products/{doc}", {"holder": holder, "ttlMs": ttl})
    assert st == 200, (st, j)
    return j["acquired"]


def lease_checks():
    def l1():
        doc, out = "lease-l1", []
        bar = threading.Barrier(30)

        def go(n):
            bar.wait()
            out.append(lease(doc, f"holder-{n}"))
        ts = [threading.Thread(target=go, args=(n,)) for n in range(30)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert len(out) == 30, f"only {len(out)} of 30 requests were answered"
        assert sum(out) == 1, f"{sum(out)} of 30 simultaneous holders got the lease"
        return "30 simultaneous holders on one document: exactly 1 acquired"
    check("L1 lease is mutually exclusive (30 threads)", l1)

    def l2():
        assert lease("lease-l2", "A") and lease("lease-l2", "A"), "the holder cannot renew its own lease"
        assert not lease("lease-l2", "B"), "another holder got a live lease"
        return "holder renews, others refused while it is live"
    check("L2 renew by holder, refuse others", l2)

    def l3():
        assert lease("lease-l3", "A", 300)
        assert not lease("lease-l3", "B", 300)
        time.sleep(0.45)
        assert lease("lease-l3", "B", 300), "an expired lease was not released"
        return "expires by itself after its TTL (a crashed tab cannot block forever)"
    check("L3 lease expires", l3)

    def l4():
        assert lease("lease-l4a", "A") and lease("lease-l4b", "B"), "different documents must not block each other"
        st, j = req("POST", "/api/lease/products/x", {"holder": "", "ttlMs": 5})
        assert st == 400, f"bad input accepted ({st})"
        return "independent per document; invalid input refused (400)"
    check("L4 independence and input checks", l4)


# ───────────── validate the downloads the browser saved ─────────────
def download_checks():
    state = json.loads((REPORTS / "state.json").read_text())
    web_ids = state["web"]

    def csv_check():
        raw = Path(state["csv"]).read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf"), "no UTF-8 BOM (Excel would garble it)"
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        head, body = rows[0], rows[1:]
        assert head[:6] == ["Product id", "Article", "Brand", "Category", "Product", "Colour"], head[:6]
        assert all(len(r) == len(head) for r in body), "ragged rows"
        db_total = state["csvDb"]      # totals read from the database at the moment the CSV was downloaded
        assert {r[0] for r in body} == set(db_total) and len(body) == len(db_total), f"CSV has {len(body)} rows, database {len(db_total)} products"
        total_i = head.index("Total")
        for r in body:
            assert r[total_i].isdigit(), f"Total not numeric: {r[total_i]!r}"
        bad = [r[0] for r in body if int(r[total_i]) != db_total[r[0]]]
        assert not bad, f"CSV totals differ from the database for {bad[:3]}"
        return f"{len(body)} rows x {len(head)} columns, BOM, ids and per-product totals equal the database"
    check("D1 CSV is valid and matches the database", csv_check)

    def zip_web():
        z = zipfile.ZipFile(state["zipWeb"])
        assert z.testzip() is None, "corrupt entry"
        names = sorted(z.namelist())
        pid = state["editId"]
        assert names == sorted([f"{pid}.jpg", f"{pid}-2.jpg"]), names
        for n in names:
            b = z.read(n)
            assert b[:3] == b"\xff\xd8\xff", f"{n} is not a JPEG"
        stored = sorted(hashlib.sha256((pgdev.DATA / "blobs" / w).read_bytes()).hexdigest() for w in web_ids)
        zipped = sorted(hashlib.sha256(z.read(n)).hexdigest() for n in names)
        assert stored == zipped, "ZIP images differ from the stored files"
        return f"{names} byte-identical to the stored photo files"
    check("D2 website-images ZIP is valid", zip_web)

    def zip_backup():
        z = zipfile.ZipFile(state["zipBackup"])
        assert z.testzip() is None
        names = z.namelist()
        assert {"records.json", "manifest.csv", "README.txt"} <= set(names), names
        rec_ = json.loads(z.read("records.json"))
        st, cols = req("GET", "/api/col/products")
        colls = rec_["collections"]
        want = state["counts"]
        mism = {c: (len(colls.get(c, {})), n) for c, n in want.items() if len(colls.get(c, {})) != n}
        assert not mism, f"documents in the backup vs the database at that moment (backup, database): {mism}"
        got = colls["products"]
        photos = [n for n in names if n.startswith("photos/") and not n.endswith("/")]
        assert len(photos) == state["assetsAtBackup"] == 4, f"{len(photos)} photos in the ZIP, {state['assetsAtBackup']} stored at that moment"
        return f"records.json: every collection's document count equals the database ({want}); {len(photos)} photos = every stored asset"
    check("D3 full-backup ZIP is valid and complete", zip_backup)


def node(phase):
    p = subprocess.run(["node", str(HERE / "browser_tests.js"), phase], cwd=HERE, capture_output=True, text=True, timeout=600)
    out = []
    for line in p.stdout.splitlines():
        if line.startswith("{"):
            j = json.loads(line)
            out.append(j)
            rec("B " + j["id"], j["status"], j["detail"])
    if p.returncode == 2:
        rec("B " + phase, "FAIL", "browser script crashed: " + p.stderr[-300:])
    return out


def main():
    REPORTS.mkdir(exist_ok=True)
    shutil.rmtree(REPORTS / "downloads", ignore_errors=True)
    pgdev.start()
    print("PostgreSQL:", subprocess.run(["psql", pgdev.conninfo(), "-Atc", "select version()"], capture_output=True, text=True).stdout.strip().split(",")[0])
    start_server()
    try:
        print("\n== HTTP lease checks ==")
        lease_checks()
        print("\n== Browser checks (real Chromium, 390x844 touch viewport) ==")
        node("main")
        print("\n== Validation of the downloaded files (Python, independent of the page) ==")
        download_checks()
        print("\n== Restart the spike server AND PostgreSQL, then re-check ==")
        stop_server()
        pgdev.stop()
        pgdev.start()
        start_server()
        node("after-restart")
    finally:
        stop_server()
    npass = sum(1 for r in RESULTS if r[1] == "PASS")
    nfail = sum(1 for r in RESULTS if r[1] == "FAIL")
    nblk = sum(1 for r in RESULTS if r[1] == "BLOCKED")
    print(f"\n{npass} PASS, {nfail} FAIL, {nblk} BLOCKED")
    (REPORTS / "spike_results.json").write_text(json.dumps(RESULTS, indent=1))
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
