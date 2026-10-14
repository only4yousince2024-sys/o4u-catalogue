/*
  O4U cart + order self-checks. Two ways to run:
    • headless (no browser window):   python scripts/run_cart_tests.py
    • by hand: open the site, F12 → Console, paste this whole file, Enter
  Prints one line per check and a PASS/FAIL total. Nothing is ever sent to
  WhatsApp: window.open is stubbed, and the order checks BUILD the wa.me URL
  and decode it - they never navigate to it. Cart, OFFER and COPY are
  restored afterwards.
*/
(async function cartTests() {
  const out = []; let pass = 0, fail = 0;
  const ok = (name, cond, extra) => { (cond ? pass++ : fail++); out.push(`${cond ? '✔' : '✖'} ${name}${extra ? '  — ' + extra : ''}`); };
  const P = allProducts;
  const A = P[0], B = P[1] || P[0];
  const savedCart = JSON.parse(JSON.stringify(cart)); const savedStorage = localStorage.getItem('o4u_cart_v1');
  const origOpen = window.open; let opened = null; window.open = u => { opened = u; return { focus() {} }; };
  const saveOfferAll = { ...OFFER };
  try {
    // 3a merge identical product+colour+size
    clearCart(); addToCart(A, A.colors[0] || '', A.sizes[0] || '', 1); addToCart(A, A.colors[0] || '', A.sizes[0] || '', 1);
    ok('3a same product+colour+size merges into one line, qty 2', cart.length === 1 && cart[0].quantity === 2, `lines=${cart.length} qty=${cart[0] && cart[0].quantity}`);
    // 3b different size / colour → separate lines
    const size2 = A.sizes[1] || (A.sizes[0] + 'x');
    addToCart(A, A.colors[0] || '', size2, 1);
    addToCart(A, 'Other Colour', A.sizes[0] || '', 1);
    ok('3b different size and different colour stay separate lines', cart.length === 3, `lines=${cart.length}`);
    // 3c clamps: 0, negative, decimal, empty, non-numeric, huge
    clearCart();
    addToCart(A, 'c', 's', 0);   addToCart(A, 'c2', 's', -3); addToCart(A, 'c3', 's', 2.7);
    addToCart(A, 'c4', 's', ''); addToCart(A, 'c5', 's', 'abc'); addToCart(A, 'c6', 's', 1e9);
    const q = cart.map(l => l.quantity);
    ok('3c quantities clamp to whole numbers 1..99', q.every(n => Number.isInteger(n) && n >= 1 && n <= 99), `got ${JSON.stringify(q)}`);
    const t = orderTotals();
    ok('3c totals never NaN / ≤0 for priced items', Number.isFinite(t.total) && t.total > 0 && !/NaN/.test(document.getElementById('cartTotal').textContent), `total=${t.total}`);
    updateLineQty(cart[0].key, -99);
    ok('3c stepping below 1 removes the line (never 0 or negative)', !cart.find(l => l.colour === 'c'), `lines=${cart.length}`);
    updateLineQty(cart[0].key, 500);
    ok('3c stepping up clamps at 99', cart[0].quantity === 99, `qty=${cart[0].quantity}`);
    // 3d empty cart: no send, no offer UI, button disabled
    clearCart(); renderCart(); opened = null; sendWhatsApp(true);
    ok('3d empty cart: send does nothing', opened === null);
    ok('3d empty cart: send button disabled and footer hidden', document.getElementById('cartSendBtn').disabled && document.getElementById('cartFoot').style.display === 'none');
    ok('3d empty cart: no offer/progress UI', document.getElementById('cartOffer').hidden);
    // 3e recalculation on remove / qty change
    addToCart(A, 'x', 's', 1); addToCart(B, 'y', 's', 2);
    const before = orderTotals().subtotal;
    updateLineQty(cart[1].key, -1);
    ok('3e qty change recalculates subtotal', orderTotals().subtotal === before - B.price, `${before} → ${orderTotals().subtotal}`);
    removeLine(cart[0].key);
    ok('3e remove recalculates subtotal', orderTotals().subtotal === B.price && document.getElementById('cartTotal').textContent === '₹' + fmt(B.price));
    // 3f persistence: survives reload of the storage layer; junk is rejected; missing storage degrades
    clearCart(); addToCart(A, 'p', 's', 3);
    const reloaded = loadCart();
    ok('3f cart survives a reload (localStorage round-trip)', reloaded.length === 1 && reloaded[0].quantity === 3);
    localStorage.setItem('o4u_cart_v1', JSON.stringify({ lines: [{ productId: 'z', quantity: 2.9, price: 10 }, { productId: '', quantity: 1, price: 5 }, { productId: 'w', quantity: 'x', price: 5 }], updatedAt: Date.now() }));
    const junk = loadCart();
    ok('3f junk in storage is sanitised (2.9→2) and invalid lines dropped', junk.length === 1 && junk[0].quantity === 2, JSON.stringify(junk.map(l => [l.productId, l.quantity])));
    localStorage.setItem('o4u_cart_v1', JSON.stringify({ lines: [{ productId: 'z', quantity: 1, price: 10 }], updatedAt: Date.now() - 8 * 86400000 }));
    ok('3f cart older than 7 days is discarded', loadCart().length === 0);
    localStorage.setItem('o4u_cart_v1', JSON.stringify({ lines: [{ productId: 'z', quantity: 1, price: 10 }], updatedAt: Date.now(), sentAt: Date.now() - 31 * 60000 }));
    ok('3f cart sent >30 min ago is discarded on load', loadCart().length === 0);
    localStorage.setItem('o4u_cart_v1', '{not json');
    ok('3f corrupt storage → empty cart, no throw', loadCart().length === 0);
    const realLS = Object.getOwnPropertyDescriptor(window, 'localStorage');
    Object.defineProperty(window, 'localStorage', { get() { throw new Error('blocked'); }, configurable: true });
    let threw = false; try { cart = []; addToCart(A, 'm', 's', 1); saveCart(); loadCart(); } catch (e) { threw = true; }
    Object.defineProperty(window, 'localStorage', realLS);
    ok('3f no storage at all → in-memory cart, nothing throws', !threw && cart.length === 1);
    // 3g discount: config-driven, once, rupee-rounded, message matches cart
    clearCart(); const saveOffer = { ...OFFER }; Object.assign(OFFER, { enabled: true, kind: 'percent', threshold: 1000, rate: 0.2 });
    addToCart(A, 'd', 's', 2);
    const tt = orderTotals();
    const msg = buildOrderMessage(cart, 'O4U-TEST-001', new Date());
    ok('3g discount = round(subtotal × rate) applied once', tt.discount === Math.round(tt.subtotal * 0.2) && tt.total === tt.subtotal - tt.discount, `subtotal ${tt.subtotal} discount ${tt.discount}`);
    ok('3g discount line in the message equals the cart', msg.includes(`Discount (20%): −₹${fmt(tt.discount)}`) && msg.includes(`Items total: ₹${fmt(tt.total)}`) && document.getElementById('cartDiscount').textContent === '−₹' + fmt(tt.discount));
    Object.assign(OFFER, saveOffer);

    // ── 4. THRESHOLD, DISCOUNT ORDER, VARIANTS, MESSAGE INTEGRITY, ENCODING ──
    // Synthetic products with known prices. `price` is the price after any offer
    // (what the customer sees); `mrp` is the tag price and must never drive anything.
    Object.assign(OFFER, { enabled: true, kind: 'free-delivery', threshold: 2000, rate: 0 });
    const mk = (id, price, mrp) => ({ id, article: id.toUpperCase(), name: 'Test Set ' + id, price, mrp, sizePrices: {}, sizes: ['M', 'L'], colors: ['Beige'], images: [], stockQty: 1, published: true });
    const decode = url => { const m = String(url).match(/^https:\/\/wa\.me\/\d+\?text=(.*)$/); return m ? { enc: m[1], text: decodeURIComponent(m[1]) } : null; };
    const IMPLIES_DONE = /\b(paid|payment (?:received|done|made)|order (?:is )?confirmed|confirmed order|guarantee)/i;
    const boundaries = [{ total: 1999, free: false }, { total: 2000, free: true }, { total: 2001, free: true }];
    window.__thresholdResults = [];
    boundaries.forEach(({ total, free }) => {
      clearCart();
      const a = mk('tq-a', 600, 899);                   // offer ₹600 (MRP ₹899) × 2 = ₹1,200
      const b = mk('tq-b', total - 1200, total - 1000);  // makes up the rest; accented colour below
      addToCart(a, 'Beige', 'M', 2); addToCart(b, 'Café Beige', 'L', 1);
      renderCart();
      const t = orderTotals();
      const shown = document.getElementById('cartTotal').textContent;
      const offerTxt = document.getElementById('cartOffer').textContent.replace(/\s+/g, ' ').trim();
      const u = decode(orderUrl(cart, 'O4U-TEST-' + total, new Date()));
      const msg = u ? u.text : '';
      const deliveryLine = (msg.match(/^Delivery: .*$/m) || [''])[0];
      window.__thresholdResults.push({ productTotal: t.subtotal, discount: t.discount, itemsTotal: t.total, freeDelivery: t.freeDelivery, bagShows: shown, bagOfferLine: offerTxt, messageDeliveryLine: deliveryLine });
      ok(`4a ₹${fmt(total)} → ${free ? 'FREE delivery' : 'delivery quoted, NOT free'}`, t.subtotal === total && t.freeDelivery === free && t.reached === free, `product total ${t.subtotal}, free=${t.freeDelivery}`);
      ok(`4b ₹${fmt(total)}: bag shows the same figure the threshold used; no NaN, no negatives`, shown === '₹' + fmt(t.total) && t.total === t.subtotal - t.discount && Number.isFinite(t.total) && t.total >= 0 && !/NaN/.test(document.getElementById('cartFoot').textContent), `bag ${shown}`);
      ok(`4b ₹${fmt(total)}: bag offer line agrees (progress never reads 100% below the threshold)`,
         free ? /free delivery unlocked/i.test(offerTxt) : offerTxt.includes(`Add ₹${fmt(OFFER.threshold - total)} more`) && !/100%/.test(offerTxt), offerTxt.slice(0, 70));
      ok(`4d ₹${fmt(total)}: wa.me URL builds and decodes`, !!u);
      ok(`4d ₹${fmt(total)}: every line has name, article, colour, size, qty and the final price`,
         cart.every(l => msg.includes(l.name) && msg.includes(`Article: ${l.article} · ${l.colour}`) && msg.includes(`Size: ${l.size}`) && msg.includes(`Qty: ${l.quantity}`) && msg.includes(`₹${fmt(l.price * l.quantity)}`)));
      ok(`4d ₹${fmt(total)}: MRP never quoted`, !msg.includes('₹899') && !msg.includes('₹' + fmt(899 * 2)) && !msg.includes('₹' + fmt(b.mrp)));
      ok(`4d ₹${fmt(total)}: items total matches the bag`, msg.includes(`Items total: ₹${fmt(t.total)}`));
      ok(`4d ₹${fmt(total)}: delivery line is ${free ? 'free' : 'to be confirmed'}`,
         free ? deliveryLine === 'Delivery: free (order of ₹2,000 or more)' : deliveryLine === 'Delivery: to be confirmed', deliveryLine);
      ok(`4d ₹${fmt(total)}: order reference present`, msg.includes('Ref: O4U-TEST-' + total));
      ok(`4d ₹${fmt(total)}: an order REQUEST - nothing implies payment or confirmation`, msg.startsWith('ORDER REQUEST') && !IMPLIES_DONE.test(msg) && !/subject to confirmation/i.test(msg));
      ok(`4e ₹${fmt(total)}: ₹, newlines and accents survive the round-trip, no double-encoding`,
         !!u && msg.includes('₹') && msg.includes('\n') && msg.includes('Café Beige') && u.enc.includes('%E2%82%B9') && u.enc.includes('%0A') &&
         u.enc.includes('Caf%C3%A9') && !/%25[0-9A-F]{2}/i.test(u.enc) && encodeURIComponent(msg) === u.enc);
    });
    // discounts apply BEFORE the threshold test: MRP ₹2,100 would cross it, the offer price ₹1,999 must not
    clearCart(); addToCart(mk('tq-c', 1999, 2100), 'Beige', 'M', 1);
    ok('4b threshold compares the price AFTER discount, not the MRP', orderTotals().subtotal === 1999 && !orderTotals().freeDelivery);
    // the site never calculates a delivery fee: ₹1,950 stays ₹1,950, delivery is only "to be confirmed"
    clearCart(); addToCart(mk('tq-d', 1950, null), 'Beige', 'M', 1); renderCart();
    const tf = orderTotals(), mf = decode(orderUrl(cart, 'O4U-TEST-FEE', new Date())).text;
    ok('4a no delivery fee is ever calculated or added (₹1,950 stays ₹1,950, delivery to be confirmed)',
       !tf.freeDelivery && tf.total === 1950 && mf.includes('Items total: ₹1,950') && mf.includes('Delivery: to be confirmed') && !/Delivery: ₹/.test(mf));
    // variants and quantities
    clearCart(); const v = mk('tq-v', 700, null);
    addToCart(v, 'Beige', 'M', 1); addToCart(v, 'Beige', 'M', 1);
    ok('4c same product + size + colour merges to qty 2', cart.length === 1 && cart[0].quantity === 2);
    addToCart(v, 'Beige', 'L', 1); addToCart(v, 'Café Beige', 'M', 1);
    ok('4c a different size or colour stays a separate line', cart.length === 3);
    const bad = [0, -2, 1.5, 'x', '', NaN, null, undefined, Infinity, -Infinity, 1e6];
    clearCart(); bad.forEach((q, i) => addToCart(mk('tq-q' + i, 100, null), 'Beige', 'M', q));
    const qs = cart.map(l => l.quantity);
    ok('4c 0, negatives, decimals, non-numeric and huge inputs never become a quantity (always whole 1..99)', qs.length === bad.length && qs.every(n => Number.isInteger(n) && n >= 1 && n <= 99), JSON.stringify(qs));
    clearCart(); addToCart(v, 'Beige', 'M', 1); addToCart(mk('tq-w', 450, null), 'Beige', 'L', 1);
    const k0 = cart[0].key; updateLineQty(k0, 'abc'); updateLineQty(k0, 1.9);
    ok('4c non-numeric / decimal steps never corrupt a quantity', cart[0].quantity === 2, `qty=${cart[0].quantity}`);
    removeLine(cart[1].key);
    ok('4c remove and quantity change recalculate the bag', orderTotals().total === 1400 && document.getElementById('cartTotal').textContent === '₹1,400');
  } finally {
    window.open = origOpen;
    Object.assign(OFFER, saveOfferAll);
    cart = savedCart; if (savedStorage === null) localStorage.removeItem('o4u_cart_v1'); else localStorage.setItem('o4u_cart_v1', savedStorage);
    cart = loadCart(); renderCart();
  }
  out.push(`\n${pass} passed, ${fail} failed`);
  console.log(out.join('\n'));
  return { pass, fail, lines: out, thresholds: window.__thresholdResults || [] };
})();
