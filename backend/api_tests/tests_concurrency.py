"""G. Concurrency through real HTTP connections (each request is its own connection into PostgREST's pool, not a SQL session)."""
from __future__ import annotations

import time

from ctx import Ctx
from lib import Fail, parallel, test


def two_xx(rs):
    return [r for r in rs if not isinstance(r, Exception) and r.status == 200]


def errs(rs):
    return sorted({(r.status, r.code, (r.message or "")[:70]) if not isinstance(r, Exception) else ("exc", str(r)[:60], "") for r in rs if isinstance(r, Exception) or r.status != 200})


@test("G1", "G concurrency over HTTP", "The last piece: 12 staff confirmations at the same instant over HTTP - exactly one wins, 5 rounds", where=("local",))
def g1(X: Ctx):
    wins = []
    for rnd in range(5):
        X.reset(stock_a_m=1)
        oids = [X.place_ok(phone=X.phone())[0] for _ in range(12)]
        res = parallel([(lambda o=o: X.rpc("confirm_and_reserve", {"p_idem_key": X.key(), "p_order": o, "p_delivery_paise": 5000, "p_discount_paise": 0}, "staff")) for o in oids])
        w = two_xx(res)
        X.need(len(w) == 1, f"round {rnd}: {len(w)} confirmations succeeded for ONE piece; failures: {errs(res)}")
        X.need(X.stock("tst-a-pink", "M") == (1, 1), f"round {rnd}: stock {X.stock('tst-a-pink', 'M')}")
        X.need(all("not enough stock" in (r.message or "") for r in res if not isinstance(r, Exception) and r.status != 200), f"round {rnd}: other failures: {errs(res)}")
        X.need(X.sql1("select count(*) from orders where status='awaiting_payment'") == 1, "more than one order holds the piece")
        X.invariants()
        wins.append(len(w))
    X.note("rounds", wins)


@test("G2", "G concurrency over HTTP", "A website hold and a counter sale for the last piece at the same instant - one of them gets it", where=("local",))
def g2(X: Ctx):
    for rnd in range(5):
        X.reset(stock_a_m=1)
        oid, _ = X.place_ok()
        res = parallel([lambda: X.rpc("confirm_and_reserve", {"p_idem_key": X.key(), "p_order": oid, "p_delivery_paise": 5000, "p_discount_paise": 0}, "staff"),
                        lambda: X.rpc("complete_sale", {"p_idem_key": X.key(), "p_lines": [{"product_id": "tst-a-pink", "size": "M", "qty": 1}],
                                                        "p_payments": [{"method": "cash", "amount_paise": 99900}]}, "staff")])
        w = two_xx(res)
        X.need(len(w) == 1, f"round {rnd}: {len(w)} winners for one piece: {errs(res)}")
        on_hand, reserved = X.stock("tst-a-pink", "M")
        X.need((on_hand, reserved) in ((1, 1), (0, 0)), f"round {rnd}: stock {(on_hand, reserved)}")
        X.invariants()


@test("G3", "G concurrency over HTTP", "Paying and dispatching: parallel duplicates over HTTP change stock and the money ledger exactly once", where=("local",))
def g3(X: Ctx):
    X.reset()
    oid, _ = X.place_ok()
    X.reserve(oid)
    amt = X.order(oid)["agreed_paise"]
    res = parallel([lambda: X.rpc("verify_payment", {"p_idem_key": X.key(), "p_order": oid, "p_method": "upi", "p_amount_paise": amt, "p_upi_ref": "UPIRACE001"}, "staff") for _ in range(6)])
    X.need(len(two_xx(res)) == 1, f"{len(two_xx(res))} payments verified; {errs(res)}")
    X.need(X.sql1("select count(*) from payments where order_id=%s", oid) == 1, "more than one payment row")
    res = parallel([lambda: X.rpc("dispatch_order", {"p_idem_key": X.key(), "p_order": oid, "p_tracking": "T"}, "staff") for _ in range(6)])
    X.need(len(two_xx(res)) == 1, f"{len(two_xx(res))} dispatches succeeded; {errs(res)}")
    X.need(X.stock("tst-a-pink", "M") == (4, 0), f"stock after dispatch: {X.stock('tst-a-pink', 'M')}")
    X.need(X.sql1("select count(*) from stock_events where order_id=%s and kind='dispatch'", oid) >= 1, "no dispatch event")
    X.invariants()


@test("G4", "G concurrency over HTTP", "Ten customers' 'I have paid' taps at once extend the hold exactly once", where=("local",))
def g4(X: Ctx):
    X.reset()
    ph = "9555555551"
    oid, ref = X.place_ok(phone=ph)
    X.reserve(oid)
    res = parallel([lambda: X.rpc("report_payment", {"p_ref": ref, "p_phone": ph, "p_claimed_ref": "UPI1", "p_claimed_paise": 1000}, "anon") for _ in range(10)])
    good = two_xx(res)
    X.need(len(good) == 10, f"some taps failed: {errs(res)}")
    X.need(sum(1 for r in good if r.json["hold_extended_once"]) == 1, "the hold was extended more than once (or never)")
    X.need(X.sql1("select count(*) from payment_reports where order_id=%s", oid) == 10, "reports lost")
    X.need(X.order(oid)["status"] == "awaiting_payment" and X.order(oid)["grace_used"] is True, "state")


@test("G5", "G concurrency over HTTP", "24 simultaneous order requests from one phone: exactly 5 are admitted (limit holds under load)", where=("local",))
def g5(X: Ctx):
    X.reset()
    ph = "9555555552"
    bodies = []
    for _ in range(24):
        items = (("tst-b-blue", "M", 1),)
        bodies.append(dict(p_idem_key=X.key(), p_ref=X.ref_for(*items), p_name="Test", p_phone=ph, p_address="12 Test Street", p_landmark="", p_lines=[{"product_id": "tst-b-blue", "size": "M", "qty": 1}]))
    res = parallel([(lambda b=b: X.rpc("place_order_request", b, "anon")) for b in bodies])
    good = two_xx(res)
    X.need(len(good) == 5 and X.sql1("select count(*) from orders where phone=%s", ph) == 5, f"{len(good)} admitted, {X.sql1('select count(*) from orders where phone=%s', ph)} stored")
    X.need(all(r.status == 429 for r in res if not isinstance(r, Exception) and r.status != 200), f"refusals were not all 429: {errs(res)}")


@test("G6", "G concurrency over HTTP", "Mixed load: 200 simultaneous requests (reads, orders, staff calls) all answered correctly, none dropped or 5xx", where=("local",))
def g6(X: Ctx):
    X.reset(stock_a_m=50)
    jobs = []
    for i in range(200):
        k = i % 4
        if k == 0:
            jobs.append(("avail", lambda: X.rpc("get_availability", {}, "anon")))
        elif k == 1:
            ph = X.phone()
            jobs.append(("order", lambda ph=ph: X.place(phone=ph)))
        elif k == 2:
            jobs.append(("rank", lambda: X.rpc("current_role_rank", {}, "manager")))
        else:
            jobs.append(("orders", lambda: X.tbl("GET", "orders", "staff", query="select=id&limit=5")))
    t0 = time.time()
    res = parallel([j for _, j in jobs])
    dt = time.time() - t0
    bad = [(n, r if isinstance(r, Exception) else (r.status, r.code)) for (n, _), r in zip(jobs, res) if isinstance(r, Exception) or r.status != 200]
    X.need(not bad, f"{len(bad)} of 200 failed, first: {bad[:3]}")
    X.need(all(r.json == 2 for (n, _), r in zip(jobs, res) if n == "rank"), "a rank answer belonged to someone else")
    X.note("mixed_load", {"requests": 200, "seconds": round(dt, 2)})
    X.invariants()
