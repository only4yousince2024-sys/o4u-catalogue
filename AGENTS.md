# Only 4 You — catalogue website: rules for agents

Static product catalogue with WhatsApp ordering. No backend, no payment, no
accounts. Read this before touching anything.

## Architecture

```
O4U_Stock_Inventory_UPDATED_v2.xlsx   (project root — archive + anything not yet in Stockroom)
stockroom.json                        (project root — LIVE products exported by O4U Stockroom, optional)
        ↓
scripts/build_catalogue.py            clean → normalise → validate → merge → generate
        ↓
website/products.js                   GENERATED. Never hand-edit.
        ↓
website/index.html                    frontend (single file, vanilla JS)
        ↓
WhatsApp order request → O4U checks stock manually → confirms → customer pays
advance incl. delivery → packed → Porter → 3-day return window
```

Products are now created in the **O4U Stockroom** artifact, which exports a ZIP
of website images plus `stockroom.json`. Unzip it into the project: the JSON at
the root, the images into `website/images/`. The workbook remains the archive
and the source for anything not in Stockroom. Nothing else writes product
data; `admin.html` is a read-only preview.
`photo-assigner.html` and `image-picker.html` are local photo tools that read
`website/stock images/` (gitignored, never deployed).

## Run the build

```
python scripts/build_catalogue.py            # root workbook → website/products.js
python scripts/build_catalogue.py --workbook path/to/other.xlsx --out ... --images-dir ...
python scripts/test_build_catalogue.py       # 28 self-checks, no pytest needed
python scripts/run_cart_tests.py             # 80 cart/threshold/WhatsApp-message/order-block/product-view checks, headless Chrome/Edge
sync.bat                                     # owner's one step: build → commit → push (stops on a failed build)
scripts/cart_tests.js                        # the same 80 checks; can also be pasted into the browser console (F12)
```

The cart checks never send anything: they BUILD the wa.me URL and decode it,
`window.open` is stubbed, and the headless runner blocks every host except
127.0.0.1. Threshold boundaries ₹1,999 / ₹2,000 / ₹2,001 are asserted on the
product total after discounts; delivery is never in that figure.

`sync.bat` is what the shop owner runs after unzipping a Stockroom export.
It never pushes a failed build, skips the commit when nothing changed, and
speaks plain language (no stack traces).

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
| `Category` | `CATEGORY_MAP` from the Description. When filled it must be a category key or label (`front-button` / `Front Button Set`) and overrides the map; unknown value or rows of one product that disagree = build error |

Rows now arrive from **O4U Stockroom** (phone capture, written by the inventory
chat) one row per size, with `Category`, `Offer Price` and `Published`. New
rows come in `Published = FALSE` until the owner switches them on; blank
`Published` on older rows still means TRUE. Articles `O4U-NB-####` are the
shop's own non-branded items: a blank brand is expected (no warning) and
`brand` is emitted as `""` - the site shows no brand for them, ever.

## stockroom.json (optional, wins over the workbook)

```
{ "exportedAt": "...", "products": [ { id, article, brand, category, tags, type, colour,
  features, sizes:[{size, mrp, barcode}], stock:{size: qty}, inStock, offerPrice,
  notes, images:[filenames] } ] }
```

Stockroom **v43** format (14 Oct 2026): `category` is one of the nine keys
below; the old six (`front-button` … `tshirt-shorts`) are a build ERROR
("pre-v43 key - re-export"). `tags` is an optional list from `front-button,
round-neck, collar-neck, satin, t-lower, t-shorts, t-capri, long-short-t,
salwar` (unknown tag = error); tags feed search only, no tag chips. Sizes are
`S M L XL XXL 3XL 4XL 5XL 6XL 7XL 8XL Free` (older `FREE`). `stock` omits
0-piece sizes. Only `products` is read - never orders, customers or settings.
Image names with `__tag` / `__src` or without a photo extension are skipped
(warning): public output carries website photos only. Each product gets
`sizeCodes` {label → size exactly as written in stockroom.json} for the
WhatsApp ITEM lines.

* Missing file → warning, build from the workbook alone. Never an error.
* `id` must equal `slugify(article, colour)` — a mismatch is a build ERROR naming
  both values. `category` must be one of the nine KEYS (labels are an error here).
* `sizes[].size` goes through `parse_sizes` (`Free` → `Free Size`); the lowest
  `mrp` is `price`, the rest go to `sizePrices` exactly like the workbook.
  `offerPrice` → `price = offerPrice, mrp = tag MRP`. `stockQty` = sum of
  `stock{}` when present, else 1 if `inStock` else 0. `images[]` are used in the
  given order, prefixed `images/` (missing files warn); an empty list falls back
  to discovery by id. Blank brand → `""`, no warning.
* Everything in the file is already published — no Published check is applied.
* Same id in both sources → stockroom.json wins; the report lists the overrides
  ("Stockroom overrides n"). Stockroom products are emitted first.

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
* IDs are stable across builds and match `photo-assigner.html` and Stockroom
  (`14560B + Black Pink Geometric` → `14560b-black-pink-geometric`). Never index
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
  sizeCodes: {"2XL": "XXL"},          // label → size exactly as in stockroom.json ({} for workbook rows)
  tags: ["front-button", "satin"],    // Stockroom v43 tags, search only ([] when none)
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
| `tshirts` | T-Shirts |
| `tops` | Tops |
| `shirts` | Shirts |
| `lowers` | Lowers |
| `trousers` | Trousers |
| `jeans` | Jeans |
| `nightsuits` | Night Suits |
| `capris` | Capris |
| `accessories` | Accessories |

Stockroom v43 keys (owner decision, 14 Oct 2026). Workbook `Description` → key
lives in `CATEGORY_MAP`; only descriptions that clearly fit a v43 category are
mapped. Old archive descriptions (co-ord sets, kurtis, kurta sets, gym wear)
are deliberately unmapped: an unmapped description is a build error — the
owner decides the category, never a default.

## Sizes

Vocabulary and order: `XS S M L XL 2XL 3XL 4XL 5XL 6XL 7XL 8XL Free Size`. `XXL` → `2XL`,
`XXXL` → `3XL`; `Free Size` / `FREESIZE` / `One Size` / `FREE` → `Free Size`
(emitted with that exact label). **`FS` is NOT free size** - on Sweet Pini tags
it means full sleeves - so it is an error, never an alias. The frontend writes
"Size XL" but plain "Free Size". Ranges `M to 3XL`, `L-3XL`, `M–3XL` expand. One parser
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
`website/images/` also holds branding: `logo-round.png` (nav + footer mark;
falls back to `logo.png` if absent), the icon set `apple-touch-icon.png`
(180), `icon-192.png`, `icon-512.png` (all owner-supplied - never generate
substitutes) with `website/favicon.ico` (32) and `website/site.webmanifest`,
`hero-main.jpg`, `store.jpg` (About), `og-cover.jpg` (1200x630 link
preview). The build warns for any that are missing.

## Reviews (`REVIEWS` in products.js)

Real reviews only. **Never generate, invent or placeholder-fill reviews,
names, cities, ratings or dates** - not even as scaffolding. The build reads
an optional workbook sheet named `Reviews`:

| Column | Notes |
|---|---|
| `Name` | as the customer gave it (first name + initial is fine) |
| `City` | Ludhiana, Amritsar, Jalandhar ... |
| `Rating` | 1-5, one decimal allowed; anything else is skipped with a warning |
| `Review` | the customer's own words |
| `Date` | when received |
| `Published` | TRUE / FALSE, same convention as products (blank = TRUE) |
| `Source` | WhatsApp / Instagram / in-store |

No sheet -> `REVIEWS = []` + one warning; never a build failure. The frontend
removes the whole section when the array is empty (no "coming soon"), shows
"4.4 from 11 reviews" computed from the entries (floored to one decimal,
never rounded up), and carries no star markup or schema.org rating data.

Note for the owner: five real reviews beat fifty invented ones, and they are
easy to collect - after each delivered order, ask on WhatsApp. A 4.3 average
with one honest three-star reads as true. A 5.0 average reads as bought,
which is the opposite of the trust the section is meant to build.

## Frontend notes (`website/index.html`)

* `website/config.js` is the ONE config file, loaded by `index.html` and
  `policy.html`: `WA` (WhatsApp number), `OFFER`, `SUPPORT`, `COPY` and the
  shared `applyCopy()` / `applyWhatsAppLinks()`. Static links carry
  `data-wa="message"` and are filled at load.
* Cart is client-side (`localStorage` key `o4u_cart_v1`, shape
  `{ lines, updatedAt, sentAt }`; every read/write is try/catch - no storage
  means an in-memory cart). A line is product + colour + size;
  `Product A / Pink / M` and `/ L` never merge. Quantities are whole numbers
  1..99. A cart expires after 7 days; a sent cart is kept 30 minutes (so
  "Copy order details" still works) then discarded on the next load.
* Bag opening: the FIRST add of a session opens the drawer (so the customer
  sees the bag and the offer once); every later add closes the modal, shows
  one toast ("Added to bag · n items" + View bag, 2.5 s, timer resets, never
  stacks, role=status) and pulses the badge (skipped under reduced motion).
  Flag: `sessionStorage` `o4u_bag_opened`, try/catch, in-memory fallback.
* Order message = readable text, then the shared **O4U ORDER block** that
  Stockroom's "Paste order" box reads (format agreed 14 Oct 2026 - never
  change it on one side only):
  ```
  ----- O4U ORDER · please don't edit below -----
  CODE: W<DDMM>-<4 chars>-<2-char check>
  ITEM: <stockroom product id> | <size exactly as in stockroom.json> | <qty>
  NAME: … / PHONE: <10 digits> / ADDRESS: … / LANDMARK: … (line omitted when blank)
  ITEMS TOTAL (without delivery): ₹<items total as shown in the bag>
  ----- END O4U ORDER -----
  ```
  One ITEM per bag line, in bag order; random chars from
  `23456789ABCDEFGHJKMNPQRSTUVWXYZ`; the check is `o4uCheck(base, items)`
  (copied verbatim from the brief; test vector `ZP`) and covers code + items
  only. No other prices in the block. The same code is the `Ref:` at the top.
  Bag lines store `sizeCode` (from products.js `sizeCodes`). Name, phone (10
  digits; +91/0 stripped) and address are required in the bag's "Your
  details" (sessionStorage `o4u_details_v1`, this tab only); each is one line
  with no `---` runs. Long orders step down full → compact → minimal readable
  text (~1,900-char URL guard); the block is never shortened.
* Wording is always "order request". Never "confirmed", "paid", "guaranteed".
* Customer-facing policy text lives ONCE in `COPY` (config.js): positioning,
  delivery area, free-delivery rule, delivery charge (Porter fare confirmed on
  WhatsApp after the address), payment (UPI after confirmation, no COD),
  pricing (website price incl. offer is final), order request, the "opening
  WhatsApp doesn't send it" note, and the four exchange lines (approved
  14 Oct 2026). Elements carry `data-copy="key"`; never type these strings
  into markup. Short versions sit where they matter (delivery under the bag
  total, price note in the product view, four points in the pre-send step);
  full detail is on `policy.html`. The site NEVER calculates a delivery fee.
  Never write a refund promise, replacement guarantee or faulty-item outcome:
  wrong/faulty items are "handled separately" and only the transport is
  promised.
* Pre-order policy modal: opens on "Send order request" with a non-empty
  cart, never on page load. Four short points from COPY (order request,
  delivery area, payment, WhatsApp-send note) plus a link to policy.html.
  Acceptance is stored in `localStorage` `o4u_policy_accepted_v3` (ISO
  timestamp, try/catch). Bump the suffix whenever the points change.
* Order-value offer: `const OFFER = { enabled, kind, threshold, rate }` in
  config.js, next to `WA`. Owner-confirmed: `enabled:true,
  kind:'free-delivery', threshold:2000` - free delivery on orders of ₹2,000
  or MORE (`>=`). The threshold is compared with the product total after
  discounts (line prices are already offer prices); delivery is never in
  the figure. Never type the threshold anywhere else; COPY uses
  `{threshold}`, markup and the WhatsApp message read `orderTotals()`.
* Support: `const SUPPORT = { heading, topics[{key,label,tag}], noteMax,
  signature }` in config.js. The Help control (header pill +
  floating button) opens a guided sheet that only ROUTES to WhatsApp with
  `O4U SUPPORT — <tag>` / `Ref: S-MMDD-XXX` / product context / note. No AI,
  no API keys in the page, no stock answers - a human confirms stock.
  There are no generic "Order on WhatsApp" CTAs; the purchase path is
  card "Add to bag" -> modal "Add to bag" -> bag "Send order request on WhatsApp".
* Language: "bag" = the container the customer fills; "order" = the request
  sent to WhatsApp. The WhatsApp message itself still says ORDER REQUEST.
* Colour rule: orange = O4U actions (Browse Collection, Add to bag, Filter,
  Help); WhatsApp green (`.glass`) = ONLY buttons that actually open
  WhatsApp. A green button that doesn't open WhatsApp, or an orange one that
  does, is a bug. Orange buttons are frosted glass (owner request 14 Oct):
  tint `rgba(189,62,11,0.90)`, blur 10px, white edge + top highlight, white
  text >= 4.6:1 over white/page/cream. Solid `#C2410C` without
  backdrop-filter support, under prefers-reduced-transparency, and on
  low-end phones (`.lite-fx`: deviceMemory <= 2 or <= 4 cores). Card buttons
  blur only while `.in-view`. Don't lower the tint opacity without
  re-measuring contrast.
* Product modal ends with "More like this": products in the SAME CATEGORY
  or by the SAME NAMED BRAND (a blank brand never matches), at most five,
  available ones first, never the open one, no price rule. Never "Recommended
  for you" - there is no personalisation. Tapping one swaps the modal content
  in place (`openModal` while open): gallery back to image 1, size cleared,
  qty 1, scroll to top, row rebuilt, bag untouched.
* Search (catalogue, above the chips; never a `.reveal` element): name, brand,
  category, colour, Stockroom tags and article, accent-insensitive, every word
  must match. It combines with the chips and the Filter sheet; "Clear all"
  and "Clear filters" also clear it. Memory only.
* Brand label: small, under the product name on cards and in the product
  view, from real brand data; a blank brand shows nothing.
* Filter (hero, under Browse Collection): "Available in size" (sizes a
  product is MADE in - never live stock), price buckets (only those with
  products), sort Newest (= catalogue order, no date field) / price. It
  combines with the category chips, lives in memory only (never stored), and
  has no colour filter until the display-name map exists.
* No kids products exist, so the page carries no kids references. Re-add
  only when kids stock is in the workbook.
* `<head>` has description / Open Graph / theme-color tags. `og:image`
  must stay an absolute URL; replace `REPLACE-WITH-DOMAIN` when live.
* Product grid is two columns on every phone down to 320px (never one).
  Order buttons are one `.glass` token overlaid on the card image; card
  buttons blur only while `.in-view`.
* Statistics tiles (`[data-stat]`) are filled from products.js at load -
  designs in stock and category count. Never type a number there; a claim
  that cannot be computed or confirmed by the owner is removed, not softened.
* Branding images index.html needs: `logo.png`, `hero-main.jpg`,
  `store.jpg` (About section, owner to
  supply). The build warns when one is missing; the page shows a placeholder.

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
