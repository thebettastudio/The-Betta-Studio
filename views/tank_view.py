# views/tank_view.py
import streamlit as st
from modules.tank_registry import (
    register_tank,
    get_all_tanks,
    update_tank_status
)

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

def render_tank_page():
    st.title("🪣 Tank & Container Registry")

    tab1, tab2 = st.tabs(["➕ Register Container", "🗃️ Container Inventory"])

    # TAB 1: REGISTER CONTAINER
    with tab1:
        st.subheader("Register New Tank or Container")

        with st.form("tank_register_form"):
            col1, col2 = st.columns(2)

            with col1:
                selected_type = st.selectbox("Container / Tank Type", DEFAULT_CONTAINER_TYPES)
                
                # Custom input trigger
                custom_type = ""
                if selected_type == "➕ Other / Custom Container...":
                    custom_type = st.text_input("Enter Custom Container Name", placeholder="e.g. 20L Storage Box, Styro Box, etc.")

                location_code = st.text_input("Tape / Location Tag", placeholder="e.g. GO-01, ST-01, B6L-03, Rack 1")
                capacity = st.number_input("Capacity (Liters)", min_value=0.1, max_value=500.0, value=6.0, step=0.5)

            with col2:
                occupant = st.text_input("Current Occupant ID (Optional)", placeholder="e.g. BRD-M-20260920 or Spawn #001")
                notes = st.text_area("Notes / Setup Details", placeholder="e.g. Almond leaf tea water, sponge filter installed")

            submit = st.form_submit_button("🏷️ Register Container")

        if submit:
            # Determine final container type name
            final_type = custom_type.strip() if selected_type == "➕ Other / Custom Container..." else selected_type

            if not final_type:
                st.error("Please specify a container type.")
            elif not location_code:
                st.error("Please provide a Tape Code or Location Tag (e.g. GO-01).")
            else:
                with st.spinner("Registering container..."):
                    res = register_tank(
                        tank_type=final_type,
                        location=location_code,
                        capacity_liters=capacity,
                        current_occupant=occupant,
                        notes=notes
                    )

                st.success(f"Container Registered! Assigned System ID: **{res['tank_id']}**")
                st.info(f"🏷️ **Tape Label Code:** Write `{location_code}` on painter's tape and attach it to your {final_type}.")

    # TAB 2: CONTAINER INVENTORY
    with tab2:
        st.subheader("Container Inventory")
        if st.button("🔄 Refresh Containers"):
            st.rerun()

        tanks = get_all_tanks()
        if not tanks:
            st.info("No containers registered yet.")
        else:
            search_query = st.text_input("🔍 Search by ID, Tape Code, Type, or Occupant:", "").strip().lower()

            filtered = [
                t for t in tanks
                if search_query in t['id'].lower()
                or search_query in t['type'].lower()
                or search_query in t['location'].lower()
                or search_query in t['occupant'].lower()
            ]

            cols = st.columns(3)
            for idx, t in enumerate(filtered):
                tank_id = t['id']
                with cols[idx % 3]:
                    with st.container(border=True):
                        st.markdown(f"### 🏷️ `{t['location']}`")
                        st.caption(f"**System ID:** `{tank_id}`")
                        st.write(f"🪣 **Type:** {t['type']}")
                        st.write(f"🧪 **Capacity:** {t['capacity']} L | **Status:** `{t['status']}`")
                        
                        if t['occupant']:
                            st.write(f"🐟 **Occupant:** `{t['occupant']}`")
                        else:
                            st.write("🐟 **Occupant:** *Empty*")

                        if t['notes']:
                            st.caption(f"📝 {t['notes']}")

                        st.divider()

                        # Quick Update Status Popover
                        with st.popover("⚙️ Update Container", use_container_width=True):
                            new_status = st.selectbox(
                                "Status",
                                ["Active", "Cleaning / Quarantine", "Empty / Idle", "Retired"],
                                key=f"status_{tank_id}"
                            )
                            new_occ = st.text_input("Current Occupant ID", value=t['occupant'], key=f"occ_{tank_id}")
                            new_notes = st.text_area("Notes", value=t['notes'], key=f"notes_{tank_id}")

                            if st.button("Save Changes", key=f"save_{tank_id}", type="primary"):
                                if update_tank_status(tank_id, new_status, new_occ, new_notes):
                                    st.success("Updated!")
                                    st.rerun()
