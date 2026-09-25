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
# Session 26F — Gemini AI frame judge integration.
#   • If GOOGLE_API_KEY is set, AI judges frames before classical pipeline.
#   • AI provides head_direction + pass/fail per frame.
#   • Classical pipeline still does color science on AI-approved frames.
#   • Fallback to classical pipeline if AI unavailable or errors.

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
MIN_BODY_RATIO_SIDE = 1.8
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
# TRACKING CONSTANTS
# ============================================================

MOTION_DIFF_THRESHOLD = 30
MIN_TRACK_BLOB_AREA = 150
TRACK_MAX_JUMP_PX = 250
TRACK_BBOX_PAD = 1.6


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
# MOTION TRACKING
# ============================================================

def _per_frame_motion_blobs(frames_rgb: list[np.ndarray]) -> list[list[dict]]:
    n = len(frames_rgb)
    blobs_per_frame: list[list[dict]] = [[] for _ in range(n)]

    if n < 2 or not _SCIPY_AVAILABLE:
        return blobs_per_frame

    H, W = frames_rgb[0].shape[:2]

    for t in range(1, n):
        prev = frames_rgb[t - 1].astype(np.int16)
        curr = frames_rgb[t].astype(np.int16)
        if curr.shape[:2] != (H, W) or prev.shape[:2] != (H, W):
            continue

        diff = np.abs(curr - prev).mean(axis=-1)
        motion_mask = diff > MOTION_DIFF_THRESHOLD

        try:
            motion_mask = _ndimage.binary_dilation(motion_mask, iterations=2)
        except Exception:
            pass

        labeled, num = _ndimage.label(motion_mask)
        if num == 0:
            continue

        blobs: list[dict] = []
        for comp_id in range(1, num + 1):
            ys, xs = np.where(labeled == comp_id)
            area = len(xs)
            if area < MIN_TRACK_BLOB_AREA:
                continue
            cx = float(xs.mean())
            cy = float(ys.mean())
            bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
            blobs.append({"centroid": (cx, cy), "bbox": bbox, "area": area})

        blobs_per_frame[t].extend(blobs)
        blobs_per_frame[t - 1].extend(blobs)

    for t in range(n):
        seen = []
        unique = []
        for b in blobs_per_frame[t]:
            key = (round(b["centroid"][0]), round(b["centroid"][1]), b["area"])
            if key in seen:
                continue
            seen.append(key)
            unique.append(b)
        blobs_per_frame[t] = unique

    return blobs_per_frame


def _is_fish_shaped(b: dict) -> bool:
    x0, y0, x1, y1 = b["bbox"]
    w = x1 - x0 + 1
    h = y1 - y0 + 1
    if w < 20 or h < 20:
        return False
    aspect = max(w, h) / max(1, min(w, h))
    if aspect < 1.15:
        return False
    return True


def _track_largest_blob(blobs_per_frame: list[list[dict]]) -> list[Optional[dict]]:
    n = len(blobs_per_frame)
    track: list[Optional[dict]] = [None] * n

    if n == 0:
        return track

    seed_frame = None
    seed_blob = None
    for t in range(min(n, max(1, n // 3))):
        if not blobs_per_frame[t]:
            continue
        candidates = [b for b in blobs_per_frame[t] if _is_fish_shaped(b)]
        if not candidates:
            continue
        biggest = max(candidates, key=lambda b: b["area"])
        if seed_blob is None or biggest["area"] > seed_blob["area"]:
            seed_blob = biggest
            seed_frame = t

    if seed_blob is None:
        return track

    track[seed_frame] = seed_blob

    prev_centroid = seed_blob["centroid"]
    for t in range(seed_frame + 1, n):
        candidates = [b for b in blobs_per_frame[t] if _is_fish_shaped(b)]
        if not candidates:
            continue
        def score(b):
            dx = b["centroid"][0] - prev_centroid[0]
            dy = b["centroid"][1] - prev_centroid[1]
            return (math.hypot(dx, dy), -b["area"])
        best = min(candidates, key=score)
        dist = math.hypot(best["centroid"][0] - prev_centroid[0],
                            best["centroid"][1] - prev_centroid[1])
        if dist > TRACK_MAX_JUMP_PX:
            continue
        track[t] = best
        prev_centroid = best["centroid"]

    prev_centroid = seed_blob["centroid"]
    for t in range(seed_frame - 1, -1, -1):
        candidates = [b for b in blobs_per_frame[t] if _is_fish_shaped(b)]
        if not candidates:
            continue
        def score_b(b):
            dx = b["centroid"][0] - prev_centroid[0]
            dy = b["centroid"][1] - prev_centroid[1]
            return (math.hypot(dx, dy), -b["area"])
        best = min(candidates, key=score_b)
        dist = math.hypot(best["centroid"][0] - prev_centroid[0],
                            best["centroid"][1] - prev_centroid[1])
        if dist > TRACK_MAX_JUMP_PX:
            continue
        track[t] = best
        prev_centroid = best["centroid"]

    known = [i for i, b in enumerate(track) if b is not None]
    for a, b in zip(known[:-1], known[1:]):
        if b - a <= 1 or b - a > 6:
            continue
        for k in range(a + 1, b):
            alpha = (k - a) / (b - a)
            cxa, cya = track[a]["centroid"]
            cxb, cyb = track[b]["centroid"]
            track[k] = {
                "centroid": (cxa + alpha * (cxb - cxa), cya + alpha * (cyb - cya)),
                "bbox": track[a]["bbox"],
                "area": int((track[a]["area"] + track[b]["area"]) / 2),
            }

    return track


def _build_trajectory_mask(shape: tuple[int, int],
                             track: list[Optional[dict]],
                             frame_idx: int,
                             pad: float = TRACK_BBOX_PAD) -> Optional[np.ndarray]:
    if frame_idx < 0 or frame_idx >= len(track):
        return None
    blob = track[frame_idx]
    if blob is None:
        return None

    H, W = shape
    x0, y0, x1, y1 = blob["bbox"]
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0
    w = (x1 - x0) * pad / 2.0
    h = (y1 - y0) * pad / 2.0

    mask = np.zeros((H, W), dtype=bool)
    rx0 = max(0, int(cx - w))
    ry0 = max(0, int(cy - h))
    rx1 = min(W, int(cx + w))
    ry1 = min(H, int(cy + h))
    if rx1 <= rx0 or ry1 <= ry0:
        return None
    mask[ry0:ry1, rx0:rx1] = True
    return mask


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
# ORIENTATION (PCA)
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
# BODY RATIO
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
        if blob_mask.sum
