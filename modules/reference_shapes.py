# modules/reference_shapes.py
# Betta Farm Management System
# Session 26H — Load reference silhouettes for Gemini matching.
#
# Loads the 4 reference SVGs from modules/reference_shapes/ and
# caches them as PNG bytes (rendered on white) for API use.
#
# Falls back to sending raw SVG bytes if cairosvg isn't available —
# Gemini can read SVG directly.

from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

from PIL import Image

REFERENCE_DIR = Path(__file__).resolve().parent / "reference_shapes"

REFERENCE_NAMES = [
    "hmpk_traditional_show",
    "hmpk_symmetrical_show",
    "hmpk_asymmetrical_show",
    "hmpk_pet_grade",
]

_cache: dict = {}


def _load_one(name: str) -> Optional[dict]:
    svg_path = REFERENCE_DIR / f"{name}.svg"
    png_path = REFERENCE_DIR / f"{name}.png"

    try:
        if svg_path.exists():
            # Try to render SVG → PNG via cairosvg (if installed)
            try:
                import cairosvg
                png_bytes = cairosvg.svg2png(
                    url=str(svg_path),
                    output_width=400,
                    output_height=300,
                    background_color="white",
                )
                buf = io.BytesIO(png_bytes)
                img = Image.open(buf).convert("RGB")
            except Exception:
                # Fallback: send raw SVG bytes to Gemini
                raw = svg_path.read_bytes()
                return {
                    "name": name,
                    "bytes": raw,
                    "mime_type": "image/svg+xml",
                }
        elif png_path.exists():
            img = Image.open(png_path)
            if img.mode != "RGB":
                bg = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "RGBA":
                    bg.paste(img, mask=img.split()[3])
                else:
                    bg.paste(img)
                img = bg
        else:
            return None

        img.thumbnail((400, 300), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)

        return {
            "name": name,
            "bytes": buf.getvalue(),
            "mime_type": "image/png",
        }
    except Exception:
        return None


def load_reference_images() -> list[dict]:
    global _cache
    if _cache:
        return list(_cache.values())

    loaded = []
    for name in REFERENCE_NAMES:
        entry = _load_one(name)
        if entry:
            _cache[name] = entry
            loaded.append(entry)
    return loaded


def get_reference_by_name(name: str) -> Optional[dict]:
    if name in _cache:
        return _cache[name]
    entry = _load_one(name)
    if entry:
        _cache[name] = entry
    return entry


def has_all_references() -> bool:
    return all(
        (REFERENCE_DIR / f"{n}.svg").exists() or (REFERENCE_DIR / f"{n}.png").exists()
        for n in REFERENCE_NAMES
    )


def missing_references() -> list[str]:
    return [
        n for n in REFERENCE_NAMES
        if not (REFERENCE_DIR / f"{n}.svg").exists()
        and not (REFERENCE_DIR / f"{n}.png").exists()
    ]
