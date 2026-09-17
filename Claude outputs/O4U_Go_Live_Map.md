# O4U — What's Actually Left

Everything from here to launch, in the order that matters. Decisions you make cost nothing. Only the last section needs credits.

---

## THE ONE THING BLOCKING EVERYTHING

Your live site right now serves **172 products, every single one with no image.**

Those are the old May inventory rows. The Stockroom swap never reached production — the change was made locally and never pushed, or never made at all.

So every conversation we've had about photos, galleries, cropping and image quality is happening on a catalogue that isn't the catalogue you're launching.

**Do this before anything else:**

1. Open Netlify → **Deploys** tab. Look at the newest deploy timestamp.
2. If it's days old, nothing is reaching the site. Run `sync.bat`.
3. Confirm at `only4you-store.netlify.app/products.js` — the first line tells you the count. You want it to match your Stockroom published count, not 172.

Until that number is right, nothing else you fix is visible to a customer.

---

## DECISIONS ONLY YOU CAN MAKE

These cost nothing and they're blocking real work. Six of them have been open for weeks.

### 1. Delivery charge — flat or quoted?

Still unanswered from the first week. **You cannot write a help page or a return policy without this.**

- **Flat rate** (say ₹80 within Ludhiana, ₹150 outside): customer knows the number upfront, no back-and-forth, you eat the variance on far deliveries.
- **Quoted per order:** accurate, but every single order needs a manual message before the customer commits — and some will drop at that point.

For your volume, flat within Ludhiana and quoted outside is the usual middle. Pick something. You can change it later; you can't launch without it.

### 2. Returns — refund, exchange, or store credit?

This is the biggest open decision and it has real money attached. See the full section below.

### 3. Kids section

Your site has a **Kids** nav link, kids copy in the hero, and "Kids Formals" in the marquee. Your catalogue has **zero kids products.**

A customer taps Kids and lands on women's loungewear. That's a broken promise on the first interaction.

Two honest options — pick one:

- **Remove all kids references** until you have kids stock. Reversible in minutes later.
- **Keep them but make them true** — Kids link goes to a short section saying kids' formals are in-store, with a WhatsApp enquiry button.

Leaving it as-is is the only wrong answer.

### 4. Cart discount rate

20% over ₹2,000 was proposed and never confirmed. I'd push back on 20% — your own Market Research names the discount death spiral as failure #1, and a standing 20% teaches customers that full price isn't real.

**Free delivery over ₹2,000** does the same job to basket size and costs you the Porter fare instead of a fifth of the order.

### 5. The `7724090-F` duplicate

Two products share this article number: a T+Pants set at ₹749 and a Button-Up Combo at ₹924. The whole Button-Up group appears to carry the T+Pants article number.

**Go check the physical tag on a Button-Up Combo.** If the number differs, the sheet is wrong. If it's genuinely the same, those rows need archiving or the build will keep erroring.

### 6. Domain

`only4you.style` lapsed. Verified free as of last check:

- `only4youstore.com`
- `only4youshop.com`
- `shoponly4you.com`
- `only4youwear.com`

**Buy one.** Not because it brings traffic — it won't — but because your entire distribution is pasting a link into WhatsApp and your Instagram bio. `only4you-store.netlify.app` reads as a test project. A real domain reads as a real shop. Roughly ₹800–1,200/year. It's the cheapest credibility on this list.

---

## DO YOU NEED CUSTOMER ACCOUNTS? — No.

You asked directly, so here's the direct answer, with the reasoning so you can overrule me later when it changes.

**What an account gives a customer:** saved address, order history, faster repeat checkout, and you get a marketing list.

**Why none of those apply to you right now:**

- **You have no checkout.** The order happens in WhatsApp. There's nothing for an account to speed up.
- **WhatsApp already is the account.** It holds their number, their name, the full order history, their address from last time, and a direct channel with far better open rates than email will ever give you in India.
- **Accounts need a backend.** Database, authentication, password resets, session handling. Your site is static files on a CDN — that's why it costs nothing to run. Adding accounts is a different product with a monthly bill.
- **It adds friction at the worst moment.** Every field between "I want this" and "message sent" loses customers. On a catalogue with no reviews and no brand recognition yet, that's expensive.
- **Storing customer personal data creates obligations** under India's data protection law. Right now the data lives in WhatsApp, which is a channel you use rather than a database you operate.

**What you actually need instead** is an order record on *your* side — a simple sheet: order ref, date, customer name, phone, items, amount, status. That's an ops habit, not a website feature, and it costs nothing.

**Revisit accounts when** all three are true: you take payment online, you have repeat customers asking for order history, and manual tracking has actually broken. Not before.

---

## RETURNS AND EXCHANGES — the real system

Right now you promise "3-day returns" and there's no system behind it. A system here is 80% policy decisions and 20% code.

### The six decisions

**1. Refund, exchange, or store credit?**

- *Refund* — most customer-friendly, hardest on your cash flow.
- *Exchange* — the item comes back, another goes out. Good for size issues, which will be most of your returns.
- *Store credit* — safest for you, but reads as stingy if it's the only option.

Most small clothing shops land on: **exchange or store credit as standard, refund only when the fault is ours** (wrong item sent, defect, not as described).

**2. Who pays return delivery?**

If you pay, returns get casual. If the customer pays, you get fewer returns and more resentment.

The standard split: **shop pays when the fault is the shop's, customer pays when it's preference.** Say it in exactly those words and nobody argues.

**3. Condition requirements**

Non-negotiable for clothing, and you must state them or you'll get worn garments back:

> Tags attached, unworn, unwashed, in original packaging.

**4. Hygiene exclusion — think carefully here**

Most Indian retailers exclude nightwear and innerwear from returns on hygiene grounds. **Your catalogue is almost entirely nightwear and loungewear.** If you exclude it, your "3-day returns" promise covers nothing and you've built a policy that lies.

The workable version: **returns accepted when tags are intact and the item is unworn**, innerwear excluded entirely. That's honest and it still protects you.

**5. How the money goes back**

UPI to the account that paid, within a stated window — e.g. *within 3 working days of the item reaching us.* State the window. Vagueness here is what turns a return into a fight.

**6. Who arranges the pickup**

You use Porter. Does the customer send it, or do you book the return trip? Decide, because it's a real cost per return and it determines decision #2.

### What needs to exist on the site

Once you've decided the above, a return "system" for your scale is three things:

1. **A returns page** stating the policy in plain words — what qualifies, what doesn't, who pays, how long, how the money comes back.
2. **A start-a-return button** that opens WhatsApp pre-filled with the order reference, same mechanic as your support flow.
3. **A column in your order sheet** — `returned / exchanged / refunded` with the date.

That's it. No portal, no login, no automation. At your volume a human handling each one is faster and better than any system you could build.

### One compliance note

India's Consumer Protection (E-Commerce) Rules 2020 require sellers to display, before purchase: **legal name, registered address, contact details, and the return / refund / exchange / delivery policies**, plus grievance-redressal contact details.

Your site currently shows almost none of this. Whether the rules bind you exactly — you take orders by message rather than payment on-site — is worth **one conversation with your CA**, and I'm not a lawyer. But displaying your shop name, Pakhowal Road address, phone and written policies costs you nothing and is what a real shop looks like anyway. Do it regardless of what the answer turns out to be.

---

## THE HELP PAGE — you're right, it doesn't help

What you built is a **router**: pick a topic, it opens WhatsApp. That's correct and it should stay. But a router with no answers means every single question becomes a message you have to type.

**The fix is content, not code.** Of the eight questions customers will actually ask, seven can be answered without you.

| Question | Who answers |
|---|---|
| Is this available in my size? | **You** — stock is manual. Keep in router. |
| How long does delivery take? | Page |
| What are the delivery charges? | Page — *needs decision #1* |
| How do I return something? | Page — *needs the returns decisions* |
| Can I exchange for a different size? | Page — *needs the returns decisions* |
| How do I pay? | Page |
| Do you have an actual shop? | Page |
| Will the colour match the photo? | Page |

That last one matters more than it looks. Screen colour varies, and "it looked different online" will be one of your top return reasons. Saying so upfront — *"colours may vary slightly between screens; message us and we'll describe the actual shade"* — prevents returns and builds trust at the same time.

**So the help page becomes:** the seven answers written out, then the router at the bottom for everything else. One screen, no accordion nonsense.

Notice that **five of the eight answers are blocked on decisions you haven't made.** That's why the decisions come first.

---

## IMAGE GENERATION — what to actually study

You asked about studying a creative site for this. The useful reframe: **your problem isn't creativity, it's consistency.** One beautiful image is easy. A hundred and seventy that look like the same shop shot them is the hard part, and that's a systems skill.

**What to build:** one locked base prompt with slots.

```
[garment description] on a neutral mannequin,
full-length centred frame,
warm cream backdrop, soft diffused daylight from the left,
3:4 portrait, no props, no text
```

Everything inside the brackets changes per product. **Nothing else ever changes** — not the light, not the backdrop, not the framing, not the crop. The moment you improvise per-product, your grid stops looking like a catalogue and starts looking like a mood board.

**What to study:** not AI art sites. Study how established comfort-wear and loungewear brands lay out their product grids — camera height, how much headroom, how the garment sits in frame, how they handle a set versus a single piece. Screenshot ten product pages you think look expensive and find what they have in common. That's your spec.

**Keep your generation prompt in a text file next to the workbook.** In two months you'll add products and you'll need the exact same prompt to make them match.

---

## WHEN YOU SPEND CREDITS — one prompt, not five

You're low, so don't do these as separate rounds. Everything below goes to Claude Code in a single pass.

```
Read AGENTS.md first. All existing rules apply.

Five changes, one pass.

## 1. MODAL GALLERY CROP (highest priority)

.gal-main is a fixed 300px box with object-fit: cover, so 3:4 product
photos centre-crop — heads and hems cut off, some images show only
trousers. The thumbnails show full frames, which proves the files are
fine and the container is wrong.

.gal-main {
  position: relative;
  width: 100%;
  aspect-ratio: 3 / 4;
  max-height: 72vh;
  overflow: hidden;
  background: var(--cream);
  display: flex;
  align-items: center;
  justify-content: center;
}
.gal-main img { width: 100%; height: 100%; object-fit: contain; }

Do NOT change .pcard-img or the thumbnails — the grid needs uniform
tiles and thumbnails are identity markers. Arrows, counter, swipe and
the badge all stay.

Tap-to-fullscreen must also use object-fit: contain on a dark backdrop.

Check the sticky header's z-index against the modal backdrop — in the
owner's screenshots the nav is visible above the dimmed overlay. The
modal and backdrop must sit above the header.

## 2. DISPLAY-NAME MAPPING

Product names come off physical tags and are inconsistent in the live
data: "Affgani" / "Afgani" / "Afgaan" are the same garment; "Mehroon"
and "Mahroon" are both maroon; "Cord Set" and "Co-Ord Set" both appear;
and abbreviations like D.Move, D.Olv, Jun.Gn, L.Pista, Ch.Grey, P.Heart,
B.White are unreadable to a customer. One product is literally named
"NIL Cord Set".

DO NOT edit the source data — the tag is the record of truth and someone
will re-enter the same strings next week.

Add a display-name map applied at build time in build_catalogue.py. Data
keeps D.Move, the site renders Dark Mauve. One table, one place, easy to
extend. Unmapped values pass through unchanged and are listed in the
build report so the owner can see what still needs an entry.

Normalise "Cord Set" to "Co-Ord Set" throughout via the same map.

Flag any product whose name is empty or reads as a placeholder (NIL,
blank colour) as a build WARNING, not an error.

## 3. STORE PHOTO, FAVICON, LINK PREVIEW

The owner is supplying:
  website/images/store.jpg          1200x1200
  website/images/og-cover.jpg       1200x630
  website/favicon.ico               32x32
  website/images/apple-touch-icon.png  180x180

Wire store.jpg into the About section, replacing the placeholder.
Keep the rounded frame and the overlapping "100% personal service" card.
Crop must not be applied — the file is already square.

Add to <head>, replacing any fevicon.png reference:
  <link rel="icon" href="/favicon.ico" sizes="32x32">
  <link rel="apple-touch-icon" href="/images/apple-touch-icon.png">
  <meta name="description" content="Women's comfort wear and loungewear in Ludhiana. Browse, then order on WhatsApp.">
  <meta property="og:title" content="Only 4 You — Comfort Wear, Ludhiana">
  <meta property="og:description" content="Night sets, co-ord sets and kurta sets. Browse the catalogue and order on WhatsApp.">
  <meta property="og:image" content="https://<DOMAIN>/images/og-cover.jpg">
  <meta property="og:type" content="website">
  <meta property="og:url" content="https://<DOMAIN>/">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="theme-color" content="#1b2430">

og:image MUST be an absolute URL. Leave <DOMAIN> as a placeholder and
flag it in the report for the owner to fill in once the domain is bought.

Any missing file: keep the graceful placeholder. Never a broken image,
never a generated substitute.

## 4. HELP PAGE — ANSWERS, NOT JUST ROUTING

The current help sheet only routes to WhatsApp. Add written answers above
the router, driven by a single config array so the owner can edit copy in
one place:

  delivery time, delivery charges, how to return, how to exchange,
  payment methods, physical store address and hours, colour accuracy

Leave the answer strings as clearly-marked TODO placeholders. DO NOT
invent delivery times, charges, or policy terms — the owner has not
decided these yet and a guessed number on a live site becomes a promise.

Keep "Is this available in my size?" as a router topic only. Stock is
confirmed by a human and must never be answered by the page.

## 5. RETURNS PAGE

New section or page, content from the same config object:
  what qualifies, what does not, who pays return delivery, the time
  window, how refunds are issued, how to start one

Add a "Start a return" button that opens WhatsApp pre-filled with an
order-reference field, using the existing support-flow mechanic.

Also add a footer block with shop legal name, Pakhowal Road address,
phone, and a link to the returns policy.

All copy as TODO placeholders. Owner supplies the real text.

## DONE WHEN
- A 5-image product shows the whole garment at every index, at 360px,
  390px and 1280px
- Build report lists any unmapped display names
- python scripts/test_build_catalogue.py passes
- Nothing overflows horizontally at 320px
```

---

## SO WHAT'S LEFT, ALL IN

**Blocking launch**

- [ ] Stockroom products actually reaching production — *the big one*
- [ ] Photos generated for every product you want live
- [ ] Delivery charge decided
- [ ] Return policy decided
- [ ] Kids section resolved
- [ ] Store photo, og-cover, favicon files made and dropped in
- [ ] Domain bought and pointed at Netlify

**Makes it look like a real shop**

- [ ] Display-name map (Afgani / Mahroon / D.Move)
- [ ] Meta tags with the real domain — right now your link pastes into WhatsApp as bare blue text
- [ ] Shop name, address and phone in the footer
- [ ] `7724090-F` physical tag checked

**Saves you work every single day**

- [ ] Help page answers written
- [ ] Returns page written
- [ ] Order log sheet started — ref, date, name, phone, items, amount, status
- [ ] The daily stock-update habit actually running

**Deliberately not now**

- Customer accounts — WhatsApp is your CRM
- Online payments — the manual stock confirmation is the whole model
- AI chat support — it will guess about stock, which is the one thing it must never do
- Reviews section — it's built and hidden. It stays hidden until you have real ones. Ask for them on WhatsApp after each delivered order. Five real ones beat fifty invented.

---

## IF YOU ONLY DO THREE THINGS

1. **Get the real catalogue live.** Everything else is decoration on a site showing 172 ghost products.
2. **Make the six decisions.** They cost nothing and five separate pieces of work are stuck behind them.
3. **Buy the domain.** Your whole distribution is a link in WhatsApp.

Everything else can wait for the next round of credits.
