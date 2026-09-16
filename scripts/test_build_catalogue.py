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
    out, errs = sizes("M L BIG")
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


def run(rows, extra_headers=(), images=None, reviews=None, stockroom=None):
    wbp = make_wb(rows, extra_headers)
    if reviews is not None:
        wb = openpyxl.load_workbook(wbp)
        ws = wb.create_sheet("Reviews")
        for r in reviews:
            ws.append(r)
        wb.save(wbp)
    out = wbp.parent / "products.js"
    imgdir = wbp.parent / "images"
    imgdir.mkdir()
    for name in images or []:
        (imgdir / name).write_bytes(b"x")
    import json as _json
    srp = wbp.parent / "stockroom.json"
    if stockroom is not None:
        srp.write_text(_json.dumps(stockroom), encoding="utf-8")
    rc = bc.main(["--workbook", str(wbp), "--out", str(out), "--images-dir", str(imgdir), "--stockroom", str(srp), "--quiet"])
    text = out.read_text(encoding="utf-8") if out.exists() else ""
    import json, re
    prods = json.loads(re.search(r"const PRODUCTS = (.*?);\n", text, re.S).group(1)) if text else None
    global LAST_REVIEWS
    LAST_REVIEWS = json.loads(re.search(r"const REVIEWS = (.*?);\n", text, re.S).group(1)) if text else None
    return rc, prods


LAST_REVIEWS = None


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


def test_reviews_absent_sheet_gives_empty_array():
    rc, prods = run([ROW])
    assert rc == 0 and LAST_REVIEWS == []


def test_reviews_sheet_is_read_and_validated():
    import datetime
    reviews = [
        ["Name", "City", "Rating", "Review", "Date", "Published", "Source"],
        ["Priya S.", "Ludhiana", 4.5, "Fabric is lovely.", datetime.date(2026, 9, 1), "TRUE", "WhatsApp"],
        ["Hidden", "Amritsar", 5, "Should not appear", None, "FALSE", "Instagram"],
        ["Bad rating", "Jalandhar", 7, "Out of range", None, "TRUE", ""],
        ["No text", "Jalandhar", 4, None, None, "TRUE", ""],
        ["Blank pub", "", "3", "Honest three stars.", "Sept 2026", None, "in-store"],
    ]
    rc, prods = run([ROW], reviews=reviews)
    assert rc == 0, "review problems must never fail the build"
    assert [r["name"] for r in LAST_REVIEWS] == ["Priya S.", "Blank pub"]
    assert LAST_REVIEWS[0] == {"name": "Priya S.", "city": "Ludhiana", "rating": 4.5, "review": "Fabric is lovely.", "date": "2026-09-01", "source": "WhatsApp"}
    assert LAST_REVIEWS[1]["rating"] == 3.0 and LAST_REVIEWS[1]["date"] == "Sept 2026"


def test_free_size():
    assert sizes("Free Size")[0] == ["Free Size"]
    assert sizes("FREE SIZE, XL")[0] == ["XL", "Free Size"]          # after 5XL in order
    assert sizes("freesize")[0] == ["Free Size"] and sizes("One Size")[0] == ["Free Size"]
    assert sizes("free")[0] == ["Free Size"]
    assert sizes("5XL Free Size M")[0] == ["M", "5XL", "Free Size"]
    out, errs = sizes("FS")
    assert out == [] and errs, "FS is full sleeves on Sweet Pini tags, never free size"
    rows = [[1, "", "O4U-NB-0001", "Cotton Lycra T-shirt & Pants Set", "Red White", "Free Size", "", 1490, 1, "Free Size", "", "", "", "tshirt-lower"]]
    rc, prods = run(rows, ["Category"])
    assert rc == 0 and prods[0]["sizes"] == ["Free Size"]


def test_category_column_override_and_blank_fallback():
    rows = [
        [1, "Sweet Pini", "14560B", "Satin Nightsuit", "Black Pink Geometric", "XL", "", 1589, 1, "XL, XXL", "", "", "", "front-button"],
        [2, "Sweet Pini", "14560B", "Satin Nightsuit", "Black Pink Geometric", "XXL", "", 1689, 1, "XL, XXL", "", "", "", "Front Button Set"],
        ROW + [None],                                                   # blank → CATEGORY_MAP (Cord Set → front-button)
        [3, "Melini", "NS1", "Night Suit", "Rose", "M", "", 999, 1, "M L", "", "", "", "Salwar Set"],   # label overrides map
    ]
    rc, prods = run(rows, ["Category"])
    assert rc == 0
    by = {p["id"]: p for p in prods}
    assert by["14560b-black-pink-geometric"]["category"] == "front-button"
    assert by["14560b-black-pink-geometric"]["brand"] == "Sweet Pini"
    assert by["14560b-black-pink-geometric"]["sizes"] == ["XL", "2XL"]
    assert by["14560b-black-pink-geometric"]["sizePrices"] == {"2XL": 1689}
    assert by["cs250a-min-red"]["category"] == "front-button"
    assert by["ns1-rose"]["category"] == "salwar-set"


def test_category_column_unknown_or_conflicting_blocks():
    rc, prods = run([ROW + ["Outerwear"]], ["Category"])
    assert rc == 1 and prods is None
    rows = [ROW + ["front-button"], [2, "Melini", "CS250A", "Cord Set", "Min.Red", "XL", "", 1415, 1, "M L", "", "", "", "round-neck"]]
    rc, prods = run(rows, ["Category"])
    assert rc == 1 and prods is None, "rows of one product disagreeing on Category must block"


def test_non_branded_blank_brand_no_warning():
    rows = [[1, None, "O4U-NB-0001", "Cotton Lycra T-shirt & Pants Set", "Red White", "Free Size", "", 1490, 1, "Free Size", "", "", "", "tshirt-lower"]]
    d = bc.Diag()
    wbp = make_wb(rows, ["Category"])
    wb = openpyxl.load_workbook(wbp, data_only=True, read_only=True)
    ws = bc.find_sheet(wb, d)
    header_row, colmap = bc.find_header(ws, d)
    parsed = bc.read_rows(ws, header_row, colmap, d)
    prods = bc.build_products(parsed, colmap, wbp.parent, d)
    assert prods[0]["brand"] == "" and prods[0]["description"] == "Cotton Lycra T-shirt & Pants Set in Red White."
    assert not any("brand" in w.lower() for w in d.warnings), d.warnings
    assert not d.errors
    # a branded article with a blank brand still warns
    d2 = bc.Diag()
    bc.build_products(bc.read_rows(ws, header_row, colmap, d2), colmap, wbp.parent, d2) if False else None
    rows2 = [[1, None, "CS250A", "Cord Set", "Min.Red", "L", "", 1415, 1, "M L", "", "", ""]]
    wbp2 = make_wb(rows2)
    wb2 = openpyxl.load_workbook(wbp2, data_only=True, read_only=True)
    ws2 = bc.find_sheet(wb2, d2); hr2, cm2 = bc.find_header(ws2, d2)
    bc.build_products(bc.read_rows(ws2, hr2, cm2, d2), cm2, wbp2.parent, d2)
    assert any("brand is blank" in w for w in d2.warnings)


def test_published_blank_stays_true_and_false_hides():
    rows = [
        ROW + [None, None],                                                                                     # old row, blank → published
        [2, "Sweet Pini", "14560B", "Satin Nightsuit", "Black Pink Geometric", "XL", "", 1589, 1, "XL, XXL", "", "", "", "front-button", "FALSE"],   # new Stockroom rows
        [3, "Sweet Pini", "14560B", "Satin Nightsuit", "Black Pink Geometric", "XXL", "", 1689, 1, "XL, XXL", "", "", "", "front-button", "FALSE"],
        [4, "Melini", "NS1", "Night Suit", "Rose", "M", "", 999, 1, "M L", "", "", "", None, "TRUE"],
    ]
    rc, prods = run(rows, ["Category", "Published"])
    assert rc == 0
    ids = [p["id"] for p in prods]
    assert "cs250a-min-red" in ids and "ns1-rose" in ids and "14560b-black-pink-geometric" not in ids


SR_PRODUCT = {
    "id": "14560b-black-pink-geometric", "article": "14560B", "brand": "Sweet Pini",
    "category": "front-button", "type": "Satin Nightsuit", "colour": "Black Pink Geometric",
    "features": ["Satin", "Full sleeves"],
    "sizes": [{"size": "XL", "mrp": 1589, "barcode": "1"}, {"size": "XXL", "mrp": 1689, "barcode": "2"}],
    "stock": {"XL": 1, "XXL": 2}, "inStock": True, "offerPrice": None, "notes": "",
    "images": ["14560b-black-pink-geometric.jpg", "14560b-black-pink-geometric-2.jpg"],
}
SR_NB = {
    "id": "o4u-nb-0001-red-white", "article": "O4U-NB-0001", "brand": "",
    "category": "tshirt-lower", "type": "Cotton Lycra T-shirt & Pants Set", "colour": "Red White",
    "features": "", "sizes": [{"size": "Free", "mrp": 1490, "barcode": ""}],
    "stock": {}, "inStock": True, "offerPrice": 1290, "notes": "", "images": [],
}


def test_stockroom_products_build():
    sr = {"exportedAt": "2026-09-15T10:00:00Z", "products": [SR_PRODUCT, SR_NB]}
    rc, prods = run([ROW], stockroom=sr, images=["14560b-black-pink-geometric.jpg", "14560b-black-pink-geometric-2.jpg", "o4u-nb-0001-red-white.jpg"])
    assert rc == 0 and [p["id"] for p in prods] == ["14560b-black-pink-geometric", "o4u-nb-0001-red-white", "cs250a-min-red"]
    a, b = prods[0], prods[1]
    assert a["sizes"] == ["XL", "2XL"] and a["price"] == 1589 and a["mrp"] is None and a["sizePrices"] == {"2XL": 1689}
    assert a["stockQty"] == 3 and a["brand"] == "Sweet Pini" and a["published"] is True
    assert a["images"] == ["images/14560b-black-pink-geometric.jpg", "images/14560b-black-pink-geometric-2.jpg"]
    assert a["description"] == "Satin Nightsuit in Black Pink Geometric by Sweet Pini. Satin, Full sleeves."
    assert b["sizes"] == ["Free Size"] and b["price"] == 1290 and b["mrp"] == 1490 and b["brand"] == ""
    assert b["stockQty"] == 1 and b["images"] == ["images/o4u-nb-0001-red-white.jpg"]   # discovered by id when images[] is empty
    assert b["description"] == "Cotton Lycra T-shirt & Pants Set in Red White."


def test_stockroom_id_mismatch_is_error():
    bad = dict(SR_PRODUCT, id="14560b-black-pink")
    rc, prods = run([ROW], stockroom={"products": [bad]})
    assert rc == 1 and prods is None


def test_stockroom_unknown_category_is_error():
    bad = dict(SR_PRODUCT, category="Front Button Set")     # label, not key → error (keys only)
    rc, prods = run([ROW], stockroom={"products": [bad]})
    assert rc == 1 and prods is None
    bad2 = dict(SR_PRODUCT, category="outerwear")
    rc, prods = run([ROW], stockroom={"products": [bad2]})
    assert rc == 1 and prods is None


def test_stockroom_overrides_workbook_same_id():
    sr_cs = {"id": "cs250a-min-red", "article": "CS250A", "brand": "Melini", "category": "round-neck",
             "type": "Cord Set", "colour": "Min.Red", "features": "", "sizes": [{"size": "M", "mrp": 1515}],
             "stock": {"M": 5}, "inStock": True, "offerPrice": None, "notes": "", "images": []}
    rc, prods = run([ROW], stockroom={"products": [sr_cs]})
    assert rc == 0 and len(prods) == 1
    p = prods[0]
    assert p["category"] == "round-neck" and p["price"] == 1515 and p["stockQty"] == 5 and p["sizes"] == ["M"]


def test_missing_stockroom_builds_from_workbook():
    rc, prods = run([ROW])          # no stockroom.json written → workbook alone, cleanly
    assert rc == 0 and [p["id"] for p in prods] == ["cs250a-min-red"]


def test_empty_catalogue_is_refused():
    rows = [ROW + ["FALSE"]]                       # the only product is unpublished → nothing to show
    rc, prods = run(rows, ["Published"])
    assert rc == 1 and prods is None, "an empty catalogue must never be written"
    rc, prods = run([], ["Published"])            # empty live sheet, no stockroom.json
    assert rc == 1 and prods is None


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
