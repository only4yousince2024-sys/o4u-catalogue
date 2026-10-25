# O4U — Stockroom & Website Integration
## Phase 1: Technical Audit (read-only)

Date: 25 Oct 2026 · Scope: audit and recommendation only. Nothing was modified, deployed, created or migrated.

**Legend:** ✅ VERIFIED = seen directly in a file or the live artifact source · ⚠️ ASSUMPTION = inferred or from memory, must be tested · ❓ UNKNOWN = could not be established.

---

## 0. What I could and could not inspect

| Item | Status | Detail |
|---|---|---|
| Stockroom HTML | ✅ obtained | Not in the project folder. I fetched it read-only from the published artifact (`claude.ai/artifact/XWwnomLQXZEAb1Gxm8LZFk`, owned by this account). Version string in the code: **v44, 14 Oct 2026**. 3,927 lines, 285 KB, one file. Saved locally by the tool; I treated it as data only and changed nothing. |
| Website source | ✅ available | `D:\CLAUDE PROJECTS\ONLY 4 YOU`, remote `github.com/only4yousince2024-sys/o4u-catalogue`, 61 commits. `website/` is what Netlify publishes (`netlify.toml`: `publish = "website"`, no build command). |
| Stockroom **database contents** (products, orders, customers, money) | ❓ not read | The HTML contains code, not data. Data lives in Claude's artifact database. I did **not** query it (it holds customer names, phones, addresses). Counts and field-level facts below come from the code, not from records. |
| Stockroom **photos** | ❓ not read | They live in the artifact `assets` store (`/_blob/<id>`). Not reachable from the HTML or from chat. |
| Live website | ❓ not loaded | I audited the repo, not the Netlify deployment. |
| Netlify / GitHub account settings, Higgsfield, any API keys | ❓ not accessed | |
| Any previous full-backup ZIP | ❓ none found in the project | A wider disk search did not complete, so "none exists" is **not** established. |

**Stale-data warning (✅):** `stockroom.json` and `website/products.js` in the repo were last generated **17 Sep 2026** (6 products, old six-category schema). The `AGENTS.md` rules describe the v43 nine-category format. So the repo's data is behind Stockroom v44, and `O4U_Stockroom_Handbook.md` (v23, 24 Sep) is behind the code too: it does not mention Orders, Exchanges, Dashboard, backup or leases at all. **The HTML is the only reliable description of Stockroom.**

---

## 1. Existing architecture

```
 SHOP PHONE / LAPTOP
 ┌────────────────────────────────────────────┐
 │ O4U Stockroom  (one HTML file, claude.ai)  │   no login of its own: access = the owner's
 │  tabs: Capture · Inventory · Orders ·      │   Claude account. "Who" (Dad/Khush/Staff) is
 │        Exchanges · Dashboard               │   a dropdown in localStorage — attribution only.
 └──────┬───────────┬───────────┬─────────────┘
        │ db        │ assets    │ sample / downloads
        ▼           ▼           ▼
  Claude artifact  Claude blob   Claude model call /   (all four are Claude-platform
  document DB      storage       browser file save      runtime services)
        │
        │  "Download for website" → ZIP (images + stockroom.json)  — MANUAL
        ▼
 PC: sync.bat → unzip → scripts/build_catalogue.py → website/products.js
        → git commit/push → Netlify (static) → only4you-store.netlify.app

 CUSTOMER → static site → cart (localStorage) → wa.me WhatsApp message with an
 "O4U ORDER" block + check code → shop → (owner copies the message) →
 Stockroom "Paste order from WhatsApp" → order record
```

Stockroom is not a client of the website and the website is not a client of Stockroom. The only link is a **one-way, hand-carried file** (Stockroom → ZIP → PC → git). Orders travel the other way by **copy/paste of a WhatsApp message**. There is no shared state at all.

### Website (✅)
- Static HTML/CSS/vanilla JS. `index.html` (185 KB), `config.js` (WhatsApp number, offer, policy copy), generated `products.js`.
- Browser network calls: Google Fonts and `wa.me` only. `SHEET_API_URL = ''` in `index.html` is an unused leftover placeholder.
- Cart in `localStorage` (`o4u_cart_v1`); no accounts, no payment, no server.
- 41 image files, 8 MB, committed to git and deployed.
- The "O4U ORDER" block (CODE `W<DDMM>-<4>-<2 check>`, `ITEM: id | size | qty`, name/phone/address, items total) is the contract between the two apps. The check function `o4uCheck` is duplicated in both codebases and is tamper-evident.

### Stockroom (✅ from source)
- Single IIFE-structured file; vanilla JS; external scripts: JSZip (cdnjs) and Google Fonts only.
- Declared runtime capabilities: `assets`, `db`, `downloads`, `sample`.
- Realtime UI: `onSnapshot` subscriptions on `products` (≤1000), `orders` (≤500), `stockmoves` (≤1000), `cases`, `refunds`, `drafts`, and config docs.

---

## 2. Claude-specific dependencies and limitations

| # | Dependency | Where in the code | Consequence | Replacement |
|---|---|---|---|---|
| 1 | **`db`** — Claude artifact document store | `claude.use("db")`; `collection().orderBy().limit().onSnapshot()`, `doc().get/set/update/delete`, `ref.acquire({holder, ttlMs})` | Data only reachable while a signed-in Claude user has the artifact open, or via the `ArtifactData` tool in chat. Max **1000 docs per read**; **no transactions** (the code says so); org-internal only — **can never be shared with customers or the website.** | Postgres (Supabase) with a thin adapter |
| 2 | **`assets`** — blob storage | `S.assets.upload/list/delete`; photos shown from `/_blob/<id>` | Asset ids are **platform-issued and cannot be reused**: migrating means uploading again and rewriting every reference. Not readable from chat. Storage has a size cap (the page shows a meter). | Object storage bucket |
| 3 | **`sample`** — Claude called from the page | `S.sample.json(prompt, {images, modelTier:"default"})` in `readTags()` | Uses the *viewer's* Claude usage. Handbook v23 says it "has never worked in Khush's view"; **whether it works today is ❓.** If not, the real path is #4. | Server-side vision API call |
| 4 | **Claude-in-chat tag reading** | "Save for Claude to read" → `savePending()` writes ≤230 KB base64 JPEGs into `readcopies`; a human opens the Claude chat, says "read the waiting products", and Claude (via `ArtifactData`) writes the product record back | The AI step depends on **a person running a chat**. This is the main automation blocker. | Same prompt, called by an Edge Function |
| 5 | **`downloads`** | ZIP export, full backup, per-photo saves | Browser cannot save silently; every export asks for confirmation. | Normal browser download / no ZIP needed once sync is automatic |
| 6 | Artifact hosting / URL | `claude.ai/artifact/…` | Page cannot be opened by staff without a Claude account in the right org; no custom domain; no auth of its own. | Static hosting + real login |
| 7 | JSZip, Google Fonts | CDN links | Fine; low risk. | keep / self-host |

### Design limitations that matter for the new backend (✅)
1. **No transactions.** Stock safety is done by *leases* (`acquire`, 8-second TTL, retry loop) and re-reading before writing (`moveStock`, `step`). It works for 2–3 staff; it is not safe for anonymous website traffic.
2. **Holds are computed by scanning orders.** `held()` sums lines of orders with `allocated: true`; stock itself is only decremented at **dispatch**. There is no per-size `reserved` field.
3. **Hold expiry is manual.** `holdUntil` = +2 hours, but nothing releases it automatically; staff see "Hold time is over" and press Release.
4. **Stock is a map on the product document** (`stock: {M:1, "Free":1}`) with **inconsistent key spellings** (`Free` vs `FREE`, `XXL` vs `2XL`) that `normSize` papers over. The detail-screen editor *replaces* counts; saves *merge* maps (the code comments that a deleted key would never be removed).
5. **No customer record.** Name/phone/address are copied onto each order, case and refund. There is no customers collection.
6. **Reads cap at 1000 documents.** `stockmoves` grows with every sale and edit; the in-app backup already warns when a collection hits the cap.
7. **Auth is honour-system.** The dashboard "who" dropdown is not security.
8. **Website and Stockroom can disagree about the schema** (6 vs 9 categories, `FREE`/`Free Size`, `XXL`/`2XL`). The build script is the only translator today.

---

## 3. Existing data structures (✅ from code; record counts ❓)

Money on orders is stored in **paise** (`unitP`, `deliveryP`, `paidP`); product prices (`mrp`, `offerPrice`) are in **rupees**.

| Collection | Key fields | Notes |
|---|---|---|
| `products` (doc id = `slugify(article + colour)`, or `pending-<ts>-<rand>`) | `article, brand, brandCode, category (9 keys), tags[], type, colour, colourSource, features, sizes[{size, mrp, barcode, qty}], stock{size:n}, inStock, published, offerPrice, flags[], notes, status ("pending"/"ready"), refPhoto, extraRefPhotos[], tagPhotos[], webImages[≤5], createdAt, updatedAt` | **Variants are not rows**: a variant is a `sizes[]` entry plus a `stock` key. |
| `drafts` | unfinished capture: `photoAssetIds, tagAssetIds, colours[], noTag, nbName, nbPrice…` | Crash-recovery only; disposable. |
| `readcopies` | `<pendingId>-photo1/-tag1…` with `image` = data-URL | Helper for the chat reading path; deleted after reading. |
| `stockmoves` | `productId, label, article, category, size, change, before, after, unitP, kind (capture/edit/sale/dispatch/return/replace), orderId, caseId, note, by, at` | **The inventory ledger already exists** and drives the dashboard. Good news for migration. |
| `orders` (doc id `w-<webcode>` for website orders → idempotent) | `code, webCode, source, name, phone, address, landmark, notes, lines[{productId, size, qty, unitP, label, article}], deliveryP, deliveryTypedP, status, allocated, holdUntil, paidP, payment{ref, at, by, checkedAt}, tracking, dispatchedAt, deliveredAt, duplicateOf, submissionKey, history[], previousLines, changeDiffP, failure{}` | 12 statuses: request → confirmed → awaiting_payment → paid → packed → (change_due) → dispatched → (failed) → delivered / refund_due → refunded / cancelled. |
| `cases` (exchanges) | `orderId, productId, size, qty, paidUnitP, kind, status, checks{unworn, unwashed, tags, exception}, replacement{…diffP}, refundId, history[]` | |
| `refunds` | `orderId, caseId, amountP, reason, status (approved/completed), ref, sentBy, completedAt` | `refundRoom()` stops over-refunding. |
| `config/brands`, `config/export`, `config/ops` | brand-code map; last-export time; `{upiId, shopName}` | `config/nbCounter` from the handbook is **not referenced in v44 source** — ❓ whether it still exists. |
| Customers | — | **None.** Derived from orders by phone. |
| Financial records | — | No ledger table. Revenue = `stockmoves` where `kind` is sale/dispatch × `unitP`; payments live on `orders.payment`; refunds in `refunds`. The UPI id is the only payment-related setting. No bank data, keys or passwords are stored (the backup README states this; I saw no secrets in the source). |

---

## 4. Can the existing records and images be exported safely and completely?

**Short answer: yes, probably — and the app already has most of the tool — but completeness is unproven, because the restore path was never tested.**

### What exists (✅)
Stockroom v44 has a **read-only "Download full backup" button** (`fullBackup()`): it reads every doc of `products, drafts, config, readcopies, stockmoves, orders, cases, refunds` into `records.json`; downloads every referenced photo into `photos/<assetId>.<ext>`; lists "unreferenced" photos; writes `manifest.csv` with a SHA-256 per file; and a `README.txt` with counts and warnings. Its own README says: **"HOW TO RESTORE (not yet tested)"**.

### Gaps and risks (✅ unless marked)
| Risk | Why | Mitigation |
|---|---|---|
| Silent truncation | Each collection is read with `.limit(1000)`. A warning is written only if exactly 1000 come back. `stockmoves` is the one likely to grow. | Compare README counts to the on-screen counts; export `stockmoves` in date windows if near the cap. |
| Photos re-encoded, not byte-identical | If `fetch('/_blob/…')` is refused in the iframe, the page falls back to canvas re-encode (marked `OK-REENCODED`). | Accept as usable; report how many. Original-quality sources are the shop's phone gallery and `website/stock images/`. |
| Asset ids change | Platform issues new ids on upload. | Import must rewrite every reference using `manifest.csv` (position-aware). This is the hardest part of the migration and is fully specifiable from the manifest. |
| Backup runs only with the page open | A person must click it on the laptop. | One-off for migration; acceptable. |
| Data in the DB that the page never lists | e.g. an orphan collection | `ArtifactData list` from chat can enumerate collections read-only (⚠️ not tested by me). |
| Customer PII in `records.json` | names/phones/addresses | Keep the ZIP off GitHub (`*.zip` is already gitignored), encrypt the copy you keep elsewhere. |

### Verdict
Export is **feasible and non-destructive** (the button never writes). Treat "complete" as true only after a **verification pass**: counts match the screen, every manifest row is `OK`/`OK-REENCODED`, SHA-256s recomputed on the saved files match, and a **dry-run import into an empty sandbox reproduces the same counts**. That pass is Milestone 1.

---

## 5. Supabase vs Firebase

> Pricing/limits below are from my general knowledge, not checked live today. ⚠️ **Verify on the vendors' pricing pages before committing.**

| Requirement | Supabase (Postgres) | Firebase (Firestore + Storage) |
|---|---|---|
| **No overselling** | Row locks + `CHECK (reserved <= on_hand)` + one SQL function = a guarantee enforced by the database. | Transactions exist and would work, but invariants live in app code/rules, easier to get wrong. |
| Fits current data | The app is already document-shaped *and* has a ledger (`stockmoves`); JSONB gives a lossless 1:1 import, relational tables for stock/orders where it matters. | Document model is the closest to today's shape. |
| Reporting (dashboard, margins, exchanges) | SQL, joins, views. The dashboard currently scans 1000 docs in the browser. | Needs denormalising or exports. |
| Live updates (`onSnapshot` feel) | Realtime on table changes. | Native and excellent. |
| Security model | Row-Level Security + Auth. Anonymous website can be limited to a single `place_order_request` function and a published-only view. | Security Rules; workable. |
| Files | Storage buckets with policies; public bucket for web images, private for source/tag photos. | Cloud Storage (⚠️ I believe new projects now need the pay-as-you-go plan to use it). |
| Region | Mumbai (ap-south-1) available. | Mumbai available. |
| Lock-in / exit | Plain Postgres: `pg_dump`, portable anywhere. | Proprietary export. |
| Cost at this scale | Free tier likely enough to build; ⚠️ projects pause after ~1 week idle and free has no managed backups. Pro ≈ US$25/month. | Free tier generous; costs per read/write; needs a billing account for Storage. |
| AI call hosting | Edge Functions (secrets kept server-side). | Cloud Functions (needs billing plan). |

### Recommendation (F): **Supabase, Mumbai region.**
Reasons in priority order: (1) the overselling guarantee is the stated requirement and Postgres gives it directly; (2) the shop's reporting needs are relational; (3) plain-Postgres exit path; (4) Edge Functions + Auth + Storage + Realtime in one bill; (5) a document-style adapter lets Stockroom's 3.9k lines stay almost untouched. Firebase is a legitimate second choice if the owner prefers its tooling; it is not wrong, just a weaker fit for a stock-integrity requirement.

---

## 6. Recommended architecture (G)

```
 Customer ── static site (Netlify, unchanged design) ──┐
   · reads catalogue (published only)                   │ anon key (public by design)
   · sends order request                                ▼
                                          ┌──────────────────────────────┐
                                          │ SUPABASE  (Mumbai)           │
                                          │  Postgres + RLS              │
                                          │  Storage: web-images (public)│
                                          │           source-photos (private)
                                          │  Edge Functions:             │
                                          │   · place-order-request      │
                                          │   · read-tag (AI)            │
 Owner/staff ── Stockroom (same UI, static page, real login) ──▶ Auth (allow-list: 2–3 emails)
```

**Principles**
1. **Keep both front-ends.** Stockroom keeps its UI and business logic; a small **adapter** re-implements the exact calls it makes (`collection/doc/onSnapshot/get/set/update/delete/acquire`, `assets.upload/list/delete`, `sample.json`, `downloads.save`) on top of Supabase. This avoids rewriting 3.9k lines and makes rollback trivial (swap the adapter back).
2. **Storage in two layers.** Phase 2 imports documents *losslessly* (JSONB, same ids). Only the things that need guarantees get proper tables: **`stock_levels(product_id, size, on_hand, reserved)`**, **`stock_moves`** (the existing ledger), **`orders` + `order_lines`**.
3. **The website never touches tables.** It gets (a) a read-only `public_catalogue` view: published, non-pending products only; per-size "available / ask us" flag, never counts, never cost or notes; (b) one RPC `place_order_request(...)`.
4. **WhatsApp stays.** The WhatsApp message with the O4U ORDER block remains the customer-facing step and the fallback if the API is down. The same `W…` code becomes the database idempotency key (exactly like today's `w-<code>` doc id).
5. **`products.js` / `sync.bat` are retired last**, not first. During the transition the build script can keep producing a static fallback catalogue from the database, so the site never depends on the backend being up.

**Security essentials** (detail in §9): RLS on every table; anon can only read the view and call the one function; staff are authenticated users on an allow-list; service-role key lives only in Edge Function secrets; the page contains only the public anon key.

---

## 7. Inventory and reservations without overselling (H)

### Model
- `on_hand` = physical pieces on the rack (what staff count).
- `reserved` = pieces promised to open orders.
- `available = on_hand − reserved`. A database constraint forbids `reserved > on_hand` or `on_hand < 0`.
- Every change writes a row to `stock_moves` (this mirrors the current ledger, so the dashboard keeps working).

### Rules (mapped to today's behaviour so nothing surprises the shop)
| Event | Today (✅) | New |
|---|---|---|
| Website order request arrives | Customer sends WhatsApp; owner pastes it; order becomes `request` | Order row is created as `request` in the database; **no stock reserved yet** (see Decision D1). |
| Bill agreed → "Hold stock, ask for payment" | `allocated=true`, `holdUntil=+2h` after `checkFree` under leases | `reserve_order(order)`: one transaction locks the stock rows, checks `available ≥ qty` for every line, increments `reserved`, sets `hold_until`. All-or-nothing. |
| Hold runs out | Staff press Release | **Automatic** release by a scheduled job (pg_cron) → status back to `request`, `reserved` decremented, history line added. |
| Payment recorded | `paid` | unchanged |
| Dispatch | `moveStock(-qty)`, `allocated=false` | one transaction: `on_hand -= qty` **and** `reserved -= qty`. |
| Shop sale / stock edit | `respectHolds`: cannot sell pieces held for orders | enforced by the constraint, not by client code. |
| Exchange return, sellable | `+qty` | `on_hand += qty` + move row. |
| Stocktake (recount) | detail editor **replaces** the count | stored as an *adjustment delta* computed under lock, so a recount during a hold cannot erase a reservation. |

**Why this cannot oversell:** the reserve is a single SQL statement per size, `UPDATE … SET reserved = reserved + q WHERE on_hand − reserved ≥ q`. Two simultaneous requests for the last piece: one row update succeeds, the other updates zero rows and the whole order is rejected. No lease timing, no retries, no client trust.

### Decisions I need from the owner (these are business decisions, not technical ones)
- **D1 — When does a website request hold stock?** The Business Model doc states the site must *never claim availability* because rack counts drift. Options: (A, recommended for Phase 1) hold only after a human confirms, exactly as today; (B) a short automatic 30-minute soft hold on request so two customers don't chase the last piece. B needs the wording on the site to stay "order request", never "reserved for you".
- **D2 — Does the backend record the request when the customer taps Send, or only after the WhatsApp message arrives?** Opening WhatsApp does not send it (the site already says so). If recorded on tap, Stockroom must label it "website request — customer may not have messaged yet".
- **D3 — Is the number the site shows ever based on counts?** Recommend: only "available / ask us per size", never numbers.

---

## 8. Replacing Claude-powered image analysis (I)

### How it works today (✅)
1. Phone: product photo + one tag photo per size are shrunk (1600 px JPEG) and stored.
2. **Path A (in page, `sample`)**: `readTags()` sends ≤5 images (image 1 = product, the rest = tags) plus a long instruction prompt to `S.sample.json(...)` and expects JSON `{brand, brandCode, category, tags[], article, type, features, colour, colourSource, sizes[{size, mrp, barcode, qty}], flags[]}`.
3. **Path B (chat)**: the same job done by Claude in a chat session reading `readcopies` (≤230 KB base64 each: 900 px product, 700 px extras, 1400 px tags) and writing the product back with `ArtifactData`.
4. **Human confirmation already exists**: results land in an editable "review" form and nothing is saved until the user taps Save. Post-processing already enforces the shop rules (`cleanTags`, valid category only, "nude" → "beige", article upper-cased, missing-size MRP from the nearest smaller tagged size).

The prompt itself is portable text — it encodes the shop's hard-won rules: keep the full article including suffix letters; `FS` = full sleeves, never a size; per-size MRP when tags differ; no-tag items are non-branded; never mention logos on the garment; flags only for things the shop must act on.

### Recommended replacement
**An authenticated Edge Function `read-tag`** that holds the API key and makes the same call, returning the same JSON to the existing review form.

| Choice | Recommendation |
|---|---|
| Vision model | **Start with the same model family** (the prompt was tuned on Claude): a Haiku-class model first, escalate to a larger one only when the result is low-confidence or has flags. Run a bake-off against Gemini Flash-class and an OpenAI mini-class model on the same test set before fixing the choice. |
| Where the key lives | Supabase Function secret. Never in the page, never in git. |
| Who can call it | Logged-in staff only; per-user daily cap; request log (no image retention beyond the product record). |
| Cost control | Prepaid API credit with a hard monthly cap. ⚠️ Rough expectation **well under ₹5 per product** (about 4–6 images ≈ a few thousand input tokens); I have not priced it and will measure it in Phase 5 rather than promise it. |
| OCR-only (Tesseract / Cloud Vision) | **Not recommended as the main path**: tags are multilingual, curved, glossy; the job is *interpretation* (article suffix, FS, size/price pairing), not just text. Optionally add a free in-browser **barcode scan** (BarcodeDetector/ZXing) as a cross-check of the barcode field. |
| Human gate | Keep the review form. Add: AI-filled fields visibly marked until edited; store `ai_raw` and `ai_model` on the product for audit; any flag blocks "Published" until cleared (as the flags UI already does). |
| Acceptance | Build a **golden set** from products already confirmed by the shop (≥30 products with their tag photos and the final saved values) and require agreed per-field accuracy (e.g. article, MRP, sizes ≥ the current Claude-in-chat result) before switching. |

---

## 9. Security considerations

1. **Public vs secret keys.** The Supabase *anon* key is designed to be public; safety comes from RLS. The *service-role* key and the AI key exist only as function secrets. Nothing secret in `index.html`, Stockroom, or git (`.env`, `*.key`, `secrets.*` are already gitignored).
2. **Customer PII** (name, phone, address) is new server-side data. Collect only what the order block already collects; no accounts; staff-only read access; retention period (e.g. purge delivered orders' addresses after N months). India's DPDP Act, 2023 likely applies to a business holding this data (⚠️ not legal advice): add a short privacy notice to `policy.html` and get it checked.
3. **Anonymous write endpoint abuse.** `place_order_request` must: validate products/sizes/prices **server-side** (never trust prices from the browser), cap quantity (site already caps 1–99), rate-limit per IP/phone, be idempotent on the order code, add a honeypot or free bot-challenge, and restrict CORS to the Netlify origin.
4. **Real authentication for Stockroom.** Magic-link login with an allow-list of 2–3 emails; replace the "Dad/Khush/Staff" dropdown with the logged-in identity (keep the names as display labels).
5. **Storage policies.** `web-images` public read; `source-photos`/`tag-photos` private (they show your supplier labels and unreleased stock).
6. **Backups.** Free tier has no managed backups (⚠️ verify). Automate a nightly `pg_dump` + storage listing to a private location *outside* the Claude/Netlify/GitHub-public surface; test a restore quarterly.
7. **Audit trail.** Keep the existing `history[]`/`stockmoves` semantics and add `created_by` from Auth.
8. **Supply chain.** Pin JSZip/Supabase client versions; self-host to avoid CDN drift.

---

## 10. Data migration and backup plan

**Principle: copy, never move. The Claude artifact stays untouched and authoritative until a signed-off cutover.**

1. **Freeze point:** pick a quiet moment; note "last write" time; stop capturing for the duration.
2. **Export #1:** run the in-app *Download full backup* on the laptop. Store the ZIP in two places (project folder is gitignored for `*.zip`; plus an offline copy).
3. **Verify the export** with a script (read-only): record counts vs screen, every manifest row present, SHA-256 recomputed, count of `MISSING`/`OK-REENCODED`, orphan photos, no collection at 1000.
4. **Parallel safety copy from chat:** `ArtifactData list/query` of each collection, saved to JSON — an independent second route to the records (needs the owner's go-ahead because it reads PII).
5. **Build the sandbox** (empty Supabase project, schema only).
6. **Dry-run import:** photos uploaded → new paths; reference rewrite driven by `manifest.csv` (collection, doc, field, position, asset id → new path); records written with **same document ids**; `webImages` order preserved.
7. **Round-trip test:** export the sandbox back to the same JSON shape and diff against `records.json` (expect differences only in photo references). Compare image hashes.
8. **Delta re-run at cutover:** after the freeze, repeat steps 2–7 for what changed; then flip the adapter.
9. **Keep the artifact intact for ≥ 30 days** after cutover (read-only use), plus the final backup ZIP indefinitely.

**Rollback at any point before cutover:** do nothing — production never changed. **After cutover:** point Stockroom back to the artifact, re-export from Supabase and re-enter the delta (this is why cutover is done on a quiet day, ideally with no open orders).

---

## 11. Estimated operating costs (⚠️ approximate; verify before buying)

| Item | Build phase | Live (steady state) |
|---|---|---|
| Supabase | Free tier, ₹0 | **Pro ≈ US$25/month ≈ ₹2,100/month** — recommended from the first real order, for backups and no auto-pause |
| Netlify (site + Stockroom page) | Free | Free at this traffic |
| GitHub | Free | Free |
| AI tag reading | prepaid credit, e.g. ₹500 for testing | ≈ ₹ tens to low hundreds per month at current volume (measured later) |
| Domain (optional) | — | ≈ ₹800–1,000/year |
| Bot challenge (Cloudflare Turnstile) | Free | Free |
| **Total** | **≈ ₹0–500** | **≈ ₹2,200–2,600/month** |

Free tier alone is workable for a pilot; the Pro upgrade is insurance for the one thing that cannot be recovered — shop data.

---

## 12. Phased roadmap, acceptance tests, rollback

| Phase | Goal | Acceptance tests | Rollback |
|---|---|---|---|
| **0 — Safety net** | Verified backup + decisions | Backup ZIP verified (counts, hashes, 0 unexplained MISSING); D1–D3 answered; restore dry-run into scratch location | Nothing changed |
| **1 — Sandbox & schema** | Empty Supabase (free), schema, RLS, import script, **no integration** | Round-trip diff clean; RLS tests: anon cannot read tables, cannot read unpublished products; constraint tests: cannot oversell in a scripted 50-parallel-request race | Delete the sandbox project |
| **2 — Catalogue read** | Website reads published products from Supabase; static fallback kept | Same 41 images and products render as the git build; works with backend blocked (fallback); no counts or notes leak in the view | Revert one commit; `products.js` still works |
| **3 — Stockroom on Supabase (shadow)** | New Stockroom copy (adapter) writing to Supabase; the artifact stays the real one | Every Stockroom action performed on both with identical results (capture, edit, publish, stock edit, reorder images); realtime updates on two devices; login works | Stop using the copy |
| **4 — Orders & reservations** | Website → `place_order_request` → Stockroom queue; reserve/expire/dispatch in DB | Race test (two clients, last piece); idempotent resubmit; expired hold auto-releases; reconciliation: Σ on_hand − Σ moves = 0; WhatsApp flow unchanged when API is offline | Feature flag off → back to paste-from-WhatsApp |
| **5 — AI capture** | `read-tag` Edge Function | Golden-set accuracy ≥ agreed bar; every AI field editable; nothing saved without Save; spend cap works; key not in any client file | Switch flag back to chat-reading path |
| **6 — Cutover & retire** | Supabase authoritative; artifact read-only archive; `sync.bat` demoted to fallback | Fresh full backup + restore test in a scratch project; 2 weeks of parallel monitoring with zero stock discrepancies | Re-point adapter to the artifact (within the 30-day window) |

---

## 13. Risks and safeguards

| Risk | Likelihood / impact | Safeguard |
|---|---|---|
| Export looks complete but isn't (1000-cap, MISSING photos) | Medium / **severe** | Phase 0 verification pass; two independent export routes |
| Restore never tested | High today / severe | Dry-run import is the Phase 1 gate |
| Photo reference rewrite error | Medium / high | Position-aware manifest-driven script; hash comparison; spot-check UI |
| Two sources of truth during transition | Medium / high | Single writer at any time; shadow mode writes to one place only; clear cutover date |
| Business rule drift ("never claim availability") | Medium / trust damage | Decision D1; site wording unchanged; per-size flag not counts |
| Schema drift between apps | Already happening | One canonical size/category vocabulary in the DB; the adapter normalises on write |
| Rack counts remain wrong in reality | High / medium | Reservations protect against *system* oversell, not physical miscounts — keep human confirmation and add cycle-count prompts |
| Free-tier pause / no backups | Medium / high | Move to Pro before real orders; nightly dump |
| PII exposure | Low–medium / high | RLS, private buckets, minimal fields, retention rule, privacy notice |
| AI cost spike or key leak | Low / medium | Prepaid cap, server-side key, staff-only function, per-day limit |
| Staff confusion at cutover | Medium / medium | Same UI, same words; rehearse on a quiet day; owner-level checklist |
| Handbook vs code mismatch misleads future work | Already true | This audit supersedes it; v44 HTML is the reference |

---

## 14. What I still need to proceed (exact list)

1. **Owner clicks "Download full backup"** (Capture tab, bottom) on the laptop, and shares the ZIP's *location* (not by upload to any public place). Also states how many products / orders / exchanges the screens show, to compare.
2. **Written answers to D1, D2, D3** (above).
3. **Permission** to read the artifact database from chat (`ArtifactData`, read-only) as the independent second export. It contains customer phone numbers and addresses.
4. A decision on **accounts**: who owns the Supabase account (suggest the shop Gmail), and whether an Anthropic API account with a spend cap may be opened (Phase 5).
5. **A sample of ~30 products' tag photos with the final confirmed values** for the AI golden set (can be taken from the backup).
6. Confirmation whether **in-page "Read tag" works today** on the owner's phone (it determines whether Path A or only Path B is in use).
7. Confirmation of what the **live site currently shows** (6 products from 17 Sep, or newer?) and whether **Netlify auto-deploys from GitHub** (handbook open item #4).

---

## 15. Exact first implementation milestone

### Milestone 1 — "Verified copy, empty sandbox, lossless round trip"
*(No production system is touched. Needs the owner's approval to start.)*

**Deliverables**
1. `backup-verify` script (read-only): consumes the backup ZIP and prints a pass/fail report — counts per collection vs the README, every `manifest.csv` row accounted for, SHA-256 re-check, MISSING/re-encoded counts, collections at the 1000 cap, orphan photos, referential checks (every `orders.lines[].productId` exists; every `cases.orderId` exists; product id equals `slugify(article, colour)`).
2. Schema design (SQL file, **not executed**) for: products (JSONB doc + indexed columns), `stock_levels`, `stock_moves`, `orders`, `order_lines`, `cases`, `refunds`, `config`, `product_images`; RLS policies; the `reserve_order`, `release_expired_holds`, `dispatch_order`, `place_order_request` functions as written specs with test cases.
3. Import script (dry-run mode default; writes only to a sandbox URL passed explicitly).

**Acceptance tests (all must pass)**
- Verification report on the real backup: **0 unexplained MISSING**, counts equal the owner's on-screen counts.
- Re-importing the same backup twice into the sandbox yields identical row counts (idempotent).
- Export-from-sandbox diffed against `records.json`: **0 differences** except rewritten photo paths; every rewritten path resolves to a file whose hash matches the manifest.
- Scripted race: 50 parallel `reserve_order` calls for 1 remaining piece → exactly **1** succeeds.
- Anonymous-role test: cannot select from any base table; can select `public_catalogue`; cannot see an unpublished product.

**Rollback:** delete the sandbox project and the local import folder. Stockroom, the website, Netlify and GitHub are never modified.

**Needs from you before it starts:** items 1–3 and 5 in §14, and a free Supabase account for the sandbox (no paid resource).

---

**STOPPED after the audit, as instructed. No code was written, nothing was deployed, no data was read, modified or deleted.**
