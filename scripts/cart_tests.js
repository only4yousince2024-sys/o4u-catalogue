/*
  O4U cart self-checks — run in the browser on the live or local site:
    1. open the site, press F12 → Console
    2. paste this whole file and press Enter
  Prints one line per check and a PASS/FAIL total. Nothing is sent to WhatsApp
  (window.open is stubbed during the run) and the cart is restored afterwards.
*/
(async function cartTests() {
  const out = []; let pass = 0, fail = 0;
  const ok = (name, cond, extra) => { (cond ? pass++ : fail++); out.push(`${cond ? '✔' : '✖'} ${name}${extra ? '  — ' + extra : ''}`); };
  const P = allProducts;
  const A = P[0], B = P[1] || P[0];
  const savedCart = JSON.parse(JSON.stringify(cart)); const savedStorage = localStorage.getItem('o4u_cart_v1');
  const origOpen = window.open; let opened = null; window.open = u => { opened = u; return { focus() {} }; };
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
  } finally {
    window.open = origOpen;
    cart = savedCart; if (savedStorage === null) localStorage.removeItem('o4u_cart_v1'); else localStorage.setItem('o4u_cart_v1', savedStorage);
    cart = loadCart(); renderCart();
  }
  out.push(`\n${pass} passed, ${fail} failed`);
  console.log(out.join('\n'));
  return { pass, fail, lines: out };
})();
