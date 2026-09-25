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
#   • IBC body ratio uses interquartile depth (excludes fin tips)
#   • Candidate picker: split merged blob, pick best IBC side view
#     (real fish wins because reflection is typically partial/broken)
#   • Regions aligned to HMPK anatomy: head 20% / body 45% / tail 35%
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
# POSTURE VALIDATION CONSTANTS
# ============================================================

MIN_ASPECT_RATIO = 1.05
MIN_BODY_RATIO_SIDE = 2.0
MIN_BODY_RATIO_PARTIAL = 1.6
MIN_COVERAGE_PCT = 1.0

MAX_SOLIDITY_FLARED = 0.92
MIN_FLARE_PIXELS = 100
MIN_TAIL_SPREAD_RATIO = 1.1

HEAD_REGION_FRAC = 0.20
BODY_REGION_FRAC = 0.45
TAIL_REGION_FRAC = 0.35

REGION_WEIGHTS = {
    "head":   0.15,
    "body":   0.35,
    "tail":   0.20,
    "dorsal": 0.15,
    "anal":   0.15,
}

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
# BLOB QUALITY
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
# BODY RATIO (IQR-based)
# ============================================================

def _compute_body_ratio(blob_mask: np.ndarray, orientation: dict) -> float:
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

        body_major = proj_major[body_band]
        body_minor = proj_minor[body_band]

        body_length = float(body_major.max() - body_major.min())

        p25 = float(np.percentile(body_minor, 25))
        p75 = float(np.percentile(body_minor, 75))
        body_depth = p75 - p25

        if body_depth < 1.0:
            return 0.0

        return body_length / body_depth
    except Exception:
        return 0.0


# ============================================================
# FLARE DETECTION
# ============================================================

def _detect_flare(blob_mask: np.ndarray, orientation: dict) -> dict:
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
# POSTURE VALIDATION
# ============================================================

def validate_fish_posture(blob_mask: np.ndarray, rgb: np.ndarray,
                           coverage_pct: float) -> dict:
    orientation = _compute_orientation(blob_mask)
    flare = _detect_flare(blob_mask, orientation)
    completeness = _check_completeness(blob_mask, orientation)

    aspect = orientation.get("aspect", 0)
    aspect_ok = aspect >= MIN_ASPECT_RATIO

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

    if (coverage_ok and is_side_profile and is_flared and flare_conf >= 0.5
            and (is_complete or is_partial_ok)):
        base["pass"] = 1
        base["reason"] = "Strict pass — side profile + flared"
        return base

    if (coverage_ok and aspect >= 1.0 and body_ratio >= MIN_BODY_RATIO_PARTIAL
            and is_partial_ok):
        base["pass"] = 2
        base["reason"] = (
            "Regional pass — "
            + ("flared" if is_flared else "possibly clamped")
        )
        return base

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
# CANDIDATE SPLIT + PICK (Session 26E, best-IBC-view)
# ============================================================

def _split_into_candidates(blob_mask: np.ndarray,
                            rgb_u8: np.ndarray) -> list[np.ndarray]:
    """
    Return a list of candidate fish masks from the blob.

    If the blob is roughly square (aspect < 1.25), it likely contains
    two fish (real + reflection). Split at the min-density column in
    the middle 30% and return [left, right]. Otherwise return [blob].
    """
    try:
        if blob_mask.sum() < 200:
            return [blob_mask]

        ys, xs = np.where(blob_mask)
        if len(xs) < 200:
            return [blob_mask]

        x_min = int(xs.min())
        x_max = int(xs.max())
        y_min = int(ys.min())
        y_max = int(ys.max())
        width = x_max - x_min + 1
        height = y_max - y_min + 1

        if width < 40 or height < 40:
            return [blob_mask]

        bbox_aspect = max(width, height) / max(1, min(width, height))
        if bbox_aspect >= 1.25:
            return [blob_mask]

        col_counts = np.bincount(xs - x_min, minlength=width)
        lo = int(width * 0.35)
        hi = int(width * 0.65)
        if hi - lo < 5:
            return [blob_mask]

        mid_band = col_counts[lo:hi]
        min_col_offset = int(np.argmin(mid_band))
        split_x = x_min + lo + min_col_offset

        left_mask = blob_mask.copy()
        left_mask[:, split_x:] = False
        right_mask = blob_mask.copy()
        right_mask[:, :split_x] = False

        left_px = int(left_mask.sum())
        right_px = int(right_mask.sum())

        if left_px < 200 or right_px < 200:
            return [blob_mask]

        min_frac = 0.25
        total_px = left_px + right_px
        if (left_px / total_px) < min_frac or (right_px / total_px) < min_frac:
            return [blob_mask]

        return [left_mask, right_mask]
    except Exception:
        return [blob_mask]


def _score_candidate(mask: np.ndarray, rgb_u8: np.ndarray) -> dict:
    """
    Score a candidate fish mask against IBC side-view criteria.

    Returns dict with all check results + a single composite score.
    """
    coverage_pct = float(mask.sum() / mask.size * 100)

    orientation = _compute_orientation(mask)
    flare = _detect_flare(mask, orientation)
    completeness = _check_completeness(mask, orientation)

    aspect = orientation.get("aspect", 0)
    aspect_ok = aspect >= MIN_ASPECT_RATIO

    body_ratio = _compute_body_ratio(mask, orientation)
    body_ratio_ok = body_ratio >= MIN_BODY_RATIO_SIDE

    is_complete = completeness.get("complete", False)
    is_partial_ok = completeness.get("partial_ok", False)
    is_flared = flare.get("is_flared", False)
    flare_conf = flare.get("confidence", 0.0)

    coverage_ok = coverage_pct >= MIN_COVERAGE_PCT

    if (coverage_ok and aspect_ok and body_ratio_ok and is_flared
            and flare_conf >= 0.5 and (is_complete or is_partial_ok)):
        pass_level = 1
    elif (coverage_ok and aspect >= 1.0 and body_ratio >= MIN_BODY_RATIO_PARTIAL
            and is_partial_ok):
        pass_level = 2
    else:
        pass_level = 3

    return {
        "mask": mask,
        "coverage_pct": round(coverage_pct, 2),
        "aspect": aspect,
        "body_ratio": round(body_ratio, 2),
        "flared": is_flared,
        "flare_conf": flare_conf,
        "complete": is_complete,
        "partial_ok": is_partial_ok,
        "pass": pass_level,
        "orientation": orientation,
        "flare": flare,
        "completeness": completeness,
        "head_direction": orientation.get("head_direction", "unknown"),
    }


def _pick_best_candidate(candidates: list[np.ndarray],
                          rgb_u8: np.ndarray) -> Optional[dict]:
    """
    Evaluate each candidate and return the one with the best IBC
    side-view score.

    Priority:
      1. Lowest pass level (1 = strict, 2 = regional, 3 = reject)
      2. Highest body_ratio
      3. Largest coverage
    """
    if not candidates:
        return None

    scored = [_score_candidate(m, rgb_u8) for m in candidates]
    scored.sort(key=lambda s: (s["pass"], -s["body_ratio"], -s["coverage_pct"]))
    return scored[0]


def _isolate_largest_blob(mask: np.ndarray, rgb: np.ndarray,
                            min_size_pct: float = 0.5) -> np.ndarray:
    if not _SCIPY_AVAILABLE or mask.sum() == 0:
        return mask

    try:
        labeled, num = _ndimage.label(mask)
        if num
