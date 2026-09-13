#!/usr/bin/env python3
"""
Self-checks for scripts/build_catalogue.py — no pytest needed:

    python scripts/test_build_catalogue.py

Covers the size parser (§6.2), Product IDs (§4.2), price rules (§6.3),
shop-column defaults (§5.2/5.3), the duplicate article+colour error (§4.3)
and the unknown-category error (§6.6) using small in-memory workbooks.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_catalogue as bc  # noqa: E402
import openpyxl  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass


def sizes(raw):
    d = bc.Diag()
    out = bc.parse_sizes(raw, "t", d)
    return out, d.errors


def test_sizes():
    assert sizes("M L XL 2XL")[0] == ["M", "L", "XL", "2XL"]
    assert sizes("2XL M L")[0] == ["M", "L", "2XL"]                       # canonical order
    assert sizes("M to 3XL")[0] == ["M", "L", "XL", "2XL", "3XL"]
    assert sizes("S to XXL")[0] == ["S", "M", "L", "XL", "2XL"]
    assert sizes("L-3XL")[0] == ["L", "XL", "2XL", "3XL"]
    assert sizes("L–3XL")[0] == ["L", "XL", "2XL", "3XL"]                  # en dash
    assert sizes("L—3XL")[0] == ["L", "XL", "2XL", "3XL"]                  # em dash
    assert sizes("M - 3XL")[0] == ["M", "L", "XL", "2XL", "3XL"]
    assert sizes("XXL")[0] == ["2XL"]
    assert sizes("xxxl, xl")[0] == ["XL", "3XL"]
    assert sizes("M, L, XL")[0] == ["M", "L", "XL"]
    assert sizes("M L L M")[0] == ["M", "L"]                              # dedupe
    assert sizes("  ")[0] == [] and sizes(None)[0] == []
    out, errs = sizes("to")
    assert out == [] and errs, "dangling 'to' must be an error"
    out, errs = sizes("3XL to M")
    assert errs, "reversed range must be an error"
    out, errs = sizes("M L FREE")
    assert out == ["M", "L"] and errs, "unknown token must be an error"
    assert sizes(1) == ([], [f"t: unknown size token '1' in '1'"])
    assert "to" not in [s.lower() for s in sizes("M to 3XL")[0]]


def test_slug():
    assert bc.slugify("CS250A", "Min.Red") == "cs250a-min-red"
    assert bc.slugify("KPL310D/B", "Violet") == "kpl310d-b-violet"
    assert bc.slugify("GW19B", None) == "gw19b"
    assert bc.slugify("A&B", "Rose Gold") == "aandb-rose-gold"
    assert bc.slugify(" CS-59A ", "Peacock ") == "cs-59a-peacock"


HEADERS = ["S.No", "Brand", "Article No.", "Description", "Shade / Color", "Size", "Barcode",
           "MRP (₹)", "Stock Qty", "Available Sizes", "Style Code", "Image URL", "Notes"]


def make_wb(rows, extra_headers=(), title=True):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Stock Inventory"
    if title:
        ws.append(["STOCK INVENTORY — TEST"])
    ws.append(HEADERS + list(extra_headers))
    for r in rows:
        ws.append(r)
    tmp = Path(tempfile.mkdtemp()) / "t.xlsx"
    wb.save(tmp)
    return tmp


def run(rows, extra_headers=(), images=None):
    wbp = make_wb(rows, extra_headers)
    out = wbp.parent / "products.js"
    imgdir = wbp.parent / "images"
    imgdir.mkdir()
    for name in images or []:
        (imgdir / name).write_bytes(b"x")
    rc = bc.main(["--workbook", str(wbp), "--out", str(out), "--images-dir", str(imgdir), "--quiet"])
    text = out.read_text(encoding="utf-8") if out.exists() else ""
    import json, re
    prods = json.loads(re.search(r"const PRODUCTS = (.*?);\n", text, re.S).group(1)) if text else None
    return rc, prods


ROW = [1, "Melini", "CS250A", "Cord Set", "Min.Red", "L", "1", 1415, 1, "M L XL 2XL", "", "", ""]


def test_defaults_when_shop_columns_absent():
    rc, prods = run([ROW])
    assert rc == 0 and len(prods) == 1
    p = prods[0]
    assert p["id"] == "cs250a-min-red"
    assert p["price"] == 1415 and p["mrp"] is None          # selling price falls back to MRP
    assert p["published"] is True                            # missing Published column → TRUE
    assert p["stockQty"] == 1 and p["images"] == [] and p["image"] == ""
    assert p["sizes"] == ["M", "L", "XL", "2XL"]


def test_price_rules():
    extra = ["Selling Price", "Offer Price", "Published"]
    rows = [
        ROW + [1415, None, "TRUE"],            # selling only → price 1415, no strike
        [2, "Melini", "CS250A", "Cord Set", "Violet", "L", "", 1415, 1, "M L", "", "", "", 1415, 999, True],   # offer → strike
        [3, "Melini", "CS250A", "Cord Set", "Grey", "L", "", 1415, 0, "M L", "", "", "", None, None, "no"],   # blank selling → MRP + warn; unpublished
        [4, "Melini", "CS250A", "Cord Set", "Blue", "L", "", 1415, 2, "M L", "", "", "", None, None, None],   # blank published → TRUE
    ]
    rc, prods = run(rows, extra)
    assert rc == 0
    by = {p["id"]: p for p in prods}
    assert by["cs250a-min-red"]["price"] == 1415 and by["cs250a-min-red"]["mrp"] is None
    assert by["cs250a-violet"]["price"] == 999 and by["cs250a-violet"]["mrp"] == 1415
    assert "cs250a-grey" not in by, "unpublished products must not reach products.js"
    assert by["cs250a-blue"]["published"] is True


def test_stock_and_grouping():
    rows = [
        [1, "Melini", "CS250B", "Cord Set", "E.Grey", "XL", "", 1465, 1, "M to 3XL", "", "", ""],
        [2, "Melini", "CS250B", "Cord Set", "E.Grey", "XXL", "", 1465, 1, "M to 3XL", "", "", ""],
        [3, "Melini", "CS250B", "Cord Set", "Violet", "M-3XL", "", 1465, 0, "", "", "", ""],
    ]
    rc, prods = run(rows)
    assert rc == 0 and len(prods) == 2
    g = next(p for p in prods if p["id"] == "cs250b-e-grey")
    assert g["stockQty"] == 2 and g["sizes"] == ["M", "L", "XL", "2XL", "3XL"]
    v = next(p for p in prods if p["id"] == "cs250b-violet")
    assert v["stockQty"] == 0 and v["sizes"] == ["M", "L", "XL", "2XL", "3XL"]   # range parsed from Size column


def test_size_prices():
    rows = [
        [1, "Sweet & Touch", "7724291-C", "Premium Lounge Wear", "Sky", "M", "", 549, 1, "S to 3XL", "", "", ""],
        [2, "Sweet & Touch", "7724291-C", "Premium Lounge Wear", "Sky", "3XL", "", 649, 1, "S to 3XL", "", "", ""],
    ]
    rc, prods = run(rows)
    assert rc == 0 and prods[0]["price"] == 549 and prods[0]["sizePrices"] == {"3XL": 649}
    assert prods[0]["brand"] == "Sweet Touch"


def test_duplicate_article_colour_blocks():
    rows = [
        [1, "Sweet & Touch", "7724090-F", "Premium Lounge Wear (T+Pants)", "Pink", "L", "", 749, 1, "M to 3XL", "", "", ""],
        [2, "Sweet & Touch", "7724090-F", "Premium Lounge Wear Button-Up Combo", "Pink", "L", "", 924, 1, "M to 3XL", "", "", ""],
    ]
    rc, prods = run(rows)
    assert rc == 1 and prods is None, "duplicate article+colour must block the build and not write output"


def test_repeated_article_across_colours_is_fine():
    rows = [ROW, [2, "Melini", "CS250A", "Cord Set", "Violet", "L", "", 1415, 1, "M L", "", "", ""]]
    rc, prods = run(rows)
    assert rc == 0 and len(prods) == 2


def test_unknown_category_blocks():
    rows = [[1, "Melini", "ZZ1", "Space Suit", "Silver", "L", "", 999, 1, "M L", "", "", ""]]
    rc, prods = run(rows)
    assert rc == 1 and prods is None


def test_blank_colour_and_shifted_row():
    rows = [
        [1, "Melini", "GW19B", "Gym Wear", None, "2XL", "", 1445, 1, "M L XL 2XL", "", "", ""],
        [None, 217, "Zaps / J.T. International", "ST21002 AMD", "Rayon Co-Ord Set", "AMD 925", "XL", None, 1649, 1, "M L XL 2XL", "ST21002", ""],
    ]
    rc, prods = run(rows)
    assert rc == 0 and len(prods) == 1
    assert prods[0]["id"] == "gw19b" and prods[0]["name"] == "Gym Wear" and prods[0]["colors"] == []
    assert prods[0]["description"] == "Gym Wear by Melini."


def test_images_discovered_in_order():
    rc, prods = run([ROW], images=["cs250a-min-red.jpg", "cs250a-min-red-2.jpg", "cs250a-min-red-3.png", "cs250a-min-red-9.jpg", "unrelated.jpg"])
    assert rc == 0
    assert prods[0]["images"] == ["images/cs250a-min-red.jpg", "images/cs250a-min-red-2.jpg", "images/cs250a-min-red-3.png", "images/cs250a-min-red-9.jpg"]
    assert prods[0]["image"] == "images/cs250a-min-red.jpg"


def test_missing_required_column_blocks():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Stock Inventory"
    ws.append(["Brand", "Article No.", "Description", "Size", "Stock Qty"])   # no colour, no MRP
    ws.append(["Melini", "CS250A", "Cord Set", "L", 1])
    tmp = Path(tempfile.mkdtemp()) / "t.xlsx"
    wb.save(tmp)
    rc = bc.main(["--workbook", str(tmp), "--out", str(tmp.parent / "p.js"), "--images-dir", str(tmp.parent), "--quiet"])
    assert rc == 1


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✔ {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  ✖ {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ✖ {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
