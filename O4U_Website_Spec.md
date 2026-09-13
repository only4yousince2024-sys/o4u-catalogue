# O4U — Catalogue Website Spec

**Project:** Only 4 You — browsable catalogue with WhatsApp ordering
**Location:** `D:\claude projects\ONLY 4 YOU\website`
**Status:** Data pipeline built, frontend incomplete, not deployed
**Last updated:** 13 September 2026

---

## 1. What we're building

A static product catalogue website. A customer browses comfort wear, adds items to a cart, and taps a button that opens WhatsApp with a pre-filled order request. No payment gateway, no accounts, no backend database. The site is a beautifully presented menu; WhatsApp is the counter.

This is deliberately the simplest thing that can work. Every piece of complexity we skip is a piece we don't have to maintain.

---

## 2. The order flow

```
Customer browses site
        ↓
Adds items to cart (client-side only)
        ↓
Taps "Order on WhatsApp"
        ↓
WhatsApp opens with pre-filled order message → sent to O4U
        ↓
O4U manually checks stock availability
        ↓
O4U confirms with customer
        ↓
Customer sends delivery details + advance payment (incl. delivery charges)
        ↓
O4U packs the order
        ↓
Handed to Porter delivery partner
        ↓
3-day return window
```

**The key consequence:** because a human verifies stock before money moves, the site does *not* need real-time inventory sync. Slightly stale stock data is tolerable. This removes the single hardest technical requirement.

---

## 3. Division of labour

The split is **code vs. data**, not build vs. operate.

| Side | Owns | Files |
|---|---|---|
| **Claude Code** | Everything that *reads* the catalogue | `index.html`, CSS, cart logic, filters, WhatsApp link builder, responsive layout |
| **Cowork (Claude)** | Everything that *writes* the catalogue | Excel sheet, tag photos → rows, image processing, running the generator, Drive, Instagram/strategy |

**Both sides touch exactly one file: the product data.** That file is the seam. Keep it clean and both sides can move independently without breaking each other.

### Rules for the seam

- Claude Code never hand-edits the product data file — it is generated output.
- Cowork never edits frontend code.
- Schema changes are agreed before either side moves.
- The schema lives in `AGENTS.md` at the project root so Claude Code reads it automatically.

---

## 4. Data contract

Current shape emitted by `auto_generate_products.py`:

```js
{
  id:          "w1",              // stable per product
  name:        "E.Grey Cord Set",
  category:    "front-button",    // filter key
  price:       1465,              // selling price
  mrp:         null,              // strike-through original, or null
  image:       "images/1000062068.jpg",
  description: "...",
  badge:       "",                // "New", "Low stock", etc.
  badgeStyle:  "",
  sizes:       ["XL", "2XL"],
  colors:      ["E.Grey"],
  inStock:     true,
  article:     "CS250B"           // ← needs adding, required for fulfilment
}
```

### Category filter keys

| Key | Display name |
|---|---|
| `front-button` | Front Button Set |
| `round-neck` | Round Neck |
| `collar-neck` | Collar Neck |
| `salwar-set` | Salwar Set |
| `tshirt-lower` | T-Shirt / Lower |
| `tshirt-shorts` | T-Shirt / Shorts |

### Size vocabulary

Canonical order: `XS, S, M, L, XL, 2XL, 3XL, 4XL, 5XL`

`XXL` must be normalised to `2XL`. Ranges written as `"M to 3XL"` or `"L-3XL"` must be expanded, not split on whitespace.

---

## 5. The WhatsApp message

This is not a notification. **It is the order form O4U fulfils from.** Every field missing from it is a round-trip with the customer.

### Mechanism

```
https://wa.me/<number>?text=<url-encoded message>
```

No WhatsApp Business API. No cost. Works on mobile and desktop.

**Limit:** some clients truncate long URLs around ~2,000 characters. Keep the message compact — article numbers, not prose descriptions. A 15-item cart with full text will break.

### Required fields per line item

- Article no.
- Product name
- Colour
- Size
- Quantity
- Price per item

Plus, at message level:

- **Order ID** — generated client-side, e.g. `O4U-0913-A7K`
- **Timestamp**
- **Order total**

The order ID costs nothing to add and pays for itself immediately: both sides can refer to "order A7K" instead of scrolling, and it pins what price the site showed the customer if there's ever a dispute.

---

## 6. Current state

### Working

- `auto_generate_products.py` — Excel → product data pipeline runs end to end. Brand cleanup, category mapping, size sorting, scoring, file writing. Architecture is sound.
- `O4U_Stock_Inventory_UPDATED_v2.xlsx` — 215 data rows, 173 unique product variants, 24 description types, all mapped.
- Brands: Melini (157 rows), Sweet & Touch (57 across two spellings), Zaps / J.T. International (1).
- `products.js` — valid generated output, 12 products across 6 categories.
- Strategy layer complete: 15-Month Action Plan, Instagram Playbook, Market Research Report.

### Not built

- `index.html`, CSS, cart, filters, WhatsApp link builder — the frontend itself.
- Deploy target (Netlify intended, no config present).
- Processed product photography.

---

## 7. Known bugs — fix before building the frontend

Building a frontend against broken data means designing around bugs, then redesigning when they're fixed. Fix these first.

### Critical

1. **Sizes are wrong on every product.** The generator reads column F (`Size` — the size of one physical piece) instead of column J (`Available Sizes` — what the design comes in). **168 of 173 variants disagree.** A product listed L–5XL shows as `["XL"]`.

2. **Size text isn't parseable.** `Available Sizes` mixes formats: `"M to 3XL"` appears 42 times, `"L-3XL"` 3 times. Splitting on whitespace produces a size chip labelled **"to"**. `XXL` (18) and `2XL` (165) are used interchangeably.

3. **Price is mislabelled.** Generator sets `price: <MRP>, mrp: null`. The site sells at MRP with no strike-through. There is no actual selling-price column in the sheet at all — this needs adding upstream.

4. **`inStock` is hardcoded `true`.** Stock Qty column is ignored entirely.

### Significant

5. **The site shows 7% of stock.** `MAX_PRODUCTS = 12`, top 2 per category, 6 categories = exactly 12. The cap is saturated — adding a 7th category silently drops items via the final slice.

6. **Photo pipeline was never wired or run.** `polish_photos.py` still contains `YOUR_API_KEY_HERE`. It reads `raw_photos/` and writes `polished/` — neither folder exists. Actual folders are `images`, `stock`, `stock images`. Also: remove.bg free tier is 50 images/month; 119+ are needed.

7. **50 of 215 rows have no image.** Two products already ship as `placeholder.jpg`.

8. **`w11` is visibly broken** — name `" Gym Wear"` with leading space, `colors: [""]`, description reads *"Gym Wear in . by Melini."* Empty-field handling needed.

### Data hygiene

9. 17 duplicate barcodes, 9 rows missing barcodes, 86 rows carrying notes/flags.
10. Summary tab counts only Melini; `COUNTIF` range is `B3:B200` while data runs past row 217.
11. `clean_category()` silently defaults unknown descriptions to `front-button` instead of erroring.
12. `AGENTS.md` is an empty stub — one heading, no content.

---

## 8. Out of scope

Named explicitly so scope creep has to argue its way in:

- Payment gateway / online payments
- User accounts, login, saved carts
- Order database or admin panel
- Real-time inventory sync
- COD integration
- Shipping API integration (Porter is handled manually)
- Multi-language

---

## 9. Held decisions

Open, not urgent. Parked until Khush wants to work through them.

1. **Price display** — show real selling price on the card, or show MRP and negotiate in chat? The Market Research Report argues hard for transparent pricing in this band, and names constant discounting as Failure #1 (the discount death spiral). Counter-argument is margin flexibility.

2. **Delivery charges** — flat rate published on the site, or quoted per order? Publishing removes a round-trip and a common drop-off point, but commits to a number.

3. **Article numbers in the WhatsApp message** — include them (fast fulfilment, uglier message) or product names only (cleaner, slower)? A compact tail line can carry them without dominating the message.

4. **Data format for the seam** — keep `products.js` as a generated JS file, or move to `products.json`? JSON is easier to validate and harder to corrupt, but requires a `fetch` instead of a `<script>` tag, which affects hosting.

5. **Site-side policy display** — should the 3-day return window and advance-payment requirement appear before the customer orders? Reading it on the site makes it policy; hearing it after messaging makes it feel like a catch.

---

## 10. Immediate next steps

1. Fill in `AGENTS.md` with the schema, folder layout and seam rules from this document.
2. Add a selling-price column to the inventory sheet.
3. Fix the four critical pipeline bugs, regenerate the product data.
4. Connect `D:\claude projects\ONLY 4 YOU` to the Cowork session via the folder picker, so operations don't require upload/download round-trips.
5. Build the frontend in Claude Code against corrected data.
6. Process product photography.
7. Deploy.
