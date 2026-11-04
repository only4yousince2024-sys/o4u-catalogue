"""Mutation check: deliberately break the SQL, one way at a time, and confirm run_db_tests.py notices.

    python backend/tests/run_mutations.py            # all mutations (about 20 s each)
    python backend/tests/run_mutations.py 3 7        # only mutations number 3 and 7

Each mutation edits a COPY of the migrations in a temp folder (the real files are never touched) and runs the full check
suite against it with O4U_MIGRATIONS_DIR. CAUGHT = at least one check failed (names printed); HUNG = the suite did not
finish in time (also a detection, but a clumsy one); SURVIVED = every check still passed -> a gap in the tests, reported.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MIG = HERE.parent / "migrations"

MUTATIONS = [
    # (name, file, old, new)
    ("0003 expire_holds: take rows without SKIP LOCKED (second scheduler waits on the first)", "0003", "           for update skip locked\n", "           for update\n"),
    ("0003 expire_holds: no per-order sub-transaction (one bad order aborts the whole run)", "0003", "    exception when others then\n      insert into expiry_failures", "    exception when no_data_found then\n      insert into expiry_failures"),
    ("0003 expire_holds: no lock_timeout (a held lock hangs the scheduler)", "0003", " set lock_timeout = '3s' as $$", " as $$"),
    ("0003 expire_holds: drop the 'has a verified payment' guard", "0003", "             and not exists (select 1 from payments p where p.order_id = orders.id and p.kind = 'payment')\n           order by hold_until", "           order by hold_until"),
    ("0003 expire_holds: forget to release the stock", "0003", "      perform release_lines(o.id, 'hold expired');\n", ""),
    ("0004 schedule: every hour instead of every minute", "0004", "'* * * * *', 'select public.expire_holds()'", "'0 * * * *', 'select public.expire_holds()'"),
    ("0004 schedule: job calls the wrong function", "0004", "'select public.expire_holds()'", "'select 1'"),
    ("0004 schedule: skip the 'not loaded' guard (relies on the exception handler alone)", "0004", "  if preload is not null and preload not like '%pg_cron%' then\n    raise notice 'o4u: pg_cron is installed but not loaded (shared_preload_libraries) - expire_holds() is NOT scheduled here';\n    return;\n  end if;\n", ""),
    ("0002 current_role_rank: ignore the staff.active flag", "0002", "  where s.user_id = auth.uid() and s.active\n    and not exists", "  where s.user_id = auth.uid()\n    and not exists"),
    ("0002 current_role_rank: ignore banned / deleted auth accounts", "0002", "    and not exists (select 1 from auth.users u where u.id = s.user_id and (u.deleted_at is not null or u.banned_until > now()))\n", ""),
    ("0002 current_role_rank: everyone signed in counts as staff rank 1", "0002", "  where s.user_id = auth.uid() and s.active\n", "  where s.active\n"),
    ("0002 staff.user_id no longer tied to auth.users", "0002", "foreign key (user_id) references auth.users(id) on delete cascade", "foreign key (user_id) references staff(user_id) on delete cascade"),
    ("0002 drop the last-owner trigger", "0002", "create trigger staff_keep_one_owner before update or delete on staff for each row execute function keep_one_owner();", ""),
    ("0002 onboarding callable by signed-in users", "0002", "revoke all on function keep_one_owner(), onboard_staff(uuid,text,text), onboard_staff_by_email(text,text,text), deactivate_staff(uuid) from public, anon, authenticated;", ""),
    ("0002 forget to close sequences", "0002", "revoke all on all sequences in schema public from public, anon, authenticated;", ""),
    ("0002 default privileges for tables left open", "0002", "alter default privileges in schema public revoke all on tables    from anon, authenticated;", ""),
    ("0005 check digits: wrong FNV prime", "0005", "* 16777619)", "* 16777618)"),
    ("0009 check digits: validation removed from place_order_request", "0009", "    if right(p_ref, 2) <> o4u_check(", "    if false and right(p_ref, 2) <> o4u_check("),
    ("0005 check digits: size normalisation dropped (2XL stays 2XL)", "0005", "when '2XL' then 'XXL' ", "when '2XL' then '2XL' "),
    ("0009 rate limit: per-phone advisory lock removed (race)", "0009", "  perform pg_advisory_xact_lock(hashtextextended('o4u-order-phone:' || p_phone, 0));\n", ""),
    ("0009 rate limit: off by one (> instead of >=)", "0009", "created_at > now() - interval '1 hour') >= setting('rate_phone_per_hour')", "created_at > now() - interval '1 hour') > setting('rate_phone_per_hour')"),
    ("0009 rate limit: daily limit forgotten", "0009", "\n     or (select count(*) from orders where phone = p_phone and created_at > now() - interval '1 day') >= setting('rate_phone_per_day') then", " then"),
    ("0005 trust flag: store_ping stops recording outages", "0005", "    insert into store_outages (kind, started_at, ended_at) values ('heartbeat_gap', prev, now());", "    null;"),
    ("0005 trust flag: reconcile allowed while the shop app is silent", "0005", "  if st.offline_switch or st.last_heartbeat is null or st.last_heartbeat <= now() - make_interval(mins => setting('heartbeat_stale_minutes')) then\n    raise exception 'the shop app is not reporting yet: reconcile after it is back online';\n  end if;\n", ""),
    ("0005 trust flag: reconcile open to any staff, not just managers", "0005", "  perform require_role('manager');\n  prev := idem_begin(p_idem_key, 'reconcile_outages');", "  perform require_role('staff');\n  prev := idem_begin(p_idem_key, 'reconcile_outages');"),
    ("0005 trust flag: unreconciled outage no longer lowers trust", "0005", "if unrec > 0 and fresh and not st.offline_switch then", "if false and unrec > 0 and fresh and not st.offline_switch then"),
    ("0005 stock_trust_status left executable by the public", "0005", "revoke all on function stock_trust_status(), reconcile_outages(text,text), o4u_check(text,jsonb) from public, anon, authenticated;", ""),
    ("0009 rate limit refusals back to the old code P0429 (HTTP 500 for the customer)", "0009", "wait a while or message the shop on WhatsApp' using errcode = 'PT429';", "wait a while or message the shop on WhatsApp' using errcode = 'P0429';"),
    ("0009 payment reports no longer capped per order", "0009", ">= setting('max_payment_reports_per_order') then", ">= setting('max_payment_reports_per_order') + 1000000 then"),
    ("0009 name length limit removed", "0009", "if char_length(trim(p_name)) > 100 then", "if false then"),
    ("0009 control characters allowed in customer text", "0009", "if p_name ~ '[\\x01-\\x1f\\x7f]' or p_address ~ '[\\x01-\\x1f\\x7f]' or coalesce(p_landmark,'') ~ '[\\x01-\\x1f\\x7f]' then", "if false then"),
    ("0009 internal helpers stay executable by the service role", "0009", "  from public, anon, authenticated, service_role;", "  from public, anon, authenticated;"),
    ("0009 claimed payment amount unbounded", "0009", "if p_claimed_paise is not null and (p_claimed_paise < 0 or p_claimed_paise > 100000000) then", "if false then"),
    ("0009 oversized request body accepted", "0009", "if p_lines is not null and octet_length(p_lines::text) > 20000 then", "if false then"),
    # ---- 0010 atomic stock moves
    ("0010 replay of a key with different contents is accepted", "0010", "    if prev->>'_req' is distinct from req then raise exception 'idempotency key already used with different contents'; end if;\n", ""),
    ("0010 recount no longer checks what the counter saw", "0010", "      if cur <> exp then raise exception 'stock changed while counting: the rack was % when you started, it is % now', exp, cur using errcode = 'P0001'; end if;\n", ""),
    ("0010 no free-stock check (relies on the table constraint alone)", "0010", "      if chg < 0 and cur - rsv < -chg then\n        raise exception 'only % free to take off (% on hand, % held for customers)', greatest(cur - rsv, 0), cur, rsv using errcode = 'P0001';\n      end if;\n", ""),
    ("0010 stock changed without a ledger row (bypasses apply_stock_event)", "0010", "      perform apply_stock_event(v, kind, chg, 0, null, null, coalesce(nullif(e->>'reason',''), nullif(p_reason,''), kind));", "      update stock_levels set on_hand = on_hand + chg where variant_id = v;"),
    ("0010 the answer is never stored (replay finds an unfinished key)", "0010", "  perform idem_end(p_idem_key, jsonb_build_object('moves', res, '_req', req));\n", ""),
    ("0010 stock rows not locked before the checks", "0010", "  perform lock_stock_rows(vids);\n", ""),
    ("0010 staff may recount", "0010", "  if exists (select 1 from jsonb_array_elements(p_moves) m where m->>'kind' = 'recount') then perform require_role('manager'); end if;\n", ""),
    ("0010 the public may call apply_stock_moves", "0010", "grant execute on function apply_stock_moves(text, jsonb, text) to authenticated;", "grant execute on function apply_stock_moves(text, jsonb, text) to anon, authenticated;"),
]


def main() -> int:
    wanted = {int(a) for a in sys.argv[1:]}
    results = []
    for n, (name, prefix, old, new) in enumerate(MUTATIONS, 1):
        if wanted and n not in wanted:
            continue
        tmp = Path(tempfile.mkdtemp(prefix="o4u-mut-"))
        try:
            for f in MIG.glob("*.sql"):
                shutil.copy(f, tmp / f.name)
            target = next(tmp.glob(f"{prefix}_*.sql"))
            text = target.read_text(encoding="utf-8")
            if text.count(old) != 1:
                results.append((n, name, "BAD MUTATION", [f"pattern found {text.count(old)} times"]))
                continue
            target.write_text(text.replace(old, new), encoding="utf-8")
            env = dict(os.environ, O4U_MIGRATIONS_DIR=str(tmp), O4U_SKIP_SLOW="1")
            try:
                r = subprocess.run([sys.executable, str(HERE / "run_db_tests.py")], env=env, capture_output=True, text=True, timeout=240)
                out = r.stdout
                fails = re.findall(r"^  FAIL  (.+)$", out, re.M)
                if r.returncode != 0 and fails:
                    results.append((n, name, "CAUGHT", fails))
                elif r.returncode != 0:
                    results.append((n, name, "CAUGHT (suite aborted)", [out.strip().splitlines()[-1] if out.strip() else r.stderr.strip().splitlines()[-1]]))
                else:
                    results.append((n, name, "SURVIVED", []))
            except subprocess.TimeoutExpired:
                results.append((n, name, "HUNG", ["suite did not finish in 240 s"]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        n_, name_, verdict, why = results[-1]
        print(f"[{n_:2d}] {verdict:22s} {name_}" + (f"\n        by: {'; '.join(why[:3])}" if why else ""), flush=True)
    caught = sum(1 for r in results if r[2].startswith("CAUGHT") or r[2] == "HUNG")
    print(f"\n{caught} of {len(results)} mutations detected; survived: {[r[0] for r in results if r[2] == 'SURVIVED']}; bad patterns: {[r[0] for r in results if r[2] == 'BAD MUTATION']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
