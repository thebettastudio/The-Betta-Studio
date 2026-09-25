# modules/ai_frame_judge.py
# Betta Farm Management System
# Session 26F — Gemini AI frame judge.
#
# Sends sampled video frames to Gemini (free tier) and asks which
# show a clean side view of the betta with fins flared.
#
# Fallback: if GOOGLE_API_KEY is missing or Gemini errors, returns
# None and the caller falls back to the classical pipeline.

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

# Gemini model to use. Flash is fast + free-tier friendly.
GEMINI_MODEL = "gemini-3.6-flash"

# Max frames to send to Gemini per video (free tier: 15 req/min)
MAX_FRAMES_TO_JUDGE = 10

# Timeout per API call (seconds)
API_TIMEOUT = 60


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

Return ONLY a JSON array. No prose. No markdown fences.
Each element is one frame, in the same order I sent them:

[
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
]

Rules:
- "pass" is true ONLY if: side view AND fins flared AND full body visible AND not reflection-only
- confidence is a float 0.0-1.0
- reason must be a short single sentence
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


# ============================================================
# MAIN ENTRY
# ============================================================

def judge_frames(frames_bytes: list[bytes],
                  frame_indices: Optional[list[int]] = None) -> Optional[list[dict]]:
    """
    Send frames to Gemini and get per-frame verdicts.

    Args:
        frames_bytes: list of JPEG bytes to analyze
        frame_indices: optional list mapping each frame_bytes[i] to
                       its original index in the video. If None, uses
                       sequential 0..n-1.

    Returns:
        List of dicts, one per frame, in the same order.
        None if Gemini is unavailable or errored.
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
        # Evenly sample
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
            # Some SDK versions want a different call
            contents.append(
                types.Part.from_data(data=fb, mime_type="image/jpeg")
            )

    # Call API
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
                max_output_tokens=4096,
            ),
        )
    except Exception as e:
        st.warning(f"Gemini API call failed: {e}")
        return None

    raw_text = getattr(response, "text", None) or ""
    if not raw_text.strip():
        return None

    # Parse JSON (Gemini sometimes wraps in code fences even with mime type)
    parsed = _parse_json_response(raw_text)
    if parsed is None:
        return None

    # Normalize: ensure each entry has the expected keys
    normalized = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        normalized.append({
            "frame_index": int(entry.get("frame_index", -1)),
            "pass": bool(entry.get("pass", False)),
            "head_direction": str(entry.get("head_direction", "unknown")).lower(),
            "is_reflection_only": bool(entry.get("is_reflection_only", False)),
            "fins_flared": bool(entry.get("fins_flared", False)),
            "full_body_visible": bool(entry.get("full_body_visible", False)),
            "confidence": float(entry.get("confidence", 0.5)),
            "reason": str(entry.get("reason", ""))[:200],
        })

    return normalized


def _parse_json_response(text: str) -> Optional[list]:
    """Extract JSON array from Gemini's response (handles fences)."""
    t = text.strip()

    # Strip markdown code fences if present
    if t.startswith("```"):
        # Remove leading ```json or ```
        first_nl = t.find("\n")
        if first_nl != -1:
            t = t[first_nl + 1:]
        # Remove trailing ```
        if t.endswith("```"):
            t = t[:-3].rstrip()

    # Try direct parse
    try:
        return json.loads(t)
    except Exception:
        pass

    # Try to find the first '[' ... last ']'
    start = t.find("[")
    end = t.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(t[start:end + 1])
        except Exception:
            pass

    return None
