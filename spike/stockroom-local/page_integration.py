"""Part 3 of the isolated page copy: Capture's quantities + the product stock editor through ONE server call, visible save failures, and what is switched off.

Imported by patch_app.py. Every anchor in EDITS must occur EXACTLY once in the (already moveStock-patched) original or patch_app.py writes nothing.
The original stockroom/ files are never touched.
"""

HELPERS = r"""/* INTEGRATED COPY: Capture and the stock editor save through ONE server call (catalogue rows + stock + ledger in one transaction). */
function hashStr(t){ let h = 5381; for (let i = 0; i < t.length; i++) h = ((h << 5) + h + t.charCodeAt(i)) | 0; return (h >>> 0).toString(36); }
function saveFriendly(e){
  const m = (e && e.message) || "";
  if (e && e.friendly) return e.friendly;
  if (e && e.code === "stale") return "Nothing was saved: the stock changed while you were editing (" + m + "). Close this and open the product again to see the latest numbers.";
  if (e && e.code === "unavailable") return "Nothing was saved: no connection. Check the network and tap Save again.";
  return "Nothing was saved: " + (m || "unknown error") + ".";
}
async function catalogueSave(args){
  const stockApi = window.claude && typeof window.claude.use === "function" ? await window.claude.use("stock") : null;
  if (!stockApi || !stockApi.save) { const e = new Error("stock saving is not available in this view"); e.friendly = "Nothing was saved: stock saving is not available in this view."; throw e; }
  try { return await stockApi.save(args); } catch (e) { e.friendly = saveFriendly(e); throw e; }
}
function capturePayload(f, c, existing){
  const seen = (existing && existing.stock) || {};
  const expectOf = (z) => Object.entries(seen).filter(([k]) => String(k).trim().toUpperCase() === String(z).trim().toUpperCase()).reduce((a, [, n]) => a + (Number(n) || 0), 0);
  const items = {};
  const priced = f.sizes.filter(s => s.size || s.mrp || s.barcode).map(s => ({size: String(s.size).trim(), mrp: s.mrp === "" ? null : Number(String(s.mrp).replace(/[^0-9.]/g, "")) || null, barcode: String(s.barcode).trim()}));
  for (const s of priced) if (s.size) items[s.size.toUpperCase()] = {size: s.size, mrp: s.mrp, barcode: s.barcode, keep: true};
  for (const [z, n] of Object.entries(c.stock)) { const u = String(z).trim().toUpperCase(); const it = items[u] || (items[u] = {size: z, mrp: null, barcode: ""}); it.size = z; it.qty = Number(n) || 0; delete it.keep; }
  const prices = priced.map(s => s.mrp).filter(Boolean);
  const base = prices.length ? Math.min(...prices) : null;
  if (!existing && !base) { const e = new Error("price needed"); e.friendly = "Nothing was saved: enter the price (MRP) of at least one size. Every product needs a price before it can go into the shared stock."; throw e; }
  const sizes = Object.values(items).map(it => {
    const exp = expectOf(it.size);
    const o = {size: it.size, qty: it.keep ? exp : it.qty, expect: exp};
    if (it.barcode) o.barcode = it.barcode;
    if (it.mrp && base && Math.round(it.mrp * 100) !== Math.round(base * 100)) o.price_paise = Math.round(it.mrp * 100);
    return o;
  });
  const product = existing ? null : {article: f.article.trim(), name: (f.type || "").trim() || f.article.trim(), brand: f.brand.trim(), category: f.category, colour: f.colour.trim(), price_paise: Math.round(base * 100)};
  return {product, sizes};
}
"""

SAVE_HEAD = 'async function saveProduct(){\n  const c = S.cap; const f = c.form;\n  if (!S.db) { c.error = "Saving isn\'t available in this view."; renderCapture(); return; }\n'

EDITS = [
    # 1. helpers + the "other colours" guard at the top of saveProduct
    (SAVE_HEAD,
     HELPERS + SAVE_HEAD +
     '  if (c.colours.length) { c.error = "Other colours can\'t be saved in this build. Save this colour first, then capture the next colour as its own product."; renderCapture(); return; }\n'),
    # 2. the shared stock first; if it refuses, no product document is written
    ('    const ref = S.db.collection("products").doc(id);\n    if (existing) {\n      const merged = [...(existing.sizes || [])];\n',
     '    const ref = S.db.collection("products").doc(id);\n'
     '    const cp = capturePayload(f, c, existing);      // throws a plain-language message when the price is missing\n'
     '    if (cp.sizes.length) {\n'
     '      c.salt = c.salt || Math.random().toString(36).slice(2, 10);      // same content = same key, so a second tap after a lost answer replays instead of repeating\n'
     '      await catalogueSave({key: "cs-" + c.salt + "-" + hashStr(JSON.stringify([id, cp.sizes, cp.product])), productId: id, product: cp.product, sizes: cp.sizes,\n'
     '        meta: {kind: "capture", by: "capture", label: [f.colour, f.type].filter(Boolean).join(" "), article: f.article, category: f.category}});\n'
     '    }\n'
     '    if (existing) {\n      const merged = [...(existing.sizes || [])];\n'),
    # 3. stock never rides along with the document writes
    ('        stock: {...(existing.stock || {}), ...c.stock},\n', ''),
    ('sizes, flags: f.flags, notes: [f.notes.trim(), (c.note || "").trim()].filter(Boolean).join("\\n"), stock: {...c.stock},',
     'sizes, flags: f.flags, notes: [f.notes.trim(), (c.note || "").trim()].filter(Boolean).join("\\n"),'),
    # 4. show why a save failed
    ('    c.error = e && e.code && /upload|too_large|quota|rate|not_granted|capability|store|upstream_auth/.test(e.code) ? uploadMsg(e) : "Saving failed. Check your connection and tap Save again.";',
     '    c.error = e && e.friendly ? e.friendly : e && e.code && /upload|too_large|quota|rate|not_granted|capability|store|upstream_auth/.test(e.code) ? uploadMsg(e) : "Saving failed. Check your connection and tap Save again.";'),
    # 5. products waiting for Claude carry stock in a document: not connected
    ('async function savePending(){\n  const c = S.cap;\n  if (!S.db) { c.error = "Saving isn\'t available in this view."; renderCapture(); return; }\n',
     'async function savePending(){\n  const c = S.cap;\n  if (!S.db) { c.error = "Saving isn\'t available in this view."; renderCapture(); return; }\n'
     '  c.error = "Saving a product for Claude to read later is not available in this build: its stock is not connected to the shared stock. Use \\"Type the tag details myself\\"."; renderCapture(); return;\n'),
    # 6. the stock editor remembers what the person saw, and can show an error
    ('  S.editStock = {id: p.id, stock: {...(p.stock || {})}, mrp};', '  S.editStock = {id: p.id, stock: {...(p.stock || {})}, seen: {...(p.stock || {})}, mrp, mrp0: {...mrp}, error: ""};'),
    ('    <div class="btnrow" style="margin-top:10px">\n      <button class="btn primary" type="button" id="eSave">Save stock</button>',
     '    ${ed.error ? `<p class="hint" role="alert" style="color:#b42318;font-weight:600">${esc(ed.error)}</p>` : ""}\n    <div class="btnrow" style="margin-top:10px">\n      <button class="btn primary" type="button" id="eSave">Save stock</button>'),
    # 7. saving the stock editor: recounts with the number the person saw
    ('''  const total = Object.values(stock).reduce((a, b) => a + b, 0);
  for (const k of Object.keys(p.stock || {})) if (!(k in stock)) stock[k] = 0;
  S.editStock = null;
  if (p.status === "pending") { await patch(p.id, {stock, inStock: total > 0}, "Stock updated"); renderDetail(); return; }
  await patch(p.id, {stock, sizes, inStock: total > 0}, total ? "Stock updated" : "Stock updated — marked out of stock");
  try { window.dispatchEvent(new CustomEvent("o4u:stockedit", {detail: {id: p.id, before: p.stock || {}, after: stock, kind: "edit"}})); } catch (_) {}
  renderDetail();
}''',
     '''  if (p.status === "pending") { ed.error = "Stock for a product that is waiting for Claude can't be changed in this build."; refreshStockEditor(p); return; }
  const seen = ed.seen || p.stock || {};
  const items = [];
  for (const z of new Set([...Object.keys(seen), ...Object.keys(ed.stock)])) {
    const qty = Number(ed.stock[z]) || 0, exp = Number(seen[z]) || 0;
    if (qty !== exp) items.push({size: z, qty, expect: exp});
  }
  // PRICES: an edited MRP is sent to the shared catalogue together with any stock change (one transaction), with the price the person saw
  let prices = null;
  const m0 = ed.mrp0 || {};
  const num = (v) => { const r = String(v || "").replace(/[^0-9.]/g, ""); return r ? Number(r) : null; };
  if (Object.keys(ed.mrp).some(k => String(ed.mrp[k] || "").trim() !== String(m0[k] || "").trim())) {
    const vals = Object.values(ed.mrp).map(num).filter(Boolean);
    if (!vals.length) { ed.error = "Nothing was saved: enter a price (MRP) for at least one size."; refreshStockEditor(p); return; }
    const was = Object.values(m0).map(num).filter(Boolean);
    const base = Math.round(Math.min(...vals) * 100);
    const sp = {};
    for (const [k, v] of Object.entries(ed.mrp)) { const n = num(v); if (n) sp[k] = Math.round(n * 100) !== base ? Math.round(n * 100) : null; }
    prices = {expect_price_paise: was.length ? Math.round(Math.min(...was) * 100) : null, price_paise: base, size_prices: sp};
  }
  if (items.length || prices) {
    ed.salt = ed.salt || Math.random().toString(36).slice(2, 10);      // same content = same key (a retry replays); a changed number is a new key
    try { await catalogueSave({key: "se-" + ed.salt + "-" + hashStr(JSON.stringify([p.id, items, prices])), productId: p.id, sizes: items, prices,
      meta: {kind: "edit", by: "stock editor", label: [p.colour, p.type].filter(Boolean).join(" "), article: p.article || "", category: p.category || ""}}); }
    catch (e) { ed.error = saveFriendly(e); toast("Nothing was saved"); refreshStockEditor(p); return; }      // the editor stays open with the message
  }
  try { await S.db.collection("products").doc(p.id).update({sizes, updatedAt: new Date().toISOString()}); }      // product details only: stock is never part of this write
  catch (e) { ed.error = "The shared stock was saved, but this page could not be updated. Tap Save stock again."; refreshStockEditor(p); return; }
  S.editStock = null;
  toast(items.length || prices ? "Saved" : "Nothing to change");
  renderDetail();
}'''),
    # 8. the history line is written by the server in the same transaction: the page must not log it again
    ('  const d = e.detail || {}; if (!O.db || !d.id) return;\n  const p = byId(d.id) || {};\n',
     '  const d = e.detail || {}; if (!O.db || !d.id) return;\n  if (d.kind === "capture" || d.kind === "edit") return;      // INTEGRATED COPY: the server wrote this history line in the same transaction\n  const p = byId(d.id) || {};\n'),
    # 8b. "In stock" is worked out from the pieces on the rack; a hand-set flag would be dropped, so say so instead
    ('  if (t.id === "tStock") patch(p.id, {inStock: t.checked}, t.checked ? "Marked in stock" : "Marked out of stock");\n',
     '  if (t.id === "tStock") { toast("In stock is worked out from the pieces on the rack. Change the pieces with Edit stock."); renderDetail(); return; }      // INTEGRATED COPY\n'),
    # 9. orders and exchanges are not connected to the shared stock (holds live in page documents): off
    ('  if (!TABS.includes(t)) t = "capture";\n', '  if (!TABS.includes(t)) t = "capture";\n  if (t === "orders" || t === "exchanges") t = "inventory";      // INTEGRATED COPY: not connected to the shared stock yet\n'),
    ('  const b = e.target.closest(".tab[data-tab]"); if (!b) return;\n',
     '  const b = e.target.closest(".tab[data-tab]"); if (!b) return;\n'
     '  if (b.dataset.tab === "orders" || b.dataset.tab === "exchanges") { toast("Orders and exchanges are switched off in this build: holds are not connected to the shared stock yet."); return; }\n'),
]

GREY_OUT = """<script>document.querySelectorAll('.tab[data-tab="orders"],.tab[data-tab="exchanges"]').forEach(function(b){b.setAttribute("aria-disabled","true");b.title="Switched off in this build";b.style.opacity=".4";});</script></body>"""
