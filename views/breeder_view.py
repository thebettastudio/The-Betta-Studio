import streamlit as st
import tempfile
import os
from modules.breeder_registry import register_breeder

def render_breeder_page():
    st.header("🧬 Breeder Registry (Parent Stock)")
    st.caption("Register male and female breeders, generate tank QR tags, and sync photos to Google Drive.")

    with st.form("register_breeder_form", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            sex = st.selectbox("Sex", ["Male", "Female"])
            variety = st.text_input("Variety / Pattern", placeholder="e.g. Avatar Black Star HMPK")
            lineage = st.text_input("Lineage / Origin", placeholder="e.g. Line A - Grand Champion Sire")

        with col2:
            dob = st.date_input("Date of Birth / Hatch Date")
            notes = st.text_area("Notes & Traits", placeholder="Iridescence, tail spread, aggression score...")

        uploaded_photo = st.file_uploader("Upload Breeder Photo", type=["jpg", "jpeg", "png"])

        submit = st.form_submit_button("📷 Register Breeder & Upload")

        if submit:
            if not uploaded_photo:
                st.error("Please upload a photo of the breeder.")
            elif not variety:
                st.error("Please specify the variety/pattern.")
            else:
                with st.spinner("Uploading photo to Google Drive and generating QR code..."):
                    # Save temporarily to local disk so drive script can process it
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
                        tmp_file.write(uploaded_photo.getvalue())
                        tmp_path = tmp_file.name

                    try:
                        result = register_breeder(
                            sex=sex,
                            variety=variety,
                            lineage=lineage,
                            dob=str(dob),
                            photo_path=tmp_path,
                            notes=notes
                        )

                        st.success(f"Registered successfully! Breeder ID: **{result['breeder_id']}**")

                        # Display generated QR Code & Links
                        qr_col, img_col = st.columns(2)
                        with qr_col:
                            st.write("### Tank Tag QR Code")
                            st.markdown(f"[View in Google Drive]({result['qr_url']})")
                        with img_col:
                            st.write("### Breeder Photo")
                            st.markdown(f"[View in Google Drive]({result['photo_url']})")

                    finally:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
