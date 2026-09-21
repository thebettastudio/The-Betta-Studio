# views/breeder_view.py
import datetime
import streamlit as st
from modules.breeder_registry import (
    register_breeder,
    get_all_breeders,
    delete_breeder
)

def render_breeder_page():
    st.title("🐟 Betta Breeder Management")

    tab1, tab2 = st.tabs(["➕ Register New Breeder", "📋 Breeder Gallery & Inventory"])

    # TAB 1: REGISTER BREEDER
    with tab1:
        st.subheader("Register a New Breeder")
        
        with st.form("register_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            
            with col1:
                sex = st.selectbox("Sex", ["Male", "Female"])
                variety = st.text_input("Variety / Tail Type", placeholder="e.g. Yellow Koi Galaxy, Halfmoon")
                lineage = st.text_input("Lineage / Breeder Source", placeholder="e.g. Peter Suson")
            
            with col2:
                dob = st.date_input("Date of Birth / Age", datetime.date.today())
                notes = st.text_area("Notes / Traits", placeholder="e.g. Big caudal 180 degrees, active swimmer")
                photo_file = st.file_uploader("Upload Breeder Photo", type=["jpg", "jpeg", "png"])

            submit = st.form_submit_button("📷 Register Breeder & Upload")

        if submit:
            if not variety or not lineage:
                st.error("Please fill in the Variety and Lineage fields.")
            else:
                with st.spinner("Uploading photos to Google Drive..."):
                    result = register_breeder(
                        sex=sex,
                        variety=variety,
                        lineage=lineage,
                        dob=str(dob),
                        photo_path=photo_file,
                        notes=notes
                    )

                st.success(f"Registered successfully! Breeder ID: **{result['breeder_id']}**")
                
                c1, c2 = st.columns(2)
                with c1:
                    st.subheader("Tank Tag QR Code")
                    if result.get("direct_qr_url"):
                        st.image(result['direct_qr_url'], width=220)
                with c2:
                    st.subheader("Breeder Photo")
                    if photo_file:
                        st.image(photo_file, caption=f"{variety} ({sex})", width=300)

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
