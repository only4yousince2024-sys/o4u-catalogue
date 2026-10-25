"""Run the Stockroom dashboard checks headless - no browser window, no real data.

    python scripts/run_dashboard_tests.py          # v1 dashboard (stockroom-dev.html)
    python scripts/run_dashboard_tests.py --v2     # v2 dashboard (stockroom-dev-v2.html)

Serves ONLY stockroom/ on 127.0.0.1 (random port), opens stockroom/dev/dashboard_test_runner.html in headless
Chrome/Edge with a throwaway profile and every non-local host blocked. The page under test talks to an in-memory
stand-in for the database filled with synthetic records, so nothing real can be read or changed.
Exit 0 = all passed, 1 = a check failed, 2 = the run itself could not happen.
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

ROOT = Path(__file__).resolve().parent.parent / "stockroom"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_cart_tests import find_browser  # noqa: E402


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


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
    v2 = "--v2" in sys.argv
    query = "?page=v2&tests=dashboard_v2_tests.js" if v2 else ""
    url = f"http://127.0.0.1:{server.server_address[1]}/dev/dashboard_test_runner.html{query}"
    profile = tempfile.mkdtemp(prefix="o4u-dash-tests-")
    try:
        cmd = [browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
               f"--user-data-dir={profile}", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
               "--virtual-time-budget=60000", "--dump-dom", url]
        run = subprocess.run(cmd, capture_output=True, timeout=240, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        print("The headless browser did not finish within 4 minutes.")
        return 2
    finally:
        server.shutdown()
        shutil.rmtree(profile, ignore_errors=True)
    m = re.search(r'<pre id="out">(.*?)</pre>', run.stdout, re.S)
    body = html.unescape(m.group(1)) if m else ""
    if not body.startswith("RESULT "):
        print("The test page did not report results.")
        print(body[:3000] or (run.stderr or "")[-2000:])
        return 2
    res = json.loads(body[len("RESULT "):])
    for line in res.get("lines", []):
        print(line)
    return 0 if res.get("fail", 1) == 0 and res.get("pass", 0) > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
