# O4U — Synchronised Offline + Online Retail System
## Roadmap for approval (planning only)

> **Updated 25 Oct 2026:** see **v2** at the end of this file. Where v2 and the sections above disagree (heartbeat timing, dual entry, rollback, temporary environments), v2 is the current plan.

Date: 25 Oct 2026 · Nothing in Stockroom, the website, Netlify, GitHub or any customer data has been touched. No code written, nothing deployed or migrated.

**Evidence labels:** ✅ verified from the Stockroom v44 source / the repo · 🔎 checked today on the vendor's own page · ⚠️ estimate or assumption · ❓ unknown, needs a test.

---

## 1. My understanding

**The business.** O4U is a running shop on Pakhowal Road, Ludhiana. Your father runs the floor: walk-ins, sales, exchanges, stock. Stockroom is already the shop's system. The website is a **second sales channel on the same stock**, not a separate shop.

**What "done" means.**
1. One stock truth. A piece sold at the counter disappears from the website, and the other way round.
2. The website does not add daily chores for your father. Anything that can be automated is; what remains manual is only what a person must judge (is the piece really on the rack, did the UPI payment arrive, what is the Porter fare).
3. No public launch until product data, images, sizes, prices, stock, order requests, reservations, deductions and releases all sync reliably.
4. The shop never stops working during development or migration.

**Decisions you have made.**
- **D1-A:** stock is reserved only after staff confirm. An unpaid hold auto-expires after 2 hours and releases safely. Sold or paid stock is never released.
- **D2-C:** a website request appears in Stockroom automatically, with a unique reference. WhatsApp stays. Opening WhatsApp is not proof of sending.
- **D3 (modified B):** per size: 3+ → "Available" (no number); 2 → "Only 2 left"; 1 → "Only 1 left"; 0 → "Ask us". If the data is not reliable or is delayed → "Check availability". Never manufactured scarcity.
- **UX-1:** a compact "Added to your bag" prompt on the first add of a session only.
- **UX-2:** `Add to Bag` becomes `[−] 1 [+]` everywhere, synchronised.

---

## 2. Contradictions and technical risks I found

### 2a. Contradictions between your requirements and facts about the system

| # | Finding | Why it matters | Proposed resolution |
|---|---|---|---|
| C1 | **The shop's stock records are cloud-only today.** ✅ Stockroom has no offline mode (no service worker, no local queue, no `navigator.onLine` handling). Every sale, restock and count is a live cloud write. | "The store loses internet" already means Stockroom cannot record a sale today. The migration does not worsen this, but the website must not sell blind while it happens. | A defined outage procedure (§7), plus a *store heartbeat* so the website degrades to "Check availability" automatically. A true offline-first Stockroom is **optional later**, not a launch need. |
| C2 | **D1 auto-expiry removes a safeguard the app has on purpose.** ✅ Today, when a hold expires the screen says "check the UPI app before releasing", because a customer may have paid at 1h58 and staff not yet recorded it. | Auto-release could free a piece that is genuinely paid for, and sell it again. | Keep the 2-hour auto-release you approved, but (i) alert staff 15 minutes before expiry, (ii) a **late-payment path**: recording a payment on an expired order tries to re-reserve; if the piece is still free it succeeds, if it was taken it creates a "paid, stock gone" exception that routes into the existing refund flow. Stock is never released once status is `paid`. |
| C3 | **D3 vs the current site rules.** ✅ `AGENTS.md`: `stockQty` is "never shown"; the size filter means "sizes made in, never live stock"; the site never claims availability. Today `products.js` has one total quantity per product, no per-size stock. | D3 needs live per-size data, which a static file generated at sync time can never provide fresh. | Catalogue content stays static/fast; availability becomes a **separate live lookup**. The rules in `AGENTS.md` must be amended with your approval (listed in §11). |
| C4 | **D3 "genuine" depends on the shop recording every counter sale.** | The biggest real-world risk is not software: a sale sold at the counter but not entered in Stockroom makes "Only 1 left" false. | (i) Make "Sold in shop" a few taps (existing screen, kept); (ii) a **one-time baseline recount** of every published product before launch (mandatory gate); (iii) periodic recount prompts; (iv) optional later: scan the tag barcode to sell. Stockroom already stores a barcode per size. |
| C5 | **UX-1 changes an existing, owner-approved rule.** ✅ `AGENTS.md` says the *first* add opens the bag drawer, later adds show a toast. You now want the first add to show a compact prompt with *View Bag* / *Continue Shopping*. | Not a conflict, but a spec change to an approved behaviour. | I will treat your new description as the replacement and update `AGENTS.md` on approval. |
| C6 | **"No extra manual work" vs D1.** | Staff must still confirm each order (D1), check the UPI app, and agree the Porter fare. Those are judgement steps that no software can remove without a payment gateway, which is out of scope. | State it plainly: the website removes *pasting*, *retyping*, *releasing holds*, *matching codes* and *chasing duplicates*. It does not remove *confirming* and *checking payment*. |
| C7 | **Cart quantity cap vs "a cart is not a reservation".** | Two customers can each hold the last piece in a cart. | Cap the stepper at current sellable stock, but **revalidate at submission** and tell the customer exactly what changed. |
| C8 | **"Both channels from one inventory" vs "Stockroom runs inside a Claude artifact".** ❓ | If the Stockroom page stays inside the artifact, it may not be allowed to call an outside server. I have not been able to confirm that. | Milestone 0 runs a harmless test (§13). The recommended plan assumes Stockroom's page moves to its own hosting (needed anyway for independence), with the artifact left untouched as the fallback. |

### 2b. Technical risks (ranked)

| Rank | Risk | Severity | Safeguard |
|---|---|---|---|
| 1 | Backup incomplete or restore untried (1000-document read cap ✅, restore "not yet tested" ✅, photos re-encoded if fetch is blocked ✅) | Severe | Phase A gate: no migration until counts, hashes and relations verify and a restore into an isolated project succeeds |
| 2 | Counter sales not recorded → false low-stock claims | High (trust) | Baseline recount, heartbeat, easy sale entry, recount nudges |
| 3 | Two writers (artifact and new backend) both live | High | Single writer at all times; shadow mode reads only; dated cutover |
| 4 | Photo references break (asset ids are platform-issued and not reusable ✅) | High | Manifest-driven rewrite, hash comparison, nothing deleted from the artifact |
| 5 | Concurrent reservations | High | Database-enforced stock rows, not client locks |
| 6 | Website depends on the backend being up | Medium | Static catalogue fallback; WhatsApp-only ordering when API unreachable; "Check availability" |
| 7 | Customer data (names, phones, addresses) now stored server-side | Medium | Access rules, private buckets, minimal fields, privacy notice (DPDP Act 2023 likely applies ⚠️ not legal advice) |
| 8 | Outdated documentation misleading later work | Medium | The v44 source is the reference; I will write a current system document in Phase A |

---

## 3. How Stockroom works today (investigation you asked for) — ✅ from the v44 source

| Workflow | Current behaviour | After migration |
|---|---|---|
| **Offline (counter) sales** | Product → *Sold in shop*: pick size, qty, price (pre-filled from offer or MRP). Refuses to sell pieces held for orders. Writes a `sale` row to `stockmoves`. Time is "now" (no back-dating). | Same screen, same words. Enforced in the database. Optional "sold at" time for after-an-outage entries (small addition). |
| **Inventory changes** | *Add or correct stock*: New stock arrived, Recount (sets the exact number; refuses if stock changed while counting), Damaged or lost. Every change appends to `stockmoves` with before/after and who. | Same three reasons. The recount's stale-check becomes a database check (expected value must match). Never silently overwrites. |
| **Orders** | 12 statuses: request → confirmed → awaiting_payment → paid → packed → (change_due) → dispatched → (failed) → delivered / refund_due → refunded / cancelled. Hold = 2 h, `allocated` flag, stock decremented only at dispatch. Duplicate detection (same phone + same items in 3 days). Website orders are saved under `w-<code>`, so re-pasting never duplicates. | Same lifecycle. Website requests arrive by themselves; the same `W…` code is the unique key. Hold expiry becomes automatic. |
| **Exchanges / returns** | A `case` per returned piece with checks (unworn, unwashed, tags). Stock returns to the rack only after the item is checked and marked sellable. Replacement diff and refunds are limited by `refundRoom()` so you can't refund more than was paid. | Unchanged logic. Stock effects go through the same single stock function. |
| **Holds** | Computed by scanning orders with `allocated: true`; client-side leases of 8 seconds stop two phones overlapping. | A real `reserved` number per size with a database rule that `reserved ≤ on_hand`. |
| **Manual corrections** | Via the stock screens above; history is visible per product. | Same; every correction is a ledger row; none is ever deleted. |
| **Product images** | Up to 5 website images per product, in display order; names derived from the product id. Product deletion deletes that product's photos (`assets.delete`). | Stored in a bucket. Deletion becomes **soft** (30-day recycle) so a mistaken delete can be undone. Nothing is removed during migration. |
| **Backup / restore** | In-app *Download full backup* (read-only). Restore not tested. | Automatic nightly backup plus the same manual button; restore tested before cutover and quarterly after. |
| **Website publishing** | *Published* switch, then *Download for website*, unzip, `sync.bat`, git push, Netlify. | The switch takes effect on the site directly. `sync.bat` becomes a fallback only. |

---

## 4. Recommended architecture

```
 Counter / phones ──► STOCKROOM (same UI, own hosting, login) ──┐
                                                                 ▼
                                         ┌──────────────────────────────────────┐
                                         │ BACKEND (Postgres + Storage + Auth)  │
                                         │  stock_levels (on_hand, reserved)    │
                                         │  stock_moves  (append-only ledger)   │
                                         │  orders / order_lines / events       │
                                         │  store_heartbeat                     │
                                         │  public_catalogue (view)             │
                                         │  get_availability()  place_order()   │
                                         │  scheduled job: release_expired()    │
                                         └──────────────▲───────────────────────┘
                                                        │ public key, rules-limited
 Customer ──► WEBSITE (static, Netlify, same design) ───┘
                  ▲ static fallback catalogue if backend unreachable
```

Principles:
1. **Stockroom's screens and wording stay.** A thin adapter re-implements the handful of calls it makes (read/write documents, live updates, photo upload, downloads). That avoids rewriting 3,927 lines and gives a one-line rollback.
2. **Everything that must never be wrong is enforced by the database:** non-negative stock, `reserved ≤ on_hand`, one active reservation per order line, unique order code. Not by browser code.
3. **Two layers of data.** Documents are imported unchanged (same ids) so nothing is lost in translation. Only stock, orders and the ledger become proper tables.
4. **Website content is static and fast; availability is a live lookup.** The server decides what text to show (so exact counts of 3+ never leave the server).
5. **WhatsApp remains the customer's channel.** The backend is a safety net and an automation, not a replacement.

### Backend evaluation (you asked whether Supabase is appropriate)

| Criterion | Supabase (Postgres) | Firebase | Neon/Postgres + R2 (self-assembled) | PocketBase on a small VPS | Shopify (buy, not build) |
|---|---|---|---|---|---|
| Transaction safety / no oversell | ★ Database-enforced | ○ Transactions work, rules in app code | ★ Same as Supabase | ○ SQLite, single server | ★ Built in |
| Fit with Stockroom's data | ★ Documents + tables | ★ Document model | ● Needs auth/functions assembled | ● | ✗ Replaces Stockroom |
| Maintenance for a family shop | ● Managed | ● Managed | ✗ You glue 3–4 services | ✗ You run a server | ★ Managed |
| Image storage | ● Included 🔎 | ● Needs pay plan ⚠️ | ● Cheap | ● | ● |
| Backups | Daily 7-day on Pro 🔎; none on Free 🔎 | Manual exports | Varies | You build | ● |
| Scheduled expiry job | ● Postgres scheduling / scheduled function ❓ confirm exact feature | ● | ○ | ○ | n/a |
| Lock-in | Low (plain Postgres) | High | Low | Low | High |
| Cost | $25/month Pro 🔎 | pay-per-use ⚠️ | ~similar | VPS + your time | high, and replaces what works ⚠️ |

**Verdict: Supabase is appropriate** and I recommend it, with one caveat: confirm that the scheduled-expiry mechanism and the Stockroom hosting question (C8) pass their small tests in Milestone 0 before you commit. **Shopify** would solve online+offline sync as a product, but it replaces Stockroom's UI and logic, which contradicts "preserve what works", so I do not recommend it; it is listed so the decision is conscious.
Region: **South Asia (Mumbai), ap-south-1** exists 🔎.

---

## 5. Order and WhatsApp workflow (D2-C)

### Two separate tracks, not one long status chain
Your list mixes things that happen independently. I recommend keeping the **existing order statuses** (so nothing in Stockroom is rewritten) and adding one **separate contact field**:

| Track | Values |
|---|---|
| **Contact** (new field) | `none` → **WhatsApp delivery unverified** (default when the site creates the request) → **customer-reported** (customer pressed "I've sent it" on the site; self-declared) → **contact confirmed** (the customer's WhatsApp message with the order code was seen/pasted/received) |
| **Order status** (existing) | `request` (= *website request created*) → `confirmed` (= *order confirmed by staff*) → `awaiting_payment` (= *stock reserved*, 2 h hold) → `paid` (= *payment completed*) → `packed` → `dispatched` → `delivered`; or `cancelled` / `refund_due` / `refunded` |

Stockroom shows one line per request: "Website request W2510-K7M3-ZP · contact: unverified · 14 min ago".

### Does automatic WhatsApp confirmation need the official WhatsApp Business Platform?
**Yes, to *verify* anything.** Without the official platform:
- The site can only open WhatsApp with pre-filled text (`wa.me`). Neither the site nor Stockroom is told whether the customer pressed send. **I will not label any request "delivered" or "sent" on that basis.**
- What *is* possible and honest: the request already exists in Stockroom (so it can't be lost), and it flips to **contact confirmed** when staff paste or recognise the customer's message code (a single tap, because the code is the match). Requests with no contact after a set time (suggest 24 h) move to a "No contact" list and are never reserved.

With the official **WhatsApp Business Platform (Cloud API)**:
- The platform can notify your backend when the customer's message *arrives*, so contact becomes confirmed automatically by matching the code, and delivery/read statuses are reported for messages *you* send through the API.
- Pricing 🔎 (Meta's own page): per-message billing since 1 July 2025; **messages from customers to you are free**; the 24-hour service window is unpriced; from **1 Oct 2026** each business number gets 1,000 free service messages per month, and utility messages in an open window become chargeable; India per-message rates are in Meta's INR rate card (not copied here).
- Costs beyond fees: Meta business verification, a dedicated or migrated number, and a provider/webhook setup. ❓ Whether your current business number can keep being used in the WhatsApp Business app alongside the API must be checked with Meta at that stage.
- **Recommendation:** not a launch requirement. Launch with *unverified → customer-reported → staff-confirmed* labels, which are honest. Add the official API afterwards if the manual "contact confirmed" tap proves to be a burden.

### Reliability rules
- Unique **reference**: keep the existing `W<DDMM>-<4>-<check>` code (customers and Stockroom already understand it) and enforce uniqueness in the database. A resubmission with the same code returns the same request (no duplicates).
- The site stores the request first, then opens WhatsApp. If the backend is down, it opens WhatsApp anyway with the same code and the request is created later when you paste it (current behaviour). Nothing is lost either way.
- The site's wording stays "order request"; never "confirmed", "reserved" or "sent".

---

## 6. Stock synchronisation, reservations and D3

### Definitions
- `on_hand` = physical pieces on the rack. `reserved` = pieces held for confirmed, unpaid-or-unshipped orders. **Sellable = on_hand − reserved.** Carts do not count.
- Every change, whoever makes it (counter sale, website order, restock, recount, damage, exchange return), goes through one database function and writes one ledger row.

### Reservation (D1) and expiry
1. Staff press *Hold stock* → one transaction locks the size rows, checks sellable ≥ qty for **every** line, adds to `reserved`, sets `hold_until = now + 2 h`. All or nothing.
2. Every minute a scheduled job finds orders with status `awaiting_payment` and `hold_until` passed, **re-checks the status under lock**, and only then releases. Orders already `paid`, `packed`, `dispatched` or cancelled are skipped. Releasing is idempotent: running it twice releases once.
3. 15 minutes before expiry Stockroom flags the order ("check the UPI app"). A late payment follows the path in C2.
4. Payment recorded → hold timer cleared. Dispatch → `on_hand` and `reserved` both drop in one transaction (matching today's "pieces leave the rack at dispatch").

### D3 availability rules, computed on the server per size
| Sellable | Shown |
|---|---|
| ≥ 3 | **Available** (number never sent to the browser) |
| 2 | **Only 2 left** |
| 1 | **Only 1 left** |
| 0 | **Ask us** |
| unknown / stale / lookup failed | **Check availability** |

### Preventing outdated information (the offline-store question)
1. **One ledger.** The counter and the website write to the same stock table. There is no copy to go stale, except what the browser already loaded.
2. **Live lookup, short life.** The page fetches availability when a product opens and every 30–60 s while it stays open, and refreshes when the tab regains focus. A response older than 60 s, or a failed one, shows **Check availability**.
3. **Revalidation at order submission.** The server re-checks every line and returns exactly what changed; the customer edits and resubmits. This is the final authority; the displayed label is guidance.
4. **Store heartbeat.** Stockroom reports "alive" every minute while open. If the shop is within its opening hours and no heartbeat has arrived for 15 minutes, **all** sizes show "Check availability", because counter sales may be going unrecorded. Outside opening hours stock isn't moving, so labels stay live. (Needs your opening hours and a "shop open/closed" override.)
5. **Baseline recount before launch** (mandatory). A "low-stock" claim is only genuine if the starting number was.
6. **Genuineness guard.** A number is displayed only for sizes whose count has been established in the new system (baseline recount, restock, or sale). Anything else shows "Check availability".
7. **No scarcity inventing.** Every label is a pure function of `on_hand − reserved`. There is no "hidden" buffer and no timer-based pressure. The ledger lets me prove any shown number after the fact.

---

## 7. Network outages and conflicts

| Situation | What staff do | What the system does |
|---|---|---|
| **Shop internet down** | Keep selling. Write each counter sale on a paper slip (item, size, qty, price). Don't hold stock for web orders. | Heartbeat stops → within 15 min the website shows "Check availability" for everything; new requests still land (they're simply not reservable until staff confirm). |
| **Internet back** | Enter the slips via *Sold in shop* (with the "sold at" time). If a slip is for a piece now held or sold elsewhere, the app shows the conflict. | Nothing is overwritten. A sale that would take sellable below zero is **refused with a message**, and staff resolve it (release a hold or contact the web customer). |
| **Two people change the same size at once** | Nothing to do | Database serialises them; the later one gets "stock changed, check again". |
| **Recount while holds exist** | Recount sets on-hand; the app refuses to go below held pieces and shows which orders are affected | Expected-value check; ledger row recording the adjustment. |
| **Backend/Supabase down** | WhatsApp-only mode (current behaviour) | Site falls back to the static catalogue, shows "Check availability", opens WhatsApp with the usual message. Stockroom shows an error and records nothing partially. |
| **Order submitted twice / double tap** | — | Same order code → same request returned. |
| **Phone loses signal mid-save** | Retry | Writes are atomic, so a retry never double-applies (idempotency key per action). |

**Optional later:** a real offline queue in Stockroom (record sales offline, sync later with conflict review). It is a significant build; the paper-slip procedure covers the launch.

---

## 8. Cart UX specification (design only — implemented in phase G)

- **First add per session:** a compact bottom sheet (not full-screen): "Added to your bag!" with `View Bag / Checkout` and `Continue Shopping`. Shown once, tracked in `sessionStorage` (try/catch, in-memory fallback). *Continue Shopping* closes it and leaves scroll position untouched. *View Bag* opens the cart.
- **Later adds:** no interruption; a small toast/inline tick and a badge pulse (respecting reduced-motion).
- **Quantity control:** the product card / modal button is `Add to Bag` until that **product + colour + size** is in the bag; then it becomes `[−] n [+]`. The same state drives cards, product view, and bag. Decreasing to 0 removes the line and restores `Add to Bag`. A size must be chosen first (a card with several sizes opens the size picker, then adds).
- **Cap:** `+` stops at current sellable stock, showing "Only 2 left" (consistent with D3) or "That's all we have". Not a reservation.
- **Safety:** a tap lock (~300 ms) and an idempotent "set quantity to n" action prevent double adds; rapid taps coalesce.
- **Persistence:** existing `localStorage` cart, 7-day expiry, unchanged shape; every read/write in try/catch.
- **Submission:** revalidates availability server-side first; shortages are shown per line.

---

## 9. Phased roadmap

Legend: **M** = mandatory for launch · **O** = optional / after launch. Costs are in §10. Effort is relative (S/M/L) and ⚠️ an estimate; elapsed time depends on your review speed (my guess: 8–12 weeks end to end, part-time). Phases G (cart UX) and the early backend phases can run in parallel because they touch different systems.

### Phase A — Backup verification (M)
- **Objective:** a complete, proven, restorable copy of all Stockroom data and photos, and a current system document.
- **Tasks:** you run *Download full backup*; read-only verification script (counts, SHA-256, relations, orphans, 1000-cap check); independent second export from chat (needs your permission); restore test into an isolated project; write the current-state document (supersedes the v23 handbook).
- **Dependencies:** you on the laptop; a free scratch Supabase project.
- **Risks:** truncated collections; re-encoded photos; PII in the ZIP.
- **Cost:** ₹0 (Free plan scratch project 🔎).
- **Permissions:** run backup (yours); read the database from chat for the second export (separate authorisation); create a free Supabase account.
- **Acceptance:** zero unexplained missing photos; counts equal the on-screen counts; every order's product, every case's order, every refund's order resolves; restore into the isolated project reproduces identical counts and image hashes; a written rollback procedure.
- **Rollback:** delete the scratch project and local files.

### Phase B — Backend setup (M)
- **Objective:** a secured production-grade backend, empty, in Mumbai.
- **Tasks:** project on Pro; schema (tables below); access rules; staff login (allow-list of 2–3 emails); buckets (public web images, private source/tag photos); nightly backup export to a private location; spike tests for C8 (can the artifact call it?) and the scheduled-expiry job.
- **Dependencies:** A passed. **Risks:** misconfigured access rules (mitigated by an automated policy test suite).
- **Cost:** Pro $25/month starts here 🔎. **Permissions:** you open the paid account; I never see card details.
- **Acceptance:** anonymous role cannot read any table; can read only the public catalogue and call the two public functions; staff login works; a scripted race of 50 parallel reservations for 1 piece yields exactly 1 success; scheduled job releases a test hold.
- **Rollback:** pause/delete the project (nothing depends on it yet).

### Phase C — Stockroom integration (M)
- **Objective:** Stockroom runs on the new backend with the same screens, in **shadow mode**: the artifact stays the real system.
- **Tasks:** adapter (documents, live updates, photos, downloads); import of Phase-A data with the same ids; photo reference rewrite from the manifest; login replaces the "Dad/Khush/Staff" dropdown (names kept as labels); soft-delete for products and photos.
- **Dependencies:** B; C8 result. **Risks:** subtle UI regressions (mitigated by a scripted side-by-side run of every screen); two systems diverging (mitigated: new copy is read/test-only until cutover).
- **Cost:** hosting Free. **Permissions:** a second Netlify site for the Stockroom copy.
- **Acceptance:** each action (capture, edit, publish, sale, restock, recount, damage, order lifecycle, exchange, refund, backup) gives the same result in both systems on test data; live updates work on two devices; photos display and hash-match.
- **Rollback:** keep using the artifact; discard the copy.

### Phase D — Inventory synchronisation (M)
- **Objective:** one trustworthy stock ledger shared by counter and website.
- **Tasks:** `stock_levels` / `stock_moves` as the single write path; reserve / release / dispatch / return functions; automatic hold expiry with the late-payment path; recount expected-value check; "sold at" time for outage entry; store heartbeat and opening-hours rule; **baseline recount** workflow; reconciliation report (Σ ledger = on_hand per size).
- **Dependencies:** C. **Risks:** counts wrong at baseline (mitigated by the recount gate).
- **Cost:** none extra. **Permissions:** your father's time for the recount (the real cost of this phase).
- **Acceptance:** tests in §12 rows 1–8 pass; reconciliation report is zero-difference after a day of parallel use.
- **Rollback:** re-point to the artifact; ledger exported for the record.

### Phase E — Website integration (M)
- **Objective:** the website reads products and availability from the backend, with a static fallback.
- **Tasks:** public catalogue view (published, finished, non-pending products only; no counts, costs or notes); `get_availability` lookup; images from the bucket (or CDN path), same filenames; static `products.js` kept as fallback; `AGENTS.md` updated (§11).
- **Dependencies:** D. **Risks:** backend outage (fallback); image path change (verify every image).
- **Cost:** none extra (Free Netlify). **Permissions:** you approve the `AGENTS.md` changes.
- **Acceptance:** every published product renders with correct sizes, prices, offer and images (compared with the current build); backend blocked → site still works with "Check availability"; no unpublished/private field present in any response.
- **Rollback:** revert one commit; the static build is untouched.

### Phase F — Order and WhatsApp workflow (M)
- **Objective:** website requests appear in Stockroom by themselves with honest status.
- **Tasks:** `place_order_request` (server-side price and stock validation, rate limit, bot check, idempotent on the code); contact-state field and Stockroom filters ("unverified", "no contact after 24 h"); "I've sent it" button on the confirmation screen (labelled customer-reported); one-tap "contact confirmed" when a message is recognised; staff alert for new requests (in-app badge at minimum); privacy notice on the policy page.
- **Dependencies:** D, E. **Risks:** spam/abuse; customers misunderstanding status wording.
- **Cost:** Free bot check ⚠️ (Cloudflare Turnstile); optional email alert free tier ⚠️.
- **Permissions:** you approve the final customer wording.
- **Acceptance:** duplicate submit → one request; tampered prices ignored; backend down → WhatsApp still opens with the code; request visible in Stockroom within seconds; no wording anywhere says "sent", "delivered" or "confirmed" unless true.
- **Rollback:** feature flag off → today's paste-from-WhatsApp flow.
- **Optional (O):** official WhatsApp Business Platform for automatic contact confirmation.

### Phase G — Cart and quantity controls (M by your request; can start now, in parallel)
- **Objective:** the UX in §8.
- **Tasks:** first-add compact sheet; `Add to Bag` → `[−] n [+]` synchronised across card, product view and bag; cap hook (mock availability until E); tap-lock; scroll position preservation; update the existing 80-check cart test suite and add new ones.
- **Dependencies:** none to build; cap needs E to be real. **Risks:** regressions in the working cart (mitigated by the existing headless tests, which never send anything).
- **Cost:** none. **Permissions:** approve `AGENTS.md` change C5.
- **Acceptance:** all tests in §12 rows 9–11 pass on a phone-width and desktop browser; existing cart checks still pass; thresholds ₹1,999/2,000/2,001 unchanged.
- **Rollback:** revert the commit.

### Phase H — Low-stock indicators (M)
- **Objective:** D3 labels exactly as specified.
- **Tasks:** server-side label function; freshness handling; the genuineness guard; display per size in card/product view/size chips; "Check availability" fallback everywhere.
- **Dependencies:** D, E. **Risks:** a wrong claim (mitigated by pure-function derivation and ledger proof).
- **Acceptance:** for test products at 5/3/2/1/0 sellable the labels are Available/Available/Only 2 left/Only 1 left/Ask us; stale or failed lookup → Check availability; no response contains a count ≥ 3.
- **Rollback:** flag off → no availability text, ordering unchanged.

### Phase I — Testing and validation (M)
Full matrix in §12, then a **parallel run**: the new system runs with real counter sales entered in both systems for one week with a daily zero-difference check, rehearsed with your father on a quiet day; a dress rehearsal order from creation to delivery and one exchange.
- **Acceptance:** all §12 tests pass; seven consecutive days with zero reconciliation differences.
- **Rollback:** abort cutover, continue on the artifact.

### Phase J — Production launch (M)
- **Objective:** go live safely.
- **Tasks:** fresh full backup + restore test; freeze window on a quiet day; delta import; flip Stockroom to the new backend; keep the artifact read-only for 30 days; soft launch (shared with a few known customers) for a week; then public launch.
- **Dependencies:** all above, written sign-off.
- **Acceptance:** §13 criteria.
- **Rollback:** within 30 days re-point Stockroom to the artifact, restore from the pre-cutover backup, re-enter the (small) delta from the ledger; site flips to static fallback.

**Optional, after launch (O):** AI tag reading (server-side vision call replacing the chat path; `sample` currently may not work, ❓); official WhatsApp API; barcode-scan selling; offline queue; staff notifications by email/Telegram; GST invoices; payment gateway; customer accounts.

---

## 10. Costs

| Item | Initial | Monthly | Status |
|---|---|---|---|
| Supabase Free during phases A and spike | ₹0 | ₹0 | 🔎 Free plan: 500 MB DB, 1 GB files, paused after 1 week idle, **no backups** |
| Supabase **Pro** from Phase B | — | **from US$25** | 🔎 8 GB DB, 100 GB files, 250 GB egress, daily backups kept 7 days, no inactivity pause |
| Point-in-time recovery | — | US$100 per 7 days | 🔎 *Not recommended* at this scale; the nightly export is enough |
| Edge Functions | — | included up to 2 M invocations 🔎 | |
| Netlify, GitHub | ₹0 | ₹0 | ⚠️ current plans; unchanged |
| Bot challenge, email alerts | ₹0 | ₹0 | ⚠️ free tiers, verify at build time |
| Domain (optional) | ~₹800–1,200/yr | — | ⚠️ |
| WhatsApp Business Platform (**optional**) | — | per-message; customer→you free; 1,000 free service messages/number/month from 1 Oct 2026 | 🔎 fees; India rate card not copied; ⚠️ setup effort |
| AI tag reading (**optional**) | — | measured later | ❓ not priced; pay-as-you-go with a hard cap |
| **Expected launch total** | **≈ ₹0–1,200** | **≈ ₹2,100–2,300** (US$25 at ₹85–90 ⚠️ exchange rate not checked) | |

The real cost is **your father's time**: the baseline recount, a rehearsal day, and the discipline of entering counter sales.

---

## 11. Approvals and dependencies

**Approvals I need (each in writing in chat):**
1. This roadmap and the order of phases.
2. Phase A: you run the backup; my read-only analysis of the ZIP; **separately** whether I may read the live database from chat (contains customer data).
3. Opening a free Supabase account (owner: shop Gmail), later upgrading to Pro.
4. Hosting the Stockroom copy on a second Netlify site (name to choose).
5. `AGENTS.md` rule changes: (a) first add → compact prompt instead of drawer; (b) `stockQty` per size may now be *derived into labels* (never shown as raw counts ≥ 3); (c) size filter wording; (d) the "site never claims availability" rule becomes "never claims availability beyond what the live ledger shows".
6. Contact-state wording shown to customers.
7. Opening hours (for the heartbeat rule) and the stale-after threshold (I propose 15 minutes).
8. The baseline-recount date and who does it.
9. Privacy notice text and retention period for addresses.

**Dependencies:** your laptop for the backup; shop Gmail; Netlify and GitHub access; a quiet day for cutover; ~30 days where both systems exist.

---

## 12. Test matrix (all mandatory before launch)

| # | Test | How | Pass |
|---|---|---|---|
| 1 | **Simultaneous online and counter sale** of the last piece | Scripted: web reservation and counter sale at once | Exactly one succeeds; the other gets a clear refusal; stock never negative |
| 2 | **Two customers, final piece** | 50 parallel reservation attempts on 1 piece | Exactly 1 reserved |
| 3 | **Reservation expiry** | Hold with a shortened timer; run job twice | Released once; sellable restored; ledger row; staff alerted before |
| 4 | **Never release paid stock** | Expire-time race with a payment recorded | Order stays reserved/consumed; no release |
| 5 | **Late payment after expiry** | Pay after release | Re-reserves if free; otherwise "paid, stock gone" exception into refund flow |
| 6 | **Cancelled order** | Cancel at request, confirmed, awaiting_payment | Reserved returns exactly once |
| 7 | **Returns and exchanges** | Sellable and not sellable returns; cheaper/dearer replacement; refund limit | Stock correct; refund ≤ paid; history intact |
| 8 | **Incorrect inventory count** | Recount below held; stale recount | Refused with explanation; nothing silently overwritten |
| 9 | **Network failures** | Cut shop heartbeat; block backend; drop mid-save | Labels degrade to "Check availability"; WhatsApp fallback works; no partial writes |
| 10 | **Duplicate requests** | Double tap; resubmit; re-paste | One request |
| 11 | **Rapid quantity changes** | 20 taps/second on `+`/`−` | Final quantity equals taps net, never above cap; no double add |
| 12 | **Cart persistence** | Reload, new tab, storage blocked, 7-day expiry, sent-cart 30-min rule | Behaves as specified; no crash without storage |
| 13 | **Product variant availability** | Same product, sizes at 5/2/1/0; two colours | Per-size labels correct; sizes never merge |
| 14 | **D3 honesty** | Compare labels against the ledger over a day of mixed activity | Every shown number reconciles to the ledger |
| 15 | **Security** | Anonymous probes of every table and function | No unpublished, private or personal data returned |
| 16 | **Backup/restore** | Full restore into an isolated project | Identical counts and hashes |
| 17 | **Offline-store procedure** | Rehearse the paper-slip outage with your father | Entries reconcile with zero unexplained difference |

---

## 13. Launch acceptance criteria

All must be true, with evidence recorded:
1. A fresh full backup exists and a restore from it has been proven.
2. Product data, images, sizes, prices and the published flag on the website equal Stockroom, verified by an automated comparison.
3. The baseline recount is done; the reconciliation report shows zero differences for seven consecutive days of parallel use.
4. All §12 tests pass.
5. Website requests appear in Stockroom without manual work; no status wording claims more than is known.
6. Reservations, deductions, cancellations and releases behave as specified, including expiry.
7. Low-stock labels derive only from the ledger and degrade to "Check availability" when data is stale.
8. Outage and rollback procedures have been rehearsed with the people who will use them.
9. No secret in any client file or in git; anonymous access limited to the public view and two functions.
10. Privacy notice published; retention rule set.
11. Your explicit written go-ahead.

---

## 14. Recommended first safe milestone

### Milestone 0 + 1 — "Prove it before we touch it" (no production change)

| Step | What | Touches production? |
|---|---|---|
| 1 | You run the in-app *Download full backup* on the laptop. | No (read-only button) |
| 2 | I run the read-only verification script on the ZIP and report counts, hashes, relations and gaps. | No |
| 3 | **Spike A:** a throwaway, empty test page (not Stockroom) to learn whether a Claude artifact may call an outside server. ❓ answers C8. | Publishes a private test artifact only |
| 4 | **Spike B:** free scratch Supabase project: a table with the reservation function, 50-parallel race test, and a scheduled expiry test with a fake hold. | No (scratch project) |
| 5 | Dry-run import of the backup into the scratch project and a round-trip diff. | No |
| 6 | I deliver: verification report, spike results, the current-system document, and an updated roadmap with real numbers. | — |

**Exit criteria:** zero unexplained missing photos; counts match your screens; race test yields exactly 1 winner; expiry job releases a test hold once; round trip shows no data differences; C8 answered. **Rollback:** delete the scratch project and test artifact; Stockroom and the website were never changed.

**Needs from you:** approval of this roadmap; the backup ZIP location; permission for the two spikes; a free Supabase account on the shop Gmail. Optionally, separate permission for the read-only second export from chat.

---
*Stopped as instructed. No implementation, migration, deployment or data access has taken place.*


---

# v2 — Owner decisions of 25 Oct 2026 (these REPLACE the conflicting parts above)

Replaced: the 15-minute heartbeat (§6/§7), the 7-day dual entry (§9 Phase I), restore-a-backup rollback (§9 Phase J, §12), and "scratch projects everywhere" (§14). Everything else stands. Status of work already done is at the end.

## V2.1 What is real data and what is experimental

| System | Real business data? | Rule |
|---|---|---|
| Stockroom database (products, orders, customers' names/phones/addresses, payments, refunds, stock history) | **YES** | Read-only until Phase A is verified. No test writes, ever. |
| Stockroom photos (asset store) | **YES** | Never deleted or re-uploaded by experiments. |
| `O4U_Inventory_Master_Sept2026.xlsx`, `O4U_Stock_Inventory_UPDATED_v2.xlsx`, `stockroom.json`, `website/images/` | **YES** (business records) | Edit only through the existing build; never overwritten by tests. |
| `website/stock images/`, `product-photos/` (raw photography, 1.1 GB) | **YES** (irreplaceable) | Never committed, never touched. |
| `website/` code, `index.html`, `config.js`, tests, AGENTS.md | No: code, versioned in git | Change freely; commit per step. |
| `stockroom/stockroom-dev.html`, `stockroom/dev/*` | No: development copy | Change freely. The v44 original is kept byte-for-byte beside it. |
| The live Netlify site (reachable by URL even though unannounced) | Customer-visible | Treat as public: nothing private in it; publish only on your approval. |
| Dev Supabase project (to be created) | No: **synthetic data only**, flagged `is_test` | One free project. |
| Production Supabase project (created at cutover) | **YES** | Pro plan, backups on, only then do real records arrive. |
| The WhatsApp number in `config.js` | **YES** (real customers) | Tests never navigate to it: `window.open` is stubbed and DNS is blocked in the headless runner. |

Two environments in total (dev with fake data, production with real data) plus Netlify's built-in deploy previews for the website. No other duplicates.

## V2.2 Payment, hold expiry, late payment

**Limit stated plainly:** with no payment gateway and no bank/UPI integration, the database cannot know that an unrecorded UPI payment has happened. Software can only (a) shrink the window, (b) make the staff step hard to forget, and (c) make the failure case safe and cheap. It cannot guarantee that a hold is never released while a payment is in flight.

**Three different facts, never merged**

| Fact | Who says so | Stored as | Effect |
|---|---|---|---|
| **Payment reported** | the customer ("I paid", a screenshot on WhatsApp) | `payment_claimed_at`, note | **Freezes the expiry clock** and puts the order at the top of "Needs attention". It is *not* money. |
| **Payment verified** | staff, after seeing the credit in the UPI app | `payment_verified_at`, UPI reference, amount, staff name | Only this moves the order to `paid`. The UPI reference must be unique (already enforced today). |
| **Payment recorded** | the system | an append-only `payments` row, written in the same transaction as the status change | Immutable. Corrections are new rows, never edits. |

**Expiry rules**
1. Hold = 2 hours from the moment staff reserve stock (D1).
2. **T−30 min:** the order appears at the top of Needs attention ("Hold ends in 18 min: check the UPI app") and the Dashboard marks it red. (Built.) Optional later: a phone alert.
3. **A reported payment freezes the clock.** Auto-release only ever touches orders with *no* claim. A frozen order never auto-releases; it waits for staff, and shows how long it has waited.
4. **At T+0, only unclaimed holds are released**, by one database function inside one transaction:
   - `SELECT … FOR UPDATE SKIP LOCKED` on `awaiting_payment` orders whose `hold_until` has passed and that have no claim;
   - re-check the status after locking (a payment recorded a millisecond earlier wins);
   - decrement `reserved` by the order's quantities, set status `hold_expired` (not `request`), write an event whose key is `order_id + hold_version + "release"` with `ON CONFLICT DO NOTHING`.
   Run twice, it releases once. A paid, packed, dispatched or cancelled order can never match the query.
5. Constraints `reserved >= 0` and `reserved <= on_hand` make a double release or double reserve impossible even if the code were wrong.
6. **Late payment** (money arrives after release): staff press *Record payment* on the `hold_expired` order. The function tries to re-reserve atomically:
   - piece still free → order becomes `paid`, nothing else happens;
   - piece was taken → status `paid_stock_gone`, which creates an approved refund automatically and lands at the top of Needs attention. The customer is never left paid-but-unserved and nobody has to remember.
7. **Soft protection against re-selling a just-released piece:** for 30 minutes after an auto-release, staff trying to reserve or sell that exact size see "This piece was released 12 min ago from an unpaid hold. Check the UPI app first." One tap to continue.
8. One-tap **Extend hold by 30 minutes** for staff (max twice), logged with who and why.
9. The customer's payment message states the exact deadline and asks them to send a screenshot straight after paying.

**Operational compromise you must accept (decision D4):** in the rare case where the customer pays close to the deadline *and* nobody tells you *and* another customer is then sold that piece, the second order is honoured on a first-confirmed basis and the late payer gets a **full refund** by UPI. Cost: one refund transfer; no stock error; no silent loss. If you prefer zero auto-release, the alternative is: *no auto-expiry, only alerts*. I do not recommend it: forgotten holds block real sales.

## V2.3 Store outages and stock accuracy

| Option | Verdict |
|---|---|
| Staff **Store offline** switch | **Yes.** The simplest, most reliable signal: a person knows the router is down. |
| Automatic heartbeat | **Yes, as the safety net.** Stockroom pings every minute while it is open; **3 minutes** without one flips the state automatically (was 15). |
| Shorter freshness | **Yes.** Website stock data is trusted for 60 seconds at most (built). |
| Immediate fallback to "Check availability" | **Yes**, for every size, the moment the state is *offline* or *heartbeat lost*. Ordering stays possible. |
| Warning inside Stockroom | **Yes.** A red bar across the top: "Store is offline: write sales on paper." |
| Reconciliation on return | **Yes**, a three-step screen (below). |

**Heartbeat proves connectivity, not accuracy.** So the wording is chosen to stay honest even when "connected": "Available" means *recorded as available*. Three habits keep that true, each a single tap for your father:
1. **Sold in shop**: unchanged, made as short as possible.
2. **End-of-day "All sales entered ✓"**: records who confirmed and when. The Dashboard shows "Last confirmed complete: yesterday 8:12 pm, by Dad" and warns when a trading day was never confirmed.
3. **Recount nudges**: the Dashboard already lists products not counted in 60 days; a recount is two taps from the list.

**Back online:** *Store back online* opens a 3-step screen, no jargon:
1. *Enter the paper slips* (Sold in shop with a "sold at" time).
2. *Problems found*: any slip that would take a size below zero or into held stock is listed with options (release a hold / contact the web customer / record anyway as correction). Nothing is silently overwritten.
3. *Count what moved*: a short list of only the sizes touched while offline; confirming sets them as verified.
Only after step 3 (or an explicit "I've checked") does the website return to live labels.

## V2.4 Transaction-preserving recovery

**Principle:** the append-only **event log is the truth**; current-state tables (stock levels, order status) are projections written in the same transaction. A backup is just a *starting point*; nothing after it is ever lost because it can be replayed.

- `events(seq, id, type, entity, entity_id, payload, idem_key UNIQUE, actor, at, source)`: no UPDATE or DELETE permission for anyone, including the app.
- Event types cover everything you listed: `stock_moved` (counter sale, recount, damage, restock, return), `order_requested`, `order_confirmed`, `stock_reserved`, `hold_released`, `payment_claimed`, `payment_verified`, `refund_approved`, `refund_sent`, `exchange_*`, `customer_updated`, `offline_slip_entered`.
- Every action carries an idempotency key (e.g. `W2510-K7M3-ZP`, `order+hold_version+release`, `case+received`). Replaying an event whose key already exists changes nothing.
- **External journal:** an hourly job exports new events (JSON lines) to a private location *outside* the database. Worst-case loss after a total database loss is under an hour of events, recoverable from the paper slips and WhatsApp.

**Recovery procedure (R)**
1. Never restore *over* production. Restore the latest daily backup into a **new** project.
2. Read its highest event `seq` (the watermark).
3. Replay every journal event with a later `seq`, in order, through the same functions the app uses. Existing idempotency keys are skipped, so running the replay twice gives the same state.
4. A replayed event that would now break a rule (e.g. a sale that oversells because a restock event was lost) is **not forced**: it goes to a "conflicts" list for a human.
5. Run the integrity report: Σ events = stock per size; each order total = its lines; each refund ≤ what was paid; counts per type equal the journal's.
6. Only when the report is clean, point the apps at the restored project.

**Returning to the Claude artifact after cutover** (if ever needed within the 30-day window): export the events since cutover as a "replay pack"; order and move documents use deterministic ids derived from the idempotency keys, written with *set* semantics, so a second application cannot duplicate; stock maps are recomputed from the ledger and shown as a diff for approval before writing.

**Proof before cutover (mandatory):** a rehearsal on the dev project with synthetic data: 200 events covering every type above, a snapshot at event 100, a simulated disaster, restore into a fresh project, replay events 101–200 **twice**, plus one deliberately duplicated event and one deliberately conflicting (overselling) event. Pass = identical state to the original, zero duplicates, the conflict reported not applied. Its output is part of the launch evidence.

**Needs your decision (D5):** where the hourly journal lives. Options: a private folder in the shop's Google Drive, a Cloudflare R2 bucket, or a second small Supabase project. Drive is simplest for you to see and costs nothing.

## V2.5 No arbitrary seven-day double entry

Dual entry is **not required**. Equivalent confidence comes from:
1. **Shadow validation (read-only):** import the verified backup, then compare automatically: counts per collection, every order's lines and totals, every ledger chain, every photo hash. Zero-diff required.
2. **Controlled test transactions:** about 25 scripted synthetic transactions (flagged `is_test`, excluded from the dashboard and the website) through every flow: counter sale, web request, reserve, expiry, late payment, cancel, return, exchange, refund, recount, outage and reconciliation.
3. **Automated integrity checks**, run daily and shown in Business health.
4. **A single-entry pilot day:** at cutover the new system is the *only* one used. The artifact is frozen read-only for reference. If the first day shows a problem, procedure V2.4 returns to the artifact with nothing lost.

Extra work for your father: **none duplicated.** Only the one-time baseline recount (a launch requirement because low-stock claims must be genuine) and the daily "All sales entered" tap. If a period of dual entry ever proved necessary (a rule failing the controlled tests), it would be limited to the *failing flow*, for one day, with the reason stated first.

## V2.6 Roles (dashboard and Stockroom)

| Role | Sees | Can do |
|---|---|---|
| **Owner** | everything incl. sales totals, refunds, cost and profit (when cost exists), customers, settings, backups | everything, grants access |
| **Store manager** | all operational data and sales totals, no cost/profit, no settings | capture, stock, orders, exchanges, refunds approval |
| **Staff** | products, stock, orders needing action, counter sales entry | Sold in shop, capture, recount, pack, dispatch; **not** revenue figures, refunds approval, customer exports |

Enforced in the database (Supabase Auth roles + row-level rules and views), not by hiding screens. In the current artifact there is no login, so these roles can't be enforced there: that is one more reason the Stockroom moves to its own hosting at Phase C.

## V2.7 Status of the first authorised work (25 Oct 2026)

| Item | State |
|---|---|
| AGENTS.md: first-add sheet, steppers, availability labels, backend-approved-in-principle | Done |
| Website: first-add sheet, `[-] n [+]` on cards / product view / bag, availability labels with caps, send blocked when the bag exceeds what is left | Done, 120 automated checks pass (80 existing + 40 new), checked visually at phone width |
| Stockroom dev copy with the new dashboard (needs-attention, KPIs, sales-by-channel chart, inventory alerts, orders, health, product performance, financial overview with definitions, stock sheet kept) | Done in `stockroom/` (dev copy only), 51 automated checks pass on synthetic data |
| Live availability feed, orders → Stockroom, reservations, expiry job, store switch/heartbeat | **Not built**: need the backend (Phase B) |
| The new dashboard published into the real Stockroom artifact | **Not done**: needs your approval (it replaces a page of the live app) |
