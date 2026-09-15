# O4U — Stockroom → Website automation

Two prompts. **A** goes to the Stockroom chat, **B** to the website chat. Do A first.

---

## What I found

Your Stockroom artifact already has almost everything:

- `products` collection — `id`, `article`, `brand`, `brandCode`, `category`, `colour`, `type`, `features`, `sizes[{size, mrp, barcode}]`, `stock`, `offerPrice`, `inStock`, `published`, `flags`, `notes`, `refPhoto`, `extraRefPhotos`, `tagPhotos`, `webImages[]`, `createdAt`, `updatedAt`
- Product IDs generated with the **same slug rule as `build_catalogue.py`** — the two already agree
- Web images named `<id>.jpg`, `<id>-2.jpg` … `<id>-5.jpg` — exactly what the build expects
- A ZIP download of those images
- `readcopies` — small base64 tag photos so Claude can read tags from chat

**The one missing link: product data never leaves the artifact.** Images come out; the article numbers, prices and sizes don't. That's the whole gap.

---

# PROMPT A — for the Stockroom chat

```
Add a data export to the Stockroom so the website build can consume it.

Right now "Download all (.zip)" exports only the website images. Product data
never leaves the artifact, so the catalogue build has nothing to read.

CHANGE: the same ZIP must also contain a file named stockroom.json at its root.

Contents — every product where published === true AND status !== "pending":

{
  "exportedAt": "<ISO timestamp>",
  "products": [
    {
      "id": "14560b-black-pink-geometric",
      "article": "14560B",
      "brand": "Sweet Pini",
      "category": "front-button",
      "type": "Satin Nightsuit",
      "colour": "Black Pink Geometric",
      "features": "Full sleeves, button-up",
      "sizes": [
        {"size": "XL",  "mrp": 1589, "barcode": "..."},
        {"size": "XXL", "mrp": 1689, "barcode": "..."}
      ],
      "stock": {"XL": 2, "XXL": 1},
      "inStock": true,
      "offerPrice": null,
      "notes": "",
      "images": ["14560b-black-pink-geometric.jpg", "14560b-black-pink-geometric-2.jpg"]
    }
  ]
}

RULES
- "images" lists the FILENAMES the ZIP contains for that product, in order —
  not asset ids, not blob URLs. Only entries actually present in the ZIP.
- Non-branded products (article starting O4U-NB-) export "brand": "".
- Unpublished and pending products are excluded entirely.
- Numbers export as numbers, not strings. Blank MRP omits the key.
- Do not invent values. A field with no data is omitted or null.

ALSO
- Rename the button to "Download for website" so it reads as one action.
- After the download, toast: "Unzip into your ONLY 4 YOU folder, then run sync."
- Keep the per-product "Download these images" button as it is.

Do not change the capture flow, the tag reading, the product schema, or the
product ID rule — the ID must stay identical to slugify(article, colour) in
scripts/build_catalogue.py.
```

---

# PROMPT B — for the website chat

```
Read AGENTS.md first. Every rule there still applies.

Products are now created in the O4U Stockroom artifact, not in Excel. Stockroom
exports a ZIP containing website images plus stockroom.json (schema below).
Make the build consume it, and make deploying one step.

## 1. New source: stockroom.json

Add an optional source file at the project root: stockroom.json.

{ "exportedAt": "...", "products": [ { id, article, brand, category, type,
  colour, features, sizes:[{size,mrp,barcode}], stock:{}, inStock,
  offerPrice, notes, images:[filenames] } ] }

- When stockroom.json exists, it is the source of live products.
- The workbook stays the source for anything already in it, and remains the
  archive. If both contain the same product id, stockroom.json wins and the
  build says so in the report.
- Missing file is not an error — build from the workbook alone, with a warning.

Mapping to the product schema:
- id            → id, unchanged. Verify it equals slugify(article, colour);
                  a mismatch is a build ERROR naming both values.
- sizes[].size  → sizes[], through the existing size parser (Free → "Free Size")
- sizes[].mrp   → per-size pricing; the lowest becomes price when they differ,
                  and record the range exactly as the existing sizePrices does
- offerPrice    → when present: price = offerPrice, mrp = the tag MRP
- inStock       → stockQty: sum of stock{} when present, else 1 if inStock else 0
- images[]      → images[], prefixed "images/", in the given order
- brand ""      → emit "", no warning (non-branded)
- category      → must be one of the six keys; anything else is a build ERROR

Everything in stockroom.json is already published — it is exported only when
published is true. Do not re-apply a Published check to these rows.

## 2. One-step sync

Add sync.bat at the project root:

  1. run scripts/build_catalogue.py
  2. if it exits non-zero, print the errors and STOP — never deploy a failed build
  3. git add -A
  4. git commit -m "stock: <n> products, <timestamp>"  (skip if nothing changed)
  5. git push

Print what happened in plain language at each step. This is run by the shop
owner, not a developer — no stack traces, no silent failures.

## 3. Tests

Add to scripts/test_build_catalogue.py:
- stockroom.json products build correctly
- a stockroom id that disagrees with slugify(article, colour) is an error
- an unknown category is an error
- stockroom.json overriding a workbook product of the same id
- a missing stockroom.json building cleanly from the workbook

## Done when

- python scripts/test_build_catalogue.py passes
- A stockroom.json with two products builds, and the site shows them with
  their images and correct size chips
- sync.bat builds, commits and pushes in one run, and refuses to push a
  failed build
```

---

## The architecture call this makes

**Stockroom becomes the source of truth for live products. The workbook becomes the archive.**

I'm proposing this rather than deciding it, but the evidence is one-sided: your Stockroom already holds every field Excel holds — article, brand, colour, category, per-size MRP and barcode, offer price, stock, published. Keeping Excel in the middle means writing every product twice, and it is the only reason this hop can't be automated.

What you lose: bulk price edits in a spreadsheet, and the Archive tab for live products. The Archive stays for the old 215.

**Say so and I'll rewrite Prompt B** to write Stockroom rows into the workbook instead, keeping Excel authoritative. Same automation, one extra hop.

---

## After both land, your loop is

```
PHONE     capture products, tap Publish on the ones you want live
PHONE     tap "Download for website"
PC        unzip into the ONLY 4 YOU folder
PC        double-click sync.bat
```

Four steps, two of them taps. The build validates, the commit and push happen on their own.

## One thing you still have to do once

**Connect GitHub → Netlify.** You're on drag-and-drop, so `sync.bat` pushing to GitHub does nothing until Netlify is watching that repo. Create the repo, push once, then Netlify → "Import from Git" → pick it. After that every push deploys itself and the drag step is gone permanently.

Until that's done, `sync.bat` still builds and commits — you'd just drag the folder as usual.
