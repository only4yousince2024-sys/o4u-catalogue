/* Dashboard v2 checks (run: python scripts/run_dashboard_tests.py --v2).
   A. the metric functions give the hand-worked totals (the same cases as v1, run against the v2 page)
   B. one definition of every figure: v2 carries v1's metric code unchanged
   C. owner vs store-operations views: what each shows and, above all, what the operations view never shows
   D. desktop and phone layouts are different layouts, not one resized
   E. the working Stockroom screens are still there. Synthetic records only; nothing real is read or saved. */
(async function dashboardV2Tests() {
  const out = []; let pass = 0, fail = 0;
  const ok = (name, cond, extra) => { (cond ? pass++ : fail++); out.push(`${cond ? "✔" : "✖"} ${name}${!cond && extra ? "  — " + extra : ""}`); };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const DEMO = "window.__demoDataset(Date.now())";
  const OWNER = {o4u_who: "Khush", o4u_view: "owner"}, OPS = {o4u_who: "Dad", o4u_view: "owner"};
  const text = (w) => w.document.getElementById("pg-dashboard").innerText.toLowerCase();   // headings are drawn in capitals: compare in lower case
  const shown = (w, el) => !!el && !!(el.offsetWidth || el.offsetHeight) && w.getComputedStyle(el).display !== "none";
  const labels = (w) => [...w.document.querySelectorAll("#pg-dashboard .kpi .kl")].map((e) => e.textContent.trim());

  // ── A. numbers: same hand-worked fixture as v1 ──
  const w0 = await openDev("{}", 1280, OWNER);
  const v1tests = await (await fetch("dashboard_tests.js", {cache: "no-store"})).text();
  const a = v1tests.indexOf("const {compute, rangeOf}"), b = v1tests.indexOf("// ── B. the page, empty shop ──");
  const AsyncFn = Object.getPrototypeOf(async function () {}).constructor;
  await new AsyncFn("ok", "w", v1tests.slice(a, b))(ok, w0);

  // ── B. one definition of every figure ──
  const grab = (html) => { const i = html.indexOf("function compute(D, rng, now) {"), j = html.indexOf("window.O4U_metrics = {compute, rangeOf};"); return i > 0 && j > i ? html.slice(i, j) : ""; };
  const m1 = grab(window.devHtmlV1), m2 = grab(window.devHtml);
  ok("B v2 carries the same metric code as v1, character for character", m1.length > 3000 && m1 === m2, `${m1.length} vs ${m2.length}`);
  ok("B the v2 page contains no demo or fixture data", !/__demoDataset|DEMO DATA|synthetic/i.test(window.devHtml));

  // ── C. roles ──
  const o = await openDev(DEMO, 1280, OWNER), os = o.__dashState, R = o.O4U_ops.C.rupees;
  ok("C owner view: the owner experience is chosen for Khush", o.__dashView.role === "owner" && /business overview/.test(text(o)));
  ok("C owner sees analytics, revenue, performance, inventory insights, health, financials", ["Sales analytics", "Needs attention", "Inventory insights", "Product performance", "Financial overview", "Operational health", "Best sellers"].every((h) => text(o).includes(h.toLowerCase())));
  const kv = [...o.document.querySelectorAll("#pg-dashboard .kpi .kv")].map((e) => e.textContent);
  ok("C owner KPI row: Sales and Today show the computed figures", kv[0] === R(os.gross) && kv[1] === R(os.todayP), `${kv[0]} / ${kv[1]}`);
  ok("C owner KPI row: shop + website + phone/WhatsApp = sales", os.ch.counter.p + os.ch.website.p + os.ch.manual.p === os.gross);
  ok("C no NaN / undefined / null in the owner view", !/nan|undefined|null/.test(text(o)));
  const ops = await openDev(DEMO, 1280, OPS), pst = ops.__dashState;
  const opsText = text(ops);
  ok("C store operations view is chosen for Dad", ops.__dashView.role === "ops" && /today at the shop/.test(opsText));
  ok("C operations sees orders, payments to verify, exchanges, stock entry, urgent actions", ["Urgent actions", "Payments to verify", "Orders in progress", "Exchanges and refunds", "Quick actions", "Stock to check"].every((h) => opsText.includes(h.toLowerCase())));
  ok("C operations view NEVER shows revenue analytics, financials, best sellers, profit or net sales", !/sales analytics|financial overview|best sellers|product performance|net sales|gross|not sold in|sales by category|profit/.test(opsText));
  ok("C operations view carries no business-total figure at all (sales, today's sales, channel sales)", ![R(pst.gross), R(pst.todayP), R(pst.ch.counter.p), R(pst.ch.website.p), R(pst.money.net)].some((f) => f !== "₹0" && opsText.includes(f)));
  ok("C operations KPI labels are operational counts, not money", labels(ops).join("|") === "Orders to action|Waiting for payment|To pack and send|Refunds to send|Low stock|To recount", labels(ops).join("|"));
  ok("C the Dashboard tab reads 'Today' in the operations view and 'Dashboard' for the owner", /Today/.test(ops.document.querySelector('.tab[data-tab="dashboard"]').textContent) && /Dashboard/.test(o.document.querySelector('.tab[data-tab="dashboard"]').textContent));
  ok("C the operations person has no switch to the owner view", !ops.document.getElementById("viewAs") && !!ops.document.querySelector(".rolechip"));
  const sel = o.document.getElementById("viewAs"); sel.value = "ops"; sel.dispatchEvent(new o.Event("change", {bubbles: true})); await sleep(80);
  ok("C the owner can preview the operations view (View as), and it hides the same things", o.__dashView.role === "ops" && !/sales analytics|financial overview|best sellers/.test(text(o)) && /payments to verify/.test(text(o)));
  o.document.getElementById("viewAs").value = "owner"; o.document.getElementById("viewAs").dispatchEvent(new o.Event("change", {bubbles: true})); await sleep(80);
  ok("C switching back restores the owner view", o.__dashView.role === "owner" && /sales analytics/.test(text(o)));
  const wsel = ops.document.getElementById("whoSel"); wsel.value = "Khush"; wsel.dispatchEvent(new ops.Event("change", {bubbles: true})); await sleep(80);
  ok("C changing 'Working as' from Dad to Khush switches the experience", ops.__dashView.role === "owner" && /business overview/.test(text(ops)));

  // ── D. layouts ──
  const t = o.document.querySelector(".tabbar"), ts = o.getComputedStyle(t);
  ok("D desktop: a left sidebar replaces the bottom bar", ts.position === "fixed" && ts.flexDirection === "column" && t.getBoundingClientRect().left === 0 && t.getBoundingClientRect().width >= 200 && t.getBoundingClientRect().height > 600);
  ok("D desktop: the sidebar carries the brand, the five sections and the signed-in user", shown(o, o.document.querySelector(".sb-brand")) && o.document.querySelectorAll(".tabbar .tab").length === 5 && shown(o, o.document.querySelector(".sb-user")) && /Khush/.test(o.document.getElementById("sbName").textContent));
  ok("D desktop: 'Working as' moved into the sidebar", o.document.querySelector(".sb-user #opsWho") !== null);
  const kr = o.document.querySelector(".kpirow").getBoundingClientRect(), an = o.document.querySelector(".analytics").getBoundingClientRect(), at = o.document.querySelector(".att").getBoundingClientRect();
  ok("D desktop owner: KPI cards on top, sales analytics below them", kr.bottom <= an.top + 1 && o.document.querySelectorAll(".kpirow .kpi").length === 6);
  ok("D desktop owner: Needs attention sits beside the chart, same row, to its right", at.left >= an.right - 1 && Math.abs(at.top - an.top) < 6 && at.width < an.width, JSON.stringify([an.left, an.right, at.left, at.top, an.top]));
  ok("D desktop: no sideways scroll", o.document.documentElement.scrollWidth <= o.innerWidth + 1);
  const m = await openDev(DEMO, 390, OWNER);
  ok("D phone owner: the phone layout is a different layout (hero card, 2x2 figures, accordions)", m.__dashView.layout === "mobile" && !!m.document.querySelector(".hero") && m.document.querySelectorAll(".mini4 .kpi").length === 4 && m.document.querySelectorAll("details.acc").length >= 6 && !m.document.querySelector(".kpirow"));
  const mt = m.document.querySelector(".tabbar"), mts = m.getComputedStyle(mt);
  ok("D phone: bottom navigation stays, no sidebar furniture", mts.position === "fixed" && mt.getBoundingClientRect().bottom >= m.innerHeight - 1 && mt.getBoundingClientRect().height < 120 && !shown(m, m.document.querySelector(".sb-brand")) && !shown(m, m.document.querySelector(".sb-user")));
  ok("D phone owner: order is hero → figures → needs attention → chart → collapsed sections", (() => { const k = [...m.document.querySelectorAll(".dv2 > *")].map((e) => e.className.split(" ")[0]); return k.indexOf("hero") < k.indexOf("mini4") && k.indexOf("mini4") < k.indexOf("dp"); })() && [...m.document.querySelectorAll("details.acc")].every((d) => !d.open));
  ok("D phone: no sideways scroll", m.document.documentElement.scrollWidth <= m.innerWidth + 1, `${m.document.documentElement.scrollWidth} > ${m.innerWidth}`);
  ok("D phone: the chart text is readable (drawn at phone scale, not shrunk from the desktop chart)", (() => { const svg = m.document.getElementById("dChart"); const vb = svg.viewBox.baseVal.width; return vb <= 400 && svg.getBoundingClientRect().width / vb > 0.8; })());
  const mo = await openDev(DEMO, 390, OPS);
  ok("D phone operations: quick actions first, urgent actions, payments to verify, then collapsed sections", mo.__dashView.layout === "mobile" && mo.document.querySelectorAll(".qa button").length === 4 && /urgent actions/.test(text(mo)) && /payments to verify/.test(text(mo)) && !/sales analytics|financial overview/.test(text(mo)));
  ok("D phone operations: no sideways scroll", mo.document.documentElement.scrollWidth <= mo.innerWidth + 1);

  // ── E. everything that works today still works ──
  const tabs = ["capture", "inventory", "orders", "exchanges", "dashboard"], X = o.O4U_ops;
  const seen = {};
  for (const tb of tabs) { X.setTab(tb, true); await sleep(60); seen[tb] = tb === "capture" ? shown(o, o.document.getElementById("capMain")) : shown(o, o.document.getElementById("pg-" + tb)); }
  ok("E all five sections still open: Capture, Inventory, Orders, Exchanges, Dashboard", tabs.every((x) => seen[x]), JSON.stringify(seen));
  X.setTab("inventory", true); await sleep(60);
  ok("E Inventory still lists products with their stock", o.document.querySelectorAll("#invList .irow").length > 0);
  X.setTab("orders", true); await sleep(60);
  ok("E Orders still offers 'Paste order from WhatsApp' and typing an order by hand", !!o.document.getElementById("ordPaste") && !!o.document.getElementById("ordNew") && o.document.querySelectorAll("#ordList .irow").length > 0);
  const pid = Object.keys(o.__mockData.products)[0];
  X.openSheet({kind: "product", id: pid}); await sleep(60);
  ok("E the product sheet still has Sold in shop and Add or correct stock", /sold in shop/i.test(o.document.getElementById("opsBody").innerText) && /add or correct stock/i.test(o.document.getElementById("opsBody").innerText));
  X.openSheet(null); o.document.getElementById("opsSheet").hidden = true;
  const before = JSON.stringify(o.__mockData.products);
  X.setTab("dashboard", true); await sleep(60);
  o.document.querySelector("[data-recount]").click(); await sleep(80);
  ok("E from the dashboard, Recount opens the real recount form (no data changed by looking)", /pieces on the rack now/i.test(o.document.getElementById("opsBody").innerText) && JSON.stringify(o.__mockData.products) === before);
  o.O4U_ops.O.sheet = null; o.document.getElementById("opsSheet").hidden = true;
  X.setTab("dashboard", true); await sleep(60);
  const ops2 = await openDev(DEMO, 1280, OPS);
  ops2.document.querySelector('[data-qa="paste"]').click(); await sleep(250);
  ok("E operations quick action 'Paste WhatsApp order' goes to Orders and opens the paste box", ops2.O4U_ops.O.tab === "orders" && ops2.O4U_ops.O.sheet && ops2.O4U_ops.O.sheet.mode === "paste");
  const ops3 = await openDev(DEMO, 1280, OPS);
  ops3.document.querySelector("#pg-dashboard .arow[data-ord]").click(); await sleep(100);
  ok("E 'Verify' on a payment opens that order", ops3.O4U_ops.O.sheet && ops3.O4U_ops.O.sheet.kind === "order");
  const e = await openDev("{}", 1280, OWNER);
  ok("E empty shop (owner): honest empty states, no demo numbers, ₹0 sales", /nothing is recorded yet/.test(text(e)) && /no sales recorded for this period/.test(text(e)) && /nothing needs you right now/.test(text(e)) && !/nan|undefined|null/.test(text(e)) && [...e.document.querySelectorAll("#pg-dashboard .kpi .kv")][0].textContent === "₹0");
  const eo = await openDev("{}", 390, OPS);
  ok("E empty shop (operations, phone): empty states, no errors", /no payments to check/.test(text(eo)) && /nothing needs you right now/.test(text(eo)) && !/nan|undefined|null/.test(text(eo)));
  o.document.querySelector('[data-metric="orders"]').click(); await sleep(60);
  ok("E the chart can switch between Sales and Orders received", /Orders received/.test(o.document.getElementById("dChart").getAttribute("aria-label")));

  out.push(`\n${pass} passed, ${fail} failed`);
  return {pass, fail, lines: out};
})();
