"""F. Abuse and limits."""
from __future__ import annotations

import itertools
import json
import random
import statistics
import time

from ctx import ALPHA, FUNCS, Ctx
from lib import Fail, Skip, parallel, test


def lines(*items):
    return [{"product_id": p, "size": s, "qty": n} for p, s, n in items]


def fill_orders(X: Ctx, n: int, phone_fn, age="0 seconds"):
    combos = itertools.islice(itertools.product("ABCDEFGH", "JKMNPQRS", "TUVWXYZ2", "3456789A"), n)
    for i, (a, b, c, d) in enumerate(combos):
        X.db.execute("insert into orders (ref, source, customer_name, phone, address, items_paise, created_at) values (%s,'website','x',%s,'y',1, now() - %s::interval)",
                     (f"W0101-{a}{b}{c}{d}-22", phone_fn(i), age))


def order_body(X: Ctx, phone=None, **over):
    items = over.pop("items", (("tst-a-pink", "M", 1),))
    b = dict(p_idem_key=X.key(), p_ref=X.ref_for(*items), p_name="Test Customer", p_phone=phone or X.phone(), p_address="12 Test Street, Testville", p_landmark="near park",
             p_lines=lines(*items))
    b.update(over)
    return b


def P(X, body, **kw):
    return X.rpc("place_order_request", body, "anon", **kw)


# ───────────────────────── F1-F3 rate limits ─────────────────────────
@test("F1", "F abuse & limits", "Per-phone hourly limit (5): what a real client sees at the limit - it must be a 429, not a server error", where=("local",))
def f1(X: Ctx):
    X.reset()
    ph = "9333333331"
    bodies = [order_body(X, ph) for _ in range(6)]
    got = [P(X, b) for b in bodies[:5]]
    X.need(all(r.status == 200 for r in got), f"first five should be accepted: {[r.status for r in got]}")
    r6 = P(X, bodies[5])
    X.note("sixth_request", r6.err())
    X.need(X.sql1("select count(*) from orders where phone=%s", ph) == 5, "the sixth request created an order")
    X.need(r6.status == 429, f"at the limit the client receives HTTP {r6.status} (code {r6.code}); a rate limit must be HTTP 429 so it is not retried or reported as a server fault")
    X.need("wait" in (r6.message or "") and "WhatsApp" in (r6.message or ""), f"limit message: {r6.message}")
    X.need(P(X, bodies[0]).json == got[0].json, "replaying an accepted request at the limit must return the stored answer")
    X.need(P(X, order_body(X)).status == 200, "another phone is affected by one phone's limit")
    X.need(X.sql1("select count(*) from orders where phone=%s", ph) == 5, "replay consumed the limit")


@test("F2", "F abuse & limits", "Per-phone daily limit (15) and the site-wide hourly brake (300): the answer and what still works while the brake is on", where=("local",))
def f2(X: Ctx):
    X.reset()
    ph = "9333333332"
    fill_orders(X, 15, lambda i: ph, age="3 hours")
    r = P(X, order_body(X, ph))
    X.note("daily_limit", r.err())
    X.need(r.status == 429 and "too many" in (r.message or ""), f"16th request in a day: {r.err()}")
    X.need(P(X, order_body(X)).status == 200, "other phones must still work at a per-phone limit")
    X.reset()
    fill_orders(X, 300, lambda i: f"90000{i:05d}")
    r = P(X, order_body(X))
    X.record("PO-rate-global", r, desc="More than 300 order requests in the last hour, from anyone", site="Show the message; do not retry automatically; offer WhatsApp.", group="rpc")
    X.note("global_brake", r.err())
    X.need(r.status == 429 and "lot of requests" in (r.message or ""), f"301st request in an hour: {r.err()}")
    X.need(X.rpc("get_availability", {}, "anon").status == 200, "availability must keep working while the order brake is on")
    X.need(X.rpc("report_payment", FUNCS["report_payment"][1], "anon").status == 400, "report_payment must still reach its logic")
    X.need(X.rpc("current_role_rank", {}, "staff").status == 200, "staff must keep working")
    X.db.execute("update orders set created_at = now() - interval '2 hours'")
    X.need(P(X, order_body(X)).status == 200, "the brake should lift once the hour has passed")


# ───────────────────────── F4-F6 report_payment ─────────────────────────
@test("F3", "F abuse & limits", "report_payment: unknown reference and wrong phone look identical (status, body, headers, timing)", where=("local",))
def f3(X: Ctx):
    X.reset()
    ph = "9444444441"
    oid, ref = X.place_ok(phone=ph)
    bodies = {"unknown ref": dict(p_ref="W0000-2222-22", p_phone=ph), "wrong phone": dict(p_ref=ref, p_phone="9444444442"),
              "wrong ref case": dict(p_ref=ref.lower(), p_phone=ph), "garbage ref": dict(p_ref="x" * 40, p_phone=ph), "garbage phone": dict(p_ref=ref, p_phone="phone")}
    seen, times = {}, {k: [] for k in bodies}
    for _ in range(30):
        for k, b in bodies.items():
            r = X.rpc("report_payment", dict(b, p_claimed_ref="", p_claimed_paise=0), "anon")
            seen.setdefault(k, set()).add(json.dumps(r.err(), sort_keys=True))
            times[k].append(r.elapsed * 1000)
    base = next(iter(seen["unknown ref"]))
    for k, v in seen.items():
        X.need(v == {base}, f"'{k}' is distinguishable from an unknown reference: {v} vs {base}")
    med = {k: round(statistics.median(v), 2) for k, v in times.items()}
    X.note("median_ms", med)
    spread = max(med.values()) - min(med.values())
    X.need(spread < 40, f"timing differs by {spread:.1f} ms between cases: {med}")
    X.need(X.sql1("select count(*) from payment_reports") == 0, "a failed lookup wrote a payment report")


@test("F4", "F abuse & limits", "Brute force: 600 random reference+phone guesses (some in parallel) - all refused alike, none succeed, no server error", where=("local",))
def f4(X: Ctx):
    X.reset()
    oid, ref = X.place_ok(phone="9444444443")
    rnd = random.Random(7)
    guess = lambda: dict(p_ref=f"W{rnd.randint(1, 3112):04d}-{''.join(rnd.choice(ALPHA) for _ in range(4))}-{''.join(rnd.choice(ALPHA) for _ in range(2))}",      # noqa: E731
                         p_phone=f"{rnd.randint(10**9, 10**10 - 1)}", p_claimed_ref="", p_claimed_paise=0)
    t0 = time.time()
    res = [X.rpc("report_payment", guess(), "anon") for _ in range(300)]
    res += parallel([(lambda g=guess(): X.rpc("report_payment", g, "anon")) for _ in range(300)])
    dt = time.time() - t0
    bad = [r for r in res if isinstance(r, Exception) or r.status != 400]
    X.need(not bad, f"{len(bad)} guesses were not refused with 400 (first: {bad[0].err() if bad and not isinstance(bad[0], Exception) else bad[:1]})")
    X.need(len({json.dumps(r.err(), sort_keys=True) for r in res}) == 1, "refusals differ between guesses")
    X.need(X.sql1("select count(*) from payment_reports") == 0, "a guess wrote a report")
    X.note("guesses", {"count": len(res), "seconds": round(dt, 1), "per_second": round(len(res) / dt), "throttled": False,
                       "meaning": "there is no per-caller throttle in the database; the defence is the size of the guess space (31^6 refs x 10^10 phones) plus an edge limit"})


@test("F5", "F abuse & limits", "report_payment is bounded: reports per order are capped, free text and amounts are limited, history cannot grow without end", where=("local",))
def f5(X: Ctx):
    X.reset()
    ph = "9444444444"
    oid, ref = X.place_ok(phone=ph)
    body = lambda **o: dict(dict(p_ref=ref, p_phone=ph, p_claimed_ref="UPI0001", p_claimed_paise=1000), **o)      # noqa: E731
    accepted = refused = 0
    last = None
    for i in range(60):
        r = X.rpc("report_payment", body(p_claimed_ref=f"UPI{i:04d}"), "anon")
        if r.status == 200:
            accepted += 1
        else:
            refused += 1
            last = r
    n_reports = X.sql1("select count(*) from payment_reports where order_id=%s", oid)
    n_events = X.sql1("select count(*) from order_events where order_id=%s and action='payment_reported'", oid)
    X.note("sixty_reports", {"accepted": accepted, "refused": refused, "payment_reports_rows": n_reports, "order_events_rows": n_events, "refusal": last.err() if last else None})
    X.need(n_reports <= 10 and n_events <= 10, f"60 reports on one order left {n_reports} payment_reports and {n_events} order_events rows (no cap)")
    X.need(last is not None and last.status == 429, f"over the cap the client should get 429, got {last.err() if last else 'no refusal'}")
    for label, kw in (("claimed_ref 1 MB", dict(p_claimed_ref="U" * 1_000_000)), ("claimed_ref 200 chars", dict(p_claimed_ref="U" * 200)),
                      ("negative amount", dict(p_claimed_paise=-5)), ("absurd amount", dict(p_claimed_paise=2_000_000_000)),
                      ("control chars in ref", dict(p_claimed_ref="UPI\u0007\u001b[31m"))):
        oid2, ref2 = X.place_ok(phone=X.phone())
        ph2 = X.sql1("select phone from orders where id=%s", oid2)
        r = X.rpc("report_payment", dict(p_ref=ref2, p_phone=ph2, p_claimed_ref="x", p_claimed_paise=1, **{}) | kw, "anon")
        X.need(400 <= r.status < 500 and r.status != 200, f"{label}: accepted ({r.status})")
    X.need(X.sql1("select max(length(claimed_ref)) from payment_reports") <= 64, "a very long claimed_ref was stored")


# ───────────────────────── F6 hostile input ─────────────────────────
@test("F6", "F abuse & limits", "Hostile and oversized inputs to place_order_request: bounded free text, no server errors, SQL-looking text stays data", where=("local",))
def f6(X: Ctx):
    X.reset()
    out, problems = {}, []

    def tryit(label, body=None, expect=None, raw=None, timeout=60):
        t0 = time.time()
        r = P(X, body, raw=raw, timeout=timeout) if raw is not None else P(X, body)
        out[label] = {"status": r.status, "code": r.code, "message": (r.message or "")[:90], "seconds": round(time.time() - t0, 2)}
        if r.status >= 500:
            problems.append(f"{label}: server error {r.status} {r.code}")
        if expect == "refuse" and r.status == 200:
            problems.append(f"{label}: accepted")
        if expect == "accept" and r.status != 200:
            problems.append(f"{label}: refused {r.err()}")
        return r

    tryit("name 100 chars", order_body(X, p_name="N" * 100), "accept")
    tryit("name 101 chars", order_body(X, p_name="N" * 101), "refuse")
    tryit("name 100 000 chars", order_body(X, p_name="N" * 100_000), "refuse")
    tryit("name 1 MB", order_body(X, p_name="N" * 1_000_000), "refuse")
    tryit("address 500 chars", order_body(X, p_address="A" * 500), "accept")
    tryit("address 501 chars", order_body(X, p_address="A" * 501), "refuse")
    tryit("address 1 MB", order_body(X, p_address="A" * 1_000_000), "refuse")
    tryit("landmark 200 chars", order_body(X, p_landmark="L" * 200), "accept")
    tryit("landmark 201 chars", order_body(X, p_landmark="L" * 201), "refuse")
    tryit("idempotency key 100 chars", order_body(X, p_idem_key="k" * 100), "accept")
    tryit("idempotency key 101 chars", order_body(X, p_idem_key="k" * 101), "refuse")
    tryit("idempotency key 1 MB", order_body(X, p_idem_key="k" * 1_000_000), "refuse")
    tryit("reference 10 000 chars", order_body(X, p_ref="W" * 10_000), "refuse")
    tryit("phone with letters", order_body(X, p_phone="90000abcde"), "refuse")
    tryit("phone with trailing newline", order_body(X, p_phone="9000000001\n"), "refuse")
    tryit("phone with Arabic-Indic digits", order_body(X, p_phone="٩٠٠٠٠٠٠٠٠١"), "refuse")
    tryit("phone null", order_body(X, p_phone=None), "refuse")
    tryit("name null", order_body(X, p_name=None), "refuse")
    tryit("address null", order_body(X, p_address=None), "refuse")
    tryit("landmark null", order_body(X, p_landmark=None))
    tryit("lines null", order_body(X, p_lines=None), "refuse")
    tryit("41 lines", order_body(X, items=tuple(("tst-a-pink", "M", 1) for _ in range(41))), "refuse")
    for q in (0, -1, 100, 2**31, 2**40, 1.5, "1e2", "abc", None, True):
        items = (("tst-a-pink", "M", q if isinstance(q, int) and not isinstance(q, bool) else 1),)
        b = order_body(X, items=items)
        b["p_lines"] = [{"product_id": "tst-a-pink", "size": "M", "qty": q}]
        tryit(f"qty {q!r}", b, "refuse")
    # text that must be stored as text
    sqlish = "Robert'); DROP TABLE orders;--"
    before = X.counts()["orders"]
    r = tryit("SQL-looking name", order_body(X, p_name=sqlish, p_address="1' OR '1'='1", p_landmark="\\'; select pg_sleep(5); --"), "accept")
    if r.status == 200:
        row = X.sql("select customer_name, address, landmark from orders where id=%s", r.json["order_id"])[0]
        if row != (sqlish, "1' OR '1'='1", "\\'; select pg_sleep(5); --"):
            problems.append(f"SQL-looking text was altered: {row}")
        if X.counts()["orders"] != before + 1:
            problems.append("SQL-looking text changed other rows")
    sq2 = (("x' OR '1'='1", "M", 1),)
    tryit("SQL-looking product id", order_body(X, items=sq2), "refuse")
    # unicode round-trip
    uni = "Ṛāṅjīt 👩‍👧‍👦 مرحبا שלום 你好 é"
    r = tryit("unicode name", order_body(X, p_name=uni), "accept")
    if r.status == 200:
        stored = X.sql1("select customer_name from orders where id=%s", r.json["order_id"])
        if stored != uni:
            problems.append(f"unicode changed: {stored!r}")
    tryit("NUL character", order_body(X, p_name="a\u0000b"), "refuse")
    for label, ch in (("bell", "\u0007"), ("escape sequence", "\u001b[31m"), ("newline in name", "\n"), ("tab", "\t"), ("DEL", "\u007f"), ("zero-width", "​"), ("RTL override", "‮")):
        tryit(f"control: {label} in name", order_body(X, p_name=f"A{ch}B"), "refuse" if label in ("bell", "escape sequence", "newline in name", "tab", "DEL") else None)
        tryit(f"control: {label} in address", order_body(X, p_address=f"A{ch}B"), "refuse" if label in ("bell", "escape sequence", "newline in name", "tab", "DEL") else None)
    # hostile JSON
    deep = "[" * 3000 + "]" * 3000
    b = order_body(X)
    raw = json.dumps(b).replace('"product_id": "tst-a-pink"', '"product_id": ' + deep, 1)
    tryit("JSON nested 3000 deep", raw=raw, expect="refuse")
    raw = json.dumps(order_body(X)).replace('"qty": 1', '"qty": 1e999')
    tryit("qty 1e999", raw=raw, expect="refuse")
    raw = json.dumps(order_body(X))[:-1] + ', "p_name": "second name"}'
    tryit("duplicate JSON key", raw=raw)
    big = order_body(X)
    big["p_lines"] = [{"product_id": "tst-a-pink", "size": "M", "qty": 1}] * 100_000
    tryit("100 000 lines (about 6 MB)", big, "refuse")
    big["p_lines"] = [{"product_id": "tst-a-pink", "size": "M", "qty": 1, "junk": "j" * 200}] * 40
    tryit("40 lines with 200-char junk fields", big)
    huge = order_body(X)
    huge["p_lines"] = [{"product_id": "tst-a-pink", "size": "M", "qty": 1, "junk": "x" * 20_000_000}]
    t = tryit("20 MB single field", huge, "refuse", timeout=90)
    X.note("hostile_input_outcomes", out)
    slow = {k: v["seconds"] for k, v in out.items() if v["seconds"] > 5}
    if slow:
        problems.append(f"slow requests: {slow}")
    X.need(not problems, "; ".join(problems[:8]) + (f" (+{len(problems) - 8} more)" if len(problems) > 8 else ""))
    X.need(X.sql1("select max(length(customer_name)) from orders") <= 100 and X.sql1("select max(length(address)) from orders") <= 500, "over-long text is stored")
    X.need(X.sql1("select max(length(landmark)) from orders") <= 200, "over-long landmark stored")
    X.need(X.sql1("select count(*) from orders where customer_name ~ '[\\x01-\\x08\\x0a-\\x1f\\x7f]' or address ~ '[\\x01-\\x08\\x0a-\\x1f\\x7f]' or landmark ~ '[\\x01-\\x08\\x0a-\\x1f\\x7f]'") == 0,
           "control characters are stored in customer text")
    X.invariants()


@test("F7", "F abuse & limits", "Oversized arrays to get_availability: answered or refused quickly, never a server error", where=("local",))
def f7(X: Ctx):
    X.reset()
    out = {}
    for n in (10, 1_000, 50_000, 300_000):
        ids = [f"tst-a-pink-{i}" for i in range(n)]
        t0 = time.time()
        r = X.rpc("get_availability", {"p_product_ids": ids}, "anon", timeout=60)
        out[n] = {"status": r.status, "code": r.code, "seconds": round(time.time() - t0, 2), "bytes_sent": len(json.dumps(ids))}
        X.need(r.status < 500, f"{n} ids: {r.status} {r.code} {r.message}")
        X.need(time.time() - t0 < 8, f"{n} ids took {time.time() - t0:.1f}s")
    X.note("array_size_outcomes", out)


@test("F8", "F abuse & limits", "Hostile input that is always refused is safe to send to the hosted project (nothing is written)", where=("local", "hosted"))
def f8(X: Ctx):
    n_before = X.counts() if X.local else None
    base = dict(p_idem_key="hostile-probe-0001", p_ref="W0000-2222-22", p_name="x", p_phone="1", p_address="y", p_landmark="", p_lines=lines(("no-such-product", "M", 1)))
    cases = {"phone too short + 2 MB name": dict(base, p_name="N" * 2_000_000), "41 lines": dict(base, p_phone="9000000000", p_lines=lines(*[("no-such-product", "M", 1)] * 41)),
             "unknown product": dict(base, p_phone="9000000000"), "NUL in name": dict(base, p_name="a\u0000b"),
             "bad reference": dict(base, p_phone="9000000000", p_ref="nope"), "SQL-looking name + short phone": dict(base, p_name="'; drop table orders; --")}
    out = {}
    for label, b in cases.items():
        r = X.rpc("place_order_request", b, "anon", timeout=60)
        out[label] = [r.status, r.code]
        X.need(400 <= r.status < 500, f"{label}: {r.status} {r.text[:120]}")
    X.note("always_refused_inputs", out)
    r = X.rpc("report_payment", dict(FUNCS["report_payment"][1], p_claimed_ref="U" * 100_000), "anon")
    X.need(400 <= r.status < 500, f"report_payment with a 100 KB reference: {r.status}")
    if X.local:
        X.need(X.counts() == n_before, "a refused request left rows behind")
