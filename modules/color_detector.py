# modules/color_detector.py
# Betta Farm Management System
# Session 26A — Color analysis via computer vision.
#
# Pipeline per photo:
#   1. Load image → convert to HSV
#   2. Filter background (low sat, extreme value)
#   3. Crop to center 70% (fish region)
#   4. K-means cluster remaining pixels (k=5)
#   5. Map each cluster centroid → nearest color category
#   6. Compute % per category
#   7. Detect iridescence (bright, saturated, scattered pixels)
#   8. Score photo quality (sharpness, coverage, brightness, contrast, orientation)
#
# Multi-shot consensus:
#   - analyze_photo(bytes) → {palette, iridescence, quality_score, ...}
#   - merge_analyses([analysis1, analysis2, ...]) → consensus
#
# All in-memory, no uploads.

from __future__ import annotations

import io
import math
from typing import Optional

import numpy as np
from PIL import Image

# Optional: skimage for Laplacian variance if available
try:
    from scipy import ndimage as _ndimage
    _SCIPY_AVAILABLE = True
except ImportError:
    _SCIPY_AVAILABLE = False


# ============================================================
# COLOR CATEGORY DEFINITIONS
# ============================================================
# Each entry: (name, hue_center, hue_range, min_sat, min_val, max_val)
# Hue in degrees 0-360. Sat/Val in 0-255.

COLOR_CATEGORIES = [
    # (name,              hue_center, hue_width, min_sat, min_val, max_val)
    ("red",                5,         20,        90,      40,      255),
    ("orange",             30,        18,        90,      40,      255),
    ("yellow",             52,        18,        90,      60,      255),
    ("green",              110,       45,        80,      40,      255),
    ("blue",               200,       50,        80,      40,      255),
    ("purple",             275,       35,        70,      40,      255),
    ("pink",               320,       30,        70,      40,      255),
    ("white",              0,         360,       0,       200,     255),  # low sat, high val
    ("black",              0,         360,       0,       0,       60),   # low sat, low val
    ("silver",             0,         360,       0,       120,     200),  # low sat, mid val
    ("gold_metallic",      45,        25,        120,     170,     255),  # high sat, high val
    ("copper",             20,        20,        120,     120,     200),  # orange-brown, high sat
]


# ============================================================
# HSV HELPERS
# ============================================================

def _load_image_rgb(raw_bytes: bytes) -> Optional[Image.Image]:
    """Load bytes into a PIL RGB image. Returns None on failure."""
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        return img
    except Exception:
        return None


def _rgb_to_hsv_numpy(rgb_array: np.ndarray) -> np.ndarray:
    """
    Convert (H, W, 3) uint8 RGB to (H, W, 3) float HSV.
    H in [0, 360), S in [0, 255], V in [0, 255].
    """
    arr = rgb_array.astype(np.float32) / 255.0
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    maxc = np.max(arr, axis=-1)
    minc = np.min(arr, axis=-1)
    delta = maxc - minc

    # Value
    v = maxc

    # Saturation
    s = np.where(maxc > 0, delta / np.maximum(maxc, 1e-6), 0)

    # Hue
    h = np.zeros_like(maxc)
    nonzero = delta > 1e-6

    r_max = (maxc == r) & nonzero
    g_max = (maxc == g) & nonzero & ~r_max
    b_max = (maxc == b) & nonzero & ~r_max & ~g_max

    h[r_max] = ((g - b) / delta)[r_max] % 6
    h[g_max] = ((b - r) / delta + 2)[g_max]
    h[b_max] = ((r - g) / delta + 4)[b_max]

    h = h * 60.0  # to degrees

    return np.stack([h, s * 255.0, v * 255.0], axis=-1)


def _hue_distance(h1: float, h2: float) -> float:
    """Shortest distance on the hue circle."""
    d = abs(h1 - h2) % 360
    return min(d, 360 - d)


# ============================================================
# BACKGROUND FILTERING + CROP
# ============================================================

def _mask_fish_region(hsv: np.ndarray) -> np.ndarray:
    """
    Returns a boolean mask: True where pixels are likely fish (not background).
    Filters:
      - Low saturation + high value (white/bright background)
      - Low saturation + low value (dark background)
      - The rest is considered potentially fish
    Also: restricts to center 70% of frame.
    """
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]

    # Exclude obviously non-fish (very low sat OR extreme bright OR extreme dark)
    is_fish = np.ones_like(s, dtype=bool)
    is_fish &= ~(s < 30)                          # too grey to be fish color
    is_fish &= ~(v > 240)                         # too bright (glare)
    is_fish &= ~(v < 25)                          # too dark (shadow)

    # Center 70% crop
    H, W = s.shape
    y0, y1 = int(H * 0.15), int(H * 0.85)
    x0, x1 = int(W * 0.15), int(W * 0.85)

    center_mask = np.zeros_like(is_fish, dtype=bool)
    center_mask[y0:y1, x0:x1] = True
    is_fish &= center_mask

    return is_fish


# ============================================================
# K-MEANS CLUSTERING (simple, no external dep)
# ============================================================

def _kmeans(pixels: np.ndarray, k: int = 5, iterations: int = 15) -> tuple[np.ndarray, np.ndarray]:
    """
    Simple k-means on (N, 3) pixel array. Returns (centroids, labels).
    Uses random initialization for simplicity.
    """
    n = pixels.shape[0]
    if n == 0:
        return np.zeros((0, 3)), np.zeros(0, dtype=int)

    k = min(k, n)
    rng = np.random.default_rng(42)  # deterministic for reproducibility
    idx = rng.choice(n, size=k, replace=False)
    centroids = pixels[idx].copy()

    labels = np.zeros(n, dtype=int)
    for _ in range(iterations):
        # Assign
        dists = np.linalg.norm(pixels[:, None, :] - centroids[None, :, :], axis=-1)
        labels = np.argmin(dists, axis=1)

        # Update
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
# COLOR CATEGORY MAPPING
# ============================================================

def _map_hsv_to_category(h: float, s: float, v: float) -> Optional[str]:
    """
    Map an HSV triple to the closest category name, or None if unmatched.
    Order matters: specific (metallic, copper) checked before generic.
    """
    # Metallic gold / copper first (they overlap with yellow/orange otherwise)
    for name in ("gold_metallic", "copper"):
        for cat in COLOR_CATEGORIES:
            if cat[0] != name:
                continue
            _, hc, hw, smin, vmin, vmax = cat
            if _hue_distance(h, hc) <= hw and s >= smin and vmin <= v <= vmax:
                return name

    # Achromatic (white / silver / black)
    if s < 40:
        if v > 200:
            return "white"
        if v < 60:
            return "black"
        return "silver"

    # Chromatic — nearest hue center
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
# IRIDESCENCE DETECTION
# ============================================================

def _detect_iridescence(hsv: np.ndarray, mask: np.ndarray) -> tuple[str, int]:
    """
    Detect iridescence from scattered bright+saturated pixels.
    Returns (level, score 0-100).

    Heuristic:
      - Look for pixels with high V (>180) AND high S (>100)
      - These should be scattered (not a solid patch)
      - Hues should span multiple ranges (blue/violet/green sparkle)
    """
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]

    sparkle = (v > 180) & (s > 100) & mask
    total = mask.sum()
    if total == 0:
        return "none", 0

    sparkle_pct = sparkle.sum() / total * 100

    if sparkle.sum() < 20:
        return "none", int(sparkle_pct)

    # Hue diversity among sparkle pixels
    sparkle_hues = h[sparkle]
    # Bin into 6 sectors of 60°
    bins = (sparkle_hues // 60).astype(int) % 6
    unique_bins = len(np.unique(bins))

    # Brightness average
    avg_v = float(v[sparkle].mean())

    # Scattered check: count connected components — too complex for now,
    # approximate by checking std-dev of sparkle distribution
    # (iridescent sparkle tends to be spread out)

    # Score: percentage × hue diversity × brightness
    diversity_factor = min(unique_bins / 3.0, 1.0)   # 3+ hues = max
    brightness_factor = min((avg_v - 180) / 75.0, 1.0)  # 180→0, 255→1
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
    """
    Score a photo 0-100 based on:
      - sharpness (Laplacian variance, or gradient fallback)
      - fish coverage (% of frame that is fish)
      - brightness balance
      - contrast
      - orientation (side profile preferred)
    """
    arr = np.asarray(img.convert("L"), dtype=np.float32)

    # Sharpness — Laplacian variance
    if _SCIPY_AVAILABLE:
        lap = _ndimage.laplace(arr)
        sharp_var = float(lap.var())
        sharpness_score = min(sharp_var / 500.0 * 100, 100)  # normalize
    else:
        # Fallback: gradient magnitude
        gx = np.diff(arr, axis=1)
        gy = np.diff(arr, axis=0)
        grad = np.sqrt(gx[:-1, :] ** 2 + gy[:, :-1] ** 2)
        sharpness_score = min(float(grad.mean()) / 20.0 * 100, 100)

    # Coverage
    coverage_pct = mask.sum() / mask.size * 100
    # Sweet spot: 15-40% coverage
    if coverage_pct < 5:
        coverage_score = coverage_pct * 4
    elif coverage_pct > 50:
        coverage_score = max(0, 100 - (coverage_pct - 50) * 2)
    else:
        coverage_score = 100.0

    # Brightness — mean V in fish region
    if mask.sum() > 0:
        avg_v = float(hsv[..., 2][mask].mean())
        brightness_score = 100 - min(abs(avg_v - 140) * 0.6, 100)
    else:
        brightness_score = 0

    # Contrast — std dev of V in fish region
    if mask.sum() > 0:
        std_v = float(hsv[..., 2][mask].std())
        contrast_score = min(std_v / 60.0 * 100, 100)
    else:
        contrast_score = 0

    # Orientation — heuristic: wider fish bounding box than tall = side profile
    if mask.sum() > 0:
        ys, xs = np.where(mask)
        h_span = xs.max() - xs.min()
        v_span = ys.max() - ys.min()
        if h_span > v_span * 1.3:
            orientation_score = 100  # side profile
        elif v_span > h_span * 1.3:
            orientation_score = 40   # vertical, less ideal
        else:
            orientation_score = 70   # square-ish, ok
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
# MAIN ENTRY: ANALYZE ONE PHOTO
# ============================================================

def analyze_photo(raw_bytes: bytes, k_clusters: int = 5) -> Optional[dict]:
    """
    Analyze a single photo. Returns dict:
      {
        "palette": {"red": 42, "orange": 28, ...},   # % per category
        "primary": "red",
        "secondary": "orange",
        "pattern_hint": "multicolor",
        "iridescence_level": "moderate",
        "iridescence_score": 72,
        "quality": {"score": 85, "sharpness": ..., ...},
        "ok": True,
      }
    Or {"ok": False, "error": "..."}.
    """
    img = _load_image_rgb(raw_bytes)
    if img is None:
        return {"ok": False, "error": "Could not load image"}

    # Resize to a manageable size for speed
    img.thumbnail((640, 640), Image.LANCZOS)

    rgb = np.asarray(img)
    hsv = _rgb_to_hsv_numpy(rgb)

    mask = _mask_fish_region(hsv)
    if mask.sum() < 50:
        return {"ok": False, "error": "Too little fish region detected"}

    # Cluster fish pixels
    fish_pixels = rgb[mask]  # (N, 3)
    centroids, labels = _kmeans(fish_pixels.astype(np.float32), k=k_clusters)

    # Compute % per cluster
    counts = np.bincount(labels, minlength=len(centroids))
    pcts = counts / counts.sum() * 100

    # Map each centroid to a color category
    palette: dict[str, float] = {}
    for ci, c in enumerate(centroids):
        # Convert centroid RGB to HSV (single pixel)
        c_rgb = np.array([[[c[0], c[1], c[2]]]], dtype=np.uint8)
        c_hsv = _rgb_to_hsv_numpy(c_rgb)[0, 0]
        ch, cs, cv = float(c_hsv[0]), float(c_hsv[1]), float(c_hsv[2])
        cat = _map_hsv_to_category(ch, cs, cv)
        if cat:
            palette[cat] = palette.get(cat, 0) + float(pcts[ci])

    # Filter tiny contributions
    palette = {k: round(v, 1) for k, v in palette.items() if v >= 3.0}

    # Sort
    sorted_palette = dict(sorted(palette.items(), key=lambda x: -x[1]))

    # Primary / secondary
    keys = list(sorted_palette.keys())
    primary = keys[0] if len(keys) > 0 else None
    secondary = keys[1] if len(keys) > 1 else None

    # Pattern hint
    if not keys:
        pattern = "unknown"
    elif len(keys) == 1 or sorted_palette[keys[0]] >= 60:
        pattern = "solid"
    elif len(keys) == 2 and sum(sorted_palette.values()) >= 70:
        pattern = "bi-color"
    else:
        pattern = "multicolor"

    # Iridescence
    iri_level, iri_score = _detect_iridescence(hsv, mask)

    # Quality
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
# MULTI-SHOT CONSENSUS
# ============================================================

def merge_analyses(analyses: list[dict]) -> dict:
    """
    Merge multiple analyze_photo() results into a consensus:
      - Average palette across all shots
      - Determine primary / secondary from averaged palette
      - Iridescence: majority vote + avg score
      - Quality: keep per-shot, return best
    """
    valid = [a for a in analyses if a and a.get("ok")]
    if not valid:
        return {"ok": False, "error": "No valid shots"}

    # Average palette
    all_keys = set()
    for a in valid:
        all_keys.update(a["palette"].keys())

    merged: dict[str, float] = {}
    for key in all_keys:
        vals = [a["palette"].get(key, 0) for a in valid]
        merged[key] = round(sum(vals) / len(vals), 1)

    # Re-filter tiny
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

    # Iridescence — take the max score across shots (one good angle is enough)
    iri_scores = [a.get("iridescence_score", 0) for a in valid]
    iri_levels = [a.get("iridescence_level", "none") for a in valid]
    max_score = max(iri_scores)
    # Level from max score
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
    """Return an inline HTML color swatch for a color name."""
    hex_color = COLOR_SWATCHES.get(color, "#E5E7EB")
    border = "border:1px solid #D1D5DB;" if color in ("white", "silver") else ""
    return (
        f'<span style="display:inline-block;width:{size}px;height:{size}px;'
        f'background:{hex_color};border-radius:4px;vertical-align:middle;{border}'
        f'margin-right:4px;"></span>'
    )


def palette_html(palette: dict, max_items: int = 5) -> str:
    """Render a palette as small color swatches with percentages."""
    if not palette:
        return "—"
    parts = []
    for i, (color, pct) in enumerate(sorted(palette.items(), key=lambda x: -x[1])[:max_items]):
        parts.append(f"{color_swatch_html(color)}{color} {pct:.0f}%")
    return " &nbsp; ".join(parts)
