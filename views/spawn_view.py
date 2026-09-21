# views/spawn_view.py
import datetime
import streamlit as st
from modules.spawn_manager import (
    get_active_pairings_with_details,
    mark_pairing_success_pending,
    mark_free_swimming,
    mark_pairing_failed
)

def render_active_pairings_view():
    st.title("🐟 Currently Paired Fish")

    active_pairs = get_active_pairings_with_details()

    if not active_pairs:
        st.info("No fish are currently in active pairing.")
        return

    for item in active_pairs:
        spawn = item["spawn"]
        male = item["male"]
        female = item["female"]

        spawn_id = spawn["id"]
        status = spawn["status"]
        pairing_date = spawn["pairing_date"]

        # Calculate days together
        try:
            days_paired = (datetime.date.today() - datetime.date.fromisoformat(pairing_date)).days
        except Exception:
            days_paired = 0

        with st.container(border=True):
            # Banner Header
            st.markdown(f"### 🧪 Spawn Record: `{spawn_id}`")
            st.caption(f"📍 **Tank:** {spawn['tank']} | 📅 **Paired Date:** {pairing_date} ({days_paired} days active) | 🏷️ **Status:** `{status}`")

            if spawn.get("line_goal"):
                st.write(f"🎯 **Goal:** {spawn['line_goal']}")

            st.divider()

            # Side-by-side Parent Display
            col_male, col_female = st.columns(2)

            # MALE BREEDER CARD
            with col_male:
                st.markdown("#### ♂️ Male Breeder")
                if male.get("image_url"):
                    st.image(male["image_url"], use_container_width=True)
                
                st.markdown(f"**ID:** `{male.get('id', spawn['male_id'])}`")
                st.markdown(f"**Variety:** {male.get('variety', 'N/A')}")
                st.markdown(f"**Grade:** `{male.get('grade', 'N/A')}`")

            # FEMALE BREEDER CARD
            with col_female:
                st.markdown("#### ♀️ Female Breeder")
                if female.get("image_url"):
                    st.image(female["image_url"], use_container_width=True)

                st.markdown(f"**ID:** `{female.get('id', spawn['female_id'])}`")
                st.markdown(f"**Variety:** {female.get('variety', 'N/A')}")
                st.markdown(f"**Grade:** `{female.get('grade', 'N/A')}`")

            # Action Controls
            st.divider()
            col_a, col_b, col_c = st.columns(3)

            with col_a:
                if status == "In Pairing":
                    if st.button("🥚 Eggs Dropped", key=f"egg_{spawn_id}"):
                        mark_pairing_success_pending(spawn_id)
                        st.success("Updated status to Pending (Success)!")
                        st.rerun()

            with col_b:
                with st.popover("🏊 Mark Free Swimming"):
                    batch_name = st.text_input("Batch Name", key=f"batch_{spawn_id}")
                    fry_cnt = st.number_input("Estimated Fry", min_value=1, value=50, key=f"cnt_{spawn_id}")
                    if st.button("Confirm Free Swim", key=f"confirm_swim_{spawn_id}"):
                        if batch_name:
                            mark_free_swimming(spawn_id, batch_name, fry_cnt)
                            st.rerun()

            with col_c:
                with st.popover("❌ Mark Failed"):
                    reason = st.text_input("Reason for Failure", key=f"fail_{spawn_id}")
                    if st.button("Confirm Failure", key=f"confirm_fail_{spawn_id}"):
                        mark_pairing_failed(spawn_id, reason)
                        st.rerun()
