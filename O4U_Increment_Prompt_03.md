# O4U — INCREMENT PROMPT 03

Continue on the existing O4U catalogue website at `D:\CLAUDE PROJECTS\ONLY 4 YOU`.

Master prompt rules still apply: repair never rebuild, Excel is the single source of truth, `products.js` is generated and never hand-edited, commit per item.

Five changes. Item 2 is a one-line fix — do it first.

---

## 1. TWO COLUMNS ON EVERY PHONE (do this first)

`index.html` around **line 1209** currently contains:

```css
@media (max-width: 380px) {
  .product-grid { grid-template-columns: 1fr; }
}
```

This collapses the catalogue to a single column on any phone 380 CSS pixels or narrower — which is most Android phones (360px) and the smaller iPhones (375px). The owner's phone shows one product per screen because of this rule.

**Fix:** the grid must stay **two columns at every width down to 320px.**

```css
@media (max-width: 380px) {
  .product-grid { grid-template-columns: repeat(2, 1fr); gap: 10px; }
}
```

Then make two cards actually fit at 320px:

- Reduce card internal padding at this breakpoint
- Allow the product name to wrap to two lines, then ellipsis
- Hide `.pcard-desc` below 380px — the description is noise at that size, it belongs in the modal
- Reduce the category label and price sizes proportionally
- Nothing may overflow horizontally

**Test at 320, 360, 375, 390 and 414 px.** Two columns at all five, no horizontal scroll, no clipped text.

---

## 2. LIQUID-GLASS ORDER BUTTONS

The small flat green "Order" pill on the product cards should adopt the weight and presence of the large "Order on WhatsApp" button in the header, rendered as **liquid glass** — translucent, blurred, with a light edge.

### The spec

```css
.wa-btn {
  background: rgba(37, 211, 102, 0.58);
  backdrop-filter: blur(14px) saturate(180%);
  -webkit-backdrop-filter: blur(14px) saturate(180%);
  border: 1px solid rgba(255, 255, 255, 0.35);
  box-shadow:
    0 4px 18px rgba(0, 0, 0, 0.18),
    inset 0 1px 0 rgba(255, 255, 255, 0.45);
  color: #fff;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.25);
}
```

Add a soft specular highlight along the top edge — a `::before` with a white gradient at low opacity, fading downward. Keep it subtle. This should read as glass, not as a gradient button.

### Important: glass needs something behind it

A blurred translucent button sitting on the flat cream card footer has nothing to refract, so the effect is invisible and it just looks washed out.

**Move the card's Order button to overlay the product image** — bottom-right of `.pcard-img`, inset about 12px. The button then sits over photography (or the coloured placeholder) and the glass reads properly. It also frees the card footer for the price alone, which is cleaner at two columns.

Apply the same treatment to the header button, the floating WhatsApp button, and the modal's Add to order button — one glass token reused, not four variations.

### Required fallbacks

- `@supports not (backdrop-filter: blur(1px))` → solid `var(--green)`, no transparency
- `@media (prefers-reduced-transparency: reduce)` → solid fill
- Contrast: white text over translucent green on a light photo can fail WCAG AA. Keep the text-shadow, and darken the base to `rgba(28, 160, 76, 0.62)` if contrast testing fails. **Legibility wins over the effect.**
- `backdrop-filter` is expensive. With 172 cards on screen, verify scroll performance on a mid-range Android. If it stutters, apply glass only to buttons within the viewport, or drop to a semi-transparent background with no blur on the cards and keep full glass on the header and floating buttons.

---

## 3. GALLERY — 4 TO 5 IMAGES PER PRODUCT

The gallery already exists. This extends it so a customer can actually inspect a garment.

- The build discovers `<pid>.jpg`, then `<pid>-2.jpg` … `<pid>-9.jpg`. Keep that. **Target is 4–5 per product**, but never require it — most products will have one for a while, and some will have none.
- Modal: main image plus a thumbnail strip. The strip must be **visible and usable on mobile**, not desktop-only.
- Add horizontal **swipe** on the main image for touch. Arrow keys stay for desktop.
- Show a position counter — `2 / 5` — so the customer knows more images exist.
- With exactly one image, no gallery chrome at all: no arrows, no counter, no strip.
- The card always shows `images[0]` only.
- Preload the next image in the gallery; lazy-load the rest.

These are large garment photos. On a phone, the main image should be tappable to full screen.

---

## 4. CART — BASKET-BUILDING AND THRESHOLD OFFER

### The mechanic

When the cart holds items, show progress toward an order-value threshold that unlocks a discount:

```
Add ₹585 more to unlock 20% off
[━━━━━━━━━━━░░░░░]  ₹1,415 of ₹2,000
```

Once crossed:

```
✓ 20% off applied — you saved ₹412
```

### Rules

- **Threshold and discount rate live in ONE config constant**, alongside the WhatsApp number. Never hardcoded into markup or repeated across functions. The shop will change these.
- The discount applies to the order subtotal, displayed as its own line: subtotal, discount, total.
- The discount **must appear in the WhatsApp message** as an explicit line, so the shop and the customer are working from the same number:

```
Subtotal: ₹2,310
Discount (20%): −₹462
TOTAL: ₹1,848
```

- Delivery is **not** included in the threshold calculation and not in this total — it is quoted separately after confirmation, per the existing policy.
- If the cart is empty, no progress bar, no mention of the offer.

### A question for the owner before this ships

**20% is steep for a threshold offer, and it is a permanent discount state.**

The O4U Market Research Report names the Discount Death Spiral as Failure #1 — customers learn to wait for the discount and full price stops feeling real. A standing "20% over ₹2,000" teaches exactly that: nobody buys a ₹1,400 item at full price once they know ₹2,000 costs ₹1,600.

Two alternatives that lift basket size at much lower margin cost:

1. **Free delivery over ₹2,000.** Delivery is already a real, separately-quoted cost the customer is conscious of. Removing it feels like a substantial win but costs the shop only the actual Porter fare — far less than 20% of the order.
2. **A smaller threshold discount, 10%**, which still moves basket size without repricing the catalogue.

**Do not implement any rate until the owner confirms it.** Build the mechanic with the value in config so it can be changed in one place, and ask before shipping the number.

---

## 5. CART HEADER — ADD MORE

The cart drawer header currently has a close **×**.

The owner's request: keep the × when the cart is empty, and replace it with an "Add more" button once items are in the cart.

**Implement the intent, not the literal swap.** Removing the only close control from a full-screen mobile drawer traps the customer — the one state where they most need an exit is the one where they are deciding whether to spend money.

**Do this instead:**

- The **×** stays, always, in the top corner. It is the escape hatch.
- When the cart has items, add a distinct **"+ Add more items"** button — full width, directly below the line items and above the totals. Ghost or outline style, so it does not compete with the primary send button.
- It closes the drawer and scrolls back to the product grid, preserving the active category filter.
- When the cart is empty, no such button — the empty state already invites browsing.

This gives the encouragement the owner wants while leaving the exit intact. If the owner still wants the × replaced outright after seeing it, that is a one-line change later.

---

## AWAITING THE OWNER

Do not ship these as guesses:

1. **The discount rate and threshold** (§4) — 20% / ₹2,000 is proposed, not confirmed
2. **Whether to use free delivery instead of a percentage discount** (§4)

---

## ORDER OF WORK

1. Two-column fix (§1) — one line, ship immediately
2. Liquid glass (§2)
3. Gallery extension (§3)
4. Cart threshold mechanic (§4) — built, rate unconfirmed
5. Add-more button (§5)

```
fix: two-column product grid on all phone widths
feat: liquid-glass order buttons
feat: gallery swipe, counter and mobile thumbnails
feat: cart order-value threshold (rate pending confirmation)
feat: add-more button in cart
```

**Verify after each:** the catalogue still renders 172 cards, and nothing overflows horizontally at 320px.
