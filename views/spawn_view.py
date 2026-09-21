import re
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

def display_breeder_image(image_url: str, gender_label: str = "Breeder"):
    """
    Sources and renders breeder images as styled HTML.
    Forces image styling to expand and fit 100% of its parent column width.
    """
    if not image_url or not isinstance(image_url, str):
        st.markdown(
            f"""
            <div style="
                border: 2px dashed #2A303F; 
                border-radius: 8px; 
                padding: 12px; 
                text-align: center; 
                background-color: #1A1D24; 
                margin-bottom: 8px;
                width: 100%;">
                <span style="font-size: 20px;">🐟</span><br/>
                <span style="color: #888888; font-size: 11px; font-weight: 500;">No {gender_label} Image</span>
            </div>
            """, 
            unsafe_allow_html=True
        )
        return

    url = image_url.strip()

    # Prepend protocol if missing but contains a drive domain
    if not url.startswith("http://") and not url.startswith("https://") and "drive.google.com" in url:
        url = "https://" + url

    # Automatically extract file ID from Google Drive URLs or raw IDs
    file_id = None
    if "drive.google.com/file/d/" in url:
        file_id = url.split("/d/")[1].split("/")[0].split("?")[0]
    elif "drive.google.com/open?id=" in url or "id=" in url:
        file_id = url.split("id=")[1].split("&")[0]
    elif re.match(r'^[a-zA-Z0-9_-]{25,50}$', url):
        file_id = url

    # If a Google Drive ID is detected, convert it to a direct thumbnail link
    if file_id:
        url = f"https://drive.google.com/thumbnail?id={file_id}&sz=w800"

    # Render image styled to fill 100% width of the column
    if url.startswith("http://") or url.startswith("https://"):
        st.markdown(
            f'<img src="{url}" class="spawn-card-img" style="width: 100%; max-width: 100%; height: auto; aspect-ratio: 1/1; object-fit: cover; border-radius: 8px;" alt="{gender_label} Betta" />',
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            f"""
            <div style="
                border: 2px dashed #2A303F; 
                border-radius: 8px; 
                padding: 12px; 
                text-align: center; 
                background-color: #1A1D24; 
                margin-bottom: 8px;
                width: 100%;">
                <span style="font-size: 20px;">🖼️</span><br/>
                <span style="color: #888888; font-size: 11px; font-weight: 500;">Invalid Source</span>
            </div>
            """, 
            unsafe_allow_html=True
        )


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

                    # 4-Column Layout: Male Info (Col 1) | Male Img (Col 2) | Female Info (Col 3) | Female Img (Col 4)
                    col_m_info, col_m_img, col_f_info, col_f_img = st.columns([2, 1.5, 2, 1.5])

                    # --- Column 1: Male Details ---
                    with col_m_info:
                        st.markdown("#### ♂️ Male Breeder")
                        st.markdown(f"**ID:** `{male.get('id', spawn['male_id'])}`")
                        st.markdown(f"**Variety:** {male.get('variety', 'N/A')}")
                        st.markdown(f"**Grade:** `{male.get('grade', 'N/A')}`")

                    # --- Column 2: Male Picture (Fills column width) ---
                    with col_m_img:
                        male_img_src = (
                            male.get("photo_id") or 
                            male.get("image_url") or 
                            male.get("image") or 
                            male.get("photo") or 
                            ""
                        )
                        display_breeder_image(male_img_src, gender_label="Male")

                    # --- Column 3: Female Details ---
                    with col_f_info:
                        st.markdown("#### ♀️ Female Breeder")
                        st.markdown(f"**ID:** `{female.get('id', spawn['female_id'])}`")
                        st.markdown(f"**Variety:** {female.get('variety', 'N/A')}")
                        st.markdown(f"**Grade:** `{female.get('grade', 'N/A')}`")

                    # --- Column 4: Female Picture (Fills column width) ---
                    with col_f_img:
                        female_img_src = (
                            female.get("photo_id") or 
                            female.get("image_url") or 
                            female.get("image") or 
                            female.get("photo") or 
                            ""
                        )
                        display_breeder_image(female_img_src, gender_label="Female")

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
