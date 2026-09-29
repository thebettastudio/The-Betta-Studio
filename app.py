# app.py
# Betta Farm Management System
# Session 17 — Navigation cleanup, Supabase diagnostic, new pages added.
# Session 21 — Added Lines & Varieties page.
# Session 25 — Added Inheritance Analysis page.
# Session 26B — WebRTC test page removed from production.
# Session 26E — Temp Video Debug page added to sidebar nav.
#
# Session 27B — Round 3A:
#   • Removed the Video Debug nav entry + import.
#   • Auto-run process_breeder_transitions() on app load.
#
# Session 32 (this revision) — PAIRING CALENDAR:
#   • Added import + sidebar entry + routing for the new
#     📅 Pairing Calendar page.

import datetime

import streamlit as st

# ---- Views ----
from views.breeder_view         import render_breeder_page
from views.fish_registry_view   import render_fish_registry_page
from views.spawn_view           import render_spawn_page
from views.activity_log_view    import render_activity_log_page
from views.tank_view            import render_tank_page
from views.search_view          import render_search_page
from views.fry_batch_view       import render_fry_batch_page
from views.lineage_view         import render_lineage_page
from views.lines_view           import render_lines_page
from views.inheritance_view     import render_inheritance_page
from views.pairing_calendar_view import render_pairing_calendar_page
from modules.dashboard          import render_dashboard


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="The Betta Studio",
    page_icon="🐟",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# GLOBAL STYLING
# ============================================================

st.markdown("""
<style>
  /* 1. Base App Light Background & Dark Text */
  .stApp {
    background-color: #FFFFFF;
    color: #1E2022;
  }

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


# ============================================================
# SESSION-LOAD SIDE EFFECTS
# ============================================================

def _run_load_time_transitions():
    """
    Run once per session: advance any breeder_status that has
    exceeded its duration (Session 27A Q2).
    Idempotent — safe to run on every load.
    """
    if st.session_state.get("_breeder_transitions_ran"):
        return
    try:
        from modules.fish_manager import process_breeder_transitions
        flipped = process_breeder_transitions()
        if flipped:
            st.toast(f"⚙️ Auto-flipped {flipped} breeder status(es).", icon="🔁")
    except Exception as e:
        print(f"process_breeder_transitions issue: {e}")
    st.session_state["_breeder_transitions_ran"] = True


# ============================================================
# SUPABASE DIAGNOSTIC (sidebar)
# ============================================================

def run_supabase_diagnostic():
    """Live health check for Supabase connection + Google Drive."""
    with st.sidebar.expander("🩺 System Diagnostics"):
        if st.button("Test Supabase Connection", use_container_width=True):
            with st.status("Testing services...", expanded=True) as status:
                # 1. Supabase
                try:
                    st.write("🗄️ Connecting to Supabase...")
                    from database import get_all_fish
                    fish = get_all_fish()
                    st.write(f"✅ Supabase OK — {len(fish)} fish rows")
                except Exception as e:
                    status.update(label="Supabase Failure", state="error")
                    st.error(f"Supabase error: {e}")
                    return

                # 2. Google Drive
                try:
                    st.write("📁 Testing Google Drive auth...")
                    from modules.drive_service import get_google_services
                    drive_service, _ = get_google_services()
                    st.write("✅ Google Drive credentials valid")
                except Exception as e:
                    status.update(label="Google Drive Failure", state="error")
                    st.error(f"Drive error: {e}")
                    return

                status.update(label="All services operational!", state="complete")

        st.divider()
        st.caption(
            f"Session: 32 · Build: {datetime.date.today().isoformat()}"
        )


# ============================================================
# SIDEBAR NAV
# ============================================================

st.sidebar.title("🐟 The Betta Studio")

page = st.sidebar.radio("Navigation", [
    "📊 Studio Dashboard",
    "🔍 Global Search Studio",
    "🐠 Fish Master Registry",
    "🐟 Breeder Registry",
    "🪣 Tank & Container Registry",
    "❤️ Pair & Spawn Tracker",
    "📅 Pairing Calendar",
    "🐣 Fry Batch Tracking",
    "🌳 Lineage Tree",
    "🧬 Lines & Varieties",
    "🧬 Inheritance",
    "📝 Activity Log",
])

st.sidebar.markdown("---")
run_supabase_diagnostic()


# ============================================================
# LOAD-TIME TRANSITIONS
# ============================================================

_run_load_time_transitions()


# ============================================================
# ROUTING
# ============================================================

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
elif page == "📅 Pairing Calendar":
    render_pairing_calendar_page()
elif page == "🐣 Fry Batch Tracking":
    render_fry_batch_page()
elif page == "🌳 Lineage Tree":
    render_lineage_page()
elif page == "🧬 Lines & Varieties":
    render_lines_page()
elif page == "🧬 Inheritance":
    render_inheritance_page()
elif page == "📝 Activity Log":
    render_activity_log_page()
