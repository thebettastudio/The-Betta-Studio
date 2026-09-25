# modules/ai_frame_judge.py
# Betta Farm Management System
# Session 26F — Gemini AI frame judge.
# Session 26G — 15 frames, best-frame + crop box, retry with backoff.
#
# Sends sampled video frames to Gemini (free tier) and asks which
# show a clean side view of the betta with fins flared.
#
# Also returns the single best frame + a suggested crop box around
# just the fish (for use as the profile photo).
#
# Retry logic: 3 attempts with backoff on transient errors (503, 429).

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

# Try these models in order — first one that works wins
GEMINI_MODEL_FALLBACKS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
]
GEMINI_MODEL = GEMINI_MODEL_FALLBACKS[0]

# Max frames sent to Gemini per video (free tier: 15 req/min)
MAX_FRAMES_TO_JUDGE = 15

# Retry behavior on 503 / 429 / timeouts
MAX_RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = [5, 15]   # wait before retry 2, retry 3

# Threshold for "AI is available at all"
_GENAI_TIMEOUT_SECONDS = 60


# ============================================================
# PROMPT
# ============================================================

JUDGE_PROMPT = """You are analyzing frames from a video of a betta fish.
The video is filmed in a tank, and there may be a mirror reflection of
the fish visible in some frames.

For EACH frame I send you, analyze it carefully and answer:

1. Is this a clean SIDE VIEW of the fish?
   - Side view = head facing LEFT or RIGHT (not head-on, not top-down)
   - The fish's body profile must be clearly visible

2. Are the fins FLARED open? (not clamped flat against the body)

3. Is the FULL FISH visible in the frame?
   - Head, body, AND caudal (tail) all inside the frame
   - Not cut off by frame edges

4. Which direction is the head pointing?
   - "left", "right", "up", or "down"

5. Is the visible fish the REAL fish, or only a MIRROR REFLECTION?
   - Real fish: crisp edges, brighter, full shape
   - Reflection: softer, dimmer, may be clipped by tank walls

Return ONLY a JSON object. No prose. No markdown fences.

The object must have TWO keys: "frames" and "best".

"frames" is an array, one element per frame, in the same order I sent them:

{
  "frames": [
    {
      "frame_index": 0,
      "pass": true,
      "head_direction": "left",
      "is_reflection_only": false,
      "fins_flared": true,
      "full_body_visible": true,
      "confidence": 0.9,
      "reason": "Clean side profile, head left, fins flared, full body visible"
    },
    ...
  ],
  "best": {
    "frame_index": 8,
    "crop_box": {
      "x": 0.18,
      "y": 0.30,
      "width": 0.55,
      "height": 0.45
    },
    "reason": "Clearest side profile with full flared fins"
  }
}

Rules for "frames":
- "pass" is true ONLY if: side view AND fins flared AND full body visible AND not reflection-only
- confidence is a float 0.0-1.0
- reason must be a short single sentence

Rules for "best":
- frame_index must be one of the frames that PASS
- crop_box uses normalized coordinates 0..1 relative to the frame
  (x = left edge, y = top edge, width, height)
- crop_box should tightly frame JUST the fish, with a small margin
- If NO frame passes, set "best" to null
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
    """Quick check whether Gemini is configured and usable."""
    return _get_client() is not None


def get_diagnostic() -> dict:
    """Return diagnostic info for the debug page."""
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
    Send frames to Gemini and get per-frame verdicts + best frame.

    Args:
        frames_bytes: list of JPEG bytes to analyze
        frame_indices: optional list mapping each frame_bytes[i] to
                       its original index in the video.

    Returns:
        {
            "frames": [ {frame_index, pass, head_direction, ...}, ... ],
            "best": {frame_index, crop_box, reason} | None,
        }
        Or None if Gemini is unavailable or errored.
    """
    client = _get_client()
    if client is None:
        return None

    if not frames_bytes:
        return None

    if frame_indices is None:
        frame_indices = list(range(len(frames_bytes)))

    # Cap to avoid burning free tier
    if len(frames_bytes) > MAX_FRAMES_TO_JUDGE:
        step = len(frames_bytes) / MAX_FRAMES_TO_JUDGE
        keep = [int(i * step) for i in range(MAX_FRAMES_TO_JUDGE)]
        frames_bytes = [frames_bytes[i] for i in keep]
        frame_indices = [frame_indices[i] for i in keep]

    # Build contents
    contents: list = [JUDGE_PROMPT]
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

    # Call API with retry + model fallback
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
            break   # success
        except Exception as e:
            last_error = e
            err_str = str(e)

            transient = any(code in err_str for code in [
                "503", "UNAVAILABLE",
                "429", "RESOURCE_EXHAUSTED",
                "500", "INTERNAL",
                "DEADLINE_EXCEEDED", "TIMEOUT",
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

            # Not transient or out of retries
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

    # Parse JSON
    parsed = _parse_json_response(raw_text)
    if parsed is None:
        return None

    # Normalize: object with "frames" and "best"
    if isinstance(parsed, list):
        # Old format — treat as frames array only
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
        normalized_frames.append({
            "frame_index": int(entry.get("frame_index", -1)),
            "pass": bool(entry.get("pass", False)),
            "head_direction": str(entry.get("head_direction", "unknown")).lower(),
            "is_reflection_only": bool(entry.get("is_reflection_only", False)),
            "fins_flared": bool(entry.get("fins_flared", False)),
            "full_body_visible": bool(entry.get("full_body_visible", False)),
            "confidence": float(entry.get("confidence", 0.5)),
            "reason": str(entry.get("reason", ""))[:200],
        })

    # Normalize best
    normalized_best = None
    if best_raw and isinstance(best_raw, dict):
        crop = best_raw.get("crop_box", {}) or {}
        try:
            cx = float(crop.get("x", 0.0))
            cy = float(crop.get("y", 0.0))
            cw = float(crop.get("width", 0.0))
            ch = float(crop.get("height", 0.0))
            if 0.0 <= cx < 1.0 and 0.0 <= cy < 1.0 and 0.01 < cw <= 1.0 and 0.01 < ch <= 1.0:
                normalized_best = {
                    "frame_index": int(best_raw.get("frame_index", -1)),
                    "crop_box": {"x": cx, "y": cy, "width": cw, "height": ch},
                    "reason": str(best_raw.get("reason", ""))[:200],
                }
        except Exception:
            normalized_best = None

    return {
        "frames": normalized_frames,
        "best": normalized_best,
    }


def _parse_json_response(text: str):
    """Extract JSON from Gemini's response (handles fences + arrays/objects)."""
    t = text.strip()

    if t.startswith("```"):
        first_nl = t.find("\n")
        if first_nl != -1:
            t = t[first_nl + 1:]
        if t.endswith("```"):
            t = t[:-3].rstrip()

    # Try direct
    try:
        return json.loads(t)
    except Exception:
        pass

    # Try to find first { ... last } (object)
    if "{" in t and "}" in t:
        start = t.find("{")
        end = t.rfind("}")
        if end > start:
            try:
                return json.loads(t[start:end + 1])
            except Exception:
                pass

    # Try to find first [ ... last ] (array)
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
# CROP HELPER (used by callers to crop the best frame)
# ============================================================

def crop_frame(frames_bytes: list[bytes], best: dict) -> Optional[bytes]:
    """
    Given the frames list and the "best" object from judge_frames(),
    crop the selected frame using the crop_box. Returns JPEG bytes.
    """
    if not best or not frames_bytes:
        return None
    idx = best.get("frame_index", -1)
    if idx < 0 or idx >= len(frames_bytes):
        return None
    box = best.get("crop_box")
    if not box:
        return frames_bytes[idx]

    try:
        from PIL import Image
        img = Image.open(io.BytesIO(frames_bytes[idx]))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        W, H = img.size

        x = int(round(box["x"] * W))
        y = int(round(box["y"] * H))
        w = int(round(box["width"] * W))
        h = int(round(box["height"] * H))

        # Clamp
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
