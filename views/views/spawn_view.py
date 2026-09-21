import streamlit as st
from modules.spawn_manager import (
    get_available_breeders,
    create_new_spawn,
    mark_pairing_failed,
    mark_pairing_success_pending,
    mark_free_swimming,
    get_all_spawns
)

def render_spawn_page():
    st.header("🐟 Pair & Spawn Tracker")

    tab1, tab2 = st.tabs(["➕ Start New Spawn", "📊 Active Spawns & Lifecycle"])

    # --- TAB 1: CREATE NEW SPAWN ---
    with tab1:
        st.subheader("Start a New Pairing")
        males, females = get_available_breeders()

        if not males or not females:
            st.warning("⚠️ You need at least 1 Available Male and 1 Available Female in the Breeders registry.")
        else:
            with st.form("new_spawn_form"):
                col1, col2 = st.columns(2)
                with col1:
                    male_opt = st.selectbox(
                        "Select Male Sire:",
                        options=males,
                        format_func=lambda x: x['label']
                    )
                with col2:
                    female_opt = st.selectbox(
                        "Select Female Dam:",
                        options=females,
                        format_func=lambda x: x['label']
                    )

                tank_location = st.text_input("Tank / Pairing Unit ID", value="Tank-B01")
                line_goal = st.text_area("Genetics / Line Goal", placeholder="Improve tail spread, iridescence...")

                if st.form_submit_button("🚀 Start Pairing"):
                    spawn_id = create_new_spawn(
                        male_breeder_id=male_opt['id'],
                        female_breeder_id=female_opt['id'],
                        tank_location=tank_location,
                        line_goal=line_goal
                    )
                    st.success(f"Spawn **{spawn_id}** created! Both parents set to 'In Pairing'.")
                    st.rerun()

    # --- TAB 2: MANAGE ACTIVE SPAWNS ---
    with tab2:
        st.subheader("Manage Active Spawns")
        spawns = get_all_spawns()

        if not spawns:
            st.info("No active spawns recorded yet.")
        else:
            selected_spawn = st.selectbox(
                "Select Spawn to Update:",
                options=spawns,
                format_func=lambda x: f"{x['id']} | Status: {x['status']} | Tank: {x['tank']}"
            )

            status = selected_spawn['status']
            spawn_id = selected_spawn['id']

            st.divider()
            st.write(f"**Spawn ID:** `{spawn_id}`")
            st.write(f"**Sire:** `{selected_spawn['male_id']}` | **Dam:** `{selected_spawn['female_id']}`")
            st.write(f"**Current Status:** `{status}`")

            # --- LIFECYCLE CONTROLS ---
            if status == "In Pairing":
                col_pass, col_fail = st.columns(2)

                with col_pass:
                    st.success("Eggs Dropped")
                    if st.button("Mark Eggs Dropped (Pending Success)"):
                        mark_pairing_success_pending(spawn_id)
                        st.success("Status updated to Pending (Success)!")
                        st.rerun()

                with col_fail:
                    st.error("Pairing Failed")
                    fail_reason = st.selectbox("Reason:", [
                        "Male ate eggs / nest destroyed",
                        "Female aggressive / Injured",
                        "No eggs dropped / Unresponsive",
                        "Water quality / Fungus on eggs"
                    ])
                    if st.button("Log Failure & Reset Parents"):
                        mark_pairing_failed(spawn_id, fail_reason)
                        st.warning("Spawn logged as Failed. Parents reset to Available.")
                        st.rerun()

            elif status == "Pending (Success)":
                st.subheader("🐣 Fry Reached Free Swimming Stage")
                with st.form("free_swim_form"):
                    batch_name = st.text_input("Assign Batch Name:", placeholder="e.g. AVATAR-2026-BATCH-1")
                    fry_count = st.number_input("Estimated Fry Count:", min_value=1, value=50)

                    if st.form_submit_button("Register Batch Name"):
                        if not batch_name:
                            st.error("Please enter a batch name.")
                        else:
                            mark_free_swimming(spawn_id, batch_name, fry_count)
                            st.balloons()
                            st.success(f"Batch **{batch_name}** is officially registered!")
                            st.rerun()

            elif status == "Free Swimming":
                st.success(f"🎉 Free Swimming Stage Active! Batch Name: **{selected_spawn.get('batch_name', 'N/A')}**")
            elif status == "Failed":
                st.error(f"❌ Pairing Failed. Reason: {selected_spawn.get('failure_reason', 'N/A')}")
