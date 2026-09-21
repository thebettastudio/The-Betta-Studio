# views/spawn_view.py
import datetime
import streamlit as st
from modules.spawn_manager import (
    get_available_breeders,
    get_active_pairings,
    get_all_spawns,
    create_new_spawn,
    mark_pairing_success_pending,
    mark_free_swimming,
    mark_pairing_failed
)

def render_spawn_page():
    st.title("🧬 Pair & Spawn Tracker")

    tab1, tab2, tab3 = st.tabs([
        "💞 Active Pairings", 
        "➕ Start New Pairing", 
        "📜 All Spawn History"
    ])

    # ==========================================
    # TAB 1: ACTIVE PAIRINGS DASHBOARD
    # ==========================================
    with tab1:
        st.subheader("Currently Active Pairings")
        
        if st.button("🔄 Refresh Active Pairs"):
            st.rerun()

        active_spawns = get_active_pairings()

        if not active_spawns:
            st.info("No active pairings at the moment. Start a new pair in the 'Start New Pairing' tab!")
        else:
            cols = st.columns(2)
            for idx, spawn in enumerate(active_spawns):
                spawn_id = spawn["id"]
                pairing_dt = datetime.date.fromisoformat(spawn["pairing_date"]) if spawn["pairing_date"] else datetime.date.today()
                days_in_pair = (datetime.date.today() - pairing_dt).days

                with cols[idx % 2]:
                    with st.container(border=True):
                        # Card Header & Status Badge
                        st.markdown(f"### 🏷️ {spawn_id}")
                        status = spawn["status"]
                        status_color = "orange" if status == "In Pairing" else "blue"
                        st.markdown(f"**Status:** :{status_color}[{status}] | **Tank:** `{spawn['tank']}`")
                        
                        st.write(f"**Male ID:** {spawn['male_id']}  |  **Female ID:** {spawn['female_id']}")
                        st.caption(f"📅 **Paired on:** {spawn['pairing_date']} ({days_in_pair} days ago)")
                        
                        if spawn.get("line_goal"):
                            st.write(f"**Goal:** {spawn['line_goal']}")
                        if spawn.get("notes"):
                            st.info(f"**Notes:** {spawn['notes']}")

                        st.divider()
                        st.markdown("##### ⚡ Quick Actions & Lifecycle")

                        # ACTION 1: Eggs Dropped -> Pending
                        if status == "In Pairing":
                            if st.button("🥚 Eggs Dropped (Mark Pending)", key=f"btn_pending_{spawn_id}", use_container_width=True):
                                with st.spinner("Updating status..."):
                                    mark_pairing_success_pending(spawn_id)
                                st.success("Status updated to Pending (Success)!")
                                st.rerun()

                        # ACTION 2: Fry Free Swimming
                        with st.expander("🏊 Mark Free Swimming (Success)", expanded=False):
                            with st.form(key=f"form_free_swim_{spawn_id}"):
                                batch_name = st.text_input("Batch / Spawn Name", placeholder="e.g. BATCH-2026-A1")
                                est_fry = st.number_input("Estimated Fry Count", min_value=1, value=50, step=5)
                                submit_swim = st.form_submit_button("Confirm Free Swimming")

                                if submit_swim:
                                    if not batch_name:
                                        st.error("Please provide a batch name.")
                                    else:
                                        with st.spinner("Finalizing spawn..."):
                                            mark_free_swimming(spawn_id, batch_name, est_fry)
                                        st.success(f"Spawn {spawn_id} recorded as Free Swimming! Parents returned to Available.")
                                        st.rerun()

                        # ACTION 3: Mark Failed
                        with st.expander("❌ Mark Pairing Failed", expanded=False):
                            with st.form(key=f"form_fail_{spawn_id}"):
                                reason = st.selectbox("Failure Reason", [
                                    "Aggression / Fighting",
                                    "Eaten Eggs",
                                    "Infertility / Unhatched Eggs",
                                    "Fungal / Mold Infection",
                                    "Other"
                                ])
                                submit_fail = st.form_submit_button("Confirm Failure", type="primary")

                                if submit_fail:
                                    with st.spinner("Logging failure..."):
                                        mark_pairing_failed(spawn_id, reason)
                                    st.warning(f"Pairing {spawn_id} marked as Failed. Parents returned to Available.")
                                    st.rerun()

    # ==========================================
    # TAB 2: START NEW PAIRING
    # ==========================================
    with tab2:
        st.subheader("Pair Male & Female Breeder")
        
        males, females = get_available_breeders()

        if not males or not females:
            st.warning("You need at least one Available/Conditioning Male AND Female breeder to create a pair.")
        else:
            with st.form("new_pairing_form", clear_on_submit=True):
                col1, col2 = st.columns(2)

                with col1:
                    male_options = {m["label"]: m["id"] for m in males}
                    selected_male_label = st.selectbox("Select Male Breeder", list(male_options.keys()))
                    male_id = male_options[selected_male_label]

                    tank = st.text_input("Tank Location", placeholder="e.g. Tank A1")

                with col2:
                    female_options = {f["label"]: f["id"] for f in females}
                    selected_female_label = st.selectbox("Select Female Breeder", list(female_options.keys()))
                    female_id = female_options[selected_female_label]

                    line_goal = st.text_input("Line / Breeding Goal", placeholder="e.g. Improve caudal spread & clean dorsal")

                notes = st.text_area("Pairing Notes", placeholder="e.g. Both pre-conditioned for 7 days on bloodworms")
                submit_pair = st.form_submit_button("💞 Initiate Pairing")

            if submit_pair:
                if not tank:
                    st.error("Please specify a Tank Location.")
                else:
                    with st.spinner("Setting up pairing..."):
                        spawn_id = create_new_spawn(male_id, female_id, tank, line_goal, notes)
                    st.success(f"Pairing initiated! Spawn ID: **{spawn_id}**")
                    st.rerun()

    # ==========================================
    # TAB 3: ALL SPAWN HISTORY
    # ==========================================
    with tab3:
        st.subheader("All Spawn Records")
        spawns = get_all_spawns()
        if spawns:
            st.dataframe(spawns, use_container_width=True)
        else:
            st.info("No spawn history recorded yet.")
