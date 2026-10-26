"""A. Public surface and B. Roles over HTTP."""
from __future__ import annotations

from ctx import ALL_FUNCS, ANON_FUNCS, FUNCS, INTERNAL, NOROWS, RANK, SERVICE_ONLY, TABLES, WRITING, ZERO, Ctx
from lib import Fail, Skip, test

AUTH_FUNCS = set(FUNCS) | set(WRITING)            # what a signed-in user may reach (staff rank decided inside the function)
from ctx import PKCOL      # noqa: E402


def PKCOLS(t):
    return PKCOL[t]


DENY_CODES = {"42501", "PGRST202", "PGRST205"}


def refused(r) -> bool:
    return r.status in (401, 403, 404) and (r.code in DENY_CODES)


def reached(r) -> bool:
    """The call got past authorization into the function: success, or one of OUR business errors."""
    return r.status < 300 or (r.status < 500 and r.code not in DENY_CODES and not (r.code or "").startswith("PGRST"))


def swagger_paths(r):
    j = r.json
    need = isinstance(j, dict) and "paths" in j
    if not need:
        raise Fail(f"no OpenAPI document (status {r.status}): {r.text[:200]}")
    return set(j["paths"]), set((j.get("definitions") or {}).keys())


# ───────────────────────── A. public surface ─────────────────────────
@test("A1", "A public surface", "OpenAPI document for anon lists exactly the three public functions and no table")
def a1(X: Ctx):
    for role in ("anon", "none"):
        r = X.root(role)
        if r.status in (401, 403, 404) and not X.local:      # newer hosted projects may hide the document from the anon key altogether: even better
            X.note(f"openapi_{role}", f"not served to this caller (HTTP {r.status}): nothing to list")
            continue
        X.need(r.status == 200, f"GET /rest/v1/ as {role}: {r.status} {r.text[:150]}")
        paths, defs = swagger_paths(r)
        rpc = {p[len("/rpc/"):] for p in paths if p.startswith("/rpc/")}
        X.need(rpc == ANON_FUNCS, f"{role}: OpenAPI lists functions {sorted(rpc ^ ANON_FUNCS)} differently from the allowlist")
        tables = {p.strip("/") for p in paths if not p.startswith("/rpc/") and p != "/"}
        X.need(not tables, f"{role}: OpenAPI lists tables {sorted(tables)}")
        X.need(not (defs & set(TABLES)), f"{role}: OpenAPI definitions mention tables {sorted(defs & set(TABLES))}")
        X.note(f"openapi_{role}", {"paths": sorted(paths), "definitions": sorted(defs)})


@test("A2", "A public surface", "OpenAPI for a signed-in stranger lists no function a stranger cannot use")
def a2(X: Ctx):
    r = X.root("stranger")
    if r.status in (401, 403, 404) and not X.local:
        X.note("openapi_authenticated", f"not served to this caller (HTTP {r.status})")
        return
    paths, _ = swagger_paths(r)
    rpc = {p[len("/rpc/"):] for p in paths if p.startswith("/rpc/")}
    X.need(rpc == AUTH_FUNCS, f"functions listed to a signed-in user differ from the allowlist: {sorted(rpc ^ AUTH_FUNCS)}")
    X.need(not (rpc & (set(SERVICE_ONLY) | set(INTERNAL))), "internal/service-only functions are advertised")
    X.note("openapi_authenticated_tables", sorted(p.strip("/") for p in paths if not p.startswith("/rpc/") and p != "/"))


@test("A3", "A public surface", "Every function in public except the three is refused to anon (with and without the anon key as bearer)")
def a3(X: Ctx):
    calls = {n: a for n, (_, a) in FUNCS.items()}
    if X.local:
        calls.update({n: a for n, (_, a) in WRITING.items()})
    calls.update(SERVICE_ONLY)
    calls.update(INTERNAL)
    seen = {}
    for role in ("anon", "none"):
        for name, args in calls.items():
            r = X.rpc(name, X.fresh(args), role)
            seen[(role, name)] = (r.status, r.code)
            if name in ANON_FUNCS:
                X.need(reached(r), f"{role}: {name} should reach its business logic, got {r.err()}")
            else:
                X.need(refused(r), f"{role}: {name} was NOT refused: {r.err()}")
    X.note("anon_function_outcomes", {f"{r}:{n}": f"{s} {c}" for (r, n), (s, c) in sorted(seen.items())})
    if X.local:       # the table above must cover every function that exists, or a new function could slip through unprobed
        have = {r[0] for r in X.sql("select p.proname from pg_proc p where p.pronamespace='public'::regnamespace and p.prokind='f' "
                                    "and not exists (select 1 from pg_depend d where d.objid=p.oid and d.deptype='e')")}
        X.need(have == ALL_FUNCS, f"the probe list is out of date; functions not probed: {sorted(have - ALL_FUNCS)}, probes with no function: {sorted(ALL_FUNCS - have)}")


@test("A4", "A public surface", "Every table refuses GET, POST, PATCH, DELETE and upsert for anon")
def a4(X: Ctx):
    out = {}
    for t in TABLES:
        for method, kw in (("GET", {"query": "select=*"}), ("POST", {"body": {}}), ("PATCH", {"query": NOROWS(t), "body": {PKCOLS(t): None}}),
                           ("DELETE", {"query": NOROWS(t)}), ("POST", {"body": [{}], "headers": {"Prefer": "resolution=merge-duplicates"}}),
                           ("HEAD", {}), ("GET", {"query": "select=*", "role": "none"})):
            kw = dict(kw)
            role = kw.pop("role", "anon")
            r = X.tbl(method, t, role, **kw)
            out[f"{method} {t}"] = r.status
            # PGRST204 = PostgREST's own "no such column" answer, given before the database is asked: still nothing was touched
            X.need(r.status in (401, 403, 404) or (r.status == 400 and r.code == "PGRST204"), f"anon {method} {t} -> {r.status} {r.text[:120]}")
            if method != "HEAD":
                X.need(r.code in DENY_CODES | {"PGRST204"}, f"anon {method} {t}: unexpected code {r.code}")
    X.note("anon_table_statuses", sorted(set(out.values())))


@test("A5", "A public surface", "Only schema public is reachable: Accept-Profile / Content-Profile for other schemas is refused")
def a5(X: Ctx):
    for sch in ("auth", "storage", "pg_catalog", "information_schema", "extensions", "graphql_public", "vault", "cron"):
        r = X.tbl("GET", "users", "anon", headers={"Accept-Profile": sch})
        X.need(r.status in (404, 406) and not (r.status < 300), f"Accept-Profile {sch}: {r.status} {r.text[:100]}")
        r2 = X.rpc("get_availability", {}, "anon", headers={"Content-Profile": sch})
        X.need(r2.status in (404, 406), f"Content-Profile {sch}: {r2.status} {r2.text[:100]}")
    for t in ("users", "pg_tables", "pg_proc", "pg_roles", "pg_authid"):
        r = X.tbl("GET", t, "stranger", query="select=*")
        X.need(r.status in (401, 403, 404), f"/{t} as a signed-in stranger -> {r.status} {r.text[:100]}")
    X.note("profile_error", X.tbl("GET", "users", "anon", headers={"Accept-Profile": "auth"}).err())


@test("A6", "A public surface", "The three public functions reach business logic for anon (bad input -> our own errors)")
def a6(X: Ctx):
    r = X.rpc("get_availability", {}, "anon")
    X.need(r.status == 200 and isinstance(r.json, list), f"get_availability: {r.status} {r.text[:150]}")
    if r.json:
        X.need(set(r.json[0]) == {"product_id", "size", "state", "n", "as_of"}, f"availability columns changed: {sorted(r.json[0])}")
        X.need(all(x["state"] in ("available", "low", "ask", "check") for x in r.json), "unexpected availability state")
    r = X.rpc("place_order_request", FUNCS["place_order_request"][1], "anon")
    X.need(r.status == 400 and r.code == "P0001", f"place_order_request with bad input: {r.err()}")
    r = X.rpc("report_payment", FUNCS["report_payment"][1], "anon")
    X.need(r.status == 400 and r.code == "P0001" and "order not found" in (r.message or ""), f"report_payment unknown ref: {r.err()}")


@test("A7", "A public surface", "HTTP verbs: volatile functions refuse GET; PUT/PATCH/DELETE on /rpc are refused; nothing gets a 5xx")
def a7(X: Ctx):
    for name in ("place_order_request", "report_payment"):
        r = X.rpc_get(name, FUNCS[name][1], "anon")
        X.need(r.status == 405, f"GET {name} (volatile) -> {r.status} {r.text[:120]}")
        X.note(f"get_volatile_{name}", r.err())
    for m in ("PUT", "PATCH", "DELETE"):
        r = X.rpc("get_availability", {}, "anon", method=m)
        X.need(r.status in (404, 405), f"{m} /rpc/get_availability -> {r.status}")
    r = X.rpc("get_availability", role="anon", method="GET")
    X.need(r.status == 200, f"GET get_availability (stable) -> {r.status}")


@test("A8", "A public surface", "Hosted gateway: a request without or with a wrong apikey is refused before reaching the database", where=("hosted",))
def a8(X: Ctx):
    r = X.rpc("get_availability", {}, "none", apikey=False)
    X.need(r.status in (401, 403), f"no apikey, no bearer -> {r.status} {r.text[:120]}")
    X.note("no_apikey", r.err())
    r = X.rpc("get_availability", {}, "none", headers={"apikey": "not-a-real-key"}, apikey=False)
    X.need(r.status in (401, 403), f"wrong apikey -> {r.status}")
    X.note("wrong_apikey", r.err())


# ───────────────────────── B. roles ─────────────────────────
@test("B1", "B roles over HTTP", "Role matrix: each role may call exactly the staff functions its rank allows")
def b1(X: Ctx):
    if X.local:
        X.reset()
    roles = ["anon", "stranger", "staff", "manager", "owner"]
    calls = dict(FUNCS)
    if X.local:
        calls.update(WRITING)
    results = {}
    for role in roles:
        if role != "anon" and role not in X.tokens:
            continue
        for name, (minrole, args) in calls.items():
            allowed = RANK[role] >= RANK[minrole] and not (role == "anon" and minrole != "anon")
            r = X.rpc(name, X.fresh(args), role)
            results[(role, name)] = (r.status, r.code)
            if allowed:
                X.need(reached(r), f"{role} should reach {name}, got {r.err()}")
            else:
                X.need(refused(r), f"{role} must NOT reach {name} (needs {minrole}), got {r.err()}")
                if role not in ("anon",):
                    X.need(r.status == 403 and r.code == "42501", f"{role}->{name}: expected 403/42501, got {r.status}/{r.code}")
    X.note("role_matrix", {f"{r}:{n}": f"{s} {c}" for (r, n), (s, c) in sorted(results.items())})
    # the discount rule inside confirm_and_reserve: staff may confirm, only a manager may discount
    if X.local:
        oid, _ = X.place_ok()
        r = X.rpc("confirm_and_reserve", {"p_idem_key": X.key(), "p_order": oid, "p_delivery_paise": 5000, "p_discount_paise": 100}, "staff")
        X.need(r.status == 403 and r.code == "42501" and "manager" in r.message, f"staff giving a discount must be refused: {r.err()}")
        X.need(X.order(oid)["status"] == "request", "the refused discount changed the order")
        r = X.rpc("confirm_and_reserve", {"p_idem_key": X.key(), "p_order": oid, "p_delivery_paise": 5000, "p_discount_paise": 100}, "manager")
        X.need(r.status == 200, f"a manager may give the discount: {r.err()}")


@test("B2", "B roles over HTTP", "Table reads: staff cannot read payments/sales/refunds; a stranger gets empty sets, not errors; anon is refused")
def b2(X: Ctx):
    if X.local:
        X.reset()
        oid, _ = X.place_ok()
        X.reserve(oid)
        X.pay(oid)
        r = X.rpc("request_refund", {"p_idem_key": X.key(), "p_order": oid, "p_reason": "test"}, "manager")
        X.need(r.status == 200, f"refund setup: {r.err()}")
        r = X.rpc("complete_sale", {"p_idem_key": X.key(), "p_lines": [{"product_id": "tst-b-blue", "size": "M", "qty": 1}],
                                    "p_payments": [{"method": "cash", "amount_paise": 149900}]}, "staff")
        X.need(r.status == 200, f"sale setup: {r.err()}")
        rows = {t: X.sql1(f"select count(*) from {t}") for t in ("payments", "sales", "refunds", "orders")}
        X.need(all(v > 0 for v in rows.values()), f"the world needs rows in the money tables first: {rows}")
    money = ("payments", "sales", "refunds", "sale_lines")
    got = {}
    for role in ("stranger", "staff", "manager", "owner"):
        if role not in X.tokens:
            continue
        for t in TABLES:
            r = X.tbl("GET", t, role, query="select=*&limit=3")
            got[(role, t)] = (r.status, len(r.json) if isinstance(r.json, list) else None)
            if t in ("idempotency", "app_settings"):
                X.need(r.status in (401, 403), f"{role} reading {t} must be refused, got {r.status}")
                continue
            X.need(r.status == 200 and isinstance(r.json, list), f"{role} GET {t}: {r.status} {r.text[:120]}")
            if role == "stranger":
                X.need(r.json == [], f"stranger sees rows in {t}: {len(r.json)}")
            if role == "staff" and t in money:
                X.need(r.json == [], f"staff sees rows in {t}")
            if role == "staff" and t == "staff":
                X.need(len(r.json) == 1, f"staff should see only their own staff row, saw {len(r.json)}")
    if X.local:
        X.need(got[("staff", "orders")][1] >= 1, "staff cannot see orders")
        for t in ("payments", "sales", "refunds"):
            for role in ("manager", "owner"):
                X.need(got[(role, t)][1] >= 1, f"{role} cannot see {t} although rows exist")
    for t in TABLES:
        X.need(X.tbl("GET", t, "anon", query="select=*").status in (401, 403), f"anon can read {t}")
    X.note("table_reads", {f"{r}:{t}": f"{s}/{n}" for (r, t), (s, n) in sorted(got.items())})


@test("B3", "B roles over HTTP", "Nobody can write any table directly over HTTP (POST / PATCH / DELETE / upsert / unfiltered DELETE), and nothing changes")
def b3(X: Ctx):
    if X.local:
        X.reset()
        X.place_ok()
        before = X.counts()
    out = {}
    for role in ("stranger", "staff", "manager", "owner"):
        if role not in X.tokens:
            continue
        for t in TABLES:
            tries = [("POST", dict(body={})), ("POST", dict(body=[{}], headers={"Prefer": "resolution=merge-duplicates"})),
                     ("PATCH", dict(query=NOROWS(t), body={PKCOLS(t): None})), ("DELETE", dict(query=NOROWS(t)))]
            for method, kw in tries:
                r = X.tbl(method, t, role, **kw)
                out[f"{role} {method} {t}"] = r.status
                X.need(r.status in (401, 403, 404), f"{role} {method} {t} -> {r.status} {r.text[:120]}")
    X.note("table_write_statuses", sorted(set(out.values())))
    if X.local:
        X.need(X.counts() == before, "a direct write changed a table")
        for sql in ("truncate stock_events", "truncate orders cascade", "delete from stock_events"):     # TRUNCATE has no HTTP verb; prove the roles cannot do it even if one existed
            for role in ("authenticated", "anon", "service_role"):
                try:
                    X.db.execute(f"set role {role}")
                    X.db.execute(sql)
                    raise Fail(f"{role} could run: {sql}")
                except Fail:
                    raise
                except Exception:      # noqa: BLE001 - permission denied is the point
                    pass
                finally:
                    X.db.execute("reset role")


@test("B4", "B roles over HTTP", "The owner summary needs the owner: staff and manager are refused with 403 'needs owner access'")
def b4(X: Ctx):
    if X.local:
        X.reset()
    args = FUNCS["owner_sales_summary"][1]
    for role in ("staff", "manager"):
        r = X.rpc("owner_sales_summary", args, role)
        X.need(r.status == 403 and r.code == "42501" and "owner" in (r.message or ""), f"{role}: {r.err()}")
    r = X.rpc("owner_sales_summary", args, "owner")
    X.need(r.status == 200 and isinstance(r.json, list), f"owner: {r.err()}")
    X.note("owner_summary_shape", sorted(r.json[0]) if r.json else "no rows in range")


@test("B5", "B roles over HTTP", "The probe calls used on the hosted project write nothing, even when the role is allowed to make them (checked locally)", where=("local",))
def b5(X: Ctx):
    X.reset()
    before = X.counts()
    for role in ("owner", "manager", "staff"):
        for name, (minrole, args) in FUNCS.items():
            X.rpc(name, X.fresh(args), role)
    for name, (minrole, args) in FUNCS.items():
        X.rpc(name, X.fresh(args), "anon")
    after = X.counts()
    X.need(before == after, f"probe calls changed tables: {[(t, before[t], after[t]) for t in before if before[t] != after[t]]}")
