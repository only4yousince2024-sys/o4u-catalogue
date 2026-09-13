"""
O4U — Auto Product Generator
=============================
Reads your Excel stock file, cleans it up, auto-selects the best
products per category, and writes a ready-to-use products.js

HOW TO USE:
1. Place your Excel file in the same folder as this script
   and update EXCEL_FILE below if needed
2. Place all your product images in the "raw_photos" folder
   (name them to match the Image URL column in your sheet)
3. Run: python auto_generate_products.py
4. It writes products.js automatically — refresh your website!

STEPS:
  Step 1 — reads & cleans Excel
  Step 2 — groups into unique products
  Step 3 — picks best per website category
  Step 4 — writes products.js
"""

import openpyxl
import json
import os

# ── CONFIG ──────────────────────────────────────────────────────────
EXCEL_FILE    = "O4U_Stock_Inventory_UPDATED_v2.xlsx"
IMAGES_FOLDER = "images"          # where your product images live
MAX_PRODUCTS  = 12                # max products to show on website
# ────────────────────────────────────────────────────────────────────


# ── BRAND NAME CLEANUP ───────────────────────────────────────────────
BRAND_MAP = {
    "sweet & touch":  "Sweet Touch",
    "sweet touch":    "Sweet Touch",
    "sweettouch":     "Sweet Touch",
    "melini":         "Melini",
    "zaps / j.t. international": "Zaps",
    "zaps":           "Zaps",
}

def clean_brand(b):
    if not b: return "Unknown"
    return BRAND_MAP.get(str(b).strip().lower(), str(b).strip())


# ── CATEGORY CLEANUP + WEBSITE FILTER MAPPING ────────────────────────
# Maps raw Excel description → website filter key + display name
CATEGORY_MAP = {
    "cord set":                          ("front-button",  "Front Button Set"),
    "co-ord set":                        ("front-button",  "Front Button Set"),
    "premium co-ord set":                ("front-button",  "Front Button Set"),
    "premium co-ord set (cotton)":       ("front-button",  "Front Button Set"),
    "cotton lycra premium co-ord set":   ("front-button",  "Front Button Set"),
    "rayon co-ord set / capri suit":     ("front-button",  "Front Button Set"),
    "premium lounge wear button-up combo":("front-button", "Front Button Set"),

    "night suit":                        ("round-neck",    "Round Neck"),
    "capri night suit":                  ("round-neck",    "Round Neck"),
    "premium lounge wear":               ("round-neck",    "Round Neck"),
    "premium lounge wear (t+pants)":     ("tshirt-lower",  "T-Shirt / Lower"),

    "kurta salwar":                      ("salwar-set",    "Salwar Set"),
    "kurta set":                         ("salwar-set",    "Salwar Set"),
    "long kurta set":                    ("salwar-set",    "Salwar Set"),
    "kurta plazzo":                      ("salwar-set",    "Salwar Set"),

    "afgaan suit":                       ("salwar-set",    "Salwar Set"),
    "afgani suit":                       ("salwar-set",    "Salwar Set"),
    "affgani suit":                      ("salwar-set",    "Salwar Set"),

    "short kurti":                       ("collar-neck",   "Collar Neck"),
    "premium kurti":                     ("collar-neck",   "Collar Neck"),
    "long kurti":                        ("collar-neck",   "Collar Neck"),
    "denim long kurti":                  ("collar-neck",   "Collar Neck"),
    "denim short kurti":                 ("collar-neck",   "Collar Neck"),

    "gym wear":                          ("tshirt-shorts", "T-Shirt / Shorts"),
}

def clean_category(desc):
    if not desc: return ("front-button", "Front Button Set")
    return CATEGORY_MAP.get(str(desc).strip().lower(),
                            ("front-button", "Front Button Set"))


# ── SIZE ORDERING ─────────────────────────────────────────────────────
SIZE_ORDER = ["XS","S","M","L","XL","2XL","3XL","4XL","5XL"]

def sort_sizes(sizes_str):
    if not sizes_str: return []
    parts = str(sizes_str).strip().split()
    ordered = [s for s in SIZE_ORDER if s in parts]
    others  = [s for s in parts if s not in SIZE_ORDER]
    return ordered + others


# ── SCORE: pick best products ─────────────────────────────────────────
def score_product(p):
    score = 0
    # More sizes available = better
    score += len(p["available_sizes"]) * 10
    # Has image = better
    if p["image"] and os.path.exists(os.path.join(IMAGES_FOLDER, p["image"])):
        score += 50
    elif p["image"]:
        score += 20  # at least has a filename
    # Higher MRP generally = better quality
    score += min((p["mrp"] or 0) / 100, 15)
    return score


# ── MAIN ──────────────────────────────────────────────────────────────
def main():
    print("\n📦 Reading Excel file...")

    if not os.path.exists(EXCEL_FILE):
        print(f"  ✗ Could not find '{EXCEL_FILE}' — place it in the same folder.")
        return

    wb = openpyxl.load_workbook(EXCEL_FILE)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))[2:]  # skip title + header

    # Step 1 — group into unique products (article + description + color)
    print("🔍 Grouping into unique products...")
    products = {}
    for row in rows:
        if not (row[0] and isinstance(row[0], (int, float))): continue
        article  = str(row[2] or "").strip()
        desc     = str(row[3] or "").strip()
        color    = str(row[4] or "").strip()
        key      = f"{article}|{desc}|{color}"

        if key not in products:
            cat_key, cat_name = clean_category(desc)
            products[key] = {
                "id":              None,
                "brand":           clean_brand(row[1]),
                "article":         article,
                "description":     desc,
                "color":           color,
                "category_key":    cat_key,
                "category_name":   cat_name,
                "mrp":             int(row[7]) if row[7] else 0,
                "image":           str(row[11]).strip() if row[11] else "",
                "available_sizes": set(),
                "style_code":      str(row[10] or "").strip(),
            }
        if row[5]:
            products[key]["available_sizes"].add(str(row[5]).strip())

    print(f"  ✓ Found {len(products)} unique product variants")

    # Step 2 — pick best per website category
    print("⭐ Selecting best products per category...")
    by_category = {}
    for p in products.values():
        cat = p["category_key"]
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(p)

    selected = []
    for cat, items in by_category.items():
        items_sorted = sorted(items, key=score_product, reverse=True)
        # Take top 2 per category
        selected.extend(items_sorted[:2])

    # Sort final selection by category then score
    selected = sorted(selected, key=lambda p: (p["category_key"], -score_product(p)))

    # Limit to MAX_PRODUCTS
    selected = selected[:MAX_PRODUCTS]

    print(f"  ✓ Selected {len(selected)} products for website")

    # Step 3 — write products.js
    print("✍️  Writing products.js...")
    lines = []
    lines.append("// ╔═══════════════════════════════════════════════════════════════╗")
    lines.append("// ║         ONLY 4 YOU — AUTO-GENERATED PRODUCT DATABASE          ║")
    lines.append("// ║         Generated by auto_generate_products.py                ║")
    lines.append("// ║  To regenerate: python auto_generate_products.py              ║")
    lines.append("// ╚═══════════════════════════════════════════════════════════════╝")
    lines.append("")
    lines.append("const PRODUCTS = [")

    for i, p in enumerate(selected):
        pid        = f"w{i+1}"
        sizes      = sort_sizes(" ".join(p["available_sizes"]))
        img_file   = p["image"] if p["image"] else "placeholder.jpg"
        # Build display name from description + color
        name       = f"{p['color']} {p['description']}"
        brand_line = f"by {p['brand']}" if p['brand'] != "Unknown" else ""
        desc_text  = f"{p['description']} in {p['color']}. {brand_line}. Soft & comfortable fabric.".strip()

        obj = f"""  {{
    id:          "{pid}",
    name:        "{name}",
    category:    "{p['category_key']}",
    price:       {p['mrp']},
    mrp:         null,
    image:       "images/{img_file}",
    description: "{desc_text}",
    badge:       "",
    badgeStyle:  "",
    sizes:       {json.dumps(sizes)},
    colors:      [{json.dumps(p['color'])}],
    inStock:     true
  }}"""
        lines.append(obj + ("," if i < len(selected) - 1 else ""))

    lines.append("];")
    lines.append("")

    output = "\n".join(lines)
    with open("products.js", "w", encoding="utf-8") as f:
        f.write(output)

    print("  ✓ products.js written!")
    print()
    print("=" * 50)
    print(f"✅ Done! {len(selected)} products ready for website.")
    print()
    print("Selected products:")
    for p in selected:
        img_status = "✓ image" if p['image'] else "✗ no image"
        print(f"  [{p['category_name']:20s}] {p['color']} {p['description']} — ₹{p['mrp']} ({img_status})")
    print()
    print("Next: Add product images to your 'images' folder,")
    print("      then redeploy the folder to Netlify.")
    print("=" * 50)


if __name__ == "__main__":
    main()
