"""Break the spike's own atomic-stock layer on purpose (shim / server / page patch), one way at a time, and confirm run_spike.py --atomic-only notices.
Edits copies in place and restores the originals afterwards (a backup is kept in memory and rewritten in `finally`)."""
import subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
MUT = [
    ("shim: a NEW request key on every retry", "static/claude-shim.js", 'body: JSON.stringify({key, meta, moves})', 'body: JSON.stringify({key: key + "-r" + attempt, meta, moves})'),
    ("server: stock + ledger + history copy NOT in one transaction", "server.py", "with db() as c, c.transaction():", "with db() as c:"),
    ("server: document writes may overwrite relational stock", "server.py", '''                data = {k: v for k, v in data.items() if k not in ("stock", "inStock", "_stockSource")}      # one writer for stock: apply_stock_moves''', "                pass"),
    ("server: page reads stale document stock instead of the relational number", "server.py", '''            if name == "products":
                docs = overlay_stock(c, docs)''', "            pass"),
    ("page copy: recount does not send what the counter saw", "patch_app.py", 'if (meta.kind === "recount") line.expect = C.stockOf({stock: meta.expect || seen[c.productId]}, c.size);', 'if (meta.kind === "recount") line.expect = C.stockOf({stock: seen[c.productId]}, c.size);'),
]
rows = []
for name, f, old, new in MUT:
    path = HERE / f
    orig = path.read_text()
    assert orig.count(old) == 1, (name, orig.count(old))
    try:
        path.write_text(orig.replace(old, new))
        r = subprocess.run([sys.executable, str(HERE / "run_spike.py"), "--atomic-only"], capture_output=True, text=True, timeout=400)
        fails = [l.split("  ", 2)[-1][:70] for l in r.stdout.splitlines() if "  FAIL  " in l]
        rows.append((name, "CAUGHT" if r.returncode else "SURVIVED", fails))
    except subprocess.TimeoutExpired:
        rows.append((name, "HUNG", []))
    finally:
        path.write_text(orig)
    print(f"{rows[-1][1]:9s} {name}\n          by: {'; '.join(rows[-1][2][:3])}", flush=True)
print(f"\n{sum(1 for r in rows if r[1] != 'SURVIVED')} of {len(rows)} detected; survived: {[r[0] for r in rows if r[1] == 'SURVIVED']}")
