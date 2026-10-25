# O4U backend (development only)

Supabase-compatible PostgreSQL: catalogue, size-level stock, an append-only stock ledger, the website-order lifecycle,
counter-sale (POS) foundations, role enforcement, a scheduler for expiring holds, and public-surface hardening. Not connected
to anything real; synthetic data only. Design and status: `Claude outputs/O4U_Order_Operations_Design.md`.

```
migrations/0001_core.sql                       schema and every function (untouched since the first commit)
migrations/0002_real_auth.sql                  staff keyed by Supabase auth user id, onboarding, privilege lockdown
migrations/0003_expire_holds_hardening.sql     expire_holds safe for 2 schedulers / one bad order / a stuck lock
migrations/0004_expire_holds_schedule.sql      pg_cron every minute; harmless no-op where pg_cron cannot run
migrations/0005_public_hardening_and_trust_flag.sql   order-ref check digits, per-phone rate limit, stock-trust flag
migrations/0006_shared_barcodes_opening_balance.sql   shared barcodes (scan never guesses), opening-balance import, count-pending flag, FREE=Free
importer/stockroom_import.py                   plan/apply a Stockroom backup into a DEV database (dry run by default; counts only)
seed/onboard_staff.sql                         how the owner puts real people on the staff list (placeholders only)
seed/dev_seed_synthetic.sql                    INVENTED catalogue + opening stock for a hosted DEV project (refuses non-dev data)
seed/dev_smoke_test.sql                        plays website/staff/manager/owner on the dev project; last grid = PASS/FAIL per check
functions/expire-holds/index.ts                fallback scheduler (Supabase Edge Function), code only, not deployed
tests/supabase_shim.sql                        TEST ONLY: Supabase roles, auth.uid(), auth.users, default privileges
tests/pgcluster.py                             starts throwaway PostgreSQL clusters (OS PostgreSQL, optional pg_cron)
tests/run_db_tests.py                          the checks (60 on Linux with pg_cron and node; 57 + 3 skips on Windows; the run prints the real count)
tests/run_mutations.py                         breaks the SQL on purpose, 27 ways, and confirms the checks notice
```

Migrations are applied in file order. 0002-0006 are idempotent (safe to run again); 0001 is not (it creates tables) and
refuses a second run. 0002+ need Supabase's `auth` schema.

## Run the checks

Linux with an OS PostgreSQL (what the results in the design doc used):

```
sudo apt-get install postgresql-16 postgresql-16-cron        # server + pg_cron (any 15+ works; 17 matches current Supabase)
python3 -m venv /tmp/venv && /tmp/venv/bin/pip install "psycopg[binary]"
/tmp/venv/bin/python backend/tests/run_db_tests.py           # ~30 s; one check waits for pg_cron's next minute
O4U_SKIP_SLOW=1 /tmp/venv/bin/python backend/tests/run_db_tests.py   # skips that wait
/tmp/venv/bin/python backend/tests/run_mutations.py          # ~10 min: 27 deliberate breakages
```

As root the runner starts PostgreSQL as the `postgres` OS user. `O4U_PG_BIN=/path/to/bin` picks another install.
`O4U_ONLY=<substring>` runs matching checks only. Without an OS PostgreSQL it falls back to `pip install pgserver`
(no pg_cron: the cron checks report SKIP, never PASS). A check that cannot run says SKIP; nothing is reported as passed unless it ran.

## Real auth (0002)

Supabase Auth issues each person a JWT. PostgREST verifies it and, per request, does `SET LOCAL ROLE authenticated` and sets
`request.jwt.claims`; `auth.uid()` is the JWT's `sub` = `auth.users.id`. `staff.user_id` is that id (foreign key, deleted
with the account). A person is staff only while their staff row is active AND their auth account is neither deleted nor
banned. Nothing in the token (`user_metadata`, e-mail, custom claims) can raise a rank. The last active owner cannot be
removed. Put people on the list with `onboard_staff_by_email` - see `seed/onboard_staff.sql`.

## Scheduling expire_holds

Primary: `0004` schedules `select public.expire_holds()` every minute with pg_cron (job `o4u-expire-holds`) plus a daily
job trimming pg_cron's run history. It does nothing, with a NOTICE, if pg_cron is not installed or not loaded, and with a
WARNING if scheduling fails for any other reason. After applying it on a real project, check:

```
select jobname, schedule, active from cron.job;                       -- two o4u-* rows
select status, return_message, start_time from cron.job_run_details order by start_time desc limit 5;
```

Fallback (no pg_cron): deploy `functions/expire-holds` as a Supabase Edge Function (`--no-verify-jwt`), set the secret
`EXPIRE_HOLDS_SECRET`, and call it every minute from any scheduler you trust (a Supabase scheduled function/cron, GitHub
Actions cron is only 5-minute granularity, or an external cron) with `POST` and header `x-o4u-cron: <secret>`. Running two
schedulers together is safe. Not deployed or tested in the sandbox.

Watching it: `overdue_holds()` (manager) lists holds past their time; `stock_trust_status()` shows the counts as warnings.

## What the owner must do to get a hosted development project (steps only - nothing here creates one)

1. Create a Supabase account and a NEW project used only for development (not the shop's live data). Pick the Postgres
   version it offers by default (the CLI's current default is 17).
2. Dashboard > Database > Extensions: confirm `pg_cron` can be enabled (migration 0004 enables it itself when allowed).
3. Dashboard > Authentication: create the owner user (strong password, then enable MFA), then the manager and staff users.
4. SQL editor: paste and run `migrations/0001` ... `0005` in order. Read any NOTICE/WARNING from 0004.
5. SQL editor: edit the e-mails and names in `seed/onboard_staff.sql` (locally, not in git) and run it.
6. Run the pg_cron check queries above; place one synthetic order through the API and watch it expire.
7. Keep the anon key (public) and the service-role key (secret) out of git; the service-role key never goes in a web page.
8. Only after those pass, decide about wiring the website and Stockroom (separate approval).

Rules this code must keep: stock changes only through `apply_stock_event`; every mutating function takes an
idempotency key; money is integer paise; nothing here is applied to a real project without the owner's approval.

## Real-backup constraints (migration 0006 and the importer)

Found by checking the live Stockroom's backup (25 Oct 2026); the backup itself is private and never in git.
- One printed barcode can belong to several colours. `variant_barcodes` holds every owner; `lookup_barcode()` lists them; `complete_sale` sells by
  `variant_id` and refuses an ambiguous barcode ("choose the colour"). Nothing is ever merged.
- Opening stock is one `opening_balance` ledger row per size (`import_opening_balance`, service role only, all-or-nothing, idempotent). No sale, receipt
  or movement is invented, and a variant that already has history is refused.
- Quantities come from the live `stock` map only. Sizes whose old size-row quantity disagrees (and every size of a product whose `inStock` flag disagrees)
  are imported with `count_pending`: the website reads "Check availability", no website hold can be placed, and a manager's `recount_stock` clears it.
  Counter sales of such items warn (`app_settings.pending_blocks_counter_sales = 1` makes them refuse).
- `FREE` and `Free` are one size (case-insensitive match; unique per product).
- Dry run on a backup: `python backend/importer/stockroom_import.py <backup.zip>` prints counts only and writes nothing.
