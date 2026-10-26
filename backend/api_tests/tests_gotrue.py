"""R. Behaviour with REAL GoTrue (Supabase's auth server, built from source, running locally): real sign-in, real tokens, real ban / delete.
Profile "gotrue" only (run_local_stack.py --gotrue). Everything is invented data on a throwaway database."""
from __future__ import annotations

import time

from ctx import FUNCS, Ctx, ZERO
from lib import Fail, Skip, payload_of, test, user_claims
from tests_jwt import battery, elevated, rank

SIGNIN = "/token?grant_type=password"


def sign_in(X: Ctx, email, password):
    return X.auth("POST", SIGNIN, {"email": email, "password": password})


def staff_probe(X: Ctx, role):
    r = X.rpc("current_role_rank", {}, role)
    c = X.rpc("confirm_and_reserve", {"p_idem_key": X.key(), "p_order": ZERO, "p_delivery_paise": 1, "p_discount_paise": 0}, role)
    return r, c


@test("R1", "R real GoTrue", "A real access token has the claim shape the database and the tests assume", where=("gotrue",))
def r1(X: Ctx):
    claims = payload_of(X.tokens["owner"])
    mine = user_claims("00000000-0000-0000-0000-000000000001")
    X.note("real_claims", {k: (v if k in ("aud", "role", "aal", "is_anonymous", "amr") else "<%s>" % type(v).__name__) for k, v in claims.items()})
    X.note("claims_only_in_my_minted_tokens", sorted(set(mine) - set(claims)))
    X.note("claims_only_in_real_tokens", sorted(set(claims) - set(mine)))
    X.need(claims["role"] == "authenticated" and claims["aud"] == "authenticated", f"role/aud: {claims['role']}/{claims['aud']}")
    for k in ("sub", "exp", "iat", "session_id", "app_metadata", "user_metadata", "aal"):
        X.need(k in claims, f"claim {k} missing from a real token")
    X.need(claims["exp"] - claims["iat"] == 3600, "expected a 1 hour token")
    import base64, json
    h = json.loads(base64.urlsafe_b64decode(X.tokens["owner"].split(".")[0] + "=="))
    X.note("jwt_header", h)
    X.need(h.get("alg") == "HS256", f"header: {h}")
    cols = {r[0] for r in X.sql("select column_name from information_schema.columns where table_schema='auth' and table_name='users'")}
    X.need({"banned_until", "deleted_at", "email", "id"} <= cols, f"auth.users lacks columns the database relies on: {sorted({'banned_until', 'deleted_at', 'email', 'id'} - cols)}")
    X.note("auth_users_columns", sorted(cols))
    r = X.rpc("current_role_rank", {}, "owner")
    X.need(r.status == 200 and r.json == 3, "a real owner token should rank 3")


@test("R2", "R real GoTrue", "Wrong password and unknown e-mail look the same; a successful sign-in has the documented shape", where=("gotrue",))
def r2(X: Ctx):
    a = sign_in(X, "owner@example.invalid", "wrong-password-xyz")
    b = sign_in(X, "nobody-here@example.invalid", "wrong-password-xyz")
    X.need(a.status == b.status == 400, f"statuses {a.status}/{b.status}")
    X.need(a.json == b.json, f"a wrong password and an unknown e-mail are distinguishable: {a.text} vs {b.text}")
    X.note("failed_sign_in", a.err() if a.json and "code" in a.json else a.json)
    ok = sign_in(X, "owner@example.invalid", "invented-pass-owner")
    X.need(ok.status == 200 and {"access_token", "refresh_token", "expires_in", "token_type", "user"} <= set(ok.json), f"sign-in body keys: {sorted(ok.json)}")
    X.note("sign_in_keys", sorted(ok.json))
    r = X.auth("POST", SIGNIN, {"email": "owner@example.invalid"})
    X.need(r.status in (400, 422), f"missing password: {r.status}")


@test("R3", "R real GoTrue", "Banning in GoTrue cuts a STILL-VALID token at once; unbanning restores it (the dashboard's Ban user button)", where=("gotrue",))
def r3(X: Ctx):
    X.reset()
    uid = X.uids["staff"]
    r, c = staff_probe(X, "staff")
    X.need(r.json == 1 and c.code == "P0001", f"baseline: {r.text} / {c.err()}")
    b = X.auth("PUT", f"/admin/users/{uid}", {"ban_duration": "24h"}, service=True)
    X.need(b.status == 200, f"ban call: {b.status} {b.text[:150]}")
    X.need(X.sql1("select banned_until > now() from auth.users where id=%s", uid) is True, "GoTrue did not set auth.users.banned_until")
    r, c = staff_probe(X, "staff")
    X.need(r.status == 200 and r.json is None and c.status == 403 and c.code == "42501", f"banned user's old token still works: {r.text} / {c.err()}")
    o = X.tbl("GET", "orders", "staff", query="select=id&limit=1")
    X.need(o.status == 200 and o.json == [], "a banned user's token still reads orders")
    s = sign_in(X, "staff@example.invalid", "invented-pass-staff")
    X.note("sign_in_while_banned", [s.status, (s.json or {}).get("error_code"), (s.json or {}).get("msg")])
    X.need(s.status >= 400, "a banned user could sign in")
    u = X.auth("PUT", f"/admin/users/{uid}", {"ban_duration": "none"}, service=True)
    X.need(u.status == 200, f"unban call: {u.status} {u.text[:150]}")
    r, c = staff_probe(X, "staff")
    X.need(r.json == 1 and c.code == "P0001", f"after unban: {r.text} / {c.err()}")
    X.need(sign_in(X, "staff@example.invalid", "invented-pass-staff").status == 200, "unbanned user cannot sign in")
    X.note("banned_until_after_unban", str(X.sql1("select banned_until from auth.users where id=%s", uid)))


@test("R4", "R real GoTrue", "Deleting a user in GoTrue (soft and hard) cuts the token at once and removes the staff row", where=("gotrue",))
def r4(X: Ctx):
    X.reset()
    made = {}
    for kind in ("soft", "hard"):
        email = f"temp-{kind}@example.invalid"
        c = X.auth("POST", "/admin/users", {"email": email, "password": "invented-pass-temp", "email_confirm": True}, service=True)
        X.need(c.status == 200, f"create {kind}: {c.text[:150]}")
        uid = c.json["id"]
        X.db.execute("insert into staff (user_id, name, role) values (%s, %s, 'staff')", (uid, f"Temp {kind}"))
        tok = sign_in(X, email, "invented-pass-temp").json["access_token"]
        made[kind] = (uid, tok)
        st, rk, _ = rank(X, tok)
        X.need(rk == 1, f"{kind}: new staff member should rank 1, got {rk}")
    uid, tok = made["soft"]
    d = X.auth("DELETE", f"/admin/users/{uid}", {"should_soft_delete": True}, service=True)
    X.need(d.status == 200, f"soft delete: {d.status} {d.text[:150]}")
    X.note("soft_delete_columns", {"deleted_at_set": X.sql1("select deleted_at is not null from auth.users where id=%s", uid), "row_still_exists": X.sql1("select count(*) from auth.users where id=%s", uid)})
    X.need(rank(X, tok)[1] is None, "a soft-deleted user's token still has a rank")
    uid, tok = made["hard"]
    d = X.auth("DELETE", f"/admin/users/{uid}", None, service=True)
    X.need(d.status == 200, f"hard delete: {d.status} {d.text[:150]}")
    X.need(X.sql1("select count(*) from auth.users where id=%s", uid) == 0 and X.sql1("select count(*) from staff where user_id=%s", uid) == 0, "hard delete left the account or the staff row")
    st, rk, _ = rank(X, tok)
    c = X.rpc("confirm_and_reserve", {"p_idem_key": X.key(), "p_order": ZERO, "p_delivery_paise": 1, "p_discount_paise": 0}, token=tok)
    X.need(st == 200 and rk is None and c.status == 403, f"hard-deleted user's token: rank {rk}, confirm {c.status}")


@test("R5", "R real GoTrue", "Anyone who can sign up (e-mail) or sign in anonymously is 'authenticated' but gets nothing: no rows, no staff functions", where=("gotrue",))
def r5(X: Ctx):
    X.reset()
    oid, _ = X.place_ok()
    X.reserve(oid)
    X.pay(oid)
    s = X.auth("POST", "/signup", {"email": "random-visitor@example.invalid", "password": "invented-pass-visitor"})
    X.need(s.status == 200 and "access_token" in s.json, f"self-signup: {s.status} {s.text[:150]} (the hosted project may ask for e-mail confirmation first)")
    X.note("self_signup_returns_a_token_immediately", True)
    b1 = battery(X, s.json["access_token"])
    X.note("self_signup_battery", b1)
    X.need(elevated(b1) is None, f"a self-signed-up visitor got: {elevated(b1)} {b1}")
    a = X.auth("POST", "/signup", {})
    X.need(a.status == 200 and "access_token" in a.json, f"anonymous sign-in: {a.status} {a.text[:150]}")
    claims = payload_of(a.json["access_token"])
    X.need(claims.get("is_anonymous") is True and claims["role"] == "authenticated", f"anonymous claims: {claims}")
    b2 = battery(X, a.json["access_token"])
    X.note("anonymous_battery", b2)
    X.need(elevated(b2) is None, f"an anonymous user got: {elevated(b2)} {b2}")
    X.need(X.rpc("get_availability", {}, token=a.json["access_token"]).status == 200, "an anonymous user cannot read availability")
    X.note("owner_decision", "Dashboard > Authentication > Providers/Sign In: switch OFF 'Allow new users to sign up' and 'Allow anonymous sign-ins' unless needed; the database already gives such users nothing.")


@test("R6", "R real GoTrue", "Refresh works; sign-out does NOT cut an access token that has not yet expired (documented behaviour, owner decision)", where=("gotrue",))
def r6(X: Ctx):
    X.reset()
    si = sign_in(X, "staff@example.invalid", "invented-pass-staff").json
    old, rt = si["access_token"], si["refresh_token"]
    r = X.auth("POST", "/token?grant_type=refresh_token", {"refresh_token": rt})
    X.need(r.status == 200 and r.json["access_token"] != old, f"refresh: {r.status} {r.text[:150]}")
    again = X.auth("POST", "/token?grant_type=refresh_token", {"refresh_token": rt})
    X.note("refresh_token_reuse", [again.status, (again.json or {}).get("error_code")])
    new = r.json["access_token"]
    X.need(rank(X, new)[1] == 1 and rank(X, old)[1] == 1, "both tokens should rank 1 before sign-out")
    sid = payload_of(new)["session_id"]
    lo = X.auth("POST", "/logout", {}, token=new)
    X.need(lo.status in (200, 204), f"logout: {lo.status} {lo.text[:100]}")
    gone = X.sql1("select count(*) from auth.sessions where id=%s", sid) == 0
    still_new, still_old = rank(X, new)[1], rank(X, old)[1]
    X.note("after_sign_out", {"session_row_deleted": gone, "new_token_rank": still_new, "old_token_rank": still_old,
                              "meaning": "PostgREST checks the signature and expiry only; the database does not look at auth.sessions. Sign-out ends the refresh capability, "
                                         "not the access token already issued (valid up to the JWT expiry, 1 hour by default)."})
    X.need(X.auth("POST", "/token?grant_type=refresh_token", {"refresh_token": r.json["refresh_token"]}).status >= 400, "the refresh token still works after sign-out")


@test("R7", "R real GoTrue", "Role changes and staff deactivation take effect at once for real tokens too", where=("gotrue",))
def r7(X: Ctx):
    X.reset()
    uid = X.uids["staff"]
    X.need(rank(X, role="staff")[1] == 1, "baseline")
    X.db.execute("update staff set role='manager' where user_id=%s", (uid,))
    X.need(rank(X, role="staff")[1] == 2, "promotion not visible")
    X.db.execute("update staff set role='staff', active=false where user_id=%s", (uid,))
    r, c = staff_probe(X, "staff")
    X.need(r.json is None and c.status == 403, "deactivated staff still work")
    X.db.execute("update staff set active=true where user_id=%s", (uid,))
    X.need(rank(X, role="staff")[1] == 1, "reactivation not visible")
    # the last owner, with a real account
    owner = X.uids["owner"]
    sv = X.admin_token
    r = X.rpc("deactivate_staff", {"p_user_id": owner}, token=sv)
    X.need(r.status >= 400 and "owner" in (r.message or "").lower(), f"last owner deactivated through the API: {r.err()}")
    d = X.auth("DELETE", f"/admin/users/{owner}", None, service=True)
    X.note("gotrue_delete_of_last_owner", [d.status, (d.json or {}).get("msg") or (d.json or {}).get("message") or d.text[:150]])
    X.need(X.sql1("select count(*) from staff where user_id=%s", owner) == 1, "deleting the last owner's account removed their staff row (no one is owner any more)")
