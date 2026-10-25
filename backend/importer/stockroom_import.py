"""Plan (and, only into a named DEVELOPMENT database, apply) an import of a Stockroom full-backup into the O4U backend.

    python backend/importer/stockroom_import.py <backup.zip>                       # dry run: prints counts only, writes nothing
    python backend/importer/stockroom_import.py <backup.zip> --apply --database-url <dev url> --i-am-using-a-dev-database

The backup is read LOCALLY and never uploaded. The dry run touches no database. Rules (from the 25 Oct 2026 backup review):
  * quantity comes from the live `stock{}` map. `sizes[].qty` is a stale capture-time note and is NEVER imported as stock.
  * a size row whose `sizes[].qty` disagrees with `stock{}` is imported but flagged count_pending (physical count needed).
  * a product whose `inStock` flag disagrees with its stock total has ALL its sizes flagged count_pending; the flag itself is
    never imported (availability is derived from the ledger only).
  * size labels: FREE and Free are one size; XXL/XXXL are kept exactly as Stockroom wrote them in the stock map
    (the website matches by that label).
  * barcodes: every printed barcode becomes a row in variant_barcodes; shared barcodes are kept for every owner, never merged.
  * one opening_balance ledger row per variant, no sales/receipts/movements are invented.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from collections import Counter, defaultdict


def _canon(label: str) -> str:
    """Case/spacing-insensitive identity of a size label (FREE == Free == Free Size). The label KEPT is chosen separately."""
    t = str(label).strip().upper().replace(" ", "")
    return "FREE" if t in ("FREE", "FREESIZE", "ONESIZE") else t


def plan(records: dict, source: str) -> dict:
    """Pure function: backup records.json content -> everything an import would write. No I/O."""
    prods = (records.get("collections") or records).get("products", {})
    out = {"source": source, "products": [], "variants": [], "barcodes": [], "opening": [], "findings": defaultdict(list), "skipped": []}
    owners = defaultdict(set)
    for pid in sorted(prods):
        p = prods[pid]
        stock = p.get("stock") or {}
        rows = p.get("sizes") or []
        mrps = [int(s["mrp"]) for s in rows if isinstance(s, dict) and isinstance(s.get("mrp"), (int, float)) and s["mrp"] > 0]
        if not mrps:
            out["skipped"].append((pid, "no usable price on any size row"))
            continue
        offer = p.get("offerPrice")
        base = min(mrps)
        price = int(offer) if isinstance(offer, (int, float)) and 0 < offer < base else base
        out["products"].append({"id": pid, "article": p.get("article", ""), "name": f"{p.get('colour', '')} {p.get('type', '')}".strip() or pid,
                                "brand": p.get("brand", ""), "category": p.get("category", ""), "colour": p.get("colour", ""),
                                "price_paise": price * 100, "mrp_paise": base * 100 if price != base else None, "published": bool(p.get("published"))})
        # one variant per canonical size; label = the stock-map key when there is one (the live source), else the size row's label
        keep, qty_row = {}, {}
        for k in stock:
            keep[_canon(k)] = k
        for s in rows:
            if isinstance(s, dict) and s.get("size"):
                keep.setdefault(_canon(s["size"]), s["size"])
                qty_row[_canon(s["size"])] = s
        stock_total = sum(v for v in stock.values() if isinstance(v, (int, float)))
        flag_bad = bool(p.get("inStock")) != (stock_total > 0)
        if flag_bad:
            out["findings"]["inStock flag disagrees with stock"].append(pid)
        for c, label in sorted(keep.items(), key=lambda kv: kv[1]):
            row = qty_row.get(c) or {}
            live = next((v for k, v in stock.items() if _canon(k) == c), 0)
            reasons = []
            if "qty" in row and row["qty"] != live:
                reasons.append(f"size-row quantity {row['qty']} differs from stock {live}")
                out["findings"]["quantity differs"].append((pid, label))
            if flag_bad:
                reasons.append("inStock flag disagrees with stock")
            ovr = int(row["mrp"]) * 100 if isinstance(row.get("mrp"), (int, float)) and row["mrp"] > 0 and int(row["mrp"]) != base and price == base else None
            out["variants"].append({"product_id": pid, "size": label, "price_paise": ovr, "barcode": row.get("barcode") or None})
            if row.get("barcode"):
                out["barcodes"].append({"barcode": str(row["barcode"]).strip(), "product_id": pid, "size": label})
                owners[str(row["barcode"]).strip()].add(pid)
            out["opening"].append({"product_id": pid, "size": label, "qty": int(live), "pending": bool(reasons), "reason": "; ".join(reasons)})
    out["findings"]["shared barcodes"] = sorted(b for b, o in owners.items() if len(o) > 1)
    out["findings"] = dict(out["findings"])
    return out


def summary(pl: dict) -> str:
    f = pl["findings"]
    return "\n".join([
        f"source           {pl['source']}",
        f"products         {len(pl['products'])}   (skipped: {len(pl['skipped'])})",
        f"variants         {len(pl['variants'])}",
        f"barcodes         {len(pl['barcodes'])} rows, {len(f.get('shared barcodes', []))} barcodes shared by several products (all kept, never merged)",
        f"opening pieces   {sum(r['qty'] for r in pl['opening'])} in {len(pl['opening'])} ledger rows (kind opening_balance only)",
        f"count pending    {sum(r['pending'] for r in pl['opening'])} variants flagged for a physical count",
        f"  quantity differs {len(f.get('quantity differs', []))}, inStock flag mismatch {len(f.get('inStock flag disagrees with stock', []))} product(s)",
        "NOTHING WAS WRITTEN (dry run)"])


def apply(conn, pl: dict) -> dict:
    """Write the plan into a DEVELOPMENT database (superuser/service connection). Products, variants, stock rows, barcodes,
    then ONE call to import_opening_balance (all-or-nothing, idempotent by key)."""
    for p in pl["products"]:
        conn.execute("""insert into products (id, article, name, brand, category, colour, price_paise, mrp_paise, published)
                        values (%(id)s,%(article)s,%(name)s,%(brand)s,%(category)s,%(colour)s,%(price_paise)s,%(mrp_paise)s,%(published)s)
                        on conflict (id) do nothing""", p)
    for v in pl["variants"]:
        row = conn.execute("""insert into variants (product_id, size, price_paise) values (%s,%s,%s)
                              on conflict (product_id, size) do nothing returning id""", (v["product_id"], v["size"], v["price_paise"])).fetchone()
        if row:
            conn.execute("insert into stock_levels (variant_id) values (%s)", (row[0],))
    for b in pl["barcodes"]:
        conn.execute("""insert into variant_barcodes (barcode, variant_id)
                        select %s, id from variants where product_id = %s and size = %s on conflict do nothing""", (b["barcode"], b["product_id"], b["size"]))
    key = "opening:" + hashlib.sha256(json.dumps(pl["opening"], sort_keys=True).encode()).hexdigest()[:24]
    return conn.execute("select import_opening_balance(%s,%s,%s::jsonb)", (key, pl["source"], json.dumps(pl["opening"]))).fetchone()[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("zip")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--database-url")
    ap.add_argument("--i-am-using-a-dev-database", action="store_true")
    a = ap.parse_args()
    z = zipfile.ZipFile(a.zip)
    src = hashlib.sha256(open(a.zip, "rb").read()).hexdigest()
    pl = plan(json.loads(z.read("records.json")), src[:16])
    print(summary(pl))
    if not a.apply:
        return 0
    if not (a.database_url and a.i_am_using_a_dev_database):
        print("Refusing: --apply needs --database-url and --i-am-using-a-dev-database. Real products are never imported by this script without separate approval.")
        return 2
    low = a.database_url.lower()
    if not any(t in low for t in ("dev", "test", "localhost", "127.0.0.1")):
        print("Refusing: the database name/host does not look like a development database.")
        return 2
    import psycopg
    with psycopg.connect(a.database_url, autocommit=False) as c:
        print(apply(c, pl))
    return 0


if __name__ == "__main__":
    sys.exit(main())
