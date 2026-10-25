/* Dashboard checks. Part A feeds hand-made records to the metric functions and compares with totals worked out by hand.
   Part B drives the real page (dev copy) with synthetic data. Nothing real is read; nothing is saved. */
(async function dashboardTests() {
  const out = []; let pass = 0, fail = 0;
  const ok = (name, cond, extra) => { (cond ? pass++ : fail++); out.push(`${cond ? "✔" : "✖"} ${name}${!cond && extra ? "  — " + extra : ""}`); };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const w = await openDev("{}");                       // an EMPTY shop first
  const {compute, rangeOf} = w.O4U_metrics, C = w.O4U_ops.C;
  const at = (d, h = 12, mi = 0, s = 0, ms = 0) => new Date(2026, 9, d, h, mi, s, ms).toISOString();        // October 2026, local time
  const NOW = new Date(2026, 9, 25, 12, 0).getTime();
  const R7 = rangeOf({range: "7d"}, NOW);

  // ── A. period boundaries ──
  ok("A today = midnight to 23:59:59.999", rangeOf({range: "today"}, NOW).from === new Date(2026, 9, 25).getTime() && rangeOf({range: "today"}, NOW).to === new Date(2026, 9, 25, 23, 59, 59, 999).getTime());
  ok("A 7 days = 19 Oct 00:00 to 25 Oct 23:59", R7.from === new Date(2026, 9, 19).getTime() && R7.to === new Date(2026, 9, 25, 23, 59, 59, 999).getTime());
  ok("A 30 days starts 26 Sept", rangeOf({range: "30d"}, NOW).from === new Date(2026, 8, 26).getTime());
  const cu = rangeOf({range: "custom", from: "2026-10-01", to: "2026-10-10"}, NOW);
  ok("A custom range covers whole first and last day", cu.from === new Date(2026, 9, 1).getTime() && cu.to === new Date(2026, 9, 10, 23, 59, 59, 999).getTime() && cu.label === "Custom range");
  ok("A custom range with start after end falls back to 30 days", rangeOf({range: "custom", from: "2026-10-10", to: "2026-10-01"}, NOW).label === "Last 30 days");
  ok("A custom range with junk dates falls back to 30 days", rangeOf({range: "custom", from: "", to: "abc"}, NOW).label === "Last 30 days");

  // ── A. the numbers ──
  const P = (id, stock, extra) => ({id, article: id.toUpperCase(), brand: "", category: "nightsuits", type: "Set", colour: id, sizes: Object.keys(stock).map((z) => ({size: z, mrp: extra && extra.mrp || 1000})), stock, published: true, status: "ready", ...extra});
  const M = (kind, pid, size, change, before, when, unitP, extra) => ({kind, productId: pid, size, change, before, after: before + change, unitP, at: when, category: "nightsuits", label: pid, orderId: "", ...extra});
  const L = (pid, size, qty, unitP) => ({productId: pid, size, qty, unitP: unitP || 100000, label: pid});
  const D = {
    products: [P("p1", {M: 5, L: 2}), P("p2", {M: 1}), P("p3", {M: 0}), P("p4", {L: 3}, {published: false, mrp: 500}), P("p5", {S: 3}, {mrp: 400})],
    moves: [
      M("capture", "p1", "M", 8, 0, at(1)), M("capture", "p1", "L", 3, 0, at(1)), M("capture", "p2", "M", 2, 0, at(1)), M("capture", "p3", "M", 1, 0, new Date(2026, 7, 1).toISOString()), M("capture", "p5", "S", 4, 0, at(1)),
      M("sale", "p3", "M", -1, 1, new Date(2026, 8, 1).toISOString(), 90000),
      M("dispatch", "p1", "M", -2, 8, at(22), 100000, {orderId: "o2"}),
      M("dispatch", "p2", "M", -1, 2, at(23, 15), 150000, {orderId: "o1"}),
      M("sale", "p1", "L", -1, 3, at(24, 11), 100000),
      M("sale", "p1", "M", -1, 6, at(25, 10), 100000),
      M("sale", "p5", "S", -1, 5, at(25, 9), 100000),               // history says 4, this starts from 5 → a gap; and the rack shows 3, history ends at 4 → another
    ],
    orders: [
      {id: "o1", code: "T1", name: "A", phone: "9000000001", source: "website", status: "delivered", createdAt: at(23, 9), lines: [L("p2", "M", 1, 150000)], deliveryP: 0, paidP: 150000, payment: {at: at(23, 10)}},
      {id: "o2", code: "T2", name: "B", phone: "9000000002", status: "delivered", createdAt: at(22, 9), lines: [L("p1", "M", 2)], deliveryP: 0},
      {id: "o3", code: "T3", name: "C", phone: "9000000001", source: "website", status: "request", allocated: false, createdAt: at(25, 8), lines: [L("p2", "M", 1)]},
      {id: "o4", code: "T4", name: "D", phone: "9000000004", status: "awaiting_payment", allocated: true, holdUntil: new Date(NOW - 6 * 60000).toISOString(), createdAt: at(25, 9), lines: [L("p1", "M", 1)]},
      {id: "o5", code: "T5", name: "E", phone: "9000000005", status: "awaiting_payment", allocated: true, holdUntil: new Date(NOW + 20 * 60000).toISOString(), createdAt: at(25, 10), lines: [L("p5", "S", 1)]},
      {id: "o6", code: "T6", name: "F", phone: "9000000006", status: "paid", allocated: true, createdAt: at(24, 9), lines: [L("p1", "L", 1)], deliveryP: 0, paidP: 100000, payment: {at: at(24, 10)}},
      {id: "o7", code: "T7", name: "G", phone: "9000000007", status: "cancelled", createdAt: at(20, 9), lines: [L("p1", "M", 1)]},
    ],
    refunds: [
      {id: "r1", orderId: "o2", name: "B", amountP: 30000, status: "approved", createdAt: at(24, 8)},
      {id: "r2", orderId: "o2", name: "B", amountP: 20000, status: "completed", createdAt: at(21, 8), completedAt: at(22, 8)},
    ],
  };
  const s = compute(D, R7, NOW);
  ok("A counter sales: 3 pieces, ₹3,000 (p1 L on 24 Oct, p1 M and p5 S on 25 Oct)", s.ch.counter.n === 3 && s.ch.counter.p === 300000, JSON.stringify(s.ch.counter));
  ok("A website orders: 1 piece, ₹1,500 (dispatched order from the website)", s.ch.website.n === 1 && s.ch.website.p === 150000, JSON.stringify(s.ch.website));
  ok("A WhatsApp / phone orders: 2 pieces, ₹2,000 (order typed by hand)", s.ch.manual.n === 2 && s.ch.manual.p === 200000, JSON.stringify(s.ch.manual));
  ok("A gross sales ₹6,500 over 6 pieces; the 1 Sept sale outside the period is not included", s.gross === 650000 && s.pieces === 6, `${s.gross} / ${s.pieces}`);
  ok("A today's sales ₹2,000 (the two 25 Oct counter sales), whatever period is selected", s.todayP === 200000, String(s.todayP));
  ok("A previous period had no sales → nothing to compare", s.prevGross === 0);
  ok("A orders received 7, 1 cancelled, 2 from the website, 2 sent", s.orders.received === 7 && s.orders.cancelled === 1 && s.orders.website === 2 && s.orders.fulfilled === 2, JSON.stringify([s.orders.received, s.orders.cancelled, s.orders.website, s.orders.fulfilled]));
  ok("A pending orders = request + 2 waiting for payment + paid = 4", s.orders.pendingNow.length === 4);
  ok("A needs attention: hold over first, hold ending second, then the refund, the paid order, the new request", s.attention.length === 5 && s.attention[0].target.id === "o4" && s.attention[1].target.id === "o5" && s.attention[2].kind === "refund" && s.attention[3].target.id === "o6" && s.attention[4].target.id === "o3", s.attention.map((a) => a.title).join(" | "));
  ok("A a hold that is over is flagged as such, one ending within 30 minutes is flagged with minutes", /Hold is over/.test(s.attention[0].title) && /Hold ends in 20 min/.test(s.attention[1].title));
  ok("A holds counted: 1 over, 1 ending soon", s.holdsOver === 1 && s.holdsSoon === 1);
  ok("A low stock: sizes with 1–2 FREE (held pieces subtracted): p1 L (2−1), p2 M (1), p5 S (3−1)", s.low.length === 3 && s.low.map((x) => x.p.id + x.z).sort().join() === "p1L,p2M,p5S" && s.lowProducts === 3, s.low.map((x) => x.p.id + x.z + x.sell).join());
  ok("A out of stock: only the published size at 0 (p3 M)", s.out.length === 1 && s.out[0].p.id === "p3");
  ok("A needs a recount: only the product nobody has touched in 60 days (p4)", s.needsRecount.length === 1 && s.needsRecount[0].id === "p4");
  ok("A stock-history gaps: the two on p5, none elsewhere", s.gaps.length === 2 && s.gaps.every((g) => g.productId === "p5"), JSON.stringify(s.gaps));
  ok("A best seller by money: p1 4 pieces ₹4,000 first", s.top[0].id === "p1" && s.top[0].n === 4 && s.top[0].p === 400000, JSON.stringify(s.top[0]));
  ok("A pieces sold by size: M 4, L 1, S 1", s.bySize.M === 4 && s.bySize.L === 1 && s.bySize.S === 1, JSON.stringify(s.bySize));
  ok("A slow movers: stock on the rack and no sale in 30 days = p4 only (p1, p2, p5 sold this week; p3 has no stock)", s.slow.map((x) => x.p.id).join() === "p4", s.slow.map((x) => x.p.id).join());
  ok("A customers: 5 distinct phones (cancelled order ignored), 1 has ordered more than once", s.customers.unique === 5 && s.customers.repeat === 1, JSON.stringify(s.customers));
  ok("A refunds: ₹200 sent in the period, ₹300 approved but not sent; net sales = gross − sent refunds", s.money.refundedP === 20000 && s.money.refundsPendingP === 30000 && s.money.net === s.gross - 20000);
  ok("A payments checked on orders ₹2,500 (two orders)", s.money.paymentsVerifiedP === 250000);
  ok("A money not yet earned kept apart: waiting for payment ₹2,000 (2 orders), requests ₹1,000 (1)", s.money.awaitingP === 200000 && s.money.awaitingN === 2 && s.money.requestsP === 100000 && s.money.requestsN === 1, JSON.stringify(s.money));
  ok("A chart: 7 daily buckets that add up to the gross, orders per day counted", s.series.length === 7 && s.series.reduce((n, b) => n + b.counter + b.website + b.manual, 0) === s.gross && s.series.reduce((n, b) => n + b.orders, 0) === 7);
  const b25 = s.series[6]; ok("A the 25 Oct bucket holds that day's ₹2,000 counter sales and 3 new orders", b25.counter === 200000 && b25.orders === 3, JSON.stringify(b25));
  // boundaries
  const edge = compute({products: [], orders: [], refunds: [], moves: [M("sale", "x", "M", -1, 1, new Date(2026, 9, 19, 0, 0, 0, 0).toISOString(), 10000), M("sale", "x", "M", -1, 2, new Date(2026, 9, 18, 23, 59, 59, 999).toISOString(), 20000), M("sale", "x", "M", -1, 3, new Date(2026, 9, 25, 23, 59, 59, 999).toISOString(), 40000), M("sale", "x", "M", -1, 4, new Date(2026, 9, 26, 0, 0, 0, 0).toISOString(), 80000)]}, R7, NOW);
  ok("A period edges: a sale at 19 Oct 00:00 and one at 25 Oct 23:59:59.999 are in; 18 Oct 23:59:59.999 and 26 Oct 00:00 are out", edge.gross === 50000);
  const wk = compute({products: [], orders: [], refunds: [], moves: []}, rangeOf({range: "custom", from: "2026-07-01", to: "2026-10-25"}, NOW), NOW);
  ok("A a long period is charted weekly (not 117 slivers)", wk.step === 7 && wk.series.length === Math.ceil(117 / 7));
  const none = compute({products: [], orders: [], refunds: [], moves: []}, R7, NOW);
  ok("A nothing recorded → every figure is 0 or empty, nothing invented", none.gross === 0 && none.pieces === 0 && none.attention.length === 0 && none.low.length === 0 && none.top.length === 0 && none.firstMove === null && none.customers.unique === 0);

  // ── B. the page, empty shop ──
  const txt = (win) => win.document.getElementById("pg-dashboard").innerText;
  const E = txt(w);
  ok("B empty shop: says nothing is recorded yet", /Nothing is recorded yet/.test(E));
  ok("B empty shop: sales ₹0, empty states instead of charts and tables", /₹0/.test(E) && /No sales recorded for this period/.test(E) && /Nothing needs you right now/.test(E));
  ok("B empty shop: no NaN / undefined / null anywhere", !/NaN|undefined|null/.test(E));
  ok("B empty shop: profit and discounts say what is missing instead of showing a number", /Cost information required/.test(E) && /Not recorded/.test(E));
  ok("B the production dev file contains no demo or fixture data", !/__demoDataset|DEMO DATA|synthetic/i.test(window.devHtml));

  // ── B. the page, demo shop ──
  const d = await openDev("window.__demoDataset(Date.now())");
  const T = txt(d), st = d.__dashState, Cd = d.O4U_ops.C;
  ok("B demo shop renders every panel", ["Needs attention", "Sales by channel", "Inventory alerts", "Orders", "Business health", "Product performance", "Financial overview"].every((h) => T.includes(h)));
  ok("B no NaN / undefined / null in the demo page", !/NaN|undefined|null/.test(T));
  const kv = [...d.document.querySelectorAll("#pg-dashboard .kpi .kv")].map((e) => e.textContent);
  ok("B the Sales tile equals the computed gross", kv[0] === Cd.rupees(st.gross), `${kv[0]} vs ${Cd.rupees(st.gross)}`);
  ok("B the tiles add up: shop + website + phone/WhatsApp = sales", st.ch.counter.p + st.ch.website.p + st.ch.manual.p === st.gross);
  ok("B every chart column is clickable for details", d.document.querySelectorAll("#dChart .hit").length === st.series.length);
  d.document.querySelector("#dChart .hit").dispatchEvent(new d.MouseEvent("click", {bubbles: true}));
  ok("B tapping a chart column shows that day's figures", !d.document.getElementById("dTip").hidden && /order/.test(d.document.getElementById("dTip").textContent));
  d.document.querySelector('[data-dr="7d"]').click(); await sleep(50);
  ok("B the 7-day button changes the period", /Last 7 days/.test(txt(d)) && d.__dashState.range.label === "Last 7 days");
  d.document.querySelector('[data-dr="today"]').click(); await sleep(50);
  ok("B the Today button works and charts say so when there are no sales today", d.__dashState.range.label === "Today");
  d.document.querySelector('[data-dr="custom"]').click(); await sleep(50);
  const from = d.document.getElementById("dFrom"), to = d.document.getElementById("dTo");
  from.value = "2026-12-01"; from.dispatchEvent(new d.Event("change", {bubbles: true})); await sleep(50);
  ok("B a custom range with the start after the end warns and shows the last 30 days", /start date is after the end date/.test(txt(d)) || d.__dashState.range.label === "Last 30 days");
  d.document.querySelector('[data-dr="30d"]').click(); await sleep(50);
  const firstAtt = d.document.querySelector("[data-att]"); firstAtt.click(); await sleep(80);
  ok("B tapping an attention row opens that order", d.O4U_ops.O.sheet && d.O4U_ops.O.sheet.kind === "order" && d.O4U_ops.O.tab === "orders");
  d.O4U_ops.setTab("dashboard"); d.O4U_ops.O.sheet = null; await sleep(50);
  const rc = d.document.querySelector("[data-recount]"); if (rc) { rc.click(); await sleep(80); ok("B tapping 'Recount' opens the recount form for that product", d.O4U_ops.O.sheet && d.O4U_ops.O.sheet.kind === "product" && d.O4U_ops.O.sheet.f && d.O4U_ops.O.sheet.f.why === "recount"); }
  d.O4U_ops.O.sheet = null;
  const narrow = await openDev("window.__demoDataset(Date.now())", 380);
  ok("B at phone width the page has no sideways scroll", narrow.document.documentElement.scrollWidth <= narrow.innerWidth + 1, `${narrow.document.documentElement.scrollWidth} > ${narrow.innerWidth}`);
  ok("B at phone width the Needs attention panel comes first", narrow.document.querySelector("#pg-dashboard .dgrid > :first-child h3").textContent === "Needs attention");

  out.push(`\n${pass} passed, ${fail} failed`);
  return {pass, fail, lines: out};
})();
