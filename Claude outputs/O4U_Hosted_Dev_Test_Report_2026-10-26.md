# O4U — hosted development project: test report, 26 Oct 2026

Development Supabase project only (Free plan, Mumbai, PostgreSQL 17.11). Invented `dev-` data only. No real products, photos or customer data. Live Stockroom, website and `master` untouched. No keys or passwords appear here.

## Applied and verified on the real project
| Step | Result |
|---|---|
| Pre-flight (read-only) | Editor runs as `postgres` (not superuser, bypasses RLS, can read server settings). Automatic-RLS event trigger present. `pg_cron` 1.6.4 installed. Public schema empty. |
| 0001–0006 | Each applied one at a time; pasted text matched the repo file's SHA-256 (0001 compared ignoring line endings). Each verified before the next. |
| 0007 | Found by the pre-flight: default grants on this project give TRUNCATE/REFERENCES/TRIGGER to `service_role` on every new table (TRUNCATE skips the append-only triggers). Reproduced locally, fixed by 0007, confirmed 20 tables → 0 on the real project. |
| Seed | 7 products, 13 variants, 30 pieces, 1 count-pending size, 13 `opening_balance` ledger rows, no invented history. |
| Staff | Three distinct test users onboarded as owner / manager / staff after the owner confirmed they control the inboxes. |

## Smoke test (SQL-editor role simulation, run on the real project)
**35 of 35 PASS**, including: website request is a request and holds no stock; Confirm & Reserve; two-hour hold; "I have paid" is information only; Payment verified; dispatch deducts once even on a repeated tap; last piece goes to one customer; expiry; late payment re-hold; shared barcode refused until a colour is chosen; counter sale and receipt; uncounted stock refused for website holds and cleared only by a manager's count; public/staff/owner permissions; ledger balances.

## Scheduler (real, not simulated)
`o4u-expire-holds` ran every minute: 882 runs, 882 succeeded, 0 failed. A deliberately overdue unpaid hold was released **by the cron job itself** 29 seconds after it was backdated (actor `system`), with no manual call.

## Final audit (after the smoke test)
20 tables, row-level security on all; the public reaches exactly 3 functions and no tables; signed-in users write nothing directly; service role has no table privileges; no function is executable by PUBLIC; ledger mismatches 0; reserved-vs-orders mismatches 0; negative stock 0; paid orders without stock 0; cron failures 0; expiry failures 0.

## Supabase Security Advisor
0 errors, 35 warnings, 2 suggestions.
- 3 × "Function Search Path Mutable" (`setting`, `forbid_change`, `keep_one_owner`): fixed locally by migration 0008, **not yet applied** to the project.
- 31 × "SECURITY DEFINER function executable by anon / signed-in users": intentional. The 3 public functions and the 28 staff functions are exactly the allowlist the tests enforce, and each staff function checks the caller's role inside.
- 1 × "Leaked password protection disabled" (Auth setting): not changed; may be a paid-plan feature.

## NOT tested
Real Data API requests, real sign-in tokens (JWT verification), exposed-schema settings, CORS from a browser, banned-user token replay, MFA, and the Edge Function fallback. The SQL editor's role switching only imitates what the Data API does.

## Open decisions (owner)
D4 late payment; 60-minute grace; roles (father = manager); uncounted-stock counter policy; applying 0008 to the dev project.
