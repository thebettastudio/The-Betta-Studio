# views/fish_registry_view.py
# Betta Farm Management System
# Session 11 — Ported to Supabase via fish_manager, tank_registry,
# database, photo_service, id_generator.
# Session 16 — Added "View Lineage" button on each fish card.
# Session 18 — Strains fully DB-managed (no more hardcoded defaults).

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
)
from modules.fish_manager import (
    register_new_fish,
    edit_fish,
    delete_fish_and_photos,
    promote_to_breeder,
    VALID_GRADES,
    VALID_GENDERS,
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
# CARD RENDERING
# ============================================================

CARD_PAGE_SIZE = 20


def _render_fish_card(fish: dict):
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

        with st.expander("⚙️ Manage"):
            _render_card_actions(fish)


def _render_card_actions(fish: dict):
    fish_uuid = fish["id"]
    system_id = fish.get("system_id") or "?"

    # Lineage shortcut
    if st.button("🌳 View Lineage", key=f"lineage_{fish_uuid}", use_container_width=True):
        st.session_state["lineage_fish_id"] = fish_uuid
        st.toast(f"Selected {system_id}. Open the Lineage page to view the tree.")

    # Promote to breeder
    if not fish.get("is_breeder") and fish.get("status") not in ("Sold", "Deceased", "Retired"):
        if st.button("⭐ Promote to Breeder", key=f"promote_{fish_uuid}", use_container_width=True):
            if promote_to_breeder(fish_uuid):
                st.success(f"{system_id} promoted to breeder.")
                st.rerun()

    # Move tank
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
            _render_fish_card(fish)


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
