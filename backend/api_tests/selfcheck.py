"""Do the API tests notice breakage? Break the throwaway database on purpose, one way at a time, and require that at least one API test
fails each time. Local only. SURVIVED = a gap in the tests.

    python3 backend/api_tests/selfcheck.py            # all breakages (about 5 s each)
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import psycopg      # noqa: E402

import runner      # noqa: E402
import stack      # noqa: E402
from ctx import MANAGER, OWNER, STAFF, STRANGER, Ctx      # noqa: E402
from lib import anon_claims, mint, register_secret, user_claims      # noqa: E402

M = stack.MIGRATIONS
# (label, tests that must notice, sql to run after the migrations  OR  (file prefix, old text, new text) to edit a migration copy)
BREAKS = [
    ("anon may read orders", "A,B", "grant select on orders to anon"),
    ("anon may run pack_order", "A", "grant execute on function pack_order(text,uuid) to anon"),
    ("anon may run an internal helper", "A", "grant execute on function apply_stock_event(uuid,text,int,int,uuid,uuid,text) to anon"),
    ("signed-in users may insert into products", "B3", "grant insert on products to authenticated; create policy x on products for insert to authenticated with check (true)"),
    ("row-level security off on orders", "B2", "alter table orders disable row level security"),
    ("staff may read payments", "B2", "grant select on payments to authenticated; drop policy if exists money_read on payments; create policy staff_pay on payments for select to authenticated using (true)"),
    ("manager may read the owner summary", "B4,B1", ("0001", "perform require_role('owner');", "perform require_role('manager');")),
    ("ban is ignored by the rank function", "C6", ("0002", "(u.deleted_at is not null or u.banned_until > now())", "(u.deleted_at is not null)")),
    ("deactivated staff still count", "C6", ("0002", "where s.user_id = auth.uid() and s.active\n", "where s.user_id = auth.uid()\n")),
    ("any signed-in user counts as staff", "B1,C5,C6", ("0002", "where s.user_id = auth.uid() and s.active\n", "where s.active\n")),
    ("service role may run internal helpers", "C5", "grant execute on function apply_stock_event(uuid,text,int,int,uuid,uuid,text) to service_role"),
    ("rate limit raised with the old code", "F1,F2", ("0009", "using errcode = 'PT429';\n  end if;\n  if (select count(*) from orders where created_at", "using errcode = 'P0429';\n  end if;\n  if (select count(*) from orders where created_at")),
    ("no cap on payment reports", "F5", ("0009", "if (select count(*) from payment_reports where order_id = o.id) >= setting('max_payment_reports_per_order') then", "if false then")),
    ("no name length limit", "F6", ("0009", "if char_length(trim(p_name)) > 100 then", "if false then")),
    ("no per-phone limit", "G5,F1", ("0009", "if (select count(*) from orders where phone = p_phone and created_at > now() - interval '1 hour') >= setting('rate_phone_per_hour')\n     or", "if false\n     or")),
    ("stock rows no longer locked", "G1", ("0001", "order by variant_id for update\n$$;", "order by variant_id\n$$;")),
    ("CORS restricted to another site (PostgREST setting)", "E", {"server-cors-allowed-origins": "https://not-the-shop.example"}),
    ("unknown reference gives a different message than a wrong phone", "F3", ("0009", "if p_ref is null or p_phone is null or char_length(p_ref) > 20 or char_length(p_phone) > 20 then raise exception 'order not found'; end if;", "if p_ref is null or p_phone is null or char_length(p_ref) > 20 or char_length(p_phone) > 20 then raise exception 'bad reference'; end if;")),
]


def run_one(label, only, brk) -> tuple[str, list]:
    migs = M
    sql = None
    tmp = None
    extra = None
    if isinstance(brk, dict):
        extra = brk
    elif isinstance(brk, tuple):
        pre, old, new = brk
        tmp = tempfile.TemporaryDirectory(prefix="o4u-selfcheck-")
        migs = []
        hit = False
        for m in M:
            t = m.read_text(encoding="utf-8")
            if m.name.startswith(pre):
                if old not in t:
                    return "ERROR", [f"text to replace not found in {m.name}"]
                t = t.replace(old, new)
                hit = True
            p = Path(tmp.name) / m.name
            p.write_text(t, encoding="utf-8")
            migs.append(p)
    else:
        sql = brk
    st = stack.LocalStack(extra_pgrst=extra)
    try:
        st.prepare_db(migrations=migs)
        if sql:
            c = psycopg.connect(st.db_uri, autocommit=True)
            c.execute(sql)
            c.close()
        st.start_postgrest()
        sec = st.secret
        register_secret(sec)
        toks = {r: mint(sec, user_claims(u)) for r, u in (("owner", OWNER), ("manager", MANAGER), ("staff", STAFF), ("stranger", STRANGER))}
        X = Ctx(local=True, rest=st.base, anon_key=mint(sec, anon_claims()), tokens=toks, db=psycopg.connect(st.db_uri, autocommit=True), secret=sec, stack=st)
        res = runner.run(X, "local", only, log=lambda *_: None)
        failed = [r["id"] for r in res if r["status"] == "FAIL"]
        return ("CAUGHT" if failed else "SURVIVED"), failed
    finally:
        st.stop()
        if tmp:
            tmp.cleanup()


def main() -> int:
    which = set(sys.argv[1:])
    survived = 0
    for i, (label, only, brk) in enumerate(BREAKS, 1):
        if which and str(i) not in which:
            continue
        verdict, failed = run_one(label, only, brk)
        print(f"{i:2}. {verdict:8} {label}   [{', '.join(failed) if failed else '-'}]")
        survived += verdict != "CAUGHT"
    print(f"\n{len(BREAKS) - survived if not which else 'selected'} caught, {survived} not caught")
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
