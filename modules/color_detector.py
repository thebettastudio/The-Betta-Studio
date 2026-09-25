# modules/color_detector.py
# Betta Farm Management System
# Session 26A — Color analysis via computer vision.
# Session 26B — Added analyze_region() for tap-to-select flow.
# Session 26C — Added extract_frames_from_video() for video upload flow.
# Session 26C fix — Added blob detection to isolate the largest fish region.
# Session 26D — Major accuracy upgrade + verified on real fish.
# Session 26D round 2 — Reject low-saturation blobs.
# Session 26D round 3 — Suppress silver glass noise in fish mask + clusters.

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

try:
    import av
    _AV_AVAILABLE = True
except ImportError:
    _AV_AVAILABLE = False


# ============================================================
# COLOR CATEGORY DEFINITIONS
# ============================================================

COLOR_CATEGORIES = [
    ("red",                5,         20,        90,      40,      255),
    ("orange",             30,        18,        90,      40,      255),
    ("copper",             20,        20,        120,     120,     200),
    ("yellow",             52,        18,        90,      60,      255),
    ("gold_metallic",      45,        25,        120,     170,     255),
    ("cream",              55,        20,        40,      200,     255),
    ("green",              110,       45,        80,      40,      255),
    ("teal",               165,       30,        70,      40,      255),
    ("cyan",               185,       25,        80,      60,      255),
    ("blue",               210,       35,        80,      40,      255),
    ("dark_blue",          220,       30,        60,      0,       80),
    ("purple",             275,       30,        70,      40,      255),
    ("violet",             295,       25,        70,      40,      255),
    ("pink",               320,       30,        70,      40,      255),
    ("bronze",             25,        20,        100,     80,      160),
    ("white",              0,         360,       0,       200,     255),
    ("silver",             0,         360,       0,       120,     200),
    ("black",              0,         360,       0,       0,       60),
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
# WHITE BALANCE
# ============================================================

def _normalize_white_balance(rgb: np.ndarray) -> np.ndarray:
    try:
        lum = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
        threshold = np.percentile(lum, 95)
        bright_mask = lum >= threshold

        if bright_mask.sum() < 20:
            return rgb

        illuminant = rgb[bright_mask].mean(axis=0)
        if np.any(illuminant < 1e-3):
            return rgb

        target = illuminant.mean()
        scale = target / np.maximum(illuminant, 1e-3)

        normalized = rgb * scale[None, None, :]
        return np.clip(normalized, 0, 255)
    except Exception:
        return rgb


# ============================================================
# WATER TINT DETECTION
# ============================================================

def _detect_water_tint(hsv: np.ndarray) -> Optional[tuple[float, float]]:
    try:
        h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        H, W = h.shape

        border = np.zeros((H, W), dtype=bool)
        b = max(2, int(min(H, W) * 0.10))
        border[:b, :] = True
        border[-b:, :] = True
        border[:, :b] = True
        border[:, -b:] = True

        border_mask = border & (s > 40) & (s < 150) & (v > 40) & (v < 220)
        if border_mask.sum() < 100:
            return None

        border_hues = h[border_mask]

        bins = (border_hues // 20).astype(int) % 18
        counts = np.bincount(bins, minlength=18)
        peak_bin = int(np.argmax(counts))
        peak_pct = counts[peak_bin] / len(border_hues)

        if peak_pct < 0.35:
            return None

        hue_center = (peak_bin + 0.5) * 20
        hue_width = 20
        return (hue_center, hue_width)
    except Exception:
        return None


# ============================================================
# ADAPTIVE BACKGROUND DETECTION
# ============================================================

def _detect_background_color_cluster(rgb: np.ndarray) -> Optional[tuple[int, int, int]]:
    try:
        H, W = rgb.shape[:2]
        b = max(2, int(min(H, W) * 0.10))

        border = np.concatenate([
            rgb[:b, :].reshape(-1, 3),
            rgb[-b:, :].reshape(-1, 3),
            rgb[:, :b].reshape(-1, 3),
            rgb[:, -b:].reshape(-1, 3),
        ])

        if len(border) < 100:
            return None

        quantized = (border // 32) * 32
        uniq, counts = np.unique(quantized, axis=0, return_counts=True)
        if len(uniq) == 0:
            return None

        top_idx = int(np.argmax(counts))
        top_pct = counts[top_idx] / len(border)

        if top_pct < 0.30:
            return None

        return tuple(int(c) for c in uniq[top_idx])
    except Exception:
        return None


def _mask_adaptive_background(rgb: np.ndarray, bg_color: Optional[tuple[int, int, int]],
                                tolerance: int = 60) -> np.ndarray:
    if bg_color is None:
        return np.ones(rgb.shape[:2], dtype=bool)

    diff = rgb.astype(np.int32) - np.array(bg_color, dtype=np.int32)[None, None, :]
    dist = np.sqrt((diff ** 2).sum(axis=-1))
    return dist > tolerance


# ============================================================
# FISH MASK (Session 26D round 3: tighter reflection filter)
# ============================================================

def _mask_fish_region(
    hsv: np.ndarray,
    rgb: np.ndarray,
    water_tint: Optional[tuple[float, float]] = None,
    bg_color: Optional[tuple[int, int, int]] = None,
) -> np.ndarray:
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]

    is_fish = np.ones_like(s, dtype=bool)

    is_fish &= ~(s < 30)
    is_fish &= ~(v > 240)
    is_fish &= ~(v < 25)

    # Round 3: tighter reflection filter — catches silver glass sheen
    # Bright AND low-saturation = glass/water/tape surface
    is_reflection = (v > 195) & (s < 60)
    is_fish &= ~is_reflection

    if water_tint is not None:
        wc_h, wc_w = water_tint
        water_like = (
            (np.abs(((h - wc_h + 180) % 360) - 180) <= wc_w / 2)
            & (s > 40) & (s < 150)
            & (v > 40) & (v < 220)
        )
        is_fish &= ~water_like

    if bg_color is not None:
        not_bg = _mask_adaptive_background(rgb, bg_color)
        is_fish &= not_bg

    H, W = s.shape
    y0, y1 = int(H * 0.15), int(H * 0.85)
    x0, x1 = int(W * 0.15), int(W * 0.85)

    center_mask = np.zeros_like(is_fish, dtype=bool)
    center_mask[y0:y1, x0:x1] = True
    is_fish &= center_mask

    return is_fish


# ============================================================
# BLOB QUALITY GATE
# ============================================================

def _blob_quality_ok(mask: np.ndarray, blob_mask: np.ndarray, rgb: np.ndarray) -> bool:
    try:
        if blob_mask.sum() < 30:
            return False

        ys, xs = np.where(blob_mask)
        h_span = xs.max() - xs.min() + 1
        v_span = ys.max() - ys.min() + 1

        if h_span < 5 or v_span < 5:
            return False

        aspect = max(h_span, v_span) / max(1, min(h_span, v_span))
        if aspect < 1.15:
            return False

        bbox_area = h_span * v_span
        fill_ratio = blob_mask.sum() / max(1, bbox_area)
        if fill_ratio > 0.85:
            return False

        H, W = mask.shape
        b = 2
        if xs.min() < b or ys.min() < b or xs.max() > W - 1 - b or ys.max() > H - 1 - b:
            if blob_mask.sum() / mask.size < 0.05:
                return False

        blob_pixels = rgb[blob_mask]
        if len(blob_pixels) < 10:
            return False

        std_rgb = blob_pixels.std(axis=0).mean()
        if std_rgb < 8:
            return False

        blob_f = blob_pixels.astype(np.float32)
        maxc = blob_f.max(axis=1)
        minc = blob_f.min(axis=1)
        sat = np.where(maxc > 1e-3, (maxc - minc) / np.maximum(maxc, 1e-3), 0.0)

        avg_sat = float(sat.mean())
        std_sat = float(sat.std())

        if avg_sat < 0.15:
            return False

        if avg_sat < 0.25 and std_sat < 0.08:
            return False

        return True
    except Exception:
        return True


def _isolate_largest_blob(mask: np.ndarray, rgb: np.ndarray, min_size_pct: float = 0.5) -> np.ndarray:
    if not _SCIPY_AVAILABLE or mask.sum() == 0:
        return mask

    try:
        labeled, num = _ndimage.label(mask)
        if num == 0:
            return mask

        component_sizes = _ndimage.sum(mask, labeled, index=range(1, num + 1))
        if len(component_sizes) == 0:
            return mask

        order = np.argsort(-component_sizes) + 1

        for comp_id in order:
            blob_mask = (labeled == comp_id)
            if blob_mask.sum() / mask.size < min_size_pct / 100.0:
                break
            if _blob_quality_ok(mask, blob_mask, rgb):
                return blob_mask

        largest_mask = (labeled == order[0])
        if largest_mask.sum() / mask.size < min_size_pct / 100.0:
            return mask
        return largest_mask
    except Exception:
        return mask


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
    for name in ("gold_metallic", "copper", "bronze"):
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

    if s < 60 and v > 200 and (h < 70 or h > 320):
        return "cream"

    if v < 80 and 200 < h < 250:
        return "dark_blue"

    best = None
    best_dist = 999
    for name, hc, hw, smin, vmin, vmax in COLOR_CATEGORIES:
        if name in ("white", "silver", "black", "gold_metallic", "copper", "bronze", "cream", "dark_blue"):
            continue
        if s < smin or not (vmin <= v <= vmax):
            continue
        d = _hue_distance(h, hc)
        if d <= hw and d < best_dist:
            best = name
            best_dist = d

    return best


# ============================================================
# SESSION 26D ROUND 3 — SILVER NOISE SUPPRESSION
# ============================================================

def _suppress_silver_noise(
    palette: dict[str, float],
    centroids: np.ndarray,
    labels: np.ndarray,
) -> dict[str, float]:
    """
    Post-cluster cleanup:
    If a silver/grey cluster is small (< 20% of pixels) and NOT dominant,
    downgrade it. Real silver fish have silver as the biggest cluster.

    Also: if `white` and `silver` together are < 25%, they're probably
    glass reflections and should be reduced.
    """
    try:
        total = sum(palette.values())
        if total <= 0:
            return palette

        # Compute per-category percentage and cluster size
        keys = list(palette.keys())

        # If silver is present but not the largest, shrink it
        if "silver" in palette:
            silver_pct = palette["silver"]
            largest_pct = max(palette.values())

            # If silver < 20% AND not the largest → shrink by 60%
            if silver_pct < 20 and silver_pct < largest_pct:
                palette["silver"] = round(silver_pct * 0.4, 1)

        # Same for white if it's smaller than 15% (usually tape/glare)
        if "white" in palette:
            white_pct = palette["white"]
            largest_pct = max(palette.values())
            if white_pct < 15 and white_pct < largest_pct:
                palette["white"] = round(white_pct * 0.5, 1)

        # Drop anything now below 3%
        palette = {k: v for k, v in palette.items() if v >= 3.0}

        # Re-sort
        palette = dict(sorted(palette.items(), key=lambda x: -x[1]))
        return palette
    except Exception:
        return palette


# ============================================================
# IRIDESCENCE
# ============================================================

def _detect_iridescence(hsv: np.ndarray, mask: np.ndarray) -> tuple[str, int]:
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]

    if mask.sum() < 50:
        return "none", 0

    sparkle = (v > 160) & (s > 80) & mask
    sparkle_count = sparkle.sum()

    if sparkle_count < 20:
        return "none", 0

    sparkle_pct = sparkle_count / mask.sum() * 100

    if _SCIPY_AVAILABLE:
        try:
            local_mean = _ndimage.uniform_filter(v, size=7)
            local_var = _ndimage.uniform_filter((v - local_mean) ** 2, size=7)
            sparkle_variance = float(np.sqrt(local_var[sparkle]).mean())
        except Exception:
            sparkle_variance = float(v[sparkle].std())
    else:
        sparkle_variance = float(v[sparkle].std())

    sparkle_hues = h[sparkle]
    bins = (sparkle_hues // 60).astype(int) % 6
    unique_bins = len(np.unique(bins))

    pct_factor = min(sparkle_pct / 20.0, 1.0)
    var_factor = min(sparkle_variance / 40.0, 1.0)
    diversity_factor = min(unique_bins / 3.0, 1.0)

    score = int(min(pct_factor * var_factor * diversity_factor * 150, 100))

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

def analyze_photo(raw_bytes: bytes, k_clusters: int = 5, use_blob: bool = True) -> Optional[dict]:
    img = _load_image_rgb(raw_bytes)
    if img is None:
        return {"ok": False, "error": "Could not load image"}

    img.thumbnail((640, 640), Image.LANCZOS)

    rgb = np.asarray(img).astype(np.float32)
    rgb = _normalize_white_balance(rgb)
    rgb_u8 = np.clip(rgb, 0, 255).astype(np.uint8)
    hsv = _rgb_to_hsv_numpy(rgb_u8)

    water_tint = _detect_water_tint(hsv)
    bg_color = _detect_background_color_cluster(rgb_u8)

    mask = _mask_fish_region(hsv, rgb_u8, water_tint=water_tint, bg_color=bg_color)
    if mask.sum() < 50:
        return {"ok": False, "error": "Too little fish region detected"}

    if use_blob:
        mask = _isolate_largest_blob(mask, rgb_u8, min_size_pct=0.5)
        if mask.sum() < 50:
            return {"ok": False, "error": "No significant fish region found"}

    fish_pixels = rgb_u8[mask]
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

    # Session 26D round 3: suppress silver/white glass noise
    palette = _suppress_silver_noise(palette, centroids, labels)

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
        "debug": {
            "water_tint_detected": water_tint is not None,
            "adaptive_bg_detected": bg_color is not None,
        },
    }


# ============================================================
# REGION ANALYSIS
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

    analysis = analyze_photo(cropped_bytes, k_clusters=k_clusters, use_blob=False)
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
# VIDEO FRAME EXTRACTION
# ============================================================

def extract_frames_from_video(
    video_bytes: bytes,
    sample_every: int = 5,
    max_frames: int = 30,
    target_width: int = 640,
) -> list[bytes]:
    if not _AV_AVAILABLE:
        raise RuntimeError("PyAV (av) not installed. Run: `py -m pip install av`")

    frames: list[bytes] = []
    stream = io.BytesIO(video_bytes)

    try:
        container = av.open(stream)
    except Exception as e:
        raise RuntimeError(f"Could not open video: {e}")

    try:
        video_stream = next(
            (s for s in container.streams if s.type == "video"),
            None,
        )
        if video_stream is None:
            raise RuntimeError("No video stream found in file")

        idx = 0
        for frame in container.decode(video_stream):
            if idx % sample_every == 0:
                try:
                    img = frame.to_image()
                    w, h = img.size
                    if w > target_width:
                        ratio = target_width / w
                        img = img.resize((target_width, int(h * ratio)), Image.LANCZOS)
                    if img.mode not in ("RGB", "L"):
                        img = img.convert("RGB")

                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=85)
                    frames.append(buf.getvalue())

                    if len(frames) >= max_frames:
                        break
                except Exception:
                    pass
            idx += 1
    finally:
        try:
            container.close()
        except Exception:
            pass

    return frames


def analyze_video(
    video_bytes: bytes,
    sample_every: int = 5,
    max_frames: int = 30,
    k_clusters: int = 5,
) -> dict:
    try:
        frames = extract_frames_from_video(
            video_bytes,
            sample_every=sample_every,
            max_frames=max_frames,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if not frames:
        return {"ok": False, "error": "No frames could be extracted"}

    analyses = []
    frame_indices = []

    for fi, fbytes in enumerate(frames):
        try:
            a = analyze_photo(fbytes, k_clusters=k_clusters, use_blob=True)
            if a and a.get("ok"):
                if a.get("coverage_pct", 0) >= 2.0:
                    analyses.append(a)
                    frame_indices.append(fi)
        except Exception:
            continue

    if len(analyses) < 3:
        return {
            "ok": False,
            "error": (
                f"Only {len(analyses)} clear frames found. "
                "Try a clearer video with the fish filling more of the frame."
            ),
        }

    consensus = merge_analyses(analyses)

    best_analysis_idx = max(
        range(len(analyses)),
        key=lambda i: (analyses[i].get("quality", {}) or {}).get("score", 0),
    )
    best_frame_idx = frame_indices[best_analysis_idx] if best_analysis_idx < len(frame_indices) else 0
    best_frame_bytes = frames[best_frame_idx] if 0 <= best_frame_idx < len(frames) else None

    return {
        "ok": True,
        "frames_analyzed": len(analyses),
        "analyses": analyses,
        "consensus": consensus,
        "best_frame_idx": best_frame_idx,
        "best_frame_bytes": best_frame_bytes,
    }


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
        "best_shot_index": max(
            range(len(analyses)),
            key=lambda i: (analyses[i] or {}).get("quality", {}).get("score", 0),
        ),
    }


# ============================================================
# DISPLAY HELPERS
# ============================================================

COLOR_SWATCHES = {
    "red": "#DC2626",
    "orange": "#EA580C",
    "yellow": "#EAB308",
    "cream": "#FEF3C7",
    "green": "#16A34A",
    "teal": "#14B8A6",
    "cyan": "#06B6D4",
    "blue": "#2563EB",
    "dark_blue": "#1E3A8A",
    "purple": "#7C3AED",
    "violet": "#8B5CF6",
    "pink": "#DB2777",
    "white": "#F3F4F6",
    "black": "#1F2937",
    "silver": "#9CA3AF",
    "gold_metallic": "#D4AF37",
    "copper": "#B87333",
    "bronze": "#92400E",
}


def color_swatch_html(color: str, size: int = 16) -> str:
    hex_color = COLOR_SWATCHES.get(color, "#E5E7EB")
    border = "border:1px solid #D1D5DB;" if color in ("white", "silver", "cream") else ""
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
