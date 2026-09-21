# O4U — The Launch Content Pack

Roughly 30 of the 40 items in that review are **writing, not code.** They cost zero credits. They are also the bottleneck: half the P0 list can't be built until this text exists.

This is that text, with blanks where only you know the answer. Fill it in a plain file and hand the whole thing to Claude Code in one pass.

---

## 1. SIZE GUIDE — the highest-value thing you can do this week

Size is the number one cause of clothing returns. GPT is right that it's missing, and it's a physical job, not a code job.

### Measure the garment, not the body

Don't publish body measurements ("L = 38" bust"). You don't have fit models and you'd be guessing. **Measure your actual stock flat with a tape**, and let the customer compare against a garment she already owns. That's more honest and more accurate.

### The method

Lay the garment flat, smooth out wrinkles, don't stretch. All measurements in **inches**, doubled where noted.

| Measurement | How |
|---|---|
| **Chest** | Across, 1 inch below the armhole seam → **double it** |
| **Length** | Highest point of shoulder straight down to hem |
| **Waist** (bottoms) | Across the waistband, relaxed → **double it** |
| **Hip** (bottoms) | Across at the widest point → **double it** |
| **Inseam** | Crotch seam to hem |
| **Sleeve** | Shoulder seam to cuff |

### What to publish

Do this **once per size, per style family** — not per product. Night suits, co-ord sets and kurta sets each get their own table. That's maybe three tables, not 170.

```
NIGHT SUITS — garment measurements, inches

Size   Chest   Length   Waist   Inseam
M      __      __       __      __
L      __      __       __      __
XL     __      __       __      __
XXL    __      __       __      __
3XL    __      __       __      __
```

Add this line under every table, because it's the thing that actually prevents returns:

> Measurements are of the garment laid flat, not of the body. Compare against a similar piece you already own and like the fit of. Still unsure? Message us on WhatsApp with your usual size and we'll tell you which will fit.

**Free Size** items get their own note — the review is right that "Free Size" can't be a blanket claim. State the actual chest and length, and the range it comfortably fits.

---

## 2. PRODUCT CODES — use the ones you already have

GPT suggests inventing codes like `O4U-NS-042`. **Don't.**

You already have codes. They're printed on the physical tags and they're in your workbook: the article number. `14560B`, `CS250A`, `7724291-C`. Your father knows them. Your suppliers know them. They're on the garment.

Inventing a second numbering scheme gives you two identities per product to keep in sync — which is exactly the failure that lost you the photo linkage the first time round.

**What to actually do:** make sure the article number and colour appear on the product card, in the modal, and in the WhatsApp message. That's the whole fix, and the data is already there.

---

## 3. THE WHATSAPP MESSAGE — the most important thing on the site

This is where your father does his job. Get this right and everything else is decoration.

Target format:

```
ORDER REQUEST — ONLY 4 YOU
Ref: O-0921-K3M

1. Printed Night Suit
   Article: 14560B · Black Pink Geometric
   Size: XL · Qty: 1 · ₹1,589

2. Rayon Co-Ord Set
   Article: CS250A · Maroon
   Size: L · Qty: 1 · ₹1,499

Items total: ₹3,088
Delivery: to be confirmed

Please confirm availability and delivery charge.
Sent from only4you website
```

**Article number and colour on every line.** That single change removes the "which blue one?" conversation from every order you ever take.

**Test on three devices before launch:** Android Chrome, iPhone Safari, desktop Chrome. `wa.me` links behave differently on each and this is the one thing that must never silently fail.

**Add a fallback.** If WhatsApp doesn't open, the customer currently loses the whole order. A **Copy order details** button next to **Try again** costs nothing and saves the sale.

---

## 4. THE POLICY PAGES

Write these as plain text. Every `___` is a decision only you can make. I'm not a lawyer — have someone qualified read the final wording before launch, especially the privacy and terms pages.

### 4a. Shipping & Delivery

```
DELIVERY

Ludhiana
  Charge: ₹___
  Timeline: ___ (e.g. same day / next day)

Punjab (outside Ludhiana)
  Charge: ₹___
  Timeline: ___ working days

Rest of India
  Available: yes / no
  Charge: ___
  Timeline: ___ working days

How it works
  We confirm stock and the exact delivery charge on WhatsApp
  before any payment is made.

Payment
  After confirmation we ask for an advance of ___
  (full amount / product amount + delivery / ₹___ )
  paid by ___ (UPI / bank transfer).
```

**The advance question is the one to nail down.** Right now the site says "an advance that includes the delivery charge" without saying how much. Your father is explaining that fresh to every customer. Pick a rule and write it once.

### 4b. Returns & Exchanges

```
RETURNS & EXCHANGES

Window
  ___ days from delivery. (currently stated as 3)

What we accept
  Wrong item sent                         yes
  Damaged or defective on arrival         yes
  Size doesn't fit                        ___
  Changed my mind                         ___
  Sale or discounted items                ___

Condition required
  Tags attached, unworn, unwashed, in original packaging.
  Items that have been worn or washed cannot be returned.

Not accepted
  Innerwear, for hygiene reasons.
  ___

What you get back
  Our fault (wrong item, defect):  ___ (refund / exchange / your choice)
  Size or preference:              ___ (exchange / store credit / refund)

Return delivery cost
  Our fault:        we pay
  Size/preference:  ___ (you pay / we pay / split)

How to start one
  Message us on WhatsApp with your order reference within ___ days.

Refund timeline
  Within ___ working days of the item reaching us, by UPI to the
  account that paid.
```

**Think hard about the hygiene line.** Standard practice excludes nightwear — but your catalogue is almost entirely nightwear. If you copy that exclusion, your "3-day returns" promise covers nothing. Tags-intact-and-unworn is the version that's both honest and protective.

### 4c. Privacy Policy

Human-readable, not a fifteen-page monster.

```
PRIVACY

What we collect
  When you order through WhatsApp we receive your name, phone
  number and delivery address. We keep a record of what you
  ordered so we can handle delivery, exchanges and returns.

  The website itself does not ask you to create an account and
  does not collect your details before you message us.

  Your cart is stored in your own browser and never sent to us.

Why we keep it
  To fulfil your order, arrange delivery, and handle any return
  or exchange.

Who else sees it
  Your name, phone and address go to the delivery service that
  brings your order. Nobody else.

How long
  ___ (e.g. we keep order records for ___ months)

Your choices
  Message us on WhatsApp to ask what we hold about you, to
  correct it, or to ask us to delete it.

Contact
  ___
```

India's data protection framework has notice-and-consent requirements. The version above is honest and plain; have it checked before it goes live.

### 4d. Contact & Grievance

```
CONTACT US

Only 4 You
[full shop address], Pakhowal Road, Ludhiana, Punjab ______

WhatsApp:  +91 _____
Call:      +91 _____
Email:     _____
Instagram: _____

Open: ___ to ___, ___ days

[ Open in Google Maps ]

Something wrong with your order?
Message us on WhatsApp with your order reference and we'll
sort it out. If it isn't resolved, contact ___ directly at ___.
```

**The Google Maps link is the cheapest trust you can buy.** A real address with a working map instantly separates you from an anonymous Instagram seller. Grab the link from your Google Business listing — and if you don't have one yet, create it. Free, and it's how people in Ludhiana will find the physical shop.

---

## 5. COPY REWRITES

### The page title

Current: `Only 4 You — Comfort & Style`

Better: `Only 4 You | Women's Comfort Wear in Ludhiana`

Nobody searches for "comfort & style". People search for what you sell and where you are.

### The ticker

Current is keyword soup: *Women's Comfort Sets · Cord Sets · Night Wear · Order on WhatsApp · Free Size · Help · Fast Delivery · New Arrivals*

Cut it to four things that are all true:

```
WOMEN'S COMFORT WEAR · STORE ON PAKHOWAL ROAD · ORDER ON WHATSAPP · EASY EXCHANGE
```

### Claims to delete

These are on the site and you can't back any of them:

- **"Fast Delivery"** — either state the actual timeline or remove it
- **"Order in 60 seconds"** — nobody cares how fast the UI is
- **"100% Personal service every order"** — unverifiable and reads as filler
- **"Genuine Fabrics"** — awkward, and "genuine" implies others are fake

Replace the last one with something you can prove: the actual fabric per product. *Cotton. Rayon. Satin.* One word, true, and more useful than any adjective.

### About section

GPT wrote you story copy built on "founded in 2024." **Check that date before you publish it.** You flagged this figure as unverified weeks ago and now an AI has quietly turned it into your origin story. Confirm the real year with your father.

The shape is right though — your advantage is that you're an actual shop with actual people, not a D2C brand:

```
Started in Ludhiana. Built around everyday comfort.

Only 4 You opened on Pakhowal Road in ____. We're family-run —
[father's name] is usually the one who'll answer when you message.

We stock women's loungewear, night sets and kurta sets. You can
visit the shop, or browse here and order on WhatsApp. We'll confirm
what's in stock and help you pick a size before you pay anything.
```

That's more believable than anything about fabric breathing through the season.

---

## 6. ONE WORD THAT PROTECTS THE WHOLE MODEL

The review's sharpest single point: **don't display "In Stock."**

Your stock is confirmed by a human. The moment the site claims availability it can't verify, you've broken the one promise the entire business rests on — and you've wasted a Porter trip and a customer.

Change the label to:

> **Availability confirmed on WhatsApp**

One string. Protects everything.

---

## 7. WHAT TO ADD TO THE CLAUDE CODE PROMPT

Fold these into the consolidated prompt from the Go-Live Map rather than running a separate round.

```
## 6. WHATSAPP MESSAGE — add product identity

Every line item in the generated WhatsApp message must include the
article number and colour, taken from the existing product data:

  1. Printed Night Suit
     Article: 14560B · Black Pink Geometric
     Size: XL · Qty: 1 · ₹1,589

Do NOT invent a new product-code scheme. The article number on the
physical tag is the shop's real identifier and must be the one used.

Add a "Copy order details" button beside the existing "Try again"
fallback, so a failed WhatsApp handoff does not lose the order.

Test the wa.me link on Android Chrome, iOS Safari and desktop Chrome.
Report any difference in behaviour.

## 7. AVAILABILITY LABEL

Replace any "In Stock" / "Available" badge with:
  "Availability confirmed on WhatsApp"
Stock is verified by a human. The site must never claim availability.

## 8. CART LOGIC — verify and fix

- Adding the same product+size+colour twice must MERGE into one line
  with qty 2, not create two lines.
- Same product, different size or colour, must stay as separate lines.
- Quantity must clamp to a minimum of 1 and a sensible maximum.
  Reject 0, negatives and non-numeric input.
- Cart persists in localStorage, and clears after an order is sent
  or after 7 days, whichever comes first.
- Empty cart: send button disabled, no discount UI, no progress bar.

Write a test for each of these.

## 9. SIZE GUIDE

Add a "Size Guide" link in the product modal, next to the size
selector, opening a sheet with per-style-family measurement tables.

Tables come from a config object the owner edits — one entry per
style family (night suits, co-ord sets, kurta sets), NOT per product.
Leave the numbers as clearly-marked TODO. Do not invent measurements.

Include the line: "Measurements are of the garment laid flat, not the
body." and a "Still unsure? Message us" WhatsApp link.

## 10. FOOTER POLICY PAGES

Footer links to: About · Contact · Shipping & Delivery · Returns &
Exchanges · Privacy Policy · Terms & Conditions · Size Guide

Content from a single config object supplied by the owner. Placeholder
TODO text until then. Do NOT generate policy or legal wording.

Add the full shop address and an "Open in Google Maps" button to the
footer and the contact section.

## 11. COPY CLEANUP

Remove: "Fast Delivery", "Order in 60 seconds", "100% Personal service
every order", "Genuine Fabrics".

Page title → "Only 4 You | Women's Comfort Wear in Ludhiana"

Ticker → "WOMEN'S COMFORT WEAR · STORE ON PAKHOWAL ROAD · ORDER ON
WHATSAPP · EASY EXCHANGE"

Verify the reviews section does not render at all when REVIEWS is
empty, per the original spec. Report if it currently does.
```

---

## 8. WHAT TO IGNORE FOR NOW

So you don't spend money on the wrong things.

**Price manipulation protection.** Overblown for your setup. Yes, someone can edit a price in their browser — but there's no payment on your site. Your father reads every order and confirms the amount before any money moves. The manipulated number gets caught by a human within minutes. Add the line *"prices subject to confirmation"* to the message and move on.

**Analytics.** Right idea, wrong time. At a handful of orders a day the numbers are too small to mean anything. You'll learn more from three WhatsApp conversations than from a funnel chart. Revisit at real volume.

**"Notify me" for out-of-stock items.** You don't have a stock system that knows when something returns. It would be a button that goes nowhere.

**Search and filters.** Genuinely needed — but only once the catalogue is actually live and you know how many products it has. If you launch with 40 curated pieces, categories are enough.

**More categories.** You have six and a catalogue that isn't live yet. Don't add structure before there's stock to fill it.

**Customer accounts.** Both reviews and I agree: no. WhatsApp is your CRM.

---

## THE HONEST SUMMARY

That review has maybe eight items that will change whether you make a sale, and thirty-two that are polish or premature.

The eight:

1. Article number in the WhatsApp message
2. Size guide with real measurements
3. Stop claiming "In Stock"
4. Returns policy actually written
5. Full address, map link, contact details
6. Cart variant merging and quantity validation
7. WhatsApp fallback so a failed handoff doesn't lose the order
8. Delete the unverifiable claims

Seven of those eight are **you writing or measuring something**, not code.

And the thing neither review has noticed, across two rounds: **your live site still serves 172 products with no images.** Both AIs have now carefully reviewed a catalogue you aren't launching.
