/* ---------- Dashboard (redesign) ----------
   Every number is worked out from the records Stockroom already holds: stock history
   (stockmoves), orders, refunds, exchanges and products. Nothing here is typed in, sampled
   or estimated. When the data for a figure does not exist the panel says so instead of
   showing a number. Definitions are listed at the bottom of the page.
   The metric functions (window.O4U_metrics) are pure: records in, numbers out. */
(() => {
"use strict";
const X = window.O4U_ops; if (!X) return;
const {O, C, esc, Pages, prodName, byId, fmtWhen, catLabel} = X;
const $ = (s, el = document) => el.querySelector(s);
const MIN = 60000, HOUR = 3600000, DAY = 86400000;
const sod = (t) => { const d = new Date(t); d.setHours(0, 0, 0, 0); return +d; };
const eod = (t) => sod(t) + DAY - 1;
const SOLD_KINDS = ["sale", "dispatch"];                    // pieces that left the shop for a customer
const VERIFY_KINDS = ["capture", "restock", "recount", "edit", "damage"];   // somebody looked at the rack
const PENDING = ["request", "confirmed", "awaiting_payment", "paid", "packed", "change_due"];
const LOW_AT_MOST = 2, RECOUNT_AFTER_DAYS = 60, SLOW_AFTER_DAYS = 30, EXPIRY_WARN_MS = 30 * MIN;
const ms = (v) => { const t = Date.parse(v); return Number.isFinite(t) ? t : NaN; };
const localDate = (s) => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(s || "")); return m ? new Date(+m[1], +m[2] - 1, +m[3]).getTime() : NaN; };

/* ---------- the period ---------- */
function rangeOf(sel, now) {
  const back = (n, label) => ({from: sod(now) - (n - 1) * DAY, to: eod(now), label});
  if (sel.range === "today") return {from: sod(now), to: eod(now), label: "Today"};
  if (sel.range === "7d") return back(7, "Last 7 days");
  if (sel.range === "custom") {
    const f = localDate(sel.from), t = localDate(sel.to);
    if (Number.isFinite(f) && Number.isFinite(t) && f <= t) return {from: f, to: t + DAY - 1, label: "Custom range"};
  }
  return back(30, "Last 30 days");
}

/* ---------- the numbers (pure) ---------- */
function compute(D, rng, now) {
  const {from, to} = rng;
  const inR = (t) => { const x = ms(t); return x >= from && x <= to; };
  const ord = new Map(D.orders.map((o) => [o.id, o]));
  const chanOf = (m) => m.kind === "sale" ? "counter" : (ord.get(m.orderId) && ord.get(m.orderId).source === "website" ? "website" : "manual");
  const val = (m) => (m.unitP || 0) * -m.change;
  const soldIn = (a, b) => D.moves.filter((m) => SOLD_KINDS.includes(m.kind) && m.change < 0 && ms(m.at) >= a && ms(m.at) <= b);
  const zero = () => ({p: 0, n: 0});
  const sold = soldIn(from, to);
  const ch = {counter: zero(), website: zero(), manual: zero()};
  for (const m of sold) { const c = ch[chanOf(m)]; c.p += val(m); c.n += -m.change; }
  const gross = ch.counter.p + ch.website.p + ch.manual.p;
  const pieces = ch.counter.n + ch.website.n + ch.manual.n;
  const todayM = soldIn(sod(now), eod(now));
  const todayP = todayM.reduce((n, m) => n + val(m), 0);
  // the same length of time just before, for the "vs previous" line
  const span = to - from + 1;
  const prevGross = soldIn(from - span, from - 1).reduce((n, m) => n + val(m), 0);

  // chart buckets: daily up to 62 days, weekly beyond
  const days = Math.round((sod(to) - sod(from)) / DAY) + 1, step = days > 62 ? 7 : 1;
  const series = Array.from({length: Math.ceil(days / step)}, (_, i) => ({t0: sod(from) + i * step * DAY, t1: Math.min(eod(to), sod(from) + (i + 1) * step * DAY - 1), counter: 0, website: 0, manual: 0, orders: 0}));
  const slot = (t) => Math.floor((sod(t) - sod(from)) / DAY / step);
  for (const m of sold) { const s = series[slot(ms(m.at))]; if (s) s[chanOf(m)] += val(m); }
  const received = D.orders.filter((o) => inR(o.createdAt));
  for (const o of received) { const s = series[slot(ms(o.createdAt))]; if (s) s.orders++; }

  // orders
  const notCancelled = received.filter((o) => o.status !== "cancelled");
  const orders = {
    received: received.length, cancelled: received.length - notCancelled.length,
    fulfilled: received.filter((o) => ["dispatched", "delivered"].includes(o.status)).length,
    website: received.filter((o) => o.source === "website").length,
    pendingNow: D.orders.filter((o) => PENDING.includes(o.status)),
  };
  const itemsOf = (list) => list.reduce((n, o) => n + C.itemsTotal(o.lines), 0);
  const awaiting = D.orders.filter((o) => o.status === "awaiting_payment");
  const requests = D.orders.filter((o) => ["request", "confirmed"].includes(o.status));

  // needs attention: orders, refunds, holds
  const attention = [];
  const add = (pri, kind, title, sub, at, target) => attention.push({pri, kind, title, sub, at, target});
  const who = (o) => o.name || "No name";
  const code = (o) => o.code || String(o.id).slice(-6).toUpperCase();
  for (const o of D.orders) {
    const left = o.status === "awaiting_payment" && o.holdUntil ? ms(o.holdUntil) - now : null;
    if (left !== null && left <= 0) add(0, "hold", `Hold is over: #${code(o)} ${who(o)}`, "Check the UPI app before releasing the stock", o.holdUntil, {type: "order", id: o.id});
    else if (left !== null && left <= EXPIRY_WARN_MS) add(1, "hold", `Hold ends in ${Math.max(1, Math.round(left / MIN))} min: #${code(o)} ${who(o)}`, "Check the UPI app now", o.holdUntil, {type: "order", id: o.id});
    else if (o.status === "change_due") add(3, "order", `Change to settle: #${code(o)} ${who(o)}`, (C.STATUS.change_due || {}).next, o.updatedAt || o.createdAt, {type: "order", id: o.id});
    else if (o.status === "failed") add(4, "order", `Delivery failed: #${code(o)} ${who(o)}`, (C.STATUS.failed || {}).next, o.updatedAt || o.createdAt, {type: "order", id: o.id});
    else if (o.status === "paid") add(5, "order", `Paid, to pack: #${code(o)} ${who(o)}`, (C.STATUS.paid || {}).next, o.payment && o.payment.at || o.updatedAt, {type: "order", id: o.id});
    else if (o.status === "request") add(6, "order", `New request: #${code(o)} ${who(o)}`, (C.STATUS.request || {}).next, o.createdAt, {type: "order", id: o.id});
    else if (o.status === "confirmed") add(7, "order", `Bill agreed: #${code(o)} ${who(o)}`, (C.STATUS.confirmed || {}).next, o.updatedAt || o.createdAt, {type: "order", id: o.id});
    else if (o.status === "packed") add(8, "order", `Packed, needs a rider: #${code(o)} ${who(o)}`, (C.STATUS.packed || {}).next, o.updatedAt || o.createdAt, {type: "order", id: o.id});
    if (o.duplicateOf && C.OPEN.includes(o.status)) add(2, "order", `Possible repeat order: #${code(o)} ${who(o)}`, "Check with the customer", o.createdAt, {type: "order", id: o.id});
  }
  const refundsDue = D.refunds.filter((r) => r.status === "approved");
  for (const r of refundsDue) add(2, "refund", `Refund to send: ${C.rupees(r.amountP)} to ${r.name || "customer"}`, "Send by UPI, then record it under Exchanges & refunds", r.createdAt, {type: "tab", id: "exchanges"});
  attention.sort((a, b) => a.pri - b.pri || ms(a.at) - ms(b.at));

  // inventory alerts
  const ready = D.products.filter((p) => p.status !== "pending");
  const low = [], out = [];
  for (const p of ready) for (const z of C.sizeKeys(p)) {
    const n = C.stockOf(p, z), h = C.held(D.orders, p.id, z), sell = n - h;
    if (n > 0 && sell >= 1 && sell <= LOW_AT_MOST) low.push({p, z, sell, n, h});
    else if (n > 0 && sell <= 0) out.push({p, z, held: true});
    else if (n === 0 && p.published) out.push({p, z, held: false});
  }
  const lastTouch = {};
  for (const m of D.moves) if (VERIFY_KINDS.includes(m.kind)) { const t = ms(m.at); if (!(lastTouch[m.productId] >= t)) lastTouch[m.productId] = t; }
  const needsRecount = ready.filter((p) => C.totalStock(p) > 0 && !((lastTouch[p.id] || 0) >= now - RECOUNT_AFTER_DAYS * DAY));
  // stock history gaps: a change whose "before" is not the previous "after", or a rack count that is not the last "after"
  const lists = {};
  for (const m of D.moves.slice().sort((a, b) => ms(a.at) - ms(b.at))) (lists[m.productId + "|" + m.size] = lists[m.productId + "|" + m.size] || []).push(m);
  const gaps = [];
  for (const [k, list] of Object.entries(lists)) {
    for (let i = 1; i < list.length; i++) if (list[i].before !== list[i - 1].after) gaps.push({productId: list[i].productId, size: list[i].size, why: `History says ${list[i - 1].after}, next change started from ${list[i].before}`});
    const last = list[list.length - 1], p = D.products.find((x) => x.id === last.productId);
    if (p && C.stockOf(p, last.size) !== last.after) gaps.push({productId: p.id, size: last.size, why: `History ends at ${last.after}, the rack shows ${C.stockOf(p, last.size)}`});
  }

  // products
  const byProd = {}, byCat = {}, bySize = {};
  for (const m of sold) {
    const p = D.products.find((x) => x.id === m.productId);
    const b = byProd[m.productId] = byProd[m.productId] || {id: m.productId, label: m.label, n: 0, p: 0}; b.n += -m.change; b.p += val(m);
    const ck = m.category || (p && p.category) || ""; byCat[ck] = byCat[ck] || {n: 0, p: 0}; byCat[ck].n += -m.change; byCat[ck].p += val(m);
    bySize[m.size] = (bySize[m.size] || 0) + -m.change;
  }
  const lastSold = {};
  for (const m of D.moves) if (SOLD_KINDS.includes(m.kind) && m.change < 0) { const t = ms(m.at); if (!(lastSold[m.productId] >= t)) lastSold[m.productId] = t; }
  const mrpValue = (p) => C.sizeKeys(p).reduce((n, z) => n + (C.mrpFor(p, z) || 0) * C.stockOf(p, z), 0);
  const slow = ready.filter((p) => C.totalStock(p) > 0 && !((lastSold[p.id] || 0) >= now - SLOW_AFTER_DAYS * DAY))
    .map((p) => ({p, n: C.totalStock(p), v: mrpValue(p), last: lastSold[p.id] || null})).sort((a, b) => b.v - a.v);
  const firstMove = D.moves.reduce((m, x) => { const t = ms(x.at); return t < m ? t : m; }, Infinity);

  // customers (online and hand-typed orders only: walk-in buyers are not recorded)
  const phone = (o) => C.phoneDigits(o.phone).slice(-10);
  const allCount = {};
  for (const o of D.orders) if (o.status !== "cancelled" && phone(o)) allCount[phone(o)] = (allCount[phone(o)] || 0) + 1;
  const inRange = new Set(notCancelled.map(phone).filter(Boolean));
  const customers = {unique: inRange.size, repeat: [...inRange].filter((ph) => allCount[ph] > 1).length};

  // money
  const refundsDone = D.refunds.filter((r) => r.status === "completed" && inR(r.completedAt || r.createdAt));
  const refundedP = refundsDone.reduce((n, r) => n + (r.amountP || 0), 0);
  const money = {
    gross, refundedP, net: gross - refundedP,
    refundsPendingP: refundsDue.reduce((n, r) => n + (r.amountP || 0), 0), refundsPendingN: refundsDue.length,
    paymentsVerifiedP: D.orders.filter((o) => o.payment && inR(o.payment.at)).reduce((n, o) => n + (o.paidP || 0), 0),
    awaitingP: itemsOf(awaiting), awaitingN: awaiting.length, requestsP: itemsOf(requests), requestsN: requests.length,
    returnedPieces: D.moves.filter((m) => inR(m.at) && m.kind === "return").reduce((n, m) => n + m.change, 0),
  };
  const holdsOver = awaiting.filter((o) => o.holdUntil && ms(o.holdUntil) - now <= 0).length;
  const holdsSoon = awaiting.filter((o) => o.holdUntil && ms(o.holdUntil) - now > 0 && ms(o.holdUntil) - now <= EXPIRY_WARN_MS).length;
  return {range: rng, ch, gross, pieces, todayP, prevGross, series, step, orders, attention, low, out, needsRecount, gaps, money,
    top: Object.values(byProd).sort((a, b) => b.p - a.p || b.n - a.n), byCat, bySize, slow, firstMove: Number.isFinite(firstMove) ? firstMove : null,
    customers, holdsOver, holdsSoon, lowProducts: new Set(low.map((x) => x.p.id)).size, readyCount: ready.length, movesTruncated: D.moves.length >= 1000};
}
window.O4U_metrics = {compute, rangeOf};

/* ---------- drawing ---------- */
O.dash = {range: "30d", from: "", to: "", mq: "", exportAt: 0, open: {}};
const ago = (iso, now) => { const t = ms(iso); if (!Number.isFinite(t)) return ""; const d = Math.max(0, now - t); return d < HOUR ? `${Math.max(1, Math.round(d / MIN))} min ago` : d < DAY ? `${Math.round(d / HOUR)} h ago` : `${Math.round(d / DAY)} d ago`; };
const R = (p) => C.rupees(p);
const dayLabel = (t) => new Date(t).toLocaleDateString("en-IN", {day: "numeric", month: "short"});
const CHAN = [["counter", "In the shop", "var(--c-counter)"], ["website", "Website", "var(--c-web)"], ["manual", "WhatsApp / phone", "var(--c-wa)"]];

function kpi(label, value, sub, opts = {}) {
  return `<div class="kpi ${opts.tone || ""}" ${opts.def ? `title="${esc(opts.def)}"` : ""}><div class="kl">${esc(label)}</div><div class="kv">${value}</div>${sub ? `<div class="ks">${sub}</div>` : ""}</div>`;
}
function delta(now, prev) {
  if (!prev) return `<span class="muted">no earlier period to compare</span>`;
  const pct = Math.round(100 * (now - prev) / prev);
  return `<span class="${pct < 0 ? "dn" : "up"}">${pct >= 0 ? "▲" : "▼"} ${Math.abs(pct)}%</span> <span class="muted">vs the period before</span>`;
}
function niceTop(v) { const r = v / 100; const mag = Math.pow(10, Math.floor(Math.log10(r))); const s = [1, 2, 2.5, 5, 10].find((k) => k * mag >= r); return s * mag * 100; }
function chart(series, step) {
  const totals = series.map((s) => s.counter + s.website + s.manual);
  const max = Math.max(...totals, 0);
  if (!max) return `<p class="empty">No sales recorded for this period.</p>`;
  const W = 720, H = 220, L = 54, B = 28, T = 10, Rr = 6, top = niceTop(max), bw = (W - L - Rr) / series.length;
  const y = (v) => T + (H - T - B) * (1 - v / top);
  const every = series.length > 14 ? Math.ceil(series.length / 7) : 1;
  const bars = series.map((s, i) => {
    let acc = 0; const x = L + i * bw + Math.max(1, bw * 0.16), w = Math.max(3, bw * 0.68);
    const segs = CHAN.map(([k, , col]) => { const h = y(acc) - y(acc + s[k]); const y0 = y(acc + s[k]); acc += s[k]; return s[k] > 0 ? `<rect x="${x}" y="${y0}" width="${w}" height="${Math.max(0, h)}" fill="${col}"/>` : ""; }).join("");
    return `<g>${segs}<rect class="hit" data-i="${i}" x="${L + i * bw}" y="${T}" width="${bw}" height="${H - T - B}" fill="transparent"/>${i % every === 0 ? `<text x="${L + i * bw + bw / 2}" y="${H - 9}" text-anchor="middle" font-size="11" fill="var(--ink-2)">${esc(dayLabel(s.t0))}</text>` : ""}</g>`;
  }).join("");
  const grid = [0, top / 2, top].map((v) => `<line x1="${L}" x2="${W - Rr}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end" font-size="11" fill="var(--ink-2)">${esc(R(v))}</text>`).join("");
  const rows = series.map((s) => `<tr><td>${esc(dayLabel(s.t0))}${step > 1 ? " week" : ""}</td>${CHAN.map(([k]) => `<td class="n">${R(s[k])}</td>`).join("")}<td class="n">${s.orders}</td></tr>`).join("");
  return `<div class="chartwrap"><svg id="dChart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Sales by channel ${step > 1 ? "each week" : "each day"}" style="width:100%;height:auto;display:block">${grid}${bars}</svg><div class="tip" id="dTip" hidden></div></div>
    <div class="legend">${CHAN.map(([, l, c]) => `<span><i style="background:${c}"></i>${l}</span>`).join("")}</div>
    <details class="plain"><summary>Show as a table</summary><div class="tblwrap"><table class="tbl"><thead><tr><th>${step > 1 ? "Week from" : "Day"}</th>${CHAN.map(([, l]) => `<th class="n">${l}</th>`).join("")}<th class="n">Orders received</th></tr></thead><tbody>${rows}</tbody></table></div></details>`;
}
const section = (key, title, body, cls = "", openDefault = true) => {
  const open = O.dash.open[key] !== undefined ? O.dash.open[key] : (openDefault && !window.matchMedia("(max-width:640px)").matches);
  return `<details class="dp ${cls}" data-sec="${key}" ${open ? "open" : ""}><summary><h3>${esc(title)}</h3></summary><div class="db">${body}</div></details>`;
};
const panel = (title, body, cls = "", extra = "") => `<section class="dp ${cls}"><div class="dh"><h3>${esc(title)}</h3>${extra}</div><div class="db">${body}</div></section>`;
const dot = (tone) => `<i class="hd ${tone}"></i>`;

Pages.dashboard = function () {
  const pg = $("#pg-dashboard");
  watchExport();
  const now = Date.now();
  const rng = rangeOf(O.dash, now);
  const D = {products: O.products, orders: O.orders, moves: O.moves, refunds: O.refunds};
  const loaded = O.loaded && O.loaded.orders && O.loaded.moves;
  const s = compute(D, rng, now);
  const m = s.money, anyData = O.products.length || O.orders.length || O.moves.length;
  const att = s.attention;
  const attHtml = !loaded ? `<p class="empty">Loading…</p>` : att.length ? `<div class="alist">${att.slice(0, 7).map((a, i) => `<button type="button" class="arow ${a.pri <= 1 ? "hot" : ""}" data-att="${i}"><span class="at">${esc(a.title)}</span><span class="as">${esc(a.sub || "")}${a.at ? ` · ${esc(ago(a.at, now))}` : ""}</span><span class="ago">Open ›</span></button>`).join("")}${att.length > 7 ? `<p class="hint">${att.length - 7} more in Orders.</p>` : ""}</div>`
    : `<p class="empty ok">Nothing needs you right now.</p>`;
  const noSales = s.pieces === 0;
  const kpis = [
    kpi("Sales", R(m.gross), `${s.pieces} piece${s.pieces === 1 ? "" : "s"} · ${delta(m.gross, s.prevGross)}`, {def: "Pieces that left the shop in this period, at the price charged: counter sales when recorded, online orders when handed to the rider. Not requests, not unpaid orders."}),
    kpi("Today", R(s.todayP), "same definition, since midnight", {def: "Sales since midnight today, whatever period is selected."}),
    kpi("In the shop", R(s.ch.counter.p), `${s.ch.counter.n} piece${s.ch.counter.n === 1 ? "" : "s"}`, {def: "Counter sales recorded with Sold in shop."}),
    kpi("Website", R(s.ch.website.p), `${s.ch.website.n} piece${s.ch.website.n === 1 ? "" : "s"}${s.ch.manual.n ? ` · plus ${R(s.ch.manual.p)} WhatsApp / phone` : ""}`, {def: "Orders that arrived through the website and were handed to the rider. Orders typed in by hand are shown separately."}),
    kpi("Orders received", String(s.orders.received), `${s.orders.website} from the website · ${s.orders.fulfilled} sent${s.orders.cancelled ? ` · ${s.orders.cancelled} cancelled` : ""}`, {def: "Orders created in this period, whatever happened to them. A request is not income."}),
    kpi("Pending orders", String(s.orders.pendingNow.length), m.awaitingN ? `${m.awaitingN} waiting for payment` : "right now", {def: "Orders that are not yet handed to a rider or closed (request, bill agreed, waiting for payment, paid, packed). Right now, not tied to the period."}),
    kpi("Low stock", String(s.lowProducts), `${s.low.length} size${s.low.length === 1 ? "" : "s"} with ${LOW_AT_MOST} or fewer free to sell`, {tone: s.low.length ? "warn" : "", def: "Sizes with 1 or 2 pieces free to sell (on the rack minus held for orders)."}),
    kpi("Needs attention", String(att.length), att.length ? "see the list above" : "all clear", {tone: att.some((a) => a.pri <= 1) ? "bad" : att.length ? "warn" : "", def: "Orders and refunds that wait for a person: holds ending, payments to check, orders to pack or send, refunds to pay."}),
  ].join("");
  const more = (n, shown, what) => n > shown ? `<p class="hint">${n - shown} more ${what}.</p>` : "";
  const lowRows = s.low.slice(0, 4).map((x) => `<button type="button" class="arow" data-prod="${esc(x.p.id)}"><span class="at">${esc(prodName(x.p))} · ${esc(C.sizeLabel(x.z))}</span><span class="as">${x.sell} free to sell${x.h ? `, ${x.h} held` : ""}</span><span class="ago">Open ›</span></button>`).join("");
  const outRows = s.out.slice(0, 3).map((x) => `<button type="button" class="arow" data-prod="${esc(x.p.id)}"><span class="at">${esc(prodName(x.p))} · ${esc(C.sizeLabel(x.z))}</span><span class="as">${x.held ? "all pieces are held for orders" : "out of stock, still on the website"}</span><span class="ago">Open ›</span></button>`).join("");
  const recRows = s.needsRecount.slice(0, 3).map((p) => `<button type="button" class="arow" data-recount="${esc(p.id)}"><span class="at">${esc(prodName(p))}</span><span class="as">${C.totalStock(p)} on the rack, no count or restock in ${RECOUNT_AFTER_DAYS} days</span><span class="ago">Recount ›</span></button>`).join("");
  const invHtml = (lowRows || outRows || recRows || s.gaps.length) ? `${lowRows ? `<p class="mini">Low stock</p><div class="alist">${lowRows}</div>${more(s.low.length, 4, "sizes")}` : ""}${outRows ? `<p class="mini">Out of stock</p><div class="alist">${outRows}</div>${more(s.out.length, 3, "sizes")}` : ""}${recRows ? `<p class="mini">Needs a recount</p><div class="alist">${recRows}</div>${more(s.needsRecount.length, 3, "products")}` : ""}${s.gaps.length ? `<p class="mini">Stock history gaps</p><div class="alist">${s.gaps.slice(0, 2).map((g) => `<button type="button" class="arow" data-prod="${esc(g.productId)}"><span class="at">${esc(byId(g.productId) ? prodName(byId(g.productId)) : g.productId)} · ${esc(C.sizeLabel(g.size))}</span><span class="as">${esc(g.why)}</span><span class="ago">Open ›</span></button>`).join("")}</div>${more(s.gaps.length, 2, "places")}` : ""}`
    : `<p class="empty ok">${O.products.length ? "No stock alerts." : "No products yet."}</p>`;
  const pend = s.orders.pendingNow.slice().sort((a, b) => ms(b.createdAt) - ms(a.createdAt));
  const recent = O.orders.filter((o) => !PENDING.includes(o.status)).slice(0, Math.max(0, 8 - pend.slice(0, 8).length));
  const orow = (o) => `<button type="button" class="orow" data-ord="${esc(o.id)}"><span class="o1"><b>#${esc(o.code || String(o.id).slice(-6).toUpperCase())}</b> ${esc(o.name || "No name")}</span><span class="o2">${C.rupees(C.orderTotal(o))}${C.isNum(o.deliveryP) ? "" : " + delivery"}</span><span class="o3"><span class="src ${o.source === "website" ? "web" : ""}">${o.source === "website" ? "Website" : "WhatsApp / phone"}</span> ${(C.STATUS[o.status] || {}).label || esc(o.status)}${PENDING.includes(o.status) && (C.STATUS[o.status] || {}).next ? ` · ${esc(C.STATUS[o.status].next)}` : ""}</span><span class="o4">${esc(fmtWhen(o.createdAt))}</span></button>`;
  const ordHtml = !loaded ? `<p class="empty">Loading…</p>` : (pend.length || recent.length) ? `<div class="olist">${pend.slice(0, 8).map(orow).join("")}${recent.map(orow).join("")}</div>` : `<p class="empty">No orders yet.</p>`;
  const ex = O.dash.exportAt, changed = ex ? O.products.filter((p) => p.published && p.status !== "pending" && ms(p.updatedAt) > ex).length : 0;
  const health = [
    [ex ? (changed ? "warn" : "ok") : "mute", "Website catalogue", ex ? `Last export ${ago(new Date(ex).toISOString(), now)}${changed ? `, ${changed} product${changed > 1 ? "s" : ""} changed since` : ", up to date"}` : "Never exported"],
    ["mute", "Store connection", "Not monitored yet. It arrives with the live backend."],
    ["mute", "Website sync", "No failed attempts recorded. Not tracked yet."],
    [s.holdsOver ? "bad" : s.holdsSoon ? "warn" : m.awaitingN ? "ok" : "mute", "Payments to check", m.awaitingN ? `${m.awaitingN} waiting${s.holdsOver ? `, ${s.holdsOver} past the hold time` : ""}${s.holdsSoon ? `, ${s.holdsSoon} ending within 30 min` : ""}` : "None waiting"],
    [s.gaps.length ? "bad" : s.firstMove ? "ok" : "mute", "Stock history", s.gaps.length ? `${s.gaps.length} place${s.gaps.length > 1 ? "s" : ""} where the rack and its history disagree` : s.firstMove ? "No gaps found" : "Nothing recorded yet"],
    [s.needsRecount.length ? "warn" : "ok", "Counts", s.needsRecount.length ? `${s.needsRecount.length} product${s.needsRecount.length > 1 ? "s" : ""} not counted in ${RECOUNT_AFTER_DAYS} days` : "Every product counted recently"],
  ].map(([t, l, d]) => `<div class="hrow">${dot(t)}<div><b>${esc(l)}</b><div class="muted">${esc(d)}</div></div></div>`).join("");
  const topHtml = s.top.length ? `<div class="tblwrap"><table class="tbl"><thead><tr><th>Product</th><th class="n">Pieces</th><th class="n">Sales</th></tr></thead><tbody>${s.top.slice(0, 8).map((t) => `<tr data-inv="${esc(t.id)}" style="cursor:pointer"><td>${esc(t.label || (byId(t.id) ? prodName(byId(t.id)) : t.id))}</td><td class="n">${t.n}</td><td class="n">${R(t.p)}</td></tr>`).join("")}</tbody></table></div>` : `<p class="empty">No sales recorded for this period.</p>`;
  const catMax = Math.max(1, ...Object.values(s.byCat).map((c) => c.p));
  const catHtml = Object.keys(s.byCat).length ? `<div class="bars">${Object.entries(s.byCat).sort((a, b) => b[1].p - a[1].p).map(([k, c]) => `<div class="bar" title="${esc(catLabel(k) || "No category")}: ${R(c.p)}"><span class="bl">${esc(catLabel(k) || "No category")}</span><span class="bt"><i style="width:${(100 * c.p / catMax).toFixed(1)}%"></i></span><span class="bn">${R(c.p)}</span></div>`).join("")}</div>` : `<p class="empty">No sales recorded for this period.</p>`;
  const sizeHtml = Object.keys(s.bySize).length ? `<div class="chips2">${Object.entries(s.bySize).sort((a, b) => b[1] - a[1]).map(([z, n]) => `<span class="sz1">${esc(C.sizeLabel(z))} <b>${n}</b></span>`).join("")}</div>` : `<p class="empty">No sales recorded for this period.</p>`;
  const slowHtml = s.slow.length ? `<div class="tblwrap"><table class="tbl"><thead><tr><th>Product</th><th class="n">On rack</th><th class="n">At MRP</th></tr></thead><tbody>${s.slow.slice(0, 8).map((x) => `<tr data-inv="${esc(x.p.id)}" style="cursor:pointer"><td>${esc(prodName(x.p))}<div class="muted">${x.last ? `last sold ${esc(ago(new Date(x.last).toISOString(), now))}` : "no sale recorded"}</div></td><td class="n">${x.n}</td><td class="n">${R(x.v)}</td></tr>`).join("")}</tbody></table></div>${s.slow.length > 8 ? `<p class="hint">${s.slow.length - 8} more.</p>` : ""}` : `<p class="empty ok">Everything in stock sold in the last ${SLOW_AFTER_DAYS} days.</p>`;
  const fin = `<div class="fin">
      <div class="frow"><span>Sales (gross)</span><b>${R(m.gross)}</b></div>
      <div class="frow"><span>Refunds sent</span><b>− ${R(m.refundedP)}</b></div>
      <div class="frow tot"><span>Net sales</span><b>${R(m.net)}</b></div>
      <div class="frow soft"><span>Discounts given</span><em>Not recorded: the price before the offer isn't saved with each sale.</em></div>
      <div class="frow soft"><span>Gross profit</span><em>Cost information required: no cost price is stored for products.</em></div>
    </div>
    <p class="mini">Not income yet</p>
    <div class="fin">
      <div class="frow"><span>Payments checked on orders</span><b>${R(m.paymentsVerifiedP)}</b></div>
      <div class="frow"><span>Waiting for payment (${m.awaitingN})</span><b>${R(m.awaitingP)}</b></div>
      <div class="frow"><span>Requests and agreed bills (${m.requestsN})</span><b>${R(m.requestsP)}</b></div>
      <div class="frow"><span>Refunds approved, not sent (${m.refundsPendingN})</span><b>${R(m.refundsPendingP)}</b></div>
    </div>`;
  const defs = `<ul class="defs"><li><b>Sales</b>: pieces that left the shop in the period, at the price charged. Counter sales count when recorded; online and WhatsApp orders count when handed to the rider. Requests and unpaid orders are never included.</li>
    <li><b>Net sales</b>: sales minus refunds actually sent in the period. Exchanges settled by a price difference are not included.</li>
    <li><b>Payments checked</b>: money staff confirmed in the UPI app on orders. Counter sales don't record how the customer paid, so cash and UPI at the counter can't be separated.</li>
    <li><b>Website</b> means the order came through the website; <b>WhatsApp / phone</b> means somebody typed it in.</li>
    <li><b>Low stock</b>: ${LOW_AT_MOST} or fewer free to sell in a size (rack count minus pieces held for orders).</li>
    <li><b>Needs a recount</b>: stock on the rack but no count, restock, capture, damage entry or correction in ${RECOUNT_AFTER_DAYS} days.</li>
    <li><b>Stock history gaps</b>: a change that does not start where the previous one ended, or a rack count different from the last change. These mean stock was altered outside the history or a record is missing.</li>
    <li><b>Customers</b> are counted from order phone numbers only. People who buy at the counter are not recorded.</li>
    <li>Sales are counted from ${s.firstMove ? esc(dayLabel(s.firstMove)) : "the first recorded stock change"}; earlier sales were not recorded in Stockroom.${s.movesTruncated ? " This view reads the latest 1,000 stock changes." : ""}</li></ul>`;
  const cust = `<div class="kpis small">${kpi("Customers who ordered", String(s.customers.unique), "online and typed-in orders")}${kpi("Ordered before", String(s.customers.repeat), s.customers.unique ? `${Math.round(100 * s.customers.repeat / s.customers.unique)}% of them` : "")}</div>`;
  pg.innerHTML = `<div class="dashhead"><div><h2>Dashboard</h2><p class="sub">${esc(rng.label)} · ${esc(dayLabel(rng.from))}${rng.from < sod(rng.to) ? ` to ${esc(dayLabel(rng.to))}` : ""}</p></div>
      <div class="chips" role="toolbar" aria-label="Period">${[["today", "Today"], ["7d", "7 days"], ["30d", "30 days"], ["custom", "Custom"]].map(([k, l]) => `<button class="chip" type="button" data-dr="${k}" aria-pressed="${O.dash.range === k}">${l}</button>`).join("")}</div></div>
    ${O.dash.range === "custom" ? `<div class="oprow dates"><label>From <input type="date" id="dFrom" value="${esc(O.dash.from)}"></label><label>To <input type="date" id="dTo" value="${esc(O.dash.to)}"></label></div>${Number.isFinite(localDate(O.dash.from)) && Number.isFinite(localDate(O.dash.to)) && localDate(O.dash.from) > localDate(O.dash.to) ? `<p class="note warn">The start date is after the end date. Showing the last 30 days.</p>` : ""}` : ""}
    ${!anyData && loaded ? `<p class="note">Nothing is recorded yet. Capture products, record sales and take orders, and this page fills in by itself.</p>` : ""}
    <div class="dgrid">
      ${panel("Needs attention", attHtml, "w12 att")}
      <div class="kpis w12">${kpis}</div>
      <div class="w8 dcol">
        ${panel("Sales by channel", noSales ? `<p class="empty">No sales recorded for this period.</p>` : chart(s.series, s.step))}
        ${panel("Orders", ordHtml, "", `<button type="button" class="x" data-go="orders">All orders</button>`)}
      </div>
      <div class="w4 dcol">
        ${panel("Inventory alerts", invHtml)}
        ${panel("Business health", health)}
      </div>
      ${section("perf", "Product performance", `<div class="two"><div><p class="mini">Best sellers by sales</p>${topHtml}</div><div><p class="mini">Not sold in ${SLOW_AFTER_DAYS} days, most money on the rack first</p>${slowHtml}</div></div><div class="two"><div><p class="mini">Sales by category</p>${catHtml}</div><div><p class="mini">Pieces sold by size</p>${sizeHtml}<p class="mini" style="margin-top:14px">Customers</p>${cust}</div></div>`, "w12")}
      ${section("fin", "Financial overview", fin, "w6")}
      ${section("defs", "How these numbers are counted", defs, "w6", false)}
      ${section("sheet", "Stock sheet and latest changes", `${X.dash.matrix()}<p class="mini" style="margin-top:18px">Latest stock changes</p>${O.moves.length ? `<div class="hist">${O.moves.slice(0, 10).map((mv) => `<div class="ev"><div><b>${esc(mv.label || mv.productId)}</b> · ${esc(X.KIND[mv.kind] || mv.kind)} · ${esc(C.sizeLabel(mv.size))}<div class="w">${esc(fmtWhen(mv.at))} · ${esc(mv.by || "")}</div></div><div class="d ${mv.change < 0 ? "minus" : "plus"}">${mv.change > 0 ? "+" : ""}${mv.change}</div></div>`).join("")}</div>` : `<p class="empty">No stock changes recorded yet.</p>`}`, "w12", false)}
    </div>`;
  bindChart(s);
  window.__dashState = s;
};

/* chart tooltip: pointer over a column (or a tap) shows that day's numbers */
function bindChart(s) {
  const svg = $("#dChart"), tip = $("#dTip"); if (!svg || !tip) return;
  const show = (e) => {
    const h = e.target.closest(".hit"); if (!h) { tip.hidden = true; return; }
    const b = s.series[+h.dataset.i], tot = b.counter + b.website + b.manual;
    tip.innerHTML = `<b>${esc(dayLabel(b.t0))}${s.step > 1 ? " week" : ""}</b><br>${CHAN.map(([k, l, c]) => `<span><i style="background:${c}"></i>${l} ${R(b[k])}</span>`).join("<br>")}<br><b>${R(tot)}</b> · ${b.orders} order${b.orders === 1 ? "" : "s"} received`;
    const box = svg.getBoundingClientRect(), r = h.getBoundingClientRect();
    tip.hidden = false;
    tip.style.left = Math.min(Math.max(8, r.left - box.left + r.width / 2 - 80), Math.max(8, box.width - 168)) + "px";
    tip.style.top = "4px";
  };
  svg.addEventListener("pointermove", show); svg.addEventListener("click", show); svg.addEventListener("pointerleave", () => { tip.hidden = true; });
}
let exportSub = false;
function watchExport() {
  if (exportSub || !O.db) return; exportSub = true;
  O.db.doc("config/export").onSnapshot((snap) => { O.dash.exportAt = (snap.exists && ms(snap.data().at)) || 0; if (O.tab === "dashboard") Pages.dashboard(); }, () => {});
}

/* ---------- stock sheet (unchanged behaviour: matrix + CSV) ---------- */
function matrixData() {
  const prods = O.products.filter((p) => p.status !== "pending").sort((a, b) => (catLabel(a.category) || "zz").localeCompare(catLabel(b.category) || "zz") || prodName(a).localeCompare(prodName(b)));
  const sizes = [...new Set(prods.flatMap((p) => C.sizeKeys(p)))].sort((a, b) => C.sizeRank(a) - C.sizeRank(b) || a.localeCompare(b));
  return {prods, sizes};
}
function matrix() {
  const {prods, sizes} = matrixData();
  if (!prods.length) return `<p class="empty">No products yet.</p>`;
  const q = (O.dash.mq || "").toLowerCase().trim();
  const shown = q ? prods.filter((p) => [prodName(p), p.article, p.brand, catLabel(p.category)].join(" ").toLowerCase().includes(q)) : prods;
  const cell = (p, z) => { const n = C.stockOf(p, z), h = C.held(O.orders, p.id, z); if (!C.sizeKeys(p).includes(z)) return `<td class="z">·</td>`; return `<td class="${n ? "" : "z"}">${n}${h ? `<small>${h} held</small>` : ""}</td>`; };
  return `<div class="pagehead" style="margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;gap:8px"><p class="label" style="margin:0">Stock sheet · pieces on the rack</p><button class="x" type="button" id="dlSheet">Download sheet (.csv)</button></div>
    <input id="mq" class="search" type="search" placeholder="Filter the sheet: product, article, brand…" value="${esc(O.dash.mq || "")}" autocomplete="off" style="margin-bottom:8px">
    <div class="scroll"><table class="matrix"><thead><tr><th class="nm">Product</th>${sizes.map((z) => `<th>${esc(C.sizeLabel(z) === "Free size" ? "Free" : z)}</th>`).join("")}<th>Total</th></tr></thead>
    <tbody>${shown.map((p) => `<tr data-inv="${esc(p.id)}" style="cursor:pointer"><td class="nm" title="${esc(prodName(p))}">${esc(prodName(p))}<small style="color:var(--ink-2)">${esc(p.article || "")}</small></td>${sizes.map((z) => cell(p, z)).join("")}<td><b>${C.totalStock(p)}</b></td></tr>`).join("") || `<tr><td class="nm" colspan="${sizes.length + 2}">Nothing matches.</td></tr>`}</tbody></table></div>
    <p class="hint">Tap a row to open it in Inventory. The download has every product, with MRP, offer and website status.</p>`;
}
X.dash = {matrix};
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

/* ---------- actions ---------- */
document.addEventListener("click", (e) => {
  if (O.tab !== "dashboard") return;
  const dr = e.target.closest("[data-dr]"); if (dr) { O.dash.range = dr.dataset.dr; if (dr.dataset.dr === "custom" && !O.dash.from) { const t = new Date(); O.dash.to = t.toISOString().slice(0, 10); O.dash.from = new Date(+t - 6 * DAY).toISOString().slice(0, 10); } Pages.dashboard(); return; }
  const a = e.target.closest("[data-att]"); if (a) { const it = window.__dashState.attention[+a.dataset.att]; if (!it) return; if (it.target.type === "tab") X.setTab(it.target.id, true); else { X.setTab("orders", true); X.openSheet({kind: "order", id: it.target.id}); } return; }
  const o = e.target.closest("[data-ord]"); if (o) { X.setTab("orders", true); X.openSheet({kind: "order", id: o.dataset.ord}); return; }
  const pr = e.target.closest("[data-prod]"); if (pr) { X.openSheet({kind: "product", id: pr.dataset.prod}); return; }
  const rc = e.target.closest("[data-recount]"); if (rc) { X.openSheet({kind: "product", id: rc.dataset.recount, mode: "stock", f: {why: "recount", n: {}}}); return; }
  const g = e.target.closest("[data-go]"); if (g) { X.setTab(g.dataset.go); return; }
  if (e.target.closest("#dlSheet")) { downloadSheet(); return; }
  const row = e.target.closest("tr[data-inv]"); if (row) X.openSheet({kind: "product", id: row.dataset.inv});
});
document.addEventListener("toggle", (e) => { const d = e.target; if (d && d.dataset && d.dataset.sec) O.dash.open[d.dataset.sec] = d.open; }, true);
document.addEventListener("change", (e) => { if (e.target.id === "dFrom" || e.target.id === "dTo") { O.dash[e.target.id === "dFrom" ? "from" : "to"] = e.target.value; Pages.dashboard(); } });
let mqT;
document.addEventListener("input", (e) => {
  if (e.target.id !== "mq") return;
  clearTimeout(mqT); mqT = setTimeout(() => { O.dash.mq = e.target.value; const pos = e.target.selectionStart; Pages.dashboard(); const i = document.getElementById("mq"); if (i) { i.focus(); try { i.setSelectionRange(pos, pos); } catch (_) {} } }, 250);
});
X.renderPage();
})();
