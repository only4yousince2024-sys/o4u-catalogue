"""Assemble stockroom/stockroom-dev.html from the untouched v44 original + the dashboard redesign.

    python stockroom/build_dev.py

The original (stockroom-v44-original.html) is never modified. The dev copy replaces ONLY the
old Dashboard script block and appends the dashboard stylesheet. Nothing here talks to Claude,
Supabase or any data: it is text assembly. Publishing the result to the live artifact is a
separate step that needs the owner's approval.
"""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
orig = (HERE / "stockroom-v44-original.html").read_text(encoding="utf-8")
js = (HERE / "dev" / "dashboard.js").read_text(encoding="utf-8")
css = (HERE / "dev" / "dashboard.css").read_text(encoding="utf-8")

START = "/* ---------- Dashboard ----------"
END = "X.renderPage();\n})();\n"
a = orig.index(START)
b = orig.index(END, a) + len(END)
# the block must be the LAST script block (it ends right before </script>)
tail = orig[b:b + 40]
if "</script>" not in tail:
    sys.exit("Unexpected layout: the old dashboard block is not at the end of the script. Nothing written.")
out = orig[:a] + js.rstrip("\n") + "\n" + orig[b:]

STYLE_END = ".matrix td small{display:block;color:var(--warn);font-size:10px}\n</style>"
if STYLE_END not in out:
    sys.exit("Could not find the end of the stylesheet. Nothing written.")
out = out.replace(STYLE_END, ".matrix td small{display:block;color:var(--warn);font-size:10px}\n" + css + "</style>", 1)
out = out.replace("<title>O4U Stockroom</title>", "<title>O4U Stockroom (DEV COPY)</title>", 1)
(HERE / "stockroom-dev.html").write_text(out, encoding="utf-8")
print(f"stockroom-dev.html written: {len(out):,} bytes (original {len(orig):,}).")
