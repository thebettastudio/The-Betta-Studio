# views/breeder_view.py
import streamlit as st
import datetime
from modules.breeder_registry import register_breeder, get_all_breeders

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
                with st.spinner("Uploading photos and saving breeder details..."):
                    result = register_breeder(
                        sex=sex,
                        variety=variety,
                        lineage=lineage,
                        dob=str(dob),
                        photo_path=photo_file,
                        notes=notes
                    )

                st.success(f"Registered successfully! Breeder ID: **{result['breeder_id']}**")
                
                # Render uploaded photo and QR Code directly inside Streamlit
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
                with cols[idx % 3]:
                    with st.container(border=True):
                        st.markdown(f"### {b['id']}")
                        st.caption(f"**Sex:** {b['sex']} | **Status:** `{b['status']}`")
                        st.write(f"**Variety:** {b['variety']}")
                        st.write(f"**Lineage:** {b['lineage']}")
                        st.write(f"**DOB:** {b['dob']}")
                        
                        if b['notes']:
                            st.info(f"**Notes:** {b['notes']}")
                        
                        if b['photo_id']:
                            img_src = f"https://drive.google.com/thumbnail?id={b['photo_id']}&sz=w600"
                            st.image(img_src, use_container_width=True)
                        else:
                            st.caption("📷 *No Photo Available*")
