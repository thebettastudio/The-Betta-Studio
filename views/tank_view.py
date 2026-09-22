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
                occupant = st.text_input("Current Occupant ID (Optional)", placeholder="e.g. BRD-M-20260920 or Spawn #001")
                photo_file = st.file_uploader("📷 Container Photo (Optional)", type=["jpg", "jpeg", "png"])
                notes = st.text_area("Notes / Setup Details", placeholder="e.g. Almond leaf tea water, sponge filter installed")

            submit = st.form_submit_button("🏷️ Register Container & Generate Tape Tag")

        if submit:
            final_type = custom_type.strip() if selected_type == "➕ Other / Custom Container..." else selected_type

            if not final_type:
                st.error("Please specify a container type.")
            else:
                with st.spinner("Generating Tape Tag & registering container..."):
                    res = register_tank(
                        tank_type=final_type,
                        capacity_liters=capacity,
                        purpose=purpose,
                        photo_file=photo_file,
                        current_occupant=occupant,
                        notes=notes
                    )

                st.success("Container Successfully Registered!")
                
                # Display prominent tape code box to write on physical tank
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
            search_query = st.text_input("🔍 Search by ID, Tape Code, Type, Purpose, or Occupant:", "").strip().lower()

            filtered = [
                t for t in tanks
                if search_query in t['id'].lower()
                or search_query in t['type'].lower()
                or search_query in t['location'].lower()
                or search_query in t['purpose'].lower()
                or search_query in t['occupant'].lower()
            ]

            cols = st.columns(3)
            for idx, t in enumerate(filtered):
                tank_id = t['id']
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
                            
                            try:
                                curr_p_idx = CONTAINER_PURPOSES.index(t['purpose'])
                            except ValueError:
                                curr_p_idx = 0

                            new_purpose = st.selectbox(
                                "Container Purpose",
                                CONTAINER_PURPOSES,
                                index=curr_p_idx,
                                key=f"purpose_{tank_id}"
                            )
                            new_occ = st.text_input("Current Occupant ID", value=t['occupant'], key=f"occ_{tank_id}")
                            new_notes = st.text_area("Notes", value=t['notes'], key=f"notes_{tank_id}")

                            if st.button("Save Changes", key=f"save_{tank_id}", type="primary"):
                                if update_tank_status(tank_id, new_status, new_purpose, new_occ, new_notes):
                                    st.success("Updated!")
                                    st.rerun()
