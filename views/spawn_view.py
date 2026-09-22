# views/spawn_view.py
import re
import datetime
import streamlit as st
import pandas as pd
from modules.spawn_manager import (
    get_available_breeders,
    get_available_spawning_tanks,
    get_all_spawns,
    get_active_pairings_with_details,
    create_new_spawn,
    mark_pairing_success_pending,
    mark_free_swimming,
    mark_pairing_failed,
    update_spawn_details,
    format_spawns_sheet,
    generate_short_spawn_id,
    calculate_child_generation,
    get_breeder_details_map
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
        
        col_ref, col_fmt = st.columns([1, 1])
        with col_ref:
            if st.button("🔄 Refresh Active Pairs", key="btn_refresh_spawns", use_container_width=True):
                st.rerun()
        with col_fmt:
            if st.button("🎨 Format Spawns Sheet", key="btn_format_spawns", use_container_width=True):
                with st.spinner("Applying sheet styling..."):
                    format_spawns_sheet()
                st.success("Sheet styling applied successfully!")

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
                line_code = spawn.get("line_code", "N/A")
                generation = spawn.get("generation", "N/A")

                try:
                    days_paired = (datetime.date.today() - datetime.date.fromisoformat(pairing_date)).days
                except Exception:
                    days_paired = 0

                with st.container(border=True):
                    col_title, col_edit = st.columns([4, 1])
                    with col_title:
                        st.markdown(f"### 🧪 Spawn: `{spawn_id}` | Line: `{line_code}` (`{generation}`)")
                    with col_edit:
                        # Edit details popover
                        with st.popover("✏️ Edit Spawn", use_container_width=True):
                            st.write(f"**Edit Spawn {spawn_id}**")
                            edit_goal = st.text_input("Line Goal", value=spawn.get("line_goal", ""), key=f"edit_goal_{spawn_id}")
                            edit_notes = st.text_area("Notes", value=spawn.get("notes", ""), key=f"edit_notes_{spawn_id}")
                            if st.button("Save Changes", key=f"save_edit_{spawn_id}"):
                                if update_spawn_details(spawn_id, line_goal=edit_goal, notes=edit_notes):
                                    st.success("Updated successfully!")
                                    st.rerun()
                                else:
                                    st.error("Failed to update spawn.")

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
                        st.markdown(f"**Line:** `{male.get('line_code', 'UNK')}` (`{male.get('generation', 'P1')}`)")

                    # --- Column 2: Male Picture ---
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
                        st.markdown(f"**Line:** `{female.get('line_code', 'UNK')}` (`{female.get('generation', 'P1')}`)")

                    # --- Column 4: Female Picture ---
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
        available_tanks = get_available_spawning_tanks()
        breeders_map = get_breeder_details_map()

        if not males or not females:
            st.warning("⚠️ You need at least one Available/Conditioning Male AND Female breeder to create a pair.")
        else:
            col1, col2 = st.columns(2)

            with col1:
                male_options = {m["label"]: m["id"] for m in males}
                selected_male_label = st.selectbox("Select Male Breeder", list(male_options.keys()))
                male_id = male_options[selected_male_label]

                if available_tanks:
                    tank_options = {t["label"]: t["id"] for t in available_tanks}
                    selected_tank_label = st.selectbox("Select Spawning Tank", list(tank_options.keys()))
                    tank_location = tank_options[selected_tank_label]
                else:
                    st.error("⚠️ No available Spawning Tanks. Free up a tank or mark one as Available.")
                    tank_location = None

            with col2:
                female_options = {f["label"]: f["id"] for f in females}
                selected_female_label = st.selectbox("Select Female Breeder", list(female_options.keys()))
                female_id = female_options[selected_female_label]

                line_goal = st.text_input("Line / Breeding Goal", placeholder="e.g. Improve caudal spread & clean dorsal")

            # Dynamic Preview Box for Line, Generation, and Spawn ID
            if male_id and female_id:
                male_info = breeders_map.get(male_id, {})
                female_info = breeders_map.get(female_id, {})

                preview_line, preview_gen = calculate_child_generation(
                    male_gen=male_info.get("generation"),
                    female_gen=female_info.get("generation"),
                    male_line=male_info.get("line_code"),
                    female_line=female_info.get("line_code")
                )
                preview_spawn_id = generate_short_spawn_id()

                st.info(
                    f"📋 **Next Spawn ID:** `{preview_spawn_id}` | "
                    f"🧬 **Target Line:** `{preview_line}` | "
                    f"🏷️ **Resulting Generation:** `{preview_gen}`"
                )

            notes = st.text_area("Pairing Notes", placeholder="e.g. Both pre-conditioned for 7 days on bloodworms")
            
            submit_pair = st.button("💞 Initiate Pairing", disabled=not available_tanks, type="primary")

            if submit_pair:
                if not tank_location:
                    st.error("Please select a valid Spawning Tank Location.")
                else:
                    with st.spinner("Setting up pairing..."):
                        spawn_id, line_code, child_gen = create_new_spawn(
                            male_id, female_id, tank_location, line_goal, notes
                        )
                    st.success(
                        f"Pairing initiated! Spawn ID: **{spawn_id}** | Line: **{line_code}** ({child_gen}) assigned to Tank **{tank_location}**"
                    )
                    st.rerun()

    # ==========================================
    # TAB 3: ALL SPAWN HISTORY
    # ==========================================
    with tab3:
        st.subheader("All Spawn Records")
        spawns = get_all_spawns()
        if spawns:
            df = pd.DataFrame(spawns)
            
            if "row_index" in df.columns:
                df = df.drop(columns=["row_index"])

            # Clean column headers for display
            df.columns = [col.replace("_", " ").title() for col in df.columns]

            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No spawn history recorded yet.")
