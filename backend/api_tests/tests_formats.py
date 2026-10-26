"""D. Request / response formats, the error contract, idempotency over HTTP."""
from __future__ import annotations

import json
import uuid

from ctx import DELIVERY, FUNCS, ZERO, Ctx
from lib import Fail, Skip, parallel, test


def lines(*items):
    return [{"product_id": p, "size": s, "qty": n} for p, s, n in items]


# ───────────────────────── D1-D4 formats ─────────────────────────
@test("D1", "D formats", "get_availability: POST JSON body and GET query string (array parameter) give the same answer")
def d1(X: Ctx):
    if X.local:
        X.reset()
    a = X.rpc("get_availability", {}, "anon")
    b = X.rpc_get("get_availability", {}, "anon")
    X.need(a.status == b.status == 200, f"statuses {a.status}/{b.status}")
    ids = sorted({r["product_id"] for r in a.json})[:2]
    if len(ids) < 1:
        raise Skip("no published products to ask about")
    pa = X.rpc("get_availability", {"p_product_ids": ids}, "anon")
    pb = X.rpc_get("get_availability", {"p_product_ids": ids}, "anon")
    strip = lambda rows: [{k: v for k, v in x.items() if k != "as_of"} for x in rows]      # noqa: E731 - as_of is now() and differs per call
    X.need(pa.status == pb.status == 200 and strip(pa.json) == strip(pb.json), f"POST {pa.status} vs GET {pb.status}: {pb.text[:150]}")
    X.need({r["product_id"] for r in pa.json} <= set(ids), "asking for 2 products returned others")
    X.need(X.rpc("get_availability", {"p_product_ids": ["no-such-product"]}, "anon").json == [], "unknown id should give an empty list")
    X.need(X.rpc("get_availability", {"p_product_ids": []}, "anon").json == [], "empty array should give an empty list")
    X.need(strip(X.rpc("get_availability", {"p_product_ids": None}, "anon").json) == strip(a.json), "null should mean everything")
    X.note("availability_row", a.json[0] if a.json else None)
    X.note("get_array_forms", {"{a,b}": pb.status, "quoted": X.rpc("get_availability", role="anon", method="GET", query='p_product_ids={"%s"}' % ids[0]).status})


@test("D2", "D formats", "jsonb parameters: real nested JSON works; a JSON string or null in its place gets our own error, never a 5xx")
def d2(X: Ctx):
    if X.local:
        X.reset()
        items = (("tst-a-pink", "M", 1), ("tst-b-blue", "M", 2))
        body = dict(p_idem_key=X.key(), p_ref=X.ref_for(*items), p_name="Test Customer", p_phone=X.phone(), p_address="12 Test Street", p_landmark="", p_lines=lines(*items))
        r = X.rpc("place_order_request", body, "anon")
        X.need(r.status == 200 and r.json["status"] == "request" and r.json["items_total_paise"] == 99900 + 2 * 149900, f"nested JSON: {r.err() if r.status >= 400 else r.json}")
        X.note("place_order_request_success_body", r.json)
        X.need(r.headers["content-type"].startswith("application/json"), "content-type")
    base = FUNCS["place_order_request"][1]
    for label, val in (("json string", json.dumps(lines(("a", "M", 1)))), ("null", None), ("object", {"product_id": "x"}), ("number", 7), ("nested array", [[1]]), ("empty array", [])):
        r = X.rpc("place_order_request", dict(base, p_idem_key=X.key(), p_name="x", p_address="y", p_phone="9000000000", p_lines=val), "anon")
        X.need(400 <= r.status < 500, f"p_lines as {label}: {r.status} {r.text[:150]}")
        X.note(f"p_lines_{label}", [r.status, r.code, r.message])


@test("D3", "D formats", "Missing, extra and wrongly typed parameters: PostgREST's own errors, all 4xx, nothing written")
def d3(X: Ctx):
    base = FUNCS["report_payment"][1]
    out = {}
    cases = {
        "missing parameter": {k: v for k, v in base.items() if k != "p_phone"},
        "extra parameter": dict(base, p_surprise=1),
        "wrong name": {"phone": "1", "ref": "x"},
        "no body at all": None,
        "claimed_paise as text": dict(base, p_claimed_paise="abc"),
        "claimed_paise as float": dict(base, p_claimed_paise=1.5),
        "claimed_paise too large": dict(base, p_claimed_paise=99999999999),
        "claimed_paise null": dict(base, p_claimed_paise=None),
        "phone as number": dict(base, p_phone=9000000000),
        "ref as list": dict(base, p_ref=["x"]),
        "ref null": dict(base, p_ref=None),
    }
    for label, body in cases.items():
        r = X.rpc("report_payment", body, "anon", raw=("" if body is None else None))
        out[label] = [r.status, r.code, r.message]
        X.need(400 <= r.status < 500, f"{label}: {r.status} {r.text[:150]}")
    X.note("param_mismatch_outcomes", out)
    r = X.rpc("report_payment", role="anon", raw="{not json")
    X.need(r.status == 400, f"invalid JSON: {r.status}")
    X.note("invalid_json", r.err())
    r = X.rpc("report_payment", role="anon", raw=json.dumps(base), headers={"Content-Type": "text/plain"})
    X.note("wrong_content_type", [r.status, r.code, r.message])
    X.need(r.status < 500, "wrong content type gave a server error")
    r = X.rpc("report_payment", role="anon", raw="[" + json.dumps(base) + "]")
    X.note("body_is_array", [r.status, r.code, r.message])
    X.need(r.status < 500, "an array body gave a server error")


@test("D4", "D formats", "Prefer / Accept / Range headers and scalar results: behaviour recorded, never a server error")
def d4(X: Ctx):
    if X.local:
        X.reset()
    out = {}
    probes = {
        "Prefer params=single-object": ("report_payment", FUNCS["report_payment"][1], {"Prefer": "params=single-object"}),
        "Prefer return=minimal": ("get_availability", {}, {"Prefer": "return=minimal"}),
        "Prefer return=representation": ("get_availability", {}, {"Prefer": "return=representation"}),
        "Prefer count=exact": ("get_availability", {}, {"Prefer": "count=exact"}),
        "Prefer tx=rollback": ("get_availability", {}, {"Prefer": "tx=rollback"}),
        "Prefer handling=strict": ("get_availability", {}, {"Prefer": "handling=strict, return=minimal"}),
        "Prefer missing=default": ("get_availability", {}, {"Prefer": "missing=default"}),
        "Accept text/csv": ("get_availability", {}, {"Accept": "text/csv"}),
        "Accept single object": ("get_availability", {}, {"Accept": "application/vnd.pgrst.object+json"}),
        "Accept text/plain": ("get_availability", {}, {"Accept": "text/plain"}),
        "Accept octet-stream": ("get_availability", {}, {"Accept": "application/octet-stream"}),
        "Accept geo+json": ("get_availability", {}, {"Accept": "application/geo+json"}),
        "Accept */*": ("get_availability", {}, {"Accept": "*/*"}),
        "Range 0-0": ("get_availability", {}, {"Range": "0-0", "Range-Unit": "items"}),
        "limit=1&offset=1 on an rpc": None,
        "Accept-Encoding gzip": ("get_availability", {}, {"Accept-Encoding": "gzip"}),
    }
    for label, p in probes.items():
        if p is None:
            r = X.rpc("get_availability", role="anon", method="POST", query="limit=1&offset=1", args={})
        else:
            name, args, h = p
            r = X.rpc(name, args, "anon", headers=h)
        out[label] = [r.status, r.code, r.headers.get("content-type"), len(r.body)]
        X.need(r.status < 500, f"{label}: server error {r.status} {r.text[:150]}")
    X.note("prefer_accept_outcomes", out)
    if "owner" in X.tokens:
        r = X.rpc("current_role_rank", {}, "owner")
        X.need(r.status == 200 and r.text.strip() == "3", f"scalar int body: {r.status} {r.text!r}")
        X.note("scalar_int_body", r.text.strip())
        r = X.rpc("current_role_rank", {}, "stranger") if "stranger" in X.tokens else None
        if r is not None:
            X.need(r.status == 200 and r.text.strip() == "null", f"scalar null body: {r.status} {r.text!r}")
            X.note("scalar_null_body", r.text.strip())
        r = X.rpc("stock_trust_status", {}, "staff")
        X.note("scalar_jsonb_body", r.text[:200])
        X.need(r.status == 200 and isinstance(r.json, dict), f"jsonb object body: {r.status} {r.text[:100]}")
        r = X.rpc("current_role_rank", {}, "owner", headers={"Accept": "application/vnd.pgrst.object+json"})
        X.note("scalar_with_object_accept", [r.status, r.text.strip()[:80]])


# ───────────────────────── D5 the error contract ─────────────────────────
@test("D5", "D formats", "ERROR CONTRACT: every business error the website / Stockroom can receive, with the exact status, code, message, details, hint", where=("local",))
def d5(X: Ctx):
    X.reset()
    bad = []

    def case(cid, desc, r, site, status=None, code=None, msg=None, group="rpc"):
        e = X.record(cid, r, desc=desc, site=site, group=group)
        if status is not None and r.status != status:
            bad.append(f"{cid}: status {r.status} != {status}")
        if code is not None and r.code != code:
            bad.append(f"{cid}: code {r.code} != {code}")
        if msg is not None and msg.lower() not in (r.message or "").lower():
            bad.append(f"{cid}: message {r.message!r} lacks {msg!r}")

    ok_items = (("tst-a-pink", "M", 1),)
    base = lambda **o: dict(dict(p_idem_key=X.key(), p_ref=X.ref_for(*ok_items), p_name="Test Customer", p_phone=X.phone(), p_address="12 Test Street",   # noqa: E731
                                 p_landmark="", p_lines=lines(*ok_items)), **o)
    P = lambda b: X.rpc("place_order_request", b, "anon")      # noqa: E731
    W = "Show the message under the form and keep the bag."
    case("PO-ok", "Order request accepted", P(base()), "Clear the bag, show the reference.", 200)
    case("PO-name", "Name or address blank", P(base(p_name="  ")), W, 400, "P0001", "name and address are required")
    case("PO-phone", "Phone is not exactly 10 digits", P(base(p_phone="12345")), W, 400, "P0001", "phone must be 10 digits")
    case("PO-lines-type", "Lines is not a list", P(base(p_lines={"a": 1})), "Programming error in the page; do not show to the customer.", 400, "P0001", "lines must be a list")
    case("PO-lines-0", "No lines", P(base(p_lines=[])), "The bag is empty.", 400, "P0001", "between 1 and 40 lines")
    many = tuple(("tst-a-pink", "M", 1) for _ in range(41))
    case("PO-lines-41", "41 lines", P(base(p_lines=lines(*many))), "Too many different items in one order request.", 400, "P0001", "between 1 and 40 lines")
    case("PO-ref-format", "Order reference is not W<DDMM>-XXXX-XX", P(base(p_ref="W1510-ABCD")), "Programming error; regenerate the reference and retry once.", 400, "P0001", "bad order reference")
    case("PO-ref-check", "Check digits do not match the items sent (or lines in another order)", P(base(p_ref="W1510-2222-22")), "Regenerate the reference from the bag and retry once.", 400, "P0001", "check digits")
    case("PO-qty-0", "Quantity 0", P(base(p_lines=lines(("tst-a-pink", "M", 0)), p_ref=X.ref_for(("tst-a-pink", "M", 0)))), W, 400, "P0001", "quantity must be 1 to 99")
    case("PO-qty-100", "Quantity 100", P(base(p_lines=lines(("tst-a-pink", "M", 100)), p_ref=X.ref_for(("tst-a-pink", "M", 100)))), W, 400, "P0001", "quantity must be 1 to 99")
    nf = (("no-such-product", "M", 1),)
    case("PO-unknown", "Product or size not on the website (or unpublished)", P(base(p_lines=lines(*nf), p_ref=X.ref_for(*nf))), "Remove the item from the bag and say it is no longer listed.", 400, "P0001", "item not available on the website")
    hid = (("tst-hidden", "M", 1),)
    case("PO-unpublished", "Unpublished product", P(base(p_lines=lines(*hid), p_ref=X.ref_for(*hid))), "Same as PO-unknown (does not reveal that it exists).", 400, "P0001", "item not available on the website")
    dup = (("tst-a-pink", "M", 1), ("tst-a-pink", "M", 2))
    case("PO-dup-line", "The same product+size twice in one request", P(base(p_lines=lines(*dup), p_ref=X.ref_for(*dup))), "Merge the lines in the bag before sending (the bag already does).", 409, "23505", None)
    case("PO-key-short", "Idempotency key shorter than 8 characters", P(base(p_idem_key="short")), "Programming error; generate a longer key.", 400, "P0001", "idempotency key required")
    first = base()
    case("PO-first", "(setup) first request of a pair", P(first), "-", 200)
    again = dict(first, p_idem_key=X.key(), p_phone=X.phone())
    case("PO-ref-used", "Same order reference, new idempotency key (a different tap of Send)", P(again), "Regenerate the reference and retry once.", 400, "P0001", "order reference already used")
    # same key, different action
    k = X.key()
    X.rpc("confirm_and_reserve", {"p_idem_key": k, "p_order": ZERO, "p_delivery_paise": 1, "p_discount_paise": 0}, "staff")        # fails: rolled back, key not stored
    oid, _ = X.place_ok()
    X.reserve(oid)         # stores a key we do not know; use a known one instead:
    k2 = X.key()
    r = X.rpc("pack_order", {"p_idem_key": k2, "p_order": oid}, "staff")      # status is awaiting_payment: refused, rolled back
    ph = X.phone()
    items = (("tst-b-blue", "M", 1),)
    rr = X.rpc("receive_stock", {"p_idem_key": k2, "p_variant": X.vid("tst-b-blue", "M"), "p_qty": 1, "p_reason": "contract test"}, "staff")
    case("PO-key-other-action", "Idempotency key already used for a different action", P(base(p_idem_key=k2, p_lines=lines(*items), p_ref=X.ref_for(*items))), "Programming error: one key per user action.", 400, "P0001", "different action")
    # rate limits
    ph = "9111111111"
    for i in range(5):
        r = P(base(p_phone=ph, p_ref=X.ref_for(*ok_items), p_idem_key=X.key()))
        if r.status != 200:
            raise Fail(f"rate-limit setup request {i} failed: {r.err()}")
    case("PO-rate-hour", "6th request in an hour from one phone", P(base(p_phone=ph)), "Tell the customer to wait or message the shop on WhatsApp. Do NOT retry automatically.", 429, "PT429", "too many order requests")
    X.db.execute("update orders set created_at = now() - interval '2 hours' where phone = %s", (ph,))
    for i in range(10):
        X.db.execute("insert into orders (ref, source, customer_name, phone, address, items_paise, created_at) values (%s,'website','x',%s,'y',1, now() - interval '3 hours')",
                     (f"W0101-{'ABCDEFGHJK'[i]}222-22", ph))
    case("PO-rate-day", "16th request in a day from one phone", P(base(p_phone=ph)), "Same as PO-rate-hour.", 429, "PT429", "too many order requests")
    X.db.execute("delete from order_events where order_id in (select id from orders where phone = %s)", ("9111111111",)) if False else None
    # PO-rate-global is produced by the abuse tests (F3) to keep this test fast
    # report_payment
    ordr = X.place_ok(phone="9222222222")
    case("RP-ok", "Customer says they paid", X.rpc("report_payment", {"p_ref": ordr[1], "p_phone": "9222222222", "p_claimed_ref": "UPI123", "p_claimed_paise": 99900}, "anon"), "Show 'we will check and confirm on WhatsApp'. Never show 'paid'.", 200)
    case("RP-unknown", "Unknown reference", X.rpc("report_payment", {"p_ref": "W0000-2222-22", "p_phone": "9222222222", "p_claimed_ref": "", "p_claimed_paise": 0}, "anon"), "'We could not find this order - check the reference or WhatsApp us.' Same text for a wrong phone.", 400, "P0001", "order not found")
    case("RP-wrong-phone", "Right reference, wrong phone (must equal RP-unknown)", X.rpc("report_payment", {"p_ref": ordr[1], "p_phone": "9222222223", "p_claimed_ref": "", "p_claimed_paise": 0}, "anon"), "Same as RP-unknown.", 400, "P0001", "order not found")
    case("RP-paise-text", "claimed_paise is not a number", X.rpc("report_payment", {"p_ref": ordr[1], "p_phone": "9222222222", "p_claimed_ref": "", "p_claimed_paise": "abc"}, "anon"), "Programming error.", 400, "22P02")
    case("RP-paise-big", "claimed_paise beyond int range", X.rpc("report_payment", {"p_ref": ordr[1], "p_phone": "9222222222", "p_claimed_ref": "", "p_claimed_paise": 99999999999}, "anon"), "Programming error.", 400, "22003")
    # availability
    case("GA-array", "product ids not an array", X.rpc("get_availability", {"p_product_ids": "abc"}, "anon"), "Programming error; fall back to 'Check availability'.", 400, "22P02", group="rpc")
    # staff
    S = lambda name, args, role="staff": X.rpc(name, dict(args, **({"p_idem_key": X.key()} if "p_idem_key" in args else {})), role)      # noqa: E731
    o2, _ = X.place_ok()
    case("ST-anon", "Anonymous caller (or expired session) reaches a staff function", X.rpc("confirm_and_reserve", {"p_idem_key": X.key(), "p_order": o2, "p_delivery_paise": 1, "p_discount_paise": 0}, "anon"), "Sign in again.", 401, "42501")
    case("ST-stranger", "Signed in but not on the staff list", X.rpc("confirm_and_reserve", {"p_idem_key": X.key(), "p_order": o2, "p_delivery_paise": 1, "p_discount_paise": 0}, "stranger"), "'This account is not shop staff.'", 403, "42501", "sign in as shop staff")
    case("ST-rank", "Staff calls a manager function", S("request_refund", {"p_idem_key": "x", "p_order": o2, "p_reason": "x"}), "'Needs manager access.'", 403, "42501", "needs manager access")
    case("ST-owner", "Manager calls the owner summary", X.rpc("owner_sales_summary", FUNCS["owner_sales_summary"][1], "manager"), "'Owner only.'", 403, "42501", "needs owner access")
    case("ST-notfound", "Order id does not exist", S("pack_order", {"p_idem_key": "x", "p_order": ZERO}), "Refresh the list.", 400, "P0001", "order not found")
    case("ST-no-delivery", "Confirm without a delivery charge", S("confirm_and_reserve", {"p_idem_key": "x", "p_order": o2, "p_delivery_paise": None, "p_discount_paise": 0}), "Ask staff to enter the charge.", 400, "P0001", "delivery charge")
    case("ST-discount", "Discount equal to or above the items total", S("confirm_and_reserve", {"p_idem_key": "x", "p_order": o2, "p_delivery_paise": 100, "p_discount_paise": 999999}, "manager"), "Fix the amount.", 400, "P0001", "discount must be below")
    case("ST-state", "Action not allowed from the current status", S("dispatch_order", {"p_idem_key": "x", "p_order": o2, "p_tracking": ""}), "Refresh; show the current status.", 400, "P0001", "cannot dispatch")
    case("ST-pay-state", "Verify payment on a request that was never reserved", S("verify_payment", {"p_idem_key": "x", "p_order": o2, "p_method": "upi", "p_amount_paise": 1, "p_upi_ref": "u1"}), "Refresh.", 400, "P0001", "cannot verify_payment")
    X.reserve(o2)
    case("ST-pay-amount", "Verified amount differs from the agreed bill", S("verify_payment", {"p_idem_key": "x", "p_order": o2, "p_method": "upi", "p_amount_paise": 1, "p_upi_ref": "u2"}), "Show the agreed amount.", 400, "P0001", "amount")
    X.pay(o2)
    o3, _ = X.place_ok()
    X.reserve(o3)
    dup_ref = X.sql1("select upi_ref from payments limit 1")
    agreed = X.order(o3)["agreed_paise"]
    case("ST-pay-dup-ref", "UPI reference already used on another order", S("verify_payment", {"p_idem_key": "x", "p_order": o3, "p_method": "upi", "p_amount_paise": agreed, "p_upi_ref": dup_ref}), "Check the reference.", 409, "23505")
    case("ST-cancel-paid", "Cancel a paid order", S("cancel_order", {"p_idem_key": "x", "p_order": o2, "p_reason": "x"}), "Use refund instead.", 400, "P0001")
    case("ST-short-stock", "Not enough free stock to hold", (lambda: (X.db.execute("update stock_levels set on_hand = reserved where variant_id=%s", (X.vid("tst-b-blue", "M"),)), S("confirm_and_reserve", {"p_idem_key": "x", "p_order": X.place_ok(("tst-b-blue", "M", 1))[0], "p_delivery_paise": 100, "p_discount_paise": 0}))[1])(), "Offer to contact the customer.", 400, "P0001", "not enough stock")
    case("ST-qty-neg", "Receive a negative quantity", S("receive_stock", {"p_idem_key": "x", "p_variant": X.vid("tst-a-pink", "M"), "p_qty": -3, "p_reason": "x"}), "Fix the number.", 400, "P0001", "quantity must be positive")
    case("ST-uuid", "Order id is not a UUID", X.rpc("pack_order", {"p_idem_key": X.key(), "p_order": "not-a-uuid"}, "staff"), "Programming error.", 400, "22P02")
    case("ST-barcode", "Unknown barcode in a counter sale", S("complete_sale", {"p_idem_key": "x", "p_lines": [{"barcode": "NOPE", "qty": 1}], "p_payments": [{"method": "cash", "amount_paise": 1}]}), "'Barcode not found.'", 400, "P0001", "unknown barcode")
    case("ST-sale-pay", "Counter sale payments do not equal the bill", S("complete_sale", {"p_idem_key": "x", "p_lines": [{"product_id": "tst-b-blue", "size": "M", "qty": 1}], "p_payments": [{"method": "cash", "amount_paise": 1}]}), "Show the bill amount.", 400, "P0001")
    # PostgREST's own errors
    case("PG-fn-missing", "Function or parameter names do not match (also: function hidden from this role)", X.rpc("get_availability", {"wrong": 1}, "anon"), "Programming error.", 404, "PGRST202", group="postgrest")
    case("PG-json", "Request body is not valid JSON", X.rpc("get_availability", role="anon", raw="{oops"), "Programming error.", 400, "PGRST102", group="postgrest")
    case("PG-denied-anon", "Function refused to anon", X.rpc("pack_order", {"p_idem_key": X.key(), "p_order": ZERO}, "anon"), "Sign in.", 401, "42501", group="postgrest")
    case("PG-denied-user", "Table refused to a signed-in user", X.tbl("DELETE", "orders", "staff", query="id=is.null"), "Never done by the apps.", 403, "42501", group="postgrest")
    case("PG-no-table", "Table that does not exist", X.tbl("GET", "no_such_table", "staff"), "Programming error.", 404, "42P01", group="postgrest")
    case("PG-method", "GET on a function that writes", X.rpc_get("place_order_request", FUNCS["place_order_request"][1], "anon"), "Programming error: use POST.", 405, "25006", group="postgrest")
    case("PG-accept", "Unsupported Accept header", X.rpc("get_availability", {}, "anon", headers={"Accept": "application/octet-stream"}), "Programming error.", 406, None, group="postgrest")
    case("PG-schema", "Schema not exposed", X.rpc("get_availability", {}, "anon", headers={"Content-Profile": "auth"}), "Programming error.", 406, "PGRST106", group="postgrest")
    case("PG-single", "Accept single object but several rows", X.rpc("get_availability", {}, "anon", headers={"Accept": "application/vnd.pgrst.object+json"}), "Programming error.", 406, "PGRST116", group="postgrest")
    from lib import mint, user_claims
    import time
    case("PG-jwt-expired", "Token expired (more than 30 s ago)", X.rpc("current_role_rank", {}, token=mint(X.secret, user_claims("00000000-0000-0000-0000-000000000001", exp=int(time.time()) - 600))), "Refresh the session or fall back to the anon key; a 401 here also breaks PUBLIC calls.", 401, "PGRST301", group="postgrest")
    case("PG-jwt-bad", "Token malformed", X.rpc("get_availability", {}, token="abc.def.ghi"), "Same as PG-jwt-expired.", 401, "PGRST301", group="postgrest")
    case("PG-jwt-public", "Expired token on a PUBLIC call", X.rpc("get_availability", {}, token=mint(X.secret, user_claims("00000000-0000-0000-0000-000000000001", exp=int(time.time()) - 600))), "A stale staff token in the browser breaks the shop page - send the anon key for public calls.", 401, "PGRST301", group="postgrest")
    # a statement that is cut off by the role's statement_timeout
    X.db.execute("alter role anon set statement_timeout = '1ms'")
    X.stack.reload_schema()         # PostgREST reads per-role settings when it loads its schema cache
    try:
        r = X.rpc("get_availability", {}, "anon")
        case("PG-timeout", "Statement timeout (anon limit 3 s on hosted projects; forced to 1 ms here)", r, "Show 'try again in a moment'; fall back to 'Check availability'.", 500, "57014", group="postgrest")
    finally:
        X.db.execute("alter role anon set statement_timeout = '3s'")
        X.stack.reload_schema()
    X.need(not bad, "unexpected: " + "; ".join(bad))
    X.note("cases_recorded", len(X.contract))


# ───────────────────────── D6 idempotency over HTTP ─────────────────────────
@test("D6", "D formats", "Idempotency over HTTP: the same key twice returns the stored answer; ten at once make one order", where=("local",))
def d6(X: Ctx):
    X.reset()
    items = (("tst-a-pink", "M", 1),)
    ref, key, phone = X.ref_for(*items), X.key(), X.phone()
    body = dict(p_idem_key=key, p_ref=ref, p_name="Test Customer", p_phone=phone, p_address="12 Test Street", p_landmark="", p_lines=lines(*items))
    a = X.rpc("place_order_request", body, "anon")
    b = X.rpc("place_order_request", body, "anon")
    X.need(a.status == b.status == 200 and a.json == b.json, f"replay differs: {a.text} vs {b.text}")
    X.need(X.sql1("select count(*) from orders") == 1, "replay created a second order")
    c = X.rpc("place_order_request", dict(body, p_name="Somebody Else", p_address="elsewhere"), "anon")
    X.need(c.status == 200 and c.json == a.json, "same key with different content must return the FIRST stored result")
    X.note("same_key_different_content", "returns the first answer unchanged (the second content is ignored)")
    # five replays through different keepalive connections, and the rate limit is not consumed by replays
    for _ in range(8):
        X.need(X.rpc("place_order_request", body, "anon").json == a.json, "replay changed")
    X.need(X.sql1("select count(*) from orders") == 1, "replays created orders")
    # ten at once with a fresh key
    items2 = (("tst-b-blue", "M", 1),)
    body2 = dict(body, p_idem_key=X.key(), p_ref=X.ref_for(*items2), p_phone=X.phone(), p_lines=lines(*items2))
    res = parallel([lambda: X.rpc("place_order_request", body2, "anon") for _ in range(10)])
    good = [r for r in res if not isinstance(r, Exception) and r.status == 200]
    other = [r for r in res if isinstance(r, Exception) or r.status != 200]
    X.need(X.sql1("select count(*) from orders where phone=%s", body2["p_phone"]) == 1, "ten simultaneous identical requests made more than one order")
    X.need(len({json.dumps(r.json, sort_keys=True) for r in good}) == 1 and len(good) >= 1, "successful answers differ")
    X.note("ten_at_once", {"200": len(good), "others": sorted({(r.status, r.code, r.message) if not isinstance(r, Exception) else str(r) for r in other})})
    # staff action replay: pay twice with one key
    oid = a.json["order_id"]
    X.reserve(oid)
    amt = X.order(oid)["agreed_paise"]
    pk = X.key()
    pay = {"p_idem_key": pk, "p_order": oid, "p_method": "upi", "p_amount_paise": amt, "p_upi_ref": "UPIREPLAY01"}
    r1, r2 = X.rpc("verify_payment", pay, "staff"), X.rpc("verify_payment", pay, "staff")
    X.need(r1.status == r2.status == 200 and r1.json == r2.json, f"verify replay: {r1.err() if r1.status>=400 else ''} {r2.err() if r2.status>=400 else ''}")
    X.need(X.sql1("select count(*) from payments where order_id=%s", oid) == 1, "a replayed verify_payment wrote a second payment")
    res = parallel([lambda: X.rpc("dispatch_order", {"p_idem_key": X.key(), "p_order": oid, "p_tracking": "T1"}, "staff") for _ in range(6)])
    wins = [r for r in res if not isinstance(r, Exception) and r.status == 200]
    X.need(len(wins) >= 1, "no dispatch succeeded")
    X.need(X.stock("tst-a-pink", "M") == (4, 0), f"dispatch deducted more than once: {X.stock('tst-a-pink', 'M')}")
    X.invariants()
