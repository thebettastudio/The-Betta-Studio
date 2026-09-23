# views/breeder_view.py
# Betta Farm Management System
# Session 9 — Ported to Supabase via fish_manager.

import datetime
import streamlit as st

from modules.fish_manager import (
    list_breeders,
    register_breeder,
    retire_breeder,
    promote_to_breeder,
    find_fish,
)
from modules.photo_service import photo_url


# ============================================================
# PRESETS
# ============================================================

COLOR_PATTERN_OPTIONS = [
    "Avatar",
    "Multicolor Galaxy",
    "Multicolor",
    "Nemo Copper Semi Dumbo",
    "Yellow Koi",
    "Candy Nemo",
    "Neon Green Eyes",
    "Candy Koi",
    "Regular",
    "Yellow Koi Galaxy",
    "Others",
]

RETIREMENT_REASONS = [
    "Bad Parent (Egg / Fry Eater)",
    "Sick / Damaged / Health Issue",
    "Old Age / Natural Retirement",
    "Aggressive / Killed Partner",
    "Infertility / Low Hatch Rate",
    "Sold / Transferred",
    "Other",
]


# ============================================================
# GRADE EVALUATION
# ============================================================

def evaluate_grade(
    caudal_180, caudal_prop, dorsal_good, anal_good,
    ventral_good, pectoral_good, body_shape, color_good,
):
    """IBC-style grading. Same rules as before."""
    passed_fin_checks = sum([
        caudal_180, caudal_prop, dorsal_good,
        anal_good, ventral_good, pectoral_good,
    ])

    if (caudal_180 and caudal_prop
            and body_shape in ["Bullet Head", "Regular"]
            and passed_fin_checks >= 5
            and color_good):
        return "Show Grade"
    elif (caudal_180 or caudal_prop or passed_fin_checks >= 3) and color_good:
        return "Material Grade"
    else:
        return "Pet Grade"


# ============================================================
# CARD GRID
# ============================================================

def render_breeder_grid(breeders_list: list):
    """2-column card layout. Handles retire popover."""
    if not breeders_list:
        st.info("No breeders found in this section.")
        return

    cols = st.columns(2)
    for idx, b in enumerate(breeders_list):
        fish_uuid = b["id"]              # uuid — needed for retire
        system_id = b.get("system_id") or "?"
        breeder_status = str(b.get("breeder_status") or "Available").strip()
        is_retired = breeder_status.lower() in ("retired", "inactive")
        fish_status = str(b.get("status") or "").strip().lower()
        is_deceased_or_sold = fish_status in ("deceased", "sold")

        with cols[idx % 2]:
            with st.container(border=True):
                # Photo
                if b.get("photo_id"):
                    st.image(photo_url(b["photo_id"]), use_container_width=True)
                else:
                    st.caption("📷 *No Photo Available*")

                st.markdown(f"### {system_id}")
                st.caption(
                    f"**Sex:** {b.get('gender') or '?'} | "
                    f"**Status:** `{breeder_status}`"
                )
                st.write(f"🧬 **Variety:** {b.get('variety') or '—'}")
                st.write(f"🏷️ **Lineage:** {b.get('line_code') or '—'}")
                if b.get("purchase_date"):
                    st.write(f"📅 **DOB:** {b['purchase_date']}")

                if b.get("grade"):
                    st.write(f"🏆 **Grade:** {b['grade']}")

                if b.get("notes"):
                    st.info(f"📝 **Notes:** {b['notes']}")

                st.divider()

                # Retire section
                if is_retired or is_deceased_or_sold:
                    st.caption("🚫 *This breeder is inactive / retired.*")
                else:
                    with st.popover("🚫 Retire Breeder", use_container_width=True):
                        st.markdown("### Retire / Deactivate Breeder")
                        st.caption(
                            "Select a reason for taking this breeder out of "
                            "active breeding rotations."
                        )

                        reason = st.selectbox(
                            "Reason for Retirement",
                            RETIREMENT_REASONS,
                            key=f"retire_reason_{fish_uuid}",
                        )
                        add_notes = st.text_area(
                            "Additional Context / Details",
                            placeholder="e.g. Ate eggs on 2 consecutive spawn attempts.",
                            key=f"retire_notes_{fish_uuid}",
                        )
                        if st.button(
                            "Confirm Retirement",
                            key=f"confirm_retire_{fish_uuid}",
                            type="primary",
                            use_container_width=True,
                        ):
                            with st.spinner("Updating status..."):
                                success = retire_breeder(fish_uuid, reason=reason, notes=add_notes)
                            if success:
                                st.success(f"Breeder {system_id} marked as Retired/Inactive!")
                                st.rerun()
                            else:
                                st.error("Failed to update status.")


# ============================================================
# REGISTRATION FORM
# ============================================================

def render_registration_form():
    with st.form("register_form", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### 📋 Basic Info")
            sex = st.selectbox("Sex", ["Male", "Female"])
            pattern_class = st.selectbox("Color / Pattern Class", COLOR_PATTERN_OPTIONS)

            custom_pattern = ""
            if pattern_class == "Others":
                custom_pattern = st.text_input(
                    "Specify Other Pattern",
                    placeholder="e.g. Black Star",
                )

            lineage = st.text_input(
                "Lineage / Breeder Source",
                placeholder="e.g. Peter Suson",
            )
            dob = st.date_input("Date of Birth / Age", datetime.date.today())
            photo_file = st.file_uploader(
                "Upload Breeder Photo",
                type=["jpg", "jpeg", "png"],
            )

        with col2:
            st.markdown("### 🏆 Form Evaluation Criteria")

            caudal_180    = st.checkbox("Caudal Fin Spread 180°", value=True)
            caudal_prop   = st.checkbox("Caudal Fin Proportion (Good branching, no damage)", value=True)
            dorsal_good   = st.checkbox("Dorsal Fin Structure (Broad base & clean overlapping)", value=True)
            anal_good     = st.checkbox("Anal Fin Structure (Parallel & proper length)", value=True)
            ventral_good  = st.checkbox("Ventral Fins (Straight, broad, no curl)", value=True)
            pectoral_good = st.checkbox("Pectoral Fins (Full & undamaged)", value=True)

            body_shape = st.selectbox(
                "Body Shape",
                ["Bullet Head", "Regular", "Spoonhead"],
            )
            color_good = st.checkbox("Good Color / Pattern Coverage", value=True)
            notes = st.text_area(
                "Notes / Traits",
                placeholder="e.g. Active swimmer, sharp caudal ray edges",
            )

        submit = st.form_submit_button("📷 Register Breeder & Evaluate Grade")

    if not submit:
        return

    selected_pattern = custom_pattern.strip() if pattern_class == "Others" else pattern_class

    grade = evaluate_grade(
        caudal_180=caudal_180,
        caudal_prop=caudal_prop,
        dorsal_good=dorsal_good,
        anal_good=anal_good,
        ventral_good=ventral_good,
        pectoral_good=pectoral_good,
        body_shape=body_shape,
        color_good=color_good,
    )

    if not selected_pattern or not lineage:
        st.error("Please fill in the Color / Pattern Class and Lineage fields.")
        return

    fin_checks = {
        "caudal_180": caudal_180,
        "caudal_prop": caudal_prop,
        "dorsal_good": dorsal_good,
        "anal_good": anal_good,
        "ventral_good": ventral_good,
        "pectoral_good": pectoral_good,
        "color_good": color_good,
    }

    with st.spinner("Uploading photo to Google Drive..."):
        result = register_breeder(
            sex=sex,
            variety=selected_pattern,
            lineage=lineage,
            dob=str(dob),
            photo_file=photo_file,
            notes=notes,
            grade=grade,
            body_shape=body_shape,
            fin_checks=fin_checks,
        )

    if not result:
        st.error("Registration failed. Check logs.")
        return

    system_id = result.get("system_id") or "?"
    st.success(f"Registered successfully! Breeder ID: **{system_id}** | Grade: **{grade}**")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Tank Tag QR Code")
        if result.get("qr_id"):
            st.image(photo_url(result["qr_id"]), width=220)
        else:
            st.caption("No QR generated.")
    with c2:
        st.subheader("Breeder Photo")
        if photo_file:
            st.image(photo_file, caption=f"{selected_pattern} ({sex}) — {grade}", width=300)


# ============================================================
# INVENTORY & GALLERY
# ============================================================

def _split_active_inactive(fish_list):
    active, inactive = [], []
    for f in fish_list:
        bs = str(f.get("breeder_status") or "Available").strip().lower()
        if bs in ("retired", "inactive"):
            inactive.append(f)
        else:
            active.append(f)
    return active, inactive


def render_inventory():
    col_title, col_btn = st.columns([4, 1])
    with col_title:
        st.subheader("Breeder Inventory & Gallery")
    with col_btn:
        if st.button("🔄 Refresh", key="refresh_all"):
            st.rerun()

    breeders = list_breeders(include_retired=True)
    if not breeders:
        st.info("No breeders registered yet.")
        return

    search_query = st.text_input(
        "🔍 Search by ID, Variety, or Lineage:",
        "",
        key="search_merged",
    ).strip().lower()

    def _match(b):
        if not search_query:
            return True
        return (
            search_query in str(b.get("system_id", "")).lower()
            or search_query in str(b.get("variety", "")).lower()
            or search_query in str(b.get("line_code", "")).lower()
        )

    filtered = [b for b in breeders if _match(b)]

    males_list   = [b for b in filtered if (b.get("gender") or "").lower() == "male"]
    females_list = [b for b in filtered if (b.get("gender") or "").lower() == "female"]

    male_tab, female_tab = st.tabs(["♂️ Male Breeders", "♀️ Female Breeders"])

    with male_tab:
        active_m, inactive_m = _split_active_inactive(males_list)
        m_sub1, m_sub2 = st.tabs([
            f"🟢 Active Males ({len(active_m)})",
            f"🚫 Inactive / Retired Males ({len(inactive_m)})",
        ])
        with m_sub1:
            render_breeder_grid(active_m)
        with m_sub2:
            render_breeder_grid(inactive_m)

    with female_tab:
        active_f, inactive_f = _split_active_inactive(females_list)
        f_sub1, f_sub2 = st.tabs([
            f"🟢 Active Females ({len(active_f)})",
            f"🚫 Inactive / Retired Females ({len(inactive_f)})",
        ])
        with f_sub1:
            render_breeder_grid(active_f)
        with f_sub2:
            render_breeder_grid(inactive_f)


# ============================================================
# PAGE
# ============================================================

def render_breeder_page():
    st.title("🐟 Betta Breeder Management")

    tab1, tab2 = st.tabs([
        "➕ Register New Breeder",
        "📋 Breeder Inventory & Gallery",
    ])

    with tab1:
        st.subheader("Register a New Breeder")
        render_registration_form()

    with tab2:
        render_inventory()
