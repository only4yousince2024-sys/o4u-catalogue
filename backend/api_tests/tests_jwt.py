"""C. JWT handling and account state."""
from __future__ import annotations

import time

from ctx import FUNCS, MANAGER, OWNER, PKCOL, RANK, STAFF, STRANGER, ZERO, Ctx
from lib import (Fail, Skip, anon_claims, b64u, jdump, mint, mint_unsigned, parallel, payload_of, tamper_payload, test, user_claims)

OWNER_ARGS = FUNCS["owner_sales_summary"][1]


def rank(X: Ctx, token=None, role=None):
    """(HTTP status, rank or None) for current_role_rank with the given bearer token."""
    r = X.rpc("current_role_rank", {}, role or "anon", token=token)
    return r.status, (r.json if r.status == 200 else None), r


def battery(X: Ctx, token: str) -> dict:
    """What a token can actually do: rank, the owner-only function, and whether any table leaks rows."""
    st, rk, r = rank(X, token)
    o = X.rpc("owner_sales_summary", OWNER_ARGS, token=token)
    rows = {}
    for t in ("orders", "payments", "staff", "stock_events"):
        g = X.tbl("GET", t, token=token, query="select=*&limit=5")
        rows[t] = len(g.json) if g.status == 200 and isinstance(g.json, list) else f"refused {g.status}"
    w = X.tbl("DELETE", "orders", token=token, query="id=is.null")
    return {"rank_status": st, "rank": rk, "rank_code": r.code, "owner_fn": o.status, "rows": rows, "write": w.status}


def elevated(b: dict, allow_rank=None) -> str | None:
    """Why this battery shows more than a stranger could do, or None."""
    if b["rank"] not in (None, allow_rank) and b["rank"] is not None:
        return f"rank {b['rank']}"
    if b["owner_fn"] == 200:
        return "owner_sales_summary succeeded"
    if b["write"] < 400 or b["write"] >= 500:
        return f"write returned {b['write']}"
    for t, v in b["rows"].items():
        if isinstance(v, int) and v > 0 and t in ("orders", "payments", "stock_events"):
            return f"table {t} returned {v} rows"
    return None


def world(X: Ctx):
    if X.local:
        X.reset()
        oid, _ = X.place_ok()
        X.reserve(oid)
        X.pay(oid)


# ───────────────────────── C1 / C2 (hosted-capable) ─────────────────────────
@test("C1", "C JWT handling", "Missing, malformed or non-Bearer Authorization headers never give a signed-in identity")
def c1(X: Ctx):
    out = {}
    X.need(X.rpc("get_availability", {}, "none").status in (200, 401), "unexpected status without a token")
    cases = {"no header": None, "empty bearer": "Bearer ", "bearer garbage": "Bearer garbage", "three junk parts": "Bearer a.b.c",
             "two parts": "Bearer aaaa.bbbb", "basic scheme": "Basic dXNlcjpwYXNz", "bare token no scheme": X.anon_key,
             "double bearer": "Bearer Bearer " + X.anon_key, "null": "Bearer null", "undefined": "Bearer undefined"}
    for label, h in cases.items():
        hdr = {} if h is None else {"Authorization": h}
        a = X.rpc("current_role_rank", {}, "none", headers=hdr)
        b = X.rpc("get_availability", {}, "none", headers=hdr)
        out[label] = {"current_role_rank": a.err() if a.status >= 300 else a.status, "get_availability": b.status}
        X.need(a.status >= 400, f"{label}: current_role_rank returned {a.status} {a.text[:80]}")
        X.need(b.status < 500 and a.status < 500, f"{label}: server error")
        if label not in ("no header", "bare token no scheme", "basic scheme"):
            X.need(a.status == 401, f"{label}: expected 401, got {a.status}")
    X.note("authorization_header_cases", out)


@test("C2", "C JWT handling", "A real token that is altered (claims, signature, algorithm) is always rejected")
def c2(X: Ctx):
    real = X.tokens.get("staff") or X.tokens.get("owner")
    if not real:
        raise Skip("needs a signed-in user")
    victim = payload_of(X.tokens["owner"])["sub"] if "owner" in X.tokens else payload_of(real)["sub"]
    h, p, s = real.split(".")
    flip = s[:-2] + ("AB" if not s.endswith("AB") else "CD")
    payload = payload_of(real)
    variants = {
        "signature last chars changed": ".".join((h, p, flip)),
        "signature removed": f"{h}.{p}.",
        "role changed to service_role, signature kept": tamper_payload(real, role="service_role"),
        "sub changed to the owner, signature kept": tamper_payload(real, sub=victim),
        "exp pushed far ahead, signature kept": tamper_payload(real, exp=4102444800),
        "app_metadata says owner, signature kept": tamper_payload(real, app_metadata={"role": "owner"}),
        "alg none with the real claims": mint_unsigned(payload),
        "alg none with owner sub and service_role": mint_unsigned(dict(payload, sub=victim, role="service_role")),
        "alg NONE spelled upper-case": b64u(jdump({"alg": "NONE", "typ": "JWT"})) + "." + p + ".",
        "header says HS512, signature kept": b64u(jdump({"alg": "HS512", "typ": "JWT"})) + f".{p}.{s}",
        "header says RS256, signature kept": b64u(jdump({"alg": "RS256", "typ": "JWT"})) + f".{p}.{s}",
        "two tokens glued together": real + "." + real,
    }
    res = {}
    for label, tok in variants.items():
        a = X.rpc("current_role_rank", {}, token=tok)
        b = X.rpc("owner_sales_summary", OWNER_ARGS, token=tok)
        c = X.tbl("GET", "orders", token=tok, query="select=*&limit=1")
        res[label] = [a.status, a.code]
        X.need(a.status == 401 and b.status == 401 and c.status == 401, f"'{label}' was not rejected: {a.status}/{b.status}/{c.status} {a.text[:100]}")
    X.note("tampered_token_outcomes", res)


@test("C3", "C JWT handling", "Many tokens, one real person: identities never leak between simultaneous requests on pooled connections")
def c3(X: Ctx):
    world(X)
    who = [r for r in ("owner", "manager", "staff", "stranger") if r in X.tokens]
    want = {"owner": 3, "manager": 2, "staff": 1, "stranger": None}
    jobs = []
    for i in range(160):
        who_i = (who + ["anon"])[i % (len(who) + 1)]
        jobs.append((who_i, (lambda w=who_i: X.rpc("current_role_rank", {}, w))))
    res = parallel([j for _, j in jobs])
    bad = 0
    for (w, _), r in zip(jobs, res):
        if isinstance(r, Exception):
            raise Fail(f"request failed: {r}")
        if w == "anon":
            ok = r.status in (401, 403)
        else:
            ok = r.status == 200 and r.json == want[w]
        bad += 0 if ok else 1
    X.need(bad == 0, f"{bad} of {len(jobs)} simultaneous requests came back with another person's rank")
    X.note("simultaneous_requests", len(jobs))


# ───────────────────────── C4 / C5 (local: throwaway secret) ─────────────────────────
@test("C4", "C JWT handling", "Expired, not-yet-valid, wrong-signature, alg-none and odd-claim tokens (minted with the throwaway secret)", where=("local",))
def c4(X: Ctx):
    world(X)
    sec, now = X.secret, int(time.time())
    base = user_claims(OWNER)
    from lib import mint as m
    cases = [
        # label, token, rule
        ("valid control", m(sec, base), "ok"),
        ("expired 60 s ago", m(sec, user_claims(OWNER, exp=now - 60)), "reject"),
        ("expired 1 s ago (PostgREST allows ~30 s clock skew)", m(sec, user_claims(OWNER, exp=now - 1)), "observe"),
        ("expired 29 s ago", m(sec, user_claims(OWNER, exp=now - 29)), "observe"),
        ("expired 40 s ago", m(sec, user_claims(OWNER, exp=now - 40)), "reject"),
        ("not valid yet (nbf +40 s)", m(sec, user_claims(OWNER, nbf=now + 40)), "reject"),
        ("not valid yet (nbf +1 h)", m(sec, user_claims(OWNER, nbf=now + 3600)), "reject"),
        ("issued in the future (iat +1 h)", m(sec, user_claims(OWNER, iat=now + 3600)), "observe"),
        ("no exp claim at all", m(sec, {k: v for k, v in base.items() if k != "exp"}), "observe"),
        ("signed with another secret", m("a-different-throwaway-secret-000000000000", base), "reject"),
        ("alg none", mint_unsigned(base), "reject"),
        ("alg None", mint_unsigned(base, "None"), "reject"),
        ("alg HS512 with the right secret", m(sec, base, "HS512"), "observe"),
        ("alg HS384 with the right secret", m(sec, base, "HS384"), "observe"),
        ("header RS256, HMAC signature", m(sec, base, "HS256", {"alg": "RS256"}), "reject"),
        ("wrong audience", m(sec, user_claims(OWNER, aud="somebody-else")), "observe"),
        ("audience missing", m(sec, {k: v for k, v in base.items() if k != "aud"}), "observe"),
        ("audience is a list incl. authenticated", m(sec, user_claims(OWNER, aud=["authenticated", "x"])), "observe"),
        ("wrong issuer", m(sec, user_claims(OWNER, iss="https://evil.example/auth/v1")), "observe"),
        ("role claim anon, owner's sub", m(sec, user_claims(OWNER, role="anon")), "lower"),
        ("role claim missing", m(sec, {k: v for k, v in base.items() if k != "role"}), "lower"),
        ("role claim empty string", m(sec, user_claims(OWNER, role="")), "lower"),
        ("role claim is a number", m(sec, user_claims(OWNER, role=123)), "refused"),
        ("role claim is a list", m(sec, user_claims(OWNER, role=["authenticated"])), "refused"),
        ("role claim postgres", m(sec, user_claims(OWNER, role="postgres")), "refused"),
        ("role claim supabase_admin", m(sec, user_claims(OWNER, role="supabase_admin")), "refused"),
        ("role claim authenticator", m(sec, user_claims(OWNER, role="authenticator")), "refused"),
        ("role claim role that does not exist", m(sec, user_claims(OWNER, role="no_such_role")), "refused"),
        ("role claim pg_read_all_data", m(sec, user_claims(OWNER, role="pg_read_all_data")), "refused"),
        ("sub missing", m(sec, {k: v for k, v in base.items() if k != "sub"}), "norank"),
        ("sub is not a uuid", m(sec, user_claims("not-a-uuid")), "norank"),
        ("sub is an empty string", m(sec, user_claims("")), "norank"),
        ("sub is a number", m(sec, user_claims(12345)), "norank"),
    ]
    out = {}
    for label, tok, rule in cases:
        b = battery(X, tok)
        out[label] = {k: b[k] for k in ("rank_status", "rank", "rank_code", "owner_fn")}
        if rule == "ok":
            X.need(b["rank"] == 3 and b["owner_fn"] == 200, f"{label}: {b}")
        elif rule == "reject":
            X.need(b["rank_status"] == 401, f"{label} was accepted: {b}")
        elif rule == "lower":
            X.need(400 <= b["rank_status"] < 500 and 400 <= b["owner_fn"] < 500, f"{label} kept privileges: {b}")
        elif rule == "refused":
            X.need(b["rank_status"] >= 400 and b["owner_fn"] >= 400 and b["write"] >= 400 and all(not isinstance(v, int) or v == 0 for v in b["rows"].values()),
                   f"{label} reached something: {b}")
        elif rule == "norank":
            X.need(b["rank"] is None and b["owner_fn"] >= 400, f"{label} got a rank: {b}")
        else:
            X.need(b["rank_status"] < 500 or label.startswith("sub"), f"{label}: server error {b}")
    X.note("claim_variant_outcomes", out)


@test("C5", "C JWT handling", "No claim inside a token can raise anyone's rank: roles in app_metadata / user_metadata / top-level / e-mail are ignored", where=("local",))
def c5(X: Ctx):
    world(X)
    sec = X.secret
    spoof = {
        "app_metadata role owner": user_claims(STRANGER, app_metadata={"provider": "email", "role": "owner", "roles": ["owner"]}),
        "user_metadata role owner": user_claims(STRANGER, user_metadata={"role": "owner", "staff_role": "owner", "is_owner": True}),
        "top-level role claims": user_claims(STRANGER, staff_role="owner", user_role="owner", is_owner=True, owner=True, rank=3),
        "owner's e-mail": user_claims(STRANGER, email="owner@example.invalid"),
        "owner's name in user_metadata": user_claims(STRANGER, user_metadata={"name": "Khush (test owner)", "full_name": "Khush (test owner)"}),
        "aal2 + amr mfa": user_claims(STRANGER, aal="aal2", amr=[{"method": "totp", "timestamp": int(time.time())}]),
        "role claim service_role with a stranger's sub": user_claims(STRANGER, role="service_role"),
        "role claim service_role, no sub": {k: v for k, v in user_claims(STRANGER, role="service_role").items() if k != "sub"},
    }
    out = {}
    for label, claims in spoof.items():
        b = battery(X, mint(sec, claims))
        out[label] = {k: b[k] for k in ("rank_status", "rank", "owner_fn", "rows", "write")}
        why = elevated(b)
        X.need(why is None, f"{label}: a stranger got more than nothing ({why}): {b}")
    X.note("spoof_outcomes", out)
    # what a service_role token IS: the master key. It must still not read or write tables directly, and it cannot act as staff without a staff sub.
    sv = mint(sec, {"iss": "supabase-demo", "role": "service_role", "iat": int(time.time()), "exp": int(time.time()) + 600})
    X.need(X.tbl("GET", "orders", token=sv, query="select=*").status in (401, 403), "service_role can read a table directly")
    X.need(X.tbl("DELETE", "stock_events", token=sv, query="id=is.null").status in (401, 403), "service_role can write a table directly")
    r = X.rpc("confirm_and_reserve", {"p_idem_key": X.key(), "p_order": ZERO, "p_delivery_paise": 1, "p_discount_paise": 0}, token=sv)
    X.need(r.status == 403 and r.code == "42501", f"service_role without a staff identity acted as staff: {r.err()}")
    X.need(X.rpc("expire_holds", {}, token=sv).status == 200, "service_role cannot run expire_holds")
    from ctx import INTERNAL
    leaked = [n for n, a in INTERNAL.items() if X.rpc(n, X.fresh(a), token=sv).code not in ("42501", "PGRST202")]
    X.need(not leaked, f"the service role can run internal helper functions over the Data API: {leaked}")
    # service key + an owner's sub = the owner (it is the master key; it must never reach a browser)
    imp = mint(sec, user_claims(OWNER, role="service_role"))
    r = X.rpc("current_role_rank", {}, token=imp)
    X.note("service_role_with_owner_sub_rank", r.json)
    # authenticated owners cannot call the service-only functions
    for name, args in (("onboard_staff", {"p_user_id": ZERO, "p_name": "x", "p_role": "owner"}), ("deactivate_staff", {"p_user_id": OWNER}), ("expire_holds", {})):
        r = X.rpc(name, args, "owner")
        X.need(r.status == 403 and r.code == "42501", f"signed-in owner could reach service-only {name}: {r.err()}")


@test("C6", "C JWT handling", "A still-valid token stops working AT ONCE when the user is deleted, banned or deactivated, and works again when restored", where=("local",))
def c6(X: Ctx):
    world(X)
    steps = {}

    def probe(label, expect_rank):
        for role in ("staff", "manager"):
            st, rk, r = rank(X, role=role)
            c = X.rpc("confirm_and_reserve", {"p_idem_key": X.key(), "p_order": ZERO, "p_delivery_paise": 1, "p_discount_paise": 0}, role)
            o = X.tbl("GET", "orders", role, query="select=id&limit=1")
            steps[f"{label}/{role}"] = {"rank": rk, "confirm": f"{c.status} {c.code} {c.message}", "orders": len(o.json) if o.status == 200 else o.status}
            if role == "staff":
                if expect_rank:
                    X.need(rk == 1 and c.code == "P0001" and len(o.json) >= 1, f"{label}: staff should work: {steps[f'{label}/{role}']}")
                else:
                    X.need(rk is None and c.status == 403 and c.code == "42501" and o.json == [], f"{label}: staff must be cut off: {steps[f'{label}/{role}']}")
    probe("baseline", True)
    uid = STAFF
    X.db.execute("update auth.users set banned_until = now() + interval '1 day' where id = %s", (uid,))
    probe("banned for a day", False)
    X.db.execute("update auth.users set banned_until = now() - interval '1 minute' where id = %s", (uid,))
    probe("ban expired", True)
    X.db.execute("update auth.users set banned_until = null, deleted_at = now() where id = %s", (uid,))
    probe("deleted_at set", False)
    X.db.execute("update auth.users set deleted_at = null where id = %s", (uid,))
    probe("restored", True)
    X.db.execute("update staff set active = false where user_id = %s", (uid,))
    probe("staff row deactivated", False)
    X.db.execute("update staff set active = true where user_id = %s", (uid,))
    probe("reactivated", True)
    X.db.execute("delete from auth.users where id = %s", (uid,))
    probe("auth user row deleted", False)
    X.need(X.sql1("select count(*) from staff where user_id=%s", uid) == 0, "deleting the account should remove the staff row")
    # and the same, for the ban, through the manager (rank 2 -> nothing)
    X.db.execute("update auth.users set banned_until = now() + interval '1 day' where id = %s", (MANAGER,))
    st, rk, _ = rank(X, role="manager")
    X.need(rk is None, "a banned manager still has a rank")
    r = X.rpc("recount_stock", {"p_idem_key": X.key(), "p_variant": ZERO, "p_counted": 0, "p_reason": "x"}, "manager")
    X.need(r.status == 403, f"a banned manager reached recount_stock: {r.err()}")
    X.note("account_state_steps", steps)


@test("C7", "C JWT handling", "A role change is effective on the very next request with the same token (no caching)", where=("local",))
def c7(X: Ctx):
    world(X)
    X.need(rank(X, role="staff")[1] == 1, "baseline")
    X.db.execute("update staff set role='manager' where user_id=%s", (STAFF,))
    X.need(rank(X, role="staff")[1] == 2, "promotion not visible at once")
    X.db.execute("update staff set role='staff' where user_id=%s", (STAFF,))
    X.need(rank(X, role="staff")[1] == 1, "demotion not visible at once")


@test("C8", "C JWT handling", "Last-owner protection holds over HTTP; signed-in owners cannot onboard or remove staff", where=("local",))
def c8(X: Ctx):
    world(X)
    sv = mint(X.secret, {"iss": "supabase-demo", "role": "service_role", "iat": int(time.time()), "exp": int(time.time()) + 600})
    r = X.rpc("deactivate_staff", {"p_user_id": OWNER}, token=sv)
    X.need(r.status >= 400 and "owner" in (r.message or "").lower(), f"the only owner was deactivated: {r.err()}")
    X.need(X.sql1("select active from staff where user_id=%s", OWNER) is True, "the owner row changed")
    X.note("last_owner_error", X.record("last_owner_deactivate", r))
    for sql in ("delete from staff where user_id = %s", "update staff set role = 'staff' where user_id = %s", "update staff set active = false where user_id = %s"):
        try:
            X.db.execute(sql, (OWNER,))
            raise Fail(f"direct SQL removed the last owner: {sql}")
        except Fail:
            raise
        except Exception as e:      # noqa: BLE001
            X.need("owner" in str(e).lower(), f"unexpected error for {sql}: {e}")
    try:
        X.db.execute("delete from auth.users where id = %s", (OWNER,))
        raise Fail("deleting the only owner's account was allowed")
    except Fail:
        raise
    except Exception as e:      # noqa: BLE001
        X.note("delete_last_owner_account", str(e)[:120])
    # with a second owner the first can be removed; then the second is protected
    X.db.execute("insert into auth.users (id, email) values ('00000000-0000-0000-0000-0000000000a2', 'second@example.invalid')")
    r = X.rpc("onboard_staff", {"p_user_id": "00000000-0000-0000-0000-0000000000a2", "p_name": "Second owner", "p_role": "owner"}, token=sv)
    X.need(r.status == 200, f"onboarding a second owner: {r.err()}")
    X.need(X.rpc("deactivate_staff", {"p_user_id": OWNER}, token=sv).status == 200, "with two owners the first can be deactivated")
    r = X.rpc("deactivate_staff", {"p_user_id": "00000000-0000-0000-0000-0000000000a2"}, token=sv)
    X.need(r.status >= 400, "the remaining owner was deactivated")
    # a BANNED sole owner is a lock-out that this rule cannot see (documented, not asserted)
    X.db.execute("update auth.users set banned_until = now() + interval '1 day' where id = '00000000-0000-0000-0000-0000000000a2'")
    X.note("sole_owner_banned_means_nobody_has_owner_rank", True)
