"""Take desktop and phone screenshots of the Stockroom dev dashboard (SYNTHETIC demo data only).

    python scripts/screenshot_dashboard.py [out_dir]

Serves stockroom/ on 127.0.0.1, opens dev/preview.html in headless Chrome/Edge at fixed widths and saves PNGs.
The preview page fills an in-memory stand-in database with invented records and shows a DEMO banner;
nothing real is read. Output defaults to stockroom/dev/screenshots/.
"""
from __future__ import annotations

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

SHOTS = [  # name, query, window width, window height
    ("desktop-owner", "who=Khush&view=owner&theme=light", 1440, 2250),
    ("desktop-owner-dark", "who=Khush&view=owner&theme=dark", 1440, 2250),
    ("desktop-store-operations", "who=Dad&theme=light", 1440, 1500),
    ("mobile-owner", "who=Khush&view=owner&w=390&theme=light", 520, 2900),
    ("mobile-store-operations", "who=Dad&w=390&theme=light", 520, 2200),
]


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dev" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    browser = find_browser()
    if not browser:
        print("Could not find Chrome or Edge.")
        return 2
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        for name, query, w, h in SHOTS:
            profile = tempfile.mkdtemp(prefix="o4u-shot-")
            target = out / f"{name}.png"
            cmd = [browser, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
                   f"--user-data-dir={profile}", f"--window-size={w},{h}", "--virtual-time-budget=9000",
                   "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
                   f"--screenshot={target}", f"http://127.0.0.1:{port}/dev/preview.html?{query}"]
            subprocess.run(cmd, capture_output=True, timeout=120)
            shutil.rmtree(profile, ignore_errors=True)
            print(("saved " if target.exists() else "FAILED ") + str(target))
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
