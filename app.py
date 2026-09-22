import io
import datetime
import streamlit as st

# Import Drive & Sheets services
from modules.drive_service import get_google_services, SPREADSHEET_ID, DRIVE_FOLDER_ID

# ------------------------------------------------------------------------------
# Helper Functions: Strain, Tank & Grade Management
# ------------------------------------------------------------------------------

def get_registered_strains(sheets_service):
    """Fetch list of saved strains from 'Master_Strains' sheet or return defaults."""
    default_strains = [
        "Yellow Koi Galaxy",
        "Red Koi Galaxy",
        "Blue Rim",
        "Avatar",
        "Black Star / Samurai",
        "Red Dragon",
        "Copper Light",
        "Fancy Marble",
        "Super Red",
        "Super Black"
    ]
    try:
        res = sheets_service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Master_Strains!A2:A'
        ).execute()
        rows = res.get('values', [])
        strains = [r[0] for r in rows if r and r[0].strip()]
        return sorted(list(set(default_strains + strains)))
    except Exception:
        return default_strains


def add_new_strain_to_db(sheets_service, new_strain):
    """Save a new strain to the 'Master_Strains' worksheet."""
    try:
        sheets_service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range='Master_Strains!A:A',
            valueInputOption='USER_ENTERED',
            body={'values': [[new_strain.strip()]]}
        ).execute()
        st.toast(f"✅ Added '{new_strain}' to Strain Registry!", icon="✨")
    except Exception as e:
        st.warning(f"Note: Could not save strain to persistent sheet ({e})")


def get_available_tanks(sheets_service):
    """Fetch tanks with status 'Available' along with their container type."""
    try:
        res = sheets_service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Tanks!A2:E'
        ).execute()
        rows = res.get('values', [])
        tanks = []
        for r in rows:
            if len(r) >= 3:
                tank_id = r[0]
                container_type = r[1] if len(r) > 1 else "Standard"
                status = r[2] if len(r) > 2 else "Available"
                if status.strip().lower() in ["available", "vacant", "empty", "free"]:
                    tanks.append({"id": tank_id, "type": container_type, "status": status})
        return tanks
    except Exception:
        # Fallback dummy tanks if sheet is empty/unreachable
        return [
            {"id": "Jar M-01", "type": "Empi Jar", "status": "Available"},
            {"id": "Jar M-02", "type": "Empi Jar", "status": "Available"},
            {"id": "B-01", "type": "6L Bottle", "status": "Available"},
            {"id": "T-01", "type": "Tubo Container", "status": "Available"},
        ]


def upload_image_to_drive(drive_service, image_bytes, filename_prefix="fish_"):
    """Upload photo bytes to Google Drive and return public file ID / URL."""
    from googleapiclient.http import MediaIoBaseUpload
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"{filename_prefix}{timestamp}.jpg"
    
    file_stream = io.BytesIO(image_bytes)
    metadata = {'name': file_name}
    if DRIVE_FOLDER_ID:
        metadata['parents'] = [DRIVE_FOLDER_ID.strip()]

    media = MediaIoBaseUpload(file_stream, mimetype='image/jpeg', resumable=False)
    uploaded = drive_service.files().create(
        body=metadata,
        media_body=media,
        fields='id'
    ).execute()
    
    file_id = uploaded.get('id')
    return file_id, f"https://lh3.googleusercontent.com/d/{file_id}"


def calculate_form_grade(checks: dict, body_shape: str) -> tuple[str, int]:
    """
    Calculates grade and total score based on fin criteria checkboxes and body shape.
    
    Each checked fin criterion adds 15 points (Max 90 pts).
    Body Shape weighting:
      - Bullet Head: +10 pts
      - Regular: +8 pts
      - Spoonhead: +5 pts
    """
    total_score = sum(15 for matched in checks.values() if matched)
    
    shape_scores = {
        "Bullet Head": 10,
        "Regular": 8,
        "Spoonhead": 5
    }
    total_score += shape_scores.get(body_shape, 8)
    
    if total_score >= 95:
        grade = "Show Grade"
    elif total_score >= 80:
        grade = "High Grade"
    elif total_score >= 60:
        grade = "Breeder Grade"
    else:
        grade = "Pet Grade"
        
    return grade, total_score


# ------------------------------------------------------------------------------
# Main Page Render Function
# ------------------------------------------------------------------------------

def render_fish_registry_page():
    st.header("🐠 Fish Master Registry")
    st.caption("Register and manage individual imported, purchased, or batch-selected Betta fish.")

    # Initialize Google Services
    try:
        drive_service, sheets_service = get_google_services()
    except Exception as e:
        st.error(f"Failed to connect to Google Services: {e}")
        return

    # Tabs for Registration and View Registry
    tab_register, tab_view = st.tabs(["📝 Register New Fish", "📋 Fish List & Database"])

    with tab_register:
        st.subheader("🛒 Purchased / Imported Fish Details")

        with st.form("register_fish_form", clear_on_submit=False):
            col1, col2 = st.columns(2)

            with col1:
                # 1. Variety / Type & Strain Selection
                st.markdown("##### 🧬 Variety & Strain")
                form_type = st.text_input("Form / Type", value="HMPK", help="Default is HMPK (Halfmoon Plakat)")
                
                existing_strains = get_registered_strains(sheets_service)
                strain_options = existing_strains + ["➕ Add New Strain..."]
                selected_strain_option = st.selectbox("Select Strain", options=strain_options, index=0)

                new_strain_input = ""
                if selected_strain_option == "➕ Add New Strain...":
                    new_strain_input = st.text_input("Enter New Strain Name", placeholder="e.g. Yellow Red Dragon Fancy")

                gender = st.selectbox("Gender", ["Male", "Female"])
                seller = st.text_input("Seller / Source", placeholder="e.g. Aquarama Import / Local Breeder")
                purchase_date = st.date_input("Purchase Date", datetime.date.today())
                purchase_cost = st.number_input("Purchase Cost (₱)", min_value=0.0, value=0.0, step=50.0)

            with col2:
                # 2. Dynamic Tank Selection with Filter
                st.markdown("##### 🪣 Tank & Container Assignment")
                
                all_available_tanks = get_available_tanks(sheets_service)
                container_types = ["All Types"] + sorted(list(set(t["type"] for t in all_available_tanks)))
                
                selected_type_filter = st.selectbox("Filter Tank Type", options=container_types)
                
                if selected_type_filter != "All Types":
                    filtered_tanks = [t for t in all_available_tanks if t["type"] == selected_type_filter]
                else:
                    filtered_tanks = all_available_tanks

                tank_options = [f"{t['id']} ({t['type']})" for t in filtered_tanks] if filtered_tanks else ["No Available Tanks"]
                selected_tank_str = st.selectbox("Select Available Tank / Jar Location", options=tank_options)

            st.divider()

            # 3. Form Evaluation Criteria Checklist & Body Shape
            st.markdown("### 🏆 Form Evaluation Criteria")
            
            chk_col, shape_col = st.columns([3, 2])
            
            with chk_col:
                caudal_spread = st.checkbox("Caudal Fin Spread 180°", value=True)
                caudal_prop = st.checkbox("Caudal Fin Proportion (Good branching, no damage)", value=True)
                dorsal_struct = st.checkbox("Dorsal Fin Structure (Broad base & clean overlapping)", value=True)
                anal_struct = st.checkbox("Anal Fin Structure (Parallel & proper length)", value=True)
                ventral_fins = st.checkbox("Ventral Fins (Straight, broad, no curl)", value=True)
                pectoral_fins = st.checkbox("Pectoral Fins (Full & undamaged)", value=True)

            with shape_col:
                body_shape = st.selectbox(
                    "Body Shape",
                    options=["Bullet Head", "Regular", "Spoonhead"],
                    index=0,
                    help="Select the head profile/body shape structure."
                )

            evaluation_checks = {
                "caudal_spread": caudal_spread,
                "caudal_prop": caudal_prop,
                "dorsal_struct": dorsal_struct,
                "anal_struct": anal_struct,
                "ventral_fins": ventral_fins,
                "pectoral_fins": pectoral_fins,
            }

            computed_grade, total_points = calculate_form_grade(evaluation_checks, body_shape)
            st.info(f"🏆 Calculated Grade: **{computed_grade}** (Score: **{total_points}/100**)")

            st.divider()

            # 4. Direct Photo Capture / Upload & Fallback URL
            st.markdown("##### 📷 Fish Photo Capture / Upload")
            
            img_col1, img_col2 = st.columns(2)
            with img_col1:
                camera_photo = st.camera_input("Take a Live Photo of Fish")
            with img_col2:
                uploaded_photo = st.file_uploader("Or Upload Photo File", type=["jpg", "jpeg", "png"])
                manual_image_url = st.text_input("Or Paste Existing Drive ID / Image URL", placeholder="Paste direct link or Drive ID")

            notes = st.text_area("Notes / Characteristics", placeholder="e.g. Strong dorsal, solid iridescence, aggressive disposition")

            submit = st.form_submit_button("💾 Register Fish", use_container_width=True)

        # Handle Form Submission Logic
        if submit:
            final_strain = new_strain_input if selected_strain_option == "➕ Add New Strain..." else selected_strain_option
            
            if selected_strain_option == "➕ Add New Strain..." and new_strain_input.strip():
                add_new_strain_to_db(sheets_service, new_strain_input.strip())

            # Handle Image Upload to Google Drive
            final_image_val = manual_image_url
            photo_bytes = None
            if camera_photo is not None:
                photo_bytes = camera_photo.getvalue()
            elif uploaded_photo is not None:
                photo_bytes = uploaded_photo.getvalue()

            if photo_bytes:
                with st.spinner("Uploading photo to Google Drive..."):
                    try:
                        file_id, img_url = upload_image_to_drive(drive_service, photo_bytes)
                        final_image_val = img_url
                        st.success(f"Image uploaded successfully! (Drive ID: {file_id})")
                    except Exception as err:
                        st.error(f"Image upload failed: {err}")

            # Selected Tank ID
            selected_tank_id = selected_tank_str.split(" (")[0] if selected_tank_str != "No Available Tanks" else ""

            # Prepare row data for Google Sheets
            new_fish_record = [
                f"FISH-{datetime.datetime.now().strftime('%M%S')}",
                f"{form_type} - {final_strain}",
                gender,
                computed_grade,
                selected_tank_id,
                seller,
                str(purchase_date),
                purchase_cost,
                final_image_val,
                f"Body Shape: {body_shape}. {notes}".strip()
            ]

            try:
                # Append row to 'Fish_Master' sheet
                sheets_service.spreadsheets().values().append(
                    spreadsheetId=SPREADSHEET_ID,
                    range='Fish_Master!A:J',
                    valueInputOption='USER_ENTERED',
                    body={'values': [new_fish_record]}
                ).execute()

                st.balloons()
                st.success(f"🎉 Fish successfully registered as Grade: **{computed_grade}** assigned to **{selected_tank_id}**!")
            except Exception as e:
                st.error(f"Error saving fish record: {e}")

    with tab_view:
        st.write("Displaying registered fish list from `Fish_Master` worksheet...")
