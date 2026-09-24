# views/fish_registry_view.py
# Betta Farm Management System
# Session 11 — Ported to Supabase.
# Session 16 — View Lineage button.
# Session 18 — Strains DB-managed.
# Session 20 — Milestone tracking.
# Session 22 — Cull Fish button.
# Session 23 — Visual Grid + Table + Highlight strip.
# Session 23b — Uniform 4:3 rounded images.
# Session 24A — Photo cropper + form reset.
# Session 26A — Multi-shot color capture (photo-based).
# Session 26B — WebRTC + snapshot + tap-to-select + STUN config.

import io
import datetime
import time
from typing import Optional

import streamlit as st
from PIL import Image

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

try:
    from streamlit_cropper import st_cropper
    _CROPPER_AVAILABLE = True
except ImportError:
    _CROPPER_AVAILABLE = False

try:
    from streamlit_webrtc import webrtc_streamer, VideoProcessorBase, WebRtcMode
    _WEBRTC_AVAILABLE = True
except ImportError:
    _WEBRTC_AVAILABLE = False

try:
    from streamlit_image_coordinates import streamlit_image_coordinates
    _TAP_AVAILABLE = True
except ImportError:
    _TAP_AVAILABLE = False

from database import (
    get_all_strains,
    create_strain,
    delete_strain,
    get_all_fish,
    get_milestones_for_fish,
    get_milestone_counts_by_fish,
)
from modules.fish_manager import (
    register_new_fish,
    edit_fish,
    delete_fish_and_photos,
    promote_to_breeder,
    cull_fish,
    restore_fish_from_culled,
    grade_badge_color,
    grade_badge_text_color,
    get_fish_age_days,
    format_fish_age,
    VALID_GRADES,
    VALID_GENDERS,
    CULL_REASONS,
    _fish_label,
)
from modules.tank_registry import (
    list_available_tanks,
    find_tank,
    assign_fish_to_tank,
    unassign_tank,
)
from modules.id_generator import generate_fish_id
from modules.photo_service import upload_photo, photo_url
from modules.fish_milestones import (
    add_milestone,
    edit_milestone,
    remove_milestone,
    milestone_is_due,
    compute_trend,
    suggest_action,
    MILESTONE_INTERVAL_DAYS,
)
from modules.color_detector import (
    analyze_photo,
    analyze_region,
    merge_analyses,
    color_swatch_html,
    palette_html,
    COLOR_SWATCHES,
)


# ============================================================
# CONSTANTS
# ============================================================

FISH_TABLE_ICON = "🐠"
CROP_ASPECT = (4, 3)
MAX_SAMPLES = 10
MIN_SAMPLES_FOR_CONSENSUS = 3
TAP_REGION_SIZE = 150
DISPLAY_WIDTH = 480

# WebRTC STUN config — required for Streamlit Cloud
RTC_CONFIG = {
    "iceServers": [
        {"urls": ["stun:stun.l.google.com:19302"]},
    ]
}


# ============================================================
# FORM EVALUATION
# ============================================================

def calculate_form_grade(checks: dict, body_shape: str) -> tuple[str, int]:
    total_score = sum(15 for passed in checks.values() if passed)
    shape_scores = {"Bullet Head": 10, "Regular": 8, "Spoonhead": 5}
    total_score += shape_scores.get(body_shape, 8)
    if total_score >= 95:
        grade = "Show Grade"
    elif total_score >= 80:
        grade = "High Grade"
    elif total_score >= 60:
        grade = "Breeder Grade"
    else:
        grade = "Pet Grade"
    return grade, total_score


def _normalize_image_bytes(raw: bytes) -> bytes:
    try:
        img = Image.open(io.BytesIO(raw))
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return buf.getvalue()
    except Exception:
        return raw


def _auto_crop_to_aspect(raw_bytes: bytes, aspect: tuple[int, int] = CROP_ASPECT) -> bytes:
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        w, h = img.size
        target_w, target_h = aspect
        target_ratio = target_w / target_h
        current_ratio = w / h
        if current_ratio > target_ratio:
            new_w = int(h * target_ratio)
            left = (w - new_w) // 2
            img = img.crop((left, 0, left + new_w, h))
        elif current_ratio < target_ratio:
            new_h = int(w / target_ratio)
            top = (h - new_h) // 2
            img = img.crop((0, top, w, top + new_h))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return buf.getvalue()
    except Exception:
        return raw_bytes


def _image_to_jpeg_bytes(pil_img: Image.Image) -> bytes:
    if pil_img.mode in ("RGBA", "P", "LA"):
        pil_img = pil_img.convert("RGB")
    buf = io.BytesIO()
    pil_img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _resize_for_display(pil_img: Image.Image, target_w: int = DISPLAY_WIDTH) -> Image.Image:
    w, h = pil_img.size
    if w <= target_w:
        return pil_img
    ratio = target_w / w
    return pil_img.resize((target_w, int(h * ratio)), Image.LANCZOS)


# ============================================================
# STRAIN HELPERS
# ============================================================

def _get_strain_names() -> list[str]:
    return sorted({s.get("name") for s in get_all_strains() if s.get("name")})


def _strain_name_to_id(name: str) -> Optional[str]:
    for s in get_all_strains():
        if s.get("name") == name:
            return s["id"]
    return None


def _add_strain(name: str) -> bool:
    name = name.strip()
    if not name:
        return False
    existing = [s.get("name") for s in get_all_strains()]
    if name in existing:
        st.toast(f"'{name}' already exists.", icon="ℹ️")
        return False
    create_strain(name=name)
    return True


def _delete_strain(name: str) -> bool:
    sid = _strain_name_to_id(name)
    if not sid:
        st.toast(f"'{name}' not found.", icon="⚠️")
        return False
    return delete_strain(sid)


# ============================================================
# TANK HELPERS
# ============================================================

def _tank_label(t: dict) -> str:
    loc = t.get("location_code") or "?"
    sysid = t.get("system_id") or t["id"]
    ttype = t.get("tank_type") or ""
    return f"{loc} ({sysid} | {ttype})"


def _get_available_tank_options() -> list[dict]:
    return [{"id": t["id"], "label": _tank_label(t)} for t in list_available_tanks()]


# ============================================================
# WEBRTC FRAME GRABBER
# ============================================================

class FrameGrabber(VideoProcessorBase):
    def __init__(self):
        self.latest_frame = None
        self.frame_count = 0

    def recv(self, frame):
        try:
            img = frame.to_ndarray(format="rgb24")
            self.latest_frame = img
            self.frame_count += 1
        except Exception as e:
            print(f"recv error: {e}")
        return frame
