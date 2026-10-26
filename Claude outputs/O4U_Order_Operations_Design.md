# O4U — Automated order operations: design and implementation report

Branch `dev/backend-synthetic` · 25 Oct 2026 · development only, synthetic data only · nothing deployed, nothing pushed

Legend: **BUILT** = written in `backend/migrations/0001_core.sql` · **TESTED** = exercised by `backend/tests/run_db_tests.py` on a throwaway PostgreSQL 16 (33 checks at first, 54 now: see section 11) · **PLANNED** = not written.

## 1. What Stockroom v44 already does (read from its source, not rebuilt)

| Step | In Stockroom today |
|---|---|
| Bill agreed | `confirm` needs a delivery charge; moves request → confirmed |
| Hold stock | `reserve`: re-checks stock, 2-hour hold, status awaiting_payment |
| Payment | `pay`: staff enter the UPI reference and time; duplicate reference refused |
| Release / cancel | manual `release` (back to request) and `cancel` |
| Pack / dispatch | `pack`; `dispatch` takes the pieces off the rack at that moment, once |
| Failed / resend / delivered / collected | present |
| No rider in 24 h | `norider` → refund due → refund recorded by a person |
| Changes and exchanges | `change_due` and the Exchanges cases |
| Pasting an order | the `O4U ORDER` block; `w-<code>` document ids make a re-paste harmless |

## 2. What needs new backend logic (none of this exists in v44)

| Need | Why Stockroom cannot do it today |
|---|---|
| Order arrives by itself | Stockroom only reads orders when someone pastes them |
| Atomic reservation | Stockroom has no transactions; it uses 8-second leases and re-reads |
| Automatic expiry | Holds are only released by hand |
| Live availability for the website | no feed exists |
| Late payment after expiry | not handled |
| Customer-reported payment | not distinguished from verified payment |
| Real roles | the "Working as" box is honour-system |
| Outage safety | none |
| Counter sales, receipts, barcode lines | sales are logged as stock moves only |
| Owner revenue from recorded money | derived from stock moves, not from a payment ledger |

## 3. The action-driven state machine

Status values: `request → awaiting_payment → paid → packed → dispatched → delivered`, with side states `hold_expired`, `failed`, `refund_due`, `refunded`, `cancelled`.

| Staff taps | From | To | Happens automatically, in one transaction | Who |
|---|---|---|---|---|
| **Confirm & Reserve** | request, hold_expired | awaiting_payment | records delivery + any discount as the **agreed** bill; re-checks every line; reserves all lines or none; starts the 2 h hold; availability drops; audit rows | staff (discount: manager) |
| **Payment verified** | awaiting_payment, hold_expired | paid | writes one verified payment row (method, amount, UPI ref, time, who); lifts the expiry; amount must equal the agreed bill; same UPI ref cannot be used twice | staff |
| **Pack** (optional) | paid | packed | audit row | staff |
| **Dispatch** | paid, packed, failed | dispatched | pieces leave the rack **once**, hold released, ledger rows, tracking saved; re-send after a failed delivery deducts nothing | staff |
| Delivered / Delivery failed | dispatched (failed) | delivered / failed | audit row | staff |
| Release hold | awaiting_payment | request | stock returns | staff |
| Cancel | request, awaiting_payment, hold_expired | cancelled | stock returns; paid orders are refused | staff |
| Approve refund | paid, packed, failed | refund_due | hold released by an explicit decision; refund row stays **due** | manager |
| Mark refund sent | refund_due | refunded | needs the UPI reference of the refund; only this completes a refund | manager |
| *(scheduler)* Expire holds | awaiting_payment, unpaid, past time | hold_expired | stock released; never touches paid, packed or dispatched orders | system |

"Confirmed" is no longer a resting status: Stockroom's confirm step and reserve step are one tap, and both audit rows are still written. Every other transition keeps Stockroom's rules; a test compares the allowed-transition table with the pairs read from v44. **Not ported yet:** the `change_due` change/exchange flow (PLANNED).

**Late payment (D4, needs the owner's decision).** If money arrives after the hold expired: stock still free → re-held and paid; stock gone → the money is recorded, the order becomes `refund_due`, the refund stays due for a person to complete. A customer's "I have paid" is recorded as information only and extends the hold **once**, by 60 minutes, then never again.

## 4. Three amounts, never conflated

| Amount | Column | Set by |
|---|---|---|
| Website preliminary total | `items_paise` | server, from catalogue prices (the page's prices are ignored) |
| Staff-agreed final bill | `agreed_paise` (= items − discount + delivery) | staff at Confirm & Reserve |
| Amount actually paid | `paid_paise` + `payments` rows | staff at Payment verified |

The site never calculates delivery; it is `null` until a person enters it.

## 5. Built for the future POS (no screen yet)

`complete_sale()` takes scanned barcodes or product + size, quantities, line and bill discounts (manager only), split cash/UPI payments that must equal the bill. In one transaction it creates the sale, deducts stock once (only **free** pieces, never ones held for a website customer), writes the stock ledger and the payment rows, and issues a receipt number. `get_receipt()` returns the receipt data. Retries with the same key return the same sale. Returns go through `return_to_stock()` (manager, never more than was sold). Website and counter sales are separate channels in the owner summary. Printing, invoices with tax, the screen and barcode hardware are PLANNED.

## 6. Who sees what (enforced in the database)

- **Public website:** three functions only (`get_availability`, `place_order_request`, `report_payment`). No table can be read.
- **Staff:** run the order actions, read orders and stock. Cannot read payments or sales totals.
- **Manager (Dad):** adds discounts, approves refunds, recounts, restocks returns, sees the money ledger; cannot see the owner summary.
- **Owner (Khush):** everything, plus `owner_sales_summary` (verified revenue and refunds actually recorded, website vs counter).
- Nobody can write a table directly; stock, order and payment history rows cannot be changed or deleted.

## 7. Outage rule

The shop app pings every minute (`store_ping`). If no ping for 3 minutes, or a manager flips the offline switch, every size on the website reads "Check availability". PLANNED: the shop app doing the pinging, and a banner in Stockroom saying stock cannot be trusted until reconciled.

## 8. Test results (run on 25 Oct 2026)

`33 passed, 0 failed` — PostgreSQL 16.2, throwaway database, invented products/customers/orders only.

Covered: request ≠ sale; catalogue pricing; duplicate submissions (five at once); availability labels and outage; the whole lifecycle; Stockroom rule parity; discounts and delivery; two customers for the last piece (15 rounds); eight orders for three pieces; opposite line order (no deadlock); counter sale vs website hold; expiry; paid stock never released; customer-reported payment; payment-vs-expiry race (30 runs plus a deterministic lock test); late payment both ways; replays and double taps; shared UPI reference; failed reservation leaves nothing and retries; negative stock; immutable audit; cancellation; refunds by people only; returns; POS sale, split payment, receipt; owner numbers; anonymous and role access.

After every check an invariant sweep confirms the stock ledger explains every shelf count, reserved stock matches the orders that hold it, and nothing is negative.

**Do the tests detect breakage?** I broke the SQL on purpose six ways. Five were caught (removing the stock-row lock, the free-stock check, the dispatch-once guard, the customer-report rule, both paid-order expiry guards). Removing `skip locked` made the deterministic expiry test **hang** instead of failing cleanly. One weaker mutation (only one of the two paid-order guards) was not caught, because the other guard still protects.

**What this does not prove**
- The 30-run payment-vs-expiry race ended with expiry winning every time; the other ordering is covered only by the deterministic lock test.
- Tests ran on a standalone PostgreSQL 16.2 for Windows with a stand-in for Supabase's `auth.uid()`. Real Supabase (its Postgres version, PostgREST, real JWTs, `pg_cron`) is untested.
- No load test beyond a few concurrent connections.

## 9. Still planned

Supabase project and real auth users · scheduler for `expire_holds` (verify `pg_cron` or an Edge Function on the chosen plan) · website `AVAILABILITY.url` and order submission · Stockroom reading orders live, in-app alert for new requests · change/exchange flow · POS screen, barcode scanner, receipt printing, tax invoices · shop-app heartbeat and reconciliation banner · order-reference check-digit validation on the server · rate-limiting and abuse protection for the public functions · partial and over-payments · negotiated amounts after the bill is agreed · production migration (separate approval).

## 10. Decisions needed

1. **D4 — late payment:** is "re-hold if free, otherwise refund due" right?
2. **Grace period:** is one 60-minute extension after "I have paid" right?
3. **Roles:** Dad = manager (can discount, refund, recount; cannot see revenue). Khush = owner. Confirm.
4. **Push:** still waiting on the Netlify branch-deploy check before pushing this branch.

## 11. Cloud session results (25 Oct 2026)

Branch `dev/backend-synthetic`, development only, synthetic data only. Nothing was pushed to master, no pull request was opened, no Supabase account or project was created or contacted, no credential was handled, `website/` and `stockroom/` were not modified (the website's `index.html` was only read, to cross-check `o4uCheck`).

**Test environment.** Real Linux PostgreSQL **16.15** (Ubuntu 24.04 package, `initdb` + `pg_ctl`, started as the `postgres` OS user) with pg_cron **1.6.2** loaded. Current Supabase projects default to Postgres **17** (the Supabase CLI 2.122.0 `config.toml` says `major_version = 17`), but the PostgreSQL project's apt repository is blocked in this sandbox, so **17 was not tested**; 16 is the closest available major. The Supabase CLI installed (npm) and Docker's daemon started, but `supabase start` could not run: the registry refused the image downloads ("Data limit exceeded" / 403 from the sandbox proxy). So **no local Supabase stack was run**; Supabase behaviour is imitated by `tests/supabase_shim.sql` (copies `auth.uid()`'s claim lookup, `auth.users`, the roles, the `authenticator` login and Supabase's default privileges) and is still unproven against the real thing.

**Built (migrations; 0001 untouched, 0002-0005 re-runnable).**
- **0002 real auth:** `staff.user_id` is a foreign key to `auth.users` (removed with the account); rank requires an active staff row and an account that is not deleted/banned; JWT metadata can never raise a rank; actor names (`system` / staff name / `unregistered user`); RLS policies wrapped in sub-selects; the last active owner cannot be removed; `onboard_staff`, `onboard_staff_by_email`, `deactivate_staff` (service role only) and `seed/onboard_staff.sql` (placeholders only). While testing, the privilege audit found that 0001 left **sequences** reachable by `anon`/`authenticated` under Supabase's default grants and that new tables/functions would be open by default; 0002 closes both and each later migration revokes new functions explicitly.
- **0003 + 0004 expiry:** `expire_holds()` takes rows with `SKIP LOCKED`, isolates each order in its own sub-transaction (one bad order cannot block the rest; failures go to `expiry_failures`), gives up on a held lock after 3 s, handles 500 orders per run; `overdue_holds()` for managers. 0004 schedules it every minute with pg_cron (plus a daily cleanup of pg_cron's history), is a no-op with a notice/warning where pg_cron is missing, not loaded or not allowed in the database, and is idempotent. Fallback: `backend/functions/expire-holds/index.ts` (Edge Function, **code only, never run**).
- **0005 hardening:** `o4u_check()` (exact port of the website's `o4uCheck`; `place_order_request` now refuses a reference whose check digits do not match the items sent, in order); per-phone limits (5 per hour, 15 per day, race-free) and a site-wide brake (300 per hour), all in `app_settings`; `stock_trust_status()` / `reconcile_outages()` / `store_outages`: the shop-app heartbeat gap or offline switch marks stock untrusted until a manager records what they checked.

**Tested (actual runs, PostgreSQL 16.15):** `54 passed, 0 failed, 0 skipped` in 57 s (33 original + 21 new). All 33 original checks also passed on this PostgreSQL before any migration changed (and again on 0001-0005; the test helpers now build valid reference check digits). New checks cover: JWT-claim lookups via PostgREST-style `SET LOCAL ROLE` (including metadata spoofing, no leakage between pooled requests, deactivated/banned/deleted accounts); a privilege audit of every function, table and sequence against an allowlist; onboarding and the seed file as written; last-owner protection; 2, 2, 4 and 6 simultaneous schedulers over 30 expired holds each (every hold released exactly once, no deadlock); an injected failing order; a stock row locked by another session; a killed run; pg_cron actually firing the job by itself in a separate database; migration idempotence (jobs not duplicated; 0002-0005 re-applied twice over live data leave an identical catalogue fingerprint); a fresh build matching the main database; the pg_cron-less path on a second cluster and a simulated "not installed"; check digits equal on SQL, Python and the website's real JavaScript for 300 random inputs (including non-ASCII ids) plus the `ZP` vector; tampered references refused; a 14-way burst from one phone admits exactly 5 (3 rounds); replays unaffected; and the trust flag through gap, reconcile, offline switch.

**Mutation checks:** 27 deliberate breakages of the new SQL (SKIP LOCKED, sub-transaction, lock timeout, payment guard, release, schedule text, auth guards, privilege revokes, check-digit constant, rate-limit lock/off-by-one/daily limit, trust flag rules and others). **27 of 27 detected.** The first run missed one (removing the "has a verified payment row" guard in `expire_holds`: that state cannot normally occur because a payment changes the status first, so the guard is a second line of defence); a test that forces that impossible state now catches it. Honest caveats: the rate-limit lock mutation was caught by a burst test that is probabilistic by nature (it failed in the one run made); the earlier unmutated runs passed every time they were run (about 6 full runs).

**What these results do not prove.** Postgres 17 and real Supabase (GoTrue tokens, PostgREST, `auth.users` column names such as `banned_until`/`deleted_at`, the actual default grants, the pg_cron build and its database restriction) are untested; the shim copies their documented behaviour. The check digits are two base-31 characters: a typo detector, not security (1 in 961 chance of a collision, which a test tripped over by luck and now avoids). `report_payment` is not rate-limited. No load test beyond a few dozen concurrent connections. The Edge Function was never executed.

**Still planned.** Website `AVAILABILITY.url` and order submission wiring (it must send lines in bag order so the check digits match); Stockroom reading orders live and the shop-app heartbeat plus banner using `stock_trust_status()`; change/exchange flow; POS screen, barcode hardware, receipts, tax invoices; partial/over-payments; rate limiting on `report_payment`; MFA enforcement for the owner role (`aal2`); production migration (separate approval).

**Owner action required (nothing was done on your behalf).** Create the Supabase development project and users and run the migrations following the numbered steps in `backend/README.md`; check that the first real `supabase start`/project run reports the Postgres version and that `cron.job` shows two `o4u-*` rows; D4 (late payment), the 60-minute grace, and the roles in section 10 are still open. If pg_cron turns out to be unavailable on the chosen plan, deploy the Edge Function and pick a scheduler.


## 12. Cloud session results — API (26 Oct 2026)

Branch `dev/backend-synthetic` from `fb2fa4d`, development only, invented data only. Nothing was pushed to `master`, no pull request, no deploy, no Supabase account/project/key/token/password was used or asked for, `website/` and `stockroom/` untouched. Full detail, test matrix and the owner's run plan: `backend/api_tests/README.md`; the error table for the front ends: `backend/api_tests/ERROR_CONTRACT.md` (generated).

**What was built.** A real-HTTP harness: throwaway PostgreSQL 16.15 + the official **PostgREST 12.2.12** binary configured like Supabase (`authenticator` NOINHERIT → `anon`/`authenticated`/`service_role`, `public` exposed, HS256 JWT with a throwaway secret generated per run, per-role statement timeouts), and a second profile with **real GoTrue** (Supabase's auth server, built from source because Docker image pulls are refused in this sandbox: "Data limit exceeded"). So: **no Supabase CLI/Docker stack, no Kong gateway and no Postgres 17 were run.** Suite: 42 checks (A public surface, B roles, C JWT, D formats + idempotency + error contract, E CORS, F abuse/limits, G concurrency), a 30-check real-GoTrue profile, `run_hosted.py` for the owner (23 checks, read-only/always-refused, passwords by hidden prompt, refuses unless every product id starts with `dev-`), `rehearsal_hosted.py`, `selfcheck.py`, a real-browser CORS page and its Chromium run, and migration `0009` with 4 new database checks.

**Results (actual runs).**
| Run | Result |
|---|---|
| database suite before the work (`fb2fa4d`) | 61 passed, 0 failed, 1 skipped |
| database suite now | **66 passed, 0 failed, 0 skipped**; `hosted_like_check.py` ALL PASSED (non-superuser, restricted grants, seed + smoke twice) |
| the 4 new database checks without 0009 | all 4 fail (and the 2 migration-list checks); the other 59 pass |
| mutation checks (`run_mutations.py`) | 34 mutations: 29 detected in the full run; 4 survivors were 0005 rate-limit/check-digit mutations that 0009's replacement of `place_order_request` had made dead code, so they were retargeted at 0009 and are now detected; 1 stale pattern (0004) repaired and detected. Every one of the 34 was individually confirmed detected, 0 survivors (a single uninterrupted 34-way run was not repeated after the retargeting) |
| API suite, migrations 0001-0009, minted tokens | **42 passed, 0 failed, 0 skipped** (about 15 s) |
| API suite on 0001-0008 (`--without-0009`) | 35 passed, **7 failed** = the gaps below |
| API suite with real GoTrue tokens (`--gotrue`) | **30 passed, 0 failed, 0 skipped** (23 repeated + R1-R7) |
| `selfcheck.py` (database broken 18 ways) | **18 of 18** noticed |
| `rehearsal_hosted.py` (fake gateway; and `--gotrue --ban` with real GoTrue sign-in) | 22 / 23 PASS, 0 FAIL, leak scan clean; `--not-dev` refused |
| real Chromium, local PostgREST | 7 of 7 requests readable cross-origin; with CORS restricted to another site all 7 show BLOCKED |

**Passed as designed (executed over HTTP).** Anon reaches exactly `get_availability`, `place_order_request`, `report_payment`; the OpenAPI document lists nothing else; all 20 tables refuse every verb for anon; the 25+3 staff functions answer 403 `42501` to the wrong rank and reach their logic for the right one; staff read no payments/sales/refunds; strangers get empty sets, not errors; nobody writes a table directly; altered/expired/alg-none/wrong-secret tokens are 401; `role` claims (`service_role`, `postgres`, metadata, e-mail) raise nothing; a still-valid token stops working **at once** when the user is banned, soft/hard-deleted (real GoTrue) or the staff row is deactivated, and works again when restored; role changes are immediate; the last owner cannot be removed (GoTrue's own DELETE of the last owner fails); the last piece goes to exactly one of 12 simultaneous HTTP requests (5 rounds), website hold vs counter sale likewise; replayed keys return the stored answer; 24 simultaneous orders from one phone admit exactly 5; unknown reference and wrong phone are byte-identical; 600 brute-force guesses all refused alike.

**Gaps found and fixed (migration `0009_api_abuse_limits.sql`, idempotent, 0001-0008 untouched).**
1. **Limit refusals were HTTP 500.** `P0429` is not a code PostgREST maps, so "please wait a while" reached the customer's browser as a server error. Now `PT429` → HTTP 429, same messages and limits.
2. **Unbounded free text.** A 1 MB name was stored; control/escape characters were stored; a 20 MB request was accepted; a NULL phone surfaced a raw `23502`; a 1 MB idempotency key produced **HTTP 500 `54000`** (index row limit). Now: name 100, address 500, landmark 200, key 100 characters, plain single-line text, lines ≤ 20,000 bytes, all refused with ordinary 400s before anything is stored.
3. **`report_payment` could grow without end** (60 calls → 60 report rows and 60 audit rows, any text, any amount). Now 10 reports per order (429 beyond), reference ≤ 64 characters, amount 0 … ₹10 lakh; inputs that cannot belong to an order get the same `order not found`.
4. **Internal helpers (`apply_stock_event`, `idem_begin`, `log_order` …) were executable by the service role over the Data API.** Revoked; the functions that use them internally still work.
Regression checks for 1-4 are in `run_db_tests.py` (each fails without 0009) and the API suite; 7 new mutations of 0009 are all detected.

**Observed, not changed (need a decision or a front-end rule).**
* PostgREST honours an expired token for ~30 s, ignores `aud`/`iss`, accepts a token without `exp` (only a holder of the signing secret can make such tokens).
* **A stale or expired token breaks PUBLIC calls too** (401 `PGRST301`); the website must send only the anon key for public calls.
* **Sign-out does not cut an access token until it expires** (real GoTrue: the session row is deleted, PostgREST and the database do not look at it). Ban, delete and deactivation do cut at once.
* Self-signup and anonymous sign-in give 'authenticated' tokens; the database gives them nothing (tested), but they should be off.
* A banned or soft-deleted **sole owner** leaves no one with owner rank; the last-owner rule watches the staff table, not account state. Recovery is via the SQL editor.
* No per-caller throttle for `report_payment`/`place_order_request` beyond the stored-order limits: the database cannot see an IP address and failed lookups roll back (cannot be counted). Guess space ≈ 31^6 references × 10^10 phones.
* `23505` errors include internal ids and a UPI reference in `details`; statement timeouts are HTTP 500 `57014`; anonymous callers can tell that a table or column exists (the schema is public here anyway).
* Local PostgREST's CORS echoes any header and answers `*`; **Supabase's gateway CORS was not run** — see the hosted plan.

**Decisions needed from the owner.**
* **A1.** Apply `0009` to the dev project (SQL editor, as for 0008), then run the hosted runner. Until applied, the hosted run will show gaps 1-4.
* **A2.** Switch off "Allow new users to sign up" and "Allow anonymous sign-ins" (Authentication settings) unless a customer account feature is planned.
* **A3.** Sign-out lag: accept it, shorten the JWT expiry (e.g. 15-30 min) in the dashboard, or have me add a session check to `current_role_rank` (a token whose `session_id` no longer exists in `auth.sessions` gets no rank; touches the hot path and every test token) — my recommendation: shorten expiry first, add the check only if staff devices are shared.
* **A4.** Request-rate protection in front of the public functions (IP-level limits need an edge such as Cloudflare/Netlify; the database cannot do it). Is the stored-order limit plus the cap enough for launch?
* **A5.** Confirm the limits are right for real customers (name 100, address 500, landmark 200 characters; one line; 10 payment reports per order; ₹10 lakh maximum claimed).
* **A6.** The front ends adopt `ERROR_CONTRACT.md` (branch on status + code, 429 handling, anon key only on public calls).
* **A7.** Previous open decisions remain: D4 late payment, 60-minute grace, roles, uncounted-stock counter policy, applying 0008.

**What was NOT executed here and needs a local authenticated run on the hosted project** (everything marked so in the README matrix): the real gateway's apikey handling, CORS answers and request-size limits; the real PostgREST version and Postgres 17 behaviour; role/table/function matrices with real hosted sign-in tokens; tamper tests on real hosted tokens; the real-browser CORS page; the banned-user replay on the hosted project. `run_hosted.py` does these, read-only.

**Local execution plan for the owner (about 10 minutes, nothing to install except Python).**
1. `git fetch origin dev/backend-synthetic`, `git checkout dev/backend-synthetic`.
2. Dashboard → SQL editor: paste and run `backend/migrations/0009_api_abuse_limits.sql` (check the pasted text's SHA-256 against the file, as before).
3. PowerShell: `$env:O4U_API_URL="https://<dev-project>.supabase.co"`, `$env:O4U_ANON_KEY="<public anon key from Project Settings > API>"`, optionally `$env:O4U_SITE_ORIGIN="https://<shop site>"`, then `py -3 backend\api_tests\run_hosted.py` (optionally `--interactive-ban`). Type the e-mails of the owner/manager/staff test users and, at the hidden password prompts, their passwords (an optional fourth, non-staff account makes the stranger checks run).
4. `py -3 -m http.server 8765 --directory backend\api_tests`, open `http://localhost:8765/browser_cors_check.html`, paste URL and **public** key, click Run.
5. Send back `backend/api_tests/reports/hosted_report.md` and, if any row says NO, the page's table. **Never share** the service-role/secret key, passwords, access tokens, `Authorization` headers or the database password; the runner never asks for them and prints/stores none.
