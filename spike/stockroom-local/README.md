# Stockroom local feasibility spike (experiment only)

Question: can the **existing, unmodified** Stockroom page (`stockroom/stockroom-v44-original.html`) run outside the Claude artifact, on its own
host, if something supplies the `window.claude.use("db" | "assets" | "downloads" | "sample")` runtime? Local only, invented data only. Nothing here is
pushed, deployed, or connected to Supabase, the website or production data. **This is not a proposed production architecture.**

```
server.py            serves the page from disk with ONE tag injected (+ JSZip CDN URL -> local copy, in memory), and a small JSON API
pgdev.py             persistent throwaway PostgreSQL in ./.data/pg  (gitignored)
schema.sql           spike_docs (JSON documents), spike_leases (real locks), spike_assets (photo metadata) - TEMPORARY tables
static/claude-shim.js  the runtime stand-in: db (REST + server-sent events from LISTEN/NOTIFY), assets (files on disk), downloads (<a download>), sample = null
browser_tests.js     Playwright/Chromium checks      run_spike.py   orchestrator, file validation, restart test, PASS/FAIL/BLOCKED table
```

Run: `npm install --no-save jszip@3.10.1` (once, in this folder), `pip install "psycopg[binary]"`, OS PostgreSQL + node/playwright, then
`python spike/stockroom-local/run_spike.py` (about 1.5 minutes). The original HTML is never modified. `dev/mock-claude.js` (in-memory, `db`+`downloads` only)
was inspected and **not** used: it has no assets, no leases and loses data on reload.

## Results (actual run, 4 Nov 2026, PostgreSQL 16.15, Chromium via Playwright, 390x844 touch viewport): 22 PASS, 0 FAIL, 0 BLOCKED

| # | Item | Result | Evidence |
|---|---|---|---|
| 1 | Load invented products from persistent storage | PASS | 14 products from PostgreSQL rendered; first row shows its own colour |
| 2 | Edit, reload, edit still there | PASS | the page's own Save button; value in the database and shown after reload |
| 3 | Photo upload with real file storage | PASS | 2 JPEGs through the page's file input -> files in `.data/blobs` (JPEG magic checked) -> `/_blob/<id>` -> decoded 900x1200; still shown after reload |
| 4 | Capture draft survives a killed tab | PASS | new tab shows "Unfinished product", Continue restores both photos and the piece count |
| 5 | `sample` unavailable, manual entry kept | PASS | no Read-tag button; product typed by hand saved with photo and stock. **The page has no message of its own** for this: the shim adds a visible notice |
| 5b | In-page camera code path | PASS (limited) | Chromium **fake** video device: live view opens, shot uploads. Not a phone camera |
| 6 | CSV download | PASS | BOM, 15 rows x 20 columns, per-product totals equal the database (validated in Python) |
| 7 | ZIP downloads | PASS | website-images ZIP byte-identical to the stored photos; full-backup ZIP: `testzip` clean, document counts and 4 photos equal the database |
| 8 | Real lock | PASS (conditional) | see below |
| 9 | Restart server AND PostgreSQL | PASS | edit, photos and a draft all still there |
| - | No uncaught page errors | PASS | all pages used |

### Leases and concurrent stock edits
`ref.acquire({holder, ttlMs})` is implemented as one atomic `INSERT ... ON CONFLICT DO UPDATE ... WHERE expired OR same holder` per document in PostgreSQL.
* HTTP level: 30 simultaneous holders -> exactly 1 acquires; the holder renews; others refused until expiry; expiry works. Mutating the SQL (always grant / never expire) fails these checks.
* Browser level: two Chromium contexts ("phones") call the app's **own** `O4U_ops.moveStock` (15 sales each, same product, same time): final stock = 60 - successful moves, one ledger row per move, 0 lost updates (one call gave up with the app's "busy" error). The **same race with `acquire` switched off lost updates** (6 and 15 in two runs), so the test can fail.
* **What this does and does not prove.** Stock writes are safe only while every writer takes the lease and finishes inside the TTL (8 s). Not protected: the product update and the `stockmoves` ledger row are two separate requests (a crash between them leaves stock changed with no ledger row; not tested); no fencing token (a write slower than the TTL can overwrite a newer one); the app never releases a lease, so a second phone waits for the first one's TTL (up to 8 s, the app retries ~10 s); the same tab re-acquires its own lease (two concurrent actions in one tab are not serialised). Orders and cases use the same leases (`withLeases`-style code at lines ~3290 and ~3668); **only the stock path was exercised**. Verdict: acceptable for a prototype, **not** accepted as stock-write safety for production; the real fix is a single database function that changes stock and writes the ledger in one transaction.
* Assumption: the real artifact runtime's `acquire` semantics are inferred from how the app calls it (holder, ttlMs, `.acquired`, never released); the spike implements those semantics, it does not copy the platform.

### Tag reading ("Claude tag reading is not preserved")
`sample` is `null`. The page then never offers "Read tag"; **Save** stores a *pending* product ("Waiting for Claude") or you use "Type the tag details myself". No paid API, no key. A manual workflow, **not tested here**: (1) shop saves the product with photos as pending or types details; (2) the owner exports/pastes the pending product's photos into a Claude chat (a person, a subscription chat, not an API) and asks for the same JSON the page's prompt requests; (3) the owner pastes the reply into the manual form. Limits: a human in the loop for every product, no automatic "waiting for Claude" resolution (that path writes `readcopies` from inside the artifact), no batch reading, photo size limits of the chat, copy-paste errors; the existing 'pending' list would need a manual "resolve" screen. Automatic reading would need a server-side model call with a key: a paid service and an owner decision, **not introduced**.

### Temporary JSON document table vs the relational backend (no architecture chosen)
`spike_docs` mirrors the page's collections (products, orders, stockmoves, drafts ...) as JSON. The relational backend (migrations 0001-0009) has its own `products/variants/stock_levels/stock_events/orders/...`. Running both would give two sources of truth for stock and orders. Ways a future adapter could avoid conflicts (options, not a decision):
1. **One writer per entity.** Stock, orders, payments, refunds and the ledger live ONLY in the relational tables; the adapter maps the page's `stock`/`orders`/`stockmoves` reads to views and turns the page's writes into calls of the existing SECURITY DEFINER functions (`receive_stock`, `confirm_and_reserve` ...). The JSON table then holds only things with no business meaning for stock: drafts, readcopies, config, UI notes.
2. **Never store derived stock in JSON.** `products.stock` in a document would be computed from `stock_levels` on read and ignored on write, so it cannot drift.
3. **Idempotency and ids:** reuse the page's ids (`slug(article+colour)`, `W...` order codes) as the keys the relational side already uses (`products.id`, `orders.ref`), and the existing idempotency keys, so a replay cannot create a second record.
4. **Fail loudly:** a nightly reconciliation (sum of ledger = on-hand per size; no entity present in both stores with different values) and a rule that a document write to a relational-owned collection is refused by the adapter.
The spike proves none of this; it proves only that the page runs against *a* document store.

### Browser results vs assumptions
Verified in a real browser: everything marked PASS above (Chromium, touch viewport emulation, real file inputs, real downloads, real reloads, a closed-tab recovery, a server+database restart). **Not verified / pending:** a real phone (camera app, `capture="environment"`, Android evicting the tab, photo sizes from a real camera, network drops), HTTPS hosting and login (no authentication in the spike: anyone who can reach the port can read and write), Safari/iOS, the dev-v2 dashboard on this shim (not run), Orders/Exchanges screens end to end, behaviour with 1000+ documents (the page's 1000-document read cap and backup warning are unchanged), the real artifact runtime's exact semantics.


---

# Part 2: atomic, retry-safe stock moves (5 Nov 2026)

Goal: close the biggest gap of part 1 (stock and its history were two requests, protected only by a lease) **without creating a second inventory system**.

## What was reused and what was added
* **Reused unchanged:** `stock_levels`, `stock_events` (append-only ledger), `apply_stock_event` (the one writer: it updates the row and inserts the ledger row), `lock_stock_rows`, `idem_begin/idem_end`, `require_role`, `count_pending`, reserved-vs-free rules.
* **Added (backend, local only, NOT applied to any hosted project): `backend/migrations/0010_stock_moves_atomic.sql`**, one function `apply_stock_moves(key, moves[, reason])` built on those pieces: all lines or none, rows locked in id order, DELTA applied to the locked current row (never an absolute overwrite), cannot go below what is held for customers, recount applies only if on-hand is still what the counter saw (`expect_on_hand`), same key + same contents replays the stored answer, same key + different contents is refused, `recount` needs manager rank. Existing ledger kinds only (sale, dispatch, return_in, receive, adjust, recount).
* **Spike layer:** `POST /api/stock/moves` runs `apply_stock_moves` and writes the page's `stockmoves` history copy in the **same transaction** (deterministic id from the key, so a replay cannot duplicate). Product documents' `stock`/`inStock` are overlaid from `stock_levels` on every read and **stripped from document writes** for products the relational side owns, so there is one writer. `static/claude-shim.js` gained `use("stock").move`, which reuses ONE key for every retry and retries only network failures.
* **Why the page itself had to change (isolated copy):** `moveStock()` reads a product, computes an absolute stock map in the browser, writes it, then writes history in a second request. A shim only sees two unrelated calls: it cannot know what stock the number was based on, cannot join the two writes, cannot tell a retry from a new action. `patch_app.py` generates `.data/stockroom-v44-atomic.html` from the untouched original (served at `/stockroom?v=atomic`; diff in `app/moveStock-atomic.diff`, two hunks: `moveStock()` and the stock-edit call site that passes `expect` for a recount). `git diff -- stockroom website` stays empty.

## Evidence (actual runs, 5 Nov 2026, PostgreSQL 16.15, Chromium via Playwright)
Command: `python spike/stockroom-local/run_spike.py` -> **34 PASS, 0 FAIL, 0 BLOCKED** (the 22 part-1 checks unchanged + 12 new). Backend: `python backend/tests/run_db_tests.py` -> **72 passed, 0 failed, 0 skipped** (was 66 documented; +6 for 0010).

| Required test | Database level (`run_db_tests.py`) | Through the spike (HTTP / real browser pages) |
|---|---|---|
| Two clients, final piece: exactly one succeeds | 6 rounds x 12 simultaneous connections: 1 sold, 11 refused "only 0 free", 1 ledger row | **H1** 12 simultaneous HTTP requests: 1 x 200, 11 x 409 `short`; **A1** two real Chromium pages calling the app's own `moveStock` at the same instant, 6 rounds: exactly one succeeds each time, loser sees the database's message, one ledger row, one history copy |
| Failure between stock update and ledger insert: both roll back | trigger fails the ledger insert (single and second-line-of-two): stock, ledger and idempotency key all unchanged; **a backend process killed with `pg_terminate_backend` while asleep inside the ledger insert**: nothing committed, no half key | **H2** same fault through the endpoint; **H3** fault in the *history copy* insert (after stock and ledger were written) rolls back stock_levels + stock_events + key; **H4** real backend kill mid-request; after each, the same key retried succeeds exactly once |
| Lost response, then retry: one deduction, one ledger entry | same request twice: identical answer, one deduction; 5 simultaneous copies: one deduction; same key + different contents refused | **H5** (HTTP: twice, 6 simultaneous, different contents); **A2** the browser's response is dropped AFTER the server committed (Playwright `route.fetch()` then `abort`): the page retried automatically with the same key (2 requests), stock 10 -> 8 once, 1 ledger row, 1 history copy |
| Delayed / expired lease holder cannot overwrite newer stock | stale recount (saw 10, now 9) refused "stock changed while counting"; a late sale lands on top (9 -> 8) | **H6** lease TTL 300 ms expired, B takes it and sells; A's late sale applies as a delta (10 -> 9 -> 8), A's stale recount 409 `stale`, a stale absolute `stock` PATCH is neither applied nor stored; **A3** same with two real pages and A's request held 2.5 s; **A4** two pages, leases switched OFF, 2x15 sales: 30/30 applied, stock 60 -> 30, 30 ledger rows (the old path lost 6-15 of the same race, part 1 check 8b) |
| Persistence | | **R1** server AND PostgreSQL restarted: 9 stock rows, 48 ledger rows identical, ledger still explains every shelf |

After every HTTP scenario `assert_ledger()` checks: per variant `on_hand` = sum of ledger deltas (and `reserved`), never negative; per product the page's history copies sum to the authoritative ledger; the document the page reads equals the relational stock.

**Sensitivity (can these tests fail?).** `run_mutations.py` 35-42: eight deliberate breakages of 0010 (no key-content check, no stale-recount check, no free-stock check, stock changed without a ledger row, answer never stored, rows not locked, staff may recount, public may call it): **8 of 8 detected**. `run_spike_mutations.py`: five breakages of the spike layer (new key on every retry, no single transaction, document writes may overwrite relational stock, stale document read, recount without what the counter saw): **5 of 5 detected** - one of them (document overwrite) survived the first version of H6 because reads were overlaid, so H6 now also inspects the stored document. API suite `backend/api_tests`: the new function was added to its role matrix (`ctx.py`) but **that suite could not be run here (no PostgREST binary in this sandbox); unverified**.

## Remaining gaps (honest list)
1. **Not routed:** capture/"New product" initial stock, the product page's stock editor (`o4u:stockedit` event) and everything else that writes `products.stock` as a document. For products the relational side owns those writes are ignored (no competing number), but their history lines are still written as documents; new products created in the page have no relational rows until a catalogue-sync step exists. Only `moveStock()` (Sold in shop, New stock, Damaged, Recount, Dispatch, Return, Replace) is atomic.
2. **Orders/holds remain documents:** the page's "held for orders" check reads order documents client-side; the relational `reserved` column is not driven by the page's orders. A sale and an order confirmation are still not atomic with each other. Orders and cases still use leases only.
3. The relational catalogue in the spike is seeded from documents (price taken from the first MRP, otherwise 100 paise); that mapping is a spike convenience, not a design.
4. **No authentication:** the spike server acts as two invented staff identities; role checks run in the database but anyone reaching the port can use them.
5. The lease is still advisory UI protection; correctness no longer depends on it for stock, but order/case flows still do.
6. `kind` mapping from page kinds (`replace` -> sale, `damage` -> adjust, ...) is an assumption; `dispatch` here does not touch `reserved` (the real order flow's `dispatch_order` does).
7. Not tested: real phone, flaky mobile networks beyond one dropped response, Safari/iOS, load beyond 12 simultaneous requests, `pending_blocks_counter_sales` policy for this path, hosted Supabase (PostgREST/RLS path) for `apply_stock_moves`.

## Smallest next step supported by these results
Route the **remaining stock writers** through `apply_stock_moves` in the isolated copy (capture's initial count and the product-page stock editor), then add one catalogue-sync function so a product created in the page gets its relational rows in the same transaction. That removes gap 1 and lets a full "capture -> sell -> recount" walk-through run against one stock owner.


---

# Part 3: Capture and the product stock editor on the relational backend (5 Nov 2026, local branch `spike/integration`)

Goal: the integrated copy of the page (`/stockroom?v=atomic`, generated by `patch_app.py` + `page_integration.py`; the original `stockroom/` files are untouched)
saves Capture's quantities and the product stock editor through the relational backend, shows failures, and never drops a stock edit silently.

## What changed
* **Backend (local only, not applied anywhere hosted):** uses migration `0011_catalogue_sync.sql` (`sync_catalogue_product`) and `0010` (`apply_stock_moves`).
* **`POST /api/catalogue/save`** (server.py): ONE transaction = `sync_catalogue_product` for sizes the product does not have yet (a new product is created UNPUBLISHED, first quantities as `receive` ledger rows;
  an existing product's own relational values are passed back unchanged) + `apply_stock_moves` RECOUNT lines (counted, `expect_on_hand` = the number the person saw) for sizes it already has
  + the page's history copies. A save is stored under its key and a replay answers from the stored result; the same key with other contents is refused.
* **Page copy:** `saveProduct()` (new and existing product) and `saveStockEdit()` call the endpoint BEFORE writing any product document; a refusal shows a plain-language message
  (Capture's red line; the stock editor stays open with an alert) and nothing is written. Product documents are written without stock. The `o4u:stockedit` history logger is skipped for capture/edit (the server already wrote the line).
  Keys are `salt + hash(content)`: a second tap with the same content replays, changed numbers are a new action.
* **Never silent:** in the integrated copy the shim sends `X-Stock-Strict: 1`; the server then answers 409 `stock_owned` to a document write that carries a different `stock`, a hand-set `inStock`,
  or stock for a product the shared stock does not know. The page's "In stock" switch now says it is worked out from the rack. (The Cloud spike checks keep the old silent-strip behaviour: they do not send the header.)
* **Switched off (not connected to the shared stock):** saving a product "for Claude to read later" (pending), "other colours" in Capture, the **Orders** and **Exchanges** tabs (greyed, a message on tap, a stored tab is redirected). Holds and order actions are therefore not available here.
* **Portability:** `pgdev.py` uses the `pgserver` pip package when no OS PostgreSQL exists (Windows/macOS); the Linux path is unchanged. `server.py` reads SQL as UTF-8 and drains the body of `/api/_spike/reset`.
* Behaviour change the owner should know: a NEW product now needs the MRP of at least one size (the shared stock requires a price); without it the page says so and saves nothing.

## Evidence (actual runs, 5 Nov 2026, Windows 11, PostgreSQL 16.2 via pgserver, Chromium in the Claude desktop browser pane)
| Check | Result |
|---|---|
| `python backend/tests/run_db_tests.py` (0001-0011) | **75 passed, 0 failed, 3 skipped** (the 3 Windows skips) |
| `python spike/stockroom-local/integration_http_tests.py --port N` (new, HTTP level) | **10 passed, 0 failed**: capture creates an unpublished product with first quantities in the ledger; the same save twice counts once and the same key with other contents is refused; a recount applies with the seen number and a stale one is refused (409 `stale`) leaving stock untouched; a new size is added and existing sizes untouched; capture of an existing product changes no product row; a failed save leaves nothing and the same key works after the fix; details edits cannot overwrite stock (409 `stock_owned`, also for a product the shared stock does not know); a hand-set `inStock` is refused; **20 rounds of simultaneous sale vs recount** (19 refused as stale, 1 applied first) never lose a piece and the shelf equals the ledger |
| Real UI, stock editor (page in Chromium, clicks on the page's own buttons) | PASS: +2 pieces saved (6), still 6 after reload; **another phone's sale during editing -> "Nothing was saved: the stock changed while you were editing (... was 6 ... is 5 now)", editor stays open, no recount recorded, stock untouched**; reopened, +1 saved; **lost answer** (server commits, reply dropped, page retries with the same key): 2 requests, ONE recount, stock 7, ledger consistent; a details edit (notes) after another phone's sale left stock at the live value |
| Real UI, Capture (new product, photo through the file input, pieces M=2 L=1, manual entry) | PASS: with no price -> "Nothing was saved: enter the price (MRP)...", capture stays open, nothing created; with a price and a **dropped first reply** -> product created once, `published=false`, stock M2 L1, ledger = 2 `receive` rows "initial stock at capture" (no duplicates), 2 requests with the same key, photo stored, capture closed |
| Orders / Exchanges tabs | PASS: greyed (`aria-disabled`), tap shows the message |
| `run_spike.py` / `browser_tests.js` (Cloud's 34 Playwright checks) | **BLOCKED** here: needs Node.js + Playwright (not installed; not installed by me) |
| `backend/api_tests` (API permission tests incl. the 0011 role-matrix entry) | **BLOCKED**: needs a PostgREST binary |
| `run_spike_mutations.py` (spike-layer mutation runs) | **BLOCKED** (same Playwright dependency); the new checks were not mutation-tested |
| Real phone, Safari/iOS, poor networks beyond one dropped reply | **NOT RUN** |

The UI checks were driven from the browser pane's JavaScript console (events dispatched on the page's real controls, `fetch` wrapped to drop one reply), not by a Playwright script, so they are not yet repeatable by command.

## Remaining gaps
1. The stock editor and Capture-of-existing use **recounts**, which the database allows for **manager** rank only; the spike server acts as the manager for them. Whether staff may recount (or a different delta-based action is wanted) is an owner decision. Staff creating products is provisional, not an approved policy.
2. Price edits in the page (the MRP boxes) change the page document only; the relational price is set at creation. A change of price needs its own backend call.
3. Orders, holds, exchanges, pending (Claude-read) products and other-colour capture are switched off, not integrated. A sale and an order confirmation are still not atomic together.
4. No authentication (the server acts as two invented staff); no hosted PostgREST/RLS path for 0010/0011; Cloud's Playwright checks and the new UI checks are not in one repeatable runner.
5. A new product with no MRP cannot be saved (by design of the shared stock); Capture offers no "price later".
