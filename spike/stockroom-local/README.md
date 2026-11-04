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
