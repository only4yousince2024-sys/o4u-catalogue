"""O4U backend checks - run against a THROWAWAY local PostgreSQL 16 filled with INVENTED data only.

    python -m venv .venv && .venv/Scripts/pip install pgserver "psycopg[binary]"
    .venv/Scripts/python backend/tests/run_db_tests.py

Starts its own temporary database in a temp folder (no network, no Supabase, nothing real), applies
tests/supabase_shim.sql (stand-ins for Supabase's roles and auth.uid()) and migrations/*.sql, then runs every check
and prints PASS/FAIL per check. Exit 0 only if all passed. Results are never claimed - they are printed from the run.
"""
from __future__ import annotations

import sys
import tempfile
import threading
import time
import traceback
import uuid
from pathlib import Path

import psycopg
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pgcluster

HERE = Path(__file__).resolve().parent
import os
MIGRATIONS = sorted((Path(os.environ.get("O4U_MIGRATIONS_DIR") or HERE.parent / "migrations")).glob("*.sql"))   # override only to prove the checks can fail

OWNER, DAD, CLERK, STRANGER = (str(uuid.UUID(int=i)) for i in (1, 2, 3, 4))   # invented identities
PRICE_A, PRICE_B, DELIVERY = 99900, 149900, 5000                                # paise


# ───────────────────────── plumbing ─────────────────────────
class Fail(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Fail(msg)


class Env:
    uri: str
    server: object

    def connect(self, who=None):
        """who: None = superuser (test setup only), 'anon', or a user id (role authenticated)."""
        c = psycopg.connect(self.uri, autocommit=True)
        if who == "anon":
            c.execute("set role anon")
        elif who is not None:
            c.execute("set role authenticated")
            c.execute("select set_config('request.jwt.claim.sub', %s, false)", (who,))
        return c


ENV = Env()
_conns: dict = {}


def conn(who=None):
    if who not in _conns or _conns[who].closed:
        _conns[who] = ENV.connect(who)
    return _conns[who]


def rpc(who, sql, *args):
    """('ok', first value) or ('err', message). Every call is its own transaction (autocommit)."""
    c = conn(who)
    try:
        row = c.execute(sql, args).fetchone()
        return "ok", (row[0] if row else None)
    except psycopg.Error as e:
        return "err", (e.diag.message_primary or str(e))


def ok(who, sql, *args):
    st, v = rpc(who, sql, *args)
    check(st == "ok", f"expected success, got error: {v}  [{sql[:60]}]")
    return v


def err(who, sql, *args, contains=None):
    st, v = rpc(who, sql, *args)
    check(st == "err", f"expected an error, but it succeeded: {v}  [{sql[:60]}]")
    if contains:
        check(contains.lower() in v.lower(), f"error was '{v}', expected it to mention '{contains}'")
    return v


def q(sql, *args, who=None):
    return conn(who).execute(sql, args).fetchall()


def q1(sql, *args, who=None):
    r = q(sql, *args, who=who)
    return r[0][0] if r else None


_ctr = [0]


def key():
    _ctr[0] += 1
    return f"test-key-{_ctr[0]:06d}-{uuid.uuid4().hex[:6]}"


_ref = [0]
ALPHA = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def new_ref():
    _ref[0] += 1
    n = _ref[0]
    return f"W1510-{ALPHA[n // 31 % 31]}{ALPHA[n % 31]}{ALPHA[(n * 7) % 31]}{ALPHA[(n * 13) % 31]}-{ALPHA[(n * 3) % 31]}{ALPHA[(n * 5) % 31]}"


# ───────────────────────── synthetic world ─────────────────────────
def reset(stock_a_m=5, stock_a_l=5, stock_b_m=5, online=True):
    """Wipe and re-seed INVENTED data. Stock arrives through receive_stock so the ledger explains every piece."""
    c = conn()
    c.execute("""truncate sale_lines, sales, payments, refunds, payment_reports, order_events, order_lines, orders, stock_events,
                 idempotency, stock_levels, variants, products, staff restart identity cascade""")
    c.execute("update store_status set last_heartbeat = null, offline_switch = false, note = null")
    c.execute("insert into staff values (%s,'Khush (test owner)','owner'), (%s,'Dad (test manager)','manager'), (%s,'Clerk (test staff)','staff')", (OWNER, DAD, CLERK))
    c.execute("""insert into products (id, article, name, brand, category, colour, price_paise, published) values
                 ('tst-a-pink','TST-A','Pink Test Tee','','tshirts','Pink',%s,true),
                 ('tst-b-blue','TST-B','Blue Test Lower','','lowers','Blue',%s,true),
                 ('tst-hidden','TST-H','Hidden Test Top','','tops','Grey',%s,false)""", (PRICE_A, PRICE_B, PRICE_A))
    for pid, size, bc in (("tst-a-pink", "M", "8900000000011"), ("tst-a-pink", "L", "8900000000012"), ("tst-b-blue", "M", "8900000000021"), ("tst-hidden", "M", "8900000000031")):
        vid = c.execute("insert into variants (product_id, size, barcode) values (%s,%s,%s) returning id", (pid, size, bc)).fetchone()[0]
        c.execute("insert into stock_levels (variant_id) values (%s)", (vid,))
    for (pid, size), n in {("tst-a-pink", "M"): stock_a_m, ("tst-a-pink", "L"): stock_a_l, ("tst-b-blue", "M"): stock_b_m, ("tst-hidden", "M"): 3}.items():
        if n:
            ok(OWNER, "select receive_stock(%s,%s,%s,'test delivery')", key(), vid_of(pid, size), n)
    if online:
        ok(CLERK, "select store_ping()")
        conn().execute("select 1")


def vid_of(pid, size):
    return q1("select id from variants where product_id=%s and size=%s", pid, size)


def stock(pid, size):
    r = q("select on_hand, reserved from stock_levels where variant_id=%s", vid_of(pid, size))[0]
    return r[0], r[1]


def lines_json(*items):
    import json
    return json.dumps([{"product_id": p, "size": s, "qty": n} for p, s, n in items])


def place(*items, idem=None, ref=None, phone="9000000001"):
    items = items or (("tst-a-pink", "M", 1),)
    res = ok("anon", "select place_order_request(%s,%s,'Test Customer',%s,'12 Test Street, Testville','near test park',%s::jsonb)",
             idem or key(), ref or new_ref(), phone, lines_json(*items))
    return res["order_id"], res["ref"]


def order(oid):
    cols = [d for d in "status items_paise delivery_paise discount_paise agreed_paise paid_paise reserved stock_deducted hold_until grace_used".split()]
    r = q(f"select {', '.join(cols)} from orders where id=%s", oid)[0]
    return dict(zip(cols, r))


def reserve(oid, delivery=DELIVERY, discount=0, who=CLERK, idem=None):
    return ok(who, "select confirm_and_reserve(%s,%s,%s,%s)", idem or key(), oid, delivery, discount)


def pay(oid, amount=None, who=CLERK, ref=None, method="upi", idem=None):
    amount = amount if amount is not None else order(oid)["agreed_paise"]
    return ok(who, "select verify_payment(%s,%s,%s,%s,%s, now())", idem or key(), oid, method, amount, ref or f"UPI{uuid.uuid4().hex[:10]}")


def invariants():
    """Run after every check: the ledger explains the shelf, holds match orders, nothing is negative."""
    bad = q("""select v.product_id, v.size from stock_levels sl join variants v on v.id = sl.variant_id
               where sl.on_hand <> coalesce((select sum(d_on_hand) from stock_events e where e.variant_id = sl.variant_id), 0)
                  or sl.reserved <> coalesce((select sum(d_reserved) from stock_events e where e.variant_id = sl.variant_id), 0)""")
    check(not bad, f"stock_levels disagree with the stock_events ledger for {bad}")
    bad = q("""select v.product_id, v.size from stock_levels sl join variants v on v.id = sl.variant_id
               where sl.reserved <> coalesce((select sum(ol.qty) from order_lines ol join orders o on o.id = ol.order_id
                                              where ol.variant_id = sl.variant_id and o.reserved), 0)""")
    check(not bad, f"reserved stock does not match the orders that hold it: {bad}")
    check(q1("select count(*) from stock_levels where on_hand < 0 or reserved < 0 or reserved > on_hand") == 0, "negative or over-reserved stock")
    check(q1("select count(*) from orders where status in ('paid','packed') and not reserved and not stock_deducted") == 0, "a paid order lost its stock")
    check(q1("select count(*) from orders where status = 'dispatched' and not stock_deducted") == 0, "dispatched without deduction")


def parallel(fns):
    """Run callables at the same instant, each on its own connection. Returns their results (value or Exception)."""
    barrier, out = threading.Barrier(len(fns)), [None] * len(fns)

    def run(i, f):
        try:
            barrier.wait(timeout=10)
            out[i] = f()
        except Exception as e:      # noqa: BLE001 - we want to inspect every outcome
            out[i] = e
    ts = [threading.Thread(target=run, args=(i, f)) for i, f in enumerate(fns)]
    [t.start() for t in ts]
    [t.join(60) for t in ts]
    return out


def solo(who, sql, *args):
    """Own short-lived connection for use inside parallel(): returns ('ok', v) / ('err', msg)."""
    c = ENV.connect(who)
    try:
        row = c.execute(sql, args).fetchone()
        return "ok", (row[0] if row else None)
    except psycopg.Error as e:
        return "err", (e.diag.message_primary or str(e))
    finally:
        c.close()


TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


# ───────────────────────── 1. website order request ─────────────────────────
@test
def request_is_a_request_not_a_sale():
    reset()
    oid, ref = place(("tst-a-pink", "M", 2), ("tst-b-blue", "M", 1))
    o = order(oid)
    check(o["status"] == "request", "new order must be a request")
    check(o["items_paise"] == 2 * PRICE_A + PRICE_B, f"items total wrong: {o['items_paise']}")
    check(o["agreed_paise"] is None and o["delivery_paise"] is None and o["paid_paise"] == 0, "preliminary total must not be an agreed or paid amount")
    check(stock("tst-a-pink", "M") == (5, 0), "a request must not hold stock")
    check(q1("select count(*) from order_events where order_id=%s", oid) == 1, "request must be audited")


@test
def prices_come_from_the_catalogue_and_bad_requests_are_refused():
    reset()
    err("anon", "select place_order_request(%s,%s,'T','9000000001','addr','', %s::jsonb)", key(), new_ref(), lines_json(("tst-hidden", "M", 1)), contains="not available")
    err("anon", "select place_order_request(%s,%s,'T','9000000001','addr','', %s::jsonb)", key(), new_ref(), lines_json(("tst-a-pink", "XXL", 1)), contains="not available")
    err("anon", "select place_order_request(%s,%s,'T','9000000001','addr','', %s::jsonb)", key(), new_ref(), lines_json(("tst-a-pink", "M", 0)), contains="quantity")
    err("anon", "select place_order_request(%s,%s,'T','9000000001','addr','', %s::jsonb)", key(), new_ref(), lines_json(("tst-a-pink", "M", 100)), contains="quantity")
    err("anon", "select place_order_request(%s,%s,'T','12345','addr','', %s::jsonb)", key(), new_ref(), lines_json(("tst-a-pink", "M", 1)), contains="phone")
    err("anon", "select place_order_request(%s,'BAD-REF','T','9000000001','addr','', %s::jsonb)", key(), lines_json(("tst-a-pink", "M", 1)), contains="reference")
    err("anon", "select place_order_request(%s,%s,'T','9000000001','addr','', %s::jsonb)", key(), new_ref(), lines_json(("tst-a-pink", "M", 1), ("tst-a-pink", "M", 1)))
    err("anon", "select place_order_request('short',%s,'T','9000000001','addr','', %s::jsonb)", new_ref(), lines_json(("tst-a-pink", "M", 1)), contains="idempotency")
    check(q1("select count(*) from orders") == 0, "a refused request must leave nothing behind")


@test
def same_request_sent_five_times_at_once_is_one_order():
    reset()
    k, ref = key(), new_ref()
    out = parallel([lambda: solo("anon", "select place_order_request(%s,%s,'T','9000000001','addr','', %s::jsonb)", k, ref, lines_json(("tst-a-pink", "M", 1)))] * 5)
    check(all(isinstance(r, tuple) and r[0] == "ok" for r in out), f"all five replays should succeed: {out}")
    check(len({r[1]["order_id"] for r in out}) == 1, "replays must return the same order")
    check(q1("select count(*) from orders") == 1, "exactly one order must exist")
    err("anon", "select place_order_request(%s,%s,'T','9000000001','addr','', %s::jsonb)", key(), ref, lines_json(("tst-a-pink", "M", 1)), contains="already used")


# ───────────────────────── 2. availability ─────────────────────────
@test
def availability_labels_and_no_big_numbers():
    reset(stock_a_m=5, stock_a_l=2, stock_b_m=1)
    rows = {(r[0], r[1]): r[2:4] for r in q("select product_id, size, state, n from get_availability()", who="anon")}
    check(rows[("tst-a-pink", "M")] == ("available", None), f"5 free must read available with no number: {rows[('tst-a-pink','M')]}")
    check(rows[("tst-a-pink", "L")] == ("low", 2), "2 free reads Only 2")
    check(rows[("tst-b-blue", "M")] == ("low", 1), "1 free reads Only 1")
    check(("tst-hidden", "M") not in rows, "unpublished products must not appear")
    oid, _ = place(("tst-b-blue", "M", 1)); reserve(oid)
    rows = {(r[0], r[1]): r[2:4] for r in q("select product_id, size, state, n from get_availability(array['tst-b-blue'])", who="anon")}
    check(rows[("tst-b-blue", "M")] == ("ask", 0), "last piece held for a customer reads Ask us")


@test
def availability_goes_to_check_when_the_shop_is_unreachable():
    reset()
    check({r[0] for r in q("select state from get_availability()", who="anon")} == {"available"}, "fresh heartbeat should be trusted")
    conn().execute("update store_status set last_heartbeat = now() - interval '10 minutes'")
    check({r[0] for r in q("select state from get_availability()", who="anon")} == {"check"}, "stale heartbeat must read Check availability")
    ok(CLERK, "select store_ping()")
    ok(DAD, "select set_offline_switch(true, 'power cut')")
    check({r[0] for r in q("select state from get_availability()", who="anon")} == {"check"}, "offline switch must read Check availability")
    err(CLERK, "select set_offline_switch(false)", contains="manager")
    ok(DAD, "select set_offline_switch(false, '')")
    check({r[0] for r in q("select state from get_availability()", who="anon")} == {"available"}, "back online")


# ───────────────────────── 3. the one-tap lifecycle ─────────────────────────
@test
def lifecycle_request_to_delivered():
    reset()
    oid, ref = place(("tst-a-pink", "M", 2), ("tst-b-blue", "M", 1))
    r = reserve(oid)
    o = order(oid)
    check(o["status"] == "awaiting_payment" and o["reserved"], "Confirm & Reserve must hold the stock")
    check(o["agreed_paise"] == 2 * PRICE_A + PRICE_B + DELIVERY, "agreed bill = items + staff-entered delivery")
    secs = q1("select extract(epoch from hold_until - now()) from orders where id=%s", oid)
    check(7000 < secs <= 7200, f"hold must be about two hours, got {secs}s")
    check(stock("tst-a-pink", "M") == (5, 2) and stock("tst-b-blue", "M") == (5, 1), "variants reserved")
    rows = {(r[0], r[1]): r[2] for r in q("select product_id, size, state from get_availability()", who="anon")}
    check(rows[("tst-a-pink", "M")] == "available", "3 free still reads available")
    pay(oid)
    o = order(oid)
    check(o["status"] == "paid" and o["paid_paise"] == o["agreed_paise"] and o["hold_until"] is None, "payment verified: paid, hold lifted")
    check(q1("select count(*) from payments where order_id=%s and kind='payment'", oid) == 1, "one verified payment row")
    ok(CLERK, "select pack_order(%s,%s)", key(), oid)
    check(order(oid)["status"] == "packed", "packed")
    ok(CLERK, "select dispatch_order(%s,%s,'TRK123')", key(), oid)
    o = order(oid)
    check(o["status"] == "dispatched" and o["stock_deducted"] and not o["reserved"], "dispatched: deducted, hold gone")
    check(stock("tst-a-pink", "M") == (3, 0) and stock("tst-b-blue", "M") == (4, 0), "pieces left the rack")
    ok(CLERK, "select mark_delivered(%s,%s)", key(), oid)
    check(order(oid)["status"] == "delivered", "delivered")
    ev = [r[0] for r in q("select action from order_events where order_id=%s order by id", oid)]
    check(ev == ["place_order_request", "confirm_and_reserve", "verify_payment", "pack", "dispatch", "mark_delivered"], f"audit trail: {ev}")
    check(q1("select count(*) from stock_events where order_id=%s", oid) == 4, "2 reserve + 2 dispatch ledger rows")


@test
def paid_can_dispatch_straight_without_packing_and_failed_can_resend():
    reset()
    oid, _ = place(); reserve(oid); pay(oid)
    ok(CLERK, "select dispatch_order(%s,%s,'')", key(), oid)
    ok(CLERK, "select mark_failed(%s,%s,'customer','not home')", key(), oid)
    err(CLERK, "select mark_failed(%s,%s,'nobody','x')", key(), oid, contains="who failed")
    ok(CLERK, "select dispatch_order(%s,%s,'TRK2')", key(), oid)
    check(stock("tst-a-pink", "M") == (4, 0), "resending after a failed delivery must not deduct again")
    ok(CLERK, "select mark_delivered(%s,%s)", key(), oid)


@test
def lifecycle_matches_stockrooms_existing_rules():
    reset()
    got = {(a, f) for a, f in q("select action, from_status from order_transitions")}
    expected = {  # read from stockroom-v44-original.html order handlers (confirm+reserve merged; every other step unchanged)
        ("confirm_and_reserve", "request"), ("confirm_and_reserve", "hold_expired"), ("verify_payment", "awaiting_payment"), ("verify_payment", "hold_expired"),
        ("release_hold", "awaiting_payment"), ("pack", "paid"), ("dispatch", "paid"), ("dispatch", "packed"), ("dispatch", "failed"),
        ("mark_failed", "dispatched"), ("mark_delivered", "dispatched"), ("mark_delivered", "failed"),
        ("cancel", "request"), ("cancel", "awaiting_payment"), ("cancel", "hold_expired"),
        ("request_refund", "paid"), ("request_refund", "packed"), ("request_refund", "failed"), ("refund_sent", "refund_due")}
    check(got == expected, f"transition table drifted: extra {got - expected}, missing {expected - got}")
    oid, _ = place()
    for action, sql in (("pack", "select pack_order(%s,%s)"), ("dispatch", "select dispatch_order(%s,%s,'')"), ("deliver", "select mark_delivered(%s,%s)")):
        err(CLERK, sql, key(), oid, contains="cannot")
    err(CLERK, "select verify_payment(%s,%s,'upi',100,'UPIX', now())", key(), oid, contains="cannot")
    check(order(oid)["status"] == "request", "illegal actions change nothing")


@test
def delivery_charge_is_required_and_discount_needs_a_manager():
    reset()
    oid, _ = place()
    err(CLERK, "select confirm_and_reserve(%s,%s,null,0)", key(), oid, contains="delivery charge")
    err(CLERK, "select confirm_and_reserve(%s,%s,%s,500)", key(), oid, DELIVERY, contains="manager")
    err(DAD, "select confirm_and_reserve(%s,%s,%s,%s)", key(), oid, DELIVERY, PRICE_A, contains="below the items total")
    reserve(oid, discount=9900, who=DAD)
    o = order(oid)
    check(o["agreed_paise"] == PRICE_A - 9900 + DELIVERY and o["discount_paise"] == 9900, "negotiated amount recorded as the agreed bill, not the website total")
    check(o["items_paise"] == PRICE_A, "the website's preliminary total is preserved unchanged")
    err(CLERK, "select verify_payment(%s,%s,'upi',%s,'UPIWRONG', now())", key(), oid, PRICE_A, contains="differs from the agreed bill")


# ───────────────────────── 4. concurrency ─────────────────────────
@test
def two_customers_one_last_piece():
    for round_ in range(15):
        reset(stock_a_m=1)
        a, _ = place(("tst-a-pink", "M", 1), phone="9000000001")
        b, _ = place(("tst-a-pink", "M", 1), phone="9000000002")
        out = parallel([lambda: solo(CLERK, "select confirm_and_reserve(%s,%s,%s,0)", key(), a, DELIVERY),
                        lambda: solo(DAD, "select confirm_and_reserve(%s,%s,%s,0)", key(), b, DELIVERY)])
        oks = [r for r in out if r[0] == "ok"]
        errs = [r for r in out if r[0] == "err"]
        check(len(oks) == 1 and len(errs) == 1, f"round {round_}: exactly one must win, got {out}")
        check("not enough stock" in errs[0][1], f"loser should be told the stock is short: {errs[0][1]}")
        check(stock("tst-a-pink", "M") == (1, 1), "one piece held, never two")
        invariants()


@test
def eight_orders_three_pieces():
    reset(stock_a_m=3)
    oids = [place(("tst-a-pink", "M", 1), phone=f"90000000{i:02d}")[0] for i in range(8)]
    out = parallel([(lambda o=o: solo(CLERK, "select confirm_and_reserve(%s,%s,%s,0)", key(), o, DELIVERY)) for o in oids])
    check(sum(r[0] == "ok" for r in out) == 3, f"exactly 3 of 8 may reserve 3 pieces: {[r[0] for r in out]}")
    check(stock("tst-a-pink", "M") == (3, 3), "all three held, none oversold")
    invariants()


@test
def opposite_line_order_does_not_deadlock():
    for _ in range(10):
        reset()
        a, _ = place(("tst-a-pink", "M", 1), ("tst-b-blue", "M", 1), phone="9000000001")
        b, _ = place(("tst-b-blue", "M", 1), ("tst-a-pink", "M", 1), phone="9000000002")
        out = parallel([lambda: solo(CLERK, "select confirm_and_reserve(%s,%s,%s,0)", key(), a, DELIVERY),
                        lambda: solo(DAD, "select confirm_and_reserve(%s,%s,%s,0)", key(), b, DELIVERY)])
        check(all(r[0] == "ok" for r in out), f"both have enough stock, neither may fail (deadlock?): {out}")
        invariants()


@test
def counter_sale_races_and_respects_website_holds():
    reset(stock_a_m=1)
    sale = lambda: solo(CLERK, "select complete_sale(%s,%s::jsonb,%s::jsonb,0)", key(),
                        '[{"barcode":"8900000000011","qty":1}]', f'[{{"method":"cash","amount_paise":{PRICE_A}}}]')
    out = parallel([sale, sale])
    check(sorted(r[0] for r in out) == ["err", "ok"], f"two counter sales of the last piece: one wins: {out}")
    check(stock("tst-a-pink", "M") == (0, 0), "sold exactly once")
    invariants()
    reset(stock_a_m=1)
    oid, _ = place(); reserve(oid)
    r = solo(CLERK, "select complete_sale(%s,%s::jsonb,%s::jsonb,0)", key(), '[{"barcode":"8900000000011","qty":1}]', f'[{{"method":"cash","amount_paise":{PRICE_A}}}]')
    check(r[0] == "err" and "free stock" in r[1], f"counter must not take a piece held for a website customer: {r}")
    invariants()


# ───────────────────────── 5. expiry, payment, and their race ─────────────────────────
def age_hold(oid, minutes=1):
    conn().execute("update orders set hold_until = now() - make_interval(mins => %s) where id=%s", (minutes, oid))


@test
def unpaid_hold_expires_and_stock_returns():
    reset()
    oid, _ = place(("tst-a-pink", "M", 2)); reserve(oid)
    check(ok(None, "select expire_holds()") == 0, "nothing is due yet")
    age_hold(oid)
    check(ok(None, "select expire_holds()") == 1, "one hold expired")
    o = order(oid)
    check(o["status"] == "hold_expired" and not o["reserved"], "order marked expired, hold gone")
    check(stock("tst-a-pink", "M") == (5, 0), "stock back on offer")
    check(ok(None, "select expire_holds()") == 0, "running expiry again changes nothing")
    check(q1("select count(*) from stock_events where kind='release' and order_id=%s", oid) == 1, "released exactly once")
    check(q1("select action from order_events where order_id=%s order by id desc limit 1", oid) == "hold_expired", "audited")
    err("anon", "select expire_holds()", contains="permission")
    err(CLERK, "select expire_holds()", contains="permission")
    invariants()


@test
def paid_stock_is_never_released_automatically():
    reset()
    oid, _ = place(); reserve(oid); pay(oid)
    conn().execute("update orders set hold_until = now() - interval '5 hours' where id=%s", (oid,))     # even a tampered clock
    ok(None, "select expire_holds(now() + interval '30 days')")
    check(order(oid)["status"] == "paid" and order(oid)["reserved"], "paid order untouched by expiry")
    oid2, _ = place(phone="9000000002"); reserve(oid2); pay(oid2)
    ok(CLERK, "select pack_order(%s,%s)", key(), oid2)
    ok(None, "select expire_holds(now() + interval '30 days')")
    check(order(oid2)["status"] == "packed" and order(oid2)["reserved"], "packed order untouched too")
    invariants()


@test
def customer_says_paid_is_information_only_and_extends_once():
    reset()
    oid, ref = place(); reserve(oid)
    before = order(oid)["hold_until"]
    conn().execute("update orders set hold_until = now() + interval '5 minutes' where id=%s", (oid,))
    r = ok("anon", "select report_payment(%s,'9000000001','UPI-FROM-CUSTOMER', %s)", ref, order(oid)["agreed_paise"])
    check(r["verified"] is False and r["hold_extended_once"] is True, f"report must not be verification: {r}")
    o = order(oid)
    check(o["status"] == "awaiting_payment" and o["paid_paise"] == 0, "still unpaid after a customer report")
    check(q1("select count(*) from payments") == 0, "no money row from a customer report")
    secs = q1("select extract(epoch from hold_until - now()) from orders where id=%s", oid)
    check(3000 < secs <= 3600, f"extended to about an hour, got {secs}")
    r2 = ok("anon", "select report_payment(%s,'9000000001','AGAIN', 1)", ref)
    check(r2["hold_extended_once"] is False, "a second report must not extend again (no unlimited holds)")
    err("anon", "select report_payment(%s,'9999999999','x', 1)", ref, contains="not found")
    age_hold(oid)
    check(ok(None, "select expire_holds()") == 1, "an unverified report does not stop expiry forever")


@test
def payment_vs_expiry_race_never_loses_or_duplicates_stock():
    outcomes = {"paid_before_expiry": 0, "expired_then_late_paid": 0}
    for i in range(30):
        reset(stock_a_m=1)
        oid, _ = place(); reserve(oid)
        age_hold(oid)
        pr = f"RACE{i}{uuid.uuid4().hex[:6]}"
        out = parallel([lambda: solo(CLERK, "select verify_payment(%s,%s,'upi',%s,%s, now())", key(), oid, PRICE_A + DELIVERY, pr),
                        lambda: solo(None, "select expire_holds()")])
        check(out[0][0] == "ok", f"verify must always succeed (on time or late): {out}")
        o = order(oid)
        check(o["status"] == "paid" and o["reserved"] and o["paid_paise"] == PRICE_A + DELIVERY, f"must end paid with stock held: {o}")
        check(stock("tst-a-pink", "M") == (1, 1), "the one piece is held exactly once")
        outcomes["expired_then_late_paid" if out[0][1].get("late") else "paid_before_expiry"] += 1
        invariants()
    print(f"        race outcomes over 30 runs: {outcomes}")


@test
def expiry_skips_an_order_whose_payment_is_being_verified_right_now():
    reset(stock_a_m=1)
    oid, _ = place(); reserve(oid); age_hold(oid)
    a = ENV.connect(CLERK); a.autocommit = False                     # staff taps "Payment verified": transaction open, order row locked
    a.execute("select verify_payment(%s,%s,'upi',%s,'UPIHOLD1', now())", (key(), oid, PRICE_A + DELIVERY))
    t0 = time.time()
    n = ok(None, "select expire_holds()")                            # the scheduler fires meanwhile: must skip, not wait, not release
    check(n == 0 and time.time() - t0 < 5, f"expiry must skip a locked order instantly (released {n}, took {time.time() - t0:.1f}s)")
    a.commit(); a.close()
    o = order(oid)
    check(o["status"] == "paid" and o["reserved"] and stock("tst-a-pink", "M") == (1, 1), "payment won: paid, stock still held")
    check(ok(None, "select expire_holds()") == 0, "and expiry now has nothing to release")
    invariants()


@test
def late_payment_when_the_piece_was_sold_elsewhere_becomes_a_refund_due_not_an_oversell():
    reset(stock_a_m=1)
    oid, _ = place(); reserve(oid); age_hold(oid); ok(None, "select expire_holds()")
    ok(CLERK, "select complete_sale(%s,%s::jsonb,%s::jsonb,0)", key(), '[{"barcode":"8900000000011","qty":1}]', f'[{{"method":"cash","amount_paise":{PRICE_A}}}]')
    r = pay(oid)
    check(r["status"] == "refund_due" and r["stock_gone"], f"late payment with no stock must become refund due: {r}")
    check(stock("tst-a-pink", "M") == (0, 0), "no oversell")
    check(q1("select status from refunds where order_id=%s", oid) == "due", "refund is DUE, not auto-completed")
    check(q1("select count(*) from payments where order_id=%s", oid) == 1, "the money that really arrived is on record")
    invariants()


@test
def late_payment_with_stock_still_free_restores_the_hold():
    reset()
    oid, _ = place(("tst-a-pink", "M", 2)); reserve(oid); age_hold(oid); ok(None, "select expire_holds()")
    r = pay(oid)
    check(r["status"] == "paid" and r["late"], "late payment, stock free: paid")
    check(order(oid)["reserved"] and stock("tst-a-pink", "M") == (5, 2), "stock re-held")
    invariants()


# ───────────────────────── 6. retries & duplicates ─────────────────────────
@test
def replays_do_not_double_anything():
    reset()
    oid, _ = place(("tst-a-pink", "M", 2))
    k1 = key()
    a = reserve(oid, idem=k1); b = reserve(oid, idem=k1)
    check(a == b and stock("tst-a-pink", "M") == (5, 2), "replayed Confirm & Reserve reserves once")
    k2, pr = key(), "UPIREPLAY1"
    pay(oid, idem=k2, ref=pr); pay(oid, idem=k2, ref=pr)
    check(q1("select count(*) from payments") == 1, "replayed verification records one payment")
    k3 = key()
    ok(CLERK, "select dispatch_order(%s,%s,'T')", k3, oid); ok(CLERK, "select dispatch_order(%s,%s,'T')", k3, oid)
    check(stock("tst-a-pink", "M") == (3, 0), "replayed dispatch deducts once")
    err(CLERK, "select dispatch_order(%s,%s,'T')", key(), oid, contains="cannot")
    check(stock("tst-a-pink", "M") == (3, 0), "a second dispatch with a NEW key is refused and deducts nothing")
    err(CLERK, "select pack_order(%s,%s)", k3, oid, contains="different action")
    invariants()


@test
def simultaneous_double_tap_on_verify_and_dispatch():
    reset()
    oid, _ = place(); reserve(oid)
    k = key()
    out = parallel([lambda: solo(CLERK, "select verify_payment(%s,%s,'upi',%s,'UPITAP1', now())", k, oid, PRICE_A + DELIVERY)] * 4)
    check(all(r[0] == "ok" for r in out) and q1("select count(*) from payments") == 1, f"four taps, one payment: {out}")
    k = key()
    out = parallel([lambda: solo(CLERK, "select dispatch_order(%s,%s,'')", k, oid)] * 4)
    check(all(r[0] == "ok" for r in out) and stock("tst-a-pink", "M") == (4, 0), f"four taps, one deduction: {out}")
    out = parallel([lambda: solo(CLERK, "select mark_delivered(%s,%s)", key(), oid)] * 4)      # different keys: one wins, others see a wrong state
    check(sum(r[0] == "ok" for r in out) == 1, f"different-key duplicates: exactly one succeeds: {out}")
    invariants()


@test
def same_upi_reference_cannot_pay_two_orders():
    reset()
    a, _ = place(phone="9000000001"); b, _ = place(phone="9000000002")
    reserve(a); reserve(b)
    pay(a, ref="UPISHARED1")
    err(CLERK, "select verify_payment(%s,%s,'upi',%s,'upishared1', now())", key(), b, PRICE_A + DELIVERY, contains="payments_upi_ref_once")
    check(order(b)["status"] == "awaiting_payment", "the second order stays unpaid")


@test
def a_failed_reservation_changes_nothing_and_can_be_retried_with_the_same_key():
    reset(stock_a_m=5, stock_b_m=0)
    oid, _ = place(("tst-a-pink", "M", 2), ("tst-b-blue", "M", 1))
    k = key()
    err(CLERK, "select confirm_and_reserve(%s,%s,%s,0)", k, oid, DELIVERY, contains="not enough stock")
    check(stock("tst-a-pink", "M") == (5, 0), "line 1 must NOT stay reserved when line 2 is short")
    check(order(oid)["status"] == "request", "order unchanged")
    check(q1("select count(*) from idempotency where key=%s", k) == 0, "a failed attempt must not consume its key")
    ok(OWNER, "select receive_stock(%s,%s,2,'late delivery')", key(), vid_of("tst-b-blue", "M"))
    ok(CLERK, "select confirm_and_reserve(%s,%s,%s,0)", k, oid, DELIVERY)
    check(order(oid)["status"] == "awaiting_payment", "retry with the same key works once stock exists")
    invariants()


# ───────────────────────── 7. negative stock & stock keeping ─────────────────────────
@test
def stock_can_never_go_negative_or_over_reserved():
    reset(stock_a_m=2)
    for sql in ("update stock_levels set on_hand = -1", "update stock_levels set reserved = on_hand + 1", "update stock_levels set reserved = -1"):
        err(None, sql, contains="violates check")
    err(OWNER, "select receive_stock(%s,%s,-3,'x')", key(), vid_of("tst-a-pink", "M"), contains="positive")
    oid, _ = place(("tst-a-pink", "M", 2)); reserve(oid)
    err(DAD, "select recount_stock(%s,%s,1,'miscount')", key(), vid_of("tst-a-pink", "M"), contains="violates check")
    check(stock("tst-a-pink", "M") == (2, 2), "recount below what is held for customers is refused")
    ok(DAD, "select recount_stock(%s,%s,4,'found two more')", key(), vid_of("tst-a-pink", "M"))
    check(stock("tst-a-pink", "M") == (4, 2), "recount recorded")
    err(CLERK, "select recount_stock(%s,%s,9,'x')", key(), vid_of("tst-a-pink", "M"), contains="manager")
    invariants()


@test
def every_stock_change_is_an_immutable_audited_event():
    reset()
    oid, _ = place(); reserve(oid); pay(oid)
    ok(CLERK, "select dispatch_order(%s,%s,'')", key(), oid)
    ev = q("select kind, d_on_hand, d_reserved, actor from stock_events where variant_id=%s order by id", vid_of("tst-a-pink", "M"))
    check([e[0] for e in ev] == ["receive", "reserve", "dispatch"], f"ledger kinds: {ev}")
    check(ev[2][1:3] == (-1, -1) and ev[1][1:3] == (0, 1), "ledger deltas")
    check(ev[1][3] == "Clerk (test staff)", "the actor is recorded")
    for sql in ("update stock_events set reason='x'", "delete from stock_events", "update order_events set note='x'", "delete from order_events",
                "update payments set amount_paise=1", "delete from payments"):
        err(None, sql, contains="append-only")
    invariants()


# ───────────────────────── 8. cancel, refund, return ─────────────────────────
@test
def cancelled_orders_release_stock_and_paid_orders_cannot_be_cancelled():
    reset()
    a, _ = place(("tst-a-pink", "M", 2), phone="9000000001")
    ok(CLERK, "select cancel_order(%s,%s,'changed mind')", key(), a)
    check(order(a)["status"] == "cancelled", "cancel a plain request")
    b, _ = place(("tst-a-pink", "M", 2), phone="9000000002"); reserve(b)
    k = key(); ok(CLERK, "select cancel_order(%s,%s,'no answer')", k, b); ok(CLERK, "select cancel_order(%s,%s,'no answer')", k, b)
    check(stock("tst-a-pink", "M") == (5, 0) and not order(b)["reserved"], "held stock released once")
    c, _ = place(phone="9000000003"); reserve(c); pay(c)
    err(CLERK, "select cancel_order(%s,%s,'oops')", key(), c, contains="cannot cancel")
    check(order(c)["status"] == "paid", "paid orders are not cancellable; they go through a refund decision")
    invariants()


@test
def refunds_are_decided_and_completed_by_people_only():
    reset()
    oid, _ = place(); reserve(oid); pay(oid)
    err(CLERK, "select request_refund(%s,%s,'no rider')", key(), oid, contains="manager")
    err(DAD, "select request_refund(%s,%s,'')", key(), oid, contains="reason")
    r = ok(DAD, "select request_refund(%s,%s,'no rider within 24 hours')", key(), oid)
    o = order(oid)
    check(o["status"] == "refund_due" and not o["reserved"], "refund due, hold released by an explicit manager decision")
    check(stock("tst-a-pink", "M") == (5, 0), "piece back on the shelf")
    ok(None, "select expire_holds(now() + interval '30 days')")
    check(q1("select status from refunds where id=%s", r["refund_id"]) == "due", "nothing automatic completes a refund")
    err(CLERK, "select mark_refund_sent(%s,%s,'UPIREF')", key(), r["refund_id"], contains="manager")
    err(DAD, "select mark_refund_sent(%s,%s,'  ')", key(), r["refund_id"], contains="reference")
    ok(DAD, "select mark_refund_sent(%s,%s,'UPIREFUND1')", key(), r["refund_id"])
    check(order(oid)["status"] == "refunded" and q1("select count(*) from payments where kind='refund'") == 1, "refunded only after a person recorded it")
    err(DAD, "select mark_refund_sent(%s,%s,'UPIREFUND2')", key(), r["refund_id"], contains="not due")
    invariants()


@test
def returns_restock_only_what_was_actually_sold():
    reset()
    oid, _ = place(("tst-a-pink", "M", 2)); reserve(oid); pay(oid)
    err(DAD, "select return_to_stock(%s,%s,1,%s,null,'x')", key(), vid_of("tst-a-pink", "M"), oid, contains="did not take")
    ok(CLERK, "select dispatch_order(%s,%s,'')", key(), oid); ok(CLERK, "select mark_delivered(%s,%s)", key(), oid)
    err(CLERK, "select return_to_stock(%s,%s,1,%s,null,'x')", key(), vid_of("tst-a-pink", "M"), oid, contains="manager")
    ok(DAD, "select return_to_stock(%s,%s,1,%s,null,'size exchange, checked')", key(), vid_of("tst-a-pink", "M"), oid)
    check(stock("tst-a-pink", "M") == (4, 0), "one piece back")
    err(DAD, "select return_to_stock(%s,%s,2,%s,null,'x')", key(), vid_of("tst-a-pink", "M"), oid, contains="more returned")
    sale = ok(CLERK, "select complete_sale(%s,%s::jsonb,%s::jsonb,0)", key(), '[{"barcode":"8900000000012","qty":1}]', f'[{{"method":"cash","amount_paise":{PRICE_A}}}]')
    ok(DAD, "select return_to_stock(%s,%s,1,null,%s,'counter return')", key(), vid_of("tst-a-pink", "L"), sale["sale_id"])
    check(stock("tst-a-pink", "L") == (5, 0), "counter return restocks")
    invariants()


# ───────────────────────── 9. POS foundations ─────────────────────────
@test
def counter_sale_by_barcode_with_split_payment_and_receipt():
    reset()
    lines = '[{"barcode":"8900000000011","qty":2},{"product_id":"tst-b-blue","size":"M","qty":1}]'
    total = 2 * PRICE_A + PRICE_B
    pays = f'[{{"method":"cash","amount_paise":{total - 100000}}},{{"method":"upi","amount_paise":100000,"upi_ref":"UPICOUNTER1"}}]'
    err(CLERK, "select complete_sale(%s,%s::jsonb,%s::jsonb,0)", key(), lines, f'[{{"method":"cash","amount_paise":{total - 1}}}]', contains="do not equal")
    k = key()
    s = ok(CLERK, "select complete_sale(%s,%s::jsonb,%s::jsonb,0)", k, lines, pays)
    s2 = ok(CLERK, "select complete_sale(%s,%s::jsonb,%s::jsonb,0)", k, lines, pays)
    check(s == s2 and q1("select count(*) from sales") == 1, "replay returns the same sale")
    check(stock("tst-a-pink", "M") == (3, 0) and stock("tst-b-blue", "M") == (4, 0), "deducted once")
    rc = ok(CLERK, "select get_receipt(%s)", s["sale_id"])
    check(rc["total_paise"] == total and len(rc["lines"]) == 2 and len(rc["payments"]) == 2 and rc["receipt_no"] == s["receipt_no"], f"receipt: {rc}")
    check(q1("select count(*) from stock_events where sale_id=%s and kind='sale'", s["sale_id"]) == 2, "ledger rows for the sale")
    err(CLERK, "select complete_sale(%s,%s::jsonb,%s::jsonb,500)", key(), lines, pays, contains="manager")
    d = ok(DAD, "select complete_sale(%s,%s::jsonb,%s::jsonb,5000)", key(), '[{"barcode":"8900000000012","qty":1}]', f'[{{"method":"cash","amount_paise":{PRICE_A - 5000}}}]')
    check(d["total_paise"] == PRICE_A - 5000, "manager discount applied")
    invariants()


@test
def owner_numbers_come_from_recorded_money_and_keep_channels_apart():
    reset()
    oid, _ = place(); reserve(oid); pay(oid)
    ok(CLERK, "select complete_sale(%s,%s::jsonb,%s::jsonb,0)", key(), '[{"barcode":"8900000000012","qty":1}]', f'[{{"method":"cash","amount_paise":{PRICE_A}}}]')
    rows = {r[0]: r[1:] for r in q("select channel, verified_paise, refunded_paise, net_paise, documents from owner_sales_summary(now() - interval '1 day', now() + interval '1 day')", who=OWNER)}
    check(rows["website"] == (PRICE_A + DELIVERY, 0, PRICE_A + DELIVERY, 1), f"website revenue: {rows['website']}")
    check(rows["counter"] == (PRICE_A, 0, PRICE_A, 1), f"counter revenue: {rows['counter']}")
    r = ok(DAD, "select request_refund(%s,%s,'test refund')", key(), oid)
    rows = {r_[0]: r_[1:] for r_ in q("select channel, verified_paise, refunded_paise, net_paise, documents from owner_sales_summary(now() - interval '1 day', now() + interval '1 day')", who=OWNER)}
    check(rows["website"][1] == 0, "a refund that is only DUE is not counted as refunded")
    ok(DAD, "select mark_refund_sent(%s,%s,'UPIOWNER1')", key(), r["refund_id"])
    rows = {r_[0]: r_[1:] for r_ in q("select channel, verified_paise, refunded_paise, net_paise, documents from owner_sales_summary(now() - interval '1 day', now() + interval '1 day')", who=OWNER)}
    check(rows["website"][1:3] == (PRICE_A + DELIVERY, 0), f"after the refund is recorded as sent, website net is zero: {rows['website']}")


# ───────────────────────── 10. who may do what ─────────────────────────
@test
def the_public_can_only_use_three_functions_and_read_nothing():
    reset()
    oid, ref = place()
    for t in ("orders", "order_lines", "stock_levels", "stock_events", "variants", "products", "payments", "sales", "refunds", "staff", "idempotency", "store_status"):
        err("anon", f"select count(*) from {t}", contains="permission denied")
    for sql in ("select confirm_and_reserve('abcdefgh1','%s',100,0)" % oid, "select verify_payment('abcdefgh2','%s','upi',1,'x',now())" % oid,
                "select dispatch_order('abcdefgh3','%s','')" % oid, "select complete_sale('abcdefgh4','[]','[]',0)", "select owner_sales_summary(now(),now())",
                "select store_ping()", "select receive_stock('abcdefgh5','%s',1,'x')" % vid_of("tst-a-pink", "M"), "select expire_holds()"):
        err("anon", sql, contains="permission denied")
    for sql in ("insert into orders (ref) values ('x')", "update stock_levels set on_hand = 999", "delete from products"):
        err("anon", sql, contains="permission denied")


@test
def staff_roles_are_enforced_in_the_database():
    reset()
    oid, _ = place()
    err(STRANGER, "select confirm_and_reserve(%s,%s,100,0)", key(), oid, contains="not allowed")        # signed in but not on the staff list
    check(q("select * from orders", who=STRANGER) == [], "a signed-in stranger sees no orders (row-level security)")
    check(len(q("select * from orders", who=CLERK)) == 1, "staff see orders")
    check(q("select * from payments", who=CLERK) == [] and q("select * from sales", who=CLERK) == [], "staff cannot read the money ledger")
    err(CLERK, "select owner_sales_summary(now() - interval '1 day', now())", contains="owner")
    err(DAD, "select owner_sales_summary(now() - interval '1 day', now())", contains="owner")
    ok(OWNER, "select owner_sales_summary(now() - interval '1 day', now())")
    for who in (CLERK, DAD, OWNER):
        for sql in ("insert into stock_levels values (gen_random_uuid(), 1, 0)", "update orders set status='paid'", "update stock_levels set on_hand = on_hand + 100", "delete from order_events"):
            err(who, sql, contains="permission denied")
    c = conn(CLERK)
    check(c.execute("select count(*) from staff").fetchone()[0] == 1, "staff can only see their own staff row")


# ───────────────────────── runner ─────────────────────────
def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    ENV.server = pgcluster.make_cluster(preload_cron=True)
    ENV.uri = ENV.server.uri
    v = psycopg.connect(ENV.uri, autocommit=True).execute("select version()").fetchone()[0].split(",")[0]
    print(f"Throwaway database: {v}  (temp folder, invented data only)")
    boot = psycopg.connect(ENV.uri, autocommit=True)
    boot.execute((HERE / "supabase_shim.sql").read_text(encoding="utf-8"))
    for m in MIGRATIONS:
        boot.execute(m.read_text(encoding="utf-8"))
        print(f"Applied {m.name}")
    boot.close()
    passed = failed = 0
    t0 = time.time()
    for fn in TESTS:
        name = fn.__name__.replace("_", " ")
        try:
            fn()
            invariants()
            print(f"  PASS  {name}")
            passed += 1
        except Exception as e:      # noqa: BLE001
            failed += 1
            print(f"  FAIL  {name}\n        {e if isinstance(e, Fail) else repr(e)}")
            if not isinstance(e, Fail):
                traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed in {time.time() - t0:.1f}s")
    for c in _conns.values():
        c.close()
    ENV.server.cleanup()
    return 0 if failed == 0 and passed > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
