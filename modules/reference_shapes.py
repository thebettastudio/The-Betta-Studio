# modules/reference_shapes.py
# Betta Farm Management System
# Session 26H — Load reference silhouettes for Gemini matching.
# Session 26H.5 — Use svglib (pure Python) to render SVG previews.
#
# Prefers PNG if present, falls back to SVG via svglib, last resort
# sends raw SVG bytes to Gemini.

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


def _svg_to_png_bytes(svg_path: Path) -> Optional[bytes]:
    """
    Render an SVG file to PNG bytes using svglib (pure Python).
    Returns None if svglib isn't available or fails.
    """
    try:
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPM
        drawing = svg2rlg(str(svg_path))
        if drawing is None:
            return None
        # Render on a white background
        png_bytes = renderPM.drawToString(drawing, fmt="PNG", bg=0xFFFFFF)
        return png_bytes
    except Exception:
        return None


def _load_one(name: str) -> Optional[dict]:
    """
    Load one reference as {name, bytes, mime_type}.
    Prefers .png; falls back to .svg rendered via svglib;
    last resort sends raw SVG bytes to Gemini.
    """
    png_path = REFERENCE_DIR / f"{name}.png"
    svg_path = REFERENCE_DIR / f"{name}.svg"

    try:
        # 1. Prefer pre-rendered PNG
        if png_path.exists():
            img = Image.open(png_path).convert("RGB")
            img.thumbnail((400, 300), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            return {
                "name": name,
                "bytes": buf.getvalue(),
                "mime_type": "image/png",
            }

        # 2. Render SVG via svglib (pure Python, no native deps)
        if svg_path.exists():
            png_bytes = _svg_to_png_bytes(svg_path)
            if png_bytes:
                try:
                    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
                    img.thumbnail((400, 300), Image.LANCZOS)
                    buf = io.BytesIO()
                    img.save(buf, format="PNG", optimize=True)
                    return {
                        "name": name,
                        "bytes": buf.getvalue(),
                        "mime_type": "image/png",
                    }
                except Exception:
                    pass

            # 3. Last resort: send raw SVG to Gemini
            raw = svg_path.read_bytes()
            return {
                "name": name,
                "bytes": raw,
                "mime_type": "image/svg+xml",
            }

        return None
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
        (REFERENCE_DIR / f"{n}.png").exists()
        or (REFERENCE_DIR / f"{n}.svg").exists()
        for n in REFERENCE_NAMES
    )


def missing_references() -> list[str]:
    return [
        n for n in REFERENCE_NAMES
        if not (REFERENCE_DIR / f"{n}.png").exists()
        and not (REFERENCE_DIR / f"{n}.svg").exists()
    ]
