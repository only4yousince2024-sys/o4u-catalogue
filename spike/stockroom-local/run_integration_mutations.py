"""Mutation check for the integration layer: break server.py / page_integration.py ONE way at a time and require ui_tests.py (browser + HTTP checks) to notice.

    python spike/stockroom-local/run_integration_mutations.py [N ...]

Each mutation edits the real file IN PLACE and restores it afterwards (also on Ctrl-C / error); `git diff` is clean when it finishes.
CAUGHT = at least one check failed. SURVIVED = every check still passed -> a gap in the tests. A pattern that is not found exactly once is reported, never skipped.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVER, PAGE = HERE / "server.py", HERE / "page_integration.py"

M = [
    ("server: a document write may carry a different stock (strict refusal off)", SERVER,
     "{k: v for k, v in asked.items() if v} != {k: v for k, v in cur.items() if v}", "False"),
    ("server: a replayed save is not recognised (the stored answer is never used)", SERVER,
     "                if prev is not None:\n                    if prev[0] is None", "                if False:\n                    if prev[0] is None"),
    ("server: a recount ignores the number the person saw (uses the current one)", SERVER,
     '"expect": int(m.get("expect") or 0), "counted"', '"expect": have[str(m["size"]).strip().upper()][1], "counted"'),
    ("server: a hand-set In stock flag is accepted silently", SERVER,
     'if owned and "inStock" in data and bool(data["inStock"]) != (sum(cur.values()) > 0):', "if False:"),
    ("page: a refused stock-editor save closes the editor anyway (error swallowed)", PAGE,
     'refreshStockEditor(p); return; }      // the editor stays open with the message', "refreshStockEditor(p); }"),
    ("page: Capture hides the real reason a save failed", PAGE,
     "c.error = e && e.friendly ? e.friendly :", 'c.error = e && e.friendly ? "Saving failed." :'),
    ("page: the Orders/Exchanges tap is not intercepted", PAGE,
     'if (b.dataset.tab === "orders" || b.dataset.tab === "exchanges") { toast(', "if (false) { toast("),
    ("page: the history line is logged a second time after capture/edit", PAGE,
     'if (d.kind === "capture" || d.kind === "edit") return;      // INTEGRATED COPY: the server wrote this history line in the same transaction\\n', ""),
    ("page: pending products can be saved again", PAGE,
     "  c.error = \"Saving a product for Claude to read later is not available in this build: its stock is not connected to the shared stock. Use \\\\\"Type the tag details myself\\\\\".\"; renderCapture(); return;\\n", ""),
    ("page: the In stock switch writes again", PAGE,
     'if (t.id === "tStock") { toast("In stock is worked out from the pieces on the rack. Change the pieces with Edit stock."); renderDetail(); return; }      // INTEGRATED COPY\\n',
     'if (t.id === "tStock") patch(p.id, {inStock: t.checked}, "x");\\n'),
    ("page: Capture of an existing product forgets what the person saw (expect 0)", PAGE,
     "    const exp = expectOf(it.size);", "    const exp = 0;"),
    ("page: the stock editor sends no stock change (recount items dropped)", PAGE,
     "    if (qty !== exp) items.push({size: z, qty, expect: exp});", "    if (false) items.push({size: z, qty, expect: exp});"),
    ("server: prices are accepted but never sent to the shared catalogue", SERVER,
     "                if prices:\n                    if not row:", "                if False:\n                    if not row:"),
    ("page: the price the person saw is not sent (no version check)", PAGE,
     "prices = {expect_price_paise: was.length ? Math.round(Math.min(...was) * 100) : null,", "prices = {expect_price_paise: null,"),
]


def run_suite() -> tuple[int, int, str]:
    r = subprocess.run([sys.executable, str(HERE / "ui_tests.py")], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    out = r.stdout + r.stderr
    m = re.findall(r"(\d+) passed, (\d+) failed", out)
    failed_names = [l.strip()[:90] for l in out.splitlines() if l.strip().startswith("FAIL")]
    p, f = (int(m[-1][0]), int(m[-1][1])) if m else (0, -1)
    return p, f, "; ".join(failed_names[:3]) or (out[-300:] if f < 0 else "")


def main() -> int:
    want = {int(a) for a in sys.argv[1:]}
    survived = bad = caught = 0
    for n, (name, path, old, new) in enumerate(M, 1):
        if want and n not in want:
            continue
        text = path.read_text(encoding="utf-8")
        if text.count(old) != 1:
            print(f"[{n}] BAD PATTERN ({text.count(old)} matches) {name}")
            bad += 1
            continue
        try:
            path.write_text(text.replace(old, new), encoding="utf-8", newline="")
            p, f, who = run_suite()
        finally:
            path.write_text(text, encoding="utf-8", newline="")
        if f != 0:
            caught += 1
            print(f"[{n}] CAUGHT   {name}\n        by: {who}")
        else:
            survived += 1
            print(f"[{n}] SURVIVED {name}  ({p} passed, 0 failed)")
    print(f"\n{caught} caught, {survived} survived, {bad} bad pattern(s)")
    return 0 if survived == 0 and bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
