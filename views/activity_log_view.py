import streamlit as st
from modules.activity_logger import fetch_activity_logs

def render_activity_log_page():
    st.header("📋 Farm Activity Log")
    st.caption("View real-time daily log entries and uploaded farm images synced with Google Drive.")

    if st.button("🔄 Refresh Logs"):
        st.rerun()

    logs = fetch_activity_logs()

    if not logs:
        st.info("No activity logs recorded yet.")
    else:
        for log in reversed(logs):  # Show newest first
            with st.expander(f"[{log['timestamp']}] {log['action_type']}"):
                st.write(f"**Description:** {log['description']}")
                if log.get('photo_url'):
                    st.markdown(f"📷 [View Photo in Google Drive]({log['photo_url']})")
