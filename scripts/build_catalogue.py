#!/usr/bin/env python3
"""
O4U — Catalogue build
=====================

    python scripts/build_catalogue.py [--workbook PATH] [--out PATH] [--images-dir PATH]

Reads the stock workbook (the SINGLE SOURCE OF TRUTH), cleans and validates
every row, groups rows into products keyed by ARTICLE + COLOUR, discovers
product images by Product ID, and writes  website/products.js.

    O4U_Stock_Inventory_UPDATED_v2.xlsx      (project root)
            ↓
    scripts/build_catalogue.py               clean → normalise → validate → generate
            ↓
    website/products.js                      generated — never hand-edit

Rules that matter (see AGENTS.md for the full list):
  • Product identity is article + colour. Article numbers alone repeat.
  • Product ID = slug(article + colour). Stable across builds, never index-based.
  • Image filenames are DERIVED from the Product ID:  <pid>.jpg, <pid>-2.jpg … <pid>-9.jpg
  • Errors block the build (exit 1, products.js NOT written). Warnings do not.
  • Missing COLUMNS default safely (Published → TRUE). Missing VALUES warn.
  • `published` is an explicit column — never derived from images/stock.
  • No product cap. Every published product is emitted.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path

try:
    import openpyxl
except ImportError:  # pragma: no cover
    sys.exit("openpyxl is required:  python -m pip install openpyxl")

# Windows consoles default to cp1252; the workbook has ₹ and — in it.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKBOOK = ROOT / "O4U_Stock_Inventory_UPDATED_v2.xlsx"
DEFAULT_OUT = ROOT / "website" / "products.js"
DEFAULT_IMAGES_DIR = ROOT / "website" / "images"
PREFERRED_SHEET = "Stock Inventory"

# ── Vocabulary ───────────────────────────────────────────────────────────────
SIZE_ORDER = ["XS", "S", "M", "L", "XL", "2XL", "3XL", "4XL", "5XL"]
SIZE_ALIASES = {
    "XXS": "XS",
    "XXL": "2XL",
    "XXXL": "3XL",
    "XXXXL": "4XL",
    "XXXXXL": "5XL",
}
SIZE_RANK = {s: i for i, s in enumerate(SIZE_ORDER)}

CATEGORIES = OrderedDict([
    ("front-button", "Front Button Set"),
    ("round-neck", "Round Neck"),
    ("collar-neck", "Collar Neck"),
    ("salwar-set", "Salwar Set"),
    ("tshirt-lower", "T-Shirt / Lower"),
    ("tshirt-shorts", "T-Shirt / Shorts"),
])

# Normalised workbook Description → category key. Unknown = build error.
CATEGORY_MAP = {
    # Front Button Set
    "cord set": "front-button",
    "co-ord set": "front-button",
    "coord set": "front-button",
    "co-ord set (embroidered)": "front-button",
    "premium co-ord set": "front-button",
    "premium co-ord set (cotton)": "front-button",
    "cotton lycra premium co-ord set": "front-button",
    "rayon co-ord set": "front-button",
    "rayon co-ord set / capri suit": "front-button",
    "premium lounge wear button-up combo": "front-button",
    # Round Neck
    "night suit": "round-neck",
    "capri night suit": "round-neck",
    "premium lounge wear": "round-neck",
    # Collar Neck
    "short kurti": "collar-neck",
    "long kurti": "collar-neck",
    "premium kurti": "collar-neck",
    "denim short kurti": "collar-neck",
    "denim long kurti": "collar-neck",
    # Salwar Set
    "kurta salwar": "salwar-set",
    "kurta set": "salwar-set",
    "long kurta set": "salwar-set",
    "kurta plazzo": "salwar-set",
    "kurta palazzo": "salwar-set",
    "afgaan suit": "salwar-set",
    "afgani suit": "salwar-set",
    "affgani suit": "salwar-set",
    "afghani suit": "salwar-set",
    # T-Shirt / Lower
    "premium lounge wear (t+pants)": "tshirt-lower",
    "t-shirt / lower": "tshirt-lower",
    "tshirt lower": "tshirt-lower",
    # T-Shirt / Shorts
    "gym wear": "tshirt-shorts",
    "t-shirt / shorts": "tshirt-shorts",
    "tshirt shorts": "tshirt-shorts",
}

BRAND_MAP = {
    "sweet & touch": "Sweet Touch",
    "sweet and touch": "Sweet Touch",
    "sweet touch": "Sweet Touch",
    "sweettouch": "Sweet Touch",
    "melini": "Melini",
    "zaps / j.t. international": "Zaps",
    "zaps": "Zaps",
}

# Header aliases (normalised: lowercase, collapsed whitespace, no punctuation)
COLUMN_ALIASES = {
    "sno":             ["s no", "sno", "sr no", "sr", "no", "sl no"],
    "brand":           ["brand"],
    "article":         ["article no", "article", "article number", "art no", "art"],
    "description":     ["description", "desc", "product type", "type", "product"],
    "colour":          ["shade color", "shade colour", "colour", "color", "shade"],
    "size":            ["size"],
    "available_sizes": ["available sizes", "avail sizes", "sizes", "size range"],
    "mrp":             ["mrp", "mrp rs", "mrp inr", "m r p"],
    "stock_qty":       ["stock qty", "stock", "qty", "quantity", "stock quantity"],
    "selling_price":   ["selling price", "sell price", "price", "sp"],
    "offer_price":     ["offer price", "offer", "sale price", "discount price"],
    "published":       ["published", "publish", "web", "show on website", "online", "live"],
    "notes":           ["notes", "note", "remarks"],
}
REQUIRED_COLUMNS = ["article", "description", "colour", "available_sizes", "mrp", "stock_qty"]
OPTIONAL_COLUMNS = ["sno", "brand", "size", "notes"]
SHOP_COLUMNS = {           # column absent → default (§5.2)
    "selling_price": "falls back to MRP",
    "offer_price": "blank (no discount shown)",
    "published": "TRUE (everything published)",
}

IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".webp"]
MAX_GALLERY = 9


# ── Diagnostics ──────────────────────────────────────────────────────────────
class Diag:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


# ── Cleaning helpers ─────────────────────────────────────────────────────────
def clean_str(v) -> str | None:
    """Trim a cell to a string; blanks (and None) become None."""
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    s = re.sub(r"\s+", " ", s)
    return s or None


def norm_key(s: str | None) -> str:
    """Normalise headers / descriptions for lookup: lowercase, punctuation → space."""
    if not s:
        return ""
    s = s.lower().replace("₹", " ").replace("&", " and ")
    s = re.sub(r"[^a-z0-9()+/.\- ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def header_key(s: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", norm_key(s))).strip()


def slugify(*parts: str | None) -> str:
    """Product ID: lowercase slug of article + colour. & → and, non-alnum runs → '-'."""
    joined = " ".join(p for p in parts if p)
    joined = joined.lower().replace("&", "and")
    joined = re.sub(r"[^a-z0-9]+", "-", joined)
    return joined.strip("-")


def parse_money(v, what: str, where: str, diag: Diag, *, required: bool) -> int | None:
    """₹ amounts: accept int/float/'₹1,415'/'1415.00'. Invalid → error."""
    s = clean_str(v)
    if s is None:
        if required:
            diag.error(f"{where}: {what} is blank")
        return None
    s2 = re.sub(r"[₹,\s]|rs\.?|inr", "", s, flags=re.I)
    try:
        n = float(s2)
    except ValueError:
        diag.error(f"{where}: {what} is not a number: {s!r}")
        return None
    if n <= 0:
        diag.error(f"{where}: {what} must be positive, got {s!r}")
        return None
    return int(round(n))


def parse_int(v, what: str, where: str, diag: Diag) -> int | None:
    s = clean_str(v)
    if s is None:
        return None
    try:
        n = float(s.replace(",", ""))
    except ValueError:
        diag.error(f"{where}: {what} is not a number: {s!r}")
        return None
    if n < 0:
        diag.error(f"{where}: {what} is negative: {s!r}")
        return None
    return int(round(n))


def parse_bool(v, where: str, diag: Diag) -> bool | None:
    """Published flag. Blank → None (caller defaults + warns). Invalid → error."""
    if isinstance(v, bool):
        return v
    s = clean_str(v)
    if s is None:
        return None
    t = s.strip().lower()
    if t in ("true", "yes", "y", "1", "✓", "✔", "published", "live", "on"):
        return True
    if t in ("false", "no", "n", "0", "✗", "✘", "x", "unpublished", "hidden", "off"):
        return False
    diag.error(f"{where}: Published is not a valid boolean: {s!r}")
    return None


# ── Size parser — ONE function, used for both Size and Available Sizes ───────
_RANGE_SEP = re.compile(r"\s*(?:\bto\b|-|–|—)\s*", re.I)


def _canon_size(tok: str) -> str | None:
    t = tok.strip().upper().replace(" ", "")
    t = SIZE_ALIASES.get(t, t)
    return t if t in SIZE_RANK else None


def parse_sizes(raw, where: str, diag: Diag) -> list[str]:
    """
    'M L XL 2XL'      → ['M','L','XL','2XL']
    'S to 3XL'        → ['S','M','L','XL','2XL','3XL']
    'L-3XL' / 'M–3XL' → expanded
    'XXL'             → ['2XL']
    Returns canonical-ordered, de-duplicated list. Invalid tokens / malformed
    ranges are errors. 'to' is never emitted as a size.
    """
    s = clean_str(raw)
    if s is None:
        return []
    s = s.replace("–", "-").replace("—", "-")
    found: set[str] = set()

    # Split into list items on commas / semicolons / pipes / slashes.
    for item in re.split(r"[,;|/]+", s):
        item = item.strip()
        if not item:
            continue
        # Tokenise on whitespace; glue 'X to Y' and 'X-Y' into ranges.
        toks = [t for t in re.split(r"\s+", item) if t]
        i = 0
        while i < len(toks):
            tok = toks[i]
            lo = hi = None
            if tok.lower() == "to":
                diag.error(f"{where}: malformed size range {item!r} (dangling 'to')")
                i += 1
                continue
            if i + 2 < len(toks) and toks[i + 1].lower() == "to":
                lo, hi = tok, toks[i + 2]
                i += 3
            elif i + 2 < len(toks) and toks[i + 1] == "-":
                lo, hi = tok, toks[i + 2]
                i += 3
            elif "-" in tok and tok.count("-") == 1 and not tok.startswith("-") and not tok.endswith("-"):
                lo, hi = tok.split("-")
                i += 1
            elif i + 1 < len(toks) and toks[i + 1].lower() == "to":
                diag.error(f"{where}: malformed size range {item!r}")
                i = len(toks)
                continue
            else:
                c = _canon_size(tok)
                if c is None:
                    diag.error(f"{where}: unknown size token {tok!r} in {s!r}")
                else:
                    found.add(c)
                i += 1
                continue
            a, b = _canon_size(lo), _canon_size(hi)
            if a is None or b is None or SIZE_RANK[a] > SIZE_RANK[b]:
                diag.error(f"{where}: malformed size range {lo!r}-{hi!r} in {s!r}")
                continue
            for k in range(SIZE_RANK[a], SIZE_RANK[b] + 1):
                found.add(SIZE_ORDER[k])
    return sorted(found, key=SIZE_RANK.__getitem__)


# ── Workbook reading ─────────────────────────────────────────────────────────
def find_sheet(wb, diag: Diag):
    if PREFERRED_SHEET in wb.sheetnames:
        return wb[PREFERRED_SHEET]
    ws = wb.worksheets[0]
    diag.warn(f"Sheet {PREFERRED_SHEET!r} not found — using first sheet {ws.title!r}")
    return ws


def find_header(ws, diag: Diag) -> tuple[int, dict[str, int]] | None:
    """Locate the header row (first 15 rows) and map logical names → column index."""
    alias_lookup = {a: k for k, al in COLUMN_ALIASES.items() for a in al}
    for r in range(1, min(ws.max_row, 15) + 1):
        cells = [header_key(clean_str(c.value)) for c in ws[r]]
        if "article no" in cells or "article" in cells:
            colmap: dict[str, int] = {}
            for idx, h in enumerate(cells):
                if not h:
                    continue
                key = alias_lookup.get(h)
                if key and key not in colmap:
                    colmap[key] = idx
            return r, colmap
    diag.error("Could not find a header row containing 'Article No.' in the first 15 rows")
    return None


def read_rows(ws, header_row: int, colmap: dict[str, int], diag: Diag) -> list[dict]:
    rows = []
    for r_idx, row in enumerate(ws.iter_rows(min_row=header_row + 1, values_only=True), start=header_row + 1):
        if all(clean_str(v) is None for v in row):
            continue
        where = f"row {r_idx}"

        def cell(key):
            i = colmap.get(key)
            return row[i] if i is not None and i < len(row) else None

        # Misaligned row: S.No blank but the Brand cell holds a number → the
        # whole row is shifted one column to the right. Do not guess. Skip + warn.
        if "sno" in colmap and clean_str(cell("sno")) is None:
            b = cell("brand") if "brand" in colmap else None
            if isinstance(b, (int, float)) or (clean_str(b) or "").isdigit():
                diag.warn(f"{where}: columns are shifted (S.No blank, Brand holds {clean_str(b)!r}) — row skipped. Fix the workbook.")
                continue

        article = clean_str(cell("article"))
        desc = clean_str(cell("description"))
        colour = clean_str(cell("colour"))
        if article is None:
            diag.error(f"{where}: Article No. is blank")
            continue
        if desc is None:
            diag.error(f"{where}: Description is blank (article {article})")
            continue

        rows.append({
            "row": r_idx,
            "sno": clean_str(cell("sno")),
            "brand": clean_str(cell("brand")),
            "article": article,
            "description": desc,
            "colour": colour,
            "size_raw": cell("size"),
            "avail_raw": cell("available_sizes"),
            "mrp": parse_money(cell("mrp"), "MRP", where, diag, required=True),
            "stock_qty": cell("stock_qty"),
            "selling_price": cell("selling_price") if "selling_price" in colmap else None,
            "offer_price": cell("offer_price") if "offer_price" in colmap else None,
            "published": cell("published") if "published" in colmap else None,
            "notes": clean_str(cell("notes")),
        })
    return rows


# ── Grouping into products ───────────────────────────────────────────────────
def clean_brand(b: str | None) -> str | None:
    if not b:
        return None
    return BRAND_MAP.get(b.strip().lower(), b.strip())


def category_for(desc: str, where: str, diag: Diag) -> str | None:
    key = CATEGORY_MAP.get(norm_key(desc))
    if key is None:
        diag.error(f"{where}: unknown category for description {desc!r} — add it to CATEGORY_MAP in scripts/build_catalogue.py")
    return key


def find_images(pid: str, images_dir: Path) -> list[str]:
    """<pid>.<ext>, then <pid>-2.<ext> … <pid>-9.<ext>, in order. First ext wins."""
    out = []
    for n in range(1, MAX_GALLERY + 1):
        stem = pid if n == 1 else f"{pid}-{n}"
        for ext in IMAGE_EXTS:
            if (images_dir / f"{stem}{ext}").is_file():
                out.append(f"images/{stem}{ext}")
                break
    return out


def build_products(rows: list[dict], colmap: dict[str, int], images_dir: Path, diag: Diag) -> list[dict]:
    has_sell = "selling_price" in colmap
    has_offer = "offer_price" in colmap
    has_pub = "published" in colmap

    groups: "OrderedDict[tuple[str, str], list[dict]]" = OrderedDict()
    for r in rows:
        groups.setdefault((r["article"], r["colour"] or ""), []).append(r)

    products = []
    seen_ids: dict[str, tuple[str, str]] = {}
    for (article, colour), rs in groups.items():
        first = rs[0]
        rownums = ", ".join(str(r["row"]) for r in rs)
        where = f"{article} + {colour or '(no colour)'} (rows {rownums})"

        # Identity ---------------------------------------------------------
        descs = sorted({r["description"] for r in rs})
        if len(descs) > 1:
            diag.error(
                f"DUPLICATE article+colour {article} + {colour!r}: {len(descs)} different products share this key → "
                + " | ".join(f"{d!r} ₹{next(r['mrp'] for r in rs if r['description'] == d)}" for d in descs)
                + f" (rows {rownums}). This is a source data error — fix the workbook."
            )
            continue
        desc = descs[0]
        if not colour:
            diag.warn(f"{where}: colour is blank — Product ID derived from article alone")
        pid = slugify(article, colour)
        if pid in seen_ids:
            diag.error(f"{where}: Product ID {pid!r} collides with {seen_ids[pid]}")
            continue
        seen_ids[pid] = (article, colour)

        brands = sorted({clean_brand(r["brand"]) for r in rs if r["brand"]})
        if len(brands) > 1:
            diag.warn(f"{where}: multiple brands {brands} — using {brands[0]!r}")
        brand = brands[0] if brands else None
        if brand is None:
            diag.warn(f"{where}: brand is blank")

        category = category_for(desc, where, diag)
        if category is None:
            continue

        # Sizes: union of Available Sizes and Size across all rows ---------
        sizes: set[str] = set()
        for r in rs:
            sizes.update(parse_sizes(r["avail_raw"], f"row {r['row']} Available Sizes", diag))
            sizes.update(parse_sizes(r["size_raw"], f"row {r['row']} Size", diag))
        sizes_list = sorted(sizes, key=SIZE_RANK.__getitem__)
        if not sizes_list:
            diag.warn(f"{where}: no sizes found in Size / Available Sizes")

        # MRP (may vary by size — record it, never flatten silently) -------
        mrps = [r["mrp"] for r in rs if r["mrp"] is not None]
        if not mrps:
            continue  # parse_money already logged the error
        mrp_base = min(mrps)
        size_prices: dict[str, int] = {}
        if len(set(mrps)) > 1:
            for r in rs:
                if r["mrp"] is None:
                    continue
                for s in parse_sizes(r["size_raw"], f"row {r['row']} Size", Diag()):
                    size_prices.setdefault(s, r["mrp"])
            size_prices = {s: p for s, p in size_prices.items() if p != mrp_base}

        # Stock ------------------------------------------------------------
        stock = 0
        for r in rs:
            q = parse_int(r["stock_qty"], "Stock Qty", f"row {r['row']}", diag)
            if q is None and clean_str(r["stock_qty"]) is None:
                diag.warn(f"row {r['row']}: Stock Qty blank — treated as 0")
                q = 0
            stock += q or 0

        # Shop-controlled columns -----------------------------------------
        def first_value(key):
            vals = [r[key] for r in rs if clean_str(r[key]) is not None]
            distinct = {clean_str(v) for v in vals}
            if len(distinct) > 1:
                diag.warn(f"{where}: conflicting {key.replace('_', ' ')} values {sorted(distinct)} — using first")
            return vals[0] if vals else None

        selling = parse_money(first_value("selling_price"), "Selling Price", where, diag, required=False) if has_sell else None
        offer = parse_money(first_value("offer_price"), "Offer Price", where, diag, required=False) if has_offer else None
        if has_sell and selling is None:
            diag.warn(f"{where}: Selling Price blank — using MRP ₹{mrp_base}")

        if offer is not None:
            price, mrp_out = offer, (selling or mrp_base)
            if price >= mrp_out:
                diag.warn(f"{where}: Offer Price ₹{offer} is not below ₹{mrp_out} — no discount shown")
                price, mrp_out = offer, None
            size_prices = {}
        elif selling is not None:
            price, mrp_out = selling, None
            size_prices = {}
        else:
            price, mrp_out = mrp_base, None

        pub_raw = first_value("published") if has_pub else None
        published = parse_bool(pub_raw, where, diag)
        if published is None:
            if has_pub:
                diag.warn(f"{where}: Published blank — treated as TRUE")
            published = True

        # Images (derived from Product ID) ---------------------------------
        images = find_images(pid, images_dir)
        if not images and published:
            diag.warn(f"{where}: no image found (expected images/{pid}.jpg) — placeholder will show")

        # Text -------------------------------------------------------------
        name = f"{colour} {desc}" if colour else desc
        bits = [desc]
        if colour:
            bits.append(f"in {colour}")
        if brand:
            bits.append(f"by {brand}")
        description = " ".join(bits) + "."

        products.append({
            "id": pid,
            "article": article,
            "name": name,
            "brand": brand or "",
            "category": category,
            "description": description,
            "colors": [colour] if colour else [],
            "sizes": sizes_list,
            "price": price,
            "mrp": mrp_out,
            "sizePrices": size_prices,
            "images": images,
            "image": images[0] if images else "",
            "stockQty": stock,
            "published": published,
            "badge": "",
            "badgeStyle": "",
        })
    return products


# ── Output ───────────────────────────────────────────────────────────────────
def write_products_js(products: list[dict], out: Path, source: Path, counts: dict) -> None:
    published = [p for p in products if p["published"]]
    cats_present = [{"key": k, "label": v} for k, v in CATEGORIES.items() if any(p["category"] == k for p in published)]
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    body = json.dumps(published, indent=2, ensure_ascii=False)
    cats = json.dumps(cats_present, indent=2, ensure_ascii=False)
    header = (
        "// ╔═══════════════════════════════════════════════════════════════╗\n"
        "// ║   ONLY 4 YOU — GENERATED PRODUCT CATALOGUE. DO NOT HAND-EDIT.  ║\n"
        "// ║   Source : the stock workbook (single source of truth)         ║\n"
        "// ║   Build  : python scripts/build_catalogue.py                   ║\n"
        "// ╚═══════════════════════════════════════════════════════════════╝\n"
        f"// Generated {stamp} from {source.name}\n"
        f"// {counts['published']} published products · {counts['source_rows']} source rows\n\n"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(header + f"const CATEGORIES = {cats};\n\nconst PRODUCTS = {body};\n", encoding="utf-8")


def verify_output(out: Path) -> None:
    """The file is `const X = <json>;` blocks — re-parse the JSON to prove it is valid JS."""
    text = out.read_text(encoding="utf-8")
    for name in ("CATEGORIES", "PRODUCTS"):
        m = re.search(rf"const {name} = (.*?);\n(?=\n|const |$)", text, re.S)
        if not m:
            raise RuntimeError(f"{out}: could not find `const {name}`")
        json.loads(m.group(1))


# ── Main ─────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build website/products.js from the stock workbook.")
    ap.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK, help="source workbook (default: root O4U_Stock_Inventory_UPDATED_v2.xlsx)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output JS file (default: website/products.js)")
    ap.add_argument("--images-dir", type=Path, default=DEFAULT_IMAGES_DIR, help="web images folder (default: website/images)")
    ap.add_argument("--quiet", action="store_true", help="only print the summary")
    args = ap.parse_args(argv)

    diag = Diag()
    if not args.workbook.is_file():
        print(f"ERROR: workbook not found: {args.workbook}")
        return 1
    if not args.images_dir.is_dir():
        diag.warn(f"images folder not found: {args.images_dir} — every product will use the placeholder")

    wb = openpyxl.load_workbook(args.workbook, data_only=True, read_only=True)
    ws = find_sheet(wb, diag)
    hdr = find_header(ws, diag)
    products: list[dict] = []
    rows: list[dict] = []
    if hdr:
        header_row, colmap = hdr
        for key in REQUIRED_COLUMNS:
            if key not in colmap:
                diag.error(f"Required column missing: {key.replace('_', ' ').title()!r} (header row {header_row})")
        for key in OPTIONAL_COLUMNS:
            if key not in colmap and key != "sno":
                diag.warn(f"Optional column missing: {key.replace('_', ' ').title()!r}")
        for key, default in SHOP_COLUMNS.items():
            if key not in colmap:
                diag.warn(f"Column {key.replace('_', ' ').title()!r} is missing — default: {default}")
        if not diag.errors:
            rows = read_rows(ws, header_row, colmap, diag)
            products = build_products(rows, colmap, args.images_dir, diag)

    published = [p for p in products if p["published"]]
    counts = {
        "source_rows": len(rows),
        "variants": len(products),
        "published": len(published),
        "unpublished": len(products) - len(published),
        "missing_images": sum(1 for p in published if not p["images"]),
        "zero_stock": sum(1 for p in published if p["stockQty"] <= 0),
        "size_priced": sum(1 for p in published if p["sizePrices"]),
        "warnings": len(diag.warnings),
        "errors": len(diag.errors),
    }

    ok = not diag.errors
    if ok:
        write_products_js(products, args.out, args.workbook, counts)
        try:
            verify_output(args.out)
        except Exception as e:  # pragma: no cover
            diag.error(f"output verification failed: {e}")
            ok = False
            counts["errors"] = len(diag.errors)

    if not args.quiet:
        if diag.warnings:
            print(f"\nWARNINGS ({len(diag.warnings)})")
            for w in diag.warnings:
                print(f"  ⚠ {w}")
        if diag.errors:
            print(f"\nERRORS ({len(diag.errors)})")
            for e in diag.errors:
                print(f"  ✖ {e}")

    print("\nO4U CATALOGUE BUILD")
    print(f"  Workbook              {args.workbook.name}")
    print(f"  Source rows           {counts['source_rows']}")
    print(f"  Unique variants       {counts['variants']}")
    print(f"  Published             {counts['published']}")
    print(f"  Unpublished           {counts['unpublished']}")
    print(f"  Missing images        {counts['missing_images']}")
    print(f"  Zero stock            {counts['zero_stock']}")
    print(f"  Size-priced variants  {counts['size_priced']}")
    print(f"  Warnings              {counts['warnings']}")
    print(f"  Errors                {counts['errors']}")
    if ok:
        print(f"\n  ✔ wrote {args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out}")
        return 0
    print(f"\n  ✖ BUILD FAILED — {args.out.name} NOT written. Fix the errors above and re-run.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
