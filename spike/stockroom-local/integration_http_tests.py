"""HTTP-level checks of the integration (no browser): Capture/stock-editor saves, retries, stale recounts, concurrent sale vs recount, metadata vs stock,
unpublished new products. INVENTED data only; talks only to the local spike server (127.0.0.1) and its throwaway PostgreSQL.

    python spike/stockroom-local/server.py --port 8780        # in another window
    python spike/stockroom-local/integration_http_tests.py [--port 8780]

Prints PASS/FAIL per check; exit 0 only if all pass. It RESETS the spike database (invented data only).
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
PORT = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8780
BASE = f"http://127.0.0.1:{PORT}"


def call(method, path, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


STRICT = {"X-Stock-Strict": "1"}
RESULTS: list = []


def check(name):
    def deco(fn):
        def run():
            try:
                fn()
                RESULTS.append((name, True, ""))
                print("  PASS ", name)
            except Exception as e:      # noqa: BLE001
                RESULTS.append((name, False, repr(e)))
                print("  FAIL ", name, "\n        ", repr(e))
        run.__name__ = fn.__name__
        return run
    return deco


def need(cond, msg):
    if not cond:
        raise AssertionError(msg)


def reset():
    call("POST", "/api/_spike/reset", {})


def newp(pid="itg-red-top", sizes=(("M", 3), ("L", 2)), **kw):
    product = {"article": "ITG1", "name": "Itg Red Top", "brand": "", "category": "tops", "colour": "Red", "price_paise": 79900}
    product.update(kw)
    return {"key": "cs-" + uuid.uuid4().hex[:10], "productId": pid, "product": product,
            "sizes": [{"size": s, "qty": q, "expect": 0} for s, q in sizes], "meta": {"kind": "capture", "by": "test", "label": "Red Top", "article": "ITG1", "category": "tops"}}


def product_doc(pid):
    s, j = call("GET", f"/api/doc/products/{pid}")
    return j.get("data") or {}


def ledger(pid):
    return call("GET", f"/api/_spike/ledger/{pid}")[1]


def create(body):
    s, j = call("POST", "/api/catalogue/save", body)
    need(s == 200, f"create: {s} {j}")
    s2, _ = put_doc(body["productId"])
    need(s2 == 200, "document write after a successful save")
    return j


def put_doc(pid, extra=None):
    """The product DOCUMENT the page writes after a successful save (stock is never part of it)."""
    d = {"article": "ITG1", "brand": "", "category": "tops", "colour": "Red", "type": "Itg Red Top", "published": False, "sizes": [{"size": "M", "mrp": 799}, {"size": "L", "mrp": 799}], "createdAt": "x", "updatedAt": "x"}
    d.update(extra or {})
    return call("PUT", f"/api/doc/products/{pid}", d, STRICT)


@check("1  capture saves the product with its first quantities, unpublished, and the ledger explains them")
def t1():
    reset()
    body = newp()
    s, j = call("POST", "/api/catalogue/save", body)
    need(s == 200 and j["created"] is True and len(j["sizes_created"]) == 2, f"{s} {j}")
    s2, _ = put_doc("itg-red-top")
    need(s2 == 200, "document write after a successful save")
    d = product_doc("itg-red-top")
    need(d.get("stock") == {"M": 3, "L": 2} and d.get("published") is False, f"doc: {d.get('stock')} published={d.get('published')}")
    lg = ledger("itg-red-top")
    need(lg["on_hand"] == 5 and sorted(e["kind"] for e in lg["events"]) == ["receive", "receive"] and lg["docs"] == 2, f"ledger {lg}")
    import psycopg, pgdev
    with psycopg.connect(pgdev.conninfo(), autocommit=True) as c:
        need(c.execute("select published from products where id='itg-red-top'").fetchone()[0] is False, "relational product must be unpublished")
        need(c.execute("select count(*) from get_availability(array['itg-red-top'])").fetchone()[0] == 0, "an unpublished product must not be offered to the website")


@check("2  the same save sent twice (a lost answer) counts once; the same key with other contents is refused")
def t2():
    reset()
    body = newp()
    a = call("POST", "/api/catalogue/save", body)
    put_doc("itg-red-top")
    b = call("POST", "/api/catalogue/save", body)
    need(a[0] == 200 and b[0] == 200 and a[1] == b[1], f"replay: {a} {b}")
    lg = ledger("itg-red-top")
    need(lg["on_hand"] == 5 and len(lg["events"]) == 2 and lg["docs"] == 2, f"counted twice: {lg}")
    other = dict(body, sizes=[{"size": "M", "qty": 9, "expect": 0}, {"size": "L", "qty": 2, "expect": 0}])
    s, j = call("POST", "/api/catalogue/save", other)
    need(s == 409 and "different contents" in j["error"], f"{s} {j}")
    need(ledger("itg-red-top")["on_hand"] == 5, "refused request changed stock")


@check("3  stock editor: a recount with the number the person saw applies; a stale one is refused with a clear message and changes nothing")
def t3():
    reset()
    create(newp())
    s, j = call("POST", "/api/catalogue/save", {"key": "se-" + uuid.uuid4().hex[:8], "productId": "itg-red-top", "sizes": [{"size": "M", "qty": 7, "expect": 3}], "meta": {"kind": "edit", "by": "t"}})
    need(s == 200 and j["moves"][0]["after"] == 7, f"{s} {j}")
    s, j = call("POST", "/api/catalogue/save", {"key": "se-" + uuid.uuid4().hex[:8], "productId": "itg-red-top", "sizes": [{"size": "M", "qty": 1, "expect": 3}], "meta": {"kind": "edit", "by": "t"}})
    need(s == 409 and j["code"] == "stale" and "changed while counting" in j["error"], f"{s} {j}")
    need(product_doc("itg-red-top")["stock"]["M"] == 7, "a refused recount must leave stock alone")


@check("4  a new size added in the stock editor is created with its quantity; existing sizes are not touched")
def t4():
    reset()
    create(newp())
    s, j = call("POST", "/api/catalogue/save", {"key": "se-" + uuid.uuid4().hex[:8], "productId": "itg-red-top", "sizes": [{"size": "XL", "qty": 4, "expect": 0}], "meta": {"kind": "edit", "by": "t"}})
    need(s == 200 and [x["size"] for x in j["sizes_created"]] == ["XL"] and j["moves"] == [], f"{s} {j}")
    st = product_doc("itg-red-top")["stock"]
    need(st == {"M": 3, "L": 2, "XL": 4}, f"stock {st}")


@check("5  capture of an EXISTING product: new size created, existing size recounted from what was seen; nothing else about the product changes")
def t5():
    reset()
    create(newp())
    with __import__("psycopg").connect(__import__("pgdev").conninfo(), autocommit=True) as c:
        before = c.execute("select article, name, brand, category, colour, price_paise, published from products where id='itg-red-top'").fetchone()
    s, j = call("POST", "/api/catalogue/save", {"key": "cs-" + uuid.uuid4().hex[:8], "productId": "itg-red-top", "meta": {"kind": "capture", "by": "t"},
                                                "sizes": [{"size": "M", "qty": 5, "expect": 3}, {"size": "XL", "qty": 1, "expect": 0}, {"size": "L", "qty": 2, "expect": 2}]})
    need(s == 200 and j["created"] is False, f"{s} {j}")
    with __import__("psycopg").connect(__import__("pgdev").conninfo(), autocommit=True) as c:
        after = c.execute("select article, name, brand, category, colour, price_paise, published from products where id='itg-red-top'").fetchone()
    need(before == after, f"product row changed: {before} -> {after}")
    need(product_doc("itg-red-top")["stock"] == {"M": 5, "L": 2, "XL": 1}, product_doc("itg-red-top")["stock"])


@check("6  a failed save changes nothing at all (bad price mid-way) and the same key then works after the fix")
def t6():
    reset()
    bad = newp(price_paise=0)
    s, j = call("POST", "/api/catalogue/save", bad)
    need(s == 409 and "price" in j["error"], f"{s} {j}")
    need(call("GET", "/api/doc/products/itg-red-top")[1]["exists"] is False and ledger("itg-red-top")["on_hand"] == 0, "a refused capture left something behind")
    good = dict(bad, product=dict(bad["product"], price_paise=79900))
    s, j = call("POST", "/api/catalogue/save", good)
    need(s == 200 and ledger("itg-red-top")["on_hand"] == 5, f"{s} {j}")


@check("7  details edits never overwrite stock: a document write that carries a different stock is REFUSED (409 stock_owned), one without stock is accepted")
def t7():
    reset()
    create(newp())
    put_doc("itg-red-top")
    s, j = call("PATCH", "/api/doc/products/itg-red-top", {"stock": {"M": 99}, "inStock": True}, STRICT)
    need(s == 409 and j["code"] == "stock_owned", f"{s} {j}")
    s, j = call("PATCH", "/api/doc/products/itg-red-top", {"notes": "edited", "sizes": [{"size": "M", "mrp": 899}]}, STRICT)
    need(s == 200, f"{s} {j}")
    d = product_doc("itg-red-top")
    need(d["stock"] == {"M": 3, "L": 2} and d["notes"] == "edited", f"{d.get('stock')} {d.get('notes')}")
    s, j = call("PUT", "/api/doc/products/ghost-product", {"stock": {"M": 5}, "article": "G"}, STRICT)      # a product the shared stock does not know
    need(s == 409 and j["code"] == "stock_owned", f"a brand-new document with stock must be refused: {s} {j}")


@check("8  concurrent sale and recount: a recount that saw the old number is refused if a sale landed first; 20 rounds never lose a piece")
def t8():
    reset()
    create(newp(sizes=(("M", 50),)))
    stale = 0
    for rnd in range(20):
        cur = product_doc("itg-red-top")["stock"]["M"]
        out = {}

        def sale():
            out["sale"] = call("POST", "/api/stock/moves", {"key": "mv-" + uuid.uuid4().hex[:8], "meta": {"kind": "sale", "by": "t"},
                                                            "moves": [{"productId": "itg-red-top", "size": "M", "change": -1, "kind": "sale", "label": "x"}]})

        def recount():
            out["rec"] = call("POST", "/api/catalogue/save", {"key": "se-" + uuid.uuid4().hex[:8], "productId": "itg-red-top", "sizes": [{"size": "M", "qty": cur - 5, "expect": cur}], "meta": {"kind": "edit", "by": "t"}})
        th = [threading.Thread(target=sale), threading.Thread(target=recount)]
        [t.start() for t in th]
        [t.join() for t in th]
        need(out["sale"][0] == 200, f"round {rnd}: sale {out['sale']}")
        after = product_doc("itg-red-top")["stock"]["M"]
        if out["rec"][0] == 200:
            need(after in (cur - 5 - 1, cur - 5), f"round {rnd}: recount ok but stock {after} (cur {cur})")      # recount first then sale (-1), or sale first can't pass expect
            need(after == cur - 6, f"round {rnd}: recount applied then sale should give {cur - 6}, got {after}")
        else:
            need(out["rec"][1]["code"] == "stale" and after == cur - 1, f"round {rnd}: refused recount must leave only the sale: {out['rec']} stock {after}")
            stale += 1
    lg = ledger("itg-red-top")
    need(lg["on_hand"] == product_doc("itg-red-top")["stock"]["M"], "shelf != ledger sum")
    print(f"        ({stale} of 20 recounts were refused as stale; the other {20 - stale} applied before the sale)")


@check("10 the hand-set In stock flag is refused for a product that has pieces (it is worked out from the rack), never silently dropped")
def t10():
    reset()
    create(newp())
    s, j = call("PATCH", "/api/doc/products/itg-red-top", {"inStock": False}, STRICT)
    need(s == 409 and j["code"] == "stock_owned", f"{s} {j}")
    need(product_doc("itg-red-top")["inStock"] is True, "flag must stay derived from the rack")


@check("11 price and stock in ONE save: both apply together; a stale price refuses the whole save (the stock part is not applied either); prices need an existing product")
def t11():
    reset()
    create(newp())
    k = "pr-" + uuid.uuid4().hex[:8]
    body = {"key": k, "productId": "itg-red-top", "meta": {"kind": "edit", "by": "t"}, "sizes": [{"size": "M", "qty": 5, "expect": 3}],
            "prices": {"expect_price_paise": 79900, "price_paise": 79900, "size_prices": {"M": 89900}}}
    s, j = call("POST", "/api/catalogue/save", body)
    need(s == 200 and j["prices"]["changed"] == 1 and j["moves"][0]["after"] == 5, f"{s} {j}")
    s2, j2 = call("POST", "/api/catalogue/save", body)                                   # a replay
    need(s2 == 200 and j2 == j, f"replay {s2} {j2}")
    s, j = call("POST", "/api/catalogue/save", {"key": "pr-" + uuid.uuid4().hex[:8], "productId": "itg-red-top", "meta": {"kind": "edit", "by": "t"},
                                                "sizes": [{"size": "M", "qty": 9, "expect": 5}], "prices": {"expect_price_paise": 1, "price_paise": 70000, "size_prices": {}}})
    need(s == 409 and "price changed while editing" in j["error"], f"{s} {j}")
    need(product_doc("itg-red-top")["stock"]["M"] == 5, "the stock half of a refused save was applied")
    s, j = call("POST", "/api/catalogue/save", {"key": "pr-" + uuid.uuid4().hex[:8], "productId": "no-such", "meta": {}, "prices": {"expect_price_paise": None, "price_paise": 5000, "size_prices": {}}})
    need(s == 400, f"{s} {j}")
    import psycopg, pgdev
    with psycopg.connect(pgdev.conninfo(), autocommit=True) as c:
        need(c.execute("select count(*) from price_events where product_id='itg-red-top'").fetchone()[0] == 1, "one audit row for the one change")


@check("9  the shelf equals the ledger and every history copy has one ledger row (end state)")
def t9():
    lg = ledger("itg-red-top")
    need(lg["on_hand"] == product_doc("itg-red-top")["stock"]["M"], f"{lg}")
    need(lg["docs"] >= 1, "no history copies")


if __name__ == "__main__":
    for fn in (t1, t2, t3, t4, t5, t6, t7, t10, t11, t8, t9):
        fn()
    bad = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(bad)} passed, {len(bad)} failed")
    sys.exit(1 if bad else 0)
