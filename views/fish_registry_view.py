import io
import datetime
import pandas as pd
import streamlit as st

# Import Drive & Sheets services
from modules.drive_service import get_google_services, SPREADSHEET_ID, DRIVE_FOLDER_ID

# ------------------------------------------------------------------------------
# Helper Functions: Sheet Initialization, Strains, Tanks, Grades & ID
# ------------------------------------------------------------------------------

def ensure_sheet_exists(sheets_service, sheet_name, default_headers):
    """Ensures that a specified worksheet tab exists in Google Sheets with headers."""
    try:
        spreadsheet = sheets_service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        sheets = spreadsheet.get('sheets', [])
        sheet_titles = [s['properties']['title'] for s in sheets]

        if sheet_name not in sheet_titles:
            # Create sheet tab
            requests = [{'addSheet': {'properties': {'title': sheet_name}}}]
            sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body={'requests': requests}
            ).execute()

            # Add headers starting at A1
            sheets_service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f'{sheet_name}!A1',
                valueInputOption='USER_ENTERED',
                body={'values': [default_headers]}
            ).execute()
    except Exception as e:
        st.warning(f"Note: Auto-creation check for '{sheet_name}' failed ({e})")


def ensure_fish_master_sheet_exists(sheets_service):
    headers = [
        "Fish ID", "Variety / Strain", "Gender", "Grade", 
        "Tank ID", "Seller", "Purchase Date", "Purchase Cost", 
        "Image URL", "Notes"
    ]
    ensure_sheet_exists(sheets_service, 'Fish_Master', headers)


def generate_next_fish_id(sheets_service) -> int:
    """Fetch all existing Fish IDs from Column A and return the next integer sequence."""
    try:
        res = sheets_service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Fish_Master!A2:A'
        ).execute()
        rows = res.get('values', [])
        
        max_id = 0
        for r in rows:
            if r and r[0].strip():
                raw_id = r[0].strip()
                val_str = raw_id.replace("FISH-", "").strip()
                if val_str.isdigit():
                    max_id = max(max_id, int(val_str))
                    
        return max_id + 1
    except Exception:
        return 1


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
        
        all_strains = set(default_strains + strains)
        removed_strains = st.session_state.get("removed_strains_list", set())
        active_strains = [s for s in all_strains if s not in removed_strains]
        
        return sorted(active_strains)
    except Exception:
        removed_strains = st.session_state.get("removed_strains_list", set())
        return sorted([s for s in default_strains if s not in removed_strains])


def add_new_strain_to_db(sheets_service, new_strain):
    """Save a new strain to the 'Master_Strains' worksheet."""
    try:
        ensure_sheet_exists(sheets_service, 'Master_Strains', ["Strain Name"])
        
        if "removed_strains_list" in st.session_state:
            st.session_state["removed_strains_list"].discard(new_strain.strip())
            
        sheets_service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range='Master_Strains!A:A',
            valueInputOption='USER_ENTERED',
            body={'values': [[new_strain.strip()]]}
        ).execute()
        st.toast(f"✅ Saved '{new_strain}' to Strain Registry!", icon="✨")
    except Exception as e:
        st.error(f"Could not save strain to database ({e})")


def delete_strain_from_db(sheets_service, strain_to_remove):
    """Delete a strain row from 'Master_Strains' or soft-delete from local registry."""
    if "removed_strains_list" not in st.session_state:
        st.session_state["removed_strains_list"] = set()
    st.session_state["removed_strains_list"].add(strain_to_remove)

    try:
        spreadsheet = sheets_service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        sheets = spreadsheet.get('sheets', [])
        sheet_id = None
        for s in sheets:
            if s['properties']['title'] == 'Master_Strains':
                sheet_id = s['properties']['sheetId']
                break

        if sheet_id is not None:
            res = sheets_service.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID,
                range='Master_Strains!A1:A'
            ).execute()
            rows = res.get('values', [])
            
            delete_requests = []
            for idx, r in enumerate(rows):
                if r and r[0].strip().lower() == strain_to_remove.strip().lower():
                    delete_requests.append({
                        "deleteDimension": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": "ROWS",
                                "startIndex": idx,
                                "endIndex": idx + 1
                            }
                        }
                    })

            if delete_requests:
                delete_requests.reverse()
                sheets_service.spreadsheets().batchUpdate(
                    spreadsheetId=SPREADSHEET_ID,
                    body={'requests': delete_requests}
                ).execute()

        st.toast(f"🗑️ Removed '{strain_to_remove}' from Strain Registry!", icon="✨")
    except Exception:
        st.toast(f"Removed '{strain_to_remove}' from UI view.", icon="ℹ️")


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
        return [
            {"id": "Jar M-01", "type": "Empi Jar", "status": "Available"},
            {"id": "Jar M-02", "type": "Empi Jar", "status": "Available"},
            {"id": "B-01", "type": "6L Bottle", "status": "Available"},
            {"id": "T-01", "type": "Tubo Container", "status": "Available"},
        ]


def mark_tank_occupied(sheets_service, tank_id: str):
    """Updates the assigned tank's status to 'Occupied' in the Tanks sheet."""
    try:
        res = sheets_service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Tanks!A2:C'
        ).execute()
        rows = res.get('values', [])
        
        for idx, r in enumerate(rows, start=2):
            if r and r[0].strip().lower() == tank_id.strip().lower():
                sheets_service.spreadsheets().values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f'Tanks!C{idx}',
                    valueInputOption='USER_ENTERED',
                    body={'values': [["Occupied"]]}
                ).execute()
                break
    except Exception as e:
        st.warning(f"Note: Could not update tank '{tank_id}' status to Occupied: {e}")


def get_all_fish_records(sheets_service):
    """Fetch all registered fish from 'Fish_Master' sheet (Range A1:J)."""
    try:
        res = sheets_service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Fish_Master!A1:J'
        ).execute()
        rows = res.get('values', [])
        
        if not rows or len(rows) < 2:
            return pd.DataFrame(columns=[
                "Fish ID", "Variety / Strain", "Gender", "Grade", 
                "Tank ID", "Seller", "Purchase Date", "Purchase Cost", 
                "Image URL", "Notes"
            ])
        
        headers = [h.strip() for h in rows[0]]
        data = rows[1:]
        
        padded_data = [r + [""] * (len(headers) - len(r)) for r in data]
        df = pd.DataFrame(padded_data, columns=headers)
        df = df.apply(lambda col: col.str.strip() if col.dtype == "object" else col)
        
        return df
    except Exception as e:
        st.error(f"Error reading Fish Master database: {e}")
        return pd.DataFrame()


def upload_image_to_drive(drive_service, image_bytes, filename_prefix="fish_"):
    """Upload photo bytes to Google Drive and return public direct view URL."""
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
    """Calculates grade and total score based on fin criteria checkboxes and body shape."""
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

    tab_register, tab_view = st.tabs(["📝 Register New Fish", "📋 Fish List & Database"])

    # ==========================================================================
    # TAB 1: REGISTER NEW FISH
    # ==========================================================================
    with tab_register:
        st.subheader("🛒 Purchased / Imported Fish Details")

        ensure_fish_master_sheet_exists(sheets_service)
        next_fish_num = generate_next_fish_id(sheets_service)
        assigned_fish_id = f"FISH-{str(next_fish_num).zfill(4)}"
        
        st.info(f"📌 Next Assigned Fish ID: **#{assigned_fish_id}**")

        strains_list = get_registered_strains(sheets_service)

        strain_col_select, strain_col_btn = st.columns([4, 1])
        
        with strain_col_btn:
            st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
            with st.popover("⚙️ Manage Strains"):
                pop_tab_add, pop_tab_remove = st.tabs(["➕ Add", "🗑️ Remove"])
                
                with pop_tab_add:
                    st.markdown("##### Add New Strain")
                    new_strain_val = st.text_input("Strain Name", placeholder="e.g. Copper Blue Star").strip()
                    if st.button("Save Strain", use_container_width=True, type="primary", key="btn_add_strain"):
                        if new_strain_val:
                            add_new_strain_to_db(sheets_service, new_strain_val)
                            st.session_state["selected_strain"] = new_strain_val
                            st.rerun()
                        else:
                            st.warning("Please enter a strain name.")

                with pop_tab_remove:
                    st.markdown("##### Remove Existing Strain")
                    if strains_list:
                        strain_to_delete = st.selectbox(
                            "Select Strain to Delete", 
                            options=strains_list, 
                            key="select_strain_to_delete"
                        )
                        if st.button("Delete Strain", use_container_width=True, type="primary", key="btn_delete_strain"):
                            delete_strain_from_db(sheets_service, strain_to_delete)
                            if st.session_state.get("selected_strain") == strain_to_delete:
                                st.session_state.pop("selected_strain", None)
                            st.rerun()
                    else:
                        st.info("No strains available to remove.")

        default_index = 0
        if "selected_strain" in st.session_state and st.session_state["selected_strain"] in strains_list:
            default_index = strains_list.index(st.session_state["selected_strain"])

        with strain_col_select:
            selected_strain = st.selectbox(
                "Select Strain",
                options=strains_list if strains_list else ["No Strains Available"],
                index=default_index if strains_list else 0,
                key="select_strain_dropdown"
            )

        with st.form("register_fish_form", clear_on_submit=False):
            col1, col2 = st.columns(2)

            with col1:
                st.markdown("##### 🧬 Variety & Details")
                form_type = st.text_input("Form / Type", value="HMPK", help="Default is HMPK (Halfmoon Plakat)")
                gender = st.selectbox("Gender", ["Male", "Female"])
                seller = st.text_input("Seller / Source", placeholder="e.g. Aquarama Import / Local Breeder")
                purchase_date = st.date_input("Purchase Date", datetime.date.today())
                purchase_cost = st.number_input("Purchase Cost (₱)", min_value=0.0, value=0.0, step=50.0)

            with col2:
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

            st.markdown("##### 📷 Fish Photo Capture / Upload")
            
            img_col1, img_col2 = st.columns(2)
            with img_col1:
                camera_photo = st.camera_input("Take a Live Photo of Fish")
            with img_col2:
                uploaded_photo = st.file_uploader("Or Upload Photo File", type=["jpg", "jpeg", "png"])
                manual_image_url = st.text_input("Or Paste Existing Drive ID / Image URL", placeholder="Paste direct link or Drive ID")

            notes = st.text_area("Notes / Characteristics", placeholder="e.g. Strong dorsal, solid iridescence, aggressive disposition")

            submit = st.form_submit_button("💾 Register Fish", use_container_width=True)

        if submit:
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

            selected_tank_id = selected_tank_str.split(" (")[0] if selected_tank_str != "No Available Tanks" else ""

            new_fish_record = [
                assigned_fish_id,
                f"{form_type} - {selected_strain}",
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
                # Appends to Range A:J
                sheets_service.spreadsheets().values().append(
                    spreadsheetId=SPREADSHEET_ID,
                    range='Fish_Master!A:J',
                    valueInputOption='USER_ENTERED',
                    body={'values': [new_fish_record]}
                ).execute()

                # Mark Tank as Occupied if assigned
                if selected_tank_id:
                    mark_tank_occupied(sheets_service, selected_tank_id)

                st.balloons()
                st.success(f"🎉 Fish **#{assigned_fish_id}** ({selected_strain}) successfully registered! Grade: **{computed_grade}**.")
                st.rerun()
            except Exception as e:
                st.error(f"Error saving fish record: {e}")

    # ==========================================================================
    # TAB 2: FISH LIST & DATABASE
    # ==========================================================================
    with tab_view:
        st.subheader("📋 Registered Fish Database")
        
        df = get_all_fish_records(sheets_service)

        if df.empty:
            st.info("No fish records found in `Fish_Master`. Register your first fish above!")
        else:
            # Metrics Overview Row
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total Registered", len(df))
            m2.metric("Males", len(df[df["Gender"] == "Male"])) if "Gender" in df else None
            m3.metric("Females", len(df[df["Gender"] == "Female"])) if "Gender" in df else None
            m4.metric("Show/High Grade", len(df[df["Grade"].isin(["Show Grade", "High Grade"])])) if "Grade" in df else None

            st.divider()

            # Filters Bar
            st.markdown("##### 🔍 Filter Database")
            f_col1, f_col2, f_col3 = st.columns(3)

            with f_col1:
                gender_filter = st.multiselect(
                    "Filter Gender",
                    options=list(df["Gender"].unique()) if "Gender" in df else [],
                    default=[]
                )

            with f_col2:
                grade_filter = st.multiselect(
                    "Filter Grade",
                    options=list(df["Grade"].unique()) if "Grade" in df else [],
                    default=[]
                )

            with f_col3:
                strain_filter = st.multiselect(
                    "Filter Strain / Variety",
                    options=list(df["Variety / Strain"].unique()) if "Variety / Strain" in df else [],
                    default=[]
                )

            # Apply Filters
            filtered_df = df.copy()
            if gender_filter:
                filtered_df = filtered_df[filtered_df["Gender"].isin(gender_filter)]
            if grade_filter:
                filtered_df = filtered_df[filtered_df["Grade"].isin(grade_filter)]
            if strain_filter:
                filtered_df = filtered_df[filtered_df["Variety / Strain"].isin(strain_filter)]

            # Interactive Table
            st.dataframe(
                filtered_df,
                column_config={
                    "Fish ID": st.column_config.TextColumn("Fish ID"),
                    "Image URL": st.column_config.ImageColumn("Photo Preview"),
                    "Purchase Cost": st.column_config.NumberColumn("Cost (₱)", format="₱%.2f"),
                    "Notes": st.column_config.TextColumn("Notes", width="large"),
                },
                use_container_width=True,
                hide_index=True
            )

            st.caption(f"Showing {len(filtered_df)} of {len(df)} records.")
