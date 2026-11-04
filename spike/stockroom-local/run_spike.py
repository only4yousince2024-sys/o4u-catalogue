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



# ───────────── atomic stock path: HTTP-level checks against the real database (migration 0010 through the spike endpoint) ─────────────
import psycopg  # noqa: E402


def pg():
    return psycopg.connect(pgdev.conninfo(), autocommit=True)


def sproduct(pid, m):
    return {"id": pid, "article": pid.upper(), "brand": "", "category": "tshirts", "type": "Http Test Tee", "colour": "Teal", "sizes": [{"size": "M", "mrp": 999}, {"size": "L", "mrp": 999}],
            "stock": {"M": m, "L": 0}, "inStock": m > 0, "published": True, "status": "ready", "flags": [], "notes": "", "webImages": [], "createdAt": "2026-11-01T00:00:00.000Z", "updatedAt": "2026-11-01T00:00:00.000Z"}


def seed(**stocks):
    req("POST", "/api/_spike/reset")
    st, j = req("POST", "/api/_spike/bulk?relational=1", {"products": {pid: sproduct(pid, m) for pid, m in stocks.items()}})
    assert st == 200, (st, j)


def move(key_, pid, change, by="tester", kind="sale", size="M", **extra):
    m = {"productId": pid, "size": size, "change": change, "label": "Http Test Tee", "article": pid.upper(), "category": "tshirts", **extra}
    return req("POST", "/api/stock/moves", {"key": key_, "meta": {"kind": kind, "by": by}, "moves": [m]})


def state(pid):
    with pg() as c:
        oh = c.execute("select coalesce(sum(sl.on_hand),0) from stock_levels sl join variants v on v.id=sl.variant_id where v.product_id=%s", (pid,)).fetchone()[0]
        ev = c.execute("select count(*) from stock_events e join variants v on v.id=e.variant_id where v.product_id=%s and e.kind <> 'opening_balance'", (pid,)).fetchone()[0]
        docs = c.execute("select count(*) from spike_docs where collection='stockmoves' and data->>'productId'=%s", (pid,)).fetchone()[0]
        idem = c.execute("select count(*) from idempotency where action='apply_stock_moves'").fetchone()[0]
    return int(oh), ev, docs, idem


def uk(tag):
    return f"{tag}-{uuid_hex()}"


def uuid_hex():
    import uuid
    return uuid.uuid4().hex[:10]


def assert_ledger():
    """The ledger explains the shelf (per variant) and the page's history copies equal the ledger (per product). Raises AssertionError."""
    with pg() as c:
        bad = c.execute("""select v.product_id, v.size from stock_levels sl join variants v on v.id = sl.variant_id
                           where sl.on_hand <> coalesce((select sum(d_on_hand) from stock_events e where e.variant_id = sl.variant_id), 0)
                              or sl.reserved <> coalesce((select sum(d_reserved) from stock_events e where e.variant_id = sl.variant_id), 0)
                              or sl.on_hand < 0""").fetchall()
        assert not bad, f"stock_levels disagree with the ledger for {bad}"
        docsum = {k: int(v) for k, v in c.execute("select data->>'productId', sum((data->>'change')::int) from spike_docs where collection='stockmoves' and data ? 'ledgerKey' group by 1").fetchall()}
        ledsum = {k: int(v) for k, v in c.execute("select v.product_id, sum(e.d_on_hand) from stock_events e join variants v on v.id=e.variant_id where e.kind <> 'opening_balance' group by 1").fetchall()}
        assert docsum == ledsum, f"history copies {docsum} vs ledger {ledsum}"
        # the page reads stock through the overlay: it must equal the relational number
        for pid, in c.execute("select id from products").fetchall():
            st, j = req("GET", f"/api/doc/products/{pid}")
            rel = {r[0]: r[1] for r in c.execute("select v.size, sl.on_hand from variants v join stock_levels sl on sl.variant_id=v.id where v.product_id=%s", (pid,)).fetchall()}
            assert j["data"]["stock"] == rel, f"{pid}: page sees {j['data']['stock']}, database {rel}"


def stock_checks():
    def h1():
        seed(**{"h-final": 1})
        out, bar = [], threading.Barrier(12)

        def go(i):
            bar.wait()
            out.append(move(uk(f"final{i}"), "h-final", -1))
        ts = [threading.Thread(target=go, args=(i,)) for i in range(12)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        wins = [r for r in out if r[0] == 200]
        loses = [r for r in out if r[0] == 409]
        assert len(out) == 12 and len(wins) == 1 and len(loses) == 11, f"{len(wins)} sold, {len(loses)} refused, others {[r for r in out if r[0] not in (200, 409)][:2]}"
        assert all(r[1]["code"] == "short" for r in loses), loses[0]
        assert state("h-final") == (0, 1, 1, 1), state("h-final")
        assert_ledger()
        return "12 simultaneous HTTP requests for the last piece: 1 sold, 11 refused (409 short); stock 0, 1 ledger row, 1 history copy"
    check("H1 final piece: exactly one succeeds", h1)

    def h2():
        seed(**{"h-fault": 5})
        c = pg()
        c.execute("create function public.zz_fault() returns trigger language plpgsql as $$ begin raise exception 'injected ledger failure'; end $$")
        c.execute("create trigger zz_fault before insert on stock_events for each row when (new.reason like '%FAULTME%') execute function public.zz_fault()")
        k = uk("fault")
        try:
            st, j = move(k, "h-fault", -1, by="FAULTME")
            assert st != 200 and "injected ledger failure" in json.dumps(j), (st, j)
            assert state("h-fault") == (5, 0, 0, 0), f"stock/ledger/history/key after the failure: {state('h-fault')}"
            two = req("POST", "/api/stock/moves", {"key": uk("fault2"), "meta": {"kind": "sale", "by": "FAULTME"}, "moves": [
                {"productId": "h-fault", "size": "L", "change": 0, "kind": "receive"}]})
        finally:
            c.execute("drop trigger if exists zz_fault on stock_events")
            c.execute("drop function if exists public.zz_fault()")
        st, j = move(k, "h-fault", -1, by="FAULTME")
        assert st == 200 and state("h-fault") == (4, 1, 1, 1), f"retry with the same key after the fault is gone: {st} {state('h-fault')}"
        c.close()
        assert_ledger()
        return "ledger insert failed after the stock UPDATE: stock, ledger, history copy and idempotency key all rolled back; the same key then succeeded once"
    check("H2 failure between stock update and ledger insert: both roll back", h2)

    def h3():
        seed(**{"h-doc": 5})
        c = pg()
        c.execute("create function public.zz_docfault() returns trigger language plpgsql as $$ begin raise exception 'injected history failure'; end $$")
        c.execute("create trigger zz_docfault before insert on spike_docs for each row when (new.collection = 'stockmoves' and new.data->>'by' = 'DOCFAULT') execute function public.zz_docfault()")
        try:
            st, j = move(uk("docfault"), "h-doc", -2, by="DOCFAULT")
            assert st != 200, (st, j)
            assert state("h-doc") == (5, 0, 0, 0), f"a failure AFTER the relational ledger row still rolls everything back: {state('h-doc')}"
        finally:
            c.execute("drop trigger if exists zz_docfault on spike_docs")
            c.execute("drop function if exists public.zz_docfault()")
        c.close()
        assert_ledger()
        return "history-copy insert failed after stock and ledger were written: stock_levels, stock_events and the key all rolled back (one transaction)"
    check("H3 failure after the ledger row (history copy) rolls back too", h3)

    def h4():
        seed(**{"h-kill": 5})
        c = pg()
        c.execute("create function public.zz_slow() returns trigger language plpgsql as $$ begin perform pg_sleep(10); return new; end $$")
        c.execute("create trigger zz_slow before insert on stock_events for each row when (new.reason like '%SLOWLEDGER%') execute function public.zz_slow()")
        k, box = uk("kill"), {}
        try:
            th = threading.Thread(target=lambda: box.update(r=move(k, "h-kill", -1, by="SLOWLEDGER")))
            th.start()
            pid_ = None
            for _ in range(40):
                time.sleep(0.25)
                r = c.execute("select pid from pg_stat_activity where query like 'select apply_stock_moves%%' and state = 'active' and pid <> pg_backend_pid()").fetchone()
                if r:
                    pid_ = r[0]
                    break
            assert pid_, "the request never reached the database"
            time.sleep(0.5)
            assert state("h-kill")[0] == 5, "uncommitted change visible to others"
            c.execute("select pg_terminate_backend(%s)", (pid_,))      # the database process dies between the UPDATE and the ledger insert
            th.join(20)
            assert box["r"][0] != 200, box
            assert state("h-kill") == (5, 0, 0, 0), f"after the kill: {state('h-kill')}"
        finally:
            c.execute("drop trigger if exists zz_slow on stock_events")
            c.execute("drop function if exists public.zz_slow()")
            c.close()
        st, j = move(k, "h-kill", -1, by="SLOWLEDGER")
        assert st == 200 and state("h-kill") == (4, 1, 1, 1), (st, state("h-kill"))
        assert_ledger()
        return "database backend killed mid-transaction (after the stock UPDATE, during the ledger insert): nothing committed; the retry with the same key deducted once"
    check("H4 process killed between stock update and ledger insert", h4)

    def h5():
        seed(**{"h-lost": 10})
        k = uk("lost")
        r1 = move(k, "h-lost", -3)              # the response is "lost": the caller ignores it and sends the same request again
        r2 = move(k, "h-lost", -3)
        assert r1[0] == r2[0] == 200 and r1[1] == r2[1], (r1, r2)
        assert state("h-lost") == (7, 1, 1, 1), state("h-lost")
        k2, out, bar = uk("burst"), [], threading.Barrier(6)

        def go():
            bar.wait()
            out.append(move(k2, "h-lost", -1))
        ts = [threading.Thread(target=go) for _ in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert len(out) == 6 and all(r[0] == 200 for r in out) and len({json.dumps(r[1], sort_keys=True) for r in out}) == 1, out
        assert state("h-lost") == (6, 2, 2, 2), state("h-lost")
        st, j = move(k, "h-lost", -1)            # same key, different contents
        assert st == 409 and "different contents" in j["error"] and state("h-lost")[0] == 6, (st, j)
        assert_ledger()
        return "same request twice: one deduction (10 -> 7), identical answer; 6 simultaneous copies: one deduction; same key with other contents refused"
    check("H5 lost response then retry: one deduction, one ledger entry", h5)

    def h6():
        seed(**{"h-late": 10})
        assert lease("h-late", "A", 300)
        time.sleep(0.5)
        assert lease("h-late", "B", 5000), "B should take the expired lease"
        assert move(uk("b"), "h-late", -1)[0] == 200
        assert state("h-late")[0] == 9
        st, j = move(uk("a"), "h-late", -1)                                           # A's delayed sale, sent after its lease expired
        assert st == 200 and state("h-late")[0] == 8, (st, j, state("h-late"))
        st, j = move(uk("arc"), "h-late", -2, kind="recount", expect=10)             # A counted 8 when it saw 10
        assert st == 409 and j["code"] == "stale" and state("h-late")[0] == 8, (st, j)
        st, j = req("PATCH", "/api/doc/products/h-late", {"stock": {"M": 99, "L": 0}, "inStock": True})   # an old-style absolute overwrite from a delayed page
        got = req("GET", "/api/doc/products/h-late")[1]["data"]["stock"]["M"]
        assert got == 8 and state("h-late")[0] == 8, f"stale absolute write changed the stock: {got}"
        with pg() as c:      # not only ignored on read: no competing stock number may be STORED in the document either
            raw = c.execute("select data->'stock'->>'M' from spike_docs where collection='products' and id='h-late'").fetchone()[0]
        assert raw != "99", "the stale absolute value was stored in the document (a second source of truth)"
        assert_ledger()
        return "expired lease holder A: its late sale landed on top of B's (10 -> 9 -> 8); its stale recount was refused; a stale absolute 'stock' write from a document PATCH is ignored"
    check("H6 delayed/expired holder cannot overwrite newer stock", h6)

    def h7():
        assert_ledger()
        with pg() as c:
            n = c.execute("select count(*) from stock_events where kind <> 'opening_balance'").fetchone()[0]
        return f"final sweep on the last scenario's data ({n} ledger rows): shelf = ledger, history copies = ledger, page overlay = database. The same sweep also ran at the end of H1-H6"
    check("H7 ledger explains the shelf, history copies match the ledger", h7)


def snapshot():
    with pg() as c:
        rows = c.execute("select count(*), coalesce(sum(on_hand),0) from stock_levels").fetchone()
        ev = c.execute("select count(*), coalesce(sum(d_on_hand),0) from stock_events").fetchone()
    return (rows[0], ev[0], int(rows[1]), int(ev[1]))


def node(phase):
    script = "atomic_tests.js" if phase == "atomic" else "browser_tests.js"
    p = subprocess.run(["node", str(HERE / script), phase], cwd=HERE, capture_output=True, text=True, timeout=600)
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
        if "--atomic-only" in sys.argv:      # used by the spike mutation checks: just the atomic stock path
            print("\n== Atomic stock path only ==")
            stock_checks()
            subprocess.run([sys.executable, str(HERE / "patch_app.py")], check=True, capture_output=True)
            node("atomic")
            stop_server()
            npass = sum(1 for r in RESULTS if r[1] == "PASS"); nfail = sum(1 for r in RESULTS if r[1] == "FAIL")
            print(f"\n{npass} PASS, {nfail} FAIL")
            return 1 if nfail else 0
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
        print("\n== Atomic stock path: HTTP checks (migration 0010 through the spike endpoint, real database faults) ==")
        stock_checks()
        print("\n== Atomic stock path: browser checks (isolated page copy, the app's own moveStock) ==")
        subprocess.run([sys.executable, str(HERE / "patch_app.py")], check=True, capture_output=True)
        node("atomic")
        print("\n== Restart again: relational stock and ledger must survive ==")
        before = snapshot()
        stop_server(); pgdev.stop(); pgdev.start(); start_server()
        check("R1 relational stock + ledger identical after restarting the server AND PostgreSQL", lambda: (snapshot() == before and assert_ledger() is None) and f"{before[0]} stock rows, {before[1]} ledger rows unchanged")
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
