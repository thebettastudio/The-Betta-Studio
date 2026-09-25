# modules/ai_frame_judge.py
# Betta Farm Management System
# Session 26H — Gemini AI frame judge with reference silhouettes,
# match_score, flare_score, posture_class, real_fish_bbox.
<<<<<<< HEAD
# Session 26H.3 — Sharper prompt: one-eye = side view rule, bbox required.
=======
>>>>>>> 9711565 (Session 26H.3 — sharper prompt + classical bbox fallback)
#
# Sends 4 reference silhouettes + up to 15 candidate frames to Gemini.
# Returns {"frames": [...], "best": {...}}.

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


GEMINI_MODEL_FALLBACKS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
]
GEMINI_MODEL = GEMINI_MODEL_FALLBACKS[0]

MAX_FRAMES_TO_JUDGE = 15
MAX_RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = [5, 15]

POSTURE_CLASS_RANK = {
    "fully_flared": 5,
    "mostly_flared": 4,
    "partially_flared": 3,
    "clamped": 2,
    "unusable": 1,
}


JUDGE_PROMPT = """You are analyzing frames from a video of a betta fish (HMPK variant).

You will receive REFERENCE SILHOUETTES first, then candidate frames.

The reference silhouettes show what an ideal HMPK side view looks like:
- Traditional Show Plakat
- Symmetrical Show Plakat
- Asymmetrical Show Plakat
- Pet-grade baseline

<<<<<<< HEAD
=== CRITICAL RULE: SIDE VIEW IS MANDATORY ===

Look at the fish's EYES to determine orientation:

- ONE EYE VISIBLE + body extends LEFT or RIGHT = SIDE VIEW (valid)
- BOTH EYES VISIBLE + face pointing at camera = HEAD-ON (unusable)
- Fish body vertical (up or down) = NOT a side view (unusable)
- Only reflection visible (no real fish) = UNUSABLE

If the frame is NOT a clean side view, you MUST set posture_class = "unusable",
REGARDLESS of how flared the fins look. Fin flare alone does not make a side view.

=== For EACH candidate frame, evaluate: ===
=======
For EACH candidate frame, evaluate:
>>>>>>> 9711565 (Session 26H.3 — sharper prompt + classical bbox fallback)

1. match_score (0..1) — how closely does this frame's fish silhouette match ANY reference?
2. flare_score (0..1) — how flared are the fins?
3. matched_reference (string) — "hmpk_traditional_show" | "hmpk_symmetrical_show" | "hmpk_asymmetrical_show" | "hmpk_pet_grade" | "none"
4. posture_class (string) — "fully_flared" | "mostly_flared" | "partially_flared" | "clamped" | "unusable"
5. head_direction (string) — "left" | "right" | "up" | "down" | "unknown"
<<<<<<< HEAD
6. bbox (object) — REQUIRED. Tight box around the REAL fish (not reflection),
   normalized 0..1: {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
   If you cannot determine the box, use {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8}.
   NEVER omit this field.
=======
6. bbox (object) — tight box around the REAL fish (not reflection), normalized 0..1:
   {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
>>>>>>> 9711565 (Session 26H.3 — sharper prompt + classical bbox fallback)
7. deviations (list of strings) — visual differences from the matched reference
8. confidence (0..1)
9. reason (one short sentence)

RULES:
- Do NOT reject a frame just because fins are clamped — set posture_class accordingly.
<<<<<<< HEAD
- "unusable" REQUIRED if: head-on, top-down, both eyes visible, only reflection.
- Only the highest (flare_score, match_score) frame gets "best".
- Prefer full-body-visible frames.
=======
- "unusable" only if head-on/top-down, or only reflection visible.
- Prefer highest (flare_score, match_score) for "best".
>>>>>>> 9711565 (Session 26H.3 — sharper prompt + classical bbox fallback)

Return ONLY JSON:
{
  "frames": [
    {"frame_index": 0, "match_score": 0.85, "flare_score": 0.90,
     "matched_reference": "hmpk_symmetrical_show", "posture_class": "fully_flared",
     "head_direction": "left", "bbox": {"x": 0.10, "y": 0.20, "w": 0.70, "h": 0.60},
     "deviations": ["dorsal fin base slightly narrow"],
     "confidence": 0.85, "reason": "Clean side profile with good flare"}
  ],
  "best": {"frame_index": 0, "bbox": {"x": 0.10, "y": 0.20, "w": 0.70, "h": 0.60},
           "reason": "Highest flare + match score"}
}
"""


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
    diag = {
        "genai_sdk_available": _GENAI_AVAILABLE,
        "secret_found": False,
        "secret_length": 0,
        "error": None,
    }
    try:
        key = st.secrets.get("GOOGLE_API_KEY", None)
        if key:
            diag["secret_found"] = True
            diag["secret_length"] = len(str(key))
    except Exception as e:
        diag["error"] = str(e)
    return diag


def judge_frames(frames_bytes, frame_indices=None):
    client = _get_client()
    if client is None or not frames_bytes:
        return None

    if frame_indices is None:
        frame_indices = list(range(len(frames_bytes)))

    if len(frames_bytes) > MAX_FRAMES_TO_JUDGE:
        step = len(frames_bytes) / MAX_FRAMES_TO_JUDGE
        keep = [int(i * step) for i in range(MAX_FRAMES_TO_JUDGE)]
        frames_bytes = [frames_bytes[i] for i in keep]
        frame_indices = [frame_indices[i] for i in keep]

    try:
        from modules.reference_shapes import load_reference_images
        refs = load_reference_images()
    except Exception:
        refs = []

    contents = [JUDGE_PROMPT]

    if refs:
        contents.append("=== REFERENCE SILHOUETTES ===")
        for ref in refs:
            contents.append("Reference: " + ref["name"])
            try:
                contents.append(types.Part.from_bytes(data=ref["bytes"], mime_type=ref["mime_type"]))
            except Exception:
                contents.append(types.Part.from_data(data=ref["bytes"], mime_type=ref["mime_type"]))
    else:
        contents.append("(No reference images. Use your HMPK knowledge.)")

    contents.append("=== CANDIDATE FRAMES ===")
    for orig_idx, fb in zip(frame_indices, frames_bytes):
        contents.append("Frame index " + str(orig_idx) + ":")
        try:
            contents.append(types.Part.from_bytes(data=fb, mime_type="image/jpeg"))
        except Exception:
            contents.append(types.Part.from_data(data=fb, mime_type="image/jpeg"))

    response = None
    last_error = None

    for attempt in range(MAX_RETRY_ATTEMPTS):
        model_to_try = GEMINI_MODEL_FALLBACKS[min(attempt, len(GEMINI_MODEL_FALLBACKS) - 1)]
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
<<<<<<< HEAD
            transient = any(code in err_str for code in [
                "503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED",
                "500", "INTERNAL", "DEADLINE_EXCEEDED", "TIMEOUT",
            ])
=======
            transient = any(code in err_str for code in ["503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "500", "INTERNAL", "DEADLINE_EXCEEDED", "TIMEOUT"])
>>>>>>> 9711565 (Session 26H.3 — sharper prompt + classical bbox fallback)
            if transient and attempt < MAX_RETRY_ATTEMPTS - 1:
                wait = RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)]
                st.info("Gemini busy (attempt " + str(attempt + 1) + "/" + str(MAX_RETRY_ATTEMPTS) + "). Retrying in " + str(wait) + "s...")
                time.sleep(wait)
                continue
            st.warning("Gemini API call failed: " + str(last_error))
            return None

    if response is None:
        return None

    raw_text = getattr(response, "text", None) or ""
    if not raw_text.strip():
        return None

    parsed = _parse_json_response(raw_text)
    if parsed is None:
        return None

    if isinstance(parsed, dict):
        frames_raw = parsed.get("frames", [])
        best_raw = parsed.get("best", None)
    elif isinstance(parsed, list):
        frames_raw = parsed
        best_raw = None
    else:
        return None

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

    normalized_best = None
    if best_raw and isinstance(best_raw, dict):
        bbox_raw = best_raw.get("bbox", {}) or best_raw.get("crop_box", {}) or {}
        bbox = _normalize_bbox(bbox_raw)
        if bbox:
            normalized_best = {
                "frame_index": int(best_raw.get("frame_index", -1)),
                "bbox": bbox,
                "crop_box": bbox,
                "reason": str(best_raw.get("reason", ""))[:250],
            }

    return {
        "frames": normalized_frames,
        "best": normalized_best,
        "reference_used": [r["name"] for r in refs],
    }


def _normalize_bbox(raw):
    try:
        x = float(raw.get("x", 0.0))
        y = float(raw.get("y", 0.0))
        w = float(raw.get("width", raw.get("w", 0.0)))
        h = float(raw.get("height", raw.get("h", 0.0)))
        x = max(0.0, min(1.0, x))
        y = max(0.0, min(1.0, y))
        w = max(0.02, min(1.0 - x, w))
        h = max(0.02, min(1.0 - y, h))
        if w < 0.05 or h < 0.05:
            return None
        return {"x": x, "y": y, "w": w, "h": h}
    except Exception:
        return None


def _parse_json_response(text):
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


def bbox_to_mask(shape, bbox, pad=0.08):
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


def crop_frame_to_bbox(frames_bytes, best):
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


crop_frame = crop_frame_to_bbox
