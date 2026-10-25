/* ---------- Dashboard v2: role-aware, independent desktop and phone layouts ----------
   Numbers: the SAME pure metric functions as v1 (inserted at build time from dashboard.js, so there is one
   definition of every figure). Everything below only decides what to show, to whom, and where.
   Roles (owner / store operations) are a VIEW choice in this single-file app: the Operations view never
   renders revenue, profit, best sellers or any business total, but with no login in the Claude artifact it
   cannot be a security boundary. Real enforcement arrives with Supabase roles + database rules (roadmap V2.6). */
(() => {
"use strict";
/*__METRICS__*/

const store = {get(k) { try { return localStorage.getItem(k); } catch { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch { /* per-device convenience */ } }};
O.dash = {range: "30d", from: "", to: "", mq: "", exportAt: 0, open: {}, metric: "sales"};
const OWNER_NAMES = ["Khush"];                                   // everyone else works in the Store Operations view
const baseRole = () => OWNER_NAMES.includes(O.who) ? "owner" : "ops";
const viewRole = () => baseRole() === "owner" && store.get("o4u_view") === "ops" ? "ops" : baseRole();
const DESK = window.matchMedia("(min-width:1024px)");
const ROLE_LABEL = {owner: "Owner", ops: "Store Operations"};

/* ---------- small formatters ---------- */
const R = (p) => C.rupees(p);
const ago = (iso, now) => { const t = ms(iso); if (!Number.isFinite(t)) return ""; const d = Math.max(0, now - t); return d < HOUR ? `${Math.max(1, Math.round(d / MIN))} min ago` : d < DAY ? `${Math.round(d / HOUR)} h ago` : `${Math.round(d / DAY)} d ago`; };
const dayLabel = (t) => new Date(t).toLocaleDateString("en-IN", {day: "numeric", month: "short"});
const compactR = (p) => { const r = p / 100; return r >= 100000 ? "₹" + +(r / 100000).toFixed(1) + "L" : r >= 1000 ? "₹" + +(r / 1000).toFixed(1) + "k" : "₹" + Math.round(r); };
const CHAN = [["counter", "In the shop", "var(--c-counter)"], ["website", "Website", "var(--c-web)"], ["manual", "WhatsApp / phone", "var(--c-wa)"]];
const ICON = {
  capture: '<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>', sale: '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6"/>',
  stock: '<path d="M3 7l9-4 9 4-9 4z"/><path d="M3 7v10l9 4 9-4V7"/><path d="M12 11v10"/>', paste: '<rect x="8" y="3" width="8" height="4" rx="1"/><path d="M8 5H6a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V6a1 1 0 0 0-1-1h-2"/>',
};
const ic = (k) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[k]}</svg>`;

/* ---------- building blocks ---------- */
const kpi = (label, value, sub, o = {}) => `<div class="kpi ${o.tone || ""}${o.spark ? " has-spark" : ""}" ${o.def ? `title="${esc(o.def)}"` : ""}><div class="kl">${esc(label)}</div><div class="kv">${value}</div><div class="ks">${sub || ""}</div>${o.spark || ""}</div>`;
function delta(now, prev) {
  if (!prev) return `<span class="muted">nothing earlier to compare</span>`;
  const pct = Math.round(100 * (now - prev) / prev);
  return `<span class="dpill ${pct < 0 ? "dn" : "up"}">${pct >= 0 ? "▲" : "▼"} ${Math.abs(pct)}%</span><span class="muted"> vs the period before</span>`;
}
function spark(vals, color) {
  const n = vals.length; if (n < 2) return "";
  const W = 96, H = 28, max = Math.max(...vals);
  if (!max) return `<svg class="spark" viewBox="0 0 ${W} ${H}" aria-hidden="true"><line x1="0" x2="${W}" y1="${H - 3}" y2="${H - 3}" stroke="var(--line)" stroke-width="2" stroke-dasharray="3 4"/></svg>`;
  const pts = vals.map((v, i) => `${(i / (n - 1) * W).toFixed(1)},${(H - 3 - (v / max) * (H - 8)).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}
const card = (title, body, o = {}) => `<section class="dp ${o.cls || ""}"><div class="dh"><h3>${esc(title)}</h3>${o.extra || ""}</div><div class="db">${body}</div></section>`;
const acc = (key, title, body, badge) => { const open = O.dash.open[key] === true; return `<details class="dp acc" data-sec="${key}" ${open ? "open" : ""}><summary><h3>${esc(title)}</h3>${badge ? `<span class="badge">${badge}</span>` : ""}</summary><div class="db">${body}</div></details>`; };
const empty = (t, ok) => `<p class="empty ${ok ? "ok" : ""}">${esc(t)}</p>`;
const moreHint = (n, shown, what) => n > shown ? `<p class="hint">${n - shown} more ${what}.</p>` : "";

function attentionHtml(s, limit, now, loaded) {
  const att = s.attention;
  if (!loaded) return empty("Loading…");
  if (!att.length) return empty("Nothing needs you right now.", true);
  return `<div class="alist">${att.slice(0, limit).map((a, i) => `<button type="button" class="arow" data-att="${i}"><i class="pri p${Math.min(a.pri, 3)}"></i><span class="at">${esc(a.title)}</span><span class="as">${esc(a.sub || "")}${a.at ? ` · ${esc(ago(a.at, now))}` : ""}</span><span class="chev">›</span></button>`).join("")}</div>${att.length > limit ? `<button type="button" class="linkbtn" data-go="orders">View all ${att.length} in Orders</button>` : ""}`;
}
function splitBar(s, onDark) {
  const tot = s.gross;
  if (!tot) return `<p class="muted" style="margin:10px 0 0">No sales recorded for this period.</p>`;
  const col = (k, c) => onDark && k === "counter" ? "var(--ground)" : c;     // the shop colour is the ink colour: invert it on the dark card
  return `<div class="split" role="img" aria-label="Sales split by channel">${CHAN.map(([k, , c]) => s.ch[k].p ? `<i style="width:${(100 * s.ch[k].p / tot).toFixed(2)}%;background:${col(k, c)}"></i>` : "").join("")}</div>
    <div class="splitkey">${CHAN.map(([k, l, c]) => `<span><i style="background:${col(k, c)}"></i>${l} <b>${R(s.ch[k].p)}</b> <em>${Math.round(100 * s.ch[k].p / tot)}%</em></span>`).join("")}</div>`;
}
function chartHtml(s, mobile) {
  const orders = O.dash.metric === "orders";
  const segs = orders ? [["orders", "Orders received", "var(--c-web)"]] : CHAN;
  const totals = s.series.map((b) => orders ? b.orders : b.counter + b.website + b.manual);
  const max = Math.max(...totals, 0);
  if (!max) return empty(orders ? "No orders received in this period." : "No sales recorded for this period.");
  const W = mobile ? 340 : 720, H = mobile ? 200 : 250, L = 44, B = 28, T = 10, Rr = 6;
  const top = orders ? Math.max(4, Math.ceil(max / 4) * 4) : niceTop(max), bw = (W - L - Rr) / s.series.length;
  const y = (v) => T + (H - T - B) * (1 - v / top);
  const every = s.series.length > 14 ? Math.ceil(s.series.length / (mobile ? 4 : 8)) : 1;
  const bars = s.series.map((b, i) => {
    let acc = 0; const x = L + i * bw + Math.max(1, bw * 0.18), w = Math.max(3, bw * 0.64);
    const rects = segs.map(([k, , col], j) => { const v = b[k]; const y0 = y(acc + v), h = y(acc) - y0; acc += v; return v > 0 ? `<rect x="${x}" y="${y0}" width="${w}" height="${Math.max(0, h)}" fill="${col}" rx="${j === segs.length - 1 ? Math.min(4, w / 2) : 0}"/>` : ""; }).join("");
    return `<g>${rects}<rect class="hit" data-i="${i}" x="${L + i * bw}" y="${T}" width="${bw}" height="${H - T - B}" fill="transparent"/>${i % every === 0 ? `<text x="${L + i * bw + bw / 2}" y="${H - 9}" text-anchor="middle" font-size="11" fill="var(--ink-2)">${esc(dayLabel(b.t0))}</text>` : ""}</g>`;
  }).join("");
  const fmtY = (v) => orders ? String(Math.round(v)) : compactR(v);
  const grid = [0, top / 2, top].map((v) => `<line x1="${L}" x2="${W - Rr}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)" stroke-dasharray="${v ? "3 4" : "0"}"/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end" font-size="11" fill="var(--ink-2)">${esc(fmtY(v))}</text>`).join("");
  const rows = s.series.map((b) => `<tr><td>${esc(dayLabel(b.t0))}${s.step > 1 ? " week" : ""}</td>${CHAN.map(([k]) => `<td class="n">${R(b[k])}</td>`).join("")}<td class="n">${b.orders}</td></tr>`).join("");
  return `<div class="chartwrap"><svg id="dChart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${orders ? "Orders received" : "Sales by channel"} ${s.step > 1 ? "each week" : "each day"}" style="width:100%;height:auto;display:block">${grid}${bars}</svg><div class="tip" id="dTip" hidden></div></div>
    ${orders ? "" : `<div class="legend">${CHAN.map(([, l, c]) => `<span><i style="background:${c}"></i>${l}</span>`).join("")}</div>`}
    <details class="plain"><summary>Show as a table</summary><div class="tblwrap"><table class="tbl"><thead><tr><th>${s.step > 1 ? "Week from" : "Day"}</th>${CHAN.map(([, l]) => `<th class="n">${l}</th>`).join("")}<th class="n">Orders received</th></tr></thead><tbody>${rows}</tbody></table></div></details>`;
}
function niceTop(v) { const r = v / 100; const mag = Math.pow(10, Math.floor(Math.log10(r))); const s = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].find((k) => k * mag >= r); return s * mag * 100; }
function analyticsCard(s, mobile) {
  const seg = `<div class="seg2 small" role="group" aria-label="Chart shows">${[["sales", "Sales"], ["orders", "Orders"]].map(([k, l]) => `<button type="button" data-metric="${k}" aria-pressed="${O.dash.metric === k}">${l}</button>`).join("")}</div>`;
  const head = `<div class="sumline"><div><div class="kl">Sales in this period</div><div class="big">${R(s.gross)}</div></div><div class="sumr">${delta(s.gross, s.prevGross)}<div class="muted">${s.pieces} piece${s.pieces === 1 ? "" : "s"} · ${s.orders.received} order${s.orders.received === 1 ? "" : "s"} received</div></div></div>`;
  return card("Sales analytics", `${head}${chartHtml(s, mobile)}${splitBar(s)}`, {extra: seg, cls: "analytics"});
}
function inventoryCard(s, compact) {
  const chips = `<div class="stats4"><div><b>${s.low.length}</b><span>low stock</span></div><div><b>${s.out.length}</b><span>out of stock</span></div><div><b>${s.needsRecount.length}</b><span>to recount</span></div><div class="${s.gaps.length ? "bad" : ""}"><b>${s.gaps.length}</b><span>history gaps</span></div></div>`;
  const row = (attr, id, t, sub, go) => `<button type="button" class="arow flat" ${attr}="${esc(id)}"><span class="at">${esc(t)}</span><span class="as">${esc(sub)}</span><span class="chev">${go}</span></button>`;
  const low = s.low.slice(0, compact ? 3 : 4).map((x) => row("data-prod", x.p.id, `${prodName(x.p)} · ${C.sizeLabel(x.z)}`, `${x.sell} free to sell${x.h ? `, ${x.h} held` : ""}`, "›")).join("");
  const out = s.out.slice(0, 3).map((x) => row("data-prod", x.p.id, `${prodName(x.p)} · ${C.sizeLabel(x.z)}`, x.held ? "all pieces are held for orders" : "out of stock, still on the website", "›")).join("");
  const rec = s.needsRecount.slice(0, 3).map((p) => row("data-recount", p.id, prodName(p), `${C.totalStock(p)} on the rack, not counted in ${RECOUNT_AFTER_DAYS} days`, "Recount ›")).join("");
  const gap = s.gaps.slice(0, 2).map((g) => row("data-prod", g.productId, `${byId(g.productId) ? prodName(byId(g.productId)) : g.productId} · ${C.sizeLabel(g.size)}`, g.why, "›")).join("");
  const none = !(low || out || rec || gap);
  return `${chips}${none ? empty(O.products.length ? "No stock alerts." : "No products yet.", true) : ""}${low ? `<p class="mini">Low stock</p><div class="alist">${low}</div>${moreHint(s.low.length, compact ? 3 : 4, "sizes")}` : ""}${out ? `<p class="mini">Out of stock</p><div class="alist">${out}</div>${moreHint(s.out.length, 3, "sizes")}` : ""}${rec ? `<p class="mini">Needs a recount</p><div class="alist">${rec}</div>${moreHint(s.needsRecount.length, 3, "products")}` : ""}${gap ? `<p class="mini">Stock history gaps</p><div class="alist">${gap}</div>${moreHint(s.gaps.length, 2, "places")}` : ""}`;
}
const orderTotalTxt = (o) => `${C.rupees(C.orderTotal(o))}${C.isNum(o.deliveryP) ? "" : " + delivery"}`;
function ordersHtml(s, loaded, limit = 8) {
  if (!loaded) return empty("Loading…");
  const pend = s.orders.pendingNow.slice().sort((a, b) => ms(b.createdAt) - ms(a.createdAt));
  const recent = O.orders.filter((o) => !PENDING.includes(o.status)).slice(0, Math.max(0, limit - Math.min(limit, pend.length)));
  const row = (o) => `<button type="button" class="orow" data-ord="${esc(o.id)}"><span class="o1"><b>#${esc(o.code || String(o.id).slice(-6).toUpperCase())}</b> ${esc(o.name || "No name")}</span><span class="o2">${orderTotalTxt(o)}</span><span class="o3"><span class="src ${o.source === "website" ? "site" : ""}">${o.source === "website" ? "Website" : "WhatsApp / phone"}</span> ${esc((C.STATUS[o.status] || {}).label || o.status)}${PENDING.includes(o.status) && (C.STATUS[o.status] || {}).next ? ` · ${esc(C.STATUS[o.status].next)}` : ""}</span><span class="o4">${esc(fmtWhen(o.createdAt))}</span></button>`;
  const list = pend.slice(0, limit).map(row).join("") + recent.map(row).join("");
  return list ? `<div class="olist">${list}</div>` : empty("No orders yet.");
}
function healthHtml(s, now, owner) {
  const ex = O.dash.exportAt, changed = ex ? O.products.filter((p) => p.published && p.status !== "pending" && ms(p.updatedAt) > ex).length : 0;
  const m = s.money;
  const rows = [
    [s.holdsOver ? "bad" : s.holdsSoon ? "warn" : m.awaitingN ? "ok" : "mute", "Payments to check", m.awaitingN ? `${m.awaitingN} waiting${s.holdsOver ? `, ${s.holdsOver} past the hold time` : ""}${s.holdsSoon ? `, ${s.holdsSoon} ending within 30 min` : ""}` : "None waiting"],
    [s.gaps.length ? "bad" : s.firstMove ? "ok" : "mute", "Stock history", s.gaps.length ? `${s.gaps.length} place${s.gaps.length > 1 ? "s" : ""} where the rack and its history disagree` : s.firstMove ? "No gaps found" : "Nothing recorded yet"],
    [s.needsRecount.length ? "warn" : "ok", "Counts", s.needsRecount.length ? `${s.needsRecount.length} product${s.needsRecount.length > 1 ? "s" : ""} not counted in ${RECOUNT_AFTER_DAYS} days` : "Every product counted recently"],
    ["mute", "Store connection", "Not monitored yet. It arrives with the live backend."],
  ];
  if (owner) rows.unshift([ex ? (changed ? "warn" : "ok") : "mute", "Website catalogue", ex ? `Last export ${ago(new Date(ex).toISOString(), now)}${changed ? `, ${changed} product${changed > 1 ? "s" : ""} changed since` : ", up to date"}` : "Never exported"]);
  if (owner) rows.push(["mute", "Website sync", "No failed attempts recorded. Not tracked yet."]);
  return rows.map(([t, l, d]) => `<div class="hrow"><i class="hd ${t}"></i><div><b>${esc(l)}</b><div class="muted">${esc(d)}</div></div></div>`).join("");
}
function performanceHtml(s, now) {
  const top = s.top.length ? `<div class="tblwrap"><table class="tbl"><thead><tr><th>Product</th><th class="n">Pieces</th><th class="n">Sales</th></tr></thead><tbody>${s.top.slice(0, 6).map((t) => `<tr data-inv="${esc(t.id)}"><td>${esc(t.label || (byId(t.id) ? prodName(byId(t.id)) : t.id))}</td><td class="n">${t.n}</td><td class="n">${R(t.p)}</td></tr>`).join("")}</tbody></table></div>` : empty("No sales recorded for this period.");
  const catMax = Math.max(1, ...Object.values(s.byCat).map((c) => c.p));
  const cats = Object.keys(s.byCat).length ? `<div class="bars">${Object.entries(s.byCat).sort((a, b) => b[1].p - a[1].p).map(([k, c]) => `<div class="bar" title="${esc(catLabel(k) || "No category")}: ${R(c.p)}"><span class="bl">${esc(catLabel(k) || "No category")}</span><span class="bt"><i style="width:${(100 * c.p / catMax).toFixed(1)}%"></i></span><span class="bn">${R(c.p)}</span></div>`).join("")}</div>` : empty("No sales recorded for this period.");
  const sizes = Object.keys(s.bySize).length ? `<div class="chips2">${Object.entries(s.bySize).sort((a, b) => b[1] - a[1]).map(([z, n]) => `<span class="sz1">${esc(C.sizeLabel(z))} <b>${n}</b></span>`).join("")}</div>` : empty("No sales recorded for this period.");
  const slow = s.slow.length ? `<div class="tblwrap"><table class="tbl"><thead><tr><th>Product</th><th class="n">On rack</th><th class="n">At MRP</th></tr></thead><tbody>${s.slow.slice(0, 5).map((x) => `<tr data-inv="${esc(x.p.id)}"><td>${esc(prodName(x.p))}<div class="muted">${x.last ? `last sold ${esc(ago(new Date(x.last).toISOString(), now))}` : "no sale recorded"}</div></td><td class="n">${x.n}</td><td class="n">${R(x.v)}</td></tr>`).join("")}</tbody></table></div>${moreHint(s.slow.length, 5, "products")}` : empty(`Everything in stock sold in the last ${SLOW_AFTER_DAYS} days.`, true);
  const cust = `<div class="stats4 two"><div><b>${s.customers.unique}</b><span>customers ordered</span></div><div><b>${s.customers.repeat}</b><span>ordered before${s.customers.unique ? ` (${Math.round(100 * s.customers.repeat / s.customers.unique)}%)` : ""}</span></div></div>`;
  return `<div class="two"><div><p class="mini">Best sellers by sales</p>${top}</div><div><p class="mini">Not sold in ${SLOW_AFTER_DAYS} days, most money on the rack first</p>${slow}</div></div>
    <div class="two"><div><p class="mini">Sales by category</p>${cats}</div><div><p class="mini">Pieces sold by size</p>${sizes}<p class="mini" style="margin-top:14px">Customers (online and typed-in orders)</p>${cust}</div></div>`;
}
function financialHtml(s) {
  const m = s.money;
  return `<div class="fin"><div class="frow"><span>Sales (gross)</span><b>${R(m.gross)}</b></div><div class="frow"><span>Refunds sent</span><b>− ${R(m.refundedP)}</b></div><div class="frow tot"><span>Net sales</span><b>${R(m.net)}</b></div>
    <div class="frow soft"><span>Discounts given</span><em>Not recorded: the price before the offer isn't saved with each sale.</em></div><div class="frow soft"><span>Gross profit</span><em>Cost information required: no cost price is stored for products.</em></div></div>
    <p class="mini">Not income yet</p><div class="fin"><div class="frow"><span>Payments checked on orders</span><b>${R(m.paymentsVerifiedP)}</b></div><div class="frow"><span>Waiting for payment (${m.awaitingN})</span><b>${R(m.awaitingP)}</b></div><div class="frow"><span>Requests and agreed bills (${m.requestsN})</span><b>${R(m.requestsP)}</b></div><div class="frow"><span>Refunds approved, not sent (${m.refundsPendingN})</span><b>${R(m.refundsPendingP)}</b></div></div>`;
}
function definitionsHtml(s) {
  return `<ul class="defs"><li><b>Sales</b>: pieces that left the shop in the period, at the price charged. Counter sales count when recorded; online and WhatsApp orders count when handed to the rider. Requests and unpaid orders are never included.</li>
    <li><b>Net sales</b>: sales minus refunds actually sent in the period. Exchanges settled by a price difference are not included.</li>
    <li><b>Payments checked</b>: money staff confirmed in the UPI app on orders. Counter sales don't record how the customer paid, so cash and UPI at the counter can't be separated.</li>
    <li><b>Website</b> means the order came through the website; <b>WhatsApp / phone</b> means somebody typed it in.</li>
    <li><b>Low stock</b>: ${LOW_AT_MOST} or fewer free to sell in a size (rack count minus pieces held for orders).</li>
    <li><b>Needs a recount</b>: stock on the rack but no count, restock, capture, damage entry or correction in ${RECOUNT_AFTER_DAYS} days.</li>
    <li><b>Stock history gaps</b>: a change that does not start where the previous one ended, or a rack count different from the last change.</li>
    <li><b>Customers</b> are counted from order phone numbers only. People who buy at the counter are not recorded.</li>
    <li>Sales are counted from ${s.firstMove ? esc(dayLabel(s.firstMove)) : "the first recorded stock change"}; earlier sales were not recorded in Stockroom.${s.movesTruncated ? " This view reads the latest 1,000 stock changes." : ""}</li></ul>`;
}

/* stock sheet (same behaviour as before) */
function matrixData() {
  const prods = O.products.filter((p) => p.status !== "pending").sort((a, b) => (catLabel(a.category) || "zz").localeCompare(catLabel(b.category) || "zz") || prodName(a).localeCompare(prodName(b)));
  const sizes = [...new Set(prods.flatMap((p) => C.sizeKeys(p)))].sort((a, b) => C.sizeRank(a) - C.sizeRank(b) || a.localeCompare(b));
  return {prods, sizes};
}
function matrixHtml() {
  const {prods, sizes} = matrixData();
  if (!prods.length) return empty("No products yet.");
  const q = (O.dash.mq || "").toLowerCase().trim();
  const shown = q ? prods.filter((p) => [prodName(p), p.article, p.brand, catLabel(p.category)].join(" ").toLowerCase().includes(q)) : prods;
  const cell = (p, z) => { const n = C.stockOf(p, z), h = C.held(O.orders, p.id, z); if (!C.sizeKeys(p).includes(z)) return `<td class="z">·</td>`; return `<td class="${n ? "" : "z"}">${n}${h ? `<small>${h} held</small>` : ""}</td>`; };
  return `<div class="pagehead"><p class="label" style="margin:0">Pieces on the rack</p><button class="x" type="button" id="dlSheet">Download sheet (.csv)</button></div>
    <input id="mq" class="search" type="search" placeholder="Filter the sheet: product, article, brand…" value="${esc(O.dash.mq || "")}" autocomplete="off" style="margin-bottom:8px">
    <div class="scroll"><table class="matrix"><thead><tr><th class="nm">Product</th>${sizes.map((z) => `<th>${esc(C.sizeLabel(z) === "Free size" ? "Free" : z)}</th>`).join("")}<th>Total</th></tr></thead>
    <tbody>${shown.map((p) => `<tr data-inv="${esc(p.id)}"><td class="nm" title="${esc(prodName(p))}">${esc(prodName(p))}<small style="color:var(--ink-2)">${esc(p.article || "")}</small></td>${sizes.map((z) => cell(p, z)).join("")}<td><b>${C.totalStock(p)}</b></td></tr>`).join("") || `<tr><td class="nm" colspan="${sizes.length + 2}">Nothing matches.</td></tr>`}</tbody></table></div>
    <p class="hint">Tap a row to open it. The download has every product, with MRP, offer and website status.</p>`;
}
const csvCell = (v) => { const t = String(v == null ? "" : v); return /[",\n]/.test(t) ? '"' + t.replace(/"/g, '""') + '"' : t; };
async function downloadSheet() {
  const dl = window.claude && typeof window.claude.use === "function" ? await window.claude.use("downloads") : null;
  if (!dl) { X.toast("Downloads aren't available in this view. Open Stockroom in the browser."); return; }
  const {prods, sizes} = matrixData();
  const head = ["Product id", "Article", "Brand", "Category", "Product", "Colour", ...sizes.map((z) => "Stock " + C.sizeLabel(z)), "Total", "Held for orders", ...sizes.map((z) => "MRP " + C.sizeLabel(z)), "Offer price", "On website"];
  const rows = prods.map((p) => {
    const heldAll = C.sizeKeys(p).reduce((n, z) => n + C.held(O.orders, p.id, z), 0);
    const mrp = (z) => { const v = C.sizeKeys(p).includes(z) ? C.mrpFor(p, z) : null; return C.isNum(v) ? v / 100 : ""; };
    return [p.id, p.article || "", p.brand || "", catLabel(p.category) || "", p.type || "", p.colour || "", ...sizes.map((z) => C.sizeKeys(p).includes(z) ? C.stockOf(p, z) : ""), C.totalStock(p), heldAll, ...sizes.map(mrp), C.isNum(p.offerPrice) && p.offerPrice > 0 ? p.offerPrice : "", p.published ? "Yes" : "No"];
  });
  const csv = "﻿" + [head, ...rows].map((r) => r.map(csvCell).join(",")).join("\r\n");
  const d = new Date(), pad = (n) => String(n).padStart(2, "0");
  try { await dl.save({filename: `o4u-stock-sheet-${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}.csv`, data: new Blob([csv], {type: "text/csv"})}); X.toast("Stock sheet saved"); }
  catch (e) { X.toast(e && e.code === "declined" ? "Download cancelled." : "The sheet couldn't be saved. Try again."); }
}

/* ---------- Store Operations pieces (no business totals) ---------- */
function paymentsHtml(now) {
  const list = O.orders.filter((o) => o.status === "awaiting_payment").sort((a, b) => (ms(a.holdUntil) || Infinity) - (ms(b.holdUntil) || Infinity));
  if (!list.length) return empty("No payments to check.", true);
  return `<div class="alist">${list.slice(0, 6).map((o) => { const left = o.holdUntil ? ms(o.holdUntil) - now : null; const t = left === null ? "no timer" : left <= 0 ? "hold is over" : `ends in ${Math.max(1, Math.round(left / MIN))} min`; return `<button type="button" class="arow" data-ord="${esc(o.id)}"><i class="pri p${left !== null && left <= 0 ? 0 : left !== null && left <= EXPIRY_WARN_MS ? 1 : 3}"></i><span class="at">#${esc(o.code || String(o.id).slice(-6).toUpperCase())} ${esc(o.name || "No name")} · ${orderTotalTxt(o)}</span><span class="as">Check the UPI app · ${esc(t)}</span><span class="chev">Verify ›</span></button>`; }).join("")}</div>${moreHint(list.length, 6, "orders")}`;
}
function exchangesHtml() {
  const open = (O.cases || []).filter((c) => ["requested", "received", "refund_due"].includes(c.status));
  if (!open.length) return empty("No exchanges waiting.", true);
  const next = {requested: "Check the item when it comes back", received: "Give a replacement or approve a refund", refund_due: "Send the refund"};
  return `<div class="alist">${open.slice(0, 6).map((c) => `<button type="button" class="arow" data-case="${esc(c.id)}"><i class="pri p3"></i><span class="at">${esc(c.label || c.productId)} · ${esc(C.sizeLabel(c.size))} × ${c.qty}</span><span class="as">${esc(next[c.status] || c.status)} · order #${esc(c.code || "")}</span><span class="chev">›</span></button>`).join("")}</div>${moreHint(open.length, 6, "exchanges")}`;
}
const quickActions = () => `<div class="qa">${[["capture", "New product"], ["sale", "Sold in shop"], ["stock", "Add or fix stock"], ["paste", "Paste WhatsApp order"]].map(([k, l]) => `<button type="button" data-qa="${k}">${ic(k)}<span>${l}</span></button>`).join("")}</div>`;
function opsKpis(s, now) {
  const toSend = O.orders.filter((o) => ["paid", "packed", "change_due"].includes(o.status)).length;
  const toAct = s.attention.filter((a) => a.kind !== "refund").length;
  const soon = O.orders.filter((o) => o.status === "awaiting_payment" && o.holdUntil).map((o) => ms(o.holdUntil) - now).sort((a, b) => a - b)[0];
  return [kpi("Orders to action", String(toAct), toAct ? "see Urgent actions" : "all clear", {tone: s.attention.some((a) => a.pri <= 1) ? "bad" : toAct ? "warn" : ""}),
    kpi("Waiting for payment", String(s.money.awaitingN), soon === undefined ? "none" : soon <= 0 ? "a hold is over" : `next hold ends in ${Math.max(1, Math.round(soon / MIN))} min`, {tone: soon !== undefined && soon <= EXPIRY_WARN_MS ? "warn" : ""}),
    kpi("To pack and send", String(toSend), toSend ? "paid orders" : "none waiting"),
    kpi("Refunds to send", String(s.money.refundsPendingN), s.money.refundsPendingN ? "open Exchanges & refunds" : "none waiting", {tone: s.money.refundsPendingN ? "warn" : ""}),
    kpi("Low stock", String(s.low.length), `size${s.low.length === 1 ? "" : "s"} with ${LOW_AT_MOST} or fewer free`, {tone: s.low.length ? "warn" : ""}),
    kpi("To recount", String(s.needsRecount.length), `not counted in ${RECOUNT_AFTER_DAYS} days`)].join("");
}

/* ---------- the four layouts ---------- */
function periodControl() {
  return `<div class="seg2" role="group" aria-label="Period">${[["today", "Today"], ["7d", "7 days"], ["30d", "30 days"], ["custom", "Custom"]].map(([k, l]) => `<button type="button" data-dr="${k}" aria-pressed="${O.dash.range === k}">${l}</button>`).join("")}</div>`;
}
function customDates() {
  if (O.dash.range !== "custom") return "";
  const bad = Number.isFinite(localDate(O.dash.from)) && Number.isFinite(localDate(O.dash.to)) && localDate(O.dash.from) > localDate(O.dash.to);
  return `<div class="dates"><label>From <input type="date" id="dFrom" value="${esc(O.dash.from)}"></label><label>To <input type="date" id="dTo" value="${esc(O.dash.to)}"></label></div>${bad ? `<p class="note warn">The start date is after the end date. Showing the last 30 days.</p>` : ""}`;
}
const viewAs = () => baseRole() === "owner" ? `<label class="viewas">View as <select id="viewAs"><option value="owner" ${viewRole() === "owner" ? "selected" : ""}>Owner</option><option value="ops" ${viewRole() === "ops" ? "selected" : ""}>Store Operations</option></select></label>` : `<span class="rolechip">${ROLE_LABEL.ops}</span>`;
function greeting() { const h = new Date().getHours(); return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening"; }

function ownerKpis(s) {
  const m = s.money;
  return [
    kpi("Sales", R(m.gross), `${s.pieces} piece${s.pieces === 1 ? "" : "s"}`, {def: "Pieces that left the shop in this period, at the price charged: counter sales when recorded, online orders when handed to the rider. Not requests, not unpaid orders.", spark: spark(s.series.map((b) => b.counter + b.website + b.manual), "var(--ink)")}),
    kpi("Today", R(s.todayP), "since midnight", {def: "Sales since midnight today, whatever period is selected."}),
    kpi("In the shop", R(s.ch.counter.p), `${s.ch.counter.n} piece${s.ch.counter.n === 1 ? "" : "s"}`, {def: "Counter sales recorded with Sold in shop.", spark: spark(s.series.map((b) => b.counter), "var(--c-counter)")}),
    kpi("Website", R(s.ch.website.p), `${s.ch.website.n} piece${s.ch.website.n === 1 ? "" : "s"}`, {def: "Orders that came through the website and were handed to the rider. Orders typed in by hand are shown separately.", spark: spark(s.series.map((b) => b.website), "var(--c-web)")}),
    kpi("Orders received", String(s.orders.received), `${s.orders.website} website · ${s.orders.fulfilled} sent${s.orders.cancelled ? ` · ${s.orders.cancelled} cancelled` : ""}`, {def: "Orders created in this period, whatever happened to them. A request is not income.", spark: spark(s.series.map((b) => b.orders), "var(--ink-2)")}),
    kpi("Pending orders", String(s.orders.pendingNow.length), s.money.awaitingN ? `${s.money.awaitingN} waiting for payment` : "right now", {def: "Orders not yet handed to a rider or closed. Right now, not tied to the period."}),
  ].join("");
}

function ownerDesktop(c) {
  const {s, now, rng, loaded} = c;
  return `<div class="dv2 owner">
    <header class="dtop"><div><p class="greet">${greeting()}, ${esc(O.who)}</p><h2>Business overview</h2><p class="sub">${esc(rng.label)} · ${esc(dayLabel(rng.from))}${sod(rng.to) > sod(rng.from) ? ` to ${esc(dayLabel(rng.to))}` : ""}</p></div>
      <div class="dtools">${viewAs()}${periodControl()}</div></header>${customDates()}
    <div class="kpirow">${ownerKpis(s)}</div>
    <div class="grid2 a">${analyticsCard(s, false)}${card("Needs attention", attentionHtml(s, 5, now, loaded), {cls: "att", extra: s.attention.length ? `<span class="badge ${s.attention.some((a) => a.pri <= 1) ? "bad" : ""}">${s.attention.length}</span>` : ""})}</div>
    <div class="grid2 b">${card("Orders", ordersHtml(s, loaded), {extra: `<button type="button" class="x" data-go="orders">All orders</button>`})}${card("Inventory insights", inventoryCard(s, false))}</div>
    <div class="grid2 b">${card("Product performance", performanceHtml(s, now))}${card("Operational health", healthHtml(s, now, true))}</div>
    <div class="grid2 c">${card("Financial overview", financialHtml(s))}${card("How these numbers are counted", definitionsHtml(s))}</div>
    ${card("Stock sheet", matrixHtml())}</div>`;
}
function ownerMobile(c) {
  const {s, now, rng, loaded} = c; const m = s.money;
  return `<div class="dv2 owner mob">
    <header class="mtop"><div><h2>Overview</h2><p class="sub">${esc(rng.label)}</p></div>${viewAs()}</header>
    <div class="chipscroll">${periodControl()}</div>${customDates()}
    <section class="hero"><div class="kl">Sales</div><div class="big">${R(m.gross)}</div><div>${delta(m.gross, s.prevGross)}</div>${spark(s.series.map((b) => b.counter + b.website + b.manual), "var(--ground)")}${splitBar(s, true)}</section>
    <div class="mini4">${kpi("Today", R(s.todayP), "since midnight")}${kpi("Orders", String(s.orders.received), `${s.orders.website} website`)}${kpi("Pending", String(s.orders.pendingNow.length), m.awaitingN ? `${m.awaitingN} unpaid` : "right now")}${kpi("Low stock", String(s.low.length), "sizes", {tone: s.low.length ? "warn" : ""})}</div>
    ${card("Needs attention", attentionHtml(s, 3, now, loaded), {cls: "att", extra: s.attention.length ? `<span class="badge ${s.attention.some((a) => a.pri <= 1) ? "bad" : ""}">${s.attention.length}</span>` : ""})}
    ${analyticsCard(s, true)}
    ${acc("orders", "Orders", ordersHtml(s, loaded, 6), String(s.orders.pendingNow.length))}${acc("inv", "Inventory insights", inventoryCard(s, true), s.low.length + s.out.length ? String(s.low.length + s.out.length) : "")}
    ${acc("perf", "Product performance", performanceHtml(s, now))}${acc("fin", "Financial overview", financialHtml(s))}${acc("health", "Operational health", healthHtml(s, now, true))}${acc("defs", "How these numbers are counted", definitionsHtml(s))}${acc("sheet", "Stock sheet", matrixHtml())}</div>`;
}
function opsDesktop(c) {
  const {s, now, loaded} = c;
  return `<div class="dv2 ops">
    <header class="dtop"><div><p class="greet">${greeting()}, ${esc(O.who)}</p><h2>Today at the shop</h2><p class="sub">${esc(new Date(now).toLocaleDateString("en-IN", {weekday: "long", day: "numeric", month: "long"}))}</p></div><div class="dtools">${viewAs()}</div></header>
    <div class="kpirow">${opsKpis(s, now)}</div>
    <div class="grid2 a">${card("Urgent actions", attentionHtml(s, 10, now, loaded), {cls: "att", extra: s.attention.length ? `<span class="badge ${s.attention.some((a) => a.pri <= 1) ? "bad" : ""}">${s.attention.length}</span>` : ""})}${card("Payments to verify", paymentsHtml(now))}</div>
    <div class="grid2 b">${card("Orders in progress", ordersHtml(s, loaded, 8), {extra: `<button type="button" class="x" data-go="orders">All orders</button>`})}<div class="stack">${card("Quick actions", quickActions())}${card("Exchanges and refunds", exchangesHtml(), {extra: `<button type="button" class="x" data-go="exchanges">Open</button>`})}</div></div>
    <div class="grid2 b">${card("Stock to check", inventoryCard(s, false))}${card("Shop health", healthHtml(s, now, false))}</div>
    ${card("Stock sheet", matrixHtml())}</div>`;
}
function opsMobile(c) {
  const {s, now, loaded} = c;
  return `<div class="dv2 ops mob">
    <header class="mtop"><div><h2>Today</h2><p class="sub">${esc(new Date(now).toLocaleDateString("en-IN", {weekday: "long", day: "numeric", month: "long"}))}</p></div>${viewAs()}</header>
    ${quickActions()}
    ${card("Urgent actions", attentionHtml(s, 5, now, loaded), {cls: "att", extra: s.attention.length ? `<span class="badge ${s.attention.some((a) => a.pri <= 1) ? "bad" : ""}">${s.attention.length}</span>` : ""})}
    ${card("Payments to verify", paymentsHtml(now))}
    ${acc("orders", "Orders in progress", ordersHtml(s, loaded, 6), String(s.orders.pendingNow.length))}${acc("ex", "Exchanges and refunds", exchangesHtml())}${acc("inv", "Stock to check", inventoryCard(s, true), s.low.length + s.out.length ? String(s.low.length + s.out.length) : "")}${acc("health", "Shop health", healthHtml(s, now, false))}${acc("sheet", "Stock sheet", matrixHtml())}</div>`;
}

Pages.dashboard = function () {
  const pg = $("#pg-dashboard");
  watchExport();
  const now = Date.now(), rng = rangeOf(O.dash, now);
  const loaded = !!(O.loaded && O.loaded.orders && O.loaded.moves);
  const s = compute({products: O.products, orders: O.orders, moves: O.moves, refunds: O.refunds}, rng, now);
  const role = viewRole(), desk = DESK.matches;
  const c = {s, now, rng, loaded};
  pg.innerHTML = (role === "owner" ? (desk ? ownerDesktop(c) : ownerMobile(c)) : (desk ? opsDesktop(c) : opsMobile(c)))
    + ((!O.products.length && !O.orders.length && !O.moves.length && loaded) ? `<p class="note">Nothing is recorded yet. Capture products, record sales and take orders, and this page fills in by itself.</p>` : "");
  window.__dashState = s; window.__dashView = {role, layout: desk ? "desktop" : "mobile"};
  bindChart(s);
};

/* ---------- shell: sidebar brand and user, role-aware labels ---------- */
function decorateShell() {
  const tb = $(".tabbar"); if (!tb || $(".sb-brand")) return;
  const brand = document.createElement("div"); brand.className = "sb-brand"; brand.innerHTML = `<span class="mark">O<b>4</b>U</span><span class="nm">Stockroom</span>`;
  const user = document.createElement("div"); user.className = "sb-user"; user.innerHTML = `<div class="who2"><span class="av" id="sbAv"></span><div><div class="n" id="sbName"></div><div class="r" id="sbRole"></div></div></div><div id="sbWhoSlot"></div>`;
  tb.insertBefore(brand, tb.firstChild); tb.appendChild(user);
}
function placeWho() {
  const who = $("#opsWho"), slot = $("#sbWhoSlot"), head = $("header.top .brandrow"); if (!who || !slot || !head) return;
  if (DESK.matches) slot.appendChild(who); else head.appendChild(who);
}
function applyRole() {
  const role = viewRole();
  const tab = $('.tab[data-tab="dashboard"]');
  if (tab) { const t = [...tab.childNodes].reverse().find((n) => n.nodeType === 3 && n.textContent.trim()); if (t) t.textContent = role === "owner" ? "Dashboard" : "Today"; }
  const av = $("#sbAv"), nm = $("#sbName"), rl = $("#sbRole");
  if (av) av.textContent = String(O.who || "?").charAt(0).toUpperCase();
  if (nm) nm.textContent = O.who; if (rl) rl.textContent = ROLE_LABEL[role] + (role !== baseRole() ? " view" : "");
  document.body.dataset.role = role;
}
decorateShell(); placeWho(); applyRole();
DESK.addEventListener("change", () => { placeWho(); if (O.tab === "dashboard") Pages.dashboard(); });
document.addEventListener("change", (e) => {
  if (e.target.id === "whoSel") { applyRole(); if (O.tab === "dashboard") Pages.dashboard(); }
  if (e.target.id === "viewAs") { store.set("o4u_view", e.target.value); applyRole(); Pages.dashboard(); }
  if (e.target.id === "dFrom" || e.target.id === "dTo") { O.dash[e.target.id === "dFrom" ? "from" : "to"] = e.target.value; Pages.dashboard(); }
});

function bindChart(s) {
  const svg = $("#dChart"), tip = $("#dTip"); if (!svg || !tip) return;
  const show = (e) => {
    const h = e.target.closest(".hit"); if (!h) { tip.hidden = true; return; }
    const b = s.series[+h.dataset.i], tot = b.counter + b.website + b.manual;
    tip.innerHTML = O.dash.metric === "orders" ? `<b>${esc(dayLabel(b.t0))}${s.step > 1 ? " week" : ""}</b><br>${b.orders} order${b.orders === 1 ? "" : "s"} received`
      : `<b>${esc(dayLabel(b.t0))}${s.step > 1 ? " week" : ""}</b><br>${CHAN.map(([k, l, c]) => `<span><i style="background:${c}"></i>${l} ${R(b[k])}</span>`).join("<br>")}<br><b>${R(tot)}</b> · ${b.orders} order${b.orders === 1 ? "" : "s"} received`;
    const box = svg.getBoundingClientRect(), r = h.getBoundingClientRect();
    tip.hidden = false;
    tip.style.left = Math.min(Math.max(8, r.left - box.left + r.width / 2 - 80), Math.max(8, box.width - 168)) + "px"; tip.style.top = "4px";
  };
  svg.addEventListener("pointermove", show); svg.addEventListener("click", show); svg.addEventListener("pointerleave", () => { tip.hidden = true; });
}
let exportSub = false;
function watchExport() {
  if (exportSub || !O.db) return; exportSub = true;
  O.db.doc("config/export").onSnapshot((snap) => { O.dash.exportAt = (snap.exists && ms(snap.data().at)) || 0; if (O.tab === "dashboard") Pages.dashboard(); }, () => {});
}

/* ---------- actions ---------- */
document.addEventListener("click", (e) => {
  if (O.tab !== "dashboard") return;
  const dr = e.target.closest("[data-dr]"); if (dr) { O.dash.range = dr.dataset.dr; if (dr.dataset.dr === "custom" && !O.dash.from) { const t = new Date(); O.dash.to = t.toISOString().slice(0, 10); O.dash.from = new Date(+t - 6 * DAY).toISOString().slice(0, 10); } Pages.dashboard(); return; }
  const mt = e.target.closest("[data-metric]"); if (mt) { O.dash.metric = mt.dataset.metric; Pages.dashboard(); return; }
  const a = e.target.closest("[data-att]"); if (a) { const it = window.__dashState.attention[+a.dataset.att]; if (!it) return; if (it.target.type === "tab") X.setTab(it.target.id, true); else { X.setTab("orders", true); X.openSheet({kind: "order", id: it.target.id}); } return; }
  const o = e.target.closest("[data-ord]"); if (o) { X.setTab("orders", true); X.openSheet({kind: "order", id: o.dataset.ord}); return; }
  const cs = e.target.closest("[data-case]"); if (cs) { X.setTab("exchanges", true); X.openSheet({kind: "case", id: cs.dataset.case}); return; }
  const pr = e.target.closest("[data-prod]"); if (pr) { X.openSheet({kind: "product", id: pr.dataset.prod}); return; }
  const rc = e.target.closest("[data-recount]"); if (rc) { X.openSheet({kind: "product", id: rc.dataset.recount, mode: "stock", f: {why: "recount", n: {}}}); return; }
  const g = e.target.closest("[data-go]"); if (g) { X.setTab(g.dataset.go); return; }
  const qa = e.target.closest("[data-qa]"); if (qa) {
    const k = qa.dataset.qa;
    if (k === "capture") X.setTab("capture");
    else if (k === "paste") { X.setTab("orders"); setTimeout(() => { const b = $("#ordPaste"); if (b) b.click(); }, 60); }
    else { X.setTab("inventory"); setTimeout(() => { const i = $("#invQ"); if (i) i.focus({preventScroll: true}); }, 60); }
    return;
  }
  if (e.target.closest("#dlSheet")) { downloadSheet(); return; }
  const row = e.target.closest("tr[data-inv]"); if (row) X.openSheet({kind: "product", id: row.dataset.inv});
});
document.addEventListener("toggle", (e) => { const d = e.target; if (d && d.dataset && d.dataset.sec) O.dash.open[d.dataset.sec] = d.open; }, true);
let mqT;
document.addEventListener("input", (e) => {
  if (e.target.id !== "mq") return;
  clearTimeout(mqT); mqT = setTimeout(() => { O.dash.mq = e.target.value; const pos = e.target.selectionStart; Pages.dashboard(); const i = document.getElementById("mq"); if (i) { i.focus(); try { i.setSelectionRange(pos, pos); } catch (_) {} } }, 250);
});
X.renderPage();
})();
