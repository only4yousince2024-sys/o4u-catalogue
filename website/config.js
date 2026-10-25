// ═══════════════════════════════════════════════════════════════════════
//  ONLY 4 YOU — SITE CONFIG. The ONE place for the WhatsApp number, the
//  free-delivery threshold, the help topics and every customer-facing policy
//  sentence. Loaded by index.html and policy.html; edit here, nowhere else.
// ═══════════════════════════════════════════════════════════════════════

// Every wa.me link on the site is filled from this at load time.
const WA = '918146597775';
const WA_DISPLAY = '+91 81465 97775';

// ── ORDER-VALUE OFFER ── the ONLY place the threshold lives.
// Owner-confirmed: delivery is free when the ITEMS total ₹2,000 or more after
// offers (line prices are already the offer prices). Delivery is never part of
// the compared figure, and the site never calculates a delivery fee.
//   kind: 'percent'       → rate off the subtotal once it reaches threshold
//   kind: 'free-delivery' → no discount line; delivery is waived instead
const OFFER = { enabled: true, kind: 'free-delivery', threshold: 2000, rate: 0 };

// ── LIVE AVAILABILITY ── (owner-approved labels: Available / Only 2 left / Only 1 left / Ask us /
// Check availability). `url` is empty until the backend exists; with no data every size honestly
// reads "Check availability". The server decides each label - the page never receives a count of
// 3 or more - and data older than 60 seconds is treated as unknown.
const AVAILABILITY = { url: '', refreshMs: 30000 };

// ── SUPPORT ── the guided Help flow. It only routes to WhatsApp; it never
// answers stock questions (a human confirms availability before money moves).
const SUPPORT = {
  heading: 'How can we help?',
  topics: [
    { key: 'size',     label: 'Is this available in my size?', tag: 'Size availability' },
    { key: 'delivery', label: 'Delivery charges',              tag: 'Delivery' },
    { key: 'exchange', label: 'Exchanges',                     tag: 'Exchange' },
    { key: 'order',    label: 'Where is my order?',            tag: 'Order status' },
    { key: 'other',    label: 'Something else',                tag: 'Other' }
  ],
  noteMax: 200,
  notePlaceholder: 'Short note (optional)',
  signature: 'Sent from only4you website'
};

// ── WORDING ── approved policy rules (owner brief, 14 Oct 2026). Pages fill
// [data-copy="key"] elements from this. {threshold} comes from OFFER.
// Never add a refund promise, a replacement guarantee, a delivery fee or an
// offer that is not real.
const COPY = {
  positioning: "Only 4 You is a comfort wear shop on Pakhowal Road, Ludhiana. Browse from home, message us on WhatsApp, and we'll help you pick the right size before you pay anything. You're always welcome to come into the shop.",
  deliveryArea: 'We deliver within Ludhiana only, for now.',
  deliveryFree: 'Delivery is free when your items total ₹{threshold} or more after offers.',
  deliveryCharge: 'Below that, we confirm the delivery charge (the Porter fare) on WhatsApp once we have your address.',
  payment: 'Pay by UPI after we confirm stock and your final bill. No cash on delivery.',
  pricing: 'The website price, including any current offer, is the final item price. There is no further discount on WhatsApp.',
  priceNote: 'Final price, including any current offer.',
  orderRequest: 'Sending is an order request, not a confirmed or paid order. We confirm stock and your final bill on WhatsApp before you pay.',
  whatsappNote: "Opening WhatsApp doesn't send the message. Tap send in WhatsApp to reach us.",
  firstAddTitle: 'Added to your bag!',
  exchangeTitle: 'Exchange within 3 days',
  exchange: [
    'Contact us within 3 days of delivery. The item must be unworn, unwashed and have its tags intact.',
    'Lowers, T-shirts, tops and nightwear sets can be exchanged. Innerwear, socks and accessories are not exchanged for a change of mind.',
    'An exchange at our Pakhowal Road shop is preferred. For an ordinary exchange, you pay the transport.',
    'Wrong, faulty or not-as-described items are handled separately, and we cover the transport for those.'
  ]
};

// ── Rendering helpers shared by both pages ─────────────────────────────
const o4uMoney = n => Number(n || 0).toLocaleString('en-IN');
const o4uEscape = str => String(str ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
const copyTpl = str => String(str).replace(/\{threshold\}/g, o4uMoney(OFFER.threshold));
const freeDeliveryOn = () => !!(OFFER && OFFER.enabled && OFFER.kind === 'free-delivery' && OFFER.threshold > 0);

// A key's text (string) or lines (array). 'delivery' = the free-delivery rule + the charge rule.
function copyFor(key) {
  if (key === 'delivery') return freeDeliveryOn() ? [copyTpl(COPY.deliveryFree), copyTpl(COPY.deliveryCharge)] : [copyTpl(COPY.deliveryCharge).replace(/^Below that, we/, 'We')];
  const v = COPY[key];
  return Array.isArray(v) ? v.map(copyTpl) : copyTpl(v == null ? '' : v);
}
// Fill [data-copy] (and [data-copy-line] for one line of a list). A <ul>/<ol> gets one <li> per line.
function applyCopy(root = document) {
  root.querySelectorAll('[data-copy]').forEach(el => {
    let v = copyFor(el.dataset.copy);
    if (el.dataset.copyLine !== undefined && Array.isArray(v)) v = v[Number(el.dataset.copyLine)] || '';
    if (Array.isArray(v)) el.innerHTML = /^(UL|OL)$/.test(el.tagName) ? v.map(x => `<li>${o4uEscape(x)}</li>`).join('') : o4uEscape(v.join(' '));
    else el.textContent = v;
  });
}
// Fill every [data-wa] link from WA.
function applyWhatsAppLinks(root = document) {
  root.querySelectorAll('[data-wa]').forEach(a => {
    const t = a.dataset.wa;
    a.href = `https://wa.me/${WA}` + (t ? `?text=${encodeURIComponent(t)}` : '');
    if (a.hasAttribute('data-wa-display')) a.textContent = WA_DISPLAY;
  });
}
