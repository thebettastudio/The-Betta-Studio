import io
import datetime
import streamlit as st
from views.breeder_view import render_breeder_page
from views.spawn_view import render_spawn_page
from views.activity_log_view import render_activity_log_page
from modules.drive_service import get_google_services, SPREADSHEET_ID, DRIVE_FOLDER_ID

st.set_page_config(page_title="The Betta Studio", page_icon="🐟", layout="wide")

def run_google_diagnostic():
    """Runs a live health check on Google Drive & Sheets connections."""
    with st.sidebar.expander("🛠️ System Diagnostics"):
        if st.button("Test Google Connection", use_container_width=True):
            with st.status("Testing APIs...", expanded=True) as status:
                # 1. Test OAuth Credentials
                try:
                    st.write("🔐 Refreshing OAuth tokens...")
                    drive_service, sheets_service = get_google_services()
                    st.write("✅ Credentials Valid")
                except Exception as e:
                    status.update(label="OAuth Failure", state="error")
                    st.error(f"Authentication failed: {e}")
                    return

                # 2. Test Google Sheets
                try:
                    st.write("📊 Checking Google Sheets...")
                    result = sheets_service.spreadsheets().values().get(
                        spreadsheetId=SPREADSHEET_ID,
                        range='Breeders!A1:J1'
                    ).execute()
                    headers = result.get('values', [])
                    st.write(f"✅ Sheets Accessible ({len(headers[0]) if headers else 0} cols)")
                except Exception as e:
                    status.update(label="Sheets Read Failure", state="error")
                    st.error(f"Spreadsheet error: {e}")
                    return

                # 3. Test Google Drive
                try:
                    st.write("📁 Testing Drive Upload...")
                    from googleapiclient.http import MediaIoBaseUpload
                    test_bytes = f"Test stream {datetime.datetime.now()}".encode('utf-8')
                    file_stream = io.BytesIO(test_bytes)
                    
                    metadata = {'name': 'temp_diagnostic.txt'}
                    if DRIVE_FOLDER_ID:
                        metadata['parents'] = [DRIVE_FOLDER_ID.strip()]

                    media = MediaIoBaseUpload(file_stream, mimetype='text/plain', resumable=False)
                    uploaded = drive_service.files().create(
                        body=metadata,
                        media_body=media,
                        fields='id'
                    ).execute()

                    file_id = uploaded.get('id')
                    st.write("✅ Drive Upload Successful")

                    # Cleanup test file
                    drive_service.files().delete(fileId=file_id).execute()
                    st.write("🧹 Test file cleaned up")
                except Exception as e:
                    status.update(label="Drive Upload Failure", state="error")
                    st.error(f"Drive error: {e}")
                    return

                status.update(label="All Services Operational!", state="complete")

# --- Sidebar Navigation ---
st.sidebar.title("🐟 The Betta Studio")
page = st.sidebar.radio("Navigation", [
    "Breeder Registry",
    "Pair & Spawn Tracker",
    "Activity Log"
])

st.sidebar.markdown("---")
run_google_diagnostic()

# --- View Routing ---
if page == "Breeder Registry":
    render_breeder_page()
elif page == "Pair & Spawn Tracker":
    render_spawn_page()
elif page == "Activity Log":
    render_activity_log_page()
