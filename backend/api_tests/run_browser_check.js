// Drives browser_cors_check.html in a REAL Chromium (Playwright), served from one local origin while the API is on another.
// Used here against the LOCAL stack (PostgREST CORS). The owner opens the same page by hand against the hosted project.
//   node backend/api_tests/run_browser_check.js <api-base-url> <anon-key> [rest-prefix]
// The key is passed as an argument ONLY for this local run with a throwaway key; never pass a real key on a command line.
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path');

(async () => {
  const [apiUrl, key, prefix = ''] = process.argv.slice(2);
  const page_html = fs.readFileSync(path.join(__dirname, 'browser_cors_check.html'));
  const srv = http.createServer((q, r) => { r.writeHead(200, { 'content-type': 'text/html' }); r.end(page_html); });
  await new Promise((ok) => srv.listen(0, '127.0.0.1', ok));
  const origin = `http://localhost:${srv.address().port}`;      // a different origin (port) from the API
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const seen = [];
  page.on('console', (m) => { if (m.type() === 'error') seen.push(m.text().slice(0, 200)); });
  await page.goto(origin);
  await page.fill('#url', apiUrl); await page.fill('#key', key); await page.fill('#prefix', prefix);
  await page.click('#run');
  await page.waitForSelector('#out:not([hidden])', { timeout: 60000 });
  const rows = await page.$$eval('#out tbody tr', (trs) => trs.map((tr) => [...tr.children].map((td) => td.textContent)));
  const verdict = await page.textContent('#verdict');
  console.log('page origin:', origin, '| api:', apiUrl);
  for (const r of rows) console.log((r[1] === 'yes' ? 'READABLE ' : 'BLOCKED  ') + r[2].padEnd(4) + ' ' + r[0].slice(0, 95) + (r[3] ? '  -> ' + r[3] : ''));
  console.log('verdict:', verdict);
  console.log('browser console errors:', seen.length);
  await browser.close(); srv.close();
  process.exit(Number(await Promise.resolve(0)));
})().catch((e) => { console.error(e); process.exit(2); });
