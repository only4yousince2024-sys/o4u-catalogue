# O4U Increment 05 — accept products coming from Stockroom

Paste this into the website chat. Read `AGENTS.md` first; every rule there still applies.

## Context

Products are now captured on the phone with a tool called **O4U Stockroom** and
written into `O4U_Stock_Inventory_UPDATED_v2.xlsx` by the inventory chat. The
workbook stays the single source of truth. `products.js` is still generated
only by `scripts/build_catalogue.py`.

The inventory chat writes rows like this, one row per size:

| Article No. | Brand | Description | Shade / Color | Size | Available Sizes | MRP (₹) | Stock Qty | Category | Offer Price | Published | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 14560B | Sweet Pini | Satin Nightsuit | Black Pink Geometric | XL | XL, XXL | 1589 | 1 | front-button | | FALSE | |
| 14560B | Sweet Pini | Satin Nightsuit | Black Pink Geometric | XXL | XL, XXL | 1689 | 1 | front-button | | FALSE | |
| O4U-NB-0001 | | Cotton Lycra T-shirt & Pants Set | Red White | Free Size | Free Size | 1490 | 1 | tshirt-lower | | FALSE | |

Product IDs are unchanged: slug of article + colour (`14560b-black-pink-geometric`).
Images arrive in `website/images/` named `<pid>.jpg`, `<pid>-2.jpg` … `<pid>-5.jpg`.

## Changes needed in `scripts/build_catalogue.py`

1. **Optional `Category` column.** Add `"category": ["category", "web category", "website category"]`
   to `COLUMN_ALIASES`. When a row has a value, it must be one of the six
   category keys or labels (`front-button` or `Front Button Set`, …) and it
   overrides `CATEGORY_MAP`. An unknown value is a build error. A blank value
   falls back to `CATEGORY_MAP` exactly as today. Rows in one product that
   disagree on category are a build error.

2. **Free Size.** Add a `FREE` size to the vocabulary, ranked after `5XL`, with
   aliases `FREE SIZE`, `FREESIZE`, `ONE SIZE`, `FREE`. Emit it as `"Free Size"`
   in `products.js` `sizes`. Do **not** alias `FS`: on Sweet Pini tags `FS` means
   full sleeves, not free size. Update the frontend size chips and the WhatsApp
   order line so "Free Size" displays correctly.

3. **Non-branded products (`O4U-NB-####`).** Articles starting with `O4U-NB-` are
   the shop's own non-branded items. A blank brand on these is expected: no
   warning, and `brand` is emitted as `""`. The frontend must hide the brand
   line when `brand` is empty, and never show any other brand name for them.

4. **New brand.** Add `"sweet pini": "Sweet Pini"` to `BRAND_MAP`.

5. **Published column.** The inventory chat will add a `Published` column. Old
   rows will have it blank, and blank must keep meaning TRUE so nothing
   disappears. New Stockroom rows arrive as FALSE until the owner switches them
   on. Confirm this with a test.

6. **Tests.** Add cases to `scripts/test_build_catalogue.py` for:
   - Category column override
   - An unknown Category value causing an error
   - Free Size parsing and ordering
   - An O4U-NB product with blank brand building without warnings
   - A blank Published value staying published

## Still open (not part of this increment)

Article **7724090-F** is still used by two different products (rows 210–212 vs
215–217). The build keeps failing until the owner checks the physical tag and
the workbook is fixed. Don't relax the duplicate rule.

## Done when

- `python scripts/test_build_catalogue.py` passes
- `python scripts/build_catalogue.py` builds with the example rows above
- The site shows Free Size and hides an empty brand
