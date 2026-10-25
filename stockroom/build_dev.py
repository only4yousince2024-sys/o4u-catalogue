"""Assemble the Stockroom development copies from the untouched v44 original.

    python stockroom/build_dev.py

Writes TWO files next to the original (which is never modified):
  stockroom-dev.html     v1 dashboard (current development version, kept intact)
  stockroom-dev-v2.html  v2 dashboard (role-aware, separate desktop and phone layouts)

Each copy replaces ONLY the old Dashboard script block and appends one stylesheet. v2 takes its metric
functions from dev/dashboard.js at build time, so there is exactly one definition of every figure.
Nothing here talks to Claude, Supabase or any data: it is text assembly. Publishing a result to the live
artifact is a separate step that needs the owner's approval.
"""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
orig = (HERE / "stockroom-v44-original.html").read_text(encoding="utf-8")
DEV = HERE / "dev"

START = "/* ---------- Dashboard ----------"
END = "X.renderPage();\n})();\n"
STYLE_END = ".matrix td small{display:block;color:var(--warn);font-size:10px}\n</style>"


def assemble(js: str, css: str, title: str) -> str:
    a = orig.index(START)
    b = orig.index(END, a) + len(END)
    if "</script>" not in orig[b:b + 40]:
        sys.exit("Unexpected layout: the old dashboard block is not at the end of the script. Nothing written.")
    out = orig[:a] + js.rstrip("\n") + "\n" + orig[b:]
    if STYLE_END not in out:
        sys.exit("Could not find the end of the stylesheet. Nothing written.")
    out = out.replace(STYLE_END, STYLE_END.replace("</style>", "") + css + "</style>", 1)
    return out.replace("<title>O4U Stockroom</title>", f"<title>{title}</title>", 1)


def metrics_of(v1_js: str) -> str:
    """The pure metric code of v1: from the 'const X = ...' line through 'window.O4U_metrics = ...'."""
    a = v1_js.index("const X = window.O4U_ops; if (!X) return;")
    marker = "window.O4U_metrics = {compute, rangeOf};"
    b = v1_js.index(marker) + len(marker)
    return v1_js[a:b]


v1_js = (DEV / "dashboard.js").read_text(encoding="utf-8")
v1 = assemble(v1_js, (DEV / "dashboard.css").read_text(encoding="utf-8"), "O4U Stockroom (DEV COPY)")
(HERE / "stockroom-dev.html").write_text(v1, encoding="utf-8")

v2_src = (DEV / "dashboard_v2.js").read_text(encoding="utf-8")
if "/*__METRICS__*/" not in v2_src:
    sys.exit("dashboard_v2.js lost its /*__METRICS__*/ placeholder. Nothing written for v2.")
v2 = assemble(v2_src.replace("/*__METRICS__*/", metrics_of(v1_js)), (DEV / "dashboard_v2.css").read_text(encoding="utf-8"), "O4U Stockroom (DEV COPY v2)")
(HERE / "stockroom-dev-v2.html").write_text(v2, encoding="utf-8")
print(f"stockroom-dev.html: {len(v1):,} bytes · stockroom-dev-v2.html: {len(v2):,} bytes (original {len(orig):,}).")
