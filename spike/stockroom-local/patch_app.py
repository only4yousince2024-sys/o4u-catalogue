"""Generate the ISOLATED SPIKE COPY of Stockroom with atomic stock moves. The original stockroom/stockroom-v44-original.html is read, never written.

    python spike/stockroom-local/patch_app.py        -> .data/stockroom-v44-atomic.html  (served at /stockroom?v=atomic)  and  app/moveStock-atomic.diff

Part 3 (integration, 5 Nov 2026, page_integration.py): the same copy also routes Capture's quantities and the product stock editor through ONE server
call (`stock.save` -> /api/catalogue/save -> sync_catalogue_product + apply_stock_moves recounts), shows save failures instead of dropping them, and switches
off what is not connected yet (products waiting for Claude, other colours, the Orders and Exchanges tabs).

Why the page itself has to change (the shim alone cannot do it): moveStock() READS a product, computes an absolute stock map in the browser, WRITES it with
`products.update({stock})` and then, in a SECOND request, writes history lines. A shim sees two unrelated calls; it cannot know which stock the page based its
number on, cannot make the two writes one transaction, and cannot tell a retry from a new action. The copy therefore sends ONE call that carries the DELTA, a request
key reused on every retry, and (for recounts) the number the counter saw. Two hunks only: moveStock() and the stock-edit call site that passes `expect` for a recount.
"""
from __future__ import annotations

import difflib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import page_integration as PI      # noqa: E402
ROOT = HERE.parents[1]
SRC = ROOT / "stockroom" / "stockroom-v44-original.html"
import os  # noqa: E402
OUT = (Path(os.environ["SPIKE_DATA_DIR"]) if os.environ.get("SPIKE_DATA_DIR") else HERE / ".data") / "stockroom-v44-atomic.html"

START = "async function moveStock(changes, meta, respectHolds){"
END = "async function logMoves(list, meta, at){"

NEW_MOVE = '''async function moveStock(changes, meta, respectHolds){
  // SPIKE COPY: one atomic server call (stock change + ledger row together, retry-safe) instead of read -> compute absolute -> write -> write history.
  const stockApi = window.claude && typeof window.claude.use === "function" ? await window.claude.use("stock") : null;
  if (!stockApi) throw fail("Atomic stock changes are not available in this view.");
  const pids = [...new Set(changes.map(c => c.productId))];
  const prods = {};
  for (const id of pids) prods[id] = await freshProduct(id);
  const holding = respectHolds ? (await freshHolding()).filter(o => o.id !== meta.orderId) : [];
  const seen = {};
  for (const id of pids) seen[id] = {...(prods[id].stock || {})};
  const moves = [];
  for (const c of changes) {
    if (respectHolds && c.change < 0) {      // friendly pre-check, exactly as before; the database repeats it under a lock
      const left = C.stockOf({stock: seen[c.productId]}, c.size) - C.held(holding, c.productId, c.size);
      if (left < -c.change) { const e = new Error(`Only ${Math.max(0, left)} of ${prodName(prods[c.productId])} in ${C.sizeLabel(c.size)} free to sell (the rest is held for orders).`); e.code = "short"; throw e; }
    }
    const p = prods[c.productId];
    const line = {productId: c.productId, size: C.normSize(c.size), change: c.change, unitP: C.isNum(c.unitP) ? c.unitP : null,
      label: prodName(p), article: p.article || "", category: p.category || ""};
    if (meta.kind === "recount") line.expect = C.stockOf({stock: meta.expect || seen[c.productId]}, c.size);   // what the person saw when counting
    moves.push(line);
  }
  const key = "mv-" + newId("k");      // ONE key per user action; the shim reuses it on every retry
  return stockApi.move({key, meta: {kind: meta.kind, orderId: meta.orderId || "", caseId: meta.caseId || "", note: meta.note || "", by: O.who}, moves});
}
'''

CALL_OLD = 'await moveStock(ch, {kind: f.why, note: (f.note || "").trim()}, f.why !== "restock");'
CALL_NEW = 'await moveStock(ch, {kind: f.why, note: (f.note || "").trim(), expect: f.why === "recount" ? (p.stock || {}) : undefined}, f.why !== "restock");'


def build() -> tuple[str, str]:
    src = SRC.read_text(encoding="utf-8")
    a, b = src.index(START), src.index(END)
    if src.count(START) != 1 or src.count(CALL_OLD) != 1:
        sys.exit("The original has changed: anchors not found exactly once. Nothing written.")
    out = src[:a] + NEW_MOVE + src[b:]
    out = out.replace(CALL_OLD, CALL_NEW)
    for old_, new_ in PI.EDITS:
        if out.count(old_) != 1:
            sys.exit("Part 3 anchor not found exactly once (%d): %r. Nothing written." % (out.count(old_), old_[:70]))
        out = out.replace(old_, new_)
    out = out.replace("</body>", PI.GREY_OUT, 1)
    diff = "".join(difflib.unified_diff(src.splitlines(True), out.splitlines(True), "stockroom-v44-original.html", "stockroom-v44-atomic.html", n=2))
    return out, diff


if __name__ == "__main__":
    out, diff = build()
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(out, encoding="utf-8")
    (HERE / "app" / "moveStock-atomic.diff").write_text(diff, encoding="utf-8")
    print(f"wrote {OUT} ({len(out)} bytes) and app/moveStock-atomic.diff ({diff.count(chr(10))} lines)")
