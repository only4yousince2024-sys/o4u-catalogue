# O4U — Automated order operations: design and implementation report

Branch `dev/backend-synthetic` · 25 Oct 2026 · development only, synthetic data only · nothing deployed, nothing pushed

Legend: **BUILT** = written in `backend/migrations/0001_core.sql` · **TESTED** = exercised by `backend/tests/run_db_tests.py` on a throwaway PostgreSQL 16 (33 checks) · **PLANNED** = not written.

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
