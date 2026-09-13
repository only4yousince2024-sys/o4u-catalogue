# O4U CATALOGUE WEBSITE — MASTER IMPLEMENTATION PROMPT

**Project root:** `D:\CLAUDE PROJECTS\ONLY 4 YOU`
**Website root:** `D:\CLAUDE PROJECTS\ONLY 4 YOU\website`

You are turning the existing Only 4 You catalogue website into a reliable, production-ready static site with WhatsApp ordering.

---

## 0. READ THIS FIRST — THIS IS AN EXISTING PROJECT

A substantial frontend already exists and has been audited. **Do not rebuild it.**

These four files are hand-built working tools. Never delete or rewrite them wholesale:

| File | What it is |
|---|---|
| `website/index.html` | 64 KB single-file site — hero, branding, typography, scroll animations, category filters, product grid, product modal, size/colour/quantity selectors, WhatsApp order builder, image fallback |
| `website/admin.html` | Product manager (File System Access API) |
| `website/image-picker.html` | Original photo-assignment tool |
| `website/photo-assigner.html` | Current photo-assignment tool — 172 products × 370 photos, localStorage-backed |

Your job is: **inspect → version → repair → extend → validate → deploy.**
Not: delete → rebuild → over-engineer.

If this prompt conflicts with what you find in the project, **stop and explain the conflict.** Do not silently pick an interpretation that loses work or data.

---

## 1. PHASE 0 — INSPECT, THEN VERSION

### 1.1 Inspect

Before touching anything, inspect and report briefly:

- Full project structure
- `website/index.html`, `admin.html`, `image-picker.html`, `photo-assigner.html`
- `products.js` and every reference to it
- `auto_generate_products.py`, `polish_photos.py`, any other scripts
- `O4U_Stock_Inventory_UPDATED_v2.xlsx` (project root) and the stale copy in `website/stock/`
- Image folders

Report: what works, what is broken, what will change.

### 1.2 Git baseline — BEFORE any code change

Version control and deployment are separate concerns. The repo must exist **now**; Netlify comes last.

1. Write a `.gitignore` (see §9.3)
2. `git init` in the project root
3. Stage and commit everything as `baseline: existing O4U website`

This is the undo point. Nothing else proceeds until it exists.

---

## 2. ARCHITECTURE AND SOURCE OF TRUTH

```
O4U_Stock_Inventory_UPDATED_v2.xlsx   (project root — SINGLE SOURCE OF TRUTH)
        ↓
scripts/build_catalogue.py            (clean → normalise → validate → generate)
        ↓
website/products.js                   (generated artifact — NEVER hand-edited)
        ↓
website/index.html                    (frontend)
        ↓
WhatsApp order request → manual confirmation → Porter → 3-day returns
```

**One writable store only.** The workbook. Everything downstream is generated.

### 2.1 admin.html must stop writing

`admin.html` can currently write `products.js`. That means: edit a product there, run the build, and the edit is silently destroyed.

Disable its write-to-`products.js` behaviour. Keep its browsing and preview functionality. Show a clear notice inside the tool:

> Excel is the source of truth. Changes made here are not saved and will be overwritten on the next build.

Do not create a second writable product store. If you believe some write capability must remain, **stop and explain before implementing it.**

---

## 3. THE FIRST FIX — products.js PATH

`website/index.html` line 9 loads `products.js`, but the file sits at the project root, one level up. It 404s, `PRODUCTS` is undefined, `SHEET_API_URL` is empty so the Sheets branch is skipped, and the catalogue renders **zero products**.

**Fix direction — this matters:**

The generator must write to **`website/products.js`**. The frontend keeps loading `./products.js`.

**Do NOT change index.html to `../products.js`.** Netlify's publish directory is `website/`, so `../` resolves outside the deploy root and 404s in production while appearing to work locally.

Everything the browser needs must live inside `website/`.

---

## 4. PRODUCT IDENTITY

### 4.1 Article numbers are NOT unique

Verified against the workbook:

- 215 inventory rows
- 173 unique variants
- **73 unique article numbers — 45 of them legitimately repeat across colours**
- 172 unique article + colour pairs

An article number identifies a *design at a price band*. `CS250A` is four colours. `7724291-C` covers 20 rows.

**The unique key is `article + colour`.** Never reject a repeated article number on its own.

### 4.2 Product ID

Every product gets a stable, derived ID — lowercase slug of article + colour:

```
CS250A + Min.Red   →  cs250a-min-red
KPL310D/B + Violet →  kpl310d-b-violet
```

Rules: lowercase, `&` → `and`, any run of non-alphanumeric → single hyphen, trim hyphens.

IDs must be **stable across builds**. Never index-based (`w1`, `w2`) — the current generator does this and IDs shift every run.

### 4.3 Known data error — do not work around it

Exactly one real duplicate exists:

```
7724090-F + Pink
  → "Premium Lounge Wear (T+Pants)"        ₹749
  → "Premium Lounge Wear Button-Up Combo"  ₹924
```

Two products, two prices, one article+colour. **This is a source data error.** Flag it loudly in the build report. Do not merge them, do not relax the uniqueness rule.

---

## 5. WORKBOOK COLUMNS

### 5.1 Required columns

The build reads: `Article No.`, `Brand`, `Description`, `Shade / Color`, `Size`, `Available Sizes`, `MRP (₹)`, `Stock Qty`, plus these, which the shop controls:

- `Selling Price`
- `Offer Price`
- `Published`

### 5.2 Missing COLUMNS are not missing VALUES

**None of those three columns exist in the workbook yet.** If a column is absent, the build must add it / default it safely with a warning — never fail, never produce an empty catalogue:

| Column absent | Default |
|---|---|
| `Selling Price` | falls back to MRP |
| `Offer Price` | blank |
| `Published` | **TRUE** |

A missing `Published` column must not unpublish the entire catalogue.

### 5.3 Blank values

- `Selling Price` blank → use MRP, emit a **warning**, not an error
- `Offer Price` blank → no discount shown
- `Published` blank → treat as TRUE, warn

---

## 6. DATA PIPELINE

Consolidate into a single command:

```
python scripts/build_catalogue.py
```

### 6.1 Sizes — currently wrong

The generator reads column F (`Size` — the size of one physical garment). Catalogue availability must come from `Available Sizes`. **168 of 173 variants currently disagree.**

**Ranges appear in BOTH columns.** Row 215 has `M-3XL` in the `Size` column. The parser must handle either.

### 6.2 Size parser — one reusable function

Canonical order: `XS S M L XL 2XL 3XL 4XL 5XL`

- `XXL` → `2XL` (appears 18 times vs 165 for `2XL`)
- `XXXL` → `3XL`
- Expand ranges: `M to 3XL` → `M L XL 2XL 3XL` (42 occurrences); `L-3XL` → `L XL 2XL 3XL` (3 occurrences)
- Separators to handle: `to`, `-`, `–`, `—`
- Trim, drop blanks, deduplicate, sort canonically
- **Never emit `to` as a size**

Fix the parser. Never patch individual products.

### 6.3 Price

```
Offer Price present  →  price = Offer Price,   mrp = MRP        (strike-through shown)
Offer Price blank    →  price = Selling Price, mrp = null       (no discount shown)
Selling Price blank  →  price = MRP,           mrp = null       (+ warning)
```

Current business rule: selling price equals MRP. Never invent or infer a discount. Offers are occasional events, not a permanent state.

### 6.4 Stock — coupled migration, both sides in one step

Stop hardcoding `inStock: true`. Read `Stock Qty`, emit `stockQty`.

**`index.html` filters on `p.inStock` in at least two places (around lines 1447 and 1453).** Removing `inStock` from the data without updating the frontend empties the catalogue.

Search the entire frontend for `inStock` and migrate every occurrence in the **same step** as the pipeline change. Verify products still render before committing.

Frontend derives: `stockQty > 0` → available; `0` → currently unavailable. Never show exact quantities to customers.

### 6.5 Published

`published` is an explicit shop-controlled column. **Never derive it** from image presence, stock, description, filename, or any heuristic. Missing images produce a warning — they must not silently unpublish a product.

### 6.6 Categories

Valid keys and labels:

| Key | Label |
|---|---|
| `front-button` | Front Button Set |
| `round-neck` | Round Neck |
| `collar-neck` | Collar Neck |
| `salwar-set` | Salwar Set |
| `tshirt-lower` | T-Shirt / Lower |
| `tshirt-shorts` | T-Shirt / Shorts |

The generator currently defaults unknown descriptions to `front-button` silently. **Unknown category = validation error.** Fix the mapping, don't hide the problem.

### 6.7 Empty fields

Known broken output: `" Gym Wear"` with `colors: [""]` and description `"Gym Wear in . by Melini."`

Fix generically at the cleaning layer — trim strings, treat blanks as null, never emit empty colour chips, never emit dangling punctuation where an optional field is missing.

### 6.8 Remove the product cap

`MAX_PRODUCTS = 12` and the top-2-per-category selection must go. All valid published products appear. Never silently slice the catalogue.

---

## 7. IMAGES — INCLUDING GALLERY SUPPORT

### 7.1 Naming is derived, never recorded

Filenames come from the Product ID. This is non-negotiable — it is the fix for a real failure where photo-to-product links were lost.

```
cs250a-min-red__tag.jpg   tag photo      — reference only, never deployed
cs250a-min-red__src.jpg   raw source shot — never deployed
cs250a-min-red.jpg        primary web image
cs250a-min-red-2.jpg      additional web images
cs250a-min-red-3.jpg
…up to -9
```

### 7.2 Folder structure

```
ONLY 4 YOU\product-photos\tags\      __tag files   (gitignored, never deployed)
ONLY 4 YOU\product-photos\source\    __src files   (gitignored, never deployed)
ONLY 4 YOU\website\images\           web images    (deployed)
```

### 7.3 Gallery — NEW REQUIREMENT

Products need **multiple images**, not one. Schema changes from a single `image` string to:

```js
images: ["images/cs250a-min-red.jpg", "images/cs250a-min-red-2.jpg", ...]
```

The build discovers them: for each product, look for `<pid>.jpg` then `<pid>-2.jpg` through `<pid>-9.jpg`, in order. Whatever exists becomes the array. `images[0]` is the card image.

**Frontend:**
- Product card — shows `images[0]` only
- Product modal — a gallery: main image plus thumbnail strip, click or swipe to change, arrow keys on desktop. Single-image products show no gallery chrome at all.
- Preserve the existing `onerror` placeholder fallback per image
- Lazy-load everything below the fold

Keep it simple. No lightbox library, no carousel dependency — this is vanilla JS.

### 7.4 Image validation

- Published product with zero images → **warning**, still published, card falls back to the existing placeholder
- Referenced file missing on disk → warning naming the product and file
- Never a broken-image icon
- 50 rows currently have no image filename. `website/images/` currently contains **only branding assets** — no product photography yet. Expect placeholders after the first build. This is not a frontend failure.

---

## 8. PRODUCT SCHEMA

```js
{
  id:          "cs250a-min-red",
  article:     "CS250A",
  name:        "Min.Red Cord Set",
  brand:       "Melini",
  category:    "front-button",
  description: "…",
  colors:      ["Min.Red"],
  sizes:       ["L","XL","2XL"],
  price:       1465,
  mrp:         null,
  images:      ["images/cs250a-min-red.jpg", "images/cs250a-min-red-2.jpg"],
  stockQty:    4,
  published:   true,
  badge:       "",
  badgeStyle:  ""
}
```

Preserve any additional field the existing frontend depends on.

---

## 9. VALIDATION, REPORTING, HYGIENE

### 9.1 Validation

| Area | Checks |
|---|---|
| Identity | duplicate article+colour (error), missing article, missing colour |
| Price | invalid MRP / Selling Price / Offer Price; blank Selling Price = warning |
| Sizes | invalid tokens, malformed ranges, `to` pseudo-size, empty size lists |
| Category | unknown category or unmapped description = error |
| Stock | non-numeric `Stock Qty` |
| Published | invalid boolean |
| Images | missing files, missing primary image = warning |
| Output | `website/products.js` exists and is syntactically valid JavaScript |

**Errors block the build with a non-zero exit code. Warnings do not.** Never generate a catalogue and report success when critical data is invalid.

### 9.2 Build report

All counts calculated dynamically. **Never hardcode or invent numbers.**

```
O4U CATALOGUE BUILD
  Source rows           <n>
  Unique variants       <n>
  Published             <n>
  Unpublished           <n>
  Missing images        <n>
  Zero stock            <n>
  Warnings              <n>
  Errors                <n>
```

### 9.3 Repo and asset hygiene

- **`website/stock images/O4u img-20260524T131909Z-3-001.zip` is 1.1 GB.** Never commit it, never deploy it.
- `.gitignore` must exclude: that ZIP, `product-photos/`, raw archives, temp/OS/editor files, secrets, `.env`
- `.gitignore` must NOT exclude: `website/`, `products.js`, the four protected HTML tools, the workbook
- `polish_photos.py` contains an API-key placeholder. Never commit a real key — environment variables only.
- Oversized/duplicate assets, to consolidate only after checking references: `cover image.png` (9.7 MB); `hero-main.jpg.jpeg` (2.8 MB) duplicating `hero-main.jpg` (302 KB); byte-identical pairs `logo.png`/`ONLY 4 YOU . REDESIGNED LOGO.png`, `wordmark.png`/`ONLY 4 YOU.png`, `kids-logo.png`/`ONLY 4 kids.png`
- Two workbooks exist. Use the **root** one. Never write to `website/stock/O4U_Stock_Inventory.xlsx`.
- The workbook's Summary tab has a stale `COUNTIF` range (`B3:B200`, data runs past 217) and counts only Melini. The catalogue must never depend on the Summary tab.

---

## 10. FRONTEND REPAIRS

1. **Stale category map.** `catLabels` maps `'women comfort'`, `'women nightwear'`, `'kids formal'`, `'kids'` — none of the six current keys. Every card currently prints the raw slug. Replace with the §6.6 labels.
2. **Dead filter.** Seven filter buttons, six categories. `oversized` never matches anything. Remove it, or make the filter bar data-driven from the generated categories (preferred).
3. **`inStock` → `stockQty`** — see §6.4. Same step as the pipeline change.
4. **WhatsApp number** `918146597775` is hardcoded in 8 places. Centralise to one constant.
5. **`SHEET_API_URL`** — the scaffold is empty. Either keep it strictly optional with graceful fallback to local `products.js`, or remove it. The catalogue must never blank out because an API is unreachable.
6. **Lazy loading.** ~172 products with photos is a lot for a phone. `loading="lazy"` on all product images.

Preserve the visual identity, typography, hero, animations and layout. No redesign.

---

## 11. CART

Currently ordering is one product at a time. Add a client-side cart. No backend, no accounts, no database.

Cart line item: `productId`, `article`, `name`, `colour`, `size`, `quantity`, `price`.

Must support: add, quantity up/down, remove, running total, empty state, multiple products, and multiple variants of the same product.

**Variant-safe line items:** `Product A / Pink / M` and `Product A / Pink / L` are two separate lines and must never collapse into one.

---

## 12. WHATSAPP ORDER

Extend the existing `sendWhatsApp()` — do not discard it.

```
https://wa.me/<NUMBER>?text=<url-encoded>
```

No WhatsApp Business API, no backend, no third-party messaging service.

**Message must contain** — order ID, timestamp, total; and per line: article number, product name, colour, size, quantity, price.

```
O4U ORDER
Order ID: O4U-0913-A7K
Time: 13 Sep 2026, 6:42 PM

1. Min.Red Cord Set
Article: CS250A
Colour: Min.Red
Size: 2XL
Qty: 1
Price: ₹1,465

TOTAL: ₹1,465
```

Order ID generated client-side, format `O4U-MMDD-XXX`.

Keep it compact — some clients truncate long URLs around 2,000 characters. Article numbers, not descriptions. Test carts of 1, 5, 10 and 15 items.

**Wording.** The customer is sending an *order request*. Never display "Order confirmed", "Payment successful" or "Stock guaranteed". Use "Order on WhatsApp" / "Send order request". Stock is confirmed manually; payment comes after.

---

## 13. BUSINESS MODEL

```
Browse → cart → WhatsApp order request → O4U checks stock manually
→ O4U confirms → customer sends details → advance payment incl. delivery
→ pack → Porter → 3-day return window
```

The manual stock check is intentional. **Do not build real-time inventory sync.**

The site should communicate: stock is confirmed manually, payment follows confirmation, delivery charges apply, 3-day returns. **Do not hardcode a delivery charge — it is not decided yet.**

---

## 14. OUT OF SCOPE

Payment gateway · online payment · COD integration · user accounts · login · saved carts · database · admin backend · real-time inventory API · Porter API · shipping API · WhatsApp Business API · multi-language.

If you think one is necessary, stop and explain before adding it.

---

## 15. PHASES

**Phase 0 — Inspect + Git baseline.** Nothing else starts first.

**Phase 1 — Data pipeline.** §4 identity · §5 columns · §6 all fixes · §7.4 image validation · §9 validation and report · generate `website/products.js`.

**Phase 2 — Frontend wiring.** §3 path · §6.4 stockQty coupling · §10 repairs. **Checkpoint: the site should render roughly 172 products.** 12 means the cap survived. 0 means the path, the `inStock` swap, or the `Published` default is wrong.

**Phase 3 — Gallery + cart + WhatsApp.** §7.3 gallery · §11 cart · §12 order message.

**Phase 4 — Admin alignment + assets.** §2.1 admin.html · §9.3 hygiene. Never unpublish products for missing photos.

**Phase 5 — QA.** Data, frontend, gallery, cart, WhatsApp at all cart sizes, mobile (Samsung S24 viewport) and desktop, and both photo tools still working. Then simulate production: serve `website/` as the root and confirm nothing references a file outside it.

**Phase 6 — Deployment.** GitHub → Netlify, publish directory `website`. Test the live URL. Verify the ZIP and `product-photos/` are excluded.

**Commit at each phase.** Not one giant commit.

```
baseline: existing O4U website
fix: catalogue data pipeline
fix: frontend inventory wiring
feat: product gallery
feat: multi-item cart
chore: admin alignment and asset cleanup
```

---

## 16. WRITE AGENTS.md

`AGENTS.md` is currently 47 bytes — one heading. Fill it in so future sessions don't re-derive the rules. It must carry: the architecture flow, the product schema, the Product ID scheme, the image naming convention and folder layout, the category keys, the size vocabulary, how to run the build, and the non-negotiables below.

---

## 17. NON-NEGOTIABLES

1. Do not rebuild the existing frontend.
2. Do not delete `index.html`, `admin.html`, `image-picker.html`, or `photo-assigner.html`.
3. Git baseline commit before any code change.
4. The Excel workbook is the single source of truth.
5. Never two writable product stores.
6. Generated `products.js` lives **inside** `website/`. Never `../products.js`.
7. Product identity is **article + colour**. Never article alone.
8. Product IDs are derived and stable. Never index-based.
9. Resolve `7724090-F + Pink`; do not relax validation to hide it.
10. Parse size ranges from **both** `Size` and `Available Sizes`.
11. Never emit `to` as a size. `XXL` → `2XL`.
12. Blank `Selling Price` → MRP fallback + warning, never a build failure.
13. Missing **columns** default safely (`Published` → TRUE) with a warning, never an empty catalogue.
14. `published` is an explicit column. Never derived. Missing images never unpublish.
15. `stockQty` pipeline and frontend migrate in the **same step**. No stale `inStock` checks.
16. Image filenames derive from the Product ID. Never recorded by hand.
17. Never invent discounts, product data, or build-report counts.
18. No 12-product cap.
19. Never commit the 1.1 GB ZIP, `product-photos/`, or API keys.
20. Errors block the build with a non-zero exit. Warnings do not.
21. Fix the parser, never the individual product.
22. No backend, no payment, no accounts.
23. Netlify only after QA passes.

---

## 18. HOW TO WORK

Before modifying a file: understand it, identify dependencies, make the smallest change that works, test it, read the diff, commit.

At the end of each phase report: what changed, what was preserved, what was validated, warnings and errors, exact files modified, and whether it is safe to commit.

**Do not claim something works unless you have actually tested it.**

Start with Phase 0.
