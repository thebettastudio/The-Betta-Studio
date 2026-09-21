import io
import datetime
import streamlit as st
from views.breeder_view import render_breeder_page
from views.spawn_view import render_spawn_page
from views.activity_log_view import render_activity_log_page
from modules.drive_service import get_google_services, SPREADSHEET_ID, DRIVE_FOLDER_ID
from modules.spawn_manager import format_spawns_sheet

st.set_page_config(page_title="The Betta Studio", page_icon="🐟", layout="wide")

# ==============================================================================
# GLOBAL STYLING: Applies Deep Midnight Dark Theme & Half-Sized Image Glow (40px)
# ==============================================================================
st.markdown("""
<style>
  /* 1. Base App Dark Background */
  .stApp {
    background-color: #0F1117;
    color: #E6E8EB;
  }
  
  /* 2. Sidebar Customization */
  section[data-testid="stSidebar"] {
    background-color: #161922 !important;
    border-right: 1px solid #232733;
  }

  /* 3. Global Cards / Expanders / Containers */
  div[data-testid="stExpander"], div.stCard, div[data-testid="stVerticalBlock"] > div[style*="background-color"] {
    background: #1A1D24;
    border: 1px solid #282C37;
    border-radius: 12px;
  }

  /* 4. Global Spawn / Breeder Card Component */
  .spawn-card {
      background-color: #1A1D24;
      border: 1px solid #282C37;
      border-radius: 12px;
      padding: 12px 16px;
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 12px;
  }

  /* 5. Betta Image - Scaled Down to Half Size (40px) with Cyan Glow */
  .spawn-card-img {
      width: 40px;
      height: 40px;
      object-fit: cover;
      border-radius: 6px;
      border: 1.5px solid #2A303F;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4), 0 0 6px rgba(0, 210, 255, 0.15);
      transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
  }

  .spawn-card-img:hover {
      transform: scale(1.08);
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.6), 0 0 10px rgba(0, 210, 255, 0.5);
      border-color: #00D2FF;
  }

  .spawn-details h4 {
      margin: 0 0 4px 0;
      color: #00D2FF;
  }

  .spawn-details p {
      margin: 1px 0;
      color: #E6E8EB;
      font-size: 13px;
  }
</style>
""", unsafe_allow_html=True)


def run_google_diagnostic():
    """Runs a live health check on Google Drive & Sheets connections and provides formatting utilities."""
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

        st.divider()

        # One-click sheet formatter button
        if st.button("✨ Format Google Sheet", use_container_width=True):
            with st.spinner("Applying theme, headers, and colors to Spawns sheet..."):
                try:
                    format_spawns_sheet()
                    st.success("Google Sheet styled & formatted successfully!")
                except Exception as e:
                    st.error(f"Failed to format sheet: {e}")

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
