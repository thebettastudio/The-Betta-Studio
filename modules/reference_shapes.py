# modules/reference_shapes.py
# Betta Farm Management System
# Session 26H — Load reference silhouettes for Gemini matching.
#
# Loads the 4 reference PNGs from modules/reference_shapes/ and
# caches them as base64 for reuse in API calls.
#
# If a file is missing, returns None for that entry (graceful degrade).

from __future__ import annotations

import base64
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
    """Load one reference as {name, bytes, mime_type} or None."""
    p = REFERENCE_DIR / f"{name}.png"
    if not p.exists():
        return None
    try:
        img = Image.open(p)
        if img.mode != "RGBA":
            img = img.convert("RGBA")

        # Downscale to 400x300 to reduce token cost
        img.thumbnail((400, 300), Image.LANCZOS)

        # Composite onto white for Gemini (transparent → white)
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3] if img.mode == "RGBA" else None)

        buf = io.BytesIO()
        bg.save(buf, format="PNG", optimize=True)

        return {
            "name": name,
            "bytes": buf.getvalue(),
            "mime_type": "image/png",
        }
    except Exception:
        return None


def load_reference_images() -> list[dict]:
    """
    Return list of loaded references. Cached.
    Each entry: {name, bytes, mime_type}.
    Silently skips any missing files.
    """
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
    return all((REFERENCE_DIR / f"{n}.png").exists() for n in REFERENCE_NAMES)


def missing_references() -> list[str]:
    return [n for n in REFERENCE_NAMES if not (REFERENCE_DIR / f"{n}.png").exists()]
