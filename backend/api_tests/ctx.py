"""Test context: how a test talks to the API (the same calls for the local stack and the hosted dev project) and, LOCAL only,
how it builds invented data and looks at the database behind the API."""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

from lib import Fail, Resp, Skip, register_secret, request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

OWNER, MANAGER, STAFF, STRANGER = (str(uuid.UUID(int=i)) for i in (1, 2, 3, 4))      # invented identities (local only)
ZERO = "00000000-0000-0000-0000-000000000000"
ROLES = ("owner", "manager", "staff", "stranger")
RANK = {"anon": -1, "stranger": 0, "staff": 1, "manager": 2, "owner": 3}
PRICE_A, PRICE_B, DELIVERY = 99900, 149900, 5000
ALPHA = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"

PKCOL = {"app_settings": "key", "expiry_failures": "order_id", "idempotency": "key", "order_events": "id", "order_lines": "order_id", "order_transitions": "from_status",
         "orders": "id", "payment_reports": "id", "payments": "id", "products": "id", "refunds": "id", "sale_lines": "sale_id", "sales": "id", "staff": "user_id",
         "stock_events": "id", "stock_levels": "variant_id", "store_outages": "id", "store_status": "id", "variant_barcodes": "barcode", "variants": "id"}
NOROWS = lambda t: f"{PKCOL[t]}=is.null"      # noqa: E731 - a primary-key column is never null, so this filter can never match a row

TABLES = ["app_settings", "expiry_failures", "idempotency", "order_events", "order_lines", "order_transitions", "orders", "payment_reports",
          "payments", "products", "refunds", "sale_lines", "sales", "staff", "stock_events", "stock_levels", "store_outages", "store_status",
          "variant_barcodes", "variants"]
ANON_FUNCS = {"get_availability", "place_order_request", "report_payment"}
# function -> (lowest role that may call it, a call that cannot change anything when it is refused AND cannot find its target when allowed)
Z, K = ZERO, "apitest-probe-0001"
FUNCS: dict[str, tuple[str, dict]] = {
    "get_availability": ("anon", {}),
    "place_order_request": ("anon", {"p_idem_key": K, "p_ref": "bad", "p_name": "", "p_phone": "1", "p_address": "", "p_landmark": "", "p_lines": []}),
    "report_payment": ("anon", {"p_ref": "W0000-AAAA-AA", "p_phone": "0000000000", "p_claimed_ref": "", "p_claimed_paise": 0}),
    "current_role_rank": ("stranger", {}),
    "confirm_and_reserve": ("staff", {"p_idem_key": K, "p_order": Z, "p_delivery_paise": 100, "p_discount_paise": 0}),
    "verify_payment": ("staff", {"p_idem_key": K, "p_order": Z, "p_method": "upi", "p_amount_paise": 1, "p_upi_ref": "x"}),
    "release_hold": ("staff", {"p_idem_key": K, "p_order": Z}),
    "cancel_order": ("staff", {"p_idem_key": K, "p_order": Z, "p_reason": "x"}),
    "pack_order": ("staff", {"p_idem_key": K, "p_order": Z}),
    "dispatch_order": ("staff", {"p_idem_key": K, "p_order": Z, "p_tracking": ""}),
    "mark_failed": ("staff", {"p_idem_key": K, "p_order": Z, "p_who": "x", "p_note": "n"}),
    "mark_delivered": ("staff", {"p_idem_key": K, "p_order": Z}),
    "receive_stock": ("staff", {"p_idem_key": K, "p_variant": Z, "p_qty": 1, "p_reason": "x"}),
    "complete_sale": ("staff", {"p_idem_key": K, "p_lines": [], "p_payments": [], "p_discount_paise": 0}),
    "get_receipt": ("staff", {"p_sale": Z}),
    "lookup_barcode": ("staff", {"p_barcode": "x"}),
    "stock_trust_status": ("staff", {}),
    "request_refund": ("manager", {"p_idem_key": K, "p_order": Z, "p_reason": "x"}),
    "mark_refund_sent": ("manager", {"p_idem_key": K, "p_refund": -1, "p_sent_ref": "x"}),
    "recount_stock": ("manager", {"p_idem_key": K, "p_variant": Z, "p_counted": 0, "p_reason": "x"}),
    "return_to_stock": ("manager", {"p_idem_key": K, "p_variant": Z, "p_qty": 1, "p_order": Z, "p_sale": Z, "p_reason": "x"}),
    "set_count_pending": ("manager", {"p_idem_key": K, "p_variant": Z, "p_reason": "x"}),
    "pending_counts": ("manager", {}),
    "overdue_holds": ("manager", {}),
    "owner_sales_summary": ("owner", {"p_from": "2000-01-01T00:00:00Z", "p_to": "2000-01-02T00:00:00Z"}),
}
# these change state even when they succeed, so the hosted profile never calls them; the local stack does
WRITING = {
    "store_ping": ("staff", {}),
    "set_offline_switch": ("manager", {"p_offline": False, "p_note": "probe"}),
    "reconcile_outages": ("manager", {"p_idem_key": K, "p_note": "probe"}),
}
SERVICE_ONLY = {"expire_holds": {}, "onboard_staff": {"p_user_id": Z, "p_name": "x", "p_role": "staff"},
                "onboard_staff_by_email": {"p_email": "nobody@example.invalid", "p_name": "x", "p_role": "staff"},
                "deactivate_staff": {"p_user_id": Z}, "import_opening_balance": {"p_idem_key": K, "p_source": "probe-source-1", "p_rows": []}}
INTERNAL = {"actor_name": {}, "apply_stock_event": {"p_variant": Z, "p_kind": "x", "p_d_on_hand": 0, "p_d_reserved": 0, "p_order": None, "p_sale": None, "p_reason": "x"},
            "idem_begin": {"p_key": K, "p_action": "x"}, "idem_end": {"p_key": K, "p_result": {}}, "lock_order_for": {"p_order": Z, "p_action": "x"},
            "lock_stock_rows": {"p_variants": []}, "log_order": {"p_order": Z, "p_action": "x", "p_from": None, "p_to": None, "p_note": ""},
            "o4u_check": {"p_base": "W0000-AAAA", "p_items": []}, "release_lines": {"p_order": Z, "p_reason": "x"}, "require_role": {"p_min": "staff"},
            "reserve_lines": {"p_order": Z}, "setting": {"p_key": "hold_minutes"}}
TRIGGER_FUNCS = {"forbid_change", "keep_one_owner", "variants_barcode_sync"}
ALL_FUNCS = set(FUNCS) | set(WRITING) | set(SERVICE_ONLY) | set(INTERNAL) | TRIGGER_FUNCS


class Ctx:
    def __init__(self, *, local: bool, rest: str, anon_key: str, tokens: dict, db=None, secret: str | None = None, stack=None,
                 real_auth: bool = False, uids: dict | None = None, auth_base: str | None = None, admin_token: str | None = None):
        self.local, self.rest, self.anon_key, self.tokens, self.db, self.secret, self.stack = local, rest.rstrip("/"), anon_key, tokens, db, secret, stack
        self.real_auth, self.auth_base, self.admin_token = real_auth, auth_base, admin_token       # real GoTrue behind the tokens (profile "gotrue")
        self.uids = uids or {"owner": OWNER, "manager": MANAGER, "staff": STAFF, "stranger": STRANGER}
        self.obs: list[tuple[str, object]] = []
        self.contract: dict[str, dict] = {}
        self._phone = 0
        register_secret(anon_key)
        for t in tokens.values():
            register_secret(t)

    # ── requests ─────────────────────────────────────────────────────────────────────────────────
    def hdr(self, role="anon", token=None, extra=None, apikey=True) -> dict:
        h = {}
        if apikey:
            h["apikey"] = self.anon_key
        if token is not None:
            h["Authorization"] = "Bearer " + token
        elif role == "anon":
            if self.anon_key.count(".") == 2:           # legacy anon key = a JWT: send it as the bearer, as supabase-js does
                h["Authorization"] = "Bearer " + self.anon_key
            # a new-style publishable key (sb_publishable_...) is not a JWT: the gateway wants it in `apikey` only
        elif role == "none":
            pass
        else:
            t = self.tokens.get(role)
            if not t:
                raise Skip(f"no signed-in '{role}' user in this run")
            h["Authorization"] = "Bearer " + t
        h.update(extra or {})
        return h

    def rpc(self, name, args=None, role="anon", *, method="POST", token=None, headers=None, raw=None, query=None, timeout=30, apikey=True) -> Resp:
        url = f"{self.rest}/rpc/{name}" + (f"?{query}" if query else "")
        h = self.hdr(role, token, headers, apikey)
        body = None
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            body = raw if raw is not None else json.dumps(args if args is not None else {})
            h.setdefault("Content-Type", "application/json")
        return request(method, url, h, body, timeout)

    def tbl(self, method, name, role="anon", *, query="", body=None, headers=None, token=None, timeout=30) -> Resp:
        url = f"{self.rest}/{name}" + (f"?{query}" if query else "")
        h = self.hdr(role, token, headers)
        data = None
        if body is not None:
            data = body if isinstance(body, (str, bytes)) else json.dumps(body)
            h.setdefault("Content-Type", "application/json")
        return request(method, url, h, data, timeout)

    def root(self, role="anon", headers=None, token=None) -> Resp:
        return request("GET", self.rest + "/", self.hdr(role, token, headers))

    def fresh(self, args: dict) -> dict:
        """A copy of probe arguments with a new idempotency key (a probe that succeeds must not poison the next one)."""
        a = dict(args)
        if "p_idem_key" in a:
            a["p_idem_key"] = self.key()
        return a

    def auth(self, method, path, body=None, token=None, service=False, headers=None) -> Resp:
        """A call to the local GoTrue (profile 'gotrue' only). service=True uses a service-role token (the admin API)."""
        if not self.auth_base:
            raise Skip("needs the real GoTrue (run_local_stack.py --gotrue)")
        h = {"apikey": self.anon_key, "Content-Type": "application/json"}
        if service:
            h["Authorization"] = "Bearer " + self.admin_token
        elif token:
            h["Authorization"] = "Bearer " + token
        h.update(headers or {})
        return request(method, self.auth_base + path, h, json.dumps(body) if body is not None else None, 30)

    # ── notes & checks ───────────────────────────────────────────────────────────────────────────
    def note(self, key, value):
        self.obs.append((key, value))

    def record(self, case, resp: Resp, **extra):
        e = resp.err() if resp.status >= 400 else {"status": resp.status, "code": None, "message": None, "details": None, "hint": None}
        e.update(extra)
        self.contract[case] = e
        return e

    @staticmethod
    def need(cond, msg):
        if not cond:
            raise Fail(msg)

    def require_local(self, what="this check"):
        if not self.local:
            raise Skip(f"{what} needs the local stack (database access or a throwaway JWT secret)")

    def phone(self) -> str:
        self._phone += 1
        return f"9{self._phone:09d}"

    # ── LOCAL world ──────────────────────────────────────────────────────────────────────────────
    def sql(self, q, *a):
        self.require_local("direct SQL")
        return self.db.execute(q, a).fetchall()

    def sql1(self, q, *a):
        r = self.sql(q, *a)
        return r[0][0] if r else None

    def reset(self, stock_a_m=5, stock_a_l=5, stock_b_m=5, online=True):
        """Wipe and re-seed INVENTED data. Stock arrives through receive_stock (over HTTP, as the owner) so the ledger explains every piece."""
        self.require_local("reset")
        c = self.db
        c.execute("""truncate sale_lines, sales, payments, refunds, payment_reports, order_events, order_lines, orders, stock_events,
                     idempotency, stock_levels, variants, products, staff, store_outages, expiry_failures restart identity cascade""")
        if not self.real_auth:          # with real GoTrue the accounts already exist (created through its admin API); only the staff list is rebuilt
            c.execute("truncate auth.users cascade")
            for uid, em in ((OWNER, "owner"), (MANAGER, "manager"), (STAFF, "staff"), (STRANGER, "stranger")):
                c.execute("insert into auth.users (id, email) values (%s, %s)", (uid, f"{em}@example.invalid"))
        c.execute("update store_status set last_heartbeat = null, offline_switch = false, note = null")
        c.execute("insert into staff values (%s,'Khush (test owner)','owner'), (%s,'Dad (test manager)','manager'), (%s,'Clerk (test staff)','staff')",
                  (self.uids["owner"], self.uids["manager"], self.uids["staff"]))
        c.execute("""insert into products (id, article, name, brand, category, colour, price_paise, published) values
                     ('tst-a-pink','TST-A','Pink Test Tee','','tshirts','Pink',%s,true),
                     ('tst-b-blue','TST-B','Blue Test Lower','','lowers','Blue',%s,true),
                     ('tst-hidden','TST-H','Hidden Test Top','','tops','Grey',%s,false)""", (PRICE_A, PRICE_B, PRICE_A))
        for pid, size, bc in (("tst-a-pink", "M", "8900000000011"), ("tst-a-pink", "L", "8900000000012"), ("tst-b-blue", "M", "8900000000021"), ("tst-hidden", "M", "8900000000031")):
            vid = c.execute("insert into variants (product_id, size, barcode) values (%s,%s,%s) returning id", (pid, size, bc)).fetchone()[0]
            c.execute("insert into stock_levels (variant_id) values (%s)", (vid,))
        for (pid, size), n in {("tst-a-pink", "M"): stock_a_m, ("tst-a-pink", "L"): stock_a_l, ("tst-b-blue", "M"): stock_b_m, ("tst-hidden", "M"): 3}.items():
            if n:
                r = self.rpc("receive_stock", {"p_idem_key": self.key(), "p_variant": self.vid(pid, size), "p_qty": n, "p_reason": "test delivery"}, "owner")
                self.need(r.status == 200, f"seeding receive_stock failed: {r.err()}")
        if online:
            r = self.rpc("store_ping", {}, "staff")
            self.need(r.status in (200, 204), f"store_ping failed: {r.err()}")

    _k = [0]

    def key(self) -> str:
        Ctx._k[0] += 1
        return f"api-key-{Ctx._k[0]:06d}-{uuid.uuid4().hex[:8]}"

    def vid(self, pid, size):
        return str(self.sql1("select id from variants where product_id=%s and size=%s", pid, size))

    def stock(self, pid, size):
        r = self.sql("select on_hand, reserved from stock_levels where variant_id=%s", self.vid(pid, size))[0]
        return r[0], r[1]

    def ref_for(self, *items):
        import run_db_tests as base      # noqa: PLC0415 - the SAME check-digit port the database tests use
        return base.ref_for(*items)

    def place(self, *items, phone=None, idem=None, ref=None, name="Test Customer", address="12 Test Street, Testville", landmark="near test park",
              role="anon", headers=None) -> Resp:
        items = items or (("tst-a-pink", "M", 1),)
        body = {"p_idem_key": idem or self.key(), "p_ref": ref or self.ref_for(*items), "p_name": name, "p_phone": phone or self.phone(),
                "p_address": address, "p_landmark": landmark, "p_lines": [{"product_id": p, "size": s, "qty": n} for p, s, n in items]}
        return self.rpc("place_order_request", body, role, headers=headers)

    def place_ok(self, *items, **kw):
        r = self.place(*items, **kw)
        self.need(r.status == 200, f"order request refused: {r.err()}")
        return r.json["order_id"], r.json["ref"]

    def rpc_get(self, name, args, role="anon", **kw) -> Resp:
        """The same call as a GET query string (arrays as {a,b}, json as text) for stable functions."""
        import urllib.parse
        parts = []
        for k, v in args.items():
            if isinstance(v, (list, dict)):
                v = json.dumps(v) if not (isinstance(v, list) and all(isinstance(x, str) for x in v) and v) else "{" + ",".join(v) + "}"
            parts.append(f"{k}={urllib.parse.quote(str(v), safe='')}")
        return self.rpc(name, role=role, method="GET", query="&".join(parts), **kw)

    def order(self, oid):
        cols = "status items_paise delivery_paise discount_paise agreed_paise paid_paise reserved stock_deducted hold_until grace_used".split()
        r = self.sql(f"select {', '.join(cols)} from orders where id=%s", oid)[0]
        return dict(zip(cols, r))

    def reserve(self, oid, who="staff", delivery=DELIVERY):
        r = self.rpc("confirm_and_reserve", {"p_idem_key": self.key(), "p_order": oid, "p_delivery_paise": delivery, "p_discount_paise": 0}, who)
        self.need(r.status == 200, f"confirm_and_reserve failed: {r.err()}")
        return r.json

    def pay(self, oid, who="staff"):
        amt = self.order(oid)["agreed_paise"]
        r = self.rpc("verify_payment", {"p_idem_key": self.key(), "p_order": oid, "p_method": "upi", "p_amount_paise": amt, "p_upi_ref": "UPI" + uuid.uuid4().hex[:10]}, who)
        self.need(r.status == 200, f"verify_payment failed: {r.err()}")
        return r.json

    def counts(self) -> dict:
        return {t: self.sql1(f"select count(*) from {t}") for t in TABLES}

    def invariants(self):
        """The ledger explains the shelf; holds match orders; nothing is negative (same sweep as the database tests)."""
        bad = self.sql("""select v.product_id, v.size from stock_levels sl join variants v on v.id = sl.variant_id
                          where sl.on_hand <> coalesce((select sum(d_on_hand) from stock_events e where e.variant_id = sl.variant_id), 0)
                             or sl.reserved <> coalesce((select sum(d_reserved) from stock_events e where e.variant_id = sl.variant_id), 0)""")
        self.need(not bad, f"stock_levels disagree with the ledger: {bad}")
        bad = self.sql("""select v.product_id, v.size from stock_levels sl join variants v on v.id = sl.variant_id
                          where sl.reserved <> coalesce((select sum(ol.qty) from order_lines ol join orders o on o.id = ol.order_id
                                                         where ol.variant_id = sl.variant_id and o.reserved), 0)""")
        self.need(not bad, f"reserved stock does not match the orders that hold it: {bad}")
        self.need(self.sql1("select count(*) from stock_levels where on_hand < 0 or reserved < 0 or reserved > on_hand") == 0, "negative or over-reserved stock")
