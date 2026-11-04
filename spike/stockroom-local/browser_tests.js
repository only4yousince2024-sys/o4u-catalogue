// Spike browser checks: real Chromium (Playwright) against the real, unmodified Stockroom page served by spike/stockroom-local/server.py.
//   node browser_tests.js main            all checks on freshly seeded INVENTED data
//   node browser_tests.js after-restart   re-checks what main stored, after the server AND PostgreSQL were restarted
// Prints one JSON object per check: {id, status: PASS|FAIL|BLOCKED, detail}. Never reports PASS without observing the thing it names.
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const { chromium } = require("playwright");

const BASE = process.env.SPIKE_BASE || "http://127.0.0.1:8780";
const HERE = __dirname;
const OUT = path.join(HERE, "reports");
const DL = path.join(OUT, "downloads");
const BLOBS = path.join(HERE, ".data", "blobs");
const STATE = path.join(OUT, "state.json");
fs.mkdirSync(DL, { recursive: true });
const results = [];
const PAGE_ERRORS = [];
const rec = (id, status, detail) => { results.push({ id, status, detail }); console.log(JSON.stringify({ id, status, detail })); };
async function check(id, fn) {
  try { const r = await fn(); if (r && r.blocked) rec(id, "BLOCKED", r.blocked); else rec(id, "PASS", (r && r.detail) || ""); }
  catch (e) { rec(id, "FAIL", String(e && e.message || e).split("\n")[0].slice(0, 400)); }
}
const ok = (c, m) => { if (!c) throw new Error(m); };
const api = async (m, p, b) => { const r = await fetch(BASE + p, { method: m, headers: b ? { "Content-Type": "application/json" } : {}, body: b ? JSON.stringify(b) : undefined }); return r.json(); };

function demoData() {   // the repo's own SYNTHETIC dataset (stockroom/dev/demo-data.js), evaluated outside a browser
  const win = {}; new Function("window", fs.readFileSync(path.join(HERE, "../../stockroom/dev/demo-data.js"), "utf8"))(win);
  return win.__demoDataset(Date.now());
}

async function jpeg(browser, label, color) {   // an invented photo: a coloured card with text, encoded as a real JPEG
  const pg = await browser.newPage();
  const b64 = await pg.evaluate(async ([label, color]) => {
    const c = document.createElement("canvas"); c.width = 900; c.height = 1200; const g = c.getContext("2d");
    g.fillStyle = color; g.fillRect(0, 0, 900, 1200); g.fillStyle = "#fff"; g.font = "bold 70px sans-serif"; g.fillText(label, 60, 300);
    for (let i = 0; i < 400; i++) { g.fillStyle = `hsl(${(i * 37) % 360} 60% 50%)`; g.fillRect((i * 53) % 880, 400 + ((i * 97) % 700), 20, 20); }   // some texture so the file is not tiny
    return c.toDataURL("image/jpeg", 0.85).split(",")[1];
  }, [label, color]);
  await pg.close();
  return Buffer.from(b64, "base64");
}
const file = (name, buf) => ({ name, mimeType: "image/jpeg", buffer: buf });

async function open(ctx, tab) {
  const page = await ctx.newPage();
  page.on("pageerror", e => PAGE_ERRORS.push(String(e).slice(0, 200)));
  await page.goto(BASE + "/stockroom");
  await page.waitForFunction(() => window.O4U_products && window.O4U_products().length >= 0 && document.querySelector("#list"), null, { timeout: 15000 });
  return page;
}
const loaded = (page, n) => page.waitForFunction(n => window.O4U_products && window.O4U_products().length === n, n, { timeout: 15000 });

async function main() {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ acceptDownloads: true, viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  const data = demoData();
  const ids = Object.keys(data.products);
  const state = {};

  await api("POST", "/api/_spike/reset");
  await api("POST", "/api/_spike/bulk", data);

  // ── 1 load invented products from persistent local storage
  let page;
  await check("1-load-products", async () => {
    page = await open(ctx);
    await loaded(page, ids.length);
    const rows = await page.locator("#list .row[data-open]").count();
    ok(rows > 0, "no product rows rendered");
    const firstId = await page.locator("#list .row[data-open]").first().getAttribute("data-open");
    ok(data.products[firstId], "first row is not a seeded product: " + firstId);
    ok((await page.locator("#list .row[data-open]").first().innerText()).includes(data.products[firstId].colour), "first row does not show its product's colour");
    const fromServer = (await api("GET", "/api/col/products")).docs.length;
    ok(fromServer === ids.length, `server has ${fromServer}`);
    return { detail: `${ids.length} invented products read from PostgreSQL, ${rows} rows rendered (first page)` };
  });

  // ── 2 edit survives reload
  const editId = ids.find(i => data.products[i].status === "ready");
  state.editId = editId;
  await check("2-edit-persists-reload", async () => {
    await page.locator(`#list .row[data-open="${editId}"]`).first().click();
    await page.waitForSelector("#dOffer");
    const note = "spike edit " + Date.now();
    await page.fill("#dOffer", "777"); await page.fill("#dNotes", note);
    await page.click("#dSave");
    await page.waitForFunction(([id, note]) => (window.O4U_products().find(p => p.id === id) || {}).notes === note, [editId, note], { timeout: 10000 });
    const doc = (await api("GET", `/api/doc/products/${editId}`)).data;
    ok(doc.notes === note && Number(doc.offerPrice) === 777, "server copy lacks the edit: " + JSON.stringify([doc.notes, doc.offerPrice]));
    await page.reload(); await loaded(page, ids.length);
    await page.locator(`#list .row[data-open="${editId}"]`).first().click();
    await page.waitForSelector("#dOffer");
    ok((await page.inputValue("#dNotes")) === note && (await page.inputValue("#dOffer")) === "777", "edit not shown after reload");
    state.note = note;
    return { detail: "edit saved by the page's own Save button, in the database, shown again after reload" };
  });

  // ── 3 photo upload through the page's real upload code, stored as a real file, shown, kept after reload
  const photo1 = await jpeg(browser, "INVENTED PHOTO 1", "#a33"), photo2 = await jpeg(browser, "INVENTED PHOTO 2", "#36a");
  await check("3-photo-upload-real-storage", async () => {
    await page.click("#detClose").catch(() => {});
    await page.locator(`#list .row[data-open="${editId}"]`).first().click();
    await page.waitForSelector("#inWeb", { state: "attached" });
    await page.setInputFiles("#inWeb", [file("one.jpg", photo1), file("two.jpg", photo2)]);
    await page.waitForFunction(id => ((window.O4U_products().find(p => p.id === id) || {}).webImages || []).length === 2, editId, { timeout: 20000 });
    const web = (await api("GET", `/api/doc/products/${editId}`)).data.webImages;
    const list = (await api("GET", "/api/assets")).assets;
    ok(web.length === 2 && list.length >= 2, `webImages ${web.length}, assets ${list.length}`);
    const onDisk = web.map(id => path.join(BLOBS, id));
    ok(onDisk.every(f => fs.existsSync(f) && fs.statSync(f).size > 5000), "photo files missing/too small on disk");
    const head = fs.readFileSync(onDisk[0]).subarray(0, 3).toString("hex");
    ok(head === "ffd8ff", "stored file is not a JPEG: " + head);
    await page.waitForSelector("#webgrid img");
    await page.waitForFunction(() => { const a = [...document.querySelectorAll("#webgrid img")]; return a.length === 2 && a.every(i => i.complete && i.naturalWidth > 0); }, null, { timeout: 15000 });
    const dims = await page.$$eval("#webgrid img", els => els.map(i => [i.naturalWidth, i.naturalHeight]));
    ok(dims.length === 2 && dims.every(d => d[0] > 100 && d[1] > 100), "images not displayed: " + JSON.stringify(dims));
    state.web = web;
    await page.reload(); await loaded(page, ids.length);
    await page.locator(`#list .row[data-open="${editId}"]`).first().click();
    await page.waitForSelector("#webgrid img");
    await page.waitForFunction(() => { const a = [...document.querySelectorAll("#webgrid img")]; return a.length === 2 && a.every(i => i.complete && i.naturalWidth > 0); }, null, { timeout: 15000 });
    const dims2 = await page.$$eval("#webgrid img", els => els.map(i => [i.complete, i.naturalWidth]));
    ok(dims2.length === 2 && dims2.every(d => d[0] && d[1] > 100), "images not displayed after reload: " + JSON.stringify(dims2));
    return { detail: `2 invented JPEGs uploaded via the page's file input -> files in .data/blobs (${onDisk.map(f => fs.statSync(f).size).join("+")} bytes) -> /_blob/<id> -> displayed ${dims[0].join("x")}; still displayed after reload` };
  });

  // ── 4 capture draft survives a killed tab
  await check("4-draft-recovery", async () => {
    await page.click("#detClose").catch(() => {});
    await page.click("#fab");
    await page.waitForSelector("#cam-photo", { state: "attached" });
    await page.setInputFiles("#cam-photo", file("shot.jpg", await jpeg(browser, "DRAFT PHOTO", "#2a7")));
    await page.waitForSelector("#cam-tag", { state: "attached" });
    await page.setInputFiles("#cam-tag", file("tag.jpg", await jpeg(browser, "DRAFT TAG", "#777")));
    await page.click('[data-plus="M"]'); await page.click('[data-plus="M"]');
    let draft;
    for (let i = 0; i < 40 && !draft; i++) {
      const d = (await api("GET", "/api/col/drafts")).docs.find(x => (x.data.photoAssetIds || []).length && (x.data.tagAssetIds || []).length);
      if (d) draft = d; else await new Promise(r => setTimeout(r, 250));
    }
    ok(draft, "the draft never received its two uploaded photos");
    state.draftId = draft.id;
    await page.close();                                   // the phone's camera app evicts the tab
    page = await open(ctx);
    await page.waitForSelector("#draftbar:not([hidden])", { timeout: 10000 });
    ok((await page.locator("#draftbar").innerText()).includes("Unfinished product"), "draft bar text");
    await page.click("#draftContinue");
    await page.waitForSelector("#capBody img");
    await page.waitForFunction(() => [...document.querySelectorAll("#capBody img")].filter(i => i.complete && i.naturalWidth > 100).length >= 2, null, { timeout: 10000 });
    const stock = (await api("GET", `/api/doc/drafts/${draft.id}`)).data.stock;
    ok(stock && stock.M === 2, "count of pieces lost: " + JSON.stringify(stock));
    return { detail: "draft id " + draft.id + ": new tab shows 'Unfinished product', Continue restores both photos (loaded from /_blob/) and the piece count" };
  });

  // ── 5 sample unavailable + manual entry still works
  await check("5-sample-unavailable-manual-entry", async () => {
    ok(await page.evaluate(async () => (await window.claude.use("sample")) === null), "sample must be null");
    ok((await page.locator("#spike-notice").innerText()).includes("NOT available"), "notice missing");
    ok((await page.locator("#doRead").count()) === 0, "a Read tag button is offered although sample is unavailable");
    ok((await page.locator("#doManual").count()) === 1 && (await page.locator("#doPending").count()) === 1, "manual / save-for-later buttons missing");
    await page.click("#doManual");
    await page.waitForSelector("#fArt");
    await page.fill("#fArt", "SPK900"); await page.fill("#fColour", "Spike Teal"); await page.fill("#fType", "Spike Test Tee");
    await page.selectOption("#fCat", "tshirts");
    await page.fill("#sz0s", "M"); await page.fill("#sz0m", "899");
    await page.waitForSelector("#doSave:not([disabled])");
    await page.click("#doSave");
    const id = "spk900-spike-teal";
    let doc;
    for (let i = 0; i < 40 && !doc; i++) { const r = await api("GET", `/api/doc/products/${id}`); if (r.exists) doc = r.data; else await new Promise(r => setTimeout(r, 250)); }
    ok(doc, "manual product not saved");
    ok(doc.article === "SPK900" && doc.refPhoto && (doc.stock || {}).M === 2, "saved record incomplete: " + JSON.stringify({ a: doc.article, r: !!doc.refPhoto, s: doc.stock }));
    state.manualId = id;
    return { detail: "no Read-tag button; spike notice visible; product typed by hand saved with photo and stock (id " + id + "); the page does not show its own 'unavailable' message, the shim's notice does" };
  });

  // ── 6 CSV download
  await check("6-csv-download", async () => {
    await page.reload(); await loaded(page, ids.length + 1);
    await page.click('[data-tab="dashboard"]');
    await page.waitForSelector("#dlSheet", { timeout: 10000 });
    const [dl] = await Promise.all([page.waitForEvent("download", { timeout: 10000 }), page.click("#dlSheet")]);
    const f = path.join(DL, dl.suggestedFilename()); await dl.saveAs(f);
    const t = fs.readFileSync(f, "utf8");
    ok(t.charCodeAt(0) === 0xfeff, "no BOM");
    state.csv = f;
    state.csvDb = Object.fromEntries((await api("GET", "/api/col/products")).docs.map(d => [d.id, Object.values(d.data.stock || {}).reduce((a, v) => a + Number(v || 0), 0)]));
    return { detail: `${dl.suggestedFilename()} ${t.length} chars (parsed by the orchestrator)` };
  });

  // ── 7 ZIP downloads (website images, all photos of one product, full backup)
  await check("7a-zip-website-images", async () => {
    await page.click('[data-tab="capture"]');
    await page.waitForSelector("#list");
    await page.locator(`#list .row[data-open="${editId}"]`).first().click();
    await page.waitForSelector("#dlOne");
    const [dl] = await Promise.all([page.waitForEvent("download", { timeout: 20000 }), page.click("#dlOne")]);
    const f = path.join(DL, dl.suggestedFilename()); await dl.saveAs(f); state.zipWeb = f;
    return { detail: dl.suggestedFilename() + " (validated by the orchestrator)" };
  });
  await check("7b-zip-full-backup", async () => {
    await page.click("#detClose").catch(() => {});
    await page.click("#bkGo");
    const dl = await page.waitForEvent("download", { timeout: 60000 });
    const f = path.join(DL, dl.suggestedFilename()); await dl.saveAs(f); state.zipBackup = f;
    state.counts = {};
    for (const c of ["products", "stockmoves", "orders", "refunds", "drafts", "config"]) state.counts[c] = (await api("GET", `/api/col/${c}`)).docs.length;
    state.assetsAtBackup = (await api("GET", "/api/assets")).assets.length;
    return { detail: dl.suggestedFilename() + " (validated by the orchestrator)" };
  });
  await page.close();

  // ── in-page camera code path with Chromium's FAKE video device (a generated test pattern; NOT a phone camera)
  await check("5b-live-camera-code-path-fake-device", async () => {
    const fb = await chromium.launch({ args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"] });
    try {
      const c2 = await fb.newContext({ permissions: ["camera"], viewport: { width: 390, height: 844 } });
      const p = await open(c2); await loaded(p, ids.length + 1);
      const before = new Set((await api("GET", "/api/col/drafts")).docs.map(d => d.id));
      await p.click("#fab"); await p.waitForSelector('label[for="cam-photo"]');
      await p.click('label[for="cam-photo"]');
      await p.waitForSelector("#live:not([hidden])", { timeout: 5000 });
      await p.waitForFunction(() => { const v = document.querySelector("#liveVid"); return v && v.videoWidth > 0; }, null, { timeout: 10000 });
      await p.click("#liveShoot");
      let d; for (let i = 0; i < 40 && !d; i++) { d = (await api("GET", "/api/col/drafts")).docs.find(x => !before.has(x.id) && (x.data.photoAssetIds || []).length); if (!d) await new Promise(r => setTimeout(r, 250)); }
      ok(d, "the shot taken from the live view never reached storage");
      const a = (await api("GET", "/api/assets")).assets.find(x => x.id === d.data.photoAssetIds[0]);
      ok(a && a.bytes > 1000, "no stored photo for the live shot");
      await api("DELETE", `/api/doc/drafts/${d.id}`);
      return { detail: `fake device stream ${await p.evaluate(() => document.querySelector("#liveVid") && document.querySelector("#liveVid").videoWidth)}px wide -> live shot uploaded (${a.bytes} bytes). This proves the page's getUserMedia code runs on its own host; it says nothing about a real phone camera, focus, torch or Android tab eviction` };
    } finally { await fb.close(); }
  });

  // a draft that stays unfinished, to be checked after the restart
  await check("4b-leave-a-draft-for-restart", async () => {
    const p2 = await open(ctx); await loaded(p2, ids.length + 1);
    await p2.click("#fab"); await p2.waitForSelector("#cam-photo", { state: "attached" });
    await p2.setInputFiles("#cam-photo", file("shot2.jpg", await jpeg(browser, "RESTART DRAFT", "#c60")));
    let d; for (let i = 0; i < 40 && !d; i++) { d = (await api("GET", "/api/col/drafts")).docs.find(x => (x.data.photoAssetIds || []).length); if (!d) await new Promise(r => setTimeout(r, 250)); }
    ok(d, "draft did not receive its photo"); state.draft2 = d.id; await p2.close();
    return { detail: "unfinished draft " + d.id + " left in the database" };
  });

  // ── 8 concurrent stock writes from two "phones" through the app's own moveStock (with and without the lease)
  async function race(nolock) {
    const pid = ids.filter(i => i !== editId)[nolock ? 4 + race.n++ : 3];
    await api("PATCH", `/api/doc/products/${pid}`, { stock: { M: 60 }, inStock: true });
    const before = (await api("GET", "/api/col/stockmoves")).docs.filter(d => d.data.productId === pid).length;
    const mk = async () => {
      const c = await browser.newContext(); const p = await c.newPage();
      await p.addInitScript(v => localStorage.setItem("spike_nolock", v), nolock ? "1" : "0");
      await p.goto(BASE + "/stockroom"); await p.waitForFunction(() => window.O4U_ops && window.O4U_ops.moveStock && window.O4U_products().length > 0);
      await p.waitForFunction(() => window.O4U_ops.O.db);
      return p;
    };
    const A = await mk(), B = await mk();
    const run = (p, n) => p.evaluate(async ([pid, n]) => {
      let okc = 0, busy = 0, other = [];
      for (let i = 0; i < n; i++) {
        try { await window.O4U_ops.moveStock([{ productId: pid, size: "M", change: -1 }], { kind: "sale" }, false); okc++; }
        catch (e) { if (e && e.code === "busy") busy++; else other.push(String(e && e.message)); }
      }
      return { okc, busy, other };
    }, [pid, n]);
    const [ra, rb] = await Promise.all([run(A, 15), run(B, 15)]);
    await new Promise(r => setTimeout(r, 500));
    const stock = (await api("GET", `/api/doc/products/${pid}`)).data.stock.M;
    const moves = (await api("GET", "/api/col/stockmoves")).docs.filter(d => d.data.productId === pid).length;
    await A.context().close(); await B.context().close();
    const done = ra.okc + rb.okc, moves0 = before;
    return { pid, ra, rb, done, stock, moves, expectedStock: 60 - done, lost: stock - (60 - done), ledgerGap: moves - before - done, added: moves - before };
  }
  race.n = 0;
  await check("8a-concurrent-stock-with-lease", async () => {
    const r = await race(false);
    state.race = r;
    ok(r.stock === r.expectedStock, `LOST UPDATES: stock ${r.stock}, expected ${r.expectedStock} after ${r.done} successful moves (${JSON.stringify([r.ra, r.rb])})`);
    ok(r.ledgerGap === 0, `ledger rows added ${r.moves - 0} vs ${r.done} successful moves (gap ${r.ledgerGap})`);
    return { detail: `phone A ${JSON.stringify(r.ra)}, phone B ${JSON.stringify(r.rb)}; final stock ${r.stock} = 60 - ${r.done}; ${r.added} ledger rows added` };
  });
  await check("8b-same-race-without-lease-is-detected", async () => {
    let seen = null;
    for (let k = 0; k < 4 && !seen; k++) { const r = await race(true); if (r.lost !== 0 || r.ledgerGap !== 0) seen = r; state.raceNoLock = r; }
    ok(seen, "the race WITHOUT a lease lost no updates in 4 rounds, so this test cannot show the lease matters");
    return { detail: `without the lease: stock ${seen.stock} vs expected ${seen.expectedStock} (lost ${seen.lost}); ledger gap ${seen.ledgerGap}` };
  });

  await check("9-no-page-errors", async () => { ok(PAGE_ERRORS.length === 0, "uncaught page errors: " + PAGE_ERRORS.slice(0, 3).join(" | ")); return { detail: "no uncaught JavaScript errors in any page used above" }; });
  fs.writeFileSync(STATE, JSON.stringify(state, null, 1));
  await browser.close();
}

async function afterRestart() {
  const state = JSON.parse(fs.readFileSync(STATE, "utf8"));
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  await check("10-after-restart-products-and-edit", async () => {
    const page = await open(ctx); await page.waitForFunction(() => window.O4U_products().length >= 15, null, { timeout: 15000 });
    await page.locator(`#list .row[data-open="${state.editId}"]`).first().click(); await page.waitForSelector("#dNotes");
    ok((await page.inputValue("#dNotes")) === state.note && (await page.inputValue("#dOffer")) === "777", "edit lost after server+PostgreSQL restart");
    await page.waitForSelector("#webgrid img");
    await page.waitForFunction(() => [...document.querySelectorAll("#webgrid img")].every(i => i.complete && i.naturalWidth > 100) && document.querySelectorAll("#webgrid img").length === 2);
    return { detail: "edit and both photos survived a restart of the spike server and of PostgreSQL" };
  });
  await check("11-after-restart-draft", async () => {
    const page = await open(ctx);
    await page.waitForSelector("#draftbar:not([hidden])", { timeout: 10000 });
    await page.click("#draftContinue"); await page.waitForSelector("#capBody img");
    await page.waitForFunction(() => [...document.querySelectorAll("#capBody img")].some(i => i.complete && i.naturalWidth > 100), null, { timeout: 10000 });
    return { detail: "draft " + state.draft2 + " offered again after the restart and its photo loads from disk" };
  });
  await browser.close();
}

(process.argv[2] === "after-restart" ? afterRestart() : main()).then(() => {
  fs.writeFileSync(path.join(OUT, `browser_${process.argv[2] || "main"}.json`), JSON.stringify(results, null, 1));
  process.exit(results.some(r => r.status === "FAIL") ? 1 : 0);
}).catch(e => { console.error(e); process.exit(2); });
