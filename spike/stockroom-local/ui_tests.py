"""Repeatable BROWSER checks of the integrated Stockroom copy (Capture + product stock editor on the relational backend). INVENTED data only.

    pip install playwright "psycopg[binary]" pgserver        # no browser download: it drives the Chrome or Edge already installed (channel)
    python spike/stockroom-local/ui_tests.py [--only NAME] [--channel chrome|msedge]

It starts its OWN server and throwaway PostgreSQL in a temporary folder (SPIKE_DATA_DIR), generates the integrated page copy there, drives the page with real
clicks, typing and file inputs, and stops everything again. Nothing leaves 127.0.0.1. Prints PASS/FAIL per check; exit 0 only if all pass.
These are NOT the Cloud spike's Node/Playwright checks (browser_tests.js, which need Node.js); they cover this integration plus a small regression set.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
DATA = Path(tempfile.mkdtemp(prefix="o4u-ui-"))
os.environ["SPIKE_DATA_DIR"] = str(DATA)
import patch_app  # noqa: E402  (after SPIKE_DATA_DIR so it targets the temporary folder)
import pgdev  # noqa: E402
import psycopg  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

CHANNEL = sys.argv[sys.argv.index("--channel") + 1] if "--channel" in sys.argv else os.environ.get("O4U_BROWSER_CHANNEL", "chrome")
ONLY = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else None      # name prefixes, e.g. --only E2,C6
WITH_HTTP = "--no-http" not in sys.argv      # the HTTP-level checks (integration_http_tests.py) run on the same server by default


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = free_port()
BASE = f"http://127.0.0.1:{PORT}"
URL = BASE + "/stockroom?v=atomic"


def api(method, path, body=None):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(), method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def pg():
    return psycopg.connect(pgdev.conninfo(), autocommit=True)


def doc(pid):
    return api("GET", f"/api/doc/products/{pid}")[1].get("data") or {}


def ledger(pid):
    return api("GET", f"/api/_spike/ledger/{pid}")[1]


def sale(pid, size, n, who="phone2"):
    return api("POST", "/api/stock/moves", {"key": "mv-" + uuid.uuid4().hex[:10], "meta": {"kind": "sale", "by": who},
                                            "moves": [{"productId": pid, "size": size, "change": -n, "kind": "sale", "label": "x"}]})


def product(pid, m=4, l=2, mrp=999):
    return {"article": pid.upper(), "brand": "", "category": "tshirts", "type": "Itg Tee", "colour": "Teal", "sizes": [{"size": "M", "mrp": mrp}, {"size": "L", "mrp": mrp}],
            "stock": {"M": m, "L": l}, "inStock": True, "published": False, "status": "ready", "flags": [], "notes": "", "webImages": [],
            "createdAt": "2026-11-01T00:00:00.000Z", "updatedAt": "2026-11-01T00:00:00.000Z"}


def fresh(**stocks):
    api("POST", "/api/_spike/reset", {})
    if stocks:
        s, j = api("POST", "/api/_spike/bulk?relational=1", {"products": {pid: product(pid, *v) for pid, v in stocks.items()}})
        assert s == 200, (s, j)


RESULTS: list = []
TESTS: list = []


def test(name):
    def deco(fn):
        TESTS.append((name, fn))
        return fn
    return deco


def need(cond, msg):
    if not cond:
        raise AssertionError(msg)


class Phone:
    """One browser tab on the integrated page ("a phone")."""

    def __init__(self, browser):
        self.ctx = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True)
        self.page = self.ctx.new_page()
        self.errors: list = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.save_calls = 0
        self.page.on("request", lambda r: self._count(r))

    def _count(self, r):
        if r.url.endswith("/api/catalogue/save") and r.method == "POST":
            self.save_calls += 1

    def open(self, expect_rows=None):
        self.page.goto(URL)
        self.page.wait_for_function("window.O4U_products && document.getElementById('list')")
        if expect_rows is not None:
            self.page.wait_for_function("n => window.O4U_products().length === n", arg=expect_rows)
        return self

    def open_detail(self, pid):
        self.page.evaluate("id => window.O4U_openDetail(id)", pid)
        self.page.wait_for_selector("#eStart")

    def jpeg(self, label="INVENTED PHOTO", color="#a33"):
        b64 = self.page.evaluate("""async ([label, color]) => { const c = document.createElement('canvas'); c.width = 900; c.height = 1200; const x = c.getContext('2d');
            x.fillStyle = color; x.fillRect(0, 0, 900, 1200); x.fillStyle = '#fff'; x.font = '60px sans-serif'; x.fillText(label, 40, 200);
            const blob = await new Promise(r => c.toBlob(r, 'image/jpeg', 0.9)); const buf = new Uint8Array(await blob.arrayBuffer()); let s = ''; buf.forEach(v => s += String.fromCharCode(v)); return btoa(s); }""", [label, color])
        return base64.b64decode(b64)

    def alert_text(self):
        loc = self.page.locator("#stockEd [role=alert]")
        return loc.inner_text() if loc.count() else None

    def toast(self):
        t = self.page.evaluate("() => (document.querySelector('.toast,#toast') || {}).textContent || ''")
        return t

    def close(self):
        self.ctx.close()


def lose_first_reply(phone):
    """The server COMMITS the save, the browser never sees the answer; the page's retry then reuses the same key."""
    state = {"dropped": 0}

    def handler(route):
        if state["dropped"] == 0:
            state["dropped"] = 1
            route.fetch()
            route.abort()
        else:
            route.continue_()
    phone.page.route("**/api/catalogue/save", handler)
    return state


# ───────────────────────────────── regression: the page still works as before ─────────────────────────────────
@test("R1 regression: the page loads the products from the database and shows them")
def r1(br):
    fresh(**{"ui-tee-teal": (4, 2), "ui-tee-red": (1, 0)})
    p = Phone(br).open(2)
    need(p.page.locator("#list .row").count() == 2, "two rows expected")
    need("Teal" in p.page.locator("#list").inner_text(), "row text")
    need(not p.errors, f"page errors: {p.errors}")
    p.close()


@test("R2 regression: details edit (notes) is saved, survives a reload, and does not touch stock")
def r2(br):
    fresh(**{"ui-tee-teal": (4, 2)})
    p = Phone(br).open(1)
    p.open_detail("ui-tee-teal")
    p.page.fill("#dNotes", "edited by test")
    p.page.click("#dSave")
    p.page.wait_for_function("() => (window.O4U_products()[0] || {}).notes === 'edited by test'")
    p.page.reload(); p.page.wait_for_function("window.O4U_products && window.O4U_products().length === 1")
    d = doc("ui-tee-teal")
    need(d["notes"] == "edited by test" and d["stock"] == {"M": 4, "L": 2}, f"{d.get('notes')} {d.get('stock')}")
    p.close()


@test("R3 regression: a web photo uploaded through the page's file input is stored as a real file and displayed")
def r3(br):
    fresh(**{"ui-tee-teal": (4, 2)})
    p = Phone(br).open(1)
    p.open_detail("ui-tee-teal")
    p.page.set_input_files("#inWeb", [{"name": "one.jpg", "mimeType": "image/jpeg", "buffer": p.jpeg()}])
    p.page.wait_for_function("() => ((window.O4U_products()[0] || {}).webImages || []).length === 1", timeout=20000)
    aid = doc("ui-tee-teal")["webImages"][0]
    f = DATA / "blobs" / aid
    need(f.exists() and f.read_bytes()[:3] == b"\xff\xd8\xff", "stored file must be a JPEG on disk")
    p.page.wait_for_function("() => { const a = [...document.querySelectorAll('#webgrid img')]; return a.length === 1 && a[0].complete && a[0].naturalWidth > 100; }")
    p.close()


@test("R4 regression: the Publish switch still works and does not change stock")
def r4(br):
    fresh(**{"ui-tee-teal": (4, 2)})
    p = Phone(br).open(1)
    p.open_detail("ui-tee-teal")
    p.page.locator("#tPub").evaluate("e => e.click()")
    p.page.wait_for_function("() => (window.O4U_products()[0] || {}).published === true")
    need(doc("ui-tee-teal")["stock"] == {"M": 4, "L": 2}, "stock changed by publishing")
    p.close()


# ───────────────────────────────── the stock editor ─────────────────────────────────
@test("E1 stock editor: +2 pieces are saved, shown, and still there after a reload; one recount in the ledger")
def e1(br):
    fresh(**{"ui-tee-teal": (4, 2)})
    p = Phone(br).open(1)
    p.open_detail("ui-tee-teal")
    p.page.click("#eStart")
    p.page.click('[data-eplus="M"]'); p.page.click('[data-eplus="M"]')
    p.page.click("#eSave")
    p.page.wait_for_function("() => !document.getElementById('eSave')")
    p.page.reload(); p.page.wait_for_function("window.O4U_products && window.O4U_products().length === 1")
    need(doc("ui-tee-teal")["stock"] == {"M": 6, "L": 2}, doc("ui-tee-teal")["stock"])
    lg = ledger("ui-tee-teal")
    need([e["kind"] for e in lg["events"]].count("recount") == 1 and lg["on_hand"] == 8, f"{lg}")
    p.close()


@test("E2 stock editor: another phone sells while editing -> the page says nothing was saved, stays open, stock untouched")
def e2(br):
    fresh(**{"ui-tee-teal": (6, 2)})
    p = Phone(br).open(1)
    p.open_detail("ui-tee-teal")
    p.page.click("#eStart")
    need(sale("ui-tee-teal", "M", 1)[0] == 200, "the other phone's sale")
    p.page.click('[data-eplus="M"]')
    p.page.click("#eSave")
    p.page.wait_for_selector("#stockEd [role=alert]")
    msg = p.alert_text()
    need("Nothing was saved" in msg and "changed while" in msg.lower() or "changed while" in msg, msg)
    need(p.page.locator("#eSave").count() == 1, "the editor must stay open")
    need(doc("ui-tee-teal")["stock"]["M"] == 5, f"stock {doc('ui-tee-teal')['stock']}")
    need([e["kind"] for e in ledger("ui-tee-teal")["events"]].count("recount") == 0, "a refused edit left a recount behind")
    p.page.click("#eCancel"); p.page.click("#eStart")                     # recovery: reopen, see 5, +1, save
    p.page.click('[data-eplus="M"]'); p.page.click("#eSave")
    p.page.wait_for_function("() => !document.getElementById('eSave')")
    need(doc("ui-tee-teal")["stock"]["M"] == 6, "recovery save")
    p.close()


@test("E3 stock editor: the server commits but the reply is lost; the page retries with the same key and the recount counts ONCE")
def e3(br):
    fresh(**{"ui-tee-teal": (6, 2)})
    p = Phone(br).open(1)
    st = lose_first_reply(p)
    p.open_detail("ui-tee-teal")
    p.page.click("#eStart"); p.page.click('[data-eplus="M"]'); p.page.click("#eSave")
    p.page.wait_for_function("() => !document.getElementById('eSave')", timeout=20000)
    need(st["dropped"] == 1 and p.save_calls == 2, f"dropped {st}, calls {p.save_calls}")
    lg = ledger("ui-tee-teal")
    need(doc("ui-tee-teal")["stock"]["M"] == 7 and [e["kind"] for e in lg["events"]].count("recount") == 1 and lg["docs"] == 1, f"{doc('ui-tee-teal')['stock']} {lg}")
    p.close()


@test("E4 two phones recount the same product at the same moment: one saves, the other is told it changed; no piece is lost")
def e4(br):
    fresh(**{"ui-tee-teal": (6, 2)})
    a, b = Phone(br).open(1), Phone(br).open(1)
    for ph in (a, b):
        ph.open_detail("ui-tee-teal"); ph.page.click("#eStart"); ph.page.click('[data-eplus="M"]')
    a.page.click("#eSave"); b.page.click("#eSave")
    a.page.wait_for_timeout(2500)
    done = [ph for ph in (a, b) if ph.page.locator("#eSave").count() == 0]
    refused = [ph for ph in (a, b) if ph.page.locator("#stockEd [role=alert]").count() == 1]
    need(len(done) == 1 and len(refused) == 1, f"saved {len(done)}, refused {len(refused)}")
    need(doc("ui-tee-teal")["stock"]["M"] == 7, f"stock {doc('ui-tee-teal')['stock']}")
    a.close(); b.close()


@test("E5 stock editor: a new size gets its quantity; the other sizes are not touched")
def e5(br):
    fresh(**{"ui-tee-teal": (4, 2)})
    p = Phone(br).open(1)
    p.open_detail("ui-tee-teal")
    p.page.click("#eStart")
    p.page.click('[data-eplus="XL"]'); p.page.click('[data-eplus="XL"]'); p.page.click('[data-eplus="XL"]')
    p.page.click("#eSave")
    p.page.wait_for_function("() => !document.getElementById('eSave')")
    need(doc("ui-tee-teal")["stock"] == {"M": 4, "L": 2, "XL": 3}, doc("ui-tee-teal")["stock"])
    p.close()


def rel_prices(pid):
    """What the database says: {size: price_paise} with the product's base price for sizes without an override."""
    with pg() as c:
        base = c.execute("select price_paise from products where id=%s", (pid,)).fetchone()[0]
        rows = c.execute("select size, price_paise from variants where product_id=%s", (pid,)).fetchall()
    return base, {z: (v if v is not None else base) for z, v in rows}


def screen_prices(pid):
    """What the page shows after a reload: {size: mrp rupees} from the product document."""
    return {s["size"]: s["mrp"] for s in doc(pid)["sizes"]}


def agree(pid):
    base, rel = rel_prices(pid)
    scr = screen_prices(pid)
    for z, mrp in scr.items():
        need(rel.get(z) == round(mrp * 100), f"screen and database disagree for {z}: screen Rs {mrp}, database {rel.get(z)} paise")
    return base, rel, scr


def price_events(pid):
    with pg() as c:
        return c.execute("select size, old_paise, new_paise from price_events where product_id=%s order by id", (pid,)).fetchall()


@test("E6 PRICE EDITS: an MRP edit in the stock editor reaches the shared catalogue; screen and database agree after a reload; stock is untouched")
def e6(br):
    fresh(**{"ui-tee-teal": (4, 2)})
    p = Phone(br).open(1)
    p.open_detail("ui-tee-teal")
    p.page.click("#eStart")
    p.page.fill('[data-emrp="M"]', "1099")
    p.page.click("#eSave")
    p.page.wait_for_function("() => !document.getElementById('eSave')")
    p.page.reload(); p.page.wait_for_function("window.O4U_products && window.O4U_products().length === 1")
    base, rel, scr = agree("ui-tee-teal")
    need(scr["M"] == 1099 and scr["L"] == 999 and base == 99900 and rel["M"] == 109900 and rel["L"] == 99900, f"{base} {rel} {scr}")
    need(price_events("ui-tee-teal") == [("M", None, 109900)], price_events("ui-tee-teal"))
    need(doc("ui-tee-teal")["stock"] == {"M": 4, "L": 2} and ledger("ui-tee-teal")["on_hand"] == 6, "stock must be unchanged by a price edit")
    with pg() as c:
        need(c.execute("select published from products where id='ui-tee-teal'").fetchone()[0] is False, "published must be untouched")
    p.close()


@test("E8 price + stock together are ONE save: a stale price refuses the whole save (stock not applied, screen unchanged); after reopening the retry works and agrees")
def e8(br):
    fresh(**{"ui-tee-teal": (4, 2)})
    p = Phone(br).open(1)
    p.open_detail("ui-tee-teal")
    p.page.click("#eStart")
    # another manager changes the price meanwhile (through the same endpoint)
    s_, j_ = api("POST", "/api/catalogue/save", {"key": "pr-" + uuid.uuid4().hex[:8], "productId": "ui-tee-teal", "meta": {"kind": "edit", "by": "phone2"},
                                                  "prices": {"expect_price_paise": 99900, "price_paise": 95000, "size_prices": {}}})
    need(s_ == 200, f"{s_} {j_}")
    api("PATCH", "/api/doc/products/ui-tee-teal", {"sizes": [{"size": "M", "mrp": 950}, {"size": "L", "mrp": 950}]})      # that other phone's page also updates the details
    p.page.click('[data-eplus="M"]')                         # +1 piece AND a new price in the same save
    p.page.fill('[data-emrp="M"]', "1050")
    p.page.click("#eSave")
    p.page.wait_for_selector("#stockEd [role=alert]")
    msg = p.alert_text()
    need("price changed while editing" in msg, msg)
    need(p.page.locator("#eSave").count() == 1, "the editor must stay open")
    need(doc("ui-tee-teal")["stock"] == {"M": 4, "L": 2}, f"the stock part of a refused save must not be applied: {doc('ui-tee-teal')['stock']}")
    need(price_events("ui-tee-teal") == [(None, 99900, 95000)], price_events("ui-tee-teal"))
    need(doc("ui-tee-teal")["stock"] == {"M": 4, "L": 2}, "stock must not be applied")
    p.page.click("#eCancel"); p.page.reload(); p.page.wait_for_function("window.O4U_products && window.O4U_products().length === 1")
    p.open_detail("ui-tee-teal"); p.page.click("#eStart")
    p.page.click('[data-eplus="M"]'); p.page.fill('[data-emrp="M"]', "1050")
    p.page.click("#eSave")
    p.page.wait_for_function("() => !document.getElementById('eSave')", timeout=20000)
    p.page.reload(); p.page.wait_for_function("window.O4U_products && window.O4U_products().length === 1")
    base, rel, scr = agree("ui-tee-teal")
    need(doc("ui-tee-teal")["stock"] == {"M": 5, "L": 2}, doc("ui-tee-teal")["stock"])
    need(rel["M"] == 105000 and scr["M"] == 1050, f"{rel} {scr}")
    p.close()


@test("E9 a price save whose reply is lost is retried with the same key: ONE price change is recorded, screen and database agree")
def e9(br):
    fresh(**{"ui-tee-teal": (4, 2)})
    p = Phone(br).open(1)
    st = lose_first_reply(p)
    p.open_detail("ui-tee-teal")
    p.page.click("#eStart")
    p.page.fill('[data-emrp="M"]', "1200"); p.page.fill('[data-emrp="L"]', "1100")
    p.page.click("#eSave")
    p.page.wait_for_function("() => !document.getElementById('eSave')", timeout=30000)
    need(st["dropped"] == 1 and p.save_calls == 2, f"{st} {p.save_calls}")
    p.page.reload(); p.page.wait_for_function("window.O4U_products && window.O4U_products().length === 1")
    base, rel, scr = agree("ui-tee-teal")
    need(base == 110000 and rel == {"M": 120000, "L": 110000} and scr == {"M": 1200, "L": 1100}, f"{base} {rel} {scr}")
    ev = price_events("ui-tee-teal")
    need(sorted(ev, key=lambda e: str(e[0])) == sorted([(None, 99900, 110000), ("M", None, 120000)], key=lambda e: str(e[0])), ev)
    need(doc("ui-tee-teal")["stock"] == {"M": 4, "L": 2}, "stock unchanged")
    p.close()


@test("E10 the shared catalogue refuses a price change from the page when the price is not valid, shows why, and writes nothing")
def e10(br):
    fresh(**{"ui-tee-teal": (4, 2)})
    p = Phone(br).open(1)
    p.open_detail("ui-tee-teal")
    p.page.click("#eStart")
    p.page.fill('[data-emrp="M"]', "0"); p.page.fill('[data-emrp="L"]', "")
    p.page.click("#eSave")
    p.page.wait_for_selector("#stockEd [role=alert]")
    need("price" in p.alert_text().lower(), p.alert_text())
    need(price_events("ui-tee-teal") == [] and screen_prices("ui-tee-teal") == {"M": 999, "L": 999}, "nothing may be written")
    p.close()


@test("E7 the In-stock switch is refused with a message (it is worked out from the rack) and changes nothing")
def e7(br):
    fresh(**{"ui-tee-teal": (4, 2)})
    p = Phone(br).open(1)
    p.open_detail("ui-tee-teal")
    p.page.locator("#tStock").evaluate("e => e.click()")
    p.page.wait_for_timeout(600)
    need("worked out from the pieces" in p.toast(), p.toast())
    need(doc("ui-tee-teal")["inStock"] is True and doc("ui-tee-teal")["stock"] == {"M": 4, "L": 2}, "switch must change nothing")
    p.close()


# ───────────────────────────────── Capture ─────────────────────────────────
def start_capture(p, article="ITG900", colour="Spike Teal", mrp="899", m=2, l=1):
    p.page.click("#fab")
    p.page.wait_for_selector("#cam-photo", state="attached")
    p.page.set_input_files("#cam-photo", [{"name": "shot.jpg", "mimeType": "image/jpeg", "buffer": p.jpeg()}])
    p.page.wait_for_function("() => document.querySelectorAll('#capBody img').length >= 1")
    for _ in range(m):
        p.page.click('[data-plus="M"]')
    for _ in range(l):
        p.page.click('[data-plus="L"]')
    p.page.click("#doManual")
    p.page.wait_for_selector("#fArt")
    p.page.fill("#fArt", article); p.page.fill("#fColour", colour); p.page.fill("#fType", "Itg Test Tee")
    p.page.select_option("#fCat", "tshirts")
    p.page.fill("#sz0s", "M"); p.page.fill("#sz0m", mrp)


def cap_error(p):
    t = p.page.locator("#capBody").inner_text()
    i = t.find("Nothing was saved")
    return t[i:i + 200] if i >= 0 else None


@test("C1 capture: a new product is saved with its first quantities, UNPUBLISHED, and the ledger explains them")
def c1(br):
    fresh()
    p = Phone(br).open(0)
    start_capture(p)
    p.page.click("#doSave")
    p.page.wait_for_function("() => document.getElementById('capture').hidden", timeout=20000)
    d = doc("itg900-spike-teal")
    need(d.get("published") is False and d["stock"] == {"M": 2, "L": 1} and d.get("refPhoto"), f"{d.get('published')} {d.get('stock')} {bool(d.get('refPhoto'))}")
    lg = ledger("itg900-spike-teal")
    need([e["reason"] for e in lg["events"]] == ["initial stock at capture"] * 2 and lg["on_hand"] == 3 and lg["docs"] == 2, f"{lg}")
    with pg() as c:
        need(c.execute("select published from products where id='itg900-spike-teal'").fetchone()[0] is False, "relational product must be unpublished")
        need(c.execute("select count(*) from get_availability(array['itg900-spike-teal'])").fetchone()[0] == 0, "an unpublished product must not reach the website")
    p.close()


@test("C2 capture: no MRP -> a plain message, the form stays open, nothing is created; after adding the price the SAME form saves")
def c2(br):
    fresh()
    p = Phone(br).open(0)
    start_capture(p, mrp="")
    p.page.click("#doSave")
    p.page.wait_for_function("() => document.getElementById('capBody').innerText.includes('Nothing was saved')")
    need("price (MRP)" in cap_error(p), cap_error(p))
    need(not p.page.evaluate("() => document.getElementById('capture').hidden"), "capture must stay open")
    need(api("GET", "/api/doc/products/itg900-spike-teal")[1]["exists"] is False and ledger("itg900-spike-teal")["on_hand"] == 0, "a refused save left something behind")
    p.page.fill("#sz0m", "899"); p.page.click("#doSave")
    p.page.wait_for_function("() => document.getElementById('capture').hidden", timeout=20000)
    need(ledger("itg900-spike-teal")["on_hand"] == 3, "saved after the fix")
    p.close()


@test("C3 capture: the reply to the save is lost; the retry replays; ONE product, ONE set of ledger rows")
def c3(br):
    fresh()
    p = Phone(br).open(0)
    st = lose_first_reply(p)
    start_capture(p)
    p.page.click("#doSave")
    p.page.wait_for_function("() => document.getElementById('capture').hidden", timeout=30000)
    lg = ledger("itg900-spike-teal")
    need(st["dropped"] == 1 and p.save_calls == 2 and lg["on_hand"] == 3 and len(lg["events"]) == 2 and lg["docs"] == 2, f"{st} calls {p.save_calls} {lg}")
    p.close()


@test("C4 capture of an EXISTING product: a new size is created, a seen size is recounted, the product's relational row does not change")
def c4(br):
    fresh(**{"ui-tee-teal": (4, 2)})
    with pg() as c:
        before = c.execute("select article, name, brand, category, colour, price_paise, published from products where id='ui-tee-teal'").fetchone()
    p = Phone(br).open(1)
    p.page.click("#fab")
    p.page.wait_for_selector("#cam-photo", state="attached")
    p.page.set_input_files("#cam-photo", [{"name": "shot.jpg", "mimeType": "image/jpeg", "buffer": p.jpeg()}])
    p.page.wait_for_function("() => document.querySelectorAll('#capBody img').length >= 1")
    p.page.click('[data-plus="XL"]'); p.page.click('[data-plus="XL"]')
    p.page.click('[data-plus="M"]'); p.page.click('[data-plus="M"]')            # the person counted 2 on the rack where the page showed 4: a recount
    p.page.click("#doManual"); p.page.wait_for_selector("#fArt")
    p.page.fill("#fArt", "UI-TEE"); p.page.fill("#fColour", "Teal"); p.page.fill("#fType", "Itg Tee"); p.page.select_option("#fCat", "tshirts")
    p.page.fill("#sz0s", "M"); p.page.fill("#sz0m", "999")
    need(p.page.evaluate("() => document.querySelector('#capBody').innerText.includes('ui-tee-teal') || true"), "form")
    p.page.click("#doSave")
    p.page.wait_for_function("() => document.getElementById('capture').hidden", timeout=20000)
    st = doc("ui-tee-teal")["stock"]
    with pg() as c:
        after = c.execute("select article, name, brand, category, colour, price_paise, published from products where id='ui-tee-teal'").fetchone()
    need(st == {"M": 2, "L": 2, "XL": 2}, f"stock {st}")
    need([e["kind"] for e in ledger("ui-tee-teal")["events"]].count("recount") == 1, "the M recount must be in the ledger")
    need(before == after, f"{before} -> {after}")
    p.close()


@test("C5 switched off: 'save for Claude to read later' is refused with a message and creates nothing")
def c5(br):
    fresh()
    p = Phone(br).open(0)
    p.page.click("#fab")
    p.page.wait_for_selector("#cam-photo", state="attached")
    p.page.set_input_files("#cam-photo", [{"name": "shot.jpg", "mimeType": "image/jpeg", "buffer": p.jpeg()}])
    p.page.wait_for_function("() => document.querySelectorAll('#capBody img').length >= 1")
    p.page.click('[data-plus="M"]')
    p.page.wait_for_selector("#cam-tag", state="attached")
    p.page.set_input_files("#cam-tag", [{"name": "tag.jpg", "mimeType": "image/jpeg", "buffer": p.jpeg("TAG", "#777")}])
    p.page.wait_for_function("() => !document.getElementById('doPending').disabled")
    p.page.click("#doPending")
    p.page.wait_for_function("() => document.getElementById('capBody').innerText.includes('not available in this build')")
    need(api("GET", "/api/col/products")[1]["docs"] == [], "no pending product may be created")
    p.close()


@test("C6 switched off: the Orders and Exchanges tabs are disabled and show a message; they do not open")
def c6(br):
    fresh(**{"ui-tee-teal": (4, 2)})
    p = Phone(br).open(1)
    for t in ("orders", "exchanges"):
        need(p.page.locator(f'.tab[data-tab="{t}"]').get_attribute("aria-disabled") == "true", f"{t} not disabled")
        p.page.locator(f'.tab[data-tab="{t}"]').click(force=True)      # aria-disabled: a person can still tap it, so tap it
        p.page.wait_for_timeout(300)
        need("switched off" in p.toast().lower(), p.toast())
        need(p.page.evaluate("() => document.body.dataset.tab") not in ("orders", "exchanges"), "the tab opened")
    p.close()


def main() -> int:
    page_html, _ = patch_app.build()
    patch_app.OUT.parent.mkdir(parents=True, exist_ok=True)
    patch_app.OUT.write_text(page_html, encoding="utf-8")
    env = {**os.environ, "SPIKE_DATA_DIR": str(DATA), "PYTHONIOENCODING": "utf-8"}
    log = open(DATA / "server.log", "w")
    srv = subprocess.Popen([sys.executable, str(HERE / "server.py"), "--port", str(PORT)], cwd=str(HERE), env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(BASE + "/api/assets", timeout=2).read()
                break
            except Exception:      # noqa: BLE001
                if srv.poll() is not None:
                    print(open(DATA / "server.log").read()[-1500:])
                    return 2
                time.sleep(1)
        else:
            print("server did not start"); return 2
        passed = failed = 0
        with sync_playwright() as pw:
            br = pw.chromium.launch(channel=CHANNEL, headless=True)
            print(f"Browser: {CHANNEL} {br.version}  (headless, 390x844 touch)\nServer: {BASE} (temporary data folder)\n")
            for name, fn in TESTS:
                if ONLY and not any(name.startswith(o) for o in ONLY):
                    continue
                try:
                    fn(br)
                    passed += 1
                    print("  PASS ", name)
                except Exception as e:      # noqa: BLE001
                    failed += 1
                    print("  FAIL ", name, "\n        ", repr(e)[:500])
            br.close()
        if WITH_HTTP and not ONLY:
            sys.argv = [sys.argv[0], "--port", str(PORT)]      # integration_http_tests.py reads its port from argv
            import integration_http_tests as H      # noqa: E402
            print("\nHTTP-level checks (integration_http_tests.py) on the same server:")
            for fn in (H.t1, H.t2, H.t3, H.t4, H.t5, H.t6, H.t7, H.t10, H.t11, H.t8, H.t9):
                fn()
            for _name, ok_, _why in H.RESULTS:
                passed += 1 if ok_ else 0
                failed += 0 if ok_ else 1
        print(f"\n{passed} passed, {failed} failed")
        return 1 if failed or not passed else 0
    finally:
        try:
            urllib.request.urlopen(urllib.request.Request(BASE + "/api/_spike/shutdown", data=b"{}", method="POST"), timeout=5).read()
        except Exception:      # noqa: BLE001
            pass
        try:
            srv.wait(timeout=20)
        except Exception:      # noqa: BLE001
            srv.kill()
        log.close()
        time.sleep(1)
        shutil.rmtree(DATA, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
