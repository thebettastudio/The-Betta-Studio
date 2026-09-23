# views/tank_view.py
# Betta Farm Management System
# Session 10 — Ported to Supabase via tank_registry + fish_manager.

from typing import Optional

import streamlit as st

from modules.tank_registry import (
    register_tank,
    get_all_tanks,
    find_tank,
    edit_tank,
    set_tank_status,
    assign_fish_to_tank,
    unassign_tank,
    delete_tank_and_media,
    update_fish_location,
    VALID_TANK_TYPES,
    VALID_STATUSES,
    VALID_PURPOSES,
)
from modules.fish_manager import get_fish_dropdown_items
from modules.photo_service import photo_url


# ============================================================
# PRESENTATION LABELS
# ============================================================
# Canonical purpose strings stay plain (used for tape-code prefix lookup).
# Labels add emoji + friendly text for display only.

PURPOSE_LABELS = {
    "Jarring":       "🫙 Jarring — Individual male/female jar",
    "Conditioning":  "🥩 Conditioning — Pre-spawn breeder conditioning",
    "Spawning":      "🥚 Spawning — Breeding pair setup",
    "Fry Nursery":   "🌿 Fry Nursery — Free-swimming fry container",
    "Grow-Out":      "🪴 Grow-Out — Fry / juvenile grow-out",
    "Sorority":      "👑 Sorority — Female colony tank",
    "Quarantine":    "🏥 Quarantine — Medical / treatment",
    "Sales Display": "🛒 Sales Display — Showcase / grooming",
    "Storage":       "📦 Storage — Empty / multi-purpose",
    "Other":         "❔ Other — Custom purpose",
}

TANK_TYPE_LABELS = {
    "Grow-Out Planggana (Large)":     "Grow-Out Planggana (Large)",
    "Spawning Planggana (Small)":     "Spawning Planggana (Small)",
    "6-Liter Water Bottle":           "6-Liter Water Bottle",
    "Empi Glass/Jar":                 "Empi (Emperador) Glass / Jar",
    "Glass Aquarium":                 "Glass Aquarium",
    "Sorority Basin":                 "Sorority / Female Basin",
    "Quarantine Jar":                 "Quarantine / Treatment Jar",
    "Custom":                         "➕ Other / Custom Container...",
}

CUSTOM_TANK_SENTINEL = "Custom"


def _purpose_label(p: str) -> str:
    return PURPOSE_LABELS.get(p, p)


def _tank_type_label(t: str) -> str:
    return TANK_TYPE_LABELS.get(t, t)


# ============================================================
# FISH DROPDOWN HELPERS
# ============================================================

def _get_fish_options(include_none: bool = True) -> list[dict]:
    """
    Returns dropdown options for occupants.
    Each item: {'id': uuid or None, 'label': str}
    """
    opts = []
    if include_none:
        opts.append({"id": None, "label": "— None (Empty) —"})

    for f in get_fish_dropdown_items():
        opts.append({
            "id": f["id"],
            "label": f"{f['system_id']} | {f.get('variety') or 'no variety'}",
        })
    return opts


def _fish_option_index(opts: list[dict], target_uuid: Optional[str]) -> int:
    if not target_uuid:
        return 0
    for i, o in enumerate(opts):
        if o["id"] == target_uuid:
            return i
    return 0


# ============================================================
# REGISTRATION FORM
# ============================================================

def render_registration_form():
    with st.form("tank_register_form", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            selected_type = st.selectbox(
                "Container / Tank Type",
                options=VALID_TANK_TYPES,
                format_func=_tank_type_label,
            )

            custom_type = ""
            if selected_type == CUSTOM_TANK_SENTINEL:
                custom_type = st.text_input(
                    "Enter Custom Container Name",
                    placeholder="e.g. 20L Storage Box, Styro Box, etc.",
                )

            capacity = st.number_input(
                "Capacity (Liters)",
                min_value=0.1, max_value=500.0, value=6.0, step=0.5,
            )

            purpose = st.selectbox(
                "Container Purpose / Role",
                options=VALID_PURPOSES,
                format_func=_purpose_label,
            )

        with col2:
            fish_opts = _get_fish_options(include_none=True)
            selected_fish_idx = st.selectbox(
                "Current Occupant (Optional)",
                options=range(len(fish_opts)),
                format_func=lambda i: fish_opts[i]["label"],
                help="Any active fish can be assigned. Leave as None for empty containers.",
            )
            selected_fish_id = fish_opts[selected_fish_idx]["id"]

            photo_file = st.file_uploader(
                "📷 Container Photo (Optional)",
                type=["jpg", "jpeg", "png"],
            )
            notes = st.text_area(
                "Notes / Setup Details",
                placeholder="e.g. Almond leaf tea water, sponge filter installed",
            )

        submit = st.form_submit_button("🏷️ Register Container & Generate Tape Tag")

    if not submit:
        return

    if selected_type == CUSTOM_TANK_SENTINEL and not custom_type.strip():
        st.error("Please enter a custom container name.")
        return

    final_type = custom_type.strip() if selected_type == CUSTOM_TANK_SENTINEL else selected_type

    with st.spinner("Generating tape tag & registering container..."):
        res = register_tank(
            tank_type=final_type,
            capacity_liters=capacity,
            purpose=purpose,
            photo_file=photo_file,
            current_occupant_id=selected_fish_id,
            notes=notes,
        )

    if not res:
        st.error("Registration failed — check logs.")
        return

    st.success("Container Successfully Registered!")
    st.markdown(f"""
    <div style="background-color: #FEF3C7; border: 2px dashed #D97706; padding: 16px; border-radius: 12px; text-align: center; margin: 12px 0;">
        <span style="font-size: 14px; color: #92400E; font-weight: bold; text-transform: uppercase;">✍️ WRITE THIS ON PAINTER'S TAPE:</span>
        <h1 style="font-size: 42px; color: #B45309; margin: 8px 0; font-family: monospace; letter-spacing: 2px;">{res['location_code']}</h1>
        <span style="font-size: 12px; color: #B45309;">System ID: {res['system_id']}</span>
    </div>
    """, unsafe_allow_html=True)

    if res.get("photo_id"):
        st.image(photo_url(res["photo_id"]), caption="Uploaded Container Photo", width=250)


# ============================================================
# UPDATE / DELETE POPOVER (inside each card)
# ============================================================

def _render_update_popover(t: dict, fish_opts: list[dict]):
    tank_uuid = t["id"]
    current_occ_uuid = t.get("occupant_fish_id")
    current_status = t.get("status") or "Empty / Idle"
    current_purpose = t.get("purpose") or "Other"
    current_notes = t.get("notes") or ""

    with st.popover("⚙️ Update / Remove", use_container_width=True):
        st.markdown("#### 📝 Edit Details")

        # Occupant selector
        occ_idx = _fish_option_index(fish_opts, current_occ_uuid)
        selected_occ_idx = st.selectbox(
            "Current Occupant",
            options=range(len(fish_opts)),
            index=occ_idx,
            format_func=lambda i: fish_opts[i]["label"],
            key=f"occ_sel_{tank_uuid}",
        )
        new_occ_uuid = fish_opts[selected_occ_idx]["id"]

        # Status
        status_index = VALID_STATUSES.index(current_status) if current_status in VALID_STATUSES else 0
        new_status = st.selectbox(
            "Status",
            options=VALID_STATUSES,
            index=status_index,
            key=f"status_{tank_uuid}",
        )

        # Purpose
        purpose_index = VALID_PURPOSES.index(current_purpose) if current_purpose in VALID_PURPOSES else VALID_PURPOSES.index("Other")
        new_purpose = st.selectbox(
            "Container Purpose",
            options=VALID_PURPOSES,
            index=purpose_index,
            format_func=_purpose_label,
            key=f"purpose_{tank_uuid}",
        )

        # Notes
        new_notes = st.text_area(
            "Notes",
            value=current_notes,
            key=f"notes_{tank_uuid}",
        )

        if st.button("💾 Save Changes", key=f"save_{tank_uuid}", type="primary", use_container_width=True):
            _apply_updates(
                tank_uuid=tank_uuid,
                old_occ_uuid=current_occ_uuid,
                new_occ_uuid=new_occ_uuid,
                old_status=current_status,
                new_status=new_status,
                old_purpose=current_purpose,
                new_purpose=new_purpose,
                old_notes=current_notes,
                new_notes=new_notes,
            )

        # Delete section
        st.divider()
        st.markdown("#### 🗑️ Remove Container")

        delete_reason = st.selectbox(
            "Reason for Removal",
            [
                "Error in Registration / Duplicate Entry",
                "Damaged / Cracked / Leaking",
                "Lost / Misplaced Container",
                "Permanently Retired from Service",
            ],
            key=f"del_reason_{tank_uuid}",
        )
        confirm_delete = st.checkbox(
            "I confirm I want to permanently delete this container.",
            key=f"del_confirm_{tank_uuid}",
        )
        if st.button(
            "🔥 Delete Container Permanently",
            key=f"del_btn_{tank_uuid}",
            type="secondary",
            disabled=not confirm_delete,
            use_container_width=True,
        ):
            with st.spinner("Deleting record..."):
                if delete_tank_and_media(tank_uuid):
                    st.success(f"Container {t.get('location_code')} removed.")
                    st.rerun()
                else:
                    st.error("Delete failed.")


def _apply_updates(
    *,
    tank_uuid: str,
    old_occ_uuid: Optional[str],
    new_occ_uuid: Optional[str],
    old_status: str,
    new_status: str,
    old_purpose: str,
    new_purpose: str,
    old_notes: str,
    new_notes: str,
):
    """
    Compare old vs new. Call the right functions:
      - occupant change -> assign_fish_to_tank / unassign_tank
      - status/purpose/notes change -> edit_tank
    """
    changed = False

    # Occupant handling
    if new_occ_uuid != old_occ_uuid:
        if new_occ_uuid is None:
            unassign_tank(tank_uuid)
            changed = True
        else:
            assign_fish_to_tank(tank_uuid, new_occ_uuid)
            changed = True

    # Other fields
    field_updates = {}
    if new_status != old_status:
        field_updates["status"] = new_status
    if new_purpose != old_purpose:
        field_updates["purpose"] = new_purpose
    if new_notes != old_notes:
        field_updates["notes"] = new_notes

    if field_updates:
        edit_tank(tank_uuid, field_updates)
        changed = True

    if changed:
        st.success("Updated successfully!")
        st.rerun()
    else:
        st.info("No changes to save.")


# ============================================================
# INVENTORY
# ============================================================

def render_inventory():
    st.subheader("Container Inventory")

    if st.button("🔄 Refresh Containers"):
        st.rerun()

    tanks = get_all_tanks()
    if not tanks:
        st.info("No containers registered yet.")
        return

    f_col1, f_col2 = st.columns([1, 2])
    with f_col1:
        availability_filter = st.selectbox(
            "🟢 Container Availability",
            options=["All Containers", "Available / Empty Only", "Occupied / In Use Only"],
            index=0,
        )
    with f_col2:
        search_query = st.text_input(
            "🔍 Search Inventory",
            placeholder="Search ID, Tape Code, Type, Purpose, or Occupant...",
        ).strip().lower()

    available_statuses = {"empty / idle", "empty", "idle", "available", "ready", "clean"}

    def _is_available(t):
        status = (t.get("status") or "").lower().strip()
        return status in available_statuses or not t.get("occupant_fish_id")

    filtered = []
    for t in tanks:
        is_avail = _is_available(t)
        if availability_filter == "Available / Empty Only" and not is_avail:
            continue
        if availability_filter == "Occupied / In Use Only" and is_avail:
            continue

        if search_query:
            haystack = " ".join([
                str(t.get("system_id") or ""),
                str(t.get("location_code") or ""),
                str(t.get("tank_type") or ""),
                str(t.get("purpose") or ""),
                str(t.get("occupant_label") or ""),
                str(t.get("notes") or ""),
            ]).lower()
            if search_query not in haystack:
                continue

        filtered.append(t)

    avail_count = sum(1 for t in tanks if _is_available(t))
    st.caption(
        f"Showing **{len(filtered)}** of **{len(tanks)}** containers | "
        f"🟢 **{avail_count}** Available / Empty"
    )
    st.markdown("---")

    if not filtered:
        st.warning("No containers match your filter criteria.")
        return

    fish_opts = _get_fish_options(include_none=True)
    cols = st.columns(3)
    for idx, t in enumerate(filtered):
        with cols[idx % 3]:
            with st.container(border=True):
                if t.get("photo_id"):
                    st.image(photo_url(t["photo_id"]), use_container_width=True)

                loc = t.get("location_code") or "?"
                sysid = t.get("system_id") or t["id"]
                st.markdown(f"### 🏷️ `{loc}`")
                st.caption(f"**System ID:** `{sysid}`")
                st.write(f"🪣 **Type:** {_tank_type_label(t.get('tank_type') or '')}")
                st.write(f"🎯 **Purpose:** {_purpose_label(t.get('purpose') or '')}")
                st.write(f"🧪 **Capacity:** {t.get('capacity_liters') or '—'} L")
                st.write(f"📌 **Status:** `{t.get('status') or 'Empty / Idle'}`")

                occ_label = t.get("occupant_label")
                if occ_label:
                    st.write(f"🐟 **Occupant:** `{occ_label}`")
                else:
                    st.write("🐟 **Occupant:** *Empty*")

                if t.get("notes"):
                    st.caption(f"📝 {t['notes']}")

                st.divider()
                _render_update_popover(t, fish_opts)


# ============================================================
# PAGE
# ============================================================

def render_tank_page():
    st.title("🪣 Tank & Container Registry")

    tab1, tab2 = st.tabs(["➕ Register Container", "🗃️ Container Inventory"])

    with tab1:
        st.subheader("Register New Tank or Container")
        render_registration_form()

    with tab2:
        render_inventory()
