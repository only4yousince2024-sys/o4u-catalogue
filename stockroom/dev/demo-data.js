/* SYNTHETIC demo records for previewing the dashboard. Generated from a fixed seed, relative to "now".
   Every name, phone, amount and date here is invented. This file is used only by dev/preview.html,
   which shows a DEMO banner. It is never included in stockroom-dev.html or published. */
window.__demoDataset = function (now) {
  let seed = 20261025; const rnd = () => (seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296;
  const pick = (a) => a[Math.floor(rnd() * a.length)];
  const DAY = 86400000, iso = (t) => new Date(t).toISOString();
  const cats = ["nightsuits", "tshirts", "lowers", "tops", "capris"];
  const types = {nightsuits: "Satin Nightsuit", tshirts: "Cotton T-shirt", lowers: "Track Lower", tops: "Crop Top", capris: "Cotton Capri"};
  const colours = ["Sage Green", "Maroon Floral", "Navy Stripe", "Lavender", "Black Pink Geometric", "Peach Abstract", "Ivory", "Teal"];
  const products = {}, moves = {}, orders = {}, refunds = {};
  const sizesAll = ["S", "M", "L", "XL", "XXL"];
  let mi = 0;
  const move = (p, z, kind, change, at, extra = {}) => {
    const before = p.stock[z] || 0, after = before + change; p.stock[z] = after;
    moves["m-demo-" + (++mi)] = {productId: p.id, label: p.colour + " " + p.type, article: p.article, category: p.category, size: z, change, before, after, kind, by: pick(["Dad", "Khush", "Staff"]), at: iso(at), orderId: "", caseId: "", note: "", ...extra};
  };
  for (let i = 0; i < 14; i++) {
    const cat = cats[i % cats.length], colour = colours[i % colours.length], article = String(4000 + i * 7) + (i % 3 ? "" : "B");
    const id = (article + " " + colour).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    const sizes = sizesAll.slice(i % 2, 3 + (i % 3)), mrp = pick([1099, 1289, 1589, 749, 899]);
    const p = products[id] = {id, article, brand: i % 4 ? "Sweet Pini" : "", category: cat, type: types[cat], colour, sizes: sizes.map((z) => ({size: z, mrp})), stock: {}, inStock: true, published: i % 5 !== 4, status: "ready", flags: [], notes: "", webImages: [], createdAt: iso(now - 90 * DAY), updatedAt: iso(now - (i % 6) * DAY)};
    sizes.forEach((z) => move(p, z, "capture", 4 + Math.floor(rnd() * 5), now - (88 - i) * DAY));
  }
  const plist = Object.values(products);
  const place = (n, o) => (orders["o-demo-" + n] = o);
  // 58 days of counter sales and some web/hand-typed orders that were sent
  let on = 0;
  for (let d = 58; d >= 0; d--) {
    const t = now - d * DAY - Math.floor(rnd() * 8) * 3600000;
    const sales = Math.floor(rnd() * 3 + (d % 7 === 5 ? 2 : 0));
    for (let s = 0; s < sales; s++) {
      const p = pick(plist), z = pick(p.sizes).size;
      if ((p.stock[z] || 0) > 0) move(p, z, "sale", -1, t + s * 600000, {unitP: Math.round(p.sizes[0].mrp * 100)});
    }
    if (rnd() < 0.3) {
      on++; const p = pick(plist), z = pick(p.sizes).size, web = rnd() < 0.65, unit = Math.round(p.sizes[0].mrp * 100);
      if ((p.stock[z] || 0) < 1) continue;
      const id = "o-demo-" + on;
      move(p, z, "dispatch", -1, t + 7200000, {unitP: unit, orderId: id});
      orders[id] = {code: "DEMO-" + on, name: pick(["Aarti S.", "Simran K.", "Neha G.", "Pooja M."]), phone: "9000000" + String(100 + on).slice(-3), address: "Demo address", status: "delivered", allocated: false, source: web ? "website" : undefined, createdAt: iso(t), updatedAt: iso(t + DAY),
        lines: [{productId: p.id, size: z, qty: 1, unitP: unit, label: p.colour + " " + p.type, article: p.article}], deliveryP: 0, paidP: unit, payment: {ref: "DEMO" + on, at: iso(t + 3600000), by: "Dad"}, history: []};
    }
  }
  // a few live orders in different states
  const live = (n, status, extra) => { const p = plist[n], z = p.sizes[0].size, unit = Math.round(p.sizes[0].mrp * 100);
    place("live" + n, {code: "LIVE-" + n, name: ["Ritu P.", "Kiran B.", "Anjali D.", "Meera T."][n % 4], phone: "9111111" + (100 + n), address: "Demo address", status, allocated: ["awaiting_payment", "paid", "packed"].includes(status), source: n % 2 ? "website" : undefined,
      createdAt: iso(now - (n + 1) * 3600000), updatedAt: iso(now - n * 600000), lines: [{productId: p.id, size: z, qty: 1, unitP: unit, label: p.colour + " " + p.type, article: p.article}], deliveryP: 6900, history: [], ...extra}); };
  live(0, "request"); live(1, "confirmed"); live(2, "awaiting_payment", {holdUntil: iso(now + 18 * 60000)}); live(3, "awaiting_payment", {holdUntil: iso(now - 6 * 60000)});
  live(4, "paid", {paidP: 150000, payment: {ref: "DEMOPAID", at: iso(now - 2 * 3600000), by: "Dad"}}); live(5, "packed", {paidP: 150000, payment: {ref: "DEMOPAK", at: iso(now - 5 * 3600000), by: "Dad"}});
  refunds["r-demo-1"] = {orderId: "o-demo-3", code: "DEMO-3", name: "Aarti S.", phone: "9000000103", amountP: 108900, reason: "Eligible exchange, no suitable replacement", status: "approved", createdAt: iso(now - 3 * 3600000)};
  refunds["r-demo-2"] = {orderId: "o-demo-5", code: "DEMO-5", name: "Neha G.", phone: "9000000105", amountP: 74900, reason: "Cheaper replacement: difference", status: "completed", createdAt: iso(now - 9 * DAY), completedAt: iso(now - 8 * DAY), ref: "DEMOREF"};
  // make a couple of products look low / sold out, and leave one without any recent count
  const lowp = plist[1], z1 = lowp.sizes[0].size; if (lowp.stock[z1] > 2) move(lowp, z1, "sale", -(lowp.stock[z1] - 2), now - 120000, {unitP: 128900});
  const outp = plist[2], z2 = outp.sizes[0].size; if (outp.stock[z2] > 0) move(outp, z2, "sale", -outp.stock[z2], now - 60000, {unitP: 158900});
  return {products, stockmoves: moves, orders, cases: {}, refunds, drafts: {}, readcopies: {}, config: {export: {at: iso(now - 4 * DAY), products: 10}, ops: {upiId: "demo@upi", shopName: "Only 4 You"}}};
};
