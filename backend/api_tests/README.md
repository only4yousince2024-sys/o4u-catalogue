# O4U API tests - real HTTP, JWT, roles, CORS, abuse

Development only. Invented data only. No Supabase account, key, token or password is used, stored or asked for by anything in this folder
except `run_hosted.py`, which the **owner** runs on their own computer (and which asks for passwords with a hidden prompt, never from a file).

The earlier checks (`backend/tests/run_db_tests.py`, `seed/dev_smoke_test.sql`) call the database directly, or imitate the Data API with
`SET ROLE`. These tests send **real HTTP requests** through **PostgREST** (the program Supabase's Data API is made of), with **real JWT
verification**, and, in one profile, tokens issued by **real GoTrue** (Supabase's auth server).

## What was run, and with what

| Piece | Version / source | Notes |
|---|---|---|
| PostgreSQL | 16.15 (Ubuntu 24.04 package) | Supabase projects default to 17; 17 was not available here (see `backend/README.md`). |
| PostgREST | **12.2.12**, official release `postgrest-v12.2.12-linux-static-x86-64.tar.xz` (SHA-256 of the archive `5de4092f...b557d5`) | Configured like Supabase: `authenticator` login role (NOINHERIT) that switches to `anon` / `authenticated` / `service_role` from the JWT `role` claim, schema `public` exposed, anon role `anon`, HS256 verification with a **throwaway secret generated fresh for every run**, per-role statement timeouts (anon 3 s, authenticated 8 s). The version Supabase currently runs was not checked from here. |
| GoTrue | module `github.com/supabase/auth` pseudo-version `v1.11.1-0.20261021123958-c3348e8f1cb3`, **built from source** with Go 1.24.7 (+ toolchain it fetched), the `godotenv` fork replaced by upstream v1.5.1 | Not the Docker image: Docker's daemon starts here but the registry answers "Data limit exceeded" (and 429), so **no Supabase Docker image or CLI stack was run**. This GoTrue creates the real `auth` schema (`auth.users` with `banned_until`, `deleted_at`, ...), signs in, bans, deletes, signs out. |
| Supabase API gateway (Kong), Studio, Storage, the hosted platform | **not run** | Gateway behaviour (apikey check, its CORS answers, platform rate limits, request-size limits, the new publishable keys, asymmetric JWT keys) is only testable on the hosted project: see "Hosted run". |
| Python / driver | 3.13.17, psycopg 3.3.6 | The hosted runner needs only Python 3.10+ and the standard library. |
| Browser | Chromium 153.0.8010.12 via Playwright 1.63.0 | Used for the real-browser CORS page against the **local** PostgREST only. |
| Other tools | `pg_cron` 1.6.2 (for the older suite) | |

JWTs in the `local` profile are minted with the same claim shape GoTrue issues (`sub, aud, exp, iat, email, phone, app_metadata, user_metadata,
role, aal, amr, session_id, is_anonymous`); test R1 compares them with real GoTrue tokens (the only difference: my minted tokens also carry `iss`).

## Files

| File | What |
|---|---|
| `run_local_stack.py` | Starts the throwaway PostgreSQL + PostgREST (+ GoTrue with `--gotrue`), runs the suite, writes `reports/` (git-ignored) and `ERROR_CONTRACT.md`. |
| `run_hosted.py` | The reduced, non-destructive profile for the hosted **development** project. Owner runs it. |
| `rehearsal_hosted.py` | Dress rehearsal of `run_hosted.py` against a local fake (or real-GoTrue) gateway, with a scan proving nothing secret reaches the output or report. |
| `selfcheck.py` | Breaks the database 18 ways and requires the suite to notice each one. |
| `browser_cors_check.html`, `run_browser_check.js`, `local_browser_check.py` | Real-browser CORS check: the page (owner opens it by hand against the hosted project) and the automated local run in Chromium. |
| `tests_*.py`, `ctx.py`, `lib.py`, `stack.py`, `runner.py`, `report.py`, `shim_gotrue.sql` | The suite and plumbing. |
| `ERROR_CONTRACT.md` | **Generated**: every error the website / Stockroom can receive (exact HTTP status, `code`, `message`, `details`, `hint`) and what the page should do. |

## Run the local suite

```
sudo apt-get install postgresql-16 postgresql-16-cron            # see backend/README.md
pip install "psycopg[binary]"
# PostgREST: download the official static release for your OS from https://github.com/PostgREST/postgrest/releases, unpack it, then
export O4U_POSTGREST=/path/to/postgrest
python3 backend/api_tests/run_local_stack.py                      # 42 checks, about 15 s
python3 backend/api_tests/run_local_stack.py --only A,B3,F        # a subset
python3 backend/api_tests/run_local_stack.py --without-0009       # same suite on migrations 0001-0008: shows the 7 failures 0009 fixes
export O4U_GOTRUE=/path/to/gotrue                                  # optional: a GoTrue binary (build notes below)
python3 backend/api_tests/run_local_stack.py --gotrue             # 30 checks with real GoTrue-issued tokens (23 repeated + R1-R7)
python3 backend/api_tests/selfcheck.py                            # does the suite notice breakage? (18 deliberate breakages)
python3 backend/tests/run_db_tests.py                             # the database suite (66 checks incl. the 4 new for 0009)
```

GoTrue build (no Docker): `go mod download github.com/supabase/auth@master`, copy the module directory somewhere writable, delete the `replace github.com/joho/godotenv`
line from its `go.mod` (that fork directory is not in the module download), `go build -o gotrue .`.

## Results of the runs made in this session (26 Oct 2026)

| Run | Result |
|---|---|
| `run_db_tests.py` on `fb2fa4d` (before this work) | 61 passed, 0 failed, 1 skipped (cron wait skipped) |
| `run_db_tests.py` with 0009 + 4 new checks | **66 passed, 0 failed, 0 skipped** (full run including the real pg_cron firing) |
| the 4 new checks with 0009 removed (`O4U_MIGRATIONS_DIR` = 0001-0008 only) | all 4 fail (plus the two migration-count checks); the other 59 pass |
| `run_mutations.py` | see `Claude outputs/O4U_Order_Operations_Design.md`, section 12 |
| `run_local_stack.py` (minted tokens, migrations 0001-0009) | **42 passed, 0 failed, 0 skipped** |
| `run_local_stack.py --without-0009` | 35 passed, **7 failed** (C5, D5, F1, F2, F5, F6, G5): the gaps below |
| `run_local_stack.py --gotrue` (real GoTrue tokens) | **30 passed, 0 failed, 0 skipped** |
| `selfcheck.py` | **18 of 18** deliberate breakages caught |
| `rehearsal_hosted.py` (fake gateway) and `--gotrue --ban` (real GoTrue sign-in, ban and unban through its admin API) | 22 / 23 PASS, 0 FAIL; leak scan clean; `--not-dev` refuses (exit 3) |
| real Chromium, `local_browser_check.py` | 7 of 7 requests readable by the page; with PostgREST CORS restricted to another site all 7 show BLOCKED (the page can see a failure) |

## Test matrix

Legend. **Local** = executed here against the throwaway stack: `M` minted tokens (42 checks), `G` real GoTrue tokens (30 checks).
**Hosted** = what the owner's run of `run_hosted.py` does. *Rehearsed* = `run_hosted.py` executed here against a local fake gateway
(proves the runner's own logic, **not** the real gateway). Nothing in the Hosted column has been executed against the real project.

| ID | What it proves | Local | Hosted project |
|---|---|---|---|
| A1 | OpenAPI document for anon lists exactly `get_availability`, `place_order_request`, `report_payment`, no table | EXECUTED here (M, G) | **REQUIRES LOCAL AUTHENTICATED RUN** (real gateway/PostgREST version; newer projects may hide the document, which also passes) |
| A2 | The same for a signed-in stranger: no function advertised that they cannot use | EXECUTED here (M, G) | REQUIRES LOCAL AUTHENTICATED RUN |
| A3 | Every other function in `public` (45 probed incl. 12 internal helpers; the 3 trigger functions are covered by the `pg_proc` cross-check) is refused to anon, with and without the key as bearer | EXECUTED here (M, G) | REQUIRES LOCAL AUTHENTICATED RUN (probe list is checked against `pg_proc` locally only) |
| A4 | All 20 tables refuse GET / POST / PATCH / DELETE / upsert / HEAD for anon | EXECUTED here (M, G) | REQUIRES LOCAL AUTHENTICATED RUN |
| A5 | Only schema `public` is reachable (`auth`, `storage`, `pg_catalog`, ... refused) | EXECUTED here (M, G) | REQUIRES LOCAL AUTHENTICATED RUN |
| A6 | The three public functions reach business logic for anon | EXECUTED here (M, G) | REQUIRES LOCAL AUTHENTICATED RUN |
| A7 | GET on a writing function, PUT/PATCH/DELETE on `/rpc` refused; nothing is a 5xx | EXECUTED here (M, G) | REQUIRES LOCAL AUTHENTICATED RUN |
| A8 | Gateway refuses a missing / wrong `apikey` before the database | not applicable locally (no gateway) | **REQUIRES LOCAL AUTHENTICATED RUN** (hosted only); rehearsed against a fake gateway |
| B1 | Role matrix: anon / stranger / staff / manager / owner x 25 functions (28 locally); allowed -> business logic, refused -> 403 `42501` (401 for anon); staff cannot discount | EXECUTED here (M, G) | REQUIRES LOCAL AUTHENTICATED RUN (read-only probes; the discount half needs a real order, so it is local only) |
| B2 | Table reads: staff cannot read payments / sales / refunds; stranger gets `[]` not an error; staff see only their own staff row; `idempotency` / `app_settings` unreadable | EXECUTED here (M, G) | REQUIRES LOCAL AUTHENTICATED RUN (on hosted the "manager/owner can see rows" half only counts if the smoke test left money rows) |
| B3 | No role can POST / PATCH / DELETE / upsert any table; row counts unchanged; TRUNCATE impossible for anon, authenticated, service_role | EXECUTED here (M, G) | REQUIRES LOCAL AUTHENTICATED RUN (every write uses a never-matching filter, so even a mistake changes nothing) |
| B4 | Manager and staff cannot call `owner_sales_summary` | EXECUTED here (M, G) | REQUIRES LOCAL AUTHENTICATED RUN |
| B5 | The exact probe calls the hosted run makes write nothing, even as owner | EXECUTED here (M, G) | not applicable (it proves the hosted run is safe) |
| C1 | Missing / malformed / non-Bearer Authorization never gives an identity | EXECUTED here (M, G) | REQUIRES LOCAL AUTHENTICATED RUN |
| C2 | A real token altered in 12 ways (signature, role -> service_role, sub -> owner, exp, alg none/NONE/HS512/RS256, glued) is always 401 | EXECUTED here (M, G) | REQUIRES LOCAL AUTHENTICATED RUN (needs a real signed-in token) |
| C3 | 160 simultaneous requests with 5 different identities on pooled connections: nobody gets another's rank | EXECUTED here (M, G) | REQUIRES LOCAL AUTHENTICATED RUN (24 requests there) |
| C4 | 33 minted-token cases: expired, nbf, iat, no exp, wrong secret, alg none, HS384/512, wrong aud / iss, 9 `role` claim values, 4 odd `sub` values | EXECUTED here (M) | not possible on hosted (needs the signing secret, which the owner must never hand out) |
| C5 | No claim can raise a rank: app_metadata / user_metadata / top-level / e-mail / aal2; `role: service_role` has no table access, no staff identity; internal helpers closed to it; owners cannot reach service-only functions | EXECUTED here (M) | not possible on hosted (same reason); the real-token half is R5 |
| C6 | Valid token + user **deleted / banned / deactivated** -> access stops at once; ban expiry and restore work | EXECUTED here (M) | **REQUIRES LOCAL AUTHENTICATED RUN** as the optional `--interactive-ban` step C6h (owner clicks Ban / Unban in the dashboard); rehearsed here with real GoTrue's admin API |
| C7 | A role change is visible on the next request with the same token | EXECUTED here (M); real-token version is R7 | not applicable (would change staff rows) |
| C8 | Last-owner protection over HTTP and in SQL; owners cannot onboard / deactivate staff | EXECUTED here (M); GoTrue's DELETE of the last owner is R7 | not applicable (destructive) |
| D1 | `get_availability` by POST body and by GET query string (`p_product_ids={a,b}`), empty / unknown / null arrays | EXECUTED here (M, G) | REQUIRES LOCAL AUTHENTICATED RUN |
| D2 | `jsonb` parameters: nested JSON works; JSON string / null / object / number in its place gets our own 4xx | EXECUTED here (M, G) | REQUIRES LOCAL AUTHENTICATED RUN (failure cases only; never creates an order) |
| D3 | Missing / extra / mistyped parameters, invalid JSON, wrong content type | EXECUTED here (M, G) | REQUIRES LOCAL AUTHENTICATED RUN |
| D4 | `Prefer` (params=single-object, return, count, tx=rollback, handling, missing), `Accept` (csv, object, text, octet-stream), `Range`; scalar `int` / `null` / `jsonb` bodies | EXECUTED here (M, G) | REQUIRES LOCAL AUTHENTICATED RUN |
| D5 | **Error contract**: every business error with exact status / code / message / details / hint -> `ERROR_CONTRACT.md` | EXECUTED here (M) | not applicable (needs seeded orders); the hosted project runs the same PostgREST so database errors have the same shape |
| D6 | Idempotency over HTTP: same key twice, same key different content, 10 at once, replayed verify_payment, 6 parallel dispatches | EXECUTED here (M, G) | not applicable (writes) |
| E1 | CORS preflight: shop site, another site, `null`, `http://localhost`, localhost:port, 127.0.0.1:port x `apikey, authorization, content-type, prefer, x-client-info` (+ profile headers) | EXECUTED here (M) - **local PostgREST's CORS, NOT Supabase's gateway** | **REQUIRES LOCAL AUTHENTICATED RUN** (needs no sign-in, only the URL and public key; set `O4U_SITE_ORIGIN` to the real site) |
| E2 | Actual responses (200, 400, 401) carry CORS headers, so a browser page can read errors | EXECUTED here (M) - local only | REQUIRES LOCAL AUTHENTICATED RUN |
| E3 | **Real browser** (`browser_cors_check.html`) | EXECUTED here in Chromium against local PostgREST only | **REQUIRES LOCAL AUTHENTICATED RUN** (owner opens the page by hand; see plan) |
| F1 | Per-phone hourly limit (5): a 429 at the limit; replays and other phones unaffected | EXECUTED here (M) (fails without 0009) | not applicable (would create orders) |
| F2 | Per-phone daily limit (15) and the site-wide brake (300/h); availability, report_payment and staff keep working under the brake; brake lifts | EXECUTED here (M) (fails without 0009) | not applicable |
| F3 | Unknown reference vs wrong phone vs garbage: byte-identical answers, timing spread < 40 ms | EXECUTED here (M, G) | not applicable (needs a real order) |
| F4 | Brute force: 600 guesses (300 in parallel): all 400 alike, none succeeds, ~570 guesses/s accepted (no throttle: see findings) | EXECUTED here (M) | not run on hosted (a burst of 600 calls at the dev project adds nothing the local run does not show) |
| F5 | `report_payment` bounded: 10 reports/order, 64-char reference, 0 .. 100,000,000 paise, no control characters, history cannot grow (fails without 0009) | EXECUTED here (M) | not applicable |
| F6 | 56 hostile `place_order_request` inputs: lengths to 1 MB / 20 MB, control characters, NUL, Unicode, SQL-looking text stored as data, quantities, 3000-deep JSON, 100,000 lines, duplicate keys (fails without 0009) | EXECUTED here (M) | not applicable (some would succeed and write) |
| F7 | `get_availability` with 10 .. 300,000 ids: answered quickly, no 5xx | EXECUTED here (M) | not run on hosted |
| F8 | Always-refused hostile inputs (2 MB name with a bad phone, 41 lines, NUL, SQL text, 100 KB reference) | EXECUTED here (M) | REQUIRES LOCAL AUTHENTICATED RUN (safe: every one is refused and rolls back) |
| G1 | **Last piece over HTTP**: 12 simultaneous confirmations for 1 piece, 5 rounds: exactly 1 wins, ledger intact | EXECUTED here (M, G) | not applicable |
| G2 | Website hold vs counter sale for the last piece, 5 rounds | EXECUTED here (M, G) | not applicable |
| G3 | 6 parallel `verify_payment` / 6 parallel `dispatch_order`: one payment, one deduction | EXECUTED here (M) | not applicable |
| G4 | 10 simultaneous "I have paid": hold extended exactly once | EXECUTED here (M) | not applicable |
| G5 | 24 simultaneous orders from one phone: exactly 5 admitted, rest 429 | EXECUTED here (M) | not applicable |
| G6 | 200 mixed simultaneous requests, none dropped, ranks correct | EXECUTED here (M) | not applicable |
| R1 | A real GoTrue token has the assumed claims, HS256, 1 h; `auth.users` has `banned_until`, `deleted_at`, `email`, `id` | EXECUTED here (G) | covered by A/B/C running with real tokens |
| R2 | Wrong password and unknown e-mail give identical answers (no account enumeration) | EXECUTED here (G) | not run on hosted (hits Auth's own rate limits) |
| R3 | **Ban in GoTrue**: old token loses access at once; sign-in refused (`user_banned`); unban restores | EXECUTED here (G) | **REQUIRES LOCAL AUTHENTICATED RUN** (= C6h) |
| R4 | **Soft and hard delete in GoTrue**: token dead at once; hard delete cascades the staff row | EXECUTED here (G) | not applicable (destructive) |
| R5 | Self-signup and anonymous sign-in produce `authenticated` tokens that get nothing | EXECUTED here (G) | owner should also switch both off in the dashboard (decision) |
| R6 | Refresh works; **sign-out does not cut an access token before it expires** | EXECUTED here (G) | not run (changes sessions) |
| R7 | Role change / deactivation immediate with real tokens; GoTrue cannot delete the last owner (500 with the owner message) | EXECUTED here (G) | not applicable |

## Findings

Fixed by migration `0009_api_abuse_limits.sql` (idempotent; existing migrations untouched; regression checks in `backend/tests/run_db_tests.py`, each shown to fail without 0009, and 7 new mutations):

| # | Gap (found by) | Fix |
|---|---|---|
| G1 | Rate-limit refusals (`P0429`) reached the browser as **HTTP 500** - PostgREST only maps `P0001` and `PTnnn` (F1, F2, G5, D5) | same messages and limits, SQLSTATE `PT429` -> HTTP 429 |
| G2 | `place_order_request` stored names / addresses / landmarks of any length (1 MB name), control and escape characters, accepted a 20 MB request, a NULL phone reached a raw `23502`, a 1 MB idempotency key hit the index limit and returned **HTTP 500 `54000`** (F6) | name 100, address 500, landmark 200, key 100 characters; one line of plain text; lines <= 20,000 bytes; NULL phone / reference / lines get the normal messages; all checked before anything is stored |
| G3 | `report_payment` unbounded: 60 calls left 60 report rows + 60 audit rows, any text, any amount (F5) | 10 reports per order (setting `max_payment_reports_per_order`, 429 over it), reference <= 64 characters, amount 0 .. 100,000,000 paise; inputs that cannot belong to an order get the same `order not found` |
| G4 | The service role could run the internal helpers (`apply_stock_event`, `idem_begin`, `log_order` ...) over the Data API (C5) | revoked; the people-facing functions that use them internally still work |

Observed, no change made (details and decisions in the design document):

* PostgREST accepts an expired token for ~30 s (clock skew), accepts any `aud` / `iss`, and a token without `exp`. Only holders of the signing secret can mint such tokens.
* A bad or expired token breaks **public** calls too (401 `PGRST301`): the website must send only the anon key.
* **Sign-out and session revocation do not cut an access token that has not expired** (R6). Ban, delete and staff deactivation do (R3, R4, C6).
* Anyone can be 'authenticated' (self-signup, anonymous sign-in) - they get nothing (R5) - but the owner should still switch both off.
* A banned or soft-deleted **sole owner** leaves nobody with owner rank, and the last-owner rule (it watches the staff table) does not see it; deleting the account outright is blocked (R7).
* No per-caller throttle exists for `report_payment` (the database cannot see an IP address; failed lookups roll back, so cannot be counted). 600 guesses are answered alike and none succeeds; the guess space is ~31^6 references x 10^10 phone numbers.
* `23505` errors carry internal ids and a UPI reference in `details`; the front ends must never display `details`/`hint`.
* Anonymous callers can learn which tables and columns exist (permission-denied vs not-found answers, `PGRST204`); the schema is public in this repository anyway.
* Statement timeouts return HTTP 500 `57014`.

## Hosted run - the owner's plan (about 10 minutes)

What you type and what you never share.

1. **Get the code.** `git fetch origin dev/backend-synthetic` then `git checkout dev/backend-synthetic`.
2. **Apply 0009 to the development project** (same way as 0008: Supabase dashboard > SQL editor > paste `backend/migrations/0009_api_abuse_limits.sql` > Run; check the pasted text against the file's SHA-256 as before). Until you do, the hosted run will report the same gaps G1-G4 (that is a valid result too).
3. **Find the two public values.** Dashboard > Project Settings > API: the project URL and the **anon / publishable** key (public). Never copy the `service_role` / secret key anywhere.
4. **Terminal** (Windows PowerShell shown; use `export` on macOS/Linux):
   ```
   $env:O4U_API_URL  = "https://<your-dev-project>.supabase.co"
   $env:O4U_ANON_KEY = "<the public anon key>"
   $env:O4U_SITE_ORIGIN = "https://<the shop's website>"       # optional: also checks CORS for the real site
   py -3 backend\api_tests\run_hosted.py
   ```
   It first asks the database for the product list and **refuses unless every id starts with `dev-`**. Then it asks for the e-mail of the owner, manager and staff test accounts (and an optional fourth account that is *not* on the staff list - create one under Authentication > Users and do not add it to `staff`), each followed by a password prompt that shows nothing as you type. Press Enter at an e-mail prompt to skip a role.
5. **Optional, 2 minutes:** `py -3 backend\api_tests\run_hosted.py --interactive-ban`. At the first pause, in the dashboard: Authentication > Users > the *staff* test user > ... > Ban user (24 hours), press Enter; at the second pause **Unban** that user, press Enter.
6. **Real-browser CORS check:** `py -3 -m http.server 8765 --directory backend\api_tests`, open `http://localhost:8765/browser_cors_check.html`, paste the project URL and the **public** key (leave the REST path as `/rest/v1`), click **Run the checks**. All seven rows should say "yes".
7. **Send back** `backend/api_tests/reports/hosted_report.md` and (if anything says NO) a copy of the page's table. The report contains PASS/FAIL lines only - no URL, key, token, password or e-mail address - and the runner's own leak scan (`rehearsal_hosted.py`) checks that.

**Never share:** the service-role / secret key, any password, any access token or `Authorization` header, the database password, anything from `.env` files. `run_hosted.py` never asks for any of them, never writes them, and rejects a key whose role is not `anon`.
Everything the hosted run sends is a read or a call that is refused or fails validation and rolls back (checked by B5 locally); it does not create orders, payments or users, and does not use the service role.

## Not tested anywhere (yet)

Postgres 17; the real Supabase gateway (apikey handling, CORS, platform limits, request-size limits, Cloudflare/WAF behaviour, the new `sb_publishable_` keys and asymmetric JWT signing keys); MFA / `aal2`; GoTrue behind an SMTP provider (e-mail confirmation, password reset); real network latency and the hosted connection limits under load (the hosted profile deliberately uses at most 24 parallel requests); the Edge Function fallback for `expire_holds`.
