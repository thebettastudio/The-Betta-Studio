# views/fish_registry_view.py
# Betta Farm Management System
# Session 11 — Ported to Supabase via fish_manager, tank_registry,
# database, photo_service, id_generator.
# Session 16 — Added "View Lineage" button on each fish card.
# Session 18 — Strains fully DB-managed (no more hardcoded defaults).
# Session 20 — Added milestone tracking section on each fish card.
# Session 22 — Added "Cull Fish" button with reason picker.
# Session 23 — Rewrote fish list: Visual Grid + Table toggle + Highlight strip.
# Session 23b — Uniform 4:3 rounded images in grid tiles.
# Session 24A — Added photo cropper UI (4:3) at upload time.
# Session 24A fix — Auto-save crop on every render; clear form after successful save.
# Session 26A — Multi-shot color capture UI.

import io
import datetime
from typing import Optional

import streamlit as st
from PIL import Image

# HEIC support (iPhone)
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

# Cropper
try:
    from streamlit_cropper import st_cropper
    _CROPPER_AVAILABLE = True
except ImportError:
    _CROPPER_AVAILABLE = False

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
MAX_SHOTS = 10
MIN_SHOTS_FOR_CONSENSUS = 3


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
# COLOR ANALYSIS — MULTI-SHOT SESSION
# ============================================================

def _reset_color_session(version_key: str):
    """Clear all color-session state for a given form version."""
    prefix = f"color_session_{version_key}"
    for key in list(st.session_state.keys()):
        if key.startswith(prefix):
            del st.session_state[key]


def _session_key(version_key: str, suffix: str) -> str:
    return f"color_session_{version_key}_{suffix}"


def _render_color_capture_ui(version_key: str):
    """
    Multi-shot color capture widget.
    - User taps camera to take shots
    - Each shot analyzed in-memory
    - Live feedback
    - When done: consensus shown with accept/upload options
    """
    cam_key = _session_key(version_key, "cam_key")
    shots_key = _session_key(version_key, "shots")
    analyses_key = _session_key(version_key, "analyses")
    done_key = _session_key(version_key, "done")
    consensus_key = _session_key(version_key, "consensus")

    if cam_key not in st.session_state:
        st.session_state[cam_key] = 0
    if shots_key not in st.session_state:
        st.session_state[shots_key] = []          # list of raw bytes
    if analyses_key not in st.session_state:
        st.session_state[analyses_key] = []       # list of analysis dicts
    if done_key not in st.session_state:
        st.session_state[done_key] = False
    if consensus_key not in st.session_state:
        st.session_state[consensus_key] = None

    st.markdown("##### 🎨 Multi-shot Color Analysis")
    st.caption(
        f"Take {MIN_SHOTS_FOR_CONSENSUS}–{MAX_SHOTS} shots from slightly different angles. "
        "Each shot is analyzed instantly — **no upload until you accept**."
    )

    shots = st.session_state[shots_key]
    analyses = st.session_state[analyses_key]

    # ---- Pre-capture state ----
    if not st.session_state[done_key]:
        st.camera_input(
            "Point at fish and tap the shutter",
            key=f"cam_widget_{version_key}_{st.session_state[cam_key]}",
        )

        # Handle new shot capture
        cam_result = st.session_state.get(f"cam_widget_{version_key}_{st.session_state[cam_key]}")
        if cam_result is not None:
            raw_bytes = cam_result.getvalue()
            # Analyze
            analysis = analyze_photo(raw_bytes)
            if analysis and analysis.get("ok"):
                st.session_state[shots_key].append(raw_bytes)
                st.session_state[analyses_key].append(analysis)
                # Bump camera key to reset widget for next shot
                st.session_state[cam_key] += 1
                st.rerun()
            else:
                err = (analysis or {}).get("error", "unknown error")
                st.warning(f"Shot could not be analyzed: {err}")
                st.session_state[cam_key] += 1
                st.rerun()

        # ---- Live feedback ----
        if shots:
            st.markdown("---")
            col_a, col_b = st.columns([2, 1])
            with col_a:
                st.markdown(f"**Shots taken: {len(shots)} / {MAX_SHOTS}**")
            with col_b:
                if st.button("🔄 Reset session", key=f"reset_{version_key}", use_container_width=True):
                    _reset_color_session(version_key)
                    st.rerun()

            # Per-shot list
            for i, (shot_bytes, analysis) in enumerate(zip(shots, analyses)):
                q = analysis.get("quality", {}).get("score", 0)
                st.caption(f"Shot {i+1}: quality **{q}/100**, primary `{analysis.get('primary')}`")

            # Consensus preview (once we have enough shots)
            if len(shots) >= MIN_SHOTS_FOR_CONSENSUS:
                consensus = merge_analyses(analyses)
                if consensus and consensus.get("ok"):
                    st.markdown("---")
                    st.markdown("**Live consensus:**")
                    st.markdown(palette_html(consensus.get("palette", {})), unsafe_allow_html=True)
                    st.caption(
                        f"Pattern: `{consensus.get('pattern_hint')}` · "
                        f"Iridescence: `{consensus.get('iridescence_level')}` "
                        f"({consensus.get('iridescence_score')})"
                    )

                # Buttons
                col_ok, col_more = st.columns(2)
                with col_ok:
                    if st.button("✅ Done — use these results", type="primary", use_container_width=True, key=f"done_{version_key}"):
                        st.session_state[done_key] = True
                        st.session_state[consensus_key] = merge_analyses(analyses)
                        st.rerun()
                with col_more:
                    if len(shots) >= MAX_SHOTS:
                        st.caption("Max shots reached")
                    else:
                        st.caption("Or take more shots above")

    # ---- Post-capture result ----
    else:
        consensus = st.session_state[consensus_key] or {}
        if not consensus.get("ok"):
            st.error("Could not compute consensus.")
            if st.button("🔁 Start over", key=f"restart_{version_key}"):
                _reset_color_session(version_key)
                st.rerun()
            return

        st.success(f"✓ Analysis complete — {consensus.get('shot_count', 0)} shots merged")

        # Palette
        st.markdown("**🎨 Detected colors:**")
        st.markdown(palette_html(consensus.get("palette", {})), unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Primary:** {color_swatch_html(consensus.get('primary') or '')}{consensus.get('primary') or '—'}", unsafe_allow_html=True)
        with col2:
            st.markdown(f"**Secondary:** {color_swatch_html(consensus.get('secondary') or '')}{consensus.get('secondary') or '—'}", unsafe_allow_html=True)

        st.markdown(f"**Pattern:** `{consensus.get('pattern_hint') or '—'}`")
        st.markdown(
            f"**✨ Iridescence:** `{consensus.get('iridescence_level') or 'none'}` "
            f"(score {consensus.get('iridescence_score') or 0})"
        )

        # Best shot
        best_idx = consensus.get("best_shot_index", 0)
        if shots and 0 <= best_idx < len(shots):
            st.markdown("---")
            st.markdown(f"**🏆 Best shot (quality {analyses[best_idx].get('quality', {}).get('score', 0)}/100):**")
            try:
                preview = Image.open(io.BytesIO(shots[best_idx]))
                st.image(preview, width=280)
            except Exception:
                st.caption("(preview unavailable)")

        # Action buttons
        st.markdown("---")
        col_accept, col_retake = st.columns(2)
        with col_accept:
            if st.button("✓ Keep this analysis", type="primary", use_container_width=True, key=f"accept_{version_key}"):
                # Mark analysis as accepted — the parent form reads from session state
                st.session_state[_session_key(version_key, "accepted")] = True
                st.rerun()
        with col_retake:
            if st.button("🔄 Retake session", use_container_width=True, key=f"retake_{version_key}"):
                _reset_color_session(version_key)
                st.rerun()

        if st.session_state.get(_session_key(version_key, "accepted")):
            st.info("✓ Color analysis accepted. It will be saved when you register the fish.")


def _get_accepted_color_data(version_key: str) -> Optional[dict]:
    """Return accepted color analysis data if user accepted in this session."""
    if not st.session_state.get(_session_key(version_key, "accepted")):
        return None
    consensus = st.session_state.get(_session_key(version_key, "consensus"))
    if not consensus or not consensus.get("ok"):
        return None
    return consensus


def _get_best_shot_bytes(version_key: str) -> Optional[bytes]:
    """Return the best shot's raw bytes if a session exists."""
    consensus = st.session_state.get(_session_key(version_key, "consensus"))
    shots = st.session_state.get(_session_key(version_key, "shots")) or []
    if not consensus or not shots:
        return None
    idx = consensus.get("best_shot_index", 0)
    if 0 <= idx < len(shots):
        return shots[idx]
    return None


# ============================================================
# CROPPER (existing, unchanged)
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

    # ---- Strain selector ----
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

    # ---- Color analysis section ----
    st.markdown("---")
    _render_color_capture_ui(version_key=form_version)

    # ---- Photo upload + crop (for the profile photo) ----
    st.markdown("---")
    st.markdown("##### 📷 Fish Profile Photo (4:3)")
    st.caption("This is the photo shown on fish tiles. Separate from color analysis above.")

    img_col1, img_col2 = st.columns(2)
    with img_col1:
        camera_photo = st.camera_input("Take a Live Photo", key=f"profile_cam_{form_version}")
    with img_col2:
        uploaded_photo = st.file_uploader(
            "Or Upload Photo File",
            type=["jpg", "jpeg", "png", "heic", "heif"],
            key=f"profile_upl_{form_version}",
        )

    if camera_photo is not None:
        st.session_state["fish_photo_raw"] = camera_photo.getvalue()
        st.session_state.pop("fish_photo_bytes", None)
    elif uploaded_photo is not None:
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
            st.markdown("**Final photo:**")
            st.image(preview_img, caption="Cropped to 4:3", width=320)
            if st.button("🔄 Re-crop photo", key=f"recrop_fish_{form_version}"):
                st.session_state.pop("fish_photo_bytes", None)
                st.rerun()
        except Exception:
            pass

    # ---- Main registration form ----
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

    # ---- Photo upload ----
    photo_id: Optional[str] = None
    photo_bytes = st.session_state.get("fish_photo_bytes")

    # If user didn't upload a profile photo, fall back to the best color-analysis shot
    if not photo_bytes:
        best_shot = _get_best_shot_bytes(form_version)
        if best_shot:
            photo_bytes = best_shot
            st.info("Using best color-analysis shot as profile photo.")

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

    # ---- Get color data if user accepted ----
    color_data = _get_accepted_color_data(form_version) or {}
    color_palette = color_data.get("palette") or {}
    color_primary = color_data.get("primary")
    color_secondary = color_data.get("secondary")
    pattern_hint = color_data.get("pattern_hint")
    iridescence_level = color_data.get("iridescence_level")

    # ---- Register ----
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

    # Patch photo + color data
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

    # ---- Cleanup ----
    st.session_state.pop("fish_photo_bytes", None)
    st.session_state.pop("fish_photo_raw", None)
    _reset_color_session(form_version)
    st.session_state["reg_form_version"] = form_version + 1

    st.balloons()
    st.success(f"🎉 Fish **#{result.get('system_id')}** registered!" + (" Colors saved." if color_primary else ""))
    st.rerun()


# ============================================================
# MILESTONE UI (unchanged from 24A)
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
            if st.button("🗑️ Delete", key=f"del_m_{m
