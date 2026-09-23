# views/breeder_view.py
import datetime
import streamlit as st
from modules.breeder_registry import (
    register_breeder,
    get_all_breeders,
    retire_breeder
)

# Preset list of color pattern classes
COLOR_PATTERN_OPTIONS = [
    "Avatar",
    "Multicolor Galaxy",
    "Multicolor",
    "Nemo Copper Semi Dumbo",
    "Yellow Koi",
    "Candy Nemo",
    "Neon Green Eyes",
    "Candy Koi",
    "Regular",
    "Yellow Koi Galaxy",
    "Others"
]

# Retirement Reason Options
RETIREMENT_REASONS = [
    "Bad Parent (Egg / Fry Eater)",
    "Sick / Damaged / Health Issue",
    "Old Age / Natural Retirement",
    "Aggressive / Killed Partner",
    "Infertility / Low Hatch Rate",
    "Sold / Transferred",
    "Other"
]


def evaluate_grade(caudal_180, caudal_prop, dorsal_good, anal_good, ventral_good, pectoral_good, body_shape, color_good):
    """
    Evaluates fish grade based on physical traits and IBC show criteria.
    """
    passed_fin_checks = sum([
        caudal_180,
        caudal_prop,
        dorsal_good,
        anal_good,
        ventral_good,
        pectoral_good
    ])
    
    if (caudal_180 and 
        caudal_prop and 
        body_shape in ["Bullet Head", "Regular"] and 
        passed_fin_checks >= 5 and 
        color_good):
        return "Show Grade"
    elif (caudal_180 or caudal_prop or passed_fin_checks >= 3) and color_good:
        return "Material Grade"
    else:
        return "Pet Grade"


def render_merged_breeder_grid(breeders_list: list):
    """
    Renders breeder records in a 2-column merged Gallery/Inventory card layout.
    """
    if not breeders_list:
        st.info("No breeders found in this section.")
        return

    # Render cards in a 2-column layout
    cols = st.columns(2)
    for idx, b in enumerate(breeders_list):
        breeder_id = b['id']
        status_val = str(b.get('status', 'Available')).strip()
        is_retired = status_val.lower() in ['retired', 'inactive', 'deceased', 'sold']

        with cols[idx % 2]:
            with st.container(border=True):
                # Photo Display
                if b.get('photo_id'):
                    img_src = f"https://drive.google.com/thumbnail?id={b['photo_id']}&sz=w800"
                    st.image(img_src, use_container_width=True)
                else:
                    st.caption("📷 *No Photo Available*")

                st.markdown(f"### {breeder_id}")
                st.caption(f"**Sex:** {b['sex']} | **Status:** `{status_val}`")
                st.write(f"🧬 **Variety:** {b['variety']}")
                st.write(f"🏷️ **Lineage:** {b['lineage']}")
                st.write(f"📅 **DOB:** {b['dob']}")
                
                if b.get('notes'):
                    st.info(f"📝 **Notes:** {b['notes']}")

                st.divider()

                # RETIRE BREEDER SECTION
                if is_retired:
                    st.caption("🚫 *This breeder is currently inactive/retired.*")
                else:
                    with st.popover("🚫 Retire Breeder", use_container_width=True):
                        st.markdown("### Retire / Deactivate Breeder")
                        st.caption("Select a reason for taking this breeder out of active breeding rotations.")
                        
                        reason = st.selectbox(
                            "Reason for Retirement",
                            RETIREMENT_REASONS,
                            key=f"retire_reason_{breeder_id}"
                        )
                        
                        add_notes = st.text_area(
                            "Additional Context / Details",
                            placeholder="e.g. Ate eggs on 2 consecutive spawn attempts.",
                            key=f"retire_notes_{breeder_id}"
                        )
                        
                        if st.button("Confirm Retirement", key=f"confirm_retire_{breeder_id}", type="primary", use_container_width=True):
                            with st.spinner("Updating status..."):
                                success = retire_breeder(breeder_id, reason=reason, notes=add_notes)
                            if success:
                                st.success(f"Breeder {breeder_id} marked as Retired/Inactive!")
                                st.rerun()
                            else:
                                st.error("Failed to update status.")


def render_breeder_page():
    st.title("🐟 Betta Breeder Management")

    tab1, tab2 = st.tabs([
        "➕ Register New Breeder", 
        "📋 Breeder Inventory & Gallery"
    ])

    # Fetch all breeders
    breeders = get_all_breeders()

    # Separate Males and Females
    males_list = [b for b in breeders if str(b.get("sex", "")).strip().lower() in ["male", "m", "♂️ male"]]
    females_list = [b for b in breeders if str(b.get("sex", "")).strip().lower() in ["female", "f", "♀️ female"]]

    # ====================================================
    # TAB 1: REGISTER BREEDER
    # ====================================================
    with tab1:
        st.subheader("Register a New Breeder")
        
        with st.form("register_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("### 📋 Basic Info")
                sex = st.selectbox("Sex", ["Male", "Female"])
                
                pattern_class = st.selectbox("Color / Pattern Class", COLOR_PATTERN_OPTIONS)
                
                custom_pattern = ""
                if pattern_class == "Others":
                    custom_pattern = st.text_input("Specify Other Pattern", placeholder="e.g. Black Star")
                    
                lineage = st.text_input("Lineage / Breeder Source", placeholder="e.g. Peter Suson")
                dob = st.date_input("Date of Birth / Age", datetime.date.today())
                photo_file = st.file_uploader("Upload Breeder Photo", type=["jpg", "jpeg", "png"])

            with col2:
                st.markdown("### 🏆 Form Evaluation Criteria")
                
                caudal_180 = st.checkbox("Caudal Fin Spread 180°", value=True)
                caudal_prop = st.checkbox("Caudal Fin Proportion (Good branching, no damage)", value=True)
                dorsal_good = st.checkbox("Dorsal Fin Structure (Broad base & clean overlapping)", value=True)
                anal_good = st.checkbox("Anal Fin Structure (Parallel & proper length)", value=True)
                ventral_good = st.checkbox("Ventral Fins (Straight, broad, no curl)", value=True)
                pectoral_good = st.checkbox("Pectoral Fins (Full & undamaged)", value=True)
                
                body_shape = st.selectbox(
                    "Body Shape", 
                    ["Bullet Head", "Regular", "Spoonhead"]
                )
                
                color_good = st.checkbox("Good Color / Pattern Coverage", value=True)

                notes = st.text_area("Notes / Traits", placeholder="e.g. Active swimmer, sharp caudal ray edges")

            submit = st.form_submit_button("📷 Register Breeder & Evaluate Grade")

        if submit:
            selected_pattern = custom_pattern.strip() if pattern_class == "Others" else pattern_class
            
            grade = evaluate_grade(
                caudal_180=caudal_180,
                caudal_prop=caudal_prop,
                dorsal_good=dorsal_good,
                anal_good=anal_good,
                ventral_good=ventral_good,
                pectoral_good=pectoral_good,
                body_shape=body_shape,
                color_good=color_good
            )

            if not selected_pattern or not lineage:
                st.error("Please fill in the Color / Pattern Class and Lineage fields.")
            else:
                full_variety = f"HMKP - {selected_pattern}"
                
                form_summary = (
                    f"Grade: {grade} | Head: {body_shape} | "
                    f"180°: {'Yes' if caudal_180 else 'No'}, "
                    f"Branching: {'Good' if caudal_prop else 'Damaged/Poor'}, "
                    f"Color: {'Good' if color_good else 'Fair'}"
                )
                full_notes = f"[{form_summary}] {notes}".strip()

                with st.spinner("Uploading photos to Google Drive..."):
                    result = register_breeder(
                        sex=sex,
                        variety=full_variety,
                        lineage=lineage,
                        dob=str(dob),
                        photo_path=photo_file,
                        notes=full_notes
                    )

                st.success(f"Registered successfully! Breeder ID: **{result['breeder_id']}** | Grade: **{grade}**")
                
                c1, c2 = st.columns(2)
                with c1:
                    st.subheader("Tank Tag QR Code")
                    if result.get("direct_qr_url"):
                        st.image(result['direct_qr_url'], width=220)
                with c2:
                    st.subheader("Breeder Photo")
                    if photo_file:
                        st.image(photo_file, caption=f"{full_variety} ({sex}) — {grade}", width=300)

    # ====================================================
    # TAB 2: INVENTORY & GALLERY (ACTIVE vs. INACTIVE)
    # ====================================================
    with tab2:
        col_title, col_btn = st.columns([4, 1])
        with col_title:
            st.subheader("Breeder Inventory & Gallery")
        with col_btn:
            if st.button("🔄 Refresh", key="refresh_all"):
                st.rerun()

        if not breeders:
            st.info("No breeders registered yet.")
        else:
            search_query = st.text_input("🔍 Search by ID, Variety, or Lineage:", "", key="search_merged")
            
            # Apply search filter
            filtered_males = [
                b for b in males_list
                if search_query.lower() in str(b['id']).lower()
                or search_query.lower() in str(b['variety']).lower()
                or search_query.lower() in str(b['lineage']).lower()
            ]
            
            filtered_females = [
                b for b in females_list
                if search_query.lower() in str(b['id']).lower()
                or search_query.lower() in str(b['variety']).lower()
                or search_query.lower() in str(b['lineage']).lower()
            ]

            male_tab, female_tab = st.tabs(["♂️ Male Breeders", "♀️ Female Breeders"])

            # Active vs. Inactive helper list splitters
            def split_active_inactive(fish_list):
                active = []
                inactive = []
                for f in fish_list:
                    st_val = str(f.get('status', 'Available')).strip().lower()
                    if st_val in ['retired', 'inactive', 'sold', 'deceased']:
                        inactive.append(f)
                    else:
                        active.append(f)
                return active, inactive

            # --- Male Section ---
            with male_tab:
                active_males, inactive_males = split_active_inactive(filtered_males)
                
                m_sub_tab1, m_sub_tab2 = st.tabs([
                    f"🟢 Active Males ({len(active_males)})", 
                    f"🚫 Inactive / Retired Males ({len(inactive_males)})"
                ])
                
                with m_sub_tab1:
                    render_merged_breeder_grid(active_males)
                
                with m_sub_tab2:
                    render_merged_breeder_grid(inactive_males)

            # --- Female Section ---
            with female_tab:
                active_females, inactive_females = split_active_inactive(filtered_females)
                
                f_sub_tab1, f_sub_tab2 = st.tabs([
                    f"🟢 Active Females ({len(active_females)})", 
                    f"🚫 Inactive / Retired Females ({len(inactive_females)})"
                ])
                
                with f_sub_tab1:
                    render_merged_breeder_grid(active_females)
                
                with f_sub_tab2:
                    render_merged_breeder_grid(inactive_females)
