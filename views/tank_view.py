# views/tank_view.py
import streamlit as st
from modules.tank_registry import (
    register_tank,
    get_all_tanks,
    update_tank_status
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
            final_type = custom_type.strip() if selected_type == "➕ Other / Custom Container..." else selected_type
            occupant_id = "" if selected_occupant == "None (Empty)" else selected_occupant.split(" | ")[0]

            if not final_type:
                st.error("Please specify a container type.")
            else:
                with st.spinner("Generating Tape Tag & registering container..."):
                    res = register_tank(
                        tank_type=final_type,
                        capacity_liters=capacity,
                        purpose=purpose,
                        photo_file=photo_file,
                        current_occupant=occupant_id,
                        notes=notes
                    )

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
            st.rerun()

        tanks = get_all_tanks()
        if not tanks:
            st.info("No containers registered yet.")
        else:
            # Availability & Search Filters
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
                            # Display photo if uploaded
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

                            # Update Container Popover
                            with st.popover("⚙️ Update Container", use_container_width=True):
                                # Dynamic Occupant Dropdown (includes current occupant + unassigned fish)
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

                                new_status = st.selectbox(
                                    "Status",
                                    ["Active", "Cleaning / Quarantine", "Empty / Idle", "Retired"],
                                    index=0 if curr_occ else 2,
                                    key=f"status_{tank_id}"
                                )
                                
                                try:
                                    curr_p_idx = CONTAINER_PURPOSES.index(t['purpose'])
                                except (ValueError, KeyError):
                                    curr_p_idx = 0

                                new_purpose = st.selectbox(
                                    "Container Purpose",
                                    CONTAINER_PURPOSES,
                                    index=curr_p_idx,
                                    key=f"purpose_{tank_id}"
                                )

                                new_notes = st.text_area("Notes", value=t.get('notes', ''), key=f"notes_{tank_id}")

                                if st.button("Save Changes", key=f"save_{tank_id}", type="primary"):
                                    # Derive final occupant ID string
                                    if selected_occ_opt == "None (Empty)":
                                        final_occ = ""
                                    elif "(Current Occupant)" in selected_occ_opt:
                                        final_occ = curr_occ
                                    else:
                                        final_occ = selected_occ_opt.split(" | ")[0]

                                    if update_tank_status(tank_id, new_status, new_purpose, final_occ, new_notes):
                                        st.success("Updated!")
                                        st.rerun()
