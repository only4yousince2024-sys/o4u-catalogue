// Browser checks for the ATOMIC stock path: the isolated page copy (/stockroom?v=atomic) calling the app's own moveStock().
//   node atomic_tests.js        (server must be running; run_spike.py does that)  -> prints {id,status,detail} lines
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");
const BASE = process.env.SPIKE_BASE || "http://127.0.0.1:8780";
const OUT = path.join(__dirname, "reports");
const results = [];
const rec = (id, status, detail) => { results.push({ id, status, detail }); console.log(JSON.stringify({ id, status, detail })); };
async function check(id, fn) { try { const r = await fn(); rec(id, "PASS", (r && r.detail) || ""); } catch (e) { rec(id, "FAIL", String(e && e.message || e).split("\n")[0].slice(0, 400)); } }
const ok = (c, m) => { if (!c) throw new Error(m); };
const api = async (m, p, b) => { const r = await fetch(BASE + p, { method: m, headers: b ? { "Content-Type": "application/json" } : {}, body: b ? JSON.stringify(b) : undefined }); return r.json(); };
const sleep = ms => new Promise(r => setTimeout(r, ms));

function product(id, M) {
  return { id, article: id.toUpperCase(), brand: "", category: "tshirts", type: "Atomic Test Tee", colour: "Teal", sizes: [{ size: "M", mrp: 999 }], stock: { M }, inStock: M > 0,
           published: true, status: "ready", flags: [], notes: "", webImages: [], createdAt: new Date().toISOString(), updatedAt: new Date().toISOString() };
}
const events = async (pid) => (await api("GET", `/api/_spike/ledger/${pid}`));    // {on_hand, events:[{kind,d_on_hand,reason}], docs}

async function phone(browser, nolock) {
  const c = await browser.newContext(); const p = await c.newPage();
  await p.addInitScript(v => localStorage.setItem("spike_nolock", v), nolock ? "1" : "0");
  await p.goto(BASE + "/stockroom?v=atomic");
  await p.waitForFunction(() => window.O4U_ops && window.O4U_ops.moveStock && window.O4U_ops.O.db && window.O4U_products().length > 0, null, { timeout: 15000 });
  return p;
}
const sell = (p, pid, n = 1, kind = "sale", meta = {}) => p.evaluate(async ([pid, n, kind, meta]) => {
  try { await window.O4U_ops.moveStock([{ productId: pid, size: "M", change: -n }], { kind, ...meta }, true); return { ok: true }; }
  catch (e) { return { ok: false, code: e && e.code, msg: String(e && e.message) }; }
}, [pid, n, kind, meta]);

(async () => {
  const browser = await chromium.launch();
  await api("POST", "/api/_spike/reset");
  const seed = {};
  for (let i = 0; i < 6; i++) seed["atomic-final-" + i] = product("atomic-final-" + i, 1);
  seed["atomic-main"] = product("atomic-main", 60); seed["atomic-lost"] = product("atomic-lost", 10); seed["atomic-delay"] = product("atomic-delay", 10);
  await api("POST", "/api/_spike/bulk?relational=1", { products: seed });

  await check("A1-two-phones-sell-the-final-piece", async () => {
    const A = await phone(browser), B = await phone(browser);
    const seen = [];
    for (let i = 0; i < 6; i++) {
      const pid = "atomic-final-" + i;
      await Promise.all([A.waitForFunction(p => window.O4U_products().some(x => x.id === p), pid), B.waitForFunction(p => window.O4U_products().some(x => x.id === p), pid)]);
      const [ra, rb] = await Promise.all([sell(A, pid), sell(B, pid)]);
      const wins = [ra, rb].filter(r => r.ok).length;
      const led = await events(pid);
      ok(wins === 1, `round ${i}: ${wins} phones sold the last piece: ${JSON.stringify([ra, rb])}`);
      const loser = [ra, rb].find(r => !r.ok); ok(loser.code === "short" && /free|Only/.test(loser.msg), "loser should get the app's 'short' message: " + JSON.stringify(loser));
      ok(led.on_hand === 0 && led.events.filter(e => e.kind === "sale").length === 1 && led.docs === 1, `round ${i}: on_hand ${led.on_hand}, sale rows ${led.events.filter(e => e.kind === "sale").length}, history copies ${led.docs}`);
      seen.push(loser.msg);
    }
    await A.context().close(); await B.context().close();
    return { detail: `6 rounds, two real pages calling the app's moveStock at the same instant: exactly one succeeded each time, stock 0, one ledger row, one history copy; loser saw: "${seen[0]}"` };
  });

  await check("A2-lost-response-then-retry-deducts-once", async () => {
    const P = await phone(browser);
    let dropped = 0;
    await P.route("**/api/stock/moves", async route => { if (dropped++ === 0) { await route.fetch(); await route.abort("connectionreset"); } else await route.continue(); });   // the server commits, the answer never arrives
    const r = await sell(P, "atomic-lost", 2);
    const calls = await P.evaluate(() => window.__spikeStockCalls);
    const led = await events("atomic-lost");
    ok(r.ok, "the user's action should succeed after the automatic retry: " + JSON.stringify(r));
    ok(dropped >= 2 && calls >= 2, `the request was not sent twice (route saw ${dropped}, page counted ${calls})`);
    ok(led.on_hand === 8 && led.events.filter(e => e.kind === "sale").length === 1 && led.docs === 1, `on_hand ${led.on_hand} (want 8), sale rows ${led.events.filter(e => e.kind === "sale").length}, history copies ${led.docs}`);
    await P.context().close();
    return { detail: `response dropped after the server committed; the page retried (${calls} requests, same key); stock 10 -> 8 once, 1 ledger row, 1 history copy` };
  });

  await check("A3-delayed-holder-cannot-overwrite-newer-stock", async () => {
    const A = await phone(browser), B = await phone(browser);
    // A takes the page's own lease on the product, then is slow: its request is held back 2.5 s, longer than the lease (300 ms) lasts
    await A.evaluate(async pid => { window.__a = await window.O4U_ops.O.db.collection("products").doc(pid).acquire({ holder: "phone-A", ttlMs: 300 }); }, "atomic-delay");
    ok(await A.evaluate(() => window.__a.acquired), "A should hold the lease first");
    await A.route("**/api/stock/moves", async route => { await sleep(2500); await route.continue(); });
    const aSale = sell(A, "atomic-delay", 1);
    await sleep(500);                                                             // A's lease has expired; B takes it and sells meanwhile
    const lease = await B.evaluate(async pid => (await window.O4U_ops.O.db.collection("products").doc(pid).acquire({ holder: "phone-B", ttlMs: 5000 })).acquired, "atomic-delay");
    ok(lease, "B should get the expired lease");
    const rb = await sell(B, "atomic-delay", 1);
    ok(rb.ok, "B's sale: " + JSON.stringify(rb));
    ok((await events("atomic-delay")).on_hand === 9, "B's sale is in");
    const ra = await aSale;
    ok(ra.ok, "A's delayed sale should still apply as a delta: " + JSON.stringify(ra));
    ok((await events("atomic-delay")).on_hand === 8, "stock must be 10 - 1 - 1 = 8: A's late request must not overwrite B's");
    // A counted the rack when it held 10 and sends that recount late: refused, nothing changes
    const rc = await B.evaluate(async () => { try { await window.O4U_ops.moveStock([{ productId: "atomic-delay", size: "M", change: -2 }], { kind: "recount", expect: { M: 10 } }, true); return { ok: true }; } catch (e) { return { ok: false, code: e.code, msg: e.message }; } });
    ok(!rc.ok && rc.code === "stale" && /changed while counting/.test(rc.msg), "stale recount must be refused: " + JSON.stringify(rc));
    const led = await events("atomic-delay");
    ok(led.on_hand === 8 && led.events.filter(e => e.kind === "recount").length === 0, "refused recount left no trace");
    await A.context().close(); await B.context().close();
    return { detail: "A's lease expired and its request arrived 2.5 s late: B's sale kept, A's delta added on top (10 -> 9 -> 8); A's stale recount (saw 10) refused with 'changed while counting'; no recount ledger row" };
  });

  await check("A4-two-phones-no-lease-contention-30-sales", async () => {
    const A = await phone(browser, true), B = await phone(browser, true);       // leases switched OFF: correctness must not depend on them
    const run = (p) => p.evaluate(async () => { let okc = 0, err = []; for (let i = 0; i < 15; i++) { try { await window.O4U_ops.moveStock([{ productId: "atomic-main", size: "M", change: -1 }], { kind: "sale" }, true); okc++; } catch (e) { err.push(e.code + ":" + e.message); } } return { okc, err }; });
    const [ra, rb] = await Promise.all([run(A), run(B)]);
    const led = await events("atomic-main");
    ok(ra.okc + rb.okc === 30 && ra.err.length + rb.err.length === 0, "all 30 sales should succeed: " + JSON.stringify([ra, rb]));
    ok(led.on_hand === 30 && led.events.filter(e => e.kind === "sale").length === 30 && led.docs === 30, `on_hand ${led.on_hand}, ledger ${led.events.filter(e => e.kind === "sale").length}, copies ${led.docs}`);
    // the page sees the database number (live push), not a stale one
    await A.waitForFunction(() => (window.O4U_products().find(p => p.id === "atomic-main").stock || {}).M === 30, null, { timeout: 8000 });
    await A.context().close(); await B.context().close();
    return { detail: "the same 2x15 race that LOST updates on the old path (browser_tests 8b) with leases off: 30/30 applied, stock 60 -> 30, 30 ledger rows, page updated by live push" };
  });

  fs.writeFileSync(path.join(OUT, "browser_atomic.json"), JSON.stringify(results, null, 1));
  await browser.close();
  process.exit(results.some(r => r.status === "FAIL") ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
