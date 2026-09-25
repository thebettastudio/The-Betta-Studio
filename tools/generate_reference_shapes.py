# tools/generate_reference_shapes.py
# Betta Farm Management System
# Session 26H — One-time helper to generate clean silhouette PNGs
# from reference images.
#
# Usage (from repo root):
#   python tools/generate_reference_shapes.py
#
# Looks for reference images in tools/reference_sources/ and writes
# clean silhouettes to modules/reference_shapes/.
#
# Sources expected (any one of these file names, .png/.jpg/.jpeg):
#   traditional_show.*
#   symmetrical_show.*
#   asymmetrical_show.*
#   pet_grade.*
#
# If a source is missing, falls back to generating a placeholder
# outline so the pipeline still works.

from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

try:
    from scipy import ndimage as _ndimage
    _SCIPY = True
except ImportError:
    _SCIPY = False


REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = REPO_ROOT / "tools" / "reference_sources"
OUTPUT_DIR = REPO_ROOT / "modules" / "reference_shapes"

# Output size for silhouettes (width x height) — generous, Gemini downscales
OUT_W, OUT_H = 800, 600

REFERENCE_NAMES = [
    "hmpk_traditional_show",
    "hmpk_symmetrical_show",
    "hmpk_asymmetrical_show",
    "hmpk_pet_grade",
]

# Source file base names to look for
SOURCE_BASENAMES = [
    "traditional_show",
    "symmetrical_show",
    "asymmetrical_show",
    "pet_grade",
]


def find_source(basename: str):
    """Look for basename.{png,jpg,jpeg} in SOURCE_DIR."""
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        p = SOURCE_DIR / f"{basename}{ext}"
        if p.exists():
            return p
    return None


def extract_silhouette(img: Image.Image) -> Image.Image:
    """
    Given a reference image (line drawing or photo), extract the outer
    contour as a clean black-on-transparent PNG.
    """
    # 1. Convert to grayscale
    gray = ImageOps.grayscale(img.convert("RGB"))
    arr = np.asarray(gray, dtype=np.float32)

    # 2. Adaptive threshold: darker pixels = ink
    # Use Otsu-like threshold via median
    med = float(np.median(arr))
    thresh = med - 15  # a bit darker than median = ink
    ink = (arr < thresh).astype(np.uint8)

    if ink.sum() < 100:
        # Too few dark pixels — image is probably inverted or white-on-black
        ink = (arr > (med + 15)).astype(np.uint8)

    # 3. Clean up with morphology
    if _SCIPY:
        ink = _ndimage.binary_closing(ink, iterations=2).astype(np.uint8)
        ink = _ndimage.binary_fill_holes(ink).astype(np.uint8)

    # 4. Find largest connected component
    if _SCIPY:
        labeled, num = _ndimage.label(ink)
        if num > 1:
            sizes = _ndimage.sum(ink, labeled, index=range(1, num + 1))
            biggest = int(np.argmax(sizes)) + 1
            ink = (labeled == biggest).astype(np.uint8)

    if ink.sum() < 100:
        # Nothing found — return blank placeholder
        return _blank_placeholder()

    # 5. Crop to ink bounding box
    ys, xs = np.where(ink > 0)
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    crop = ink[y0:y1, x0:x1]

    # 6. Resize to output size, preserving aspect ratio
    h, w = crop.shape
    scale = min(OUT_W / w, OUT_H / h) * 0.9   # 10% margin
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))

    crop_img = Image.fromarray((crop * 255).astype(np.uint8))
    crop_img = crop_img.resize((new_w, new_h), Image.LANCZOS)

    # 7. Paste into output canvas centered, with black on transparent
    out = Image.new("RGBA", (OUT_W, OUT_H), (0, 0, 0, 0))
    paste_x = (OUT_W - new_w) // 2
    paste_y = (OUT_H - new_h) // 2

    # Solid black with full alpha where crop > 0
    crop_arr = np.asarray(crop_img, dtype=np.uint8)
    rgba = np.zeros((new_h, new_w, 4), dtype=np.uint8)
    rgba[..., 3] = crop_arr  # alpha = ink
    rgba[..., 0:3] = 0       # black

    out.paste(Image.fromarray(rgba, mode="RGBA"), (paste_x, paste_y), Image.fromarray(rgba, mode="RGBA"))

    return out


def _blank_placeholder() -> Image.Image:
    """Return a minimal placeholder silhouette if no source found."""
    out = Image.new("RGBA", (OUT_W, OUT_H), (0, 0, 0, 0))
    from PIL import ImageDraw
    draw = ImageDraw.Draw(out)
    # Simple betta-ish outline
    cx, cy = OUT_W // 2, OUT_H // 2
    # Body ellipse
    draw.ellipse([cx - 200, cy - 80, cx + 150, cy + 80],
                 outline=(0, 0, 0, 255), width=6)
    # Tail fan
    draw.polygon([(cx + 140, cy - 100), (cx + 320, cy - 160),
                  (cx + 350, cy + 40), (cx + 320, cy + 180),
                  (cx + 140, cy + 100)],
                 outline=(0, 0, 0, 255))
    # Dorsal fin
    draw.polygon([(cx - 80, cy - 80), (cx - 20, cy - 180),
                  (cx + 60, cy - 160), (cx + 60, cy - 80)],
                 outline=(0, 0, 0, 255))
    # Anal fin
    draw.polygon([(cx - 60, cy + 80), (cx + 20, cy + 200),
                  (cx + 120, cy + 180), (cx + 120, cy + 80)],
                 outline=(0, 0, 0, 255))
    # Ventral fins
    draw.line([(cx - 180, cy + 40), (cx - 260, cy + 220)], fill=(0, 0, 0, 255), width=6)
    draw.line([(cx - 150, cy + 40), (cx - 200, cy + 240)], fill=(0, 0, 0, 255), width=6)
    return out


def main():
    print(f"Repo root: {REPO_ROOT}")
    print(f"Source dir: {SOURCE_DIR}")
    print(f"Output dir: {OUTPUT_DIR}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    found_any = False
    for name, basename in zip(REFERENCE_NAMES, SOURCE_BASENAMES):
        source_path = find_source(basename)
        out_path = OUTPUT_DIR / f"{name}.png"

        if source_path is None:
            print(f"  [no source] {basename}.* — writing placeholder to {out_path.name}")
            silhouette = _blank_placeholder()
        else:
            print(f"  [found] {source_path.name} → {out_path.name}")
            try:
                img = Image.open(source_path)
                silhouette = extract_silhouette(img)
                found_any = True
            except Exception as e:
                print(f"    error: {e} — writing placeholder")
                silhouette = _blank_placeholder()

        silhouette.save(out_path, "PNG")
        print(f"    saved: {out_path}")

    print("\nDone.")
    if not found_any:
        print("⚠️  No source images found — wrote 4 placeholders.")
        print(f"   Drop your reference images into {SOURCE_DIR}/ as:")
        for basename in SOURCE_BASENAMES:
            print(f"     {basename}.png  (or .jpg)")
        print("   Then run this script again.")


if __name__ == "__main__":
    main()
