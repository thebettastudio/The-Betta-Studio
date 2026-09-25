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
# Session 26B — Multi-photo upload + tap-to-select region analysis.
# Session 26C — Added video upload (auto frame scan).
# Session 26D fix — Better video UX + best frame handling.
# Session 26D round 2 — Stronger framing warning banner.
# Session 26E — Temp debug block for video posture diagnosis.

import io
import datetime
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
    analyze_video,
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
VIDEO_SAMPLE_EVERY = 5
VIDEO_MAX_FRAMES = 30
VIDEO_MAX_MB = 150


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
# COLOR CAPTURE — PHOTO + VIDEO
# ============================================================

def _reset_color_session(version_key: str):
    prefix = f"color_session_{version_key}"
    for key in list(st.session_state.keys()):
        if key.startswith(prefix):
            del st.session_state[key]


def _session_key(version_key: str, suffix: str) -> str:
    return f"color_session_{version_key}_{suffix}"


def _render_color_capture_ui(version_key: str):
    """Color analysis via Photos (tap-to-select) or Video (auto scan)."""
    session_prefix = f"color_session_{version_key}"

    defaults = {
        f"{session_prefix}_samples": [],
        f"{session_prefix}_snapshots": [],
        f"{session_prefix}_pending": [],
        f"{session_prefix}_tap_idx": 0,
        f"{session_prefix}_done": False,
        f"{session_prefix}_consensus": None,
        f"{session_prefix}_accepted": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    samples = st.session_state[f"{session_prefix}_samples"]
    snapshots = st.session_state[f"{session_prefix}_snapshots"]
    pending = st.session_state[f"{session_prefix}_pending"]
    tap_idx = st.session_state[f"{session_prefix}_tap_idx"]

    st.markdown("##### 🎨 Color Analysis")
    st.caption("Choose a method below. Take photos or video with your phone's camera app for best quality.")

    if st.session_state[f"{session_prefix}_done"]:
        _render_color_result(version_key)
        return

    if st.session_state[f"{session_prefix}_accepted"]:
        st.success("✓ Color analysis accepted. Save it with the fish registration below.")

    method = st.radio(
        "Method",
        options=["📸 Photos (tap to select)", "🎬 Video (auto scan)"],
        horizontal=True,
        key=f"method_{version_key}",
        label_visibility="collapsed",
    )

    # ============================================================
    # METHOD A — PHOTO UPLOAD + TAP-TO-SELECT
    # ============================================================
    if method.startswith("📸"):
        if not _TAP_AVAILABLE:
            st.error("Tap coordinate widget missing. Run: `py -m pip install streamlit-image-coordinates`")
            return

        uploaded_files = st.file_uploader(
            f"📁 Choose {MIN_SAMPLES_FOR_CONSENSUS}–{MAX_SAMPLES} photos of the same fish",
            type=["jpg", "jpeg", "png", "heic", "heif"],
            accept_multiple_files=True,
            key=f"color_uploads_{version_key}_{len(samples)}",
        )

        if uploaded_files:
            existing_hashes = {hash(p) for p in pending}
            for f in uploaded_files:
                data = f.getvalue()
                h = hash(data)
                if h in existing_hashes:
                    continue
                if len(samples) >= MAX_SAMPLES:
                    break
                pending.append(data)
                existing_hashes.add(h)
            st.session_state[f"{session_prefix}_pending"] = pending

        if pending and tap_idx < len(pending):
            photo = pending[tap_idx]
            st.markdown(f"**🎯 Tap the fish on photo {len(samples) + 1} of {MAX_SAMPLES}**")
            try:
                pil = Image.open(io.BytesIO(photo))
                if pil.mode in ("RGBA", "P", "LA"):
                    pil = pil.convert("RGB")
                display = _resize_for_display(pil, target_w=DISPLAY_WIDTH)
                dw, dh = display.size

                coords = streamlit_image_coordinates(display, key=f"tap_{version_key}_{len(samples)}_{tap_idx}")

                col_skip, col_discard = st.columns(2)
                with col_skip:
                    if st.button("⏭️ Skip this photo", use_container_width=True, key=f"skip_{version_key}_{tap_idx}"):
                        pending.pop(tap_idx)
                        st.session_state[f"{session_prefix}_pending"] = pending
                        st.session_state[f"{session_prefix}_tap_idx"] = max(0, tap_idx - 1)
                        st.rerun()
                with col_discard:
                    if st.button("🗑️ Discard all", use_container_width=True, key=f"discard_all_{version_key}"):
                        _reset_color_session(version_key)
                        st.rerun()

                if coords is not None:
                    with st.spinner("Analyzing tapped region..."):
                        analysis = analyze_region(
                            raw_bytes=photo,
                            tap_x=coords["x"],
                            tap_y=coords["y"],
                            display_w=dw,
                            display_h=dh,
                            region_size=TAP_REGION_SIZE,
                        )
                    if analysis and analysis.get("ok"):
                        samples.append(analysis)
                        snapshots.append(photo)
                        pending.pop(tap_idx)
                        st.session_state[f"{session_prefix}_samples"] = samples
                        st.session_state[f"{session_prefix}_snapshots"] = snapshots
                        st.session_state[f"{session_prefix}_pending"] = pending
                        st.session_state[f"{session_prefix}_tap_idx"] = max(0, tap_idx - 1)
                        if len(samples) >= MAX_SAMPLES:
                            st.session_state[f"{session_prefix}_done"] = True
                            st.session_state[f"{session_prefix}_consensus"] = merge_analyses(samples)
                        st.rerun()
                    else:
                        err = (analysis or {}).get("error", "unknown")
                        st.warning(f"Tap analysis failed: {err}")
            except Exception as e:
                st.warning(f"Could not process photo: {e}")
                pending.pop(tap_idx)
                st.session_state[f"{session_prefix}_pending"] = pending
                st.rerun()

        if not samples and not pending:
            st.info("👆 Upload photos above to start.")

    # ============================================================
    # METHOD B — VIDEO UPLOAD + AUTO SCAN
    # ============================================================
    else:
        st.warning(
            "📏 **Get CLOSE.** The fish should fill **40–60% of the frame**. "
            "If the whole tank is visible, detection fails — the app picks up "
            "glass and water instead of the fish."
        )
        with st.expander("📋 Recording tips (tap to expand)", expanded=False):
            st.markdown(
                "**✅ Do:**\n"
                "- Point at **ONE fish** — get close (10–15 cm away)\n"
                "- Fish fills 40–60% of the frame\n"
                "- Record 5–10 seconds, keep fish centered\n"
                "- Even lighting, minimal glare\n"
                "\n"
                "**🎯 Mirror setup:** the app picks the **largest fish** each "
                "frame. The real fish is bigger than its reflection, so it wins.\n"
                "\n"
                "**❌ Don't:**\n"
                "- Capture the whole tank\n"
                "- Multiple fish in frame\n"
                "- Fish cut off by frame edges\n"
                "- Camera shake / very dark / very bright\n"
                "\n"
                "**Recommended recording:** 1080p @ 60fps, 5–10 seconds, "
                "H.264 codec if possible (most compatible)."
            )

        video_file = st.file_uploader(
            "🎬 Upload a video of the fish",
            type=["mp4", "mov", "webm", "m4v", "avi"],
            accept_multiple_files=False,
            key=f"video_upload_{version_key}",
        )

        if video_file is not None:
            video_bytes = video_file.getvalue()
            size_mb = len(video_bytes) / (1024 * 1024)

            if size_mb > VIDEO_MAX_MB:
                st.warning(
                    f"⚠️ Video is {size_mb:.0f} MB. For best results, keep videos under "
                    f"{VIDEO_MAX_MB} MB (roughly 10 seconds at 1080p)."
                )
            else:
                st.caption(f"Video size: {size_mb:.1f} MB — ready to analyze.")

            if st.button("🔍 Analyze video", type="primary", use_container_width=True, key=f"analyze_video_{version_key}"):
                with st.spinner(f"Extracting frames and analyzing... this takes ~10–20s"):
                    result = analyze_video(
                        video_bytes,
                        sample_every=VIDEO_SAMPLE_EVERY,
                        max_frames=VIDEO_MAX_FRAMES,
                    )

                if not result or not result.get("ok"):
                    err = (result or {}).get("error", "unknown")
                    st.error(f"Video analysis failed: {err}")
                else:
                    analyses = result.get("analyses") or []
                    consensus = result.get("consensus") or {}
                    best_frame_bytes = result.get("best_frame_bytes")

                    st.session_state[f"{session_prefix}_samples"] = analyses
                    st.session_state[f"{session_prefix}_consensus"] = consensus
                    st.session_state[f"{session_prefix}_done"] = True

                    if best_frame_bytes:
                        st.session_state[f"{session_prefix}_snapshots"] = [best_frame_bytes]
                    else:
                        st.session_state[f"{session_prefix}_snapshots"] = []

                    st.success(f"✓ Analyzed {len(analyses)} frames from video.")
                    st.rerun()

            # ---------- TEMP DEBUG (remove when done) ----------
            with st.expander("🐛 Debug this video (temp)", expanded=False):
                if st.button("Run diagnostic", key=f"debug_video_{version_key}"):
                    from modules.color_debug import debug_analyze_video
                    with st.spinner("Diagnosing frames..."):
                        dbg = debug_analyze_video(
                            video_bytes,
                            sample_every=VIDEO_SAMPLE_EVERY,
                            max_frames=VIDEO_MAX_FRAMES,
                        )
                    st.json(dbg)
            # ---------- END TEMP DEBUG ----------

    # ---- Samples taken so far ----
    if samples:
        st.markdown("---")
        st.markdown(f"**📊 Samples taken: {len(samples)}**")
        for i, a in enumerate(samples[:5]):
            pal = a.get("palette", {})
            pal_str = ", ".join(f"{k} {v:.0f}%" for k, v in pal.items())
            q = a.get("quality", {}).get("score", 0)
            st.caption(f"Sample {i+1}: quality {q}/100 — {pal_str or 'no palette'}")
        if len(samples) > 5:
            st.caption(f"... and {len(samples) - 5} more")

        if not st.session_state[f"{session_prefix}_done"] and len(samples) >= MIN_SAMPLES_FOR_CONSENSUS:
            consensus_preview = merge_analyses(samples)
            st.markdown("**Live consensus:**")
            st.markdown(palette_html(consensus_preview.get("palette", {})), unsafe_allow_html=True)
            st.caption(
                f"Pattern: `{consensus_preview.get('pattern_hint')}` · "
                f"Iridescence: `{consensus_preview.get('iridescence_level')}`"
            )
            if st.button("✅ Done — use these results", type="primary", use_container_width=True, key=f"done_{version_key}"):
                st.session_state[f"{session_prefix}_done"] = True
                st.session_state[f"{session_prefix}_consensus"] = consensus_preview
                st.rerun()


def _render_color_result(version_key: str):
    session_prefix = f"color_session_{version_key}"
    consensus = st.session_state[f"{session_prefix}_consensus"] or {}

    if not consensus.get("ok"):
        st.error("Could not compute consensus.")
        if st.button("🔁 Start over", key=f"restart_{version_key}"):
            _reset_color_session(version_key)
            st.rerun()
        return

    st.success(f"✓ Analysis complete — {consensus.get('shot_count', 0)} samples merged")

    st.markdown("**🎨 Detected colors:**")
    st.markdown(palette_html(consensus.get("palette", {})), unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(
            f"**Primary:** {color_swatch_html(consensus.get('primary') or '')}"
            f"{consensus.get('primary') or '—'}",
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f"**Secondary:** {color_swatch_html(consensus.get('secondary') or '')}"
            f"{consensus.get('secondary') or '—'}",
            unsafe_allow_html=True,
        )

    st.markdown(f"**Pattern:** `{consensus.get('pattern_hint') or '—'}`")
    st.markdown(
        f"**✨ Iridescence:** `{consensus.get('iridescence_level') or 'none'}` "
        f"(score {consensus.get('iridescence_score') or 0})"
    )

    best_snap = _get_best_snapshot_bytes(version_key)
    if best_snap:
        st.markdown("---")
        st.markdown("**🏆 Best snapshot (will be used as profile photo):**")
        try:
            preview = Image.open(io.BytesIO(best_snap))
            st.image(preview, width=320)
        except Exception:
            pass

    st.markdown("---")
    col_accept, col_retake = st.columns(2)
    with col_accept:
        if st.button("✓ Keep this analysis", type="primary", use_container_width=True, key=f"accept_{version_key}"):
            st.session_state[f"{session_prefix}_accepted"] = True
            st.rerun()
    with col_retake:
        if st.button("🔄 Retake all", use_container_width=True, key=f"retake_{version_key}"):
            _reset_color_session(version_key)
            st.rerun()


def _get_accepted_color_data(version_key: str) -> Optional[dict]:
    if not st.session_state.get(_session_key(version_key, "accepted")):
        return None
    consensus = st.session_state.get(_session_key(version_key, "consensus"))
    if not consensus or not consensus.get("ok"):
        return None
    return consensus


def _get_best_snapshot_bytes(version_key: str) -> Optional[bytes]:
    session_prefix = f"color_session_{version_key}"
    snapshots = st.session_state.get(f"{session_prefix}_snapshots") or []
    samples = st.session_state.get(f"{session_prefix}_samples") or []
    if not snapshots or not samples:
        return None
    if len(snapshots) == 1:
        return snapshots[0]
    best_idx = max(
        range(len(samples)),
        key=lambda i: (samples[i].get("quality", {}) or {}).get("score", 0),
    )
    if 0 <= best_idx < len(snapshots):
        return snapshots[best_idx]
    return None


# ============================================================
# CROPPER
# ============================================================

def _render_cropper_ui(raw_bytes: bytes, key_prefix: str) -> Optional[bytes]:
    if not _CROPPER_AVAILABLE:
        return None
    try:
        st.markdown("##### ✂️ Adjust the photo")
        st.caption("Drag the blue corners to resize. Drag inside the box to move the image.")
        source_img = Image.open(io.BytesIO(raw_bytes))
        if source_img.mode in ("RGBA", "P", "LA"):
            source_img = source_img.convert("RGB")
        col_crop, col_controls = st.columns([3, 1])
        with col_crop:
            cropped = st_cropper(
                source_img,
                realtime_update=True,
                box_color="#0072FF",
                aspect_ratio=CROP_ASPECT,
                return_type="image",
                key=f"crop_{key_prefix}",
            )
        with col_controls:
            st.markdown("**How to crop**")
            st.caption("1. Drag the blue corners")
            st.caption("2. Drag inside to move")
            st.caption("3. Saved automatically")
            skip_clicked = st.button(
                "⏭️ Skip (auto center-crop)",
                use_container_width=True,
                key=f"skip_crop_{key_prefix}",
            )
        if skip_clicked:
            return _auto_crop_to_aspect(raw_bytes)
        if cropped is not None:
            return _image_to_jpeg_bytes(cropped)
        return None
    except Exception as e:
        st.warning(f"Cropper unavailable, using auto-crop ({e})")
        return _auto_crop_to_aspect(raw_bytes)


# ============================================================
# REGISTER TAB
# ============================================================

def render_register_tab():
    st.subheader("🛒 Purchased / Imported Fish Details")

    next_id = generate_fish_id()
    st.info(f"📌 Next Assigned Fish ID: **#{next_id}**")

    form_version = st.session_state.get("reg_form_version", 0)

    strains_list = _get_strain_names()

    strain_col_select, strain_col_btn = st.columns([4, 1])
    with strain_col_btn:
        st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
        with st.popover("⚙️ Manage Strains"):
            pop_add, pop_remove = st.tabs(["➕ Add", "🗑️ Remove"])
            with pop_add:
                st.markdown("##### Add New Strain")
                new_strain_val = st.text_input(
                    "Strain Name",
                    placeholder="e.g. Copper Blue Star",
                    key=f"new_strain_input_{form_version}",
                ).strip()
                if st.button("Save Strain", use_container_width=True, type="primary", key=f"btn_add_strain_{form_version}"):
                    if new_strain_val and _add_strain(new_strain_val):
                        st.session_state["selected_strain"] = new_strain_val
                        st.rerun()
            with pop_remove:
                st.markdown("##### Remove Existing Strain")
                if strains_list:
                    strain_to_delete = st.selectbox(
                        "Select Strain to Delete",
                        options=strains_list,
                        key=f"select_strain_to_delete_{form_version}",
                    )
                    if st.button("Delete Strain", use_container_width=True, type="primary", key=f"btn_delete_strain_{form_version}"):
                        _delete_strain(strain_to_delete)
                        if st.session_state.get("selected_strain") == strain_to_delete:
                            st.session_state.pop("selected_strain", None)
                        st.rerun()

    default_index = 0
    if "selected_strain" in st.session_state and st.session_state["selected_strain"] in strains_list:
        default_index = strains_list.index(st.session_state["selected_strain"])

    with strain_col_select:
        selected_strain = st.selectbox(
            "Select Strain",
            options=strains_list if strains_list else ["No Strains Available"],
            index=default_index if strains_list else 0,
            key=f"select_strain_dropdown_{form_version}",
        )

    st.markdown("---")
    _render_color_capture_ui(version_key=form_version)

    st.markdown("---")
    st.markdown("##### 📷 Profile Photo")
    st.caption("Optional — takes the best color-analysis photo by default. Upload only if you want a different one.")

    uploaded_photo = st.file_uploader(
        "Upload a different photo (optional)",
        type=["jpg", "jpeg", "png", "heic", "heif"],
        key=f"profile_upl_{form_version}",
    )

    if uploaded_photo is not None:
        st.session_state["fish_photo_raw"] = uploaded_photo.getvalue()
        st.session_state.pop("fish_photo_bytes", None)

    raw_bytes = st.session_state.get("fish_photo_raw")
    if raw_bytes and not st.session_state.get("fish_photo_bytes"):
        cropped_bytes = _render_cropper_ui(raw_bytes, key_prefix=f"fish_reg_{form_version}")
        if cropped_bytes:
            st.session_state["fish_photo_bytes"] = cropped_bytes

    if st.session_state.get("fish_photo_bytes"):
        try:
            preview_img = Image.open(io.BytesIO(st.session_state["fish_photo_bytes"]))
            st.markdown("**Custom photo (overrides best snapshot):**")
            st.image(preview_img, caption="Cropped to 4:3", width=320)
            if st.button("🔄 Re-crop photo", key=f"recrop_fish_{form_version}"):
                st.session_state.pop("fish_photo_bytes", None)
                st.rerun()
        except Exception:
            pass

    with st.form(f"register_fish_form_{form_version}", clear_on_submit=False):
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("##### 🧬 Variety & Details")
            form_type = st.text_input("Form / Type", value="HMPK", help="e.g. HMPK, HM, PK, CT", key=f"form_type_{form_version}")
            gender = st.selectbox("Gender", VALID_GENDERS, key=f"gender_{form_version}")
            seller = st.text_input("Seller / Source", placeholder="e.g. Aquarama Import / Local Breeder", key=f"seller_{form_version}")
            purchase_date = st.date_input("Purchase Date", datetime.date.today(), key=f"pdate_{form_version}")
            purchase_cost = st.number_input("Purchase Cost (₱)", min_value=0.0, value=0.0, step=50.0, key=f"pcost_{form_version}")

        with col2:
            st.markdown("##### 🪣 Tank & Container Assignment")
            tank_opts = _get_available_tank_options()
            tank_types = sorted({t["label"].split(" | ")[-1].rstrip(")") for t in tank_opts})
            type_filter_options = ["All Types"] + tank_types

            selected_type_filter = st.selectbox("Filter Tank Type", options=type_filter_options, key=f"ttype_{form_version}")

            if selected_type_filter != "All Types":
                filtered = [t for t in tank_opts if selected_type_filter in t["label"]]
            else:
                filtered = tank_opts

            tank_dropdown = [{"id": None, "label": "Leave Unassigned"}] + filtered
            selected_tank_idx = st.selectbox(
                "Select Available Tank / Jar Location",
                options=range(len(tank_dropdown)),
                format_func=lambda i: tank_dropdown[i]["label"],
                key=f"tank_sel_{form_version}",
            )
            selected_tank_id = tank_dropdown[selected_tank_idx]["id"]

        st.divider()
        st.markdown("### 🏆 Form Evaluation Criteria")

        chk_col, shape_col = st.columns([3, 2])
        with chk_col:
            caudal_spread = st.checkbox("Caudal Fin Spread 180°", value=True, key=f"cs_{form_version}")
            caudal_prop   = st.checkbox("Caudal Fin Proportion (Good branching, no damage)", value=True, key=f"cp_{form_version}")
            dorsal_struct = st.checkbox("Dorsal Fin Structure (Broad base & clean overlapping)", value=True, key=f"ds_{form_version}")
            anal_struct   = st.checkbox("Anal Fin Structure (Parallel & proper length)", value=True, key=f"as_{form_version}")
            ventral_fins  = st.checkbox("Ventral Fins (Straight, broad, no curl)", value=True, key=f"vf_{form_version}")
            pectoral_fins = st.checkbox("Pectoral Fins (Full & undamaged)", value=True, key=f"pf_{form_version}")

        with shape_col:
            body_shape = st.selectbox(
                "Body Shape",
                options=["Bullet Head", "Regular", "Spoonhead"],
                index=0,
                key=f"bs_{form_version}",
            )

        evaluation_checks = {
            "caudal_spread": caudal_spread,
            "caudal_prop":   caudal_prop,
            "dorsal_struct": dorsal_struct,
            "anal_struct":   anal_struct,
            "ventral_fins":  ventral_fins,
            "pectoral_fins": pectoral_fins,
        }

        computed_grade, total_points = calculate_form_grade(evaluation_checks, body_shape)
        st.info(f"🏆 Calculated Grade: **{computed_grade}** (Score: **{total_points}/100**)")

        st.divider()
        manual_image_id = st.text_input(
            "Or Paste Existing Drive ID",
            placeholder="Paste raw Drive file ID (not a URL)",
            key=f"manual_img_{form_version}",
        )
        notes = st.text_area(
            "Notes / Characteristics",
            placeholder="e.g. Strong dorsal, solid iridescence",
            key=f"notes_{form_version}",
        )

        submit = st.form_submit_button("💾 Register Fish", use_container_width=True)

    if not submit:
        return

    photo_id: Optional[str] = None
    photo_bytes = st.session_state.get("fish_photo_bytes")

    if not photo_bytes:
        best_snap = _get_best_snapshot_bytes(form_version)
        if best_snap:
            photo_bytes = best_snap
            st.info("Using best color-analysis photo as profile photo.")

    if photo_bytes:
        with st.spinner("Uploading & optimizing photo for Google Drive..."):
            normalized = _normalize_image_bytes(photo_bytes)
            photo_id = upload_photo(normalized, entity_type="fish", entity_id=next_id)
            if photo_id:
                st.success(f"Photo uploaded (Drive ID: {photo_id})")
            else:
                st.error("Photo upload failed. Continuing without photo.")

    if not photo_id and manual_image_id:
        photo_id = manual_image_id.strip() or None

    if not selected_strain or selected_strain == "No Strains Available":
        st.error("Please select a valid strain.")
        return

    color_data = _get_accepted_color_data(form_version) or {}
    color_palette = color_data.get("palette") or {}
    color_primary = color_data.get("primary")
    color_secondary = color_data.get("secondary")
    pattern_hint = color_data.get("pattern_hint")
    iridescence_level = color_data.get("iridescence_level")

    result = register_new_fish(
        origin="Purchased",
        gender=gender,
        variety=selected_strain,
        form_type=form_type,
        grade=computed_grade,
        body_shape=body_shape,
        form_score=total_points,
        fin_checks=evaluation_checks,
        seller=seller,
        purchase_date=str(purchase_date),
        purchase_cost=purchase_cost,
        notes=notes,
        photo_file=None,
        location=None,
        line_code="UNK",
        generation="P1",
        status="Active",
    )

    if not result:
        st.error("Fish registration failed. Check logs.")
        return

    patch: dict = {}
    if photo_id:
        patch["photo_id"] = photo_id
    if color_primary:
        patch["color_primary"] = color_primary
    if color_secondary:
        patch["color_secondary"] = color_secondary
    if color_palette:
        patch["color_palette"] = color_palette
    if pattern_hint:
        patch["pattern_hint"] = pattern_hint
    if iridescence_level:
        patch["iridescence_level"] = iridescence_level

    if patch:
        edit_fish(result["id"], patch)

    if selected_tank_id:
        assign_fish_to_tank(selected_tank_id, result["id"])

    st.session_state.pop("fish_photo_bytes", None)
    st.session_state.pop("fish_photo_raw", None)
    _reset_color_session(form_version)
    st.session_state["reg_form_version"] = form_version + 1

    st.balloons()
    st.success(f"🎉 Fish **#{result.get('system_id')}** registered!" + (" Colors saved." if color_primary else ""))
    st.rerun()


# ============================================================
# MILESTONE UI
# ============================================================

def _render_milestone_add_form(fish: dict):
    fish_uuid = fish["id"]
    crop_key = f"ms_{fish_uuid}"

    st.markdown("**➕ Add Milestone**")
    st.caption("**Photo (optional)** — cropped to 4:3")
    ms_photo_file = st.file_uploader(
        "Upload milestone photo",
        type=["jpg", "jpeg", "png", "heic", "heif"],
        key=f"{crop_key}_uploader",
    )

    if ms_photo_file is not None:
        st.session_state[f"{crop_key}_raw"] = ms_photo_file.getvalue()
        st.session_state.pop(f"{crop_key}_cropped", None)

    raw = st.session_state.get(f"{crop_key}_raw")
    if raw and not st.session_state.get(f"{crop_key}_cropped"):
        cropped = _render_cropper_ui(raw, key_prefix=crop_key)
        if cropped:
            st.session_state[f"{crop_key}_cropped"] = cropped

    if st.session_state.get(f"{crop_key}_cropped"):
        try:
            preview = Image.open(io.BytesIO(st.session_state[f"{crop_key}_cropped"]))
            st.image(preview, caption="Milestone photo (cropped)", width=280)
            if st.button("🔄 Re-crop photo", key=f"{crop_key}_recrop"):
                st.session_state.pop(f"{crop_key}_cropped", None)
                st.rerun()
        except Exception:
            pass

    with st.form(f"add_milestone_{fish_uuid}", clear_on_submit=False):
        col_a, col_b = st.columns(2)
        with col_a:
            m_date = st.date_input("Date", value=datetime.date.today(), key=f"m_date_{fish_uuid}")
        with col_b:
            m_shape = st.selectbox(
                "Body Shape",
                options=["", "Bullet Head", "Regular", "Spoonhead"],
                index=0,
                key=f"m_shape_{fish_uuid}",
            )

        st.caption("Optional re-score (leave blank to skip):")
        chk_col, _ = st.columns([3, 2])
        with chk_col:
            c1 = st.checkbox("Caudal 180°", key=f"m_c1_{fish_uuid}")
            c2 = st.checkbox("Caudal branching", key=f"m_c2_{fish_uuid}")
            c3 = st.checkbox("Dorsal structure", key=f"m_c3_{fish_uuid}")
            c4 = st.checkbox("Anal structure", key=f"m_c4_{fish_uuid}")
            c5 = st.checkbox("Ventral fins", key=f"m_c5_{fish_uuid}")
            c6 = st.checkbox("Pectoral fins", key=f"m_c6_{fish_uuid}")

        notes = st.text_area(
            "Notes",
            placeholder="e.g. Starting to color up, dorsal showing good rays",
            key=f"m_notes_{fish_uuid}",
        )

        submit = st.form_submit_button("Save Milestone", type="primary", use_container_width=True)

    if not submit:
        return

    checks = {
        "caudal_180": c1, "caudal_prop": c2, "dorsal_struct": c3,
        "anal_struct": c4, "ventral_fins": c5, "pectoral_fins": c6,
    }
    any_check = any(checks.values())
    score = None
    if any_check or m_shape:
        _, score = calculate_form_grade(checks, m_shape or "Regular")

    photo_bytes = st.session_state.get(f"{crop_key}_cropped") or st.session_state.get(f"{crop_key}_raw")

    add_milestone(
        fish_id=fish_uuid,
        milestone_date=str(m_date),
        photo_file=io.BytesIO(photo_bytes) if photo_bytes else None,
        form_score=score,
        body_shape=m_shape,
        fin_checks=checks if any_check else {},
        notes=notes,
    )

    st.session_state.pop(f"{crop_key}_cropped", None)
    st.session_state.pop(f"{crop_key}_raw", None)
    st.success("Milestone added.")
    st.rerun()


def _render_milestone_timeline(milestones: list[dict]):
    if not milestones:
        st.caption("No milestones yet.")
        return

    trend = compute_trend(milestones)
    if trend["direction"] == "rising":
        st.success(f"📈 Rising — latest score **{trend['latest_score']}** (+{trend['delta']})")
    elif trend["direction"] == "falling":
        st.warning(f"📉 Falling — latest score **{trend['latest_score']}** ({trend['delta']})")
    elif trend["direction"] == "flat":
        st.info(f"➡️ Flat — latest score **{trend['latest_score']}**")

    cols = st.columns(3)
    for idx, m in enumerate(milestones):
        with cols[idx % 3]:
            st.markdown(f"**{m.get('milestone_date') or '—'}**")
            if m.get("photo_id"):
                st.image(photo_url(m["photo_id"]), use_container_width=True)
            else:
                st.caption("📷 *No photo*")
            if m.get("form_score") is not None:
                st.caption(f"Score: **{m['form_score']}**")
            if m.get("body_shape"):
                st.caption(f"Shape: {m['body_shape']}")
            if m.get("notes"):
                st.caption(f"📝 {m['notes']}")
            if st.button("🗑️ Delete", key=f"del_m_{m['id']}", use_container_width=True):
                if remove_milestone(m["id"]):
                    st.success("Milestone deleted.")
                    st.rerun()


def _render_milestones_section(fish: dict, milestones: list[dict]):
    suggestion = suggest_action(fish, milestones)
    if suggestion:
        if suggestion["kind"] == "promote":
            st.success(f"{suggestion['icon']} **{suggestion['label']}** — {suggestion['reason']}")
        else:
            st.warning(f"{suggestion['icon']} **{suggestion['label']}** — {suggestion['reason']}")

    if milestone_is_due(fish, milestones):
        st.info(f"⏰ Milestone due — last check was {MILESTONE_INTERVAL_DAYS}+ days ago.")

    with st.expander("➕ Add Milestone", expanded=False):
        _render_milestone_add_form(fish)

    st.markdown(f"**📸 Milestones ({len(milestones)})**")
    _render_milestone_timeline(milestones)


# ============================================================
# CARD ACTIONS
# ============================================================

def _render_card_actions(fish: dict):
    fish_uuid = fish["id"]
    system_id = fish.get("system_id") or "?"
    current_status = (fish.get("status") or "").lower()

    if st.button("🌳 View Lineage", key=f"lineage_{fish_uuid}", use_container_width=True):
        st.session_state["lineage_fish_id"] = fish_uuid
        st.toast(f"Selected {system_id}. Open the Lineage page to view the tree.")

    if not fish.get("is_breeder") and current_status not in ("sold", "deceased", "retired", "culled"):
        if st.button("⭐ Promote to Breeder", key=f"promote_{fish_uuid}", use_container_width=True):
            if promote_to_breeder(fish_uuid):
                st.success(f"{system_id} promoted to breeder.")
                st.rerun()

    if current_status == "culled":
        with st.popover("↩️ Restore from Culled", use_container_width=True):
            st.markdown("**Restore this fish?**")
            restore_status = st.selectbox(
                "Restore to status",
                options=["Active", "Jarred", "For Sale"],
                key=f"restore_status_{fish_uuid}",
            )
            if st.button("Confirm Restore", key=f"restore_btn_{fish_uuid}", type="primary", use_container_width=True):
                if restore_fish_from_culled(fish_uuid, new_status=restore_status):
                    st.success(f"{system_id} restored.")
                    st.rerun()
    else:
        with st.popover("🚫 Cull Fish", use_container_width=True):
            st.markdown("**Cull this fish**")
            cull_reason = st.selectbox("Reason", options=CULL_REASONS, key=f"cull_reason_{fish_uuid}")
            cull_notes = st.text_area(
                "Additional notes (optional)",
                placeholder="e.g. Curled ventral fins",
                key=f"cull_notes_{fish_uuid}",
            )
            confirm_cull = st.checkbox("I understand — cull this fish.", key=f"cull_confirm_{fish_uuid}")
            if st.button(
                "Confirm Cull",
                key=f"cull_btn_{fish_uuid}",
                type="primary",
                use_container_width=True,
                disabled=not confirm_cull,
            ):
                if cull_fish(fish_uuid, reason=cull_reason, notes=cull_notes):
                    st.success(f"{system_id} culled.")
                    st.rerun()

    if current_status not in ("culled", "deceased", "retired"):
        tank_opts = _get_available_tank_options()
        if tank_opts:
            dd = [{"id": None, "label": "— Leave / Clear Tank —"}] + tank_opts
            selected_idx = st.selectbox(
                "Move to Tank",
                options=range(len(dd)),
                format_func=lambda i: dd[i]["label"],
                key=f"move_tank_{fish_uuid}",
            )
            new_tank_id = dd[selected_idx]["id"]
            if st.button("📦 Apply Move", key=f"apply_move_{fish_uuid}", use_container_width=True):
                if fish.get("tank_id"):
                    unassign_tank(fish["tank_id"])
                if new_tank_id:
                    assign_fish_to_tank(new_tank_id, fish_uuid)
                st.success("Location updated.")
                st.rerun()

    st.divider()
    confirm = st.checkbox("Confirm delete (removes fish + Drive photo)", key=f"del_confirm_{fish_uuid}")
    if st.button("🔥 Delete Fish", key=f"del_btn_{fish_uuid}", disabled=not confirm, use_container_width=True):
        if delete_fish_and_photos(fish_uuid):
            st.success(f"{system_id} deleted.")
            st.rerun()


# ============================================================
# UNIFORM PHOTO HTML
# ============================================================

def _uniform_photo_html(file_id: Optional[str], aspect: str = "4 / 3"):
    if not file_id:
        return (
            f'<div style="width:100%;aspect-ratio:{aspect};background:#F3F4F6;'
            f'border-radius:14px;display:flex;align-items:center;justify-content:center;'
            f'color:#9CA3AF;font-size:13px;">No Photo</div>'
        )
    url = photo_url(file_id)
    return (
        f'<div style="width:100%;aspect-ratio:{aspect};overflow:hidden;'
        f'border-radius:14px;background:#F3F4F6;">'
        f'<img src="{url}" style="width:100%;height:100%;object-fit:cover;display:block;" /></div>'
    )


def _color_swatch_row(fish: dict) -> str:
    palette = fish.get("color_palette") or {}
    if not palette:
        return ""
    parts = []
    for color, pct in sorted(palette.items(), key=lambda x: -x[1])[:4]:
        parts.append(color_swatch_html(color, size=14))
    return "".join(parts)


def _render_highlight_strip(all_fish: list[dict], milestone_counts: dict):
    active = [
        f for f in all_fish
        if (f.get("status") or "").lower() not in ("culled", "deceased", "sold", "retired")
    ]
    if not active:
        return

    grade_rank = {"Show Grade": 5, "High Grade": 4, "Breeder Grade": 3, "Material Grade": 2, "Pet Grade": 1}
    best = max(active, key=lambda f: grade_rank.get(f.get("grade") or "", 0))

    most_ms = None
    if milestone_counts:
        top_id = max(milestone_counts, key=lambda k: milestone_counts[k])
        most_ms = next((f for f in active if f["id"] == top_id), None)

    recent = None
    for f in sorted(active, key=lambda x: x.get("created_at") or "", reverse=True):
        age = get_fish_age_days(f)
        if age is not None and age <= 7:
            recent = f
            break

    picks = []
    if best:
        picks.append(("🏆 Best Form", best))
    if most_ms and (not best or most_ms["id"] != best["id"]):
        picks.append((f"📸 Most Milestones ({milestone_counts[most_ms['id']]})", most_ms))
    if recent and (not best or recent["id"] != best["id"]):
        picks.append(("🆕 Just Added", recent))

    if not picks:
        return

    st.markdown("###### ✨ Highlights")
    cols = st.columns(len(picks))
    for i, (label, f) in enumerate(picks):
        with cols[i]:
            with st.container(border=True):
                st.markdown(_uniform_photo_html(f.get("photo_id"), aspect="4 / 3"), unsafe_allow_html=True)
                st.caption(f"*{label}*")
                st.markdown(f"**{f.get('system_id')}**")
                st.caption(f"{f.get('gender') or '?'} · {f.get('variety') or '—'} · {f.get('grade') or '—'}")

    st.markdown("---")


# ============================================================
# GRID TILE
# ============================================================

def _render_grid_tile(fish: dict, milestone_count: int = 0):
    system_id = fish.get("system_id") or "?"
    status = (fish.get("status") or "Active").lower()
    is_culled = status in ("culled", "deceased")

    badge_bg = grade_badge_color(fish.get("grade"))
    badge_fg = grade_badge_text_color(fish.get("grade"))
    grade_text = fish.get("grade") or "—"

    age_days = get_fish_age_days(fish)
    age_text = format_fish_age(age_days)

    gender = (fish.get("gender") or "?").lower()
    gender_sym = "♂" if gender == "male" else ("♀" if gender == "female" else "•")

    with st.container(border=True):
        st.markdown(_uniform_photo_html(fish.get("photo_id"), aspect="4 / 3"), unsafe_allow_html=True)

        st.markdown(
            f'<span style="display:inline-block;background:{badge_bg};color:{badge_fg};'
            f'font-size:11px;font-weight:600;padding:2px 8px;border-radius:10px;'
            f'margin-top:6px;">{grade_text}</span>',
            unsafe_allow_html=True,
        )

        st.markdown(f"**{system_id}** · {gender_sym} {fish.get('variety') or '—'}")

        swatch_html = _color_swatch_row(fish)
        if swatch_html:
            st.markdown(f'<div style="margin-top:4px;">{swatch_html}</div>', unsafe_allow_html=True)

        badges = []
        if milestone_count:
            badges.append(f"📸 {milestone_count}")
        if age_text and age_text != "—":
            badges.append(f"🗓 {age_text}")
        if is_culled:
            badges.append("⛔ Culled")
        if fish.get("iridescence_level") and fish["iridescence_level"] != "none":
            badges.append(f"✨ {fish['iridescence_level']}")
        if fish.get("location"):
            badges.append(f"🪣 {fish['location']}")
        if badges:
            st.caption(" · ".join(badges))

        with st.popover("⚙️ Manage", use_container_width=True):
            _render_card_actions(fish)

        with st.popover("📸 Milestones" + (f" ({milestone_count})" if milestone_count else ""), use_container_width=True):
            milestones = get_milestones_for_fish(fish["id"])
            _render_milestones_section(fish, milestones)


# ============================================================
# TABLE VIEW
# ============================================================

def _render_table_view(filtered: list[dict], milestone_counts: dict):
    rows = []
    for f in filtered:
        age_days = get_fish_age_days(f)
        palette = f.get("color_palette") or {}
        palette_str = ", ".join(f"{k} {v:.0f}%" for k, v in sorted(palette.items(), key=lambda x: -x[1])[:3])
        rows.append({
            "ID": f.get("system_id") or "?",
            "Gender": f.get("gender") or "—",
            "Variety": f.get("variety") or "—",
            "Grade": f.get("grade") or "—",
            "Line": f.get("line_code") or "—",
            "Gen": f.get("generation") or "—",
            "Colors": palette_str or "—",
            "Irid.": f.get("iridescence_level") or "—",
            "Location": f.get("location") or "—",
            "Status": f.get("status") or "—",
            "Age": format_fish_age(age_days),
            "Milestones": milestone_counts.get(f["id"], 0),
        })
    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Milestones": st.column_config.NumberColumn("📸", width="small"),
            "Age": st.column_config.TextColumn("Age", width="small"),
        },
    )


# ============================================================
# LIST TAB
# ============================================================

CARD_PAGE_SIZE = 15


def render_list_tab():
    st.subheader("📋 Registered Fish Database")

    all_fish = get_all_fish()
    if not all_fish:
        st.info("No fish registered yet. Use the Register tab to add your first fish.")
        return

    milestone_counts = get_milestone_counts_by_fish()

    alive = [
        f for f in all_fish
        if (f.get("status") or "").lower() not in ("culled", "deceased")
    ]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Fish", len(all_fish))
    m2.metric("Alive", len(alive))
    m3.metric("Males", sum(1 for f in alive if (f.get("gender") or "").lower() == "male"))
    m4.metric("Females", sum(1 for f in alive if (f.get("gender") or "").lower() == "female"))

    st.divider()

    _render_highlight_strip(all_fish, milestone_counts)

    st.markdown("##### 🔍 Filter Database")
    f_col1, f_col2, f_col3, f_col4 = st.columns(4)

    with f_col1:
        gender_filter = st.multiselect(
            "Gender",
            options=sorted({f.get("gender") for f in all_fish if f.get("gender")}),
        )
    with f_col2:
        grade_filter = st.multiselect(
            "Grade",
            options=sorted({f.get("grade") for f in all_fish if f.get("grade")}),
        )
    with f_col3:
        variety_filter = st.multiselect(
            "Variety",
            options=sorted({f.get("variety") for f in all_fish if f.get("variety")}),
        )
    with f_col4:
        iri_filter = st.multiselect(
            "Iridescence",
            options=["none", "faint", "moderate", "strong"],
        )

    view_mode = st.radio(
        "View",
        options=["🎨 Grid", "📊 Table"],
        horizontal=True,
        label_visibility="collapsed",
    )
    hide_culled = st.checkbox("Hide culled & deceased", value=True)

    filtered = all_fish
    if gender_filter:
        filtered = [f for f in filtered if f.get("gender") in gender_filter]
    if grade_filter:
        filtered = [f for f in filtered if f.get("grade") in grade_filter]
    if variety_filter:
        filtered = [f for f in filtered if f.get("variety") in variety_filter]
    if iri_filter:
        filtered = [f for f in filtered if f.get("iridescence_level") in iri_filter]
    if hide_culled:
        filtered = [f for f in filtered if (f.get("status") or "").lower() not in ("culled", "deceased")]

    st.caption(f"Showing {len(filtered)} of {len(all_fish)} fish.")
    st.markdown("---")

    if not filtered:
        st.warning("No fish match the current filters.")
        return

    if view_mode == "📊 Table":
        _render_table_view(filtered, milestone_counts)
        return

    total_pages = max(1, (len(filtered) + CARD_PAGE_SIZE - 1) // CARD_PAGE_SIZE)
    if total_pages > 1:
        page = st.number_input(
            f"Page (1–{total_pages})",
            min_value=1, max_value=total_pages, value=1, step=1,
            key="fish_page_number",
        )
    else:
        page = 1

    start = (page - 1) * CARD_PAGE_SIZE
    page_items = filtered[start : start + CARD_PAGE_SIZE]

    cols = st.columns(3)
    for idx, fish in enumerate(page_items):
        with cols[idx % 3]:
            _render_grid_tile(fish, milestone_count=milestone_counts.get(fish["id"], 0))


# ============================================================
# PAGE
# ============================================================

def render_fish_registry_page():
    st.header("🐠 Fish Master Registry")
    st.caption("Register and manage individual imported, purchased, or batch-selected Betta fish.")

    tab_register, tab_view = st.tabs(["📝 Register New Fish", "📋 Fish List & Database"])

    with tab_register:
        render_register_tab()

    with tab_view:
        render_list_tab()
