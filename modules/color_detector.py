# modules/color_detector.py
# Betta Farm Management System
# Session 26A — Color analysis via computer vision.
# Session 26B — Added analyze_region() for tap-to-select flow.
# Session 26C — Added extract_frames_from_video() for video upload flow.
# Session 26C fix — Added blob detection to isolate largest fish.
# Session 26D — Major accuracy upgrade + verified.
# Session 26D round 2 — Reject low-saturation blobs.
# Session 26D round 3 — Suppress silver glass noise.
# Session 26E — Two-pass posture strategy + 5-region split + Side A/B.
#   • Pass 1 (strict): clean side profile + fully flared + complete
#   • Pass 2 (lenient + regional): per-frame regional fallback
#   • Head-on/top-down detection via IBC body ratio (length/depth ≥ 2.0)
#   • Regions aligned to HMPK anatomy: head 20% / body 45% / tail 35%
#   • Tuned for real flared bettas (wide aspect, tank reflections)
#   • Side A = head-left, Side B = head-right
#   • tap-to-select crops bypass posture via skip_posture=True

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
# POSTURE VALIDATION CONSTANTS (Session 26E, tuned)
# ============================================================

# Side profile: elongated blob. Flared bettas are WIDE — lower threshold.
# Head-on/top-down gives ~1.0 aspect. Flared side view gives 1.05–1.5.
MIN_ASPECT_RATIO = 1.05

# IBC body ratio: side views have a long thin body, head-on is square.
# From ibc_standards.MEASURABLE_CRITERIA["body_length_depth_ratio"]
MIN_BODY_RATIO_SIDE = 2.0       # strict side view
MIN_BODY_RATIO_PARTIAL = 1.6    # lenient regional fallback

# Coverage: blob must be >=2% of frame
MIN_COVERAGE_PCT = 2.0

# Flare: solidity below this = distinct fin extensions
MAX_SOLIDITY_FLARED = 0.92
# Minimum fin-extension pixels outside core-body ellipse
MIN_FLARE_PIXELS = 100
# Tail width vs mid-body width (only meaningful when near-horizontal)
MIN_TAIL_SPREAD_RATIO = 1.1

# Region split fractions — HMPK anatomy-aligned
# head = front of fish (eye+gill), body = torso, tail = caudal fin
HEAD_REGION_FRAC = 0.20
BODY_REGION_FRAC = 0.45
TAIL_REGION_FRAC = 0.35

# Region weights for palette merge
REGION_WEIGHTS = {
    "head":   0.15,
    "body":   0.35,
    "tail":   0.20,
    "dorsal": 0.15,
    "anal":   0.15,
}

# Pass thresholds
MIN_STRICT_FRAMES = 3
MIN_PARTIAL_REGION_FRAMES = 3
MIN_REGION_PIXELS = 30
EDGE_MARGIN_PX = 2


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
# WATER TINT / BACKGROUND
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
# FISH MASK
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
# BLOB QUALITY + ISOLATION
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
# ORIENTATION (PCA, vectorized)
# ============================================================

def _compute_orientation(blob_mask: np.ndarray) -> dict:
    default = {
        "major_axis_angle_deg": 0.0,
        "length": 0.0,
        "height": 0.0,
        "aspect": 0.0,
        "head_direction": "unknown",
        "proj_major": None,
        "proj_minor": None,
        "mean": None,
        "major_vec": None,
        "minor_vec": None,
    }

    try:
        ys, xs = np.where(blob_mask)
        if len(xs) < 10:
            return default

        points = np.column_stack([xs, ys]).astype(np.float32)
        mean = points.mean(axis=0)
        centered = points - mean

        cov = np.cov(centered.T)
        eigvals, eigvecs = np.linalg.eig(cov)
        major_idx = int(np.argmax(eigvals))
        minor_idx = 1 - major_idx
        major_vec = eigvecs[:, major_idx].astype(np.float32)
        minor_vec = eigvecs[:, minor_idx].astype(np.float32)

        proj_major = centered @ major_vec
        proj_minor = centered @ minor_vec

        length = float(proj_major.max() - proj_major.min()) + 1
        height = float(proj_minor.max() - proj_minor.min()) + 1
        aspect = length / max(1.0, height)

        angle_rad = math.atan2(major_vec[1], major_vec[0])
        angle_deg = math.degrees(angle_rad) % 180

        maj_min = float(proj_major.min())
        maj_max = float(proj_major.max())
        span = max(1e-6, maj_max - maj_min)
        lo_cut = maj_min + span / 3.0
        hi_cut = maj_max - span / 3.0

        lo_mask = proj_major <= lo_cut
        hi_mask = proj_major >= hi_cut

        if lo_mask.sum() < 3 or hi_mask.sum() < 3:
            head_direction = "left" if (proj_major < 0).sum() > (proj_major >= 0).sum() else "right"
        else:
            lo_spread = float(proj_minor[lo_mask].max() - proj_minor[lo_mask].min())
            hi_spread = float(proj_minor[hi_mask].max() - proj_minor[hi_mask].min())

            if abs(lo_spread - hi_spread) < 1.0:
                head_direction = "left" if (proj_major < 0).sum() > (proj_major >= 0).sum() else "right"
            elif lo_spread < hi_spread:
                if 60 <= angle_deg <= 120:
                    head_direction = "up"
                else:
                    head_direction = "left"
            else:
                if 60 <= angle_deg <= 120:
                    head_direction = "down"
                else:
                    head_direction = "right"

        return {
            "major_axis_angle_deg": round(angle_deg, 1),
            "length": round(length, 1),
            "height": round(height, 1),
            "aspect": round(aspect, 2),
            "head_direction": head_direction,
            "proj_major": proj_major,
            "proj_minor": proj_minor,
            "mean": mean,
            "major_vec": major_vec,
            "minor_vec": minor_vec,
        }
    except Exception:
        return default


# ============================================================
# BODY RATIO (IBC body_length_depth_ratio)
# ============================================================

def _compute_body_ratio(blob_mask: np.ndarray, orientation: dict) -> float:
    """
    Compute IBC body_length_depth_ratio from the BODY region only
    (excluding dorsal/anal fin extensions).

    Uses the middle 40% of the major axis to isolate the torso.
    Head-on fish → ~0.8–1.8.  Side-view fish → 2.5–4.5.

    Returns 0.0 if the ratio cannot be computed.
    """
    try:
        proj_major = orientation.get("proj_major")
        proj_minor = orientation.get("proj_minor")
        if proj_major is None or proj_minor is None:
            return 0.0
        if len(proj_major) < 50:
            return 0.0

        maj_min = float(proj_major.min())
        maj_max = float(proj_major.max())
        span = max(1e-6, maj_max - maj_min)

        body_lo = maj_min + span * 0.30
        body_hi = maj_min + span * 0.70
        body_band = (proj_major >= body_lo) & (proj_major <= body_hi)

        if body_band.sum() < 30:
            return 0.0

        body_length = float(
            proj_major[body_band].max() - proj_major[body_band].min()
        )
        body_depth = float(
            proj_minor[body_band].max() - proj_minor[body_band].min()
        )

        if body_depth < 1.0:
            return 0.0

        return body_length / body_depth
    except Exception:
        return 0.0


# ============================================================
# FLARE DETECTION (Session 26E, tuned)
# ============================================================

def _detect_flare(blob_mask: np.ndarray, orientation: dict) -> dict:
    """
    Detect fin flare using:
      1. Solidity (blob area / convex hull area)
      2. Fin-extension pixel count outside core-body ellipse
      3. Tail spread ratio (only counted when near-horizontal)

    Flared if >= 1 signal. Hard-reject if aspect > 3.5 (tube).
    """
    try:
        if blob_mask.sum() < 30:
            return {"is_flared": False, "confidence": 0.0,
                    "reason": "Blob too small", "solidity": 1.0,
                    "extension_px": 0, "tail_ratio": 1.0}

        solidity = 1.0
        if _SCIPY_AVAILABLE:
            try:
                filled = _ndimage.binary_fill_holes(blob_mask)
                hull = _ndimage.binary_dilation(filled, iterations=3)
                hull = _ndimage.binary_fill_holes(hull)
                hull_area = float(hull.sum())
                blob_area = float(blob_mask.sum())
                solidity = blob_area / max(1.0, hull_area)
            except Exception:
                solidity = 1.0

        extension_px = 0
        try:
            ys, xs = np.where(blob_mask)
            if len(xs) > 0:
                cx = float(xs.mean())
                cy = float(ys.mean())
                h_span = xs.max() - xs.min() + 1
                v_span = ys.max() - ys.min() + 1
                a = h_span * 0.30
                b = v_span * 0.30
                if a > 0 and b > 0:
                    inside = ((xs - cx) / a) ** 2 + ((ys - cy) / b) ** 2 <= 1.0
                    extension_px = int((~inside).sum())
        except Exception:
            extension_px = 0

        tail_ratio = 1.0
        proj_major = orientation.get("proj_major")
        proj_minor = orientation.get("proj_minor")
        if proj_major is not None and proj_minor is not None and len(proj_major) > 10:
            try:
                maj_min = float(proj_major.min())
                maj_max = float(proj_major.max())
                span = max(1e-6, maj_max - maj_min)
                hd = orientation.get("head_direction", "left")

                if hd in ("left", "up"):
                    tail_lo = maj_min + span * 0.75
                    mid_lo = maj_min + span * 0.35
                    mid_hi = maj_min + span * 0.65
                    tail_mask = proj_major >= tail_lo
                else:
                    tail_lo = maj_max - span * 0.75
                    mid_lo = maj_min + span * 0.35
                    mid_hi = maj_min + span * 0.65
                    tail_mask = proj_major <= tail_lo

                mid_mask = (proj_major >= mid_lo) & (proj_major <= mid_hi)

                if tail_mask.sum() > 5 and mid_mask.sum() > 5:
                    tail_w = float(proj_minor[tail_mask].max() - proj_minor[tail_mask].min())
                    mid_w = float(proj_minor[mid_mask].max() - proj_minor[mid_mask].min())
                    tail_ratio = tail_w / max(1e-6, mid_w)
            except Exception:
                tail_ratio = 1.0

        flared_signals = 0
        if solidity <= MAX_SOLIDITY_FLARED:
            flared_signals += 1
        if extension_px >= MIN_FLARE_PIXELS:
            flared_signals += 1

        angle = orientation.get("major_axis_angle_deg", 0)
        near_horizontal = (angle < 30) or (angle > 150)
        if near_horizontal and tail_ratio >= MIN_TAIL_SPREAD_RATIO:
            flared_signals += 1

        is_flared = flared_signals >= 1

        aspect = orientation.get("aspect", 0)
        if aspect > 3.5:
            is_flared = False

        confidence = min(1.0, 0.25 + 0.25 * flared_signals) if is_flared else 0.0

        reason_bits = [
            f"solidity={solidity:.2f}",
            f"ext_px={extension_px}",
            f"tail_ratio={tail_ratio:.2f}",
        ]
        reason = ("flared" if is_flared else "clamped") + " (" + ", ".join(reason_bits) + ")"

        return {
            "is_flared": is_flared,
            "confidence": round(confidence, 2),
            "reason": reason,
            "solidity": round(solidity, 3),
            "extension_px": int(extension_px),
            "tail_ratio": round(tail_ratio, 3),
        }
    except Exception as e:
        return {"is_flared": False, "confidence": 0.0,
                "reason": f"Flare check failed: {e}",
                "solidity": 1.0, "extension_px": 0, "tail_ratio": 1.0}


# ============================================================
# COMPLETENESS
# ============================================================

def _check_completeness(blob_mask: np.ndarray, orientation: dict) -> dict:
    try:
        H, W = blob_mask.shape
        ys, xs = np.where(blob_mask)
        if len(xs) < 30:
            return {"complete": False, "partial_ok": False,
                    "reason": "Blob too small"}

        b = EDGE_MARGIN_PX
        touches_edge = (
            xs.min() <= b or ys.min() <= b
            or xs.max() >= W - 1 - b or ys.max() >= H - 1 - b
        )

        if not touches_edge:
            return {"complete": True, "partial_ok": True,
                    "reason": "Full fish visible"}

        proj_major = orientation.get("proj_major")
        if proj_major is None or len(proj_major) < 10:
            return {"complete": False, "partial_ok": False,
                    "reason": "Partial visibility, cannot assess regions"}

        maj_min = float(proj_major.min())
        maj_max = float(proj_major.max())
        span = max(1e-6, maj_max - maj_min)
        mid_lo = maj_min + span * 0.30
        mid_hi = maj_min + span * 0.70

        mid_mask = (proj_major >= mid_lo) & (proj_major <= mid_hi)
        mid_px = int(mid_mask.sum())

        if mid_px >= max(30, int(0.25 * len(proj_major))):
            return {"complete": False, "partial_ok": True,
                    "reason": "Partial fish — body + fin region visible"}
        return {"complete": False, "partial_ok": False,
                "reason": "Partial fish — body not sufficiently visible"}
    except Exception:
        return {"complete": False, "partial_ok": False,
                "reason": "Completeness check failed"}


# ============================================================
# POSTURE VALIDATION (Session 26E)
# ============================================================

def validate_fish_posture(blob_mask: np.ndarray, rgb: np.ndarray,
                           coverage_pct: float) -> dict:
    orientation = _compute_orientation(blob_mask)
    flare = _detect_flare(blob_mask, orientation)
    completeness = _check_completeness(blob_mask, orientation)

    aspect = orientation.get("aspect", 0)
    aspect_ok = aspect >= MIN_ASPECT_RATIO

    # IBC body ratio: side views have a long thin body (2.0–4.5),
    # head-on views have a squarish body (0.8–1.8).
    body_ratio = _compute_body_ratio(blob_mask, orientation)
    body_ratio_ok = body_ratio >= MIN_BODY_RATIO_SIDE

    is_side_profile = aspect_ok and body_ratio_ok
    is_complete = completeness.get("complete", False)
    is_partial_ok = completeness.get("partial_ok", False)
    is_flared = flare.get("is_flared", False)
    flare_conf = flare.get("confidence", 0.0)

    coverage_ok = coverage_pct >= MIN_COVERAGE_PCT

    head_dir = orientation.get("head_direction", "unknown")
    if head_dir == "left":
        side_label = "A"
    elif head_dir == "right":
        side_label = "B"
    else:
        side_label = "?"

    base = {
        "side_profile": is_side_profile,
        "body_ratio": round(body_ratio, 2),
        "flared": is_flared,
        "complete": is_complete,
        "partial_ok": is_partial_ok,
        "head_direction": head_dir,
        "side_label": side_label,
        "orientation": {k: v for k, v in orientation.items()
                        if k not in ("proj_major", "proj_minor", "mean",
                                      "major_vec", "minor_vec")},
        "flare": flare,
    }

    # --- PASS 1: strict ---
    if (coverage_ok and is_side_profile and is_flared and flare_conf >= 0.5
            and (is_complete or is_partial_ok)):
        base["pass"] = 1
        base["reason"] = "Strict pass — side profile + flared"
        return base

    # --- PASS 2: regional fallback ---
    if (coverage_ok and aspect >= 1.0 and body_ratio >= MIN_BODY_RATIO_PARTIAL
            and is_partial_ok):
        base["pass"] = 2
        base["reason"] = (
            "Regional pass — "
            + ("flared" if is_flared else "possibly clamped")
        )
        return base

    # --- PASS 3: reject ---
    base["pass"] = 3
    if not coverage_ok:
        base["reason"] = "Fish too small in frame"
    elif not aspect_ok:
        base["reason"] = "Not a side profile (head-on or top-down)"
    elif not body_ratio_ok:
        base["reason"] = (
            f"Fish facing camera (body ratio {body_ratio:.2f}, "
            f"need ≥{MIN_BODY_RATIO_SIDE} for side view)"
        )
    elif not is_partial_ok:
        base["reason"] = "Fish cut off — body not visible enough"
    else:
        base["reason"] = "Posture rejected"
    return base


# ============================================================
# 5-REGION SPLIT (Session 26E, vectorized, HMPK-aligned)
# ============================================================

def _split_blob_into_regions(blob_mask: np.ndarray,
                              orientation: Optional[dict] = None) -> dict:
    try:
        if orientation is None:
            orientation = _compute_orientation(blob_mask)

        proj_major = orientation.get("proj_major")
        proj_minor = orientation.get("proj_minor")
        mean = orientation.get("mean")

        if proj_major is None or mean is None:
            return {}

        ys, xs = np.where(blob_mask)
        if len(xs) < 10:
            return {}

        maj_min = float(proj_major.min())
        maj_max = float(proj_major.max())
        span = max(1e-6, maj_max - maj_min)
        norm_major = (proj_major - maj_min) / span

        hd = orientation.get("head_direction", "left")

        if hd in ("left", "up", "unknown"):
            canon = norm_major
        else:
            canon = 1.0 - norm_major

        # HMPK anatomy-aligned bands:
        #   head = 0.00 .. 0.20 (eye + gill)
        #   body = 0.20 .. 0.65 (torso)
        #   tail = 0.65 .. 1.00 (caudal fin)
        is_head = canon < HEAD_REGION_FRAC
        is_tail = canon >= (HEAD_REGION_FRAC + BODY_REGION_FRAC)
        is_body = ~is_head & ~is_tail

        dorsal = proj_minor < 0
        anal = proj_minor >= 0

        head_mask = np.zeros_like(blob_mask, dtype=bool)
        body_mask = np.zeros_like(blob_mask, dtype=bool)
        tail_mask = np.zeros_like(blob_mask, dtype=bool)
        dorsal_mask = np.zeros_like(blob_mask, dtype=bool)
        anal_mask = np.zeros_like(blob_mask, dtype=bool)

        head_mask[ys[is_head], xs[is_head]] = True
        body_mask[ys[is_body], xs[is_body]] = True
        tail_mask[ys[is_tail], xs[is_tail]] = True
        dorsal_mask[ys[dorsal], xs[dorsal]] = True
        anal_mask[ys[anal], xs[anal]] = True

        return {
            "head_mask": head_mask,
            "body_mask": body_mask,
            "tail_mask": tail_mask,
            "dorsal_mask": dorsal_mask,
            "anal_mask": anal_mask,
            "head_direction": hd,
        }
    except Exception:
        return {}


# ============================================================
# PER-REGION PALETTE
# ============================================================

def _palette_for_mask(
    rgb_u8: np.ndarray,
    region_mask: np.ndarray,
    k_clusters: int = 4,
) -> dict[str, float]:
    if region_mask.sum() < MIN_REGION_PIXELS:
        return {}

    region_pixels = rgb_u8[region_mask]
    centroids, labels = _kmeans(region_pixels.astype(np.float32), k=k_clusters)

    counts = np.bincount(labels, minlength=len(centroids))
    total = counts.sum()
    if total == 0:
        return {}

    pcts = counts / total * 100

    palette: dict[str, float] = {}
    for ci, c in enumerate(centroids):
        c_rgb = np.array([[[c[0], c[1], c[2]]]], dtype=np.uint8)
        c_hsv = _rgb_to_hsv_numpy(c_rgb)[0, 0]
        ch, cs, cv = float(c_hsv[0]), float(c_hsv[1]), float(c_hsv[2])
        cat = _map_hsv_to_category(ch, cs, cv)
        if cat:
            palette[cat] = palette.get(cat, 0) + float(pcts[ci])

    return palette


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
        if name in ("white", "silver", "black", "gold_metallic",
                    "copper", "bronze", "cream", "dark_blue"):
            continue
        if s < smin or not (vmin <= v <= vmax):
            continue
        d = _hue_distance(h, hc)
        if d <= hw and d < best_dist:
            best = name
            best_dist = d

    return best


# ============================================================
# SILVER NOISE SUPPRESSION
# ============================================================

def _suppress_silver_noise(palette: dict[str, float]) -> dict[str, float]:
    try:
        if not palette:
            return palette

        if "silver" in palette:
            silver_pct = palette["silver"]
            largest_pct = max(palette.values())
            if silver_pct < 20 and silver_pct < largest_pct:
                palette["silver"] = round(silver_pct * 0.4, 1)

        if "white" in palette:
            white_pct = palette["white"]
            largest_pct = max(palette.values())
            if white_pct < 15 and white_pct < largest_pct:
                palette["white"] = round(white_pct * 0.5, 1)

        palette = {k: v for k, v in palette.items() if v >= 3.0}
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
# REGION MERGE HELPERS
# ============================================================

def _merge_region_palettes(region_palettes: dict[str, dict[str, float]]) -> dict[str, float]:
    if not region_palettes:
        return {}

    merged: dict[str, float] = {}
    total_weight = 0.0
    for region_name, pal in region_palettes.items():
        weight = REGION_WEIGHTS.get(region_name, 0.0)
        if weight == 0 or not pal:
            continue
        total_weight += weight
        for color, pct in pal.items():
            merged[color] = merged.get(color, 0) + pct * weight

    if total_weight > 0:
        merged = {k: round(v / total_weight, 1) for k, v in merged.items()}

    merged = {k: v for k, v in merged.items() if v >= 3.0}
    merged = _suppress_silver_noise(merged)
    return dict(sorted(merged.items(), key=lambda x: -x[1]))


def _classify_pattern(palette: dict[str, float]) -> str:
    if not palette:
        return "unknown"
    keys = list(palette.keys())
    if len(keys) == 1 or palette[keys[0]] >= 60:
        return "solid"
    if len(keys) == 2 and sum(palette.values()) >= 70:
        return "bi-color"
    return "multicolor"


# ============================================================
# MAIN: ANALYZE PHOTO (Session 26E two-pass)
# ============================================================

def analyze_photo(raw_bytes: bytes, k_clusters: int = 5,
                  use_blob: bool = True, skip_posture: bool = False) -> Optional[dict]:
    """
    Analyze a photo using 5-region full-fish split + posture validation.

    skip_posture=True bypasses posture validation — used by analyze_region()
    for tap-to-select crops that aren't full-fish silhouettes.
    """
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

    coverage_pct = float(mask.sum() / mask.size * 100)

    if skip_posture:
        posture = {
            "pass": 1,
            "side_profile": True,
            "body_ratio": 0.0,
            "flared": True,
            "complete": True,
            "partial_ok": True,
            "head_direction": "unknown",
            "side_label": "?",
            "reason": "Posture validation skipped (region crop)",
        }
        pass_num = 1
    else:
        posture = validate_fish_posture(mask, rgb_u8, coverage_pct)
        pass_num = posture.get("pass", 3)

        if pass_num == 3:
            return {
                "ok": False,
                "error": "Fish posture not usable — try a side-profile shot with fins flared",
                "posture": posture,
            }

    orientation_full = _compute_orientation(mask)
    regions = _split_blob_into_regions(mask, orientation=orientation_full)

    if not regions:
        regions = {
            "body_mask": mask,
            "head_mask": np.zeros_like(mask, dtype=bool),
            "tail_mask": np.zeros_like(mask, dtype=bool),
            "dorsal_mask": np.zeros_like(mask, dtype=bool),
            "anal_mask": np.zeros_like(mask, dtype=bool),
            "head_direction": posture.get("head_direction", "unknown"),
        }

    region_palettes: dict[str, dict[str, float]] = {}
    for region_name in ("head", "body", "tail", "dorsal", "anal"):
        rmask = regions.get(f"{region_name}_mask")
        if rmask is not None and rmask.sum() >= MIN_REGION_PIXELS:
            pal = _palette_for_mask(rgb_u8, rmask, k_clusters=4)
            if pal:
                region_palettes[region_name] = pal

    merged = _merge_region_palettes(region_palettes)

    if not merged:
        merged = _palette_for_mask(rgb_u8, mask, k_clusters=k_clusters)
        merged = {k: v for k, v in merged.items() if v >= 3.0}
        merged = _suppress_silver_noise(merged)
        merged = dict(sorted(merged.items(), key=lambda x: -x[1]))

    keys = list(merged.keys())
    primary = keys[0] if keys else None
    secondary = keys[1] if len(keys) > 1 else None
    pattern = _classify_pattern(merged)

    iri_level, iri_score = _detect_iridescence(hsv, mask)
    quality = _score_quality(img, mask, hsv)

    side_label = posture.get("side_label", "?")
    regions_used = len(region_palettes)
    region_confidence = round(min(1.0, regions_used / 5.0), 2)

    return {
        "ok": True,
        "palette": merged,
        "primary": primary,
        "secondary": secondary,
        "pattern_hint": pattern,
        "iridescence_level": iri_level,
        "iridescence_score": iri_score,
        "quality": quality,
        "coverage_pct": round(coverage_pct, 1),
        "posture": posture,
        "regions_used": list(region_palettes.keys()),
        "region_palettes": region_palettes,
        "region_confidence": region_confidence,
        "side_label": side_label,
        "pass": pass_num,
        "debug": {
            "water_tint_detected": water_tint is not None,
            "adaptive_bg_detected": bg_color is not None,
        },
    }


# ============================================================
# REGION ANALYSIS (tap-to-select)
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

    analysis = analyze_photo(cropped_bytes, k_clusters=k_clusters,
                             use_blob=False, skip_posture=True)
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
# VIDEO
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


# ============================================================
# VIDEO: PASS 2 REGIONAL FALLBACK
# ============================================================

def _frame_regions_clean(regions: dict, shape: tuple[int, int]) -> dict[str, np.ndarray]:
    clean: dict[str, np.ndarray] = {}
    H, W = shape
    b = EDGE_MARGIN_PX

    for name in ("head", "body", "tail", "dorsal", "anal"):
        rmask = regions.get(f"{name}_mask")
        if rmask is None:
            continue
        if rmask.sum() < MIN_REGION_PIXELS:
            continue
        ys, xs = np.where(rmask)
        if len(xs) == 0:
            continue
        if (xs.min() <= b or ys.min() <= b
                or xs.max() >= W - 1 - b or ys.max() >= H - 1 - b):
            continue
        if name in ("dorsal", "anal", "tail") and rmask.sum() < 40:
            continue
        clean[name] = rmask
    return clean


def analyze_video(
    video_bytes: bytes,
    sample_every: int = 5,
    max_frames: int = 30,
    k_clusters: int = 5,
) -> dict:
    """
    Two-pass video pipeline.

    Pass 1 (strict): keep only frames where posture pass == 1.
    If >= MIN_STRICT_FRAMES and same-side majority → mode="strict".

    Pass 2 (regional fallback): per-frame region-only analysis.
    Merge per-region across frames → mode="regional".

    Else reject.
    """
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

    # ---------- PASS 1 ----------
    strict_analyses = []
    strict_indices = []

    for fi, fbytes in enumerate(frames):
        try:
            a = analyze_photo(fbytes, k_clusters=k_clusters, use_blob=True)
            if not a or not a.get("ok"):
                continue
            if a.get("pass", 3) != 1:
                continue
            strict_analyses.append(a)
            strict_indices.append(fi)
        except Exception:
            continue

    if len(strict_analyses) >= MIN_STRICT_FRAMES:
        sides = [a.get("side_label", "?") for a in strict_analyses]
        a_count = sides.count("A")
        b_count = sides.count("B")
        if a_count >= b_count:
            majority = "A"
        else:
            majority = "B"

        kept = [a for a in strict_analyses if a.get("side_label") == majority]
        if len(kept) >= MIN_STRICT_FRAMES:
            consensus = merge_analyses(kept)
            best_idx = max(
                range(len(kept)),
                key=lambda i: (kept[i].get("quality", {}) or {}).get("score", 0),
            )
            best_frame_idx = strict_indices[best_idx]
            best_frame_bytes = frames[best_frame_idx]

            return {
                "ok": True,
                "mode": "strict",
                "frames_analyzed": len(kept),
                "analyses": kept,
                "consensus": consensus,
                "best_frame_idx": best_frame_idx,
                "best_frame_bytes": best_frame_bytes,
                "side_a_count": sum(1 for a in kept if a.get("side_label") == "A"),
                "side_b_count": sum(1 for a in kept if a.get("side_label") == "B"),
                "majority_side": majority,
                "discarded_minority_frames": len(strict_analyses) - len(kept),
            }

    # ---------- PASS 2: regional fallback ----------
    regional_contributors = 0
    region_samples: dict[str, list[dict[str, float]]] = {
        "head": [], "body": [], "tail": [], "dorsal": [], "anal": []
    }

    for fi, fbytes in enumerate(frames):
        try:
            img = _load_image_rgb(fbytes)
            if img is None:
                continue
            img.thumbnail((640, 640), Image.LANCZOS)

            rgb = np.asarray(img).astype(np.float32)
            rgb = _normalize_white_balance(rgb)
            rgb_u8 = np.clip(rgb, 0, 255).astype(np.uint8)
            hsv = _rgb_to_hsv_numpy(rgb_u8)

            water_tint = _detect_water_tint(hsv)
            bg_color = _detect_background_color_cluster(rgb_u8)

            mask = _mask_fish_region(hsv, rgb_u8,
                                     water_tint=water_tint, bg_color=bg_color)
            if mask.sum() < 50:
                continue
            mask = _isolate_largest_blob(mask, rgb_u8, min_size_pct=0.5)
            if mask.sum() < 50:
                continue

            coverage_pct = float(mask.sum() / mask.size * 100)
            if coverage_pct < MIN_COVERAGE_PCT:
                continue

            orientation_full = _compute_orientation(mask)
            aspect = orientation_full.get("aspect", 0)
            if aspect < 1.0:
                continue

            body_ratio = _compute_body_ratio(mask, orientation_full)
            if body_ratio < MIN_BODY_RATIO_PARTIAL:
                continue

            regions = _split_blob_into_regions(mask, orientation=orientation_full)
            if not regions:
                continue

            clean = _frame_regions_clean(regions, mask.shape)
            if not clean:
                continue

            contributed = False
            for name, rmask in clean.items():
                pal = _palette_for_mask(rgb_u8, rmask, k_clusters=4)
                if pal:
                    region_samples[name].append(pal)
                    contributed = True

            if contributed:
                regional_contributors += 1
        except Exception:
            continue

    merged_region_palettes: dict[str, dict[str, float]] = {}
    for name, samples in region_samples.items():
        if not samples:
            continue
        keys = set()
        for s in samples:
            keys.update(s.keys())
        avg: dict[str, float] = {}
        for k in keys:
            avg[k] = round(sum(s.get(k, 0.0) for s in samples) / len(samples), 1)
        avg = {k: v for k, v in avg.items() if v >= 3.0}
        if avg:
            merged_region_palettes[name] = avg

    if regional_contributors >= MIN_PARTIAL_REGION_FRAMES and merged_region_palettes:
        merged = _merge_region_palettes(merged_region_palettes)
        pattern = _classify_pattern(merged)
        keys = list(merged.keys())
        primary = keys[0] if keys else None
        secondary = keys[1] if len(keys) > 1 else None

        return {
            "ok": True,
            "mode": "regional",
            "frames_analyzed": regional_contributors,
            "region_samples": {k: len(v) for k, v in region_samples.items()},
            "merged_region_palettes": merged_region_palettes,
            "consensus": {
                "ok": True,
                "palette": merged,
                "primary": primary,
                "secondary": secondary,
                "pattern_hint": pattern,
                "shot_count": regional_contributors,
            },
            "best_frame_idx": 0,
            "best_frame_bytes": frames[0] if frames else None,
            "side_a_count": 0,
            "side_b_count": 0,
        }

    # ---------- BOTH FAILED ----------
    return {
        "ok": False,
        "error": (
            "Could not find a clear side view. "
            "Try again with fish side-on and fins flared."
        ),
        "strict_frames_found": len(strict_analyses),
        "regional_contributors": regional_contributors,
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
    pattern = _classify_pattern(merged)

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

    region_confs = [a.get("region_confidence", 0) for a in valid]
    avg_region_conf = round(sum(region_confs) / len(region_confs), 2) if region_confs else 0.0

    sides_seen = sorted(set(a.get("side_label", "?") for a in valid))

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
        "region_confidence": avg_region_conf,
        "sides_seen": sides_seen,
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
