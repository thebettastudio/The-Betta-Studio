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


# ============================================================
# CONSTANTS
# ============================================================

FISH_TABLE_ICON = "🐠"
HIDE_STATUSES_DEFAULT = ["Culled", "Deceased"]


# ============================================================
# FORM EVALUATION
# ============================================================

def calculate_form_grade(checks: dict, body_shape: str) -> tuple[str, int]:
    """Score = 15 per passed fin check + body shape bonus. Max 100."""
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
    """Ensure image is RGB JPEG-compatible. Returns original on failure."""
    try:
        img = Image.open(io.BytesIO(raw))
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return buf.getvalue()
    except Exception:
        return raw


# ============================================================
# STRAIN HELPERS
# ============================================================

def _get_strain_names() -> list[str]:
    """All strain names from the DB, sorted."""
    return sorted({s.get("name") for s in get_all_strains() if s.get("name")})


def _strain_name_to_id(name: str) -> Optional[str]:
    for s in get_all_strains():
        if s.get("name") == name:
            return s["id"]
    return None


def _add_strain(name: str) -> bool:
    """Create a strain in DB. Refuses duplicates."""
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
    """Delete a strain by name if it exists in DB."""
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
    """Returns list of {'id': uuid, 'label': str}."""
    return [
        {"id": t["id"], "label": _tank_label(t)}
        for t in list_available_tanks()
    ]


# ============================================================
# REGISTER TAB
# ============================================================

def render_register_tab():
    st.subheader("🛒 Purchased / Imported Fish Details")

    next_id = generate_fish_id()
    st.info(f"📌 Next Assigned Fish ID: **#{next_id}**")

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
                    key="new_strain_input",
                ).strip()
                if st.button("Save Strain", use_container_width=True, type="primary", key="btn_add_strain"):
                    if new_strain_val:
                        if _add_strain(new_strain_val):
                            st.session_state["selected_strain"] = new_strain_val
                            st.rerun()
                    else:
                        st.warning("Please enter a strain name.")

            with pop_remove:
                st.markdown("##### Remove Existing Strain")
                if strains_list:
                    strain_to_delete = st.selectbox(
                        "Select Strain to Delete",
                        options=strains_list,
                        key="select_strain_to_delete",
                    )
                    if st.button("Delete Strain", use_container_width=True, type="primary", key="btn_delete_strain"):
                        _delete_strain(strain_to_delete)
                        if st.session_state.get("selected_strain") == strain_to_delete:
                            st.session_state.pop("selected_strain", None)
                        st.rerun()
                else:
                    st.info("No strains available to remove.")

    default_index = 0
    if "selected_strain" in st.session_state and st.session_state["selected_strain"] in strains_list:
        default_index = strains_list.index(st.session_state["selected_strain"])

    with strain_col_select:
        selected_strain = st.selectbox(
            "Select Strain",
            options=strains_list if strains_list else ["No Strains Available"],
            index=default_index if strains_list else 0,
            key="select_strain_dropdown",
        )

    st.markdown("##### 📷 Fish Photo Capture / Upload")
    img_col1, img_col2 = st.columns(2)
    with img_col1:
        camera_photo = st.camera_input("Take a Live Photo of Fish")
    with img_col2:
        uploaded_photo = st.file_uploader(
            "Or Upload Photo File",
            type=["jpg", "jpeg", "png", "heic", "heif"],
            help="Supports iPhone HEIC and standard JPEG/PNG.",
        )

    if camera_photo is not None:
        st.session_state["fish_photo_bytes"] = camera_photo.getvalue()
    elif uploaded_photo is not None:
        st.session_state["fish_photo_bytes"] = uploaded_photo.getvalue()

    if st.session_state.get("fish_photo_bytes"):
        try:
            preview_img = Image.open(io.BytesIO(st.session_state["fish_photo_bytes"]))
            st.image(preview_img, caption="Photo Preview", width=250)
        except Exception:
            pass

    with st.form("register_fish_form", clear_on_submit=False):
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("##### 🧬 Variety & Details")
            form_type = st.text_input("Form / Type", value="HMPK", help="e.g. HMPK, HM, PK, CT")
            gender = st.selectbox("Gender", VALID_GENDERS)
            seller = st.text_input("Seller / Source", placeholder="e.g. Aquarama Import / Local Breeder")
            purchase_date = st.date_input("Purchase Date", datetime.date.today())
            purchase_cost = st.number_input("Purchase Cost (₱)", min_value=0.0, value=0.0, step=50.0)

        with col2:
            st.markdown("##### 🪣 Tank & Container Assignment")
            tank_opts = _get_available_tank_options()
            tank_types = sorted({t["label"].split(" | ")[-1].rstrip(")") for t in tank_opts})
            type_filter_options = ["All Types"] + tank_types

            selected_type_filter = st.selectbox("Filter Tank Type", options=type_filter_options)

            if selected_type_filter != "All Types":
                filtered = [t for t in tank_opts if selected_type_filter in t["label"]]
            else:
                filtered = tank_opts

            tank_dropdown = [{"id": None, "label": "Leave Unassigned"}] + filtered
            selected_tank_idx = st.selectbox(
                "Select Available Tank / Jar Location",
                options=range(len(tank_dropdown)),
                format_func=lambda i: tank_dropdown[i]["label"],
            )
            selected_tank_id = tank_dropdown[selected_tank_idx]["id"]

        st.divider()
        st.markdown("### 🏆 Form Evaluation Criteria")

        chk_col, shape_col = st.columns([3, 2])
        with chk_col:
            caudal_spread = st.checkbox("Caudal Fin Spread 180°", value=True)
            caudal_prop   = st.checkbox("Caudal Fin Proportion (Good branching, no damage)", value=True)
            dorsal_struct = st.checkbox("Dorsal Fin Structure (Broad base & clean overlapping)", value=True)
            anal_struct   = st.checkbox("Anal Fin Structure (Parallel & proper length)", value=True)
            ventral_fins  = st.checkbox("Ventral Fins (Straight, broad, no curl)", value=True)
            pectoral_fins = st.checkbox("Pectoral Fins (Full & undamaged)", value=True)

        with shape_col:
            body_shape = st.selectbox(
                "Body Shape",
                options=["Bullet Head", "Regular", "Spoonhead"],
                index=0,
                help="Select the head profile/body shape structure.",
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
        )
        notes = st.text_area(
            "Notes / Characteristics",
            placeholder="e.g. Strong dorsal, solid iridescence, aggressive disposition",
        )

        submit = st.form_submit_button("💾 Register Fish", use_container_width=True)

    if not submit:
        return

    photo_id: Optional[str] = None
    photo_bytes = st.session_state.get("fish_photo_bytes")
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

    if photo_id:
        edit_fish(result["id"], {"photo_id": photo_id})

    if selected_tank_id:
        assign_fish_to_tank(selected_tank_id, result["id"])

    st.session_state.pop("fish_photo_bytes", None)
    st.balloons()
    st.success(
        f"🎉 Fish **#{result.get('system_id')}** ({selected_strain}) registered!"
    )
    st.rerun()


# ============================================================
# MILESTONE UI
# ============================================================

def _render_milestone_add_form(fish: dict):
    """Inline form to add a milestone."""
    fish_uuid = fish["id"]

    with st.form(f"add_milestone_{fish_uuid}", clear_on_submit=True):
        st.markdown("**➕ Add Milestone**")

        col_a, col_b = st.columns(2)
        with col_a:
            m_date = st.date_input(
                "Date",
                value=datetime.date.today(),
                key=f"m_date_{fish_uuid}",
            )
        with col_b:
            photo_file = st.file_uploader(
                "Photo",
                type=["jpg", "jpeg", "png", "heic", "heif"],
                key=f"m_photo_{fish_uuid}",
            )

        st.caption("Optional re-score (leave blank to skip):")
        chk_col, shape_col = st.columns([3, 2])
        with chk_col:
            c1 = st.checkbox("Caudal 180°", key=f"m_c1_{fish_uuid}")
            c2 = st.checkbox("Caudal branching", key=f"m_c2_{fish_uuid}")
            c3 = st.checkbox("Dorsal structure", key=f"m_c3_{fish_uuid}")
            c4 = st.checkbox("Anal structure", key=f"m_c4_{fish_uuid}")
            c5 = st.checkbox("Ventral fins", key=f"m_c5_{fish_uuid}")
            c6 = st.checkbox("Pectoral fins", key=f"m_c6_{fish_uuid}")
        with shape_col:
            m_shape = st.selectbox(
                "Body Shape",
                options=["", "Bullet Head", "Regular", "Spoonhead"],
                index=0,
                key=f"m_shape_{fish_uuid}",
            )

        notes = st.text_area(
            "Notes",
            placeholder="e.g. Starting to color up, dorsal showing good rays",
            key=f"m_notes_{fish_uuid}",
        )

        submit = st.form_submit_button("Save Milestone", type="primary", use_container_width=True)

    if not submit:
        return

    checks = {
        "caudal_180": c1,
        "caudal_prop": c2,
        "dorsal_struct": c3,
        "anal_struct": c4,
        "ventral_fins": c5,
        "pectoral_fins": c6,
    }
    any_check = any(checks.values())
    score = None
    if any_check or m_shape:
        _, score = calculate_form_grade(checks, m_shape or "Regular")

    add_milestone(
        fish_id=fish_uuid,
        milestone_date=str(m_date),
        photo_file=photo_file,
        form_score=score,
        body_shape=m_shape,
        fin_checks=checks if any_check else {},
        notes=notes,
    )
    st.success("Milestone added.")
    st.rerun()


def _render_milestone_timeline(milestones: list[dict]):
    """Display milestones as a photo grid with dates + scores."""
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
    """Full milestones expander content."""
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
# CARD ACTIONS (shared by grid + table)
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
            st.caption("Sets status back to Active. Adds a note.")
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
            st.caption("Marks as culled, frees its tank, and logs the reason.")
            cull_reason = st.selectbox(
                "Reason",
                options=CULL_REASONS,
                key=f"cull_reason_{fish_uuid}",
            )
            cull_notes = st.text_area(
                "Additional notes (optional)",
                placeholder="e.g. Curled ventral fins, poor appetite since day 10",
                key=f"cull_notes_{fish_uuid}",
            )
            confirm_cull = st.checkbox(
                "I understand — cull this fish.",
                key=f"cull_confirm_{fish_uuid}",
            )
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
    confirm = st.checkbox(
        "Confirm delete (removes fish + Drive photo)",
        key=f"del_confirm_{fish_uuid}",
    )
    if st.button(
        "🔥 Delete Fish",
        key=f"del_btn_{fish_uuid}",
        disabled=not confirm,
        use_container_width=True,
    ):
        if delete_fish_and_photos(fish_uuid):
            st.success(f"{system_id} deleted.")
            st.rerun()


# ============================================================
# HIGHLIGHT STRIP
# ============================================================

def _uniform_photo_html(file_id: Optional[str], aspect: str = "4 / 3"):
    """
    Render a Drive image inside a fixed aspect-ratio container
    with rounded corners and object-fit: cover.
    Ensures every photo displays at identical dimensions.
    """
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
        f'<img src="{url}" '
        f'style="width:100%;height:100%;object-fit:cover;display:block;" />'
        f'</div>'
    )


def _render_highlight_strip(all_fish: list[dict], milestone_counts: dict):
    """Top-of-page curated strip: best grade, most milestones, recently added."""
    active = [
        f for f in all_fish
        if (f.get("status") or "").lower() not in ("culled", "deceased", "sold", "retired")
    ]
    if not active:
        return

    grade_rank = {
        "Show Grade": 5, "High Grade": 4, "Breeder Grade": 3,
        "Material Grade": 2, "Pet Grade": 1,
    }
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
                st.markdown(
                    _uniform_photo_html(f.get("photo_id"), aspect="4 / 3"),
                    unsafe_allow_html=True,
                )
                st.caption(f"*{label}*")
                st.markdown(f"**{f.get('system_id')}**")
                st.caption(
                    f"{f.get('gender') or '?'} · {f.get('variety') or '—'} · "
                    f"{f.get('grade') or '—'}"
                )

    st.markdown("---")


# ============================================================
# GRID TILE
# ============================================================

def _render_grid_tile(fish: dict, milestone_count: int = 0):
    """Compact visual grid tile for the fish list. Uniform 4:3 rounded photos."""
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

    # Dim container for culled
    wrapper_open = '<div style="opacity:0.45;">' if is_culled else '<div style="opacity:1.0;">'

    with st.container(border=True):
        # Uniform photo (4:3, rounded)
        st.markdown(
            _uniform_photo_html(fish.get("photo_id"), aspect="4 / 3"),
            unsafe_allow_html=True,
        )

        # Grade badge
        st.markdown(
            f'<span style="display:inline-block;background:{badge_bg};color:{badge_fg};'
            f'font-size:11px;font-weight:600;padding:2px 8px;border-radius:10px;'
            f'margin-top:6px;">{grade_text}</span>',
            unsafe_allow_html=True,
        )

        # ID + gender + variety
        st.markdown(f"**{system_id}** · {gender_sym} {fish.get('variety') or '—'}")

        # Badges row
        badges = []
        if milestone_count:
            badges.append(f"📸 {milestone_count}")
        if age_text and age_text != "—":
            badges.append(f"🗓 {age_text}")
        if is_culled:
            badges.append("⛔ Culled")
        if fish.get("location"):
            badges.append(f"🪣 {fish['location']}")
        if badges:
            st.caption(" · ".join(badges))

        # Quick actions
        with st.popover("⚙️ Manage", use_container_width=True):
            _render_card_actions(fish)

        with st.popover("📸 Milestones" + (f" ({milestone_count})" if milestone_count else ""), use_container_width=True):
            milestones = get_milestones_for_fish(fish["id"])
            _render_milestones_section(fish, milestones)


# ============================================================
# TABLE VIEW
# ============================================================

def _render_table_view(filtered: list[dict], milestone_counts: dict):
    """Dense table view for power users."""
    rows = []
    for f in filtered:
        age_days = get_fish_age_days(f)
        rows.append({
            "ID": f.get("system_id") or "?",
            "Gender": f.get("gender") or "—",
            "Variety": f.get("variety") or "—",
            "Grade": f.get("grade") or "—",
            "Line": f.get("line_code") or "—",
            "Gen": f.get("generation") or "—",
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
    st.caption("💡 Tip: use the Grid view for photo browsing. Table view is best for finding a specific fish fast.")


# ============================================================
# LIST TAB (MAIN)
# ============================================================

CARD_PAGE_SIZE = 15


def render_list_tab():
    st.subheader("📋 Registered Fish Database")

    all_fish = get_all_fish()
    if not all_fish:
        st.info("No fish registered yet. Use the Register tab to add your first fish.")
        return

    milestone_counts = get_milestone_counts_by_fish()

    # ---- Metrics ----
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

    # ---- Highlight Strip ----
    _render_highlight_strip(all_fish, milestone_counts)

    # ---- Filters ----
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
        hide_culled = st.checkbox("Hide culled & deceased", value=True)

    # ---- View toggle ----
    view_mode = st.radio(
        "View",
        options=["🎨 Grid", "📊 Table"],
        horizontal=True,
        label_visibility="collapsed",
    )

    # ---- Apply filters ----
    filtered = all_fish
    if gender_filter:
        filtered = [f for f in filtered if f.get("gender") in gender_filter]
    if grade_filter:
        filtered = [f for f in filtered if f.get("grade") in grade_filter]
    if variety_filter:
        filtered = [f for f in filtered if f.get("variety") in variety_filter]
    if hide_culled:
        filtered = [
            f for f in filtered
            if (f.get("status") or "").lower() not in ("culled", "deceased")
        ]

    st.caption(f"Showing {len(filtered)} of {len(all_fish)} fish.")
    st.markdown("---")

    if not filtered:
        st.warning("No fish match the current filters.")
        return

    # ---- Render view ----
    if view_mode == "📊 Table":
        _render_table_view(filtered, milestone_counts)
        return

    # Grid view with pagination
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
