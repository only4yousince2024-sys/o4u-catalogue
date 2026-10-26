"""E. CORS (browser origins).

LABEL: on the LOCAL profile the answers come from PostgREST itself. On a hosted Supabase project they come from Supabase's API
gateway, which handles CORS before PostgREST sees the request - so local results do NOT prove what the hosted project does.
Curl-style requests also cannot prove what a browser will accept: the real-browser check is `browser_cors_check.html`
(see README, 'Real-browser CORS check').
"""
from __future__ import annotations

import os

from ctx import Ctx
from lib import request, test

SITE = "https://only4you.example"                     # stand-in for the shop's site; hosted runs add O4U_SITE_ORIGIN if set
ORIGINS = [("the shop's site", SITE), ("another site", "https://evil.example"), ("null (file:// or sandboxed frame)", "null"),
           ("http://localhost", "http://localhost"), ("localhost with a port", "http://localhost:3000"), ("127.0.0.1 with a port", "http://127.0.0.1:8765")]
BROWSER_HEADERS = "apikey,authorization,content-type,prefer,x-client-info"
EXTRA_HEADERS = "accept-profile,content-profile,x-supabase-api-version"


def origins():
    o = list(ORIGINS)
    extra = os.environ.get("O4U_SITE_ORIGIN", "").strip()
    if extra:
        o.insert(0, ("the real site (O4U_SITE_ORIGIN)", extra))
    return o


def cors_view(h):
    return {"allow-origin": h.get("access-control-allow-origin"), "allow-headers": h.get("access-control-allow-headers"),
            "allow-methods": h.get("access-control-allow-methods"), "max-age": h.get("access-control-max-age"),
            "allow-credentials": h.get("access-control-allow-credentials"), "expose-headers": h.get("access-control-expose-headers"),
            "vary": h.get("vary")}


def must_work(label: str) -> bool:
    """Origins the site really runs from (shop site, local development) must work; 'another site' and 'null' are recorded, not judged."""
    return label.startswith(("the shop's site", "the real site", "http://localhost", "localhost", "127.0.0.1"))


def covers(allow_headers: str | None, wanted: str) -> list[str]:
    """Which wanted request headers the server's Access-Control-Allow-Headers does NOT cover."""
    if allow_headers is None:
        return wanted.split(",")
    have = {x.strip().lower() for x in allow_headers.split(",")}
    return [w for w in wanted.split(",") if "*" not in have and w not in have]


@test("E1", "E CORS", "Preflight (OPTIONS) from the shop's site, another site, null and localhost for the headers a browser client sends")
def e1(X: Ctx):
    out = {}
    problems = []
    for label, origin in origins():
        for path, method in (("/rpc/get_availability", "POST"), ("/rpc/place_order_request", "POST"), ("/rpc/report_payment", "POST"), ("/rpc/confirm_and_reserve", "POST"), ("/orders", "GET")):
            h = {"Origin": origin, "Access-Control-Request-Method": method, "Access-Control-Request-Headers": BROWSER_HEADERS + "," + EXTRA_HEADERS}
            r = request("OPTIONS", X.rest + path, h)      # a preflight carries no apikey or token, exactly like a browser's
            v = cors_view(r.headers)
            out[f"{label} {method} {path}"] = {"status": r.status, **v}
            X.need(r.status < 500, f"{label} {path}: preflight gave {r.status}")
            X.need((v["allow-credentials"] or "").lower() != "true", f"{label}: Access-Control-Allow-Credentials: true (tokens travel in headers, never cookies)")
            ao = v["allow-origin"]
            if not must_work(label):
                continue
            if r.status in (200, 204) and path.startswith(("/rpc/get_availability", "/rpc/place_order_request")):
                if ao not in ("*", origin):
                    problems.append(f"{label}: Allow-Origin={ao!r} for a browser at {origin}")
                miss = covers(v["allow-headers"], BROWSER_HEADERS)
                if miss and ao in ("*", origin):
                    problems.append(f"{label} {path}: Allow-Headers does not cover {miss}")
                if ao in ("*", origin) and method not in (v["allow-methods"] or ""):
                    problems.append(f"{label} {path}: Allow-Methods {v['allow-methods']!r} lacks {method}")
    X.note("preflight_matrix (" + ("LOCAL PostgREST, not Supabase's gateway" if X.local else "HOSTED gateway") + ")", out)
    if X.local:
        X.note("local_caveat", "PostgREST echoes whatever headers are asked for and answers Allow-Origin: * to every origin. Supabase's gateway has its own list; run the hosted profile and the browser page.")
    X.need(not problems, "; ".join(problems[:6]))


@test("E2", "E CORS", "Real requests (not preflights) carry the right CORS headers, and errors do too (a browser must be able to read a 400/401)")
def e2(X: Ctx):
    out = {}
    problems = []
    for label, origin in origins():
        for name, call in (("GET get_availability 200", lambda o=origin: X.rpc("get_availability", {}, "anon", headers={"Origin": o})),
                           ("POST place_order_request 400", lambda o=origin: X.rpc("place_order_request", {"p_idem_key": "cors-probe-0001", "p_ref": "x", "p_name": "", "p_phone": "1", "p_address": "", "p_landmark": "", "p_lines": []}, "anon", headers={"Origin": o})),
                           ("POST confirm_and_reserve 401", lambda o=origin: X.rpc("confirm_and_reserve", {"p_idem_key": "cors-probe-0001", "p_order": "00000000-0000-0000-0000-000000000000", "p_delivery_paise": 1, "p_discount_paise": 0}, "anon", headers={"Origin": o})),
                           ("GET table 401", lambda o=origin: X.tbl("GET", "orders", "anon", query="select=*", headers={"Origin": o}))):
            r = call()
            v = cors_view(r.headers)
            out[f"{label} {name}"] = {"status": r.status, **v}
            if must_work(label) and v["allow-origin"] not in ("*", origin):
                problems.append(f"{label} {name}: status {r.status} without Allow-Origin ({v['allow-origin']!r}) - the browser would hide the answer from the page")
    X.note("simple_request_matrix (" + ("LOCAL PostgREST" if X.local else "HOSTED gateway") + ")", out)
    X.need(not problems, "; ".join(problems[:6]))
