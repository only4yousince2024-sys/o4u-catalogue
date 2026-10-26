"""Shared plumbing for the O4U API tests: a stdlib-only HTTP client (so the hosted runner needs no pip install), a tiny JWT
minter for the LOCAL harness only (throwaway secret, never a real one), output redaction and the test registry.

Nothing in this file reads a file for secrets. Keys and tokens live in memory and are scrubbed from everything printed or written.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import json
import re
import ssl
import threading
import time
import urllib.parse
import uuid

# ───────────────────────── redaction ─────────────────────────
_SECRETS: set[str] = set()
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]*")
_KEY_RE = re.compile(r"sb_(?:publishable|secret)_[A-Za-z0-9_-]{8,}")


def register_secret(s: str | None):
    """Anything registered here is replaced by [redacted] in every string passed through redact()."""
    if s and len(s) >= 6:
        _SECRETS.add(s)


def redact(text) -> str:
    text = str(text)
    for s in sorted(_SECRETS, key=len, reverse=True):
        text = text.replace(s, "[redacted]")
    text = _JWT_RE.sub("[jwt-redacted]", text)
    return _KEY_RE.sub("[key-redacted]", text)


# ───────────────────────── HTTP ─────────────────────────
class Resp:
    def __init__(self, status: int, headers: dict, body: bytes, elapsed: float):
        self.status, self.headers, self.body, self.elapsed = status, headers, body, elapsed

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    @property
    def json(self):
        try:
            return json.loads(self.body) if self.body else None
        except ValueError:
            return None

    @property
    def code(self):
        j = self.json
        return j.get("code") if isinstance(j, dict) else None

    @property
    def message(self):
        j = self.json
        return j.get("message") if isinstance(j, dict) else None

    def err(self) -> dict:
        j = self.json
        if isinstance(j, dict) and ("code" in j or "message" in j):
            return {"status": self.status, "code": j.get("code"), "message": j.get("message"), "details": j.get("details"), "hint": j.get("hint")}
        return {"status": self.status, "code": None, "message": self.text[:200], "details": None, "hint": None}


def request(method: str, url: str, headers: dict | None = None, body: bytes | str | None = None, timeout: float = 30.0) -> Resp:
    """One request, one connection. Never raises on an HTTP error status; raises on network failure."""
    u = urllib.parse.urlsplit(url)
    cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
    kw = {"context": ssl.create_default_context()} if u.scheme == "https" else {}
    conn = cls(u.hostname, u.port, timeout=timeout, **kw)
    if isinstance(body, str):
        body = body.encode("utf-8")
    hdr = dict(headers or {})
    if body is not None and not any(k.lower() == "content-length" for k in hdr):
        hdr["Content-Length"] = str(len(body))
    t0 = time.perf_counter()
    try:
        path = u.path + (("?" + u.query) if u.query else "")
        conn.request(method, path, body=body, headers=hdr)
        r = conn.getresponse()
        data = r.read()
        return Resp(r.status, {k.lower(): v for k, v in r.getheaders()}, data, time.perf_counter() - t0)
    finally:
        conn.close()


# ───────────────────────── JWT (LOCAL harness only) ─────────────────────────
def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def jdump(o) -> bytes:
    return json.dumps(o, separators=(",", ":")).encode()


def mint(secret: str, claims: dict, alg: str = "HS256", header: dict | None = None) -> str:
    h = {"alg": alg, "typ": "JWT"}
    h.update(header or {})
    signing = b64u(jdump(h)) + "." + b64u(jdump(claims))
    dig = {"HS256": hashlib.sha256, "HS384": hashlib.sha384, "HS512": hashlib.sha512}[alg]
    sig = hmac.new(secret.encode(), signing.encode(), dig).digest()
    return signing + "." + b64u(sig)


def mint_unsigned(claims: dict, alg: str = "none") -> str:
    return b64u(jdump({"alg": alg, "typ": "JWT"})) + "." + b64u(jdump(claims)) + "."


def user_claims(sub: str, *, now: int | None = None, **over) -> dict:
    """The claim shape Supabase Auth (GoTrue) puts in an access token for a signed-in user."""
    now = now or int(time.time())
    c = {"iss": "http://127.0.0.1:54321/auth/v1", "aud": "authenticated", "exp": now + 3600, "iat": now, "sub": sub,
         "email": f"user-{str(sub)[-4:]}@example.invalid", "phone": "", "app_metadata": {"provider": "email", "providers": ["email"]},
         "user_metadata": {}, "role": "authenticated", "aal": "aal1",
         "amr": [{"method": "password", "timestamp": now}], "session_id": str(uuid.uuid4()), "is_anonymous": False}
    c.update(over)
    return c


def anon_claims(*, now: int | None = None) -> dict:
    now = now or int(time.time())
    return {"iss": "supabase-demo", "role": "anon", "iat": now, "exp": now + 10 * 365 * 86400}


def tamper_payload(token: str, **claims) -> str:
    """Change claims inside a REAL token but keep its original signature (the signature then no longer matches)."""
    h, p, s = token.split(".")
    pad = "=" * (-len(p) % 4)
    d = json.loads(base64.urlsafe_b64decode(p + pad))
    d.update(claims)
    return h + "." + b64u(jdump(d)) + "." + s


def payload_of(token: str) -> dict:
    p = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))


# ───────────────────────── test registry & context ─────────────────────────
class Fail(Exception):
    pass


class Skip(Exception):
    pass


TESTS: list[dict] = []


def test(tid: str, area: str, title: str, where=("local", "hosted")):
    """where: profiles that can run it. The hosted profile only runs read-only / always-refused calls."""
    def deco(fn):
        TESTS.append({"id": tid, "area": area, "title": title, "where": tuple(where), "fn": fn})
        return fn
    return deco


def parallel(fns, timeout=90):
    """Run callables at the same instant (barrier), each in its own thread. Returns values or Exceptions."""
    barrier, out = threading.Barrier(len(fns)), [None] * len(fns)

    def run(i, f):
        try:
            barrier.wait(timeout=20)
            out[i] = f()
        except Exception as e:      # noqa: BLE001 - every outcome is data
            out[i] = e
    ts = [threading.Thread(target=run, args=(i, f)) for i, f in enumerate(fns)]
    [x.start() for x in ts]
    [x.join(timeout) for x in ts]
    return out
