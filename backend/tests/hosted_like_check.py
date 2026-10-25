"""Do migrations 0001-0006 + the dev seed + the dev smoke test work on something shaped like a HOSTED Supabase project?

    python backend/tests/hosted_like_check.py

Throwaway local PostgreSQL, invented data only. Differences from run_db_tests.py, on purpose:
  * the runner is a NON-superuser owner (like Supabase's `postgres`), so statements that quietly relied on superuser rights fail here;
  * new tables/functions are NOT exposed to anon/authenticated/service_role by default ("Automatically expose new tables" off);
  * an event trigger switches row-level security on for every new table in public ("Automatic RLS" on).
It proves the SQL applies and behaves under those settings. It does NOT prove PostgREST, real JWT verification, the dashboard SQL editor,
pg_cron on Supabase, or anything about Supabase's own Postgres build: those need the real project.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import pgcluster  # noqa: E402
import run_db_tests as T  # noqa: E402  (only for the allowlists of what each role may reach)

FAILS = []


def check(ok, msg, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {msg}" + (f"  -- {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(msg)


def run_script(conn, path, notices):
    cur = conn.execute(path.read_text(encoding="utf-8"))
    last = None
    while True:
        if cur.description:
            last = cur.fetchall()
        if not cur.nextset():
            break
    return last


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    cl = pgcluster.make_cluster(preload_cron=False)
    try:
        su = psycopg.connect(cl.uri, autocommit=True)
        print("Database:", su.execute("select version()").fetchone()[0].split(",")[0])
        su.execute((HERE / "supabase_shim_restricted.sql").read_text(encoding="utf-8"))
        own = psycopg.connect(make_conninfo(cl.uri, user="supa_owner"), autocommit=True)
        check(own.execute("select not rolsuper and rolbypassrls from pg_roles where rolname = current_user").fetchone()[0], "runner is a non-superuser with BYPASSRLS (like Supabase's postgres)")
        notices = []
        own.add_notice_handler(lambda d: notices.append(f"{d.severity}: {d.message_primary}"))
        for m in sorted((ROOT / "migrations").glob("*.sql")):
            try:
                own.execute(m.read_text(encoding="utf-8"))
                check(True, f"{m.name} applies")
            except psycopg.Error as e:
                check(False, f"{m.name} applies", f"{e.diag.sqlstate}: {e.diag.message_primary}")
                break
        # the 0004 hazard found by this check: a non-superuser cannot read shared_preload_libraries
        try:
            own.execute("select current_setting('shared_preload_libraries', true)")
            check(False, "premise: the runner cannot read shared_preload_libraries (needed to prove the 0004 guard)")
        except psycopg.errors.InsufficientPrivilege:
            check(True, "premise holds: a non-superuser gets 'permission denied' reading shared_preload_libraries")
        guard = (ROOT / "migrations" / "0004_expire_holds_schedule.sql").read_text(encoding="utf-8")
        check("exception when insufficient_privilege" in guard and guard.index("exception when insufficient_privilege") < guard.index("create extension"),
              "0004 survives an unreadable shared_preload_libraries instead of aborting")
        print("  notices:", *[n for n in notices if "o4u" in n], sep="\n    ")

        # re-applying 0002-0006 over a live schema must change nothing
        try:
            for m in sorted((ROOT / "migrations").glob("*.sql"))[1:]:
                own.execute(m.read_text(encoding="utf-8"))
            check(True, "0002-0006 re-apply cleanly")
        except psycopg.Error as e:
            check(False, "0002-0006 re-apply cleanly", f"{e.diag.sqlstate}: {e.diag.message_primary}")

        # security shape under the hosted-like settings
        rls_off = [r[0] for r in su.execute("select relname from pg_class where relnamespace='public'::regnamespace and relkind='r' and not relrowsecurity").fetchall()]
        check(not rls_off, "every table has row-level security on", str(rls_off))
        rows = su.execute("""select p.proname, has_function_privilege('anon', p.oid, 'execute'), has_function_privilege('authenticated', p.oid, 'execute'),
                                    has_function_privilege('service_role', p.oid, 'execute')
                             from pg_proc p where p.pronamespace = 'public'::regnamespace and p.prokind = 'f'""").fetchall()
        anon = {r[0] for r in rows if r[1]}
        auth_ = {r[0] for r in rows if r[2]}
        svc = {r[0] for r in rows if r[3]}
        check(anon == T.EXPECTED_ANON_FUNCS, "anon reaches exactly the three public functions", str(sorted(anon ^ T.EXPECTED_ANON_FUNCS)))
        check(auth_ == T.EXPECTED_AUTH_FUNCS, "signed-in users reach exactly the documented functions", str(sorted(auth_ ^ T.EXPECTED_AUTH_FUNCS)))
        check(T.EXPECTED_SERVICE_ONLY <= svc and not (T.EXPECTED_SERVICE_ONLY & auth_), "scheduler/onboarding/import functions are service-role only")
        pub = su.execute("""select p.proname from pg_proc p where p.pronamespace = 'public'::regnamespace and p.prokind = 'f'
                            and exists (select 1 from aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a where a.grantee = 0 and a.privilege_type = 'EXECUTE')""").fetchall()
        check(not pub, "no function is executable by PUBLIC", str(pub))
        t = su.execute("""select c.relname, has_table_privilege('anon', c.oid, 'select,insert,update,delete,truncate,references,trigger'),
                                 has_table_privilege('authenticated', c.oid, 'insert,update,delete,truncate,references,trigger'), has_table_privilege('authenticated', c.oid, 'select'),
                                 has_table_privilege('service_role', c.oid, 'select,insert,update,delete,truncate,references,trigger')
                          from pg_class c where c.relnamespace = 'public'::regnamespace and c.relkind = 'r'""").fetchall()
        check(not [r[0] for r in t if r[1]], "anon has no table access", str([r[0] for r in t if r[1]]))
        check(not [r[0] for r in t if r[2]], "signed-in users cannot write any table", str([r[0] for r in t if r[2]]))
        check({r[0] for r in t if r[3]} == T.EXPECTED_AUTH_SELECT, "signed-in users can read exactly the documented tables", str({r[0] for r in t if r[3]} ^ T.EXPECTED_AUTH_SELECT))
        check(not [r[0] for r in t if r[4]], "the service role has NO table privileges at all, not even TRUNCATE (it works only through the functions)", str([r[0] for r in t if r[4]]))

        # seed + smoke through the non-superuser session (what the SQL editor does)
        for role in ("owner", "manager", "staff"):
            uid = str(uuid.uuid4())
            su.execute("insert into auth.users (id, email) values (%s, %s)", (uid, f"{role}@example.invalid"))
            own.execute("select onboard_staff(%s, %s, %s)", (uid, f"Dev {role}", role))
        seed = run_script(own, ROOT / "seed" / "dev_seed_synthetic.sql", notices)
        check(seed == [(7, 13, 30, 1, 13)], "seed loads 7 products, 13 variants, 30 pieces, 1 count-pending, 13 opening rows", str(seed))
        again = run_script(own, ROOT / "seed" / "dev_seed_synthetic.sql", notices)
        check(again == seed, "seed is safe to run twice")
        for i in (1, 2):
            res = run_script(own, ROOT / "seed" / "dev_smoke_test.sql", notices)
            bad = [r for r in res if r[2] != "PASS" and "pg_cron job present" not in r[1]]
            check(len(res) >= 30 and not bad, f"smoke test run {i}: {sum(r[2] == 'PASS' for r in res)} of {len(res)} PASS (pg_cron row expected to FAIL here)", str(bad))
    finally:
        cl.cleanup()
    print(f"\n{'ALL PASSED' if not FAILS else str(len(FAILS)) + ' FAILED'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
