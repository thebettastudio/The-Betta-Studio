# views/fish_registry_view.py
import datetime
import streamlit as st
import pandas as pd
from modules.fish_manager import (
    get_all_fish,
    register_new_fish,
    promote_fish_to_breeder,
    generate_purchased_fish_id,
    generate_batch_fish_id,
    get_existing_fish_ids
)
from modules.spawn_manager import get_all_spawns, get_breeder_details_map
from views.spawn_view import display_breeder_image

def render_fish_registry_page():
    st.title("🐟 Individual Fish Master Registry")

    tab1, tab2 = st.tabs(["➕ Register Fish", "📋 Master Fish Inventory"])

    # ==========================================
    # TAB 1: REGISTER NEW INDIVIDUAL FISH
    # ==========================================
    with tab1:
        st.subheader("Register Individual Fish")
        
        origin_type = st.radio(
            "Select Origin Type", 
            ["Purchased / External", "Recorded Batch Fry"], 
            horizontal=True,
            key="radio_origin_type"
        )

        existing_ids = get_existing_fish_ids()

        if origin_type == "Purchased / External":
            st.markdown("#### 🛒 Purchased / Imported Fish Details")
            
            col1, col2 = st.columns(2)
            with col1:
                variety = st.text_input("Variety / Type", value="Halfmoon Plakat", help="e.g. Red Dragon HMPK, Blue Rim")
                gender = st.selectbox("Gender", ["Male", "Female", "Unsexed"])
                grade = st.selectbox("Grade", ["Show Grade", "High Grade", "Pet Grade", "Breeder Grade"])
                location = st.text_input("Tank / Jar Location", value="Jar M-01")
            
            with col2:
                seller = st.text_input("Seller / Source", placeholder="e.g. Aquarama Import / Local Breeder")
                purchase_date = st.date_input("Purchase Date", value=datetime.date.today())
                purchase_cost = st.number_input("Purchase Cost", min_value=0.0, value=0.0, step=5.0)
                image_url = st.text_input("Image URL / Google Drive File ID", placeholder="Paste direct link or Drive ID")

            notes = st.text_area("Notes / Characteristics", placeholder="e.g. Strong dorsal, solid iridescence")

            # Dynamic ID Generation Preview
            suggested_id = generate_purchased_fish_id(variety, gender, existing_ids)
            
            st.info(f"🆔 **Assigned Fish ID:** `{suggested_id}` | 🧬 **Lineage:** `Untraceable (P1)`")

            if st.button("💾 Register Purchased Fish", type="primary", use_container_width=True):
                if not variety:
                    st.error("Please specify a variety for the fish.")
                else:
                    fish_payload = {
                        "fish_id": suggested_id,
                        "origin": "Purchased",
                        "batch_id": "N/A",
                        "line_code": "UNK",
                        "generation": "P1",
                        "sire_id": "N/A",
                        "dam_id": "N/A",
                        "gender": gender,
                        "variety": variety,
                        "grade": grade,
                        "image_url": image_url,
                        "location": location,
                        "purchase_date": purchase_date.isoformat(),
                        "seller": seller,
                        "purchase_cost": purchase_cost,
                        "status": "Active",
                        "notes": notes
                    }
                    new_id = register_new_fish(fish_payload)
                    st.success(f"Fish registered successfully with ID: **{new_id}**!")
                    st.rerun()

        else:
            # Recorded Batch Fry Logic
            st.markdown("#### 🐣 Jar Fish from Recorded Batch Spawn")
            
            spawns = get_all_spawns()
            # Filter for successful / free-swimming spawns or active ones
            valid_spawns = [s for s in spawns if s.get("status") in ["Free Swimming", "In Pairing", "Pending (Success)"]]
            
            if not valid_spawns:
                st.warning("⚠️ No recorded spawns found. Register a spawn in the Pair & Spawn Tracker first.")
            else:
                spawn_map = {}
                for s in valid_spawns:
                    label = f"Spawn {s['id']} | Line: {s.get('line_code', 'UNK')} ({s.get('generation', 'F1')}) | Batch: {s.get('batch_name', 'N/A')}"
                    spawn_map[label] = s

                selected_label = st.selectbox("Select Source Spawn Batch", list(spawn_map.keys()))
                selected_spawn = spawn_map[selected_label]

                # Fetch details from parents
                batch_code = selected_spawn.get("batch_name") or f"SP{selected_spawn['id']}"
                sire_id = selected_spawn.get("male_id", "N/A")
                dam_id = selected_spawn.get("female_id", "N/A")
                line_code = selected_spawn.get("line_code", "UNK")
                generation = selected_spawn.get("generation", "F1")

                col1, col2 = st.columns(2)
                with col1:
                    gender = st.selectbox("Gender", ["Unsexed", "Male", "Female"])
                    grade = st.selectbox("Grade", ["High Grade", "Show Grade", "Pet Grade", "Cull"])
                    variety = st.text_input("Variety / Trait Description", value=f"{line_code} Betta")
                
                with col2:
                    location = st.text_input("Jar / Tank Location", value="Jar 01")
                    image_url = st.text_input("Image URL / Google Drive File ID", placeholder="Paste direct link or Drive ID")

                notes = st.text_area("Notes / Growth Observation", placeholder="e.g. First pick from batch, good form")

                # Dynamic Batch ID Preview
                suggested_id = generate_batch_fish_id(batch_code, existing_ids)

                st.info(
                    f"🆔 **Assigned Fish ID:** `{suggested_id}` | "
                    f"🧬 **Line:** `{line_code}` (`{generation}`) | "
                    f"♂️ **Sire:** `{sire_id}` | ♀️ **Dam:** `{dam_id}`"
                )

                if st.button("💾 Register Batch Fry", type="primary", use_container_width=True):
                    fish_payload = {
                        "fish_id": suggested_id,
                        "origin": "Batch Spawn",
                        "batch_id": selected_spawn["id"],
                        "line_code": line_code,
                        "generation": generation,
                        "sire_id": sire_id,
                        "dam_id": dam_id,
                        "gender": gender,
                        "variety": variety,
                        "grade": grade,
                        "image_url": image_url,
                        "location": location,
                        "status": "Jarred",
                        "notes": notes
                    }
                    new_id = register_new_fish(fish_payload)
                    st.success(f"Fry jarred and registered successfully with ID: **{new_id}**!")
                    st.rerun()

    # ==========================================
    # TAB 2: MASTER FISH INVENTORY & PROMOTION
    # ==========================================
    with tab2:
        st.subheader("Master Fish Inventory")
        all_fish = get_all_fish()

        if not all_fish:
            st.info("No fish registered in the inventory yet. Add one in the 'Register Fish' tab!")
        else:
            col_filter1, col_filter2 = st.columns([2, 2])
            with col_filter1:
                search_query = st.text_input("🔍 Search Fish ID / Variety / Line", placeholder="e.g. PUR-HMPK or DRG")
            with col_filter2:
                breeder_filter = st.selectbox("Filter by Role", ["All Fish", "Breeders Only", "Non-Breeders Only"])

            # Filter logic
            filtered_fish = all_fish
            if search_query:
                q = search_query.lower()
                filtered_fish = [
                    f for f in filtered_fish 
                    if q in f["fish_id"].lower() or q in f["variety"].lower() or q in f["line_code"].lower()
                ]

            if breeder_filter == "Breeders Only":
                filtered_fish = [f for f in filtered_fish if f.get("is_breeder")]
            elif breeder_filter == "Non-Breeders Only":
                filtered_fish = [f for f in filtered_fish if not f.get("is_breeder")]

            st.write(f"Showing **{len(filtered_fish)}** fish")

            for fish in filtered_fish:
                fish_id = fish["fish_id"]
                is_breeder = fish.get("is_breeder", False)

                with st.container(border=True):
                    col_img, col_main, col_action = st.columns([1.2, 3, 1.8])

                    with col_img:
                        display_breeder_image(fish.get("image_url", ""), gender_label=fish.get("gender", "Fish"))

                    with col_main:
                        role_badge = "👑 **[ACTIVE BREEDER]**" if is_breeder else "🐟 [Master Inventory]"
                        st.markdown(f"### `{fish_id}` {role_badge}")
                        st.markdown(f"**Variety:** {fish.get('variety', 'N/A')} | **Gender:** `{fish.get('gender', 'N/A')}` | **Grade:** `{fish.get('grade', 'N/A')}`")
                        st.markdown(f"🧬 **Lineage:** `{fish.get('line_code', 'UNK')}` (`{fish.get('generation', 'P1')}`) | **Origin:** `{fish.get('origin', 'Purchased')}`")
                        
                        if fish.get("origin") == "Batch Spawn":
                            st.caption(f"♂️ **Sire:** `{fish.get('sire_id')}` | ♀️ **Dam:** `{fish.get('dam_id')}` | 📦 **Batch:** `{fish.get('batch_id')}`")
                        else:
                            st.caption(f"🛒 **Seller:** {fish.get('seller', 'N/A')} | 📅 **Purchased:** {fish.get('purchase_date', 'N/A')} | 💰 **Cost:** ₱{fish.get('purchase_cost', 0):,.2f}")

                        st.caption(f"📍 **Location:** `{fish.get('location', 'Unassigned')}` | 🏷️ **Status:** `{fish.get('status', 'Active')}`")
                        if fish.get("notes"):
                            st.info(f"**Notes:** {fish['notes']}")

                    with col_action:
                        st.markdown("#### Actions")
                        if not is_breeder:
                            if st.button("👑 Promote to Breeder", key=f"promote_{fish_id}", type="primary", use_container_width=True):
                                if promote_fish_to_breeder(fish_id):
                                    st.success(f"`{fish_id}` promoted to Active Breeder!")
                                    st.rerun()
                                else:
                                    st.error("Failed to promote fish.")
                        else:
                            st.button("✅ Active Breeder", key=f"is_breeder_btn_{fish_id}", disabled=True, use_container_width=True)
                            st.caption("Breeder ID matches Fish ID perfectly.")
