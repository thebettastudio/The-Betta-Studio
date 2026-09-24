# modules/color_detector.py
# Betta Farm Management System
# Session 26A — Color analysis via computer vision.
# Session 26B — Added analyze_region() for tap-to-select flow.
#
# Pipeline per photo:
#   1. Load image → convert to HSV
#   2. Filter background (low sat, extreme value)
#   3. Crop to center 70% (fish region)
#   4. K-means cluster remaining pixels (k=5)
#   5. Map each cluster centroid → nearest color category
#   6. Compute % per category
#   7. Detect iridescence (bright, saturated, scattered pixels)
#   8. Score photo quality
#
# Multi-shot consensus via merge_analyses().
# Region analysis via analyze_region() — used by WebRTC tap-to-select.

from __future__ import annotations

import io
import math
from typing import Optional

import numpy as np
from PIL import Image

try:
    from scipy import ndimage as _ndimage
    _SCIPY_AVAILABLE = True
except ImportError:
    _SCIPY_AVAILABLE = False


# ============================================================
# COLOR CATEGORY DEFINITIONS
# ============================================================

COLOR_CATEGORIES = [
    ("red",                5,         20,        90,      40,      255),
    ("orange",             30,        18,        90,      40,      255),
    ("yellow",             52,        18,        90,      60,      255),
    ("green",              110,       45,        80,      40,      255),
    ("blue",               200,       50,        80,      40,      255),
    ("purple",             275,       35,        70,      40,      255),
    ("pink",               320,       30,        70,      40,      255),
    ("white",              0,         360,       0,       200,     255),
    ("black",              0,         360,       0,       0,       60),
    ("silver",             0,         360,       0,       120,     200),
    ("gold_metallic",      45,        25,        120,     170,     255),
    ("copper",             20,        20,        120,     120,     200),
]


# ============================================================
# HSV HELPERS
# ============================================================

def _load_image_rgb(raw_bytes: bytes) -> Optional[Image.Image]:
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        return img
    except Exception:
        return None


def _rgb_to_hsv_numpy(rgb_array: np.ndarray) -> np.ndarray:
    arr = rgb_array.astype(np.float32) / 255.0
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    maxc = np.max(arr, axis=-1)
    minc = np.min(arr, axis=-1)
    delta = maxc - minc

    v = maxc
    s = np.where(maxc > 0, delta / np.maximum(maxc, 1e-6), 0)

    h = np.zeros_like(maxc)
    nonzero = delta > 1e-6

    r_max = (maxc == r) & nonzero
    g_max = (maxc == g) & nonzero & ~r_max
    b_max = (maxc == b) & nonzero & ~r_max & ~g_max

    h[r_max] = ((g - b) / delta)[r_max] % 6
    h[g_max] = ((b - r) / delta + 2)[g_max]
    h[b_max] = ((r - g) / delta + 4)[b_max]

    h = h * 60.0

    return np.stack([h, s * 255.0, v * 255.0], axis=-1)


def _hue_distance(h1: float, h2: float) -> float:
    d = abs(h1 - h2) % 360
    return min(d, 360 - d)


# ============================================================
# BACKGROUND FILTERING + CROP
# ============================================================

def _mask_fish_region(hsv: np.ndarray) -> np.ndarray:
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]

    is_fish = np.ones_like(s, dtype=bool)
    is_fish &= ~(s < 30)
    is_fish &= ~(v > 240)
    is_fish &= ~(v < 25)

    H, W = s.shape
    y0, y1 = int(H * 0.15), int(H * 0.85)
    x0, x1 = int(W * 0.15), int(W * 0.85)

    center_mask = np.zeros_like(is_fish, dtype=bool)
    center_mask[y0:y1, x0:x1] = True
    is_fish &= center_mask

    return is_fish


# ============================================================
# K-MEANS
# ============================================================

def _kmeans(pixels: np.ndarray, k: int = 5, iterations: int = 15) -> tuple[np.ndarray, np.ndarray]:
    n = pixels.shape[0]
    if n == 0:
        return np.zeros((0, 3)), np.zeros(0, dtype=int)

    k = min(k, n)
    rng = np.random.default_rng(42)
    idx = rng.choice(n, size=k, replace=False)
    centroids = pixels[idx].copy()

    labels = np.zeros(n, dtype=int)
    for _ in range(iterations):
        dists = np.linalg.norm(pixels[:, None, :] - centroids[None, :, :], axis=-1)
        labels = np.argmin(dists, axis=1)
        new_centroids = np.zeros_like(centroids)
        for ci in range(k):
            mask = labels == ci
            if mask.any():
                new_centroids[ci] = pixels[mask].mean(axis=0)
            else:
                new_centroids[ci] = centroids[ci]
        if np.allclose(new_centroids, centroids, atol=0.5):
            centroids = new_centroids
            break
        centroids = new_centroids

    return centroids, labels


# ============================================================
# CATEGORY MAPPING
# ============================================================

def _map_hsv_to_category(h: float, s: float, v: float) -> Optional[str]:
    for name in ("gold_metallic", "copper"):
        for cat in COLOR_CATEGORIES:
            if cat[0] != name:
                continue
            _, hc, hw, smin, vmin, vmax = cat
            if _hue_distance(h, hc) <= hw and s >= smin and vmin <= v <= vmax:
                return name

    if s < 40:
        if v > 200:
            return "white"
        if v < 60:
            return "black"
        return "silver"

    best = None
    best_dist = 999
    for name, hc, hw, smin, vmin, vmax in COLOR_CATEGORIES:
        if name in ("white", "silver", "black", "gold_metallic", "copper"):
            continue
        if s < smin or not (vmin <= v <= vmax):
            continue
        d = _hue_distance(h, hc)
        if d <= hw and d < best_dist:
            best = name
            best_dist = d

    return best


# ============================================================
# IRIDESCENCE
# ============================================================

def _detect_iridescence(hsv: np.ndarray, mask: np.ndarray) -> tuple[str, int]:
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]

    sparkle = (v > 180) & (s > 100) & mask
    total = mask.sum()
    if total == 0:
        return "none", 0

    sparkle_pct = sparkle.sum() / total * 100

    if sparkle.sum() < 20:
        return "none", int(sparkle_pct)

    sparkle_hues = h[sparkle]
    bins = (sparkle_hues // 60).astype(int) % 6
    unique_bins = len(np.unique(bins))

    avg_v = float(v[sparkle].mean())

    diversity_factor = min(unique_bins / 3.0, 1.0)
    brightness_factor = min((avg_v - 180) / 75.0, 1.0)
    score = int(min(sparkle_pct * 3 * diversity_factor * brightness_factor, 100))

    if score < 10:
        level = "none"
    elif score < 30:
        level = "faint"
    elif score < 60:
        level = "moderate"
    else:
        level = "strong"

    return level, score


# ============================================================
# QUALITY SCORING
# ============================================================

def _score_quality(img: Image.Image, mask: np.ndarray, hsv: np.ndarray) -> dict:
    arr = np.asarray(img.convert("L"), dtype=np.float32)

    if _SCIPY_AVAILABLE:
        lap = _ndimage.laplace(arr)
        sharp_var = float(lap.var())
        sharpness_score = min(sharp_var / 500.0 * 100, 100)
    else:
        gx = np.diff(arr, axis=1)
        gy = np.diff(arr, axis=0)
        grad = np.sqrt(gx[:-1, :] ** 2 + gy[:, :-1] ** 2)
        sharpness_score = min(float(grad.mean()) / 20.0 * 100, 100)

    coverage_pct = mask.sum() / mask.size * 100
    if coverage_pct < 5:
        coverage_score = coverage_pct * 4
    elif coverage_pct > 50:
        coverage_score = max(0, 100 - (coverage_pct - 50) * 2)
    else:
        coverage_score = 100.0

    if mask.sum() > 0:
        avg_v = float(hsv[..., 2][mask].mean())
        brightness_score = 100 - min(abs(avg_v - 140) * 0.6, 100)
    else:
        brightness_score = 0

    if mask.sum() > 0:
        std_v = float(hsv[..., 2][mask].std())
        contrast_score = min(std_v / 60.0 * 100, 100)
    else:
        contrast_score = 0

    if mask.sum() > 0:
        ys, xs = np.where(mask)
        h_span = xs.max() - xs.min()
        v_span = ys.max() - ys.min()
        if h_span > v_span * 1.3:
            orientation_score = 100
        elif v_span > h_span * 1.3:
            orientation_score = 40
        else:
            orientation_score = 70
    else:
        orientation_score = 0

    total = (
        sharpness_score * 0.30 +
        coverage_score * 0.25 +
        brightness_score * 0.15 +
        contrast_score * 0.15 +
        orientation_score * 0.15
    )

    return {
        "score": int(total),
        "sharpness": int(sharpness_score),
        "coverage": int(coverage_score),
        "brightness": int(brightness_score),
        "contrast": int(contrast_score),
        "orientation": int(orientation_score),
    }


# ============================================================
# MAIN: ANALYZE FULL PHOTO
# ============================================================

def analyze_photo(raw_bytes: bytes, k_clusters: int = 5) -> Optional[dict]:
    img = _load_image_rgb(raw_bytes)
    if img is None:
        return {"ok": False, "error": "Could not load image"}

    img.thumbnail((640, 640), Image.LANCZOS)

    rgb = np.asarray(img)
    hsv = _rgb_to_hsv_numpy(rgb)

    mask = _mask_fish_region(hsv)
    if mask.sum() < 50:
        return {"ok": False, "error": "Too little fish region detected"}

    fish_pixels = rgb[mask]
    centroids, labels = _kmeans(fish_pixels.astype(np.float32), k=k_clusters)

    counts = np.bincount(labels, minlength=len(centroids))
    pcts = counts / counts.sum() * 100

    palette: dict[str, float] = {}
    for ci, c in enumerate(centroids):
        c_rgb = np.array([[[c[0], c[1], c[2]]]], dtype=np.uint8)
        c_hsv = _rgb_to_hsv_numpy(c_rgb)[0, 0]
        ch, cs, cv = float(c_hsv[0]), float(c_hsv[1]), float(c_hsv[2])
        cat = _map_hsv_to_category(ch, cs, cv)
        if cat:
            palette[cat] = palette.get(cat, 0) + float(pcts[ci])

    palette = {k: round(v, 1) for k, v in palette.items() if v >= 3.0}
    sorted_palette = dict(sorted(palette.items(), key=lambda x: -x[1]))

    keys = list(sorted_palette.keys())
    primary = keys[0] if len(keys) > 0 else None
    secondary = keys[1] if len(keys) > 1 else None

    if not keys:
        pattern = "unknown"
    elif len(keys) == 1 or sorted_palette[keys[0]] >= 60:
        pattern = "solid"
    elif len(keys) == 2 and sum(sorted_palette.values()) >= 70:
        pattern = "bi-color"
    else:
        pattern = "multicolor"

    iri_level, iri_score = _detect_iridescence(hsv, mask)
    quality = _score_quality(img, mask, hsv)

    return {
        "ok": True,
        "palette": sorted_palette,
        "primary": primary,
        "secondary": secondary,
        "pattern_hint": pattern,
        "iridescence_level": iri_level,
        "iridescence_score": iri_score,
        "quality": quality,
        "coverage_pct": round(float(mask.sum() / mask.size * 100), 1),
    }


# ============================================================
# REGION ANALYSIS (Session 26B — tap-to-select)
# ============================================================

def analyze_region(
    raw_bytes: bytes,
    tap_x: float,
    tap_y: float,
    display_w: float,
    display_h: float,
    region_size: int = 150,
    k_clusters: int = 5,
) -> Optional[dict]:
    """
    Analyze a small square region around a tap point.

    Coordinates come from DISPLAY size (what the user sees).
    Auto-scales to actual image dimensions before cropping.
    """
    img = _load_image_rgb(raw_bytes)
    if img is None:
        return {"ok": False, "error": "Could not load image"}

    actual_w, actual_h = img.size
    if display_w <= 0 or display_h <= 0:
        return {"ok": False, "error": "Invalid display dimensions"}

    scale_x = actual_w / display_w
    scale_y = actual_h / display_h

    cx = tap_x * scale_x
    cy = tap_y * scale_y
    r = (region_size / 2) * ((scale_x + scale_y) / 2)

    left = max(0, int(cx - r))
    top = max(0, int(cy - r))
    right = min(actual_w, int(cx + r))
    bottom = min(actual_h, int(cy + r))

    if right - left < 20 or bottom - top < 20:
        return {"ok": False, "error": "Region too small after scaling"}

    cropped = img.crop((left, top, right, bottom))

    buf = io.BytesIO()
    cropped.save(buf, format="JPEG", quality=90)
    cropped_bytes = buf.getvalue()

    analysis = analyze_photo(cropped_bytes, k_clusters=k_clusters)
    if not analysis or not analysis.get("ok"):
        return analysis or {"ok": False, "error": "Region analysis failed"}

    analysis["region"] = {
        "tap_x": tap_x,
        "tap_y": tap_y,
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "region_size": region_size,
    }
    return analysis


# ============================================================
# MULTI-SHOT CONSENSUS
# ============================================================

def merge_analyses(analyses: list[dict]) -> dict:
    valid = [a for a in analyses if a and a.get("ok")]
    if not valid:
        return {"ok": False, "error": "No valid shots"}

    all_keys = set()
    for a in valid:
        all_keys.update(a["palette"].keys())

    merged: dict[str, float] = {}
    for key in all_keys:
        vals = [a["palette"].get(key, 0) for a in valid]
        merged[key] = round(sum(vals) / len(vals), 1)

    merged = {k: v for k, v in merged.items() if v >= 3.0}
    merged = dict(sorted(merged.items(), key=lambda x: -x[1]))

    keys = list(merged.keys())
    primary = keys[0] if keys else None
    secondary = keys[1] if len(keys) > 1 else None

    if not keys:
        pattern = "unknown"
    elif len(keys) == 1 or merged[keys[0]] >= 60:
        pattern = "solid"
    elif len(keys) == 2 and sum(merged.values()) >= 70:
        pattern = "bi-color"
    else:
        pattern = "multicolor"

    iri_scores = [a.get("iridescence_score", 0) for a in valid]
    max_score = max(iri_scores)

    if max_score < 10:
        iri_level = "none"
    elif max_score < 30:
        iri_level = "faint"
    elif max_score < 60:
        iri_level = "moderate"
    else:
        iri_level = "strong"

    return {
        "ok": True,
        "palette": merged,
        "primary": primary,
        "secondary": secondary,
        "pattern_hint": pattern,
        "iridescence_level": iri_level,
        "iridescence_score": max_score,
        "shot_count": len(valid),
        "best_shot_index": max(range(len(analyses)), key=lambda i: (analyses[i] or {}).get("quality", {}).get("score", 0)),
    }


# ============================================================
# DISPLAY HELPERS
# ============================================================

COLOR_SWATCHES = {
    "red": "#DC2626",
    "orange": "#EA580C",
    "yellow": "#EAB308",
    "green": "#16A34A",
    "blue": "#2563EB",
    "purple": "#7C3AED",
    "pink": "#DB2777",
    "white": "#F3F4F6",
    "black": "#1F2937",
    "silver": "#9CA3AF",
    "gold_metallic": "#D4AF37",
    "copper": "#B87333",
}


def color_swatch_html(color: str, size: int = 16) -> str:
    hex_color = COLOR_SWATCHES.get(color, "#E5E7EB")
    border = "border:1px solid #D1D5DB;" if color in ("white", "silver") else ""
    return (
        f'<span style="display:inline-block;width:{size}px;height:{size}px;'
        f'background:{hex_color};border-radius:4px;vertical-align:middle;{border}'
        f'margin-right:4px;"></span>'
    )


def palette_html(palette: dict, max_items: int = 5) -> str:
    if not palette:
        return "—"
    parts = []
    for i, (color, pct) in enumerate(sorted(palette.items(), key=lambda x: -x[1])[:max_items]):
        parts.append(f"{color_swatch_html(color)}{color} {pct:.0f}%")
    return " &nbsp; ".join(parts)
