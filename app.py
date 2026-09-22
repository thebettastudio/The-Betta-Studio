import io
import datetime
import streamlit as st
from views.breeder_view import render_breeder_page
from views.fish_registry_view import render_fish_registry_page  # Fish Master Registry View
from views.spawn_view import render_spawn_page
from views.activity_log_view import render_activity_log_page
from views.tank_view import render_tank_page       # Tank Registry View
from views.search_view import render_search_page   # Global Search View
from modules.dashboard import render_dashboard      # Main Studio Dashboard View
from modules.drive_service import get_google_services, SPREADSHEET_ID, DRIVE_FOLDER_ID
from modules.spawn_manager import format_spawns_sheet

st.set_page_config(
    page_title="The Betta Studio", 
    page_icon="🐟", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==============================================================================
# GLOBAL STYLING: Applies Clean Light Theme
# ==============================================================================
st.markdown("""
<style>
  /* 1. Base App Light Background & Dark Text */
  .stApp {
    background-color: #FFFFFF;
    color: #1E2022;
  }
  
  /* Force global text elements to remain dark */
  .stApp p, .stApp span, .stApp label, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6 {
    color: #1E2022 !important;
  }

  /* 2. Sidebar Customization */
  section[data-testid="stSidebar"] {
    background-color: #F8F9FA !important;
    border-right: 1px solid #E2E8F0;
  }

  /* 3. Global Cards / Expanders / Containers */
  div[data-testid="stExpander"], div.stCard, div[data-testid="stVerticalBlock"] > div[style*="background-color"] {
    background: #FFFFFF !important;
    border: 1px solid #E2E8F0 !important;
    border-radius: 12px;
  }

  /* 4. Global Spawn / Breeder Card Component */
  .spawn-card {
      background-color: #F8F9FA;
      border: 1px solid #E2E8F0;
      border-radius: 12px;
      padding: 12px 16px;
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 12px;
  }

  /* 5. Betta Image Styling */
  .spawn-card-img {
      width: 44px;
      height: 44px;
      object-fit: cover;
      border-radius: 8px;
      border: 1.5px solid #CBD5E1;
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
      transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
  }

  .spawn-card-img:hover {
      transform: scale(1.08);
      box-shadow: 0 4px 12px rgba(0, 150, 255, 0.25);
      border-color: #0072FF;
  }

  .spawn-details h4 {
      margin: 0 0 4px 0;
      color: #0072FF !important;
  }

  .spawn-details p {
      margin: 1px 0;
      color: #4A5568 !important;
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
    "📊 Studio Dashboard",
    "🔍 Global Search Studio",
    "🐠 Fish Master Registry",
    "🐟 Breeder Registry",
    "🪣 Tank & Container Registry",
    "❤️ Pair & Spawn Tracker",
    "📝 Activity Log"
])

st.sidebar.markdown("---")
run_google_diagnostic()

# --- View Routing ---
if page == "📊 Studio Dashboard":
    render_dashboard()
elif page == "🔍 Global Search Studio":
    render_search_page()
elif page == "🐠 Fish Master Registry":
    render_fish_registry_page()
elif page == "🐟 Breeder Registry":
    render_breeder_page()
elif page == "🪣 Tank & Container Registry":
    render_tank_page()
elif page == "❤️ Pair & Spawn Tracker":
    render_spawn_page()
elif page == "📝 Activity Log":
    render_activity_log_page()
