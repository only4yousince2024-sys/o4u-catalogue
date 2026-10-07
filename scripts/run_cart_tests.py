"""Run scripts/cart_tests.js headless - no browser window, no WhatsApp.

    python scripts/run_cart_tests.py

Serves ONLY website/ and the two test files on 127.0.0.1 (random port), opens
scripts/cart_test_runner.html in headless Chrome (or Edge) with a throwaway
profile and every non-local host blocked, and prints the results.
Exit 0 = all passed, 1 = a check failed, 2 = the run itself could not happen.

The tests never navigate to wa.me: they build the URL and decode it. As a
second guard window.open is stubbed in the page, and DNS for every host except
127.0.0.1 is mapped to nowhere, so even a bug could not send a message.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED = ("/website/", "/scripts/cart_tests.js", "/scripts/cart_test_runner.html")
BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "google-chrome", "chromium", "chromium-browser", "msedge",
]


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib name
        if not self.path.split("?")[0].startswith(ALLOWED):
            self.send_error(404)
            return
        super().do_GET()

    def log_message(self, *args):  # keep the output to the test lines
        pass


def find_browser() -> str | None:
    for b in BROWSERS:
        if Path(b).is_file():
            return b
        found = shutil.which(b)
        if found:
            return found
    return None


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    browser = find_browser()
    if not browser:
        print("Could not find Chrome or Edge to run the tests headless.")
        return 2
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/scripts/cart_test_runner.html"
    profile = tempfile.mkdtemp(prefix="o4u-cart-tests-")
    try:
        cmd = [
            browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
            f"--user-data-dir={profile}",
            "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
            "--virtual-time-budget=30000", "--dump-dom", url,
        ]
        run = subprocess.run(cmd, capture_output=True, timeout=180, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        print("The headless browser did not finish within 3 minutes.")
        return 2
    finally:
        server.shutdown()
        shutil.rmtree(profile, ignore_errors=True)

    m = re.search(r'<pre id="out">(.*?)</pre>', run.stdout, re.S)
    body = html.unescape(m.group(1)) if m else ""
    if not body.startswith("RESULT "):
        print("The test page did not report results.")
        print(body[:2000] or (run.stderr or "")[-2000:])
        return 2
    res = json.loads(body[len("RESULT "):])
    for line in res.get("lines", []):
        print(line)
    if res.get("thresholds"):
        print("\nThreshold boundaries (actual numbers):")
        for t in res["thresholds"]:
            print(f"  product total ₹{t['productTotal']:,} · discount ₹{t['discount']} · items total ₹{t['itemsTotal']:,}"
                  f" · free={t['freeDelivery']} · bag shows {t['bagShows']} · bag: \"{t['bagOfferLine']}\""
                  f" · message: \"{t['messageDeliveryLine']}\"")
    print(f"\nProducts loaded: {res.get('products')} · WhatsApp opens attempted: {res.get('blockedOpens')} (all stubbed)")
    return 0 if res.get("fail", 1) == 0 and res.get("pass", 0) > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
