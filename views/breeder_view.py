# views/breeder_view.py
import datetime
import streamlit as st
from modules.breeder_registry import (
    register_breeder,
    get_all_breeders,
    delete_breeder
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

def evaluate_grade(caudal_180, caudal_prop, dorsal_good, anal_good, ventral_good, pectoral_good, body_shape, color_good):
    """
    Evaluates fish grade based on physical traits and IBC show criteria:
    - Show Grade: Full 180° caudal spread, clean fin branching/proportion, 
                 proper body shape (Bullet/Regular), clean dorsal/anal/ventral/pectoral fins, and good color.
    - Material Grade: Good color coverage and high-tier form features, but minor form flaws or spoonhead.
    - Pet Grade: Lacks core form criteria or key show traits.
    """
    passed_fin_checks = sum([
        caudal_180,
        caudal_prop,
        dorsal_good,
        anal_good,
        ventral_good,
        pectoral_good
    ])
    
    # Show Grade: Strict form standards met
    if (caudal_180 and 
        caudal_prop and 
        body_shape in ["Bullet Head", "Regular"] and 
        passed_fin_checks >= 5 and 
        color_good):
        return "Show Grade"
    # Material Grade: Strong breeding/color potential with minor physical limitations
    elif (caudal_180 or caudal_prop or passed_fin_checks >= 3) and color_good:
        return "Material Grade"
    # Pet Grade: Standard pet quality
    else:
        return "Pet Grade"


def render_breeder_page():
    st.title("🐟 Betta Breeder Management")

    tab1, tab2 = st.tabs(["➕ Register New Breeder", "📋 Breeder Gallery & Inventory"])

    # TAB 1: REGISTER BREEDER
    with tab1:
        st.subheader("Register a New Breeder")
        
        with st.form("register_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("### 📋 Basic Info")
                sex = st.selectbox("Sex", ["Male", "Female"])
                
                # Color / Pattern Class dropdown selector
                pattern_class = st.selectbox("Color / Pattern Class", COLOR_PATTERN_OPTIONS)
                
                # Input field displayed if "Others" is selected
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
            # Determine selected color pattern
            selected_pattern = custom_pattern.strip() if pattern_class == "Others" else pattern_class
            
            # Auto-calculate the fish classification
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
                
                # Format evaluation results into the notes field for logging
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

    # TAB 2: BREEDER GALLERY / INVENTORY
    with tab2:
        st.subheader("Registered Breeders")
        if st.button("🔄 Refresh Gallery"):
            st.rerun()

        breeders = get_all_breeders()
        if not breeders:
            st.info("No breeders registered yet. Add your first breeder in the Registration tab!")
        else:
            search_query = st.text_input("🔍 Search by ID, Variety, or Lineage:", "")
            
            filtered = [
                b for b in breeders
                if search_query.lower() in b['id'].lower()
                or search_query.lower() in b['variety'].lower()
                or search_query.lower() in b['lineage'].lower()
            ]

            cols = st.columns(3)
            for idx, b in enumerate(filtered):
                breeder_id = b['id']
                with cols[idx % 3]:
                    with st.container(border=True):
                        st.markdown(f"### {breeder_id}")
                        st.caption(f"**Sex:** {b['sex']} | **Status:** `{b['status']}`")
                        st.write(f"**Variety:** {b['variety']}")
                        st.write(f"**Lineage:** {b['lineage']}")
                        st.write(f"**DOB:** {b['dob']}")
                        
                        if b['notes']:
                            st.info(f"**Notes:** {b['notes']}")
                        
                        if b['photo_id']:
                            img_src = f"https://drive.google.com/thumbnail?id={b['photo_id']}&sz=w800"
                            st.image(img_src, use_container_width=True)
                        else:
                            st.caption("📷 *No Photo Available*")

                        st.divider()

                        # DELETE BREEDER SECTION
                        confirm_key = f"confirm_del_{breeder_id}"

                        if st.session_state.get(confirm_key, False):
                            st.warning("⚠️ Delete this breeder and associated media?")
                            btn_col1, btn_col2 = st.columns(2)
                            
                            with btn_col1:
                                if st.button("Yes, Delete", key=f"yes_{breeder_id}", type="primary", use_container_width=True):
                                    with st.spinner("Deleting..."):
                                        success = delete_breeder(breeder_id)
                                    if success:
                                        st.session_state[confirm_key] = False
                                        st.success("Deleted!")
                                        st.rerun()
                                    else:
                                        st.error("Failed to delete.")
                            
                            with btn_col2:
                                if st.button("Cancel", key=f"no_{breeder_id}", use_container_width=True):
                                    st.session_state[confirm_key] = False
                                    st.rerun()
                        else:
                            if st.button("🗑️ Delete Breeder", key=f"del_btn_{breeder_id}", use_container_width=True):
                                st.session_state[confirm_key] = True
                                st.rerun()
