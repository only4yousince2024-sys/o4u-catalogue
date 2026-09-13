"""
O4U Product Photo Polisher
==========================
Removes background from product photos using remove.bg API
and saves clean, web-ready images.

HOW TO USE:
1. Get a free API key from https://www.remove.bg/api (50 free images/month)
2. Put it in the environment - never in this file, never in git:
     PowerShell:  $env:REMOVE_BG_API_KEY = "your-key"
     bash:        export REMOVE_BG_API_KEY=your-key
3. Put all your product photos in the "raw_photos" folder
4. Run: python polish_photos.py
5. Find polished images in the "polished" folder
"""

import os
import requests
from PIL import Image, ImageOps
import io

# ── API key comes from the environment only (never commit a real key) ──
API_KEY = os.environ.get("REMOVE_BG_API_KEY", "")
# ────────────────────────────────────────────────────────────────────

INPUT_FOLDER  = "raw_photos"   # put your phone photos here
OUTPUT_FOLDER = "polished"     # polished images saved here
OUTPUT_SIZE   = (800, 1000)    # width x height (portrait, good for product cards)
BG_COLOR      = (255, 255, 255) # white background

SUPPORTED = (".jpg", ".jpeg", ".png", ".webp")


def remove_background(image_path):
    """Send image to remove.bg and get back a transparent PNG."""
    with open(image_path, "rb") as f:
        response = requests.post(
            "https://api.remove.bg/v1.0/removebg",
            files={"image_file": f},
            data={"size": "auto"},
            headers={"X-Api-Key": API_KEY},
        )
    if response.status_code == 200:
        return Image.open(io.BytesIO(response.content)).convert("RGBA")
    else:
        print(f"  ✗ API error: {response.status_code} — {response.text[:100]}")
        return None


def polish(img_rgba, output_size, bg_color):
    """Place subject on white background, centered, with padding."""
    # White canvas
    canvas = Image.new("RGBA", output_size, (*bg_color, 255))

    # Fit image within canvas with 5% padding
    pad = int(output_size[0] * 0.05)
    max_w = output_size[0] - pad * 2
    max_h = output_size[1] - pad * 2
    img_rgba.thumbnail((max_w, max_h), Image.LANCZOS)

    # Center on canvas
    x = (output_size[0] - img_rgba.width) // 2
    y = (output_size[1] - img_rgba.height) // 2
    canvas.paste(img_rgba, (x, y), img_rgba)

    return canvas.convert("RGB")


def main():
    if not API_KEY:
        print("\n⚠️  Set the REMOVE_BG_API_KEY environment variable first!")
        print("   Get one free at: https://www.remove.bg/api\n")
        return

    os.makedirs(INPUT_FOLDER, exist_ok=True)
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    photos = [f for f in os.listdir(INPUT_FOLDER)
              if f.lower().endswith(SUPPORTED)]

    if not photos:
        print(f"\n📂 No photos found in '{INPUT_FOLDER}' folder.")
        print(f"   Add your product photos there and run again.\n")
        return

    print(f"\n🔄 Processing {len(photos)} photo(s)...\n")

    for i, filename in enumerate(photos, 1):
        input_path = os.path.join(INPUT_FOLDER, filename)
        name = os.path.splitext(filename)[0]
        output_path = os.path.join(OUTPUT_FOLDER, f"{name}.jpg")

        print(f"  [{i}/{len(photos)}] {filename}")

        img = remove_background(input_path)
        if img is None:
            continue

        result = polish(img, OUTPUT_SIZE, BG_COLOR)
        result.save(output_path, "JPEG", quality=88, optimize=True)
        size_kb = os.path.getsize(output_path) // 1024
        print(f"       ✓ Saved → {output_path} ({size_kb} KB)")

    print(f"\n✅ Done! Check the '{OUTPUT_FOLDER}' folder.\n")


if __name__ == "__main__":
    main()
