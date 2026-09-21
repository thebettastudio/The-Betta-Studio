# views/activity_log_view.py
import streamlit as st
from modules.activity_logger import fetch_activity_logs

def render_activity_log_page():
    st.title("📋 Activity Log")
    st.write("Recent activities, logs, and system updates.")

    logs = fetch_activity_logs()

    if not logs:
        st.info("No activity records found.")
        return

    # Display logs in reverse order (newest first)
    for log in reversed(logs):
        with st.container():
            st.markdown(f"**{log['timestamp']}** — *{log['action_type']}*")
            st.write(log['description'])
            if log['photo_url']:
                st.image(log['photo_url'], caption="Log Photo", width=300)
            st.divider()
