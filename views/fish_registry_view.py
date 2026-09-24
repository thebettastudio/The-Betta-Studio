# views/fish_registry_view.py
# Betta Farm Management System
# Session 11 — Ported to Supabase via fish_manager, tank_registry,
# database, photo_service, id_generator.
# Session 16 — Added "View Lineage" button on each fish card.
# Session 18 — Strains fully DB-managed (no more hardcoded defaults).
# Session 20 — Added milestone tracking section on each fish card.
# Session 22 — Added "Cull Fish" button with reason picker.

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
    """Inline form to add a milestone. Uses a form to avoid rerun churn."""
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

    # Compute score if any checkbox checked OR shape selected
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

    # Trend summary
    trend = compute_trend(milestones)
    if trend["direction"] == "rising":
        st.success(f"📈 Rising — latest score **{trend['latest_score']}** (+{trend['delta']})")
    elif trend["direction"] == "falling":
        st.warning(f"📉 Falling — latest score **{trend['latest_score']}** ({trend['delta']})")
    elif trend["direction"] == "flat":
        st.info(f"➡️ Flat — latest score **{trend['latest_score']}**")
    # insufficient → no message

    # Photo grid + metadata
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

            # Delete button per milestone
            if st.button("🗑️ Delete", key=f"del_m_{m['id']}", use_container_width=True):
                if remove_milestone(m["id"]):
                    st.success("Milestone deleted.")
                    st.rerun()


def _render_milestones_section(fish: dict, milestones: list[dict]):
    """Full milestones expander content: suggestions, add form, timeline."""
    # 1. Suggestion banner (if trend-based suggestion exists)
    suggestion = suggest_action(fish, milestones)
    if suggestion:
        if suggestion["kind"] == "promote":
            st.success(f"{suggestion['icon']} **{suggestion['label']}** — {suggestion['reason']}")
        else:
            st.warning(f"{suggestion['icon']} **{suggestion['label']}** — {suggestion['reason']}")

    # 2. Due indicator
    if milestone_is_due(fish, milestones):
        st.info(f"⏰ Milestone due — last check was {MILESTONE_INTERVAL_DAYS}+ days ago.")

    # 3. Add milestone form (collapsible by using expander inside)
    with st.expander("➕ Add Milestone", expanded=False):
        _render_milestone_add_form(fish)

    # 4. Timeline
    st.markdown(f"**📸 Milestones ({len(milestones)})**")
    _render_milestone_timeline(milestones)


# ============================================================
# CARD RENDERING
# ============================================================

CARD_PAGE_SIZE = 20


def _render_fish_card(fish: dict, milestone_count: int = 0):
    with st.container(border=True):
        if fish.get("photo_id"):
            st.image(photo_url(fish["photo_id"]), use_container_width=True)
        else:
            st.caption("📷 *No Photo*")

        system_id = fish.get("system_id") or "?"
        st.markdown(f"### {system_id}")
        st.caption(
            f"**{fish.get('gender') or '?'}** | "
            f"`{fish.get('status') or 'Active'}` | "
            f"{fish.get('grade') or '—'}"
        )
        st.write(f"🧬 **Variety:** {fish.get('variety') or '—'}")
        if fish.get("form_type"):
            st.write(f"📐 **Form:** {fish['form_type']}")
        if fish.get("line_code") and fish["line_code"] != "UNK":
            st.write(f"🏷️ **Line:** {fish['line_code']} ({fish.get('generation') or 'P1'})")
        if fish.get("location"):
            st.write(f"🪣 **Location:** `{fish['location']}`")

        # Milestone badge
        if milestone_count:
            st.caption(f"📸 {milestone_count} milestone{'s' if milestone_count != 1 else ''}")

        with st.expander("⚙️ Manage"):
            _render_card_actions(fish)

        # Milestones expander (populated lazily to keep list fast)
        with st.expander("📸 Milestones", expanded=False):
            milestones = get_milestones_for_fish(fish["id"])
            _render_milestones_section(fish, milestones)


def _render_card_actions(fish: dict):
    fish_uuid = fish["id"]
    system_id = fish.get("system_id") or "?"
    current_status = (fish.get("status") or "").lower()

    # Lineage shortcut
    if st.button("🌳 View Lineage", key=f"lineage_{fish_uuid}", use_container_width=True):
        st.session_state["lineage_fish_id"] = fish_uuid
        st.toast(f"Selected {system_id}. Open the Lineage page to view the tree.")

    # Promote to breeder
    if not fish.get("is_breeder") and current_status not in ("sold", "deceased", "retired", "culled"):
        if st.button("⭐ Promote to Breeder", key=f"promote_{fish_uuid}", use_container_width=True):
            if promote_to_breeder(fish_uuid):
                st.success(f"{system_id} promoted to breeder.")
                st.rerun()

    # Cull / Restore
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

    # Move tank — only if not culled/deceased/retired
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

    # Delete
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
# LIST TAB
# ============================================================

def render_list_tab():
    st.subheader("📋 Registered Fish Database")

    all_fish = get_all_fish()
    if not all_fish:
        st.info("No fish registered yet. Use the Register tab to add your first fish.")
        return

    # Fast milestone count lookup
    milestone_counts = get_milestone_counts_by_fish()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Fish", len(all_fish))
    m2.metric("Males", sum(1 for f in all_fish if (f.get("gender") or "").lower() == "male"))
    m3.metric("Females", sum(1 for f in all_fish if (f.get("gender") or "").lower() == "female"))
    m4.metric(
        "Show/High Grade",
        sum(1 for f in all_fish if f.get("grade") in ("Show Grade", "High Grade")),
    )

    st.divider()

    st.markdown("##### 🔍 Filter Database")
    f_col1, f_col2, f_col3 = st.columns(3)
    with f_col1:
        gender_filter = st.multiselect("Gender", options=sorted({f.get("gender") for f in all_fish if f.get("gender")}))
    with f_col2:
        grade_filter = st.multiselect("Grade", options=sorted({f.get("grade") for f in all_fish if f.get("grade")}))
    with f_col3:
        variety_filter = st.multiselect("Variety", options=sorted({f.get("variety") for f in all_fish if f.get("variety")}))

    filtered = all_fish
    if gender_filter:
        filtered = [f for f in filtered if f.get("gender") in gender_filter]
    if grade_filter:
        filtered = [f for f in filtered if f.get("grade") in grade_filter]
    if variety_filter:
        filtered = [f for f in filtered if f.get("variety") in variety_filter]

    st.caption(f"Showing {len(filtered)} of {len(all_fish)} fish.")
    st.markdown("---")

    if not filtered:
        st.warning("No fish match the current filters.")
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

    cols = st.columns(2)
    for idx, fish in enumerate(page_items):
        with cols[idx % 2]:
            _render_fish_card(fish, milestone_count=milestone_counts.get(fish["id"], 0))


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
