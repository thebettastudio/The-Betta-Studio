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
# Sources expected (any of .png/.jpg/.jpeg/.webp):
#   traditional_show.*
#   symmetrical_show.*
#   asymmetrical_show.*
#   pet_grade.*
#
# If a source is missing, writes a clean placeholder outline so the
# pipeline still works.

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps

try:
    from scipy import ndimage as _ndimage
    _SCIPY = True
except ImportError:
    _SCIPY = False


REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = REPO_ROOT / "tools" / "reference_sources"
OUTPUT_DIR = REPO_ROOT / "modules" / "reference_shapes"

OUT_W, OUT_H = 800, 600

REFERENCE_NAMES = [
    "hmpk_traditional_show",
    "hmpk_symmetrical_show",
    "hmpk_asymmetrical_show",
    "hmpk_pet_grade",
]

SOURCE_BASENAMES = [
    "traditional_show",
    "symmetrical_show",
    "asymmetrical_show",
    "pet_grade",
]


# ============================================================
# HELPERS
# ============================================================

def find_source(basename: str):
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        p = SOURCE_DIR / f"{basename}{ext}"
        if p.exists():
            return p
    return None


def extract_silhouette(img: Image.Image) -> Image.Image:
    """
    Extract the outer fish contour from a reference image and
    produce a clean black outline on transparent background.
    """
    gray = ImageOps.grayscale(img.convert("RGB"))
    arr = np.asarray(gray, dtype=np.float32)

    # Adaptive threshold: darker than median = ink
    med = float(np.median(arr))
    thresh = med - 15
    ink = (arr < thresh).astype(np.uint8)

    if ink.sum() < 100:
        # Try inverted
        ink = (arr > (med + 15)).astype(np.uint8)

    # Morphology cleanup
    if _SCIPY:
        try:
            ink = _ndimage.binary_closing(ink, iterations=2).astype(np.uint8)
            ink = _ndimage.binary_fill_holes(ink).astype(np.uint8)
        except Exception:
            pass

    # Keep largest component
    if _SCIPY:
        try:
            labeled, num = _ndimage.label(ink)
            if num > 1:
                sizes = _ndimage.sum(ink, labeled, index=range(1, num + 1))
                biggest = int(np.argmax(sizes)) + 1
                ink = (labeled == biggest).astype(np.uint8)
        except Exception:
            pass

    if ink.sum() < 100:
        return _blank_placeholder()

    # Crop to ink
    ys, xs = np.where(ink > 0)
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    crop = ink[y0:y1, x0:x1]

    # Resize to fit canvas with margin
    h, w = crop.shape
    scale = min(OUT_W / w, OUT_H / h) * 0.9
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))

    crop_img = Image.fromarray((crop * 255).astype(np.uint8))
    crop_img = crop_img.resize((new_w, new_h), Image.LANCZOS)

    # Compose on transparent canvas
    out = Image.new("RGBA", (OUT_W, OUT_H), (0, 0, 0, 0))
    paste_x = (OUT_W - new_w) // 2
    paste_y = (OUT_H - new_h) // 2

    crop_arr = np.asarray(crop_img, dtype=np.uint8)
    rgba = np.zeros((new_h, new_w, 4), dtype=np.uint8)
    rgba[..., 3] = crop_arr   # alpha = ink
    rgba[..., 0:3] = 0        # solid black

    mask_img = Image.fromarray(rgba, mode="RGBA")
    out.paste(mask_img, (paste_x, paste_y), mask_img)

    return out


def _blank_placeholder() -> Image.Image:
    """A minimal fish-shaped outline placeholder."""
    out = Image.new("RGBA", (OUT_W, OUT_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(out)

    cx, cy = OUT_W // 2, OUT_H // 2

    # Body ellipse
    draw.ellipse([cx - 200, cy - 70, cx + 140, cy + 70],
                 outline=(0, 0, 0, 255), width=6)
    # Head — slight taper
    draw.line([(cx - 200, cy - 50), (cx - 260, cy - 30)],
              fill=(0, 0, 0, 255), width=6)
    draw.line([(cx - 200, cy + 50), (cx - 260, cy + 30)],
              fill=(0, 0, 0, 255), width=6)
    draw.line([(cx - 260, cy - 30), (cx - 260, cy + 30)],
              fill=(0, 0, 0, 255), width=6)
    # Caudal fan
    draw.polygon([(cx + 130, cy - 100), (cx + 300, cy - 170),
                  (cx + 340, cy - 80), (cx + 340, cy + 80),
                  (cx + 300, cy + 170), (cx + 130, cy + 100)],
                 outline=(0, 0, 0, 255))
    # Dorsal fin
    draw.polygon([(cx - 80, cy - 70), (cx - 20, cy - 190),
                  (cx + 80, cy - 170), (cx + 80, cy - 70)],
                 outline=(0, 0, 0, 255))
    # Anal fin
    draw.polygon([(cx - 60, cy + 70), (cx + 30, cy + 210),
                  (cx + 130, cy + 190), (cx + 130, cy + 70)],
                 outline=(0, 0, 0, 255))
    # Ventral fins
    draw.line([(cx - 180, cy + 40), (cx - 250, cy + 230)],
              fill=(0, 0, 0, 255), width=6)
    draw.line([(cx - 150, cy + 40), (cx - 190, cy + 250)],
              fill=(0, 0, 0, 255), width=6)

    return out


def main():
    print(f"Repo root:  {REPO_ROOT}")
    print(f"Source dir: {SOURCE_DIR}")
    print(f"Output dir: {OUTPUT_DIR}")
    print()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)

    found_any = False

    for name, basename in zip(REFERENCE_NAMES, SOURCE_BASENAMES):
        source_path = find_source(basename)
        out_path = OUTPUT_DIR / f"{name}.png"

        if source_path is None:
            print(f"  [no source] {basename}.* — writing placeholder → {out_path.name}")
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

        try:
            silhouette.save(out_path, "PNG")
            print(f"    saved: {out_path}")
        except Exception as e:
            print(f"    SAVE FAILED: {e}")

    print()
    print("Done.")
    if not found_any:
        print()
        print("⚠️  No source images found — wrote 4 placeholders.")
        print(f"   Drop your reference images into: {SOURCE_DIR}/")
        print("   Name them:")
        for basename in SOURCE_BASENAMES:
            print(f"     {basename}.png  (or .jpg/.jpeg/.webp)")
        print("   Then run this script again.")
    else:
        print(f"✅ Generated {len(REFERENCE_NAMES)} silhouettes in {OUTPUT_DIR}")
        print("   Review them before committing.")


if __name__ == "__main__":
    main()
