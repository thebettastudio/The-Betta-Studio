# modules/ai_frame_judge.py
# Betta Farm Management System
# Session 26F — Gemini AI frame judge.
# Session 26G — 15 frames, best-frame + crop box, retry with backoff.
# Session 26H — Reference silhouettes + match_score + flare_score +
#                posture_class + real_fish_bbox per frame.
#
# Sends:
#   1. Reference silhouettes (4 HMPK variants) — "this is ideal HMPK"
#   2. Candidate frames — "score each against the references"
#
# Returns per frame:
#   {
#     frame_index, match_score, flare_score, matched_reference,
#     posture_class, head_direction, bbox, deviations,
#     confidence, reason
#   }
# Plus best frame + crop.

from __future__ import annotations

import io
import json
import time
from typing import Optional

import streamlit as st

try:
    from google import genai
    from google.genai import types
    _GENAI_AVAILABLE = True
except ImportError:
    _GENAI_AVAILABLE = False


# ============================================================
# CONFIG
# ============================================================

GEMINI_MODEL_FALLBACKS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
]
GEMINI_MODEL = GEMINI_MODEL_FALLBACKS[0]

MAX_FRAMES_TO_JUDGE = 15

MAX_RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = [5, 15]


# Posture class priority (higher = better) — used by caller
POSTURE_CLASS_RANK = {
    "fully_flared": 5,
    "mostly_flared": 4,
    "partially_flared": 3,
    "clamped": 2,
    "unusable": 1,
}


# ============================================================
# PROMPT
# ============================================================

JUDGE_PROMPT = """You are analyzing frames from a video of a betta fish (HMPK / Halfmoon Plakat variant).

You will receive REFERENCE SILHOUETTES first, then candidate frames.

The reference silhouettes show what an ideal HMPK side view looks like:
- Traditional Show Plakat
- Symmetrical Show Plakat
- Asymmetrical Show Plakat
- Pet-grade baseline (relaxed pose)

These are the archetypes. Real fish may not match perfectly — that is
expected. Your job is to score how close each frame is.

For EACH candidate frame, evaluate:

1. match_score (float 0..1) — how closely does this frame's fish silhouette
   match ANY of the reference silhouettes?
   1.0 = essentially perfect match to a reference anatomy
   0.7-0.9 = very good, minor deviations
   0.5-0.7 = recognizable HMPK but noticeable deviations
   0.3-0.5 = only loosely resembles the reference anatomy
   <0.3 = does not look like an HMPK side view

2. flare_score (float 0..1) — how flared/open are the fins?
   1.0 = fully flared, maximum spread
   0.7-0.9 = well flared
   0.4-0.7 = partially flared
   0.2-0.4 = mostly clamped
   <0.2 = fully clamped / fins tight against body

3. matched_reference (string) — which reference matches best:
   "hmpk_traditional_show" | "hmpk_symmetrical_show" |
   "hmpk_asymmetrical_show" | "hmpk_pet_grade" | "none"

4. posture_class (string) — one of:
   "fully_flared" | "mostly_flared" | "partially_flared" |
   "clamped" | "unusable"
   NOTE: "unusable" only if the fish is head-on/top-down, or only a
   mirror reflection is visible, or the fish is not identifiable.

5. head_direction (string) — "left" | "right" | "up" | "down" | "unknown"

6. bbox (object) — tight bounding box around the REAL fish ONLY,
   excluding any mirror reflection. Use normalized 0..1 coords:
   {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
   (x,y = top-left corner; w,h = width,height as fractions)

7. deviations (list of strings) — specific visual differences from
   the matched reference. Example:
   ["dorsal fin base narrower than ideal",
    "caudal spread approximately 170 degrees"]

8. confidence (float 0..1) — your confidence in the assessment

9. reason (string) — one short sentence summarizing the frame

RULES:
- Do NOT reject a frame just because fins are clamped — set flare_score
  and posture_class accordingly.
- If the fish is in profile but relaxed, still score it.
- Only mark "unusable" if the frame truly cannot be analyzed.
- Prefer the frame with highest (flare_score, match_score) for "best".
- If only a mirror reflection is visible (no real fish), mark as unusable.

Return ONLY JSON. No prose. No markdown fences:

{
  "frames": [
    {
      "frame_index": 0,
      "match_score": 0.85,
      "flare_score": 0.90,
      "matched_reference": "hmpk_symmetrical_show",
      "posture_class": "fully_flared",
      "head_direction": "left",
      "bbox": {"x": 0.10, "y": 0.20, "w": 0.70, "h": 0.60},
      "deviations": ["dorsal fin base slightly narrow"],
      "confidence": 0.85,
      "reason": "Clean side profile with good flare"
    }
  ],
  "best": {
    "frame_index": 0,
    "bbox": {"x": 0.10, "y": 0.20, "w": 0.70, "h": 0.60},
    "reason": "Highest flare + match score"
  }
}
"""


# ============================================================
# API CLIENT
# ============================================================

def _get_client():
    if not _GENAI_AVAILABLE:
        return None
    try:
        api_key = st.secrets.get("GOOGLE_API_KEY", None)
    except Exception:
        api_key = None
    if not api_key:
        return None
    try:
        return genai.Client(api_key=api_key)
    except Exception:
        return None


def is_ai_available() -> bool:
    return _get_client() is not None


def get_diagnostic() -> dict:
    import streamlit as _st
    diag = {
        "genai_sdk_available": _GENAI_AVAILABLE,
        "secret_found": False,
        "secret_length": 0,
        "error": None,
    }
    try:
        key = _st.secrets.get("GOOGLE_API_KEY", None)
        if key:
            diag["secret_found"] = True
            diag["secret_length"] = len(str(key))
    except Exception as e:
        diag["error"] = str(e)
    return diag


# ============================================================
# MAIN ENTRY
# ============================================================

def judge_frames(frames_bytes: list[bytes],
                  frame_indices: Optional[list[int]] = None) -> Optional[dict]:
    """
    Send reference silhouettes + frames to Gemini.
    Returns {"frames": [...], "best": {...}, "reference_used": [...]}.
    """
    client = _get_client()
    if client is None or not frames_bytes:
        return None

    if frame_indices is None:
        frame_indices = list(range(len(frames_bytes)))

    # Cap
    if len(frames_bytes) > MAX_FRAMES_TO_JUDGE:
        step = len(frames_bytes) / MAX_FRAMES_TO_JUDGE
        keep = [int(i * step) for i in range(MAX_FRAMES_TO_JUDGE)]
        frames_bytes = [frames_bytes[i] for i in keep]
        frame_indices = [frame_indices[i] for i in keep]

    # Load references
    try:
        from modules.reference_shapes import load_reference_images
        refs = load_reference_images()
    except Exception:
        refs = []

    # Build contents
    contents: list = [JUDGE_PROMPT]

    if refs:
        contents.append("=== REFERENCE SILHOUETTES ===")
        for ref in refs:
            contents.append(f"Reference: {ref['name']}")
            try:
                contents.append(
                    types.Part.from_bytes(data=ref["bytes"],
                                            mime_type=ref["mime_type"])
                )
            except Exception:
                contents.append(
                    types.Part.from_data(data=ref["bytes"],
                                           mime_type=ref["mime_type"])
                )
    else:
        contents.append("(No reference images available. Use your knowledge of HMPK anatomy.)")

    contents.append("=== CANDIDATE FRAMES ===")
    for orig_idx, fb in zip(frame_indices, frames_bytes):
        contents.append(f"Frame index {orig_idx}:")
        try:
            contents.append(
                types.Part.from_bytes(data=fb, mime_type="image/jpeg")
            )
        except Exception:
            contents.append(
                types.Part.from_data(data=fb, mime_type="image/jpeg")
            )

    # Call with retry
    response = None
    last_error = None

    for attempt in range(MAX_RETRY_ATTEMPTS):
        model_to_try = GEMINI_MODEL_FALLBACKS[
            min(attempt, len(GEMINI_MODEL_FALLBACKS) - 1)
        ]
        try:
            response = client.models.generate_content(
                model=model_to_try,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                    max_output_tokens=8192,
                ),
            )
            break
        except Exception as e:
            last_error = e
            err_str = str(e)
            transient = any(code in err_str for code in [
                "503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED",
                "500", "INTERNAL", "DEADLINE_EXCEEDED", "TIMEOUT",
            ])
            if transient and attempt < MAX_RETRY_ATTEMPTS - 1:
                wait = RETRY_BACKOFF_SECONDS[
                    min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)
                ]
                next_model = GEMINI_MODEL_FALLBACKS[
                    min(attempt + 1, len(GEMINI_MODEL_FALLBACKS) - 1)
                ]
                st.info(
                    f"⏳ Gemini busy (attempt {attempt + 1}/{MAX_RETRY_ATTEMPTS}). "
                    f"Trying {next_model} in {wait}s…"
                )
                time.sleep(wait)
                continue
            st.warning(
                f"Gemini API call failed after {attempt + 1} attempt(s): "
                f"{last_error}"
            )
            return None

    if response is None:
        st.warning(f"Gemini API gave no response: {last_error}")
        return None

    raw_text = getattr(response, "text", None) or ""
    if not raw_text.strip():
        return None

    parsed = _parse_json_response(raw_text)
    if parsed is None:
        return None

    if isinstance(parsed, list):
        frames_raw = parsed
        best_raw = None
    elif isinstance(parsed, dict):
        frames_raw = parsed.get("frames", [])
        best_raw = parsed.get("best", None)
    else:
        return None

    # Normalize frames
    normalized_frames = []
    for entry in frames_raw:
        if not isinstance(entry, dict):
            continue
        bbox_raw = entry.get("bbox", {}) or {}
        bbox = _normalize_bbox(bbox_raw)
        normalized_frames.append({
            "frame_index": int(entry.get("frame_index", -1)),
            "match_score": float(entry.get("match_score", 0.0)),
            "flare_score": float(entry.get("flare_score", 0.0)),
            "matched_reference": str(entry.get("matched_reference", "none")).lower(),
            "posture_class": str(entry.get("posture_class", "unusable")).lower(),
            "head_direction": str(entry.get("head_direction", "unknown")).lower(),
            "bbox": bbox,
            "deviations": list(entry.get("deviations", []) or [])[:8],
            "confidence": float(entry.get("confidence", 0.5)),
            "reason": str(entry.get("reason", ""))[:250],
        })

    # Normalize best
    normalized_best = None
    if best_raw and isinstance(best_raw, dict):
        bbox_raw = best_raw.get("bbox", {}) or best_raw.get("crop_box", {}) or {}
        bbox = _normalize_bbox(bbox_raw)
        if bbox:
            normalized_best = {
                "frame_index": int(best_raw.get("frame_index", -1)),
                "bbox": bbox,
                "crop_box": bbox,   # alias for backward compat
                "reason": str(best_raw.get("reason", ""))[:250],
            }

    return {
        "frames": normalized_frames,
        "best": normalized_best,
        "reference_used": [r["name"] for r in refs],
    }


def _normalize_bbox(raw: dict) -> Optional[dict]:
    """Validate and clamp a bbox dict {x,y,w,h} 0..1."""
    try:
        x = float(raw.get("x", 0.0))
        y = float(raw.get("y", 0.0))
        w = float(raw.get("width", raw.get("w", 0.0)))
        h = float(raw.get("height", raw.get("h", 0.0)))
        # Clamp
        x = max(0.0, min(1.0, x))
        y = max(0.0, min(1.0, y))
        w = max(0.02, min(1.0 - x, w))
        h = max(0.02, min(1.0 - y, h))
        if w < 0.05 or h < 0.05:
            return None
        return {"x": x, "y": y, "w": w, "h": h}
    except Exception:
        return None


def _parse_json_response(text: str):
    t = text.strip()
    if t.startswith("```"):
        first_nl = t.find("\n")
        if first_nl != -1:
            t = t[first_nl + 1:]
        if t.endswith("```"):
            t = t[:-3].rstrip()

    try:
        return json.loads(t)
    except Exception:
        pass

    if "{" in t and "}" in t:
        start = t.find("{")
        end = t.rfind("}")
        if end > start:
            try:
                return json.loads(t[start:end + 1])
            except Exception:
                pass

    if "[" in t and "]" in t:
        start = t.find("[")
        end = t.rfind("]")
        if end > start:
            try:
                return json.loads(t[start:end + 1])
            except Exception:
                pass

    return None


# ============================================================
# HELPERS
# ============================================================

def bbox_to_mask(shape: tuple[int, int], bbox: dict,
                  pad: float = 0.08) -> Optional["np.ndarray"]:
    """
    Convert a normalized bbox {x,y,w,h} to a bool mask of the given
    (H, W) shape. Adds padding (fraction of bbox size) as safety margin.
    """
    try:
        import numpy as np
        H, W = shape
        x = max(0.0, bbox["x"] - bbox["w"] * pad)
        y = max(0.0, bbox["y"] - bbox["h"] * pad)
        w = min(1.0 - x, bbox["w"] * (1 + 2 * pad))
        h = min(1.0 - y, bbox["h"] * (1 + 2 * pad))

        px0 = int(x * W)
        py0 = int(y * H)
        px1 = int((x + w) * W)
        py1 = int((y + h) * H)

        mask = np.zeros((H, W), dtype=bool)
        mask[max(0, py0):min(H, py1), max(0, px0):min(W, px1)] = True
        return mask
    except Exception:
        return None


def crop_frame_to_bbox(frames_bytes: list[bytes], best: dict) -> Optional[bytes]:
    """Crop the best frame using its bbox. Returns JPEG bytes."""
    if not best or not frames_bytes:
        return None
    idx = best.get("frame_index", -1)
    if idx < 0 or idx >= len(frames_bytes):
        return None

    bbox = best.get("bbox") or best.get("crop_box")
    if not bbox:
        return frames_bytes[idx]

    try:
        from PIL import Image
        img = Image.open(io.BytesIO(frames_bytes[idx]))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        W, H = img.size

        x = int(round(bbox["x"] * W))
        y = int(round(bbox["y"] * H))
        w = int(round(bbox["w"] * W))
        h = int(round(bbox["h"] * H))

        x = max(0, min(x, W - 1))
        y = max(0, min(y, H - 1))
        w = max(10, min(w, W - x))
        h = max(10, min(h, H - y))

        cropped = img.crop((x, y, x + w, y + h))
        buf = io.BytesIO()
        cropped.save(buf, format="JPEG", quality=90)
        return buf.getvalue()
    except Exception:
        return None


# Backward-compat alias
crop_frame = crop_frame_to_bbox
