# Only 4 You — catalogue website: rules for agents

Static product catalogue with WhatsApp ordering. No backend, no payment, no
accounts. Read this before touching anything.

## Architecture

```
O4U_Stock_Inventory_UPDATED_v2.xlsx   (project root — SINGLE SOURCE OF TRUTH)
        ↓
scripts/build_catalogue.py            clean → normalise → validate → generate
        ↓
website/products.js                   GENERATED. Never hand-edit.
        ↓
website/index.html                    frontend (single file, vanilla JS)
        ↓
WhatsApp order request → O4U checks stock manually → confirms → customer pays
advance incl. delivery → packed → Porter → 3-day return window
```

One writable store only: the workbook. `admin.html` is a read-only preview.
`photo-assigner.html` and `image-picker.html` are local photo tools that read
`website/stock images/` (gitignored, never deployed).

## Run the build

```
python scripts/build_catalogue.py            # root workbook → website/products.js
python scripts/build_catalogue.py --workbook path/to/other.xlsx --out ... --images-dir ...
python scripts/test_build_catalogue.py       # 12 self-checks, no pytest needed
```

Needs Python 3.10+ and `openpyxl`. Errors → exit 1 and `products.js` is NOT
written. Warnings → exit 0. The report at the end is computed, never typed.

To preview locally serve `website/` as the root (`python -m http.server
8765 --directory website`). Netlify publishes `website/`; nothing the browser
loads may live outside it (never `../products.js`).

## Workbook columns (sheet "Stock Inventory", header row found by name)

Required: `Article No.`, `Description`, `Shade / Color`, `Available Sizes`,
`MRP (₹)`, `Stock Qty`. Optional: `S.No`, `Brand`, `Size`, `Notes`.
Shop-controlled (absent today; the build defaults them with ONE warning):

| Column | Blank / absent → |
|---|---|
| `Selling Price` | MRP (+ warning per product when the column exists but is blank) |
| `Offer Price` | no discount shown |
| `Published` | TRUE — a missing column must never empty the catalogue |

`published` is explicit. Never derive it from images, stock or anything else.
Rows whose `S.No` is blank while `Brand` holds a number are shifted one column
right — they are skipped with a warning, never guessed. The Summary tab and
the `Image URL` column are ignored.

## Product identity

* Identity = **article + colour**. Article numbers repeat across colours
  (CS250A has four). Never key on article alone.
* Product ID = slug of `article + colour`: lowercase, `&` → `and`, any run of
  non-alphanumerics → `-`, trimmed. `CS250A + Min.Red` → `cs250a-min-red`,
  `KPL310D/B + Violet` → `kpl310d-b-violet`, blank colour → `gw19b`.
* IDs are stable across builds and match `photo-assigner.html`. Never index
  based (`w1`, `w2`).
* Same article+colour with two descriptions (e.g. `7724090-F + Pink` in the
  current workbook) is a **build error**. Fix the workbook; don't relax the
  rule.

## Product schema (`website/products.js`)

```js
const CATEGORIES = [{ key, label }, …];   // only categories with published products
const PRODUCTS = [{
  id: "cs250a-min-red", article: "CS250A", name: "Min.Red Cord Set",
  brand: "Melini", category: "front-button",
  description: "Cord Set in Min.Red by Melini.",
  colors: ["Min.Red"],                // [] when the colour is blank — never [""]
  sizes: ["M","L","XL","2XL"],        // canonical order, ranges expanded
  price: 1415, mrp: null,             // mrp only when an Offer Price exists (strike-through)
  sizePrices: {},                     // {"3XL": 649} when MRP differs by size; price = lowest
  images: ["images/cs250a-min-red.jpg", "images/cs250a-min-red-2.jpg"],
  image: "images/cs250a-min-red.jpg", // = images[0] or "" (kept for admin.html)
  stockQty: 4,                        // frontend: > 0 available, 0 "currently unavailable"; never shown
  published: true,                    // unpublished products are not emitted at all
  badge: "", badgeStyle: ""
}];
```

Price rule: Offer Price → `price = offer, mrp = MRP`; else Selling Price →
`price = selling, mrp = null`; else `price = MRP, mrp = null`. Never invent a
discount.

## Categories

| Key | Label |
|---|---|
| `front-button` | Front Button Set |
| `round-neck` | Round Neck |
| `collar-neck` | Collar Neck |
| `salwar-set` | Salwar Set |
| `tshirt-lower` | T-Shirt / Lower |
| `tshirt-shorts` | T-Shirt / Shorts |

Workbook `Description` → key lives in `CATEGORY_MAP` in the build script.
An unmapped description is a build error — add the mapping, never a default.

## Sizes

Vocabulary and order: `XS S M L XL 2XL 3XL 4XL 5XL`. `XXL` → `2XL`,
`XXXL` → `3XL`. Ranges `M to 3XL`, `L-3XL`, `M–3XL` expand. One parser
(`parse_sizes`) reads both `Size` and `Available Sizes`; the product gets the
union. `to` is never a size. Fix the parser, never a product.

## Images

Filenames are DERIVED from the Product ID — never recorded in a sheet:

```
product-photos/tags/<pid>__tag.jpg    tag photo, reference only   (gitignored)
product-photos/source/<pid>__src.jpg  raw shot                    (gitignored)
website/images/<pid>.jpg              primary web image           (deployed)
website/images/<pid>-2.jpg … -9.jpg   gallery images, in order    (deployed)
```

The build discovers `<pid>.jpg` then `-2` … `-9` (jpg/jpeg/png/webp).
`images[0]` is the card image; the modal shows a gallery when there is more
than one. A missing image is a warning and a placeholder, never an unpublish.
`website/images/` also holds branding (`logo.png`, `hero-main.jpg`,
`kids-hero.jpg`, `fevicon.png`).

## Frontend notes (`website/index.html`)

* The WhatsApp number lives once, in `WA` inside the `<head>` config script.
  Static links carry `data-wa="message"` and are filled at load.
* Cart is client-side (`localStorage` key `o4u_cart_v1`). A line is
  product + colour + size; `Product A / Pink / M` and `/ L` never merge.
* Order message: `O4U ORDER`, `Order ID: O4U-MMDD-XXX`, time, then per item
  `n. Name` / `article, colour, Size X, Qty n, ₹total`, then `TOTAL`. Two
  lines per item on purpose — 15 items ≈ 1,740 URL chars (limit ~2,000).
* Wording is always "order request". Never "confirmed", "paid", "guaranteed".
  Delivery charge is not hardcoded anywhere (not decided).

## Non-negotiables

1. Don't rebuild the frontend; don't delete `index.html`, `admin.html`,
   `image-picker.html`, `photo-assigner.html`.
2. The workbook is the single source of truth; `products.js` is generated
   into `website/`; never a second writable store.
3. Identity = article + colour; IDs derived and stable.
4. Errors block the build (exit 1). Warnings don't. Never fake the counts.
5. Missing columns default safely; missing images never unpublish.
6. No product cap. No invented discounts or data.
7. Never commit `website/stock images/` (1.1 GB raw + 1.1 GB ZIP),
   `product-photos/`, `archive/`, or any API key (`polish_photos.py` reads
   `REMOVE_BG_API_KEY` from the environment).
8. No backend, payment, accounts, real-time inventory, Porter/shipping or
   WhatsApp Business APIs. Stop and explain before adding any.
9. Commit per phase; Netlify (publish directory `website`) only after QA.
