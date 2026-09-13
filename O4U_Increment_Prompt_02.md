# O4U — INCREMENT PROMPT 02

Continue on the existing O4U catalogue website at `D:\CLAUDE PROJECTS\ONLY 4 YOU`.

All rules from the master prompt still apply — in particular: repair, never rebuild; the Excel workbook is the single source of truth; `products.js` is generated and never hand-edited; commit at the end of each item.

Three changes.

---

## 1. PRE-ORDER POLICY MODAL

Before an order request is sent to WhatsApp, the customer must see and accept the terms once.

### Trigger

Fires when the customer clicks **Send order on WhatsApp** from the cart — **not** on page load. A modal that blocks the page on arrival costs sales and is not the point; the point is informed consent at the moment of ordering.

If the cart is empty, the button behaves as it does now.

### Content — exactly these four points, nothing else

- **Stock is confirmed manually.** We check availability and reply on WhatsApp before anything is paid.
- **Payment comes after confirmation.** Once we confirm, we ask for delivery details and an advance that includes the delivery charge.
- **Delivery charges apply** and are quoted when we confirm your order.
- **Returns within 3 days** of delivery.

Keep it to those four. No terms-and-conditions wall, no legal boilerplate. The customer should be able to read the whole thing in about ten seconds.

### Behaviour

- Two actions: **Accept & send order** (primary) and **Cancel** (ghost).
- Accept → record acceptance, close the modal, proceed to the existing WhatsApp handoff unchanged.
- Cancel → close, cart untouched, nothing sent.
- Store acceptance in `localStorage` under `o4u_policy_accepted_v1` as an ISO timestamp. Wrap the read and write in `try/catch` — if storage is unavailable, show the modal every time rather than failing.
- Once accepted, do not show it again on that device. Bump the key to `_v2` if the policy text ever changes, so returning customers see the new terms.
- Escape and clicking the backdrop both cancel. Focus moves into the modal on open and returns to the trigger on close.
- Mobile first: full-width sheet on small screens, centred dialog on desktop. It must be fully readable without scrolling on a Samsung S24 viewport.

### Also

Add the same four points as static text in the footer, so they are visible without ordering.

---

## 2. FOOTER / ABOUT SECTION

### 2.1 The empty image

The "Our Story" block shows an empty `STORE.JPG` placeholder.

- Expected file: **`website/images/store.jpg`**
- The shop owner will supply the photo. Until it exists, keep the existing graceful placeholder — do not ship a broken image icon.
- Treat it like product images: warn if missing, never fail.
- Serve it responsively and lazily; it is below the fold.

### 2.2 Rewrite the copy

Current text reads as a hobby shop. Keep the warmth, lose the diminutives ("small family shop", "adorable", "cozy").

Suggested replacement — the owner will adjust facts before it ships:

> **Built on comfort. Made with care.**
>
> Only 4 You is a comfort wear store on Pakhowal Road, Ludhiana. We stock women's loungewear, night sets and kurta sets, and formals for kids — chosen for fabric first. Pieces that keep their shape, breathe through the season, and feel the same on the tenth wear as the first.
>
> Ordering is straightforward. Send us the product on WhatsApp, we confirm availability and size, and arrange delivery. No accounts, no checkout queues — a direct conversation with the people who run the shop.

**Do not invent facts.** Any figure, date or location in this copy must be confirmed by the owner before it ships. If a claim cannot be confirmed, remove it rather than soften it.

### 2.3 The three feature points

Keep the structure, tighten the wording:

| Heading | Line |
|---|---|
| Fabric first | Breathable, durable materials selected for every piece |
| Order on WhatsApp | We help you choose the right size and colour before you pay |
| Women & kids | Comfort wear and formals, under one roof |

Replace the emoji icons (🧵 💬 👶) with simple inline SVG line icons. Emoji render differently on every device and undercut the tone. Keep them monochrome, inheriting the existing accent colour.

### 2.4 The statistics strip

The site currently claims **"2,000+ Happy Customers · Trusted by families since 2024"**.

**Ask the owner to confirm this number and date before shipping.** If either is unverified, replace the tile rather than keep it. Verifiable alternatives:

- The Pakhowal Road location and years trading
- Typical WhatsApp reply time
- Number of designs currently in stock — this can be generated live from `products.js`, which makes it true by construction and self-updating

Prefer the generated one. A number the build computes cannot become a lie.

---

## 3. REVIEWS — REAL ONLY, DATA-DRIVEN

### The rule

**Never generate, invent, or placeholder-fill customer reviews, names, locations or ratings.** No sample testimonials, no lorem-ipsum reviews with plausible names, not even as temporary scaffolding — placeholder reviews have a way of shipping.

Build the mechanism. The owner supplies the content.

### Data source

Reviews live in the workbook as a new sheet named **`Reviews`**, so they follow the same single-source-of-truth rule as products:

| Column | Notes |
|---|---|
| `Name` | as the customer gave it — first name and initial is fine |
| `City` | Ludhiana, Amritsar, Jalandhar etc. |
| `Rating` | 1–5, one decimal allowed |
| `Review` | the customer's own words |
| `Date` | when received |
| `Published` | TRUE / FALSE — same convention as products |
| `Source` | WhatsApp / Instagram / in-store |

The build reads this sheet and emits a `REVIEWS` array into `website/products.js` alongside `PRODUCTS` and `CATEGORIES`.

Apply the same missing-column rule as the product pipeline: if the `Reviews` sheet does not exist, emit an empty array with a warning. Never fail the build, never invent rows.

### Frontend

- If `REVIEWS` is empty, **the entire section does not render.** No empty state, no "reviews coming soon", no placeholder cards. The page reads as though the section was never designed.
- With entries: show name, city, rating and review text. Cards or a simple scroller, matching the existing visual language.
- Average rating is **computed from the actual entries**. Never hardcoded, never rounded up. Show it to one decimal alongside the count: "4.4 from 11 reviews".
- Do not add star-rating markup or aggregate rating structured data (schema.org) until there are real reviews — falsely marked-up ratings are a search-engine penalty as well as a lie.

### Note for the owner, to include in AGENTS.md

Five real reviews beat fifty invented ones, and they are easy to collect: after each delivered order, ask on WhatsApp. A 4.3 average with one honest three-star reads as true. A 5.0 average reads as bought — which is the opposite of the trust the section is meant to build.

---

## WHAT THE OWNER MUST SUPPLY

Do not ship these as guesses. Flag them and wait:

1. `website/images/store.jpg` — a photo of the shop
2. Confirmation of the "2,000+ customers / since 2024" figures, or approval to replace the tile
3. Real reviews for the `Reviews` sheet
4. Approval of the rewritten About copy, with facts checked

---

## ORDER OF WORK

1. Policy modal (§1) — self-contained, ships first
2. Footer copy, icons, image slot, statistics tile (§2)
3. Reviews pipeline and section (§3) — ships hidden until real data exists

Commit each separately:

```
feat: pre-order policy modal
chore: about section copy and assets
feat: reviews pipeline (data-driven, hidden when empty)
```

Then report per the master prompt: what changed, what was preserved, what was validated, and anything awaiting the owner.
