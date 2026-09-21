import datetime
import streamlit as st
from modules.spawn_manager import (
    get_available_breeders,
    get_all_spawns,
    get_active_pairings_with_details,
    create_new_spawn,
    mark_pairing_success_pending,
    mark_free_swimming,
    mark_pairing_failed
)

def display_breeder_image(image_url: str):
    """
    Safely renders breeder images.
    Prevents MediaFileStorageError when image_url is missing, a raw Google Drive ID, 
    or an invalid file path.
    """
    if not image_url or not isinstance(image_url, str):
        st.info("🖼️ No image available")
        return

    url = image_url.strip()

    # Convert raw Google Drive view links to direct viewable web URLs
    if "drive.google.com/file/d/" in url:
        file_id = url.split("/d/")[1].split("/")[0]
        url = f"https://drive.google.com/uc?id={file_id}"
    elif "drive.google.com/open?id=" in url:
        file_id = url.split("id=")[1].split("&")[0]
        url = f"https://drive.google.com/uc?id={file_id}"

    # Only pass to st.image if it is a valid web URL
    if url.startswith("http://") or url.startswith("https://"):
        try:
            st.image(url, use_container_width=True)
        except Exception:
            st.warning("⚠️ Image could not be loaded")
    else:
        st.caption("ℹ️ Invalid image link")


def render_spawn_page():
    st.title("🧬 Pair & Spawn Tracker")

    tab1, tab2, tab3 = st.tabs([
        "💞 Active Pairings", 
        "➕ Start New Pairing", 
        "📜 All Spawn History"
    ])

    # ==========================================
    # TAB 1: ACTIVE PAIRINGS
    # ==========================================
    with tab1:
        st.subheader("Currently Active Pairings")
        
        if st.button("🔄 Refresh Active Pairs", key="btn_refresh_spawns"):
            st.rerun()

        active_pairs = get_active_pairings_with_details()

        if not active_pairs:
            st.info("No active pairings at the moment. Start a new pair in the 'Start New Pairing' tab!")
        else:
            for item in active_pairs:
                spawn = item["spawn"]
                male = item["male"]
                female = item["female"]

                spawn_id = spawn["id"]
                status = spawn["status"]
                pairing_date = spawn["pairing_date"]

                try:
                    days_paired = (datetime.date.today() - datetime.date.fromisoformat(pairing_date)).days
                except Exception:
                    days_paired = 0

                with st.container(border=True):
                    st.markdown(f"### 🧪 Spawn: `{spawn_id}`")
                    st.caption(f"📍 **Tank:** {spawn['tank']} | 📅 **Paired:** {pairing_date} ({days_paired} days ago) | 🏷️ **Status:** `{status}`")

                    if spawn.get("line_goal"):
                        st.write(f"🎯 **Goal:** {spawn['line_goal']}")
                    if spawn.get("notes"):
                        st.info(f"**Notes:** {spawn['notes']}")

                    st.divider()

                    # Side-by-side Breeder Cards
                    col_male, col_female = st.columns(2)

                    with col_male:
                        st.markdown("#### ♂️ Male Breeder")
                        display_breeder_image(male.get("image_url", ""))
                        st.markdown(f"**ID:** `{male.get('id', spawn['male_id'])}`")
                        st.markdown(f"**Variety:** {male.get('variety', 'N/A')}")
                        st.markdown(f"**Grade:** `{male.get('grade', 'N/A')}`")

                    with col_female:
                        st.markdown("#### ♀️ Female Breeder")
                        display_breeder_image(female.get("image_url", ""))
                        st.markdown(f"**ID:** `{female.get('id', spawn['female_id'])}`")
                        st.markdown(f"**Variety:** {female.get('variety', 'N/A')}")
                        st.markdown(f"**Grade:** `{female.get('grade', 'N/A')}`")

                    st.divider()

                    # Quick Controls
                    col_a, col_b, col_c = st.columns(3)

                    with col_a:
                        if status == "In Pairing":
                            if st.button("🥚 Eggs Dropped", key=f"egg_{spawn_id}", use_container_width=True):
                                mark_pairing_success_pending(spawn_id)
                                st.success("Status updated to Pending (Success)!")
                                st.rerun()

                    with col_b:
                        with st.popover("🏊 Mark Free Swimming", use_container_width=True):
                            batch_name = st.text_input("Batch Name", key=f"batch_{spawn_id}")
                            fry_cnt = st.number_input("Estimated Fry", min_value=1, value=50, key=f"cnt_{spawn_id}")
                            if st.button("Confirm Free Swim", key=f"confirm_swim_{spawn_id}"):
                                if batch_name:
                                    mark_free_swimming(spawn_id, batch_name, fry_cnt)
                                    st.rerun()
                                else:
                                    st.error("Please enter a batch name.")

                    with col_c:
                        with st.popover("❌ Mark Failed", use_container_width=True):
                            reason = st.selectbox("Reason", [
                                "Aggression / Fighting",
                                "Eaten Eggs",
                                "Infertility / Unhatched Eggs",
                                "Fungal / Mold Infection",
                                "Other"
                            ], key=f"fail_reason_{spawn_id}")
                            if st.button("Confirm Failure", key=f"confirm_fail_{spawn_id}", type="primary"):
                                mark_pairing_failed(spawn_id, reason)
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
