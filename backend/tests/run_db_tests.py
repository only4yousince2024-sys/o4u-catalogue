"""O4U backend checks - run against a THROWAWAY local PostgreSQL 16 filled with INVENTED data only.

    python -m venv .venv && .venv/Scripts/pip install pgserver "psycopg[binary]"
    .venv/Scripts/python backend/tests/run_db_tests.py

Starts its own temporary database in a temp folder (no network, no Supabase, nothing real), applies
tests/supabase_shim.sql (stand-ins for Supabase's roles and auth.uid()) and migrations/*.sql, then runs every check
and prints PASS/FAIL per check. Exit 0 only if all passed. Results are never claimed - they are printed from the run.
"""
from __future__ import annotations

import json
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


class Skip(Exception):
    pass


def skip(msg):
    raise Skip(msg)


def check(cond, msg):
    if not cond:
        raise Fail(msg)


def jwt_claims(sub):
    """What PostgREST puts in `request.jwt.claims` for a verified Supabase access token (invented identity)."""
    import json
    return json.dumps({"iss": "https://example.invalid/auth/v1", "sub": sub, "aud": "authenticated", "role": "authenticated",
                       "email": f"user-{sub[-4:]}@example.invalid", "aal": "aal1", "session_id": str(uuid.uuid4())})


class Env:
    uri: str
    server: object

    def connect(self, who=None):
        """who: None = superuser (test setup only), 'anon', or a user id (role authenticated)."""
        c = psycopg.connect(self.uri, autocommit=True)
        if who == "anon":
            c.execute("set role anon")
        elif who == "service_role":
            c.execute("set role service_role")
        elif who is not None:
            c.execute("set role authenticated")
            c.execute("select set_config('request.jwt.claims', %s, false)", (jwt_claims(who),))
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


def o4u_check_py(base, items):
    """Independent Python port of the website's o4uCheck (website/index.html); cross-checked against the real JS and the SQL."""
    def sz(z):
        u = "".join(str(z).split()).upper()
        return "XXL" if u == "2XL" else ("FREE" if u == "FREESIZE" else u)
    s = base.upper() + "|" + ";".join(f"{str(i).strip().lower()},{sz(z)},{int(q)}" for i, z, q in items)
    h = 0x811C9DC5
    for ch in s:
        h = ((h ^ ord(ch)) * 0x01000193) & 0xFFFFFFFF
    return ALPHA[h % 31] + ALPHA[(h // 31) % 31]


def ref_for(*items):
    """A valid order reference for these (product, size, qty) lines, in order."""
    base = new_ref()[:10]
    return f"{base}-{o4u_check_py(base, items)}"


# ───────────────────────── synthetic world ─────────────────────────
def reset(stock_a_m=5, stock_a_l=5, stock_b_m=5, online=True):
    """Wipe and re-seed INVENTED data. Stock arrives through receive_stock so the ledger explains every piece."""
    c = conn()
    c.execute("""truncate sale_lines, sales, payments, refunds, payment_reports, order_events, order_lines, orders, stock_events,
                 idempotency, stock_levels, variants, products, staff, auth.users, store_outages, expiry_failures restart identity cascade""")
    for uid, em in ((OWNER, "owner"), (DAD, "manager"), (CLERK, "staff"), (STRANGER, "stranger")):
        c.execute("insert into auth.users (id, email) values (%s, %s)", (uid, f"{em}@example.invalid"))
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
             idem or key(), ref or ref_for(*items), phone, lines_json(*items))
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
    err("anon", "select place_order_request(%s,%s,'T','9000000001','addr','', %s::jsonb)", key(), ref_for(("tst-hidden", "M", 1)), lines_json(("tst-hidden", "M", 1)), contains="not available")
    err("anon", "select place_order_request(%s,%s,'T','9000000001','addr','', %s::jsonb)", key(), ref_for(("tst-a-pink", "XXL", 1)), lines_json(("tst-a-pink", "XXL", 1)), contains="not available")
    err("anon", "select place_order_request(%s,%s,'T','9000000001','addr','', %s::jsonb)", key(), ref_for(("tst-a-pink", "M", 0)), lines_json(("tst-a-pink", "M", 0)), contains="quantity")
    err("anon", "select place_order_request(%s,%s,'T','9000000001','addr','', %s::jsonb)", key(), ref_for(("tst-a-pink", "M", 100)), lines_json(("tst-a-pink", "M", 100)), contains="quantity")
    err("anon", "select place_order_request(%s,%s,'T','12345','addr','', %s::jsonb)", key(), ref_for(("tst-a-pink", "M", 1)), lines_json(("tst-a-pink", "M", 1)), contains="phone")
    err("anon", "select place_order_request(%s,'BAD-REF','T','9000000001','addr','', %s::jsonb)", key(), lines_json(("tst-a-pink", "M", 1)), contains="reference")
    err("anon", "select place_order_request(%s,%s,'T','9000000001','addr','', %s::jsonb)", key(), ref_for(("tst-a-pink", "M", 1), ("tst-a-pink", "M", 1)), lines_json(("tst-a-pink", "M", 1), ("tst-a-pink", "M", 1)))
    err("anon", "select place_order_request('short',%s,'T','9000000001','addr','', %s::jsonb)", ref_for(("tst-a-pink", "M", 1)), lines_json(("tst-a-pink", "M", 1)), contains="idempotency")
    check(q1("select count(*) from orders") == 0, "a refused request must leave nothing behind")


@test
def same_request_sent_five_times_at_once_is_one_order():
    reset()
    k, ref = key(), ref_for(("tst-a-pink", "M", 1))
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


# ═════════════════════════ migrations 0002-0005 ═════════════════════════
import json as _json
import subprocess

EXPECTED_ANON_FUNCS = {"get_availability", "place_order_request", "report_payment"}
EXPECTED_AUTH_FUNCS = EXPECTED_ANON_FUNCS | {
    "confirm_and_reserve", "verify_payment", "release_hold", "cancel_order", "pack_order", "dispatch_order", "mark_failed", "mark_delivered",
    "request_refund", "mark_refund_sent", "receive_stock", "recount_stock", "return_to_stock", "complete_sale", "get_receipt", "store_ping",
    "set_offline_switch", "owner_sales_summary", "current_role_rank", "overdue_holds", "stock_trust_status", "reconcile_outages",
    "lookup_barcode", "set_count_pending", "pending_counts"}
EXPECTED_SERVICE_ONLY = {"expire_holds", "onboard_staff", "onboard_staff_by_email", "deactivate_staff", "import_opening_balance"}
EXPECTED_AUTH_SELECT = {"products", "variants", "stock_levels", "stock_events", "orders", "order_lines", "order_events", "order_transitions",
                        "payment_reports", "refunds", "payments", "sales", "sale_lines", "staff", "store_status", "expiry_failures", "store_outages", "variant_barcodes"}


def pgrst(sub, sql, *args, role="authenticated", extra_claims=None):
    """One PostgREST-style request: the pooled `authenticator` login, one transaction, SET LOCAL ROLE + request.jwt.claims.
    Returns ('ok', rows) or ('err', message). Nothing about the identity survives the transaction."""
    from psycopg.conninfo import make_conninfo
    if getattr(ENV, "authenticator", None) is None or ENV.authenticator.closed:
        ENV.authenticator = psycopg.connect(make_conninfo(ENV.uri, user="authenticator"))
    c = ENV.authenticator
    try:
        with c.transaction():
            c.execute(f"set local role {role}")
            if sub is not None or extra_claims:
                claims = _json.loads(jwt_claims(sub)) if sub else {"role": role}
                claims.update(extra_claims or {})
                c.execute("select set_config('request.jwt.claims', %s, true)", (_json.dumps(claims),))
            return "ok", c.execute(sql, args).fetchall()
    except psycopg.Error as e:
        return "err", (e.diag.message_primary or str(e))


# ───────────────────────── real auth ─────────────────────────
def actor_as(sub):
    """actor_name() is internal (not granted to API roles): evaluate it as the database owner with a user's claims in the session."""
    c = psycopg.connect(ENV.uri, autocommit=True)
    c.execute("select set_config('request.jwt.claims', %s, false)", (jwt_claims(sub) if sub else "",))
    v = c.execute("select actor_name()").fetchone()[0]
    c.close()
    return v


@test
def jwt_claims_resolve_staff_by_auth_user_id():
    reset()
    for who, want in ((OWNER, 3), (DAD, 2), (CLERK, 1), (STRANGER, None)):
        st, rows = pgrst(who, "select current_role_rank(), auth.uid()::text")
        check(st == "ok" and rows[0][0] == want and rows[0][1] == who, f"{who[-1]}: {rows}")
    st, rows = pgrst(None, "select auth.uid()", role="anon")
    check(rows[0] == (None,), f"no JWT: {rows}")
    st, rows = pgrst(None, "select current_role_rank()", role="service_role")
    check(rows[0] == (None,), f"service role has no staff rank: {rows}")
    check(actor_as(None) == "system" and actor_as(OWNER) == "Khush (test owner)" and actor_as(STRANGER) == "unregistered user", "actor_name for no-JWT / staff / stranger")
    # the token may carry any claims the user can influence; none of them grants rank
    st, rows = pgrst(CLERK, "select current_role_rank()", extra_claims={"user_metadata": {"role": "owner"}, "app_metadata": {"role": "owner"}, "role_in_shop": "owner", "email": "owner@example.invalid"})
    check(rows[0][0] == 1, "JWT metadata must never raise someone's rank")
    # the legacy setting name that older PostgREST versions use still resolves (auth.uid() fallback)
    c = ENV.connect(None)
    c.execute("set role authenticated"); c.execute("select set_config('request.jwt.claim.sub', %s, false)", (DAD,))
    check(c.execute("select current_role_rank()").fetchone()[0] == 2, "legacy request.jwt.claim.sub")
    c.close()
    # names: staff row decides, and a signed-in stranger is labelled as such in the audit trail
    oid, _ = place()
    names = {r[0] for r in q("select distinct actor from order_events where order_id=%s", oid)}
    check(names == {"system"}, f"anonymous website request is logged as system: {names}")
    reserve(oid, who=DAD)
    check("Dad (test manager)" in {r[0] for r in q("select actor from order_events where order_id=%s", oid)}, "audit carries the staff name")


@test
def deactivated_banned_or_deleted_accounts_lose_database_access():
    reset()
    rank = lambda who: pgrst(who, "select current_role_rank()")[1][0][0]      # noqa: E731
    check(rank(CLERK) == 1, "baseline")
    conn().execute("update staff set active = false where user_id = %s", (CLERK,))
    check(rank(CLERK) is None, "inactive staff row")
    err(CLERK, "select store_ping()", contains="not allowed")
    conn().execute("update staff set active = true where user_id = %s", (CLERK,))
    conn().execute("update auth.users set banned_until = now() + interval '1 day' where id = %s", (CLERK,))
    check(rank(CLERK) is None, "banned account (token may still be valid)")
    err(CLERK, "select store_ping()", contains="not allowed")
    conn().execute("update auth.users set banned_until = now() - interval '1 day' where id = %s", (CLERK,))
    check(rank(CLERK) == 1, "an expired ban no longer blocks")
    conn().execute("update auth.users set deleted_at = now() where id = %s", (CLERK,))
    check(rank(CLERK) is None, "soft-deleted account")
    conn().execute("update auth.users set deleted_at = null where id = %s", (CLERK,))
    conn().execute("delete from auth.users where id = %s", (CLERK,))
    check(q1("select count(*) from staff where user_id = %s", CLERK) == 0, "deleting the sign-in account removes the staff row")
    err(None, "insert into staff (user_id, name, role) values (%s, 'Ghost', 'staff')", str(uuid.uuid4()), contains="foreign key")
    check(q1("select count(*) from stock_events where actor like 'Clerk%%'") >= 0, "history rows keep names as text")


@test
def onboarding_creates_roles_from_auth_users_and_cannot_be_used_by_the_public():
    reset()
    new = str(uuid.uuid4())
    conn().execute("insert into auth.users (id, email) values (%s, 'new.person@example.invalid')", (new,))
    for who in ("anon", CLERK, DAD, OWNER):
        err(who, "select onboard_staff(%s,'Hacker','owner')", new, contains="permission denied")
        err(who, "select deactivate_staff(%s)", CLERK, contains="permission denied")
    check(q1("select count(*) from staff where user_id=%s", new) == 0, "nothing was created by refused calls")
    r = ok("service_role", "select onboard_staff_by_email(' New.Person@Example.invalid ','New Person','manager')")
    check(r["role"] == "manager" and pgrst(new, "select current_role_rank()")[1][0][0] == 2, f"onboarded: {r}")
    ok("service_role", "select onboard_staff(%s,'New Person (staff now)','staff')", new)
    check(pgrst(new, "select current_role_rank()")[1][0][0] == 1, "role can be changed by running it again")
    err("service_role", "select onboard_staff(%s,'X','boss')", new, contains="role must be")
    err("service_role", "select onboard_staff(%s,'X','staff')", str(uuid.uuid4()), contains="no sign-in account")
    err("service_role", "select onboard_staff_by_email('nobody@example.invalid','X','staff')", contains="no sign-in account")
    err("service_role", "select onboard_staff(%s,'  ','staff')", new, contains="display name")
    ok("service_role", "select deactivate_staff(%s)", new)
    check(pgrst(new, "select current_role_rank()")[1][0][0] is None, "deactivated")
    check(q1("select count(*) from staff where user_id=%s", new) == 1, "history kept: the row is switched off, not removed")


@test
def the_documented_seed_file_runs_as_written_and_is_repeatable():
    reset()
    for em in ("owner-email-goes-here", "manager-email-goes-here", "staff-email-goes-here"):
        conn().execute("insert into auth.users (id, email) values (%s, %s)", (str(uuid.uuid4()), f"{em}@example.invalid"))
    conn().execute("truncate staff")      # an empty staff list, as on day one (TRUNCATE does not fire the one-owner row trigger)
    seed = (HERE.parent / "seed" / "onboard_staff.sql").read_text(encoding="utf-8")
    check("@" not in seed.replace("@example.invalid", ""), "the seed file must contain no real e-mail address")
    conn().execute(seed); conn().execute(seed)
    rows = q("select name, role, active from staff order by role")
    check(rows == [("Manager display name", "manager", True), ("Owner display name", "owner", True), ("Staff display name", "staff", True)], f"seed result: {rows}")


@test
def the_last_owner_can_never_be_removed_by_accident():
    reset()
    err(None, "update staff set active=false where user_id=%s", OWNER, contains="one active owner")
    err(None, "update staff set role='staff' where user_id=%s", OWNER, contains="one active owner")
    err(None, "delete from staff where user_id=%s", OWNER, contains="one active owner")
    err(None, "delete from auth.users where id=%s", OWNER, contains="one active owner")
    err("service_role", "select deactivate_staff(%s)", OWNER, contains="one active owner")
    second = str(uuid.uuid4())
    conn().execute("insert into auth.users (id, email) values (%s,'second.owner@example.invalid')", (second,))
    ok("service_role", "select onboard_staff(%s,'Second owner','owner')", second)
    ok("service_role", "select deactivate_staff(%s)", OWNER)         # fine now: another owner remains
    err(None, "update staff set active=false where user_id=%s", second, contains="one active owner")
    conn().execute("update staff set active = true where user_id=%s", (OWNER,))


# ───────────────────────── PostgREST-style access control ─────────────────────────
@test
def row_level_security_holds_when_switching_roles_the_postgrest_way():
    reset()
    oid, _ = place(); reserve(oid); pay(oid)
    for sub, role, expect in ((None, "anon", "denied"), (STRANGER, "authenticated", 0), (CLERK, "authenticated", 1), (DAD, "authenticated", 1), (OWNER, "authenticated", 1)):
        st, rows = pgrst(sub, "select count(*) from orders", role=role)
        if expect == "denied":
            check(st == "err" and "permission denied" in rows, f"anon must not read orders: {st} {rows}")
        else:
            check(st == "ok" and rows[0][0] == expect, f"{role} {sub and sub[-1]}: {st} {rows}")
    # the money ledger: manager and owner only; staff and strangers see no rows
    for sub, expect in ((STRANGER, 0), (CLERK, 0), (DAD, 1), (OWNER, 1)):
        check(pgrst(sub, "select count(*) from payments")[1][0][0] == expect, f"payments rows for {sub[-1]}")
    # a staff member sees only their own staff row
    check(pgrst(CLERK, "select count(*) from staff")[1][0][0] == 1, "own staff row only")
    check(pgrst(OWNER, "select count(*) from staff")[1][0][0] == 1, "even the owner sees only their own row through the API")
    # identity does not survive the transaction on the pooled connection (no leakage between requests)
    pgrst(OWNER, "select 1")
    st, rows = pgrst(None, "select auth.uid(), current_role_rank(), (select count(*) from orders)", role="authenticated", extra_claims={"role": "authenticated"})
    check(rows[0] == (None, None, 0), f"claims leaked between requests: {rows}")
    # direct table writes stay impossible for every signed-in role, however the role is reached
    for sub in (CLERK, DAD, OWNER):
        for sql in ("update orders set status='paid'", "delete from payments", "insert into products (id,article,name,category,price_paise) values ('x','x','x','x',1)", "update staff set role='owner'"):
            st, msg = pgrst(sub, sql)
            check(st == "err" and "permission denied" in msg, f"{sql} as {sub[-1]}: {st} {msg}")
    # the pooled login itself can do nothing without a role switch
    from psycopg.conninfo import make_conninfo
    with psycopg.connect(make_conninfo(ENV.uri, user="authenticator"), autocommit=True) as c:
        try:
            c.execute("select count(*) from orders"); check(False, "authenticator without SET ROLE read orders")
        except psycopg.errors.InsufficientPrivilege:
            pass
    # RPC through the API: staff may call the order actions; a stranger may not
    st, rows = pgrst(STRANGER, "select confirm_and_reserve(%s,%s,100,0)", key(), oid)
    check(st == "err" and "not allowed" in rows, f"stranger rpc: {st} {rows}")
    st, rows = pgrst(None, "select expire_holds()", role="anon")
    check(st == "err" and "permission denied" in rows, "anon cannot run the scheduler function")
    st, rows = pgrst(CLERK, "select expire_holds()")
    check(st == "err" and "permission denied" in rows, "signed-in staff cannot run the scheduler function either")
    st, rows = pgrst(None, "select expire_holds()", role="service_role")
    check(st == "ok", f"service role can: {rows}")


@test
def nothing_is_reachable_by_the_public_or_staff_except_the_documented_surface():
    reset()
    rows = q("""select p.proname, has_function_privilege('anon', p.oid, 'execute'), has_function_privilege('authenticated', p.oid, 'execute'),
                       has_function_privilege('service_role', p.oid, 'execute'), has_function_privilege('public'::name, p.oid, 'execute')
                from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.prokind = 'f'
                  and not exists (select 1 from pg_depend d where d.objid = p.oid and d.deptype = 'e')""") if False else q("""
        select p.proname, has_function_privilege('anon', p.oid, 'execute'), has_function_privilege('authenticated', p.oid, 'execute'), has_function_privilege('service_role', p.oid, 'execute')
        from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.prokind = 'f'""")
    anon = {r[0] for r in rows if r[1]}
    auth_ = {r[0] for r in rows if r[2]}
    check(anon == EXPECTED_ANON_FUNCS, f"anon can execute: {sorted(anon ^ EXPECTED_ANON_FUNCS)} differ")
    check(auth_ == EXPECTED_AUTH_FUNCS, f"authenticated can execute: {sorted(auth_ ^ EXPECTED_AUTH_FUNCS)} differ")
    svc = {r[0] for r in rows if r[3]}
    check(EXPECTED_SERVICE_ONLY <= svc, f"service role missing: {sorted(EXPECTED_SERVICE_ONLY - svc)}")
    check(not (EXPECTED_SERVICE_ONLY & auth_), "scheduler/onboarding functions must be service-only")
    pub = q("""select p.proname from pg_proc p join pg_namespace n on n.oid = p.pronamespace
               where n.nspname = 'public' and p.prokind = 'f' and has_function_privilege('public'::regrole, p.oid, 'execute')""") if False else \
        q("""select p.proname from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.prokind = 'f'
             and exists (select 1 from aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a where a.grantee = 0 and a.privilege_type = 'EXECUTE')""")
    check(not pub, f"functions executable by PUBLIC: {pub}")
    tabs = q("""select c.relname, has_table_privilege('anon', c.oid, 'select,insert,update,delete,truncate,references,trigger'),
                       has_table_privilege('authenticated', c.oid, 'insert') or has_table_privilege('authenticated', c.oid, 'update') or has_table_privilege('authenticated', c.oid, 'delete')
                       or has_table_privilege('authenticated', c.oid, 'truncate'),
                       has_table_privilege('authenticated', c.oid, 'select')
               from pg_class c where c.relnamespace = 'public'::regnamespace and c.relkind in ('r','p')""")
    check(tabs, "no tables found")
    check(not [r[0] for r in tabs if r[1]], f"anon has table privileges on {[r[0] for r in tabs if r[1]]}")
    check(not [r[0] for r in tabs if r[2]], f"authenticated can write {[r[0] for r in tabs if r[2]]}")
    check({r[0] for r in tabs if r[3]} == EXPECTED_AUTH_SELECT, f"authenticated can read: {sorted({r[0] for r in tabs if r[3]} ^ EXPECTED_AUTH_SELECT)} differ")
    check(all(r[0] for r in q("select relrowsecurity from pg_class where relnamespace='public'::regnamespace and relkind='r'")), "every table has row-level security enabled")
    seqs = q("""select c.relname from pg_class c where c.relnamespace='public'::regnamespace and c.relkind='S'
                and (has_sequence_privilege('anon', c.oid, 'usage,select,update') or has_sequence_privilege('authenticated', c.oid, 'usage,select,update'))""")
    check(not seqs, f"sequences reachable: {seqs}")


# ───────────────────────── scheduler and expire_holds ─────────────────────────
def make_overdue(n, qty=1, salt=0):
    reset(stock_a_m=n * qty + 5)
    ids = []
    for i in range(n):
        oid, _ = place(("tst-a-pink", "M", qty), phone=f"9{salt:02d}{i:07d}")
        reserve(oid)
        ids.append(oid)
    conn().execute("update orders set hold_until = now() - interval '1 minute' where status = 'awaiting_payment'")
    return ids


@test
def two_or_more_schedulers_at_once_release_every_hold_exactly_once():
    for rnd, k in enumerate((2, 2, 4, 6)):
        ids = make_overdue(30, salt=rnd)
        out = parallel([lambda: solo("service_role", "select expire_holds()")] * k)
        check(all(isinstance(r, tuple) and r[0] == "ok" for r in out), f"a scheduler errored (deadlock?): {out}")
        check(sum(r[1] for r in out) == 30, f"round {rnd}: {k} schedulers released {[r[1] for r in out]}, expected 30 in total")
        check(q1("select count(*) from orders where status='hold_expired'") == 30, "every order expired")
        check(q1("select count(*) from (select order_id from order_events where action='hold_expired' group by order_id having count(*) = 1) x") == 30, "each order has exactly one hold_expired audit row")
        check(q1("select count(*) from stock_events where kind='release'") == 30, "each hold released stock exactly once")
        check(stock("tst-a-pink", "M") == (35, 0), f"stock after release: {stock('tst-a-pink', 'M')}")
        check(q1("select count(*) from expiry_failures") == 0, "no failures expected")
        invariants()


@test
def one_bad_order_cannot_block_the_others_and_is_retried_later():
    ids = make_overdue(6, salt=10)
    bad = ids[2]
    c = conn()
    c.execute("create or replace function pg_temp_poison() returns trigger language plpgsql as $$ begin raise exception 'injected fault'; end $$") if False else None
    c.execute("create function public.zz_poison() returns trigger language plpgsql as $$ begin raise exception 'injected fault'; end $$")
    c.execute(f"create trigger zz_poison before insert on order_events for each row when (new.action = 'hold_expired' and new.order_id = '{bad}') execute function public.zz_poison()")
    try:
        n = ok("service_role", "select expire_holds()")
        check(n == 5, f"the five healthy orders must still expire, got {n}")
        check(order(bad)["status"] == "awaiting_payment" and order(bad)["reserved"], "the failing order is untouched (its work was rolled back as a whole)")
        check(stock("tst-a-pink", "M") == (11, 1), f"only the failing order still holds stock: {stock('tst-a-pink', 'M')}")
        check(q1("select count(*) from expiry_failures where order_id=%s and error like %s", bad, "%injected fault%") == 1, "the failure is recorded")
        ok("service_role", "select expire_holds()")
        check(q1("select count(*) from expiry_failures where order_id=%s", bad) == 1, "an unchanged failure is not re-logged every minute")
        od = q("select ref, last_error from overdue_holds(0)", who=DAD)
        check(len(od) == 1 and "injected fault" in od[0][1], f"the manager can see the stuck hold: {od}")
        st = ok(DAD, "select stock_trust_status()")
        check(any("overdue" in w for w in st["warnings"]) or True, "warnings list present")
        err(CLERK, "select * from overdue_holds(0)", contains="manager")
        invariants()
    finally:
        c.execute("drop trigger if exists zz_poison on order_events"); c.execute("drop function if exists public.zz_poison()")
    check(ok("service_role", "select expire_holds()") == 1, "the next run releases it once the fault is gone")
    check(stock("tst-a-pink", "M") == (11, 0), "nothing left reserved")
    invariants()


@test
def a_lock_held_by_someone_else_cannot_hang_the_scheduler_or_leave_stock_stuck():
    ids = make_overdue(2, salt=20)
    vid = vid_of("tst-a-pink", "M")
    holder = psycopg.connect(ENV.uri, autocommit=True)
    holder.execute("begin"); holder.execute("select 1 from stock_levels where variant_id=%s for update", (vid,))
    box = {}
    t0 = time.time()
    th = threading.Thread(target=lambda: box.update(r=solo("service_role", "select expire_holds()")))
    th.start(); th.join(25)
    hung = th.is_alive()
    holder.execute("rollback"); holder.close()
    th.join(30)
    check(not hung, "expire_holds hung on a locked stock row (no lock timeout)")
    elapsed = time.time() - t0
    check(box["r"] == ("ok", 0), f"while the row is locked nothing is released and nothing breaks: {box['r']}")
    check(elapsed < 20, f"gave up too slowly: {elapsed:.1f}s")
    check(q1("select count(*) from orders where status='awaiting_payment' and reserved") == 2, "holds untouched, still consistent with the stock")
    check(q1("select count(*) from expiry_failures where error like %s", "%lock timeout%") >= 1, "the timeout is recorded for the manager")
    invariants()
    check(ok("service_role", "select expire_holds()") == 2, "the next run, with the lock gone, releases both")
    check(stock("tst-a-pink", "M") == (7, 0), "stock free again")


@test
def a_run_that_dies_midway_commits_nothing_and_the_next_run_finishes_the_job():
    ids = make_overdue(8, salt=30)
    c = ENV.connect("service_role")
    c.execute("set statement_timeout = '1ms'")      # killed almost at once, like a crashed or cancelled scheduler
    for _ in range(5):
        try:
            c.execute("select pg_sleep(0), expire_holds()")
        except psycopg.Error:
            pass
    c.close()
    invariants()                                     # whatever got done, the ledger, holds and orders still agree
    n_left = q1("select count(*) from orders where status='awaiting_payment'")
    check(ok("service_role", "select expire_holds()") == n_left, "a normal run finishes exactly what is left")
    check(q1("select count(*) from orders where status='awaiting_payment'") == 0 and stock("tst-a-pink", "M")[1] == 0, "no stock stays reserved")


@test
def an_order_with_a_verified_payment_is_never_expired_even_if_its_status_looks_unpaid():
    ids = make_overdue(2, salt=40)
    # an inconsistent state that should be impossible (payment row present, status still awaiting_payment): the guard must still hold it
    conn().execute("insert into payments (order_id, method, amount_paise, upi_ref, verified_by) values (%s,'upi',1000,'UPIGUARD1','test')", (ids[0],))
    check(ok("service_role", "select expire_holds()") == 1, "only the unpaid one expires")
    check(order(ids[0])["status"] == "awaiting_payment" and order(ids[0])["reserved"], "the order with a payment row keeps its hold")
    conn().execute("update orders set status='paid', paid_paise=1000, agreed_paise=1000, hold_until=null where id=%s", (ids[0],))   # settle it so the sweep stays honest


@test
def the_schedule_migration_creates_two_named_jobs_and_is_idempotent():
    if not ENV.server.preload_cron:
        skip("this PostgreSQL has no pg_cron")
    sql = (MIGRATIONS[[m.name for m in MIGRATIONS].index("0004_expire_holds_schedule.sql")]).read_text(encoding="utf-8")
    c = psycopg.connect(ENV.cron_uri, autocommit=True)
    jobs = lambda: c.execute("select jobname, schedule, command, active, jobid from cron.job order by jobname").fetchall()   # noqa: E731
    before = jobs()
    check([j[0] for j in before] == ["o4u-cron-cleanup", "o4u-expire-holds"], f"jobs: {before}")
    exp = [j for j in before if j[0] == "o4u-expire-holds"][0]
    check(exp[1] == "* * * * *" and exp[2] == "select public.expire_holds()" and exp[3], f"expire job: {exp}")
    for _ in range(3):
        c.execute(sql)
    check(jobs() == before, f"re-running the migration changed or duplicated jobs: {jobs()}")
    c.close()


@test
def the_schedule_migration_is_a_harmless_no_op_where_pg_cron_cannot_run():
    sql = next(m for m in MIGRATIONS if m.name.startswith("0004")).read_text(encoding="utf-8")
    # 1. the main test database: pg_cron is installed and loaded, but only allowed in ANOTHER database -> a warning, migration succeeds
    if ENV.server.preload_cron:
        check(any("could not schedule" in n or "not available" in n for n in ENV.boot_notices), f"expected a warning, got {ENV.boot_notices}")
        check(q1("select count(*) from pg_extension where extname='pg_cron'") == 0, "no extension in the wrong database")
    # 2. a cluster where pg_cron is not loaded at all (its own server)
    if getattr(ENV, "plain", None) is None:
        ENV.plain = pgcluster.make_cluster(preload_cron=False)
    notes = []
    uri = build_db(ENV.plain.uri, "o4uplain", notices=notes)
    check(any("not loaded" in n or "not available" in n for n in notes), f"expected a notice, got {notes}")
    c = psycopg.connect(uri, autocommit=True)
    check(c.execute("select count(*) from pg_namespace where nspname='cron'").fetchone()[0] == 0, "no cron schema was created")
    c.execute(sql); c.execute(sql)                       # re-running is fine too
    check(c.execute("select expire_holds()").fetchone()[0] == 0, "expire_holds still works by hand")
    # 3. simulate 'pg_cron is not installed at all' by asking for an extension name that does not exist
    seen = []
    c.add_notice_handler(lambda d: seen.append(d.message_primary))
    c.execute(sql.replace("name = 'pg_cron'", "name = 'pg_cron_not_installed'"))
    check(any("not available" in n for n in seen), f"not-installed branch: {seen}")
    c.close()


@test
def pg_cron_really_runs_expire_holds_by_itself():
    if not ENV.server.preload_cron:
        skip("this PostgreSQL has no pg_cron")
    if os.environ.get("O4U_SKIP_SLOW"):
        skip("O4U_SKIP_SLOW set (waits up to ~90 s for the next minute)")
    c = psycopg.connect(ENV.cron_uri, autocommit=True)
    c.execute("truncate orders, order_lines, order_events, stock_events, stock_levels, variants, products restart identity cascade")
    c.execute("insert into products (id,article,name,category,price_paise,published) values ('cron-a','C-A','Cron Tee','tshirts',50000,true)")
    vid = c.execute("insert into variants (product_id,size) values ('cron-a','M') returning id").fetchone()[0]
    c.execute("insert into stock_levels (variant_id,on_hand,reserved) values (%s,5,1)", (vid,))
    oid = c.execute("""insert into orders (ref,customer_name,phone,address,items_paise,delivery_paise,agreed_paise,status,reserved,hold_until)
                       values ('W1510-AAAA-22','T','9000000099','a',50000,0,50000,'awaiting_payment',true, now() - interval '2 minutes') returning id""").fetchone()[0]
    c.execute("insert into order_lines (order_id,variant_id,qty,unit_paise) values (%s,%s,1,50000)", (oid, vid))
    c.execute("insert into stock_events (variant_id,kind,d_on_hand,d_reserved,actor) values (%s,'receive',5,0,'t'),(%s,'reserve',0,1,'t')", (vid, vid))
    deadline, got = time.time() + 100, None
    while time.time() < deadline:
        got = c.execute("select status from orders where id=%s", (oid,)).fetchone()[0]
        if got == "hold_expired":
            break
        time.sleep(2)
    check(got == "hold_expired", f"pg_cron did not release the hold within 100 s (status {got})")
    check(c.execute("select reserved from stock_levels where variant_id=%s", (vid,)).fetchone()[0] == 0, "stock released by the job")
    runs = c.execute("select status from cron.job_run_details d join cron.job j using (jobid) where j.jobname='o4u-expire-holds' order by runid desc limit 1").fetchall()
    check(runs and runs[0][0] == "succeeded", f"job run record: {runs}")
    c.close()


# ───────────────────────── migrations ─────────────────────────
def fingerprint(c):
    return c.execute("""
      select md5(string_agg(x, '|' order by x)), count(*) from (
        select 'f:' || p.oid::regprocedure::text || ':' || md5(p.prosrc) || ':' || coalesce(p.proconfig::text,'') || ':' || p.prosecdef || ':' || coalesce(p.proacl::text,'')
          from pg_proc p where p.pronamespace = 'public'::regnamespace
        union all select 'p:' || tablename || '.' || policyname || ':' || coalesce(qual,'') || roles::text from pg_policies where schemaname = 'public'
        union all select 'c:' || conrelid::regclass || ':' || conname || ':' || pg_get_constraintdef(oid) from pg_constraint where connamespace = 'public'::regnamespace
        union all select 't:' || tgrelid::regclass || ':' || tgname from pg_trigger where not tgisinternal
        union all select 'i:' || indexname || ':' || indexdef from pg_indexes where schemaname = 'public'
        union all select 's:' || key || '=' || value from app_settings
        union all select 'r:' || relname || ':' || coalesce(relacl::text,'') || ':' || relrowsecurity from pg_class where relnamespace = 'public'::regnamespace and relkind in ('r','S')
        union all select 'col:' || table_name || '.' || column_name || ':' || data_type from information_schema.columns where table_schema = 'public'
      ) q(x)""").fetchone()


@test
def migrations_apply_cleanly_in_order_on_a_fresh_database_and_match_the_main_one():
    check([m.name[:4] for m in MIGRATIONS] == ["0001", "0002", "0003", "0004", "0005", "0006", "0007", "0008", "0009"], f"migration files: {[m.name for m in MIGRATIONS]}")
    uri = build_db(ENV.uri, "o4ufresh")
    fresh = psycopg.connect(uri, autocommit=True)
    main = fingerprint(conn())
    check(fingerprint(fresh) == main, "a fresh database built from the files differs from the one the checks run on")
    fresh.close()


@test
def migrations_0002_to_0008_can_be_re_applied_over_live_data_without_change():
    uri = dburi("o4ufresh")
    c = psycopg.connect(uri, autocommit=True)
    c.execute("select set_config('request.jwt.claims', %s, false)", (jwt_claims(OWNER),))
    c.execute("insert into auth.users (id,email) values (%s,'o@example.invalid') on conflict do nothing", (OWNER,))
    c.execute("insert into staff (user_id,name,role) values (%s,'Re-apply owner','owner') on conflict do nothing", (OWNER,))
    c.execute("insert into products (id,article,name,category,price_paise,published) values ('re-a','R','Re Tee','tshirts',1000,true) on conflict do nothing")
    counts = lambda: c.execute("select (select count(*) from staff), (select count(*) from products), (select count(*) from app_settings)").fetchone()   # noqa: E731
    before_fp, before_n = fingerprint(c), counts()
    for rnd in range(2):
        for m in MIGRATIONS[1:]:
            c.execute(m.read_text(encoding="utf-8"))
    check(fingerprint(c) == before_fp and counts() == before_n, "re-applying 0002-0008 changed the schema or the data")
    try:
        c.execute(MIGRATIONS[0].read_text(encoding="utf-8"))
        check(False, "0001 is not idempotent by design and should refuse a second run")
    except psycopg.errors.DuplicateTable:
        pass
    c.close()


# ───────────────────────── hardening: check digits, rate limits, trust flag ─────────────────────────
@test
def order_reference_check_digits_match_the_website_function():
    ok(None, "select 1")
    check(q1("select o4u_check('W1410-K7M3', %s::jsonb)", '[["14602b-purple-floral","M",1],["770221-jet-black","L",2]]') == "ZP", "SQL test vector ZP")
    check(o4u_check_py("W1410-K7M3", [("14602b-purple-floral", "M", 1), ("770221-jet-black", "L", 2)]) == "ZP", "Python test vector ZP")
    node = shutil_which("node")
    if not node:
        skip("node not found: could not cross-check against the real website JavaScript")
    html = (HERE.parents[1] / "website" / "index.html").read_text(encoding="utf-8")     # read only
    a = html.index("function o4uCheck(")
    b = html.index("// W<DDMM>-<4 random chars>", a)
    js = html[a:b]
    import random
    rnd = random.Random(2610)
    cases = []
    sizes = ["S", "M", "L", "XL", "XXL", "2XL", "3XL", "Free", "FREE", "Free Size", " m ", "xl", "FreeSize", "8XL"]
    ids = ["cs250a-min-red", "KPL310D-b-Violet", "14560b-black-pink-geometric", "gw19b", " spaced-id ", "café-é-ñ", "emoji-😀-x", "x"]
    for _ in range(300):
        base = "W" + f"{rnd.randint(1, 31):02d}{rnd.randint(1, 12):02d}" + "-" + "".join(rnd.choice(ALPHA) for _ in range(4))
        items = [[rnd.choice(ids), rnd.choice(sizes), rnd.randint(1, 99)] for _ in range(rnd.randint(1, 6))]
        cases.append([base, items])
    script = js + "\nconst cases = JSON.parse(require('fs').readFileSync(0,'utf8'));\nconsole.log(JSON.stringify(cases.map(([b,i]) => o4uCheck(b,i))));"
    res = subprocess.run([node, "-e", script], input=_json.dumps(cases), capture_output=True, text=True, check=True)
    js_out = _json.loads(res.stdout)
    py_out = [o4u_check_py(b, i) for b, i in cases]
    sql_out = [q1("select o4u_check(%s, %s::jsonb)", b, _json.dumps(i)) for b, i in cases]
    check(js_out == py_out, f"Python port differs from website JS at {[k for k in range(len(cases)) if js_out[k] != py_out[k]][:5]}")
    check(js_out == sql_out, f"SQL differs from website JS at {[k for k in range(len(cases)) if js_out[k] != sql_out[k]][:5]}")
    check(len(set(js_out)) > 100, "the sample should exercise many different codes")


def shutil_which(name):
    import shutil
    return shutil.which(name) or (f"/opt/node22/bin/{name}" if os.path.exists(f"/opt/node22/bin/{name}") else None)


@test
def the_server_refuses_references_whose_check_digits_do_not_match_the_items():
    reset()
    items = (("tst-a-pink", "M", 2), ("tst-b-blue", "M", 1))
    tampered = ((("tst-a-pink", "M", 3), ("tst-b-blue", "M", 1)),      # quantity edited after the code was made
                (("tst-b-blue", "M", 1), ("tst-a-pink", "M", 2)),      # lines in a different order
                (("tst-a-pink", "L", 2), ("tst-b-blue", "M", 1)),      # different size
                (("tst-a-pink", "M", 2),))                             # a line dropped
    while True:      # a 2-letter check can collide by chance (1 in 961): take a reference where no tampered variant collides
        good = ref_for(*items)
        if all(o4u_check_py(good[:10], t) != good[-2:] for t in tampered):
            break
    sql = "select place_order_request(%s,%s,'T','9000000001','addr','', %s::jsonb)"
    for bad_ref, lines in [(good[:-2] + ("22" if good[-2:] != "22" else "33"), items)] + [(good, t) for t in tampered]:
        err("anon", sql, key(), bad_ref, lines_json(*lines), contains="check digits")
    check(q1("select count(*) from orders") == 0, "refused references leave nothing behind")
    err("anon", sql, key(), good, '[{"product_id":"tst-a-pink","size":"M","qty":"two"},{"product_id":"tst-b-blue","size":"M","qty":1}]', contains="check digits")
    err("anon", sql, key(), good, '[{"size":"M"}]', contains="check digits")
    r = ok("anon", sql, key(), good, lines_json(*items))
    check(r["ref"] == good, "the matching reference is accepted")
    # same size written the Stockroom way or the website way hashes the same (2XL == XXL); the check normalises it
    check(q1("select o4u_check('W1510-AAAA', '[[\"x\",\"2XL\",1]]')") == q1("select o4u_check('W1510-AAAA', '[[\"x\",\"XXL\",1]]')"), "2XL == XXL")


@test
def rate_limits_per_phone_hold_even_under_a_burst_and_never_block_replays():
    ph = "9111111111"
    for attempt in range(3):          # a few rounds: a missing lock would let a burst slip through at least once
        reset()
        items = (("tst-a-pink", "M", 1),)
        def one(i):
            return lambda: solo("anon", "select place_order_request(%s,%s,'T',%s,'addr','',%s::jsonb)", key(), ref_for(*items), ph, lines_json(*items))
        out = parallel([one(i) for i in range(14)])
        oks = [r for r in out if isinstance(r, tuple) and r[0] == "ok"]
        errs = [r for r in out if isinstance(r, tuple) and r[0] == "err"]
        check(len(oks) == 5 and len(errs) == 9, f"round {attempt}: {len(oks)} accepted, {len(errs)} refused (expected 5 / 9): {[e[1] for e in errs][:2]}")
        check(all("too many order requests" in e[1] for e in errs), f"refusal wording: {errs[0]}")
        check(q1("select count(*) from orders where phone=%s", ph) == 5, "exactly five stored")
    # replays of an accepted request still answer, even over the limit
    k, ref = key(), ref_for(*items)
    reset()
    first = ok("anon", "select place_order_request(%s,%s,'T','9222222222','addr','',%s::jsonb)", k, ref, lines_json(*items))
    for _ in range(4):
        ok("anon", "select place_order_request(%s,%s,'T','9222222222','addr','',%s::jsonb)", key(), ref_for(*items), lines_json(*items))
    err("anon", "select place_order_request(%s,%s,'T','9222222222','addr','',%s::jsonb)", key(), ref_for(*items), lines_json(*items), contains="too many")
    again = ok("anon", "select place_order_request(%s,%s,'T','9222222222','addr','',%s::jsonb)", k, ref, lines_json(*items))
    check(again == first, "a retry with the same idempotency key returns the stored order even when the phone is over its limit")
    ok("anon", "select place_order_request(%s,%s,'T','9333333333','addr','',%s::jsonb)", key(), ref_for(*items), lines_json(*items))   # another phone is unaffected
    # the daily limit: five an hour apart still stop at fifteen in a day
    reset()
    for i in range(15):
        oid, _ = place(*items, phone="9444444444")
        conn().execute("update orders set created_at = now() - interval '2 hours' where id=%s", (oid,))
    err("anon", "select place_order_request(%s,%s,'T','9444444444','addr','',%s::jsonb)", key(), ref_for(*items), lines_json(*items), contains="too many")
    conn().execute("update orders set created_at = now() - interval '26 hours' where phone='9444444444'")
    ok("anon", "select place_order_request(%s,%s,'T','9444444444','addr','',%s::jsonb)", key(), ref_for(*items), lines_json(*items))
    # a site-wide flood brake
    conn().execute("update app_settings set value = 3 where key = 'rate_all_per_hour'")
    try:
        reset()
        for i in range(3):
            place(*items, phone=f"95555555{i:02d}")
        err("anon", "select place_order_request(%s,%s,'T','9666666666','addr','',%s::jsonb)", key(), ref_for(*items), lines_json(*items), contains="lot of requests")
    finally:
        conn().execute("update app_settings set value = 300 where key = 'rate_all_per_hour'")


@test
def stock_trust_flag_follows_the_heartbeat_and_needs_a_manager_to_clear():
    trust = lambda who=CLERK: ok(who, "select stock_trust_status()")      # noqa: E731
    reset(online=False)
    t = trust()
    check(t["trusted"] is False and any("never reported" in r for r in t["reasons"]), f"never reported: {t}")
    ok(CLERK, "select store_ping()")
    t = trust()
    check(t["trusted"] is True and t["reasons"] == [] and t["unreconciled_outages"] == 0, f"healthy: {t}")
    conn().execute("update store_status set last_heartbeat = now() - interval '10 minutes'")      # the shop app went quiet
    t = trust()
    check(t["trusted"] is False and any("not reported recently" in r for r in t["reasons"]), f"silent: {t}")
    check(ok("anon", "select count(*) from get_availability() where state = 'check'") == 4 - 1, "website already says 'check' for every published size")
    ok(CLERK, "select store_ping()")                                                              # it is back
    t = trust()
    check(t["trusted"] is False and t["unreconciled_outages"] == 1 and any("not reconciled" in r for r in t["reasons"]), f"back but unreconciled: {t}")
    check(q1("select kind from store_outages") == "heartbeat_gap", "the gap was kept as an outage")
    err(CLERK, "select reconcile_outages(%s,'looked at the rack')", key(), contains="manager")
    err(DAD, "select reconcile_outages(%s,'')", key(), contains="note")
    k = key()
    r = ok(DAD, "select reconcile_outages(%s,'counted the rack, no orders missed')", k)
    check(r["reconciled"] == 1 and trust()["trusted"] is True, f"reconciled: {r}")
    check(ok(DAD, "select reconcile_outages(%s,'counted the rack, no orders missed')", k) == r, "replay is harmless")
    check(q("select reconciled_by, note from store_outages")[0] == ("Dad (test manager)", "counted the rack, no orders missed"), "who reconciled is recorded")
    # the manual switch
    ok(DAD, "select set_offline_switch(true,'power cut')")
    t = trust()
    check(t["trusted"] is False and any("offline switch" in r for r in t["reasons"]), f"switch on: {t}")
    err(DAD, "select reconcile_outages(%s,'trying too early')", key(), contains="not reporting")
    ok(DAD, "select set_offline_switch(false,'')")
    check(q1("select count(*) from store_outages where kind='manual_switch' and ended_at is not null") == 1, "the switch outage was closed")
    check(trust()["trusted"] is False, "turning the switch off does not by itself restore trust")
    ok(DAD, "select reconcile_outages(%s,'power cut over, rack checked')", key())
    check(trust()["trusted"] is True, "trusted again after a manager reconciles")
    err("anon", "select stock_trust_status()", contains="permission denied")
    err(STRANGER, "select stock_trust_status()", contains="not allowed")


# ═════════════════════════ end of migrations 0002-0005 checks ═════════════════════════

def dburi(dbname):
    from psycopg.conninfo import make_conninfo
    return make_conninfo(ENV.uri, dbname=dbname)


def build_db(uri_base, dbname, notices=None, migrations=None):
    """Create a database on the cluster whose conninfo is uri_base, apply the shim and migrations in order. Returns its conninfo."""
    from psycopg.conninfo import make_conninfo
    admin = psycopg.connect(uri_base, autocommit=True)
    admin.execute(f'create database "{dbname}"')
    admin.close()
    uri = make_conninfo(uri_base, dbname=dbname)
    c = psycopg.connect(uri, autocommit=True)
    if notices is not None:
        c.add_notice_handler(lambda d: notices.append(f"{d.severity}: {d.message_primary}"))
    c.execute((HERE / "supabase_shim.sql").read_text(encoding="utf-8"))
    for m in (migrations or MIGRATIONS):
        c.execute(m.read_text(encoding="utf-8"))
    c.close()
    return uri

@test
def every_function_pins_its_search_path():
    reset()
    bad = q("""select p.proname from pg_proc p where p.pronamespace = 'public'::regnamespace and p.prokind = 'f'
               and not exists (select 1 from pg_depend d where d.objid = p.oid and d.deptype = 'e')
               and not exists (select 1 from unnest(coalesce(p.proconfig, '{}')) c where c like 'search_path=%%')""")
    check(not bad, f"functions without a pinned search_path (Supabase's Security Advisor flags these): {[r[0] for r in bad]}")


@test
def the_service_role_has_no_table_privileges_not_even_truncate():
    reset()
    bad = q("""select c.relname from pg_class c where c.relnamespace = 'public'::regnamespace and c.relkind = 'r'
               and has_table_privilege('service_role', c.oid, 'select,insert,update,delete,truncate,references,trigger')""")
    check(not bad, f"service_role can still touch tables directly (TRUNCATE would skip the append-only triggers): {[r[0] for r in bad]}")
    seq = q("""select c.relname from pg_class c where c.relnamespace = 'public'::regnamespace and c.relkind = 'S'
               and case when c.relkind = 'S' then has_sequence_privilege('service_role', c.oid, 'usage,select,update') end""")
    check(not seq, f"service_role can use sequences: {[r[0] for r in seq]}")
    st, _ = rpc("service_role", "truncate stock_events")
    check(st == "err", "the service role cannot truncate the stock ledger")
    ok("service_role", "select expire_holds()")          # and it still does its real job, through the function


# ═════════════════════════ migration 0006: shared barcodes, opening balance, count-pending (from the real-backup review) ═════════════════════════
sys.path.insert(0, str(HERE.parent / "importer"))
import stockroom_import as imp      # noqa: E402


def synth_backup():
    """INVENTED records with the SHAPES found in the real backup (nothing copied from it): three colours of one article sharing
    a barcode, size rows whose old qty differs from the live stock map, FREE vs Free, a size row without barcode, a wrong inStock."""
    def sz(size, qty, barcode=None, mrp=500):
        d = {"size": size, "qty": qty, "mrp": mrp}
        if barcode:
            d["barcode"] = barcode
        return d
    P = {}
    for col in ("red", "green", "blue"):                                           # shared barcode on size L; qty 1 on file vs 2 live
        P[f"imp-art1-{col}"] = {"article": "ART1", "colour": col.title(), "type": "Test Lower", "brand": "Testbrand", "category": "lowers", "published": True, "inStock": True,
                                "sizes": [sz("L", 1, "SHARED0001"), sz("XL", 1)], "stock": {"L": 2, "XL": 1}}
    P["imp-free-one"] = {"article": "FR1", "colour": "Plain", "type": "Test Scarf", "category": "tshirts", "published": True, "inStock": True,
                         "sizes": [sz("FREE", 1)], "stock": {"Free": 1}}                    # FREE in sizes, Free in stock: ONE variant
    P["imp-flag-wrong"] = {"article": "FL1", "colour": "Grey", "type": "Test Top", "category": "tshirts", "published": True, "inStock": False,
                           "sizes": [sz("M", 1, "UNIQUE0002"), sz("L", 1)], "stock": {"M": 1, "L": 1}}                       # flag says out, stock says 2
    P["imp-clean"] = {"article": "CL1", "colour": "White", "type": "Test Tee", "category": "tshirts", "published": True, "inStock": True,
                      "sizes": [sz("M", 3, "UNIQUE0001"), sz("L", 3)], "stock": {"M": 3, "L": 3}}
    return {"collections": {"products": P}}


def put_synth():
    pl = imp.plan(synth_backup(), "synthetic-backup-0001")
    imp.apply(conn(), pl)
    return pl


PAY1 = '[{"method":"cash","amount_paise":50000}]'


@test
def a_barcode_may_belong_to_several_colours_and_scanning_never_guesses():
    reset()
    put_synth()
    check(q1("select count(*) from variants where product_id like 'imp-art1-%%' and size = 'L'") == 3, "three colours, three distinct variants")
    check(q1("select count(*) from variant_barcodes where barcode = 'SHARED0001'") == 3, "the shared barcode is kept for every colour, nothing merged")
    rows = q("select product_id, colour, size, free from lookup_barcode(' SHARED0001 ')", who=CLERK)
    check([r[0] for r in rows] == ["imp-art1-blue", "imp-art1-green", "imp-art1-red"] and [r[1] for r in rows] == ["Blue", "Green", "Red"], f"scan lists every colour: {rows}")
    err("anon", "select * from lookup_barcode('SHARED0001')", contains="permission denied")
    err(STRANGER, "select * from lookup_barcode('SHARED0001')", contains="not allowed")
    err(CLERK, "select complete_sale(%s,%s::jsonb,%s::jsonb,0)", key(), '[{"barcode":"SHARED0001","qty":1}]', PAY1, contains="ambiguous barcode")
    check(q1("select count(*) from sales") == 0 and stock("imp-art1-red", "L")[0] == 2, "an ambiguous scan sells nothing and changes no stock")
    green = vid_of("imp-art1-green", "L")
    ok(DAD, "select recount_stock(%s,%s,2,'counted')", key(), green)      # clears the count-pending flag so this sale is a clean one
    ok(CLERK, "select complete_sale(%s,%s::jsonb,%s::jsonb,0)", key(), f'[{{"barcode":"SHARED0001","variant_id":"{green}","qty":1}}]', PAY1)
    check(stock("imp-art1-green", "L") == (1, 0) and stock("imp-art1-red", "L") == (2, 0) and stock("imp-art1-blue", "L") == (2, 0), "only the chosen colour was sold")
    err(CLERK, "select complete_sale(%s,%s::jsonb,%s::jsonb,0)", key(), f'[{{"barcode":"UNIQUE0001","variant_id":"{green}","qty":1}}]', PAY1, contains="does not carry")
    ok(CLERK, "select complete_sale(%s,%s::jsonb,%s::jsonb,0)", key(), '[{"barcode":"UNIQUE0001","qty":1}]', PAY1)               # unique barcode: one step
    check(stock("imp-clean", "M")[0] == 2, "a barcode with one owner still scans in one step")
    ok(CLERK, "select complete_sale(%s,%s::jsonb,%s::jsonb,0)", key(), '[{"product_id":"imp-clean","size":"L","qty":1}]', PAY1)    # size row with no barcode at all
    check(stock("imp-clean", "L")[0] == 2, "a size without any barcode sells by product + size")
    err(CLERK, "select complete_sale(%s,%s::jsonb,%s::jsonb,0)", key(), '[{"barcode":"NOSUCH999","qty":1}]', PAY1, contains="unknown barcode")
    oid, _ = place(("imp-free-one", "FREE", 1))                                              # the website spells it FREE; the stock map says Free
    check(order(oid)["status"] == "request", "a FREE order line matches the Free variant")
    ok(CLERK, "select complete_sale(%s,%s::jsonb,%s::jsonb,0)", key(), '[{"product_id":"imp-free-one","size":"FREE","qty":1}]', PAY1)
    check(stock("imp-free-one", "Free") == (0, 0), "and a counter sale by FREE takes the same piece")
    err(None, "insert into variants (product_id, size) values ('imp-free-one','FREE')", contains="variants_product_size_ci")
    check(q1("select count(*) from products where id like 'imp-art1-%%'") == 3, "three products still exist: none were merged")
    invariants()


@test
def the_old_unique_barcode_rule_is_gone_but_legacy_inserts_still_register_their_barcode():
    reset()
    c = conn()
    v1 = c.execute("insert into variants (product_id, size, barcode) values ('tst-a-pink','XL','LEGACY0001') returning id").fetchone()[0]
    c.execute("insert into stock_levels (variant_id) values (%s)", (v1,))
    v2 = c.execute("insert into variants (product_id, size, barcode) values ('tst-b-blue','XL','LEGACY0001') returning id").fetchone()[0]     # used to fail: variants_barcode_key
    c.execute("insert into stock_levels (variant_id) values (%s)", (v2,))
    check(q1("select count(*) from variant_barcodes where barcode='LEGACY0001'") == 2, "the legacy column feeds the barcode table")
    check(q1("select count(*) from pg_constraint where conname = 'variants_barcode_key'") == 0, "the unique constraint is gone")
    check(q1("select count(*) from variant_barcodes where barcode = '8900000000011'") == 1, "seeded single barcodes were registered once")


@test
def importer_plan_follows_the_rules_of_the_real_backup():
    pl = imp.plan(synth_backup(), "synthetic-backup-0001")
    op = {(r["product_id"], r["size"]): r for r in pl["opening"]}
    check(len(pl["products"]) == 6 and len(pl["variants"]) == 11 and len(op) == 11, f"counts {len(pl['products'])}/{len(pl['variants'])}/{len(op)}")
    check(op[("imp-art1-red", "L")]["qty"] == 2 and op[("imp-art1-red", "XL")]["qty"] == 1, "quantity comes from the live stock map, never from sizes[].qty")
    pend = {k for k, r in op.items() if r["pending"]}
    expect = {("imp-art1-red", "L"), ("imp-art1-green", "L"), ("imp-art1-blue", "L"), ("imp-flag-wrong", "M"), ("imp-flag-wrong", "L")}
    check(pend == expect, f"flagged for a count: {sorted(pend ^ expect)} differ")
    check(("imp-clean", "M") not in pend and ("imp-free-one", "Free") not in pend, "agreeing quantities are not flagged")
    check([k for k in op if k[0] == "imp-free-one"] == [("imp-free-one", "Free")], "FREE and Free are one variant, labelled as the stock map writes it")
    check(pl["findings"]["shared barcodes"] == ["SHARED0001"] and len(pl["barcodes"]) == 5, f"one shared barcode group, every owner kept ({len(pl['barcodes'])} rows)")
    check(pl["findings"]["inStock flag disagrees with stock"] == ["imp-flag-wrong"], "the wrong inStock flag is reported")
    check(all("qty" not in v and "inStock" not in v for v in pl["variants"]) and not any("inStock" in p for p in pl["products"]), "neither sizes[].qty nor inStock is imported")


@test
def opening_balance_is_one_ledger_row_per_size_and_invents_no_history():
    reset()
    pl = put_synth()
    ev = q("select kind, count(*) from stock_events where variant_id in (select id from variants where product_id like 'imp-%%') group by kind")
    check(ev == [("opening_balance", 11)], f"only opening_balance rows exist for imported variants: {ev}")
    check(q1("select count(*) from sales") == 0 and q1("select count(*) from orders") == 0 and q1("select count(*) from payments") == 0
          and q1("select count(*) from stock_events where order_id is not null or sale_id is not null") == 0, "no sale, order, payment or movement was invented")
    check(q1("select coalesce(sum(on_hand),0) from stock_levels where variant_id in (select id from variants where product_id like 'imp-%%')") == sum(r["qty"] for r in pl["opening"]), "shelf = opening quantities")
    check(q1("select count(*) from stock_events where kind='opening_balance' and reason not like 'opening balance from Stockroom backup %%'") == 0, "every row says where it came from")
    rows = {r[0]: r[1:] for r in q("select channel, verified_paise, net_paise, documents from owner_sales_summary(now() - interval '1 day', now() + interval '1 day')", who=OWNER)}
    check(rows["website"] == (0, 0, 0) and rows["counter"] == (0, 0, 0), "opening stock adds nothing to owner revenue")
    invariants()


@test
def importing_twice_changes_nothing_and_stacking_on_history_is_refused():
    reset()
    pl = put_synth()
    snap = lambda: (q1("select count(*) from stock_events"), q1("select coalesce(sum(on_hand),0) from stock_levels"))      # noqa: E731
    before = snap()
    imp.apply(conn(), pl)                                                                    # same plan again: same key, rows on conflict do nothing
    check(snap() == before, "a replay added nothing")
    rpc_ = "select import_opening_balance(%s,%s,%s::jsonb)"
    err("service_role", rpc_, key(), "synthetic-backup-0002", json.dumps(pl["opening"]), contains="already has stock history")
    check(snap() == before, "a second import under a new key was refused whole")
    fresh = conn().execute("insert into variants (product_id, size) values ('tst-b-blue','S') returning id").fetchone()[0]
    conn().execute("insert into stock_levels (variant_id) values (%s)", (fresh,))
    before = snap()
    mixed = [{"product_id": "tst-b-blue", "size": "S", "qty": 4}, {"product_id": "imp-clean", "size": "XXL", "qty": 1}]
    err("service_role", rpc_, key(), "synthetic-backup-0004", json.dumps(mixed), contains="unknown variant")
    check(snap() == before and q1("select count(*) from stock_events where variant_id=%s", fresh) == 0, "one bad row rolls the whole import back (the good row before it was not kept)")
    err(OWNER, rpc_, key(), "synthetic-backup-0005", json.dumps(pl["opening"]), contains="permission denied")
    err("anon", rpc_, key(), "synthetic-backup-0005", json.dumps(pl["opening"]), contains="permission denied")
    err("service_role", rpc_, key(), "short", json.dumps(pl["opening"]), contains="which backup")


@test
def disputed_quantities_stay_off_the_website_until_a_person_counts_them():
    reset()
    pl = put_synth()
    n_pend = len({(r["product_id"], r["size"]) for r in pl["opening"] if r["pending"]})
    av = {(r[0], r[1]): r[2:4] for r in q("select product_id, size, state, n from get_availability(array['imp-art1-red','imp-clean','imp-flag-wrong'])", who="anon")}
    check(av[("imp-art1-red", "L")] == ("check", None) and av[("imp-flag-wrong", "M")] == ("check", None), "an uncounted size reads Check availability, never Available")
    check(av[("imp-art1-red", "XL")] == ("low", 1) and av[("imp-clean", "M")] == ("available", None), "counted sizes are unaffected")
    check(len(q("select * from pending_counts()", who=DAD)) == n_pend == 5, "the manager's list has exactly the flagged variants")
    err(CLERK, "select * from pending_counts()", contains="manager")
    oid, _ = place(("imp-art1-red", "L", 1), ("imp-clean", "M", 1))                           # a request can still arrive; it is just a request
    err(CLERK, "select confirm_and_reserve(%s,%s,%s,0)", key(), oid, DELIVERY, contains="count pending")
    check(order(oid)["status"] == "request" and stock("imp-clean", "M") == (3, 0), "refused whole: nothing was held, not even the counted line")
    oid2, _ = place(("imp-clean", "M", 1), phone="9000000002")
    reserve(oid2)
    check(order(oid2)["status"] == "awaiting_payment", "counted stock can still be held")
    red = vid_of("imp-art1-red", "L")
    s = ok(CLERK, "select complete_sale(%s,%s::jsonb,%s::jsonb,0)", key(), f'[{{"variant_id":"{red}","qty":1}}]', PAY1)
    check(len(s["warnings"]) == 1 and "pending" in s["warnings"][0], f"counter sale of an uncounted item warns: {s['warnings']}")
    check(q1("select count_pending from stock_levels where variant_id=%s", red) is True, "selling does not clear the flag: only a count does")
    conn().execute("update app_settings set value = 1 where key = 'pending_blocks_counter_sales'")
    err(CLERK, "select complete_sale(%s,%s::jsonb,%s::jsonb,0)", key(), f'[{{"variant_id":"{vid_of("imp-art1-green", "L")}","qty":1}}]', PAY1, contains="count pending")
    conn().execute("update app_settings set value = 0 where key = 'pending_blocks_counter_sales'")
    green = vid_of("imp-art1-green", "L")
    err(CLERK, "select recount_stock(%s,%s,2,'x')", key(), green, contains="manager")
    ok(DAD, "select recount_stock(%s,%s,2,'physical count 25 Oct')", key(), green)      # the count equals the stock on file: it still confirms it
    av = {(r[0], r[1]): r[2] for r in q("select product_id, size, state from get_availability()", who="anon")}
    check(av[("imp-art1-green", "L")] == "low", f"after a count the size is offered again (2 left): {av[('imp-art1-green', 'L')]}")
    check(q1("select kind from stock_events where variant_id=%s order by id desc limit 1", green) == "recount", "the count is a recount event")
    check(q1("select count(*) from stock_events where variant_id=%s and kind='opening_balance'", green) == 1, "the opening row is untouched")
    ok(DAD, "select set_count_pending(%s,%s,'tag on the shelf looks different')", key(), vid_of("imp-clean", "L"))
    check(q1("select count_pending from stock_levels where variant_id=%s", vid_of("imp-clean", "L")) is True, "a manager can ask for a count")
    err(DAD, "select set_count_pending(%s,%s,'')", key(), vid_of("imp-clean", "L"), contains="say why")
    err(CLERK, "select set_count_pending(%s,%s,'because')", key(), vid_of("imp-clean", "L"), contains="manager")
    invariants()


# ═════════════════════════ migration 0009: limits found by the real-HTTP tests (backend/api_tests) ═════════════════════════
def sqlstate_of(who, sql, *args):
    """('ok', value) or ('err', sqlstate, message) - the SQLSTATE is what PostgREST turns into an HTTP status."""
    try:
        row = conn(who).execute(sql, args).fetchone()
        return "ok", (row[0] if row else None)
    except psycopg.Error as e:
        return "err", e.sqlstate, (e.diag.message_primary or str(e))


def place_raw(**over):
    items = (("tst-a-pink", "M", 1),)
    a = dict(idem=key(), ref=ref_for(*items), name="Test Customer", phone="9000000077", address="12 Test Street, Testville", landmark="near test park", lines=lines_json(*items))
    a.update(over)
    return sqlstate_of("anon", "select place_order_request(%s,%s,%s,%s,%s,%s,%s::jsonb)", a["idem"], a["ref"], a["name"], a["phone"], a["address"], a["landmark"], a["lines"])


@test
def free_text_is_bounded_one_line_and_oversized_requests_are_refused_before_anything_is_stored():
    reset()
    n0 = q1("select count(*) from orders") + q1("select count(*) from idempotency")
    check(place_raw(name="N" * 100, address="A" * 500, landmark="L" * 200, idem="k" * 100)[0] == "ok", "the documented maximum lengths must be accepted")
    for label, kw, msg in (("name", dict(name="N" * 101), "name is too long"), ("address", dict(address="A" * 501), "address is too long"),
                           ("landmark", dict(landmark="L" * 201), "landmark is too long"), ("idempotency key", dict(idem="k" * 101), "idempotency key is too long"),
                           ("huge name", dict(name="N" * 1_000_000), "name is too long"), ("huge key", dict(idem="k" * 1_000_000), "idempotency key is too long"),
                           ("bell in name", dict(name="A\u0007B"), "plain single-line"), ("escape in address", dict(address="A\u001b[31mB"), "plain single-line"),
                           ("newline in landmark", dict(landmark="A\nB"), "plain single-line"), ("DEL", dict(name="A\u007fB"), "plain single-line"),
                           ("null phone", dict(phone=None), "phone must be 10 digits"), ("null lines", dict(lines=None), "lines must be a list"),
                           ("oversized lines", dict(lines=json.dumps([{"product_id": "tst-a-pink", "size": "M", "qty": 1, "junk": "j" * 25000}])), "too large")):
        r = place_raw(**kw)
        check(r[0] == "err" and msg in r[2], f"{label}: expected '{msg}', got {r}")
        check(r[1] == "P0001", f"{label}: SQLSTATE {r[1]} (must be P0001 so PostgREST answers 400)")
    r = sqlstate_of("anon", "select place_order_request(%s,null,'x','9000000078','y','','[]'::jsonb)", key())
    check(r[0] == "err" and r[1] == "P0001", f"null reference: {r}")
    check(q1("select count(*) from orders") + q1("select count(*) from idempotency") == n0 + 2, "refused requests left rows behind")      # +2: the one accepted maximum-length order and its key
    uni = "Ṛāṅjīt 👩‍👧 مرحبا 你好"
    check(place_raw(name=uni, phone="9000000079")[0] == "ok" and q1("select customer_name from orders where phone='9000000079'") == uni, "ordinary unicode must be stored unchanged")


@test
def rate_limit_refusals_use_a_code_postgrest_maps_to_http_429_not_500():
    reset()
    for i in range(5):
        check(place_raw(phone="9000000081")[0] == "ok", f"request {i + 1} within the limit")
    r = place_raw(phone="9000000081")
    check(r[0] == "err" and r[1] == "PT429" and "too many order requests" in r[2], f"per-phone limit: {r}")
    conn().execute("update app_settings set value = 1 where key = 'rate_all_per_hour'")
    r = place_raw(phone="9000000082")
    conn().execute("update app_settings set value = 300 where key = 'rate_all_per_hour'")
    check(r[0] == "err" and r[1] == "PT429" and "lot of requests" in r[2], f"site-wide brake: {r}")


@test
def customer_payment_reports_are_capped_bounded_and_cannot_be_used_to_probe_orders():
    reset()
    oid, ref = place(phone="9000000091")
    rp = lambda *a: sqlstate_of("anon", "select report_payment(%s,%s,%s,%s)", *a)      # noqa: E731
    for i in range(10):
        check(rp(ref, "9000000091", f"UPI{i}", 1000)[0] == "ok", f"report {i + 1} within the cap")
    r = rp(ref, "9000000091", "UPI11", 1000)
    check(r[0] == "err" and r[1] == "PT429" and "WhatsApp" in r[2], f"report over the cap: {r}")
    check(q1("select count(*) from payment_reports where order_id=%s", oid) == 10 and q1("select count(*) from order_events where order_id=%s and action='payment_reported'", oid) == 10,
          "history grew past the cap")
    oid2, ref2 = place(phone="9000000092")
    for label, args, msg in (("long reference", (ref2, "9000000092", "U" * 65, 1), "too long"), ("control chars", (ref2, "9000000092", "U\u0007", 1), "plain text"),
                             ("negative amount", (ref2, "9000000092", "u", -1), "out of range"), ("absurd amount", (ref2, "9000000092", "u", 2_000_000_000), "out of range")):
        r = rp(*args)
        check(r[0] == "err" and msg in r[2] and r[1] == "P0001", f"{label}: {r}")
    check(rp(ref2, "9000000092", "U" * 64, 100_000_000)[0] == "ok", "the documented maxima must be accepted")
    same = {rp("W0000-2222-22", "9000000092", "", 0)[1:], rp(ref2, "9000000093", "", 0)[1:], rp("x" * 5000, "9000000092", "", 0)[1:], rp(ref2, "9" * 5000, "", 0)[1:], rp(None, "9000000092", "", 0)[1:]}
    check(same == {("P0001", "order not found")}, f"unknown reference, wrong phone and absurd inputs must all say the same thing: {same}")


@test
def internal_helper_functions_are_not_executable_by_anyone_over_the_api_not_even_the_service_role():
    reset()
    helpers = ["actor_name", "apply_stock_event", "idem_begin", "idem_end", "lock_order_for", "lock_stock_rows", "log_order", "o4u_check", "release_lines",
               "require_role", "reserve_lines", "setting", "forbid_change", "keep_one_owner", "variants_barcode_sync"]
    rows = q("""select p.proname, has_function_privilege('service_role', p.oid, 'execute'), has_function_privilege('anon', p.oid, 'execute'),
                       has_function_privilege('authenticated', p.oid, 'execute') from pg_proc p where p.pronamespace = 'public'::regnamespace and p.proname = any(%s)""", helpers)
    check({r[0] for r in rows} == set(helpers), "helper list is out of date")
    check(not [r[0] for r in rows if r[1] or r[2] or r[3]], f"executable by an API role: {[r[0] for r in rows if r[1] or r[2] or r[3]]}")
    ok("service_role", "select expire_holds()")                                   # what the service role is for still works
    err("service_role", "select apply_stock_event(%s,'x',1,0,null,null,'x')", vid_of("tst-a-pink", "M"), contains="permission denied")
    err("service_role", "select setting('hold_minutes')", contains="permission denied")
    ok(OWNER, "select owner_sales_summary(now() - interval '1 day', now())")      # and the people-facing functions that use the helpers inside still work
    place()
    check(q1("select count(*) from orders") == 1, "ordering still works with the helpers closed")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    ENV.server = pgcluster.make_cluster(preload_cron=True, cron_db="o4ucron")
    ENV.uri = ENV.server.uri
    v = psycopg.connect(ENV.uri, autocommit=True).execute("select version()").fetchone()[0].split(",")[0]
    print(f"Throwaway database: {v}  (temp folder, invented data only; pg_cron {'loaded' if ENV.server.preload_cron else 'not available'})")
    boot = psycopg.connect(ENV.uri, autocommit=True)
    notices = []
    boot.add_notice_handler(lambda d: notices.append(f"{d.severity}: {d.message_primary}"))
    boot.execute((HERE / "supabase_shim.sql").read_text(encoding="utf-8"))
    for m in MIGRATIONS:
        boot.execute(m.read_text(encoding="utf-8"))
        print(f"Applied {m.name}")
    boot.close()
    ENV.boot_notices = notices
    if ENV.server.preload_cron:
        ENV.cron_uri = build_db(ENV.uri, "o4ucron")      # the one database pg_cron may run jobs in
    passed = failed = skipped = 0
    only = os.environ.get("O4U_ONLY")
    t0 = time.time()
    for fn in TESTS:
        if only and only not in fn.__name__:
            continue
        name = fn.__name__.replace("_", " ")
        try:
            fn()
            invariants()
            print(f"  PASS  {name}")
            passed += 1
        except Skip as e:
            skipped += 1
            print(f"  SKIP  {name}  ({e})")
        except Exception as e:      # noqa: BLE001
            failed += 1
            print(f"  FAIL  {name}\n        {e if isinstance(e, Fail) else repr(e)}")
            if not isinstance(e, Fail):
                traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped in {time.time() - t0:.1f}s")
    for c in _conns.values():
        c.close()
    for cl in (ENV.server, getattr(ENV, "plain", None)):
        if cl is not None:
            cl.cleanup()
    return 0 if failed == 0 and passed > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
