import re
import streamlit as st
from modules.tank_registry import (
    register_tank,
    get_all_tanks,
    update_tank_status,
    delete_tank
)
from modules.breeder_registry import get_available_breeders

DEFAULT_CONTAINER_TYPES = [
    "Grow-Out Planggana (Large)",
    "Spawning Planggana (Small)",
    "6-Liter Water Bottle",
    "Empi (Emperador) Glass / Jar",
    "Glass Aquarium",
    "Sorority / Female Basin",
    "Quarantine / Treatment Jar",
    "➕ Other / Custom Container..."
]

CONTAINER_PURPOSES = [
    "🫙 Male / Female Individual Jarring",
    "🥩 Breeder Conditioning",
    "🥚 Spawning & Breeding Set-Up",
    "🌿 Fry Nursery / Free Swimming",
    "🪴 Fry / Juvenile Grow-Out",
    "👑 Female Sorority Tank",
    "🏥 Medical / Quarantine Treatment",
    "🛒 Sales / Grooming Display",
    "📦 General / Multi-purpose Storage"
]


def clean_text_for_matching(text: str) -> str:
    """Strips special characters and emojis for reliable index matching."""
    return re.sub(r'[^\w\s]', '', text).strip().lower()


def get_purpose_index(stored_purpose: str) -> int:
    """Matches stored purpose string against CONTAINER_PURPOSES safely."""
    clean_stored = clean_text_for_matching(stored_purpose)
    if not clean_stored:
        return 0

    for idx, purpose in enumerate(CONTAINER_PURPOSES):
        clean_p = clean_text_for_matching(purpose)
        if clean_p in clean_stored or clean_stored in clean_p:
            return idx
    return 0


def render_tank_page():
    st.title("🪣 Tank & Container Registry")

    tab1, tab2 = st.tabs(["➕ Register Container", "🗃️ Container Inventory"])

    # Fetch available breeders (unassigned to any tank)
    available_breeders = get_available_breeders()
    breeder_options = ["None (Empty)"] + [
        f"{b['id']} | {b.get('variety', 'Betta')} ({b.get('sex', 'Unknown')})"
        for b in available_breeders
    ]

    # TAB 1: REGISTER CONTAINER
    with tab1:
        st.subheader("Register New Tank or Container")

        with st.form("tank_register_form", clear_on_submit=True):
            col1, col2 = st.columns(2)

            with col1:
                selected_type = st.selectbox("Container / Tank Type", DEFAULT_CONTAINER_TYPES)

                custom_type = ""
                if selected_type == "➕ Other / Custom Container...":
                    custom_type = st.text_input("Enter Custom Container Name", placeholder="e.g. 20L Storage Box, Styro Box, etc.")

                capacity = st.number_input("Capacity (Liters)", min_value=0.1, max_value=500.0, value=6.0, step=0.5)
                purpose = st.selectbox("Container Purpose / Role", CONTAINER_PURPOSES)

            with col2:
                selected_occupant = st.selectbox(
                    "Current Occupant (Available Fish Only)",
                    options=breeder_options,
                    help="Only active breeders not assigned to other tanks are listed."
                )
                photo_file = st.file_uploader("📷 Container Photo (Optional)", type=["jpg", "jpeg", "png"])
                notes = st.text_area("Notes / Setup Details", placeholder="e.g. Almond leaf tea water, sponge filter installed")

            submit = st.form_submit_button("🏷️ Register Container & Generate Tape Tag")

        if submit:
            if selected_type == "➕ Other / Custom Container..." and not custom_type.strip():
                st.error("Please enter a custom container name.")
            else:
                final_type = custom_type.strip() if selected_type == "➕ Other / Custom Container..." else selected_type
                occupant_id = "" if selected_occupant == "None (Empty)" else selected_occupant.split(" | ")[0]

                with st.spinner("Generating Tape Tag & registering container..."):
                    res = register_tank(
                        tank_type=final_type,
                        capacity_liters=capacity,
                        purpose=purpose,
                        photo_file=photo_file,
                        current_occupant=occupant_id,
                        notes=notes
                    )

                st.cache_data.clear()  # Clear cache after registering
                st.success("Container Successfully Registered!")
                st.markdown(f"""
                <div style="background-color: #FEF3C7; border: 2px dashed #D97706; padding: 16px; border-radius: 12px; text-align: center; margin: 12px 0;">
                    <span style="font-size: 14px; color: #92400E; font-weight: bold; text-transform: uppercase;">✍️ WRITE THIS ON PAINTER'S TAPE:</span>
                    <h1 style="font-size: 42px; color: #B45309; margin: 8px 0; font-family: monospace; letter-spacing: 2px;">{res['location_code']}</h1>
                    <span style="font-size: 12px; color: #B45309;">System ID: {res['tank_id']}</span>
                </div>
                """, unsafe_allow_html=True)

                if res.get("direct_photo_url"):
                    st.image(res["direct_photo_url"], caption="Uploaded Container Photo", width=250)

    # TAB 2: CONTAINER INVENTORY
    with tab2:
        st.subheader("Container Inventory")
        if st.button("🔄 Refresh Containers"):
            st.cache_data.clear()
            st.rerun()

        tanks = get_all_tanks()
        if not tanks:
            st.info("No containers registered yet.")
        else:
            f_col1, f_col2 = st.columns([1, 2])

            with f_col1:
                availability_filter = st.selectbox(
                    "🟢 Container Availability",
                    options=["All Containers", "Available / Empty Only", "Occupied / In Use Only"],
                    index=0
                )

            with f_col2:
                search_query = st.text_input("🔍 Search Inventory", placeholder="Search ID, Tape Code, Type, Purpose, or Occupant...").strip().lower()

            available_statuses = ["empty / idle", "empty", "idle", "available", "ready", "clean"]

            filtered = []
            for t in tanks:
                status_str = str(t.get('status', '')).strip().lower()
                occupant_str = str(t.get('occupant', '')).strip().lower()

                is_available = (status_str in available_statuses) or (not occupant_str or occupant_str in ["empty", "none", "n/a"])

                if availability_filter == "Available / Empty Only" and not is_available:
                    continue
                elif availability_filter == "Occupied / In Use Only" and is_available:
                    continue

                if search_query:
                    searchable_fields = [
                        str(t.get('id', '')), str(t.get('type', '')), str(t.get('location', '')),
                        str(t.get('purpose', '')), str(t.get('occupant', '')), str(t.get('notes', ''))
                    ]
                    if not any(search_query in field.lower() for field in searchable_fields):
                        continue

                filtered.append(t)

            avail_count = sum(
                1 for t in tanks
                if str(t.get('status', '')).strip().lower() in available_statuses
                or not str(t.get('occupant', '')).strip()
                or str(t.get('occupant', '')).strip().lower() in ["empty", "none", "n/a"]
            )
            st.caption(f"Showing **{len(filtered)}** of **{len(tanks)}** containers | 🟢 **{avail_count}** Available / Empty Containers")
            st.markdown("---")

            if not filtered:
                st.warning("No containers match your filter criteria.")
            else:
                cols = st.columns(3)
                for idx, t in enumerate(filtered):
                    tank_id = t['id']
                    curr_occ = t.get('occupant', '')

                    with cols[idx % 3]:
                        with st.container(border=True):
                            if t.get('photo_id'):
                                st.image(f"https://drive.google.com/thumbnail?id={t['photo_id']}&sz=w800", use_container_width=True)

                            st.markdown(f"### 🏷️ `{t['location']}`")
                            st.caption(f"**System ID:** `{tank_id}`")
                            st.write(f"🪣 **Type:** {t['type']}")
                            st.write(f"🎯 **Purpose:** {t['purpose']}")
                            st.write(f"🧪 **Capacity:** {t['capacity']} L | **Status:** `{t['status']}`")

                            if curr_occ:
                                st.write(f"🐟 **Occupant:** `{curr_occ}`")
                            else:
                                st.write("🐟 **Occupant:** *Empty*")

                            if t.get('notes'):
                                st.caption(f"📝 {t['notes']}")

                            st.divider()

                            # UPDATE & DELETE POPOVER
                            with st.popover("⚙️ Update / Remove", use_container_width=True):
                                st.markdown("#### 📝 Edit Details")
                                update_options = ["None (Empty)"]
                                if curr_occ:
                                    update_options.append(f"{curr_occ} (Current Occupant)")

                                for b in available_breeders:
                                    opt_str = f"{b['id']} | {b.get('variety', 'Betta')} ({b.get('sex', 'Unknown')})"
                                    if opt_str not in update_options:
                                        update_options.append(opt_str)

                                selected_occ_opt = st.selectbox(
                                    "Current Occupant",
                                    options=update_options,
                                    index=1 if curr_occ else 0,
                                    key=f"occ_sel_{tank_id}"
                                )

                                status_options = ["Empty / Idle", "Active", "Cleaning / Quarantine", "Retired"]
                                curr_status = str(t.get('status', 'Empty / Idle')).title()
                                status_index = next((i for i, s in enumerate(status_options) if s.lower() in curr_status.lower()), 0)

                                new_status = st.selectbox(
                                    "Status",
                                    status_options,
                                    index=status_index,
                                    key=f"status_{tank_id}"
                                )

                                curr_p_idx = get_purpose_index(t.get('purpose', ''))

                                new_purpose = st.selectbox(
                                    "Container Purpose",
                                    CONTAINER_PURPOSES,
                                    index=curr_p_idx,
                                    key=f"purpose_{tank_id}"
                                )

                                new_notes = st.text_area("Notes", value=t.get('notes', ''), key=f"notes_{tank_id}")

                                if st.button("💾 Save Changes", key=f"save_{tank_id}", type="primary", use_container_width=True):
                                    if selected_occ_opt == "None (Empty)":
                                        final_occ = ""
                                    elif "(Current Occupant)" in selected_occ_opt:
                                        final_occ = curr_occ
                                    else:
                                        final_occ = selected_occ_opt.split(" | ")[0]

                                    with st.spinner("Saving changes to sheet..."):
                                        if update_tank_status(tank_id, new_status, new_purpose, final_occ, new_notes):
                                            st.cache_data.clear()  # Invalidate Streamlit sheet cache
                                            st.success("Updated successfully!")
                                            st.rerun()

                                # DELETE / REMOVE SECTION
                                st.divider()
                                st.markdown("#### 🗑️ Remove Container")

                                delete_reason = st.selectbox(
                                    "Reason for Removal",
                                    [
                                        "Error in Registration / Duplicate Entry",
                                        "Damaged / Cracked / Leaking",
                                        "Lost / Misplaced Container",
                                        "Permanently Retired from Service"
                                    ],
                                    key=f"del_reason_{tank_id}"
                                )

                                confirm_delete = st.checkbox(
                                    "I confirm I want to permanently delete this container.",
                                    key=f"del_confirm_{tank_id}"
                                )

                                if st.button(
                                    "🔥 Delete Container Permanently",
                                    key=f"del_btn_{tank_id}",
                                    type="secondary",
                                    disabled=not confirm_delete,
                                    use_container_width=True
                                ):
                                    with st.spinner("Deleting record..."):
                                        if delete_tank(tank_id):
                                            st.cache_data.clear()  # Invalidate Streamlit sheet cache
                                            st.success(f"Container {t['location']} removed successfully!")
                                            st.rerun()
