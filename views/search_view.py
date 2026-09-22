# views/search_view.py
import datetime
import streamlit as st
from modules.breeder_registry import get_all_breeders
from modules.tank_registry import get_all_tanks
from modules.spawn_manager import get_all_spawns

def render_search_page():
    st.title("🔍 Global Search Studio")
    st.caption("Locate breeders, spawns, and containers with live text search and detailed filter attributes.")

    # 1. MAIN KEYWORD SEARCH BAR
    query = st.text_input("🔍 Search Keyword / Tape Code...", placeholder="e.g. BRD-M, GO-01, Avatar, HMKP, High Grade...").strip().lower()

    # 2. FILTER EXPANDER PANEL
    with st.expander("🎛️ Filter Options (Variety, Grade, Tank Type, DOB, Batch Type)", expanded=False):
        col1, col2, col3 = st.columns(3)

        with col1:
            filter_sex = st.selectbox("Fish Sex / Type", ["All", "Male", "Female"])
            filter_grade = st.selectbox("Betta Grade", ["All", "Show / Competition Grade", "Breeder Grade", "Commercial / Pet Grade", "Unsorted / Young"])

        with col2:
            filter_tank_type = st.selectbox("Tank / Container Type", [
                "All",
                "Grow-Out Planggana (Large)",
                "Spawning Planggana (Small)",
                "6-Liter Water Bottle",
                "Empi (Emperador) Glass / Jar",
                "Glass Aquarium",
                "Sorority / Female Basin",
                "Quarantine / Treatment Jar"
            ])
            filter_batch_type = st.selectbox("Spawn Batch Type", ["All", "F1 Lineage", "F2 Lineage", "Outcross", "Test Spawn"])

        with col3:
            st.write("📅 Date Range / DOB Filter")
            use_date_filter = st.checkbox("Filter by Date Range")
            start_date = st.date_input("From Date", value=datetime.date(2025, 1, 1))
            end_date = st.date_input("To Date", value=datetime.date.today())

    # Fetch Data
    breeders = get_all_breeders()
    tanks = get_all_tanks()
    try:
        spawns = get_all_spawns()
    except Exception:
        spawns = []

    # ==============================================================================
    # FILTER LOGIC
    # ==============================================================================

    # --- FILTER BREEDERS ---
    matching_breeders = []
    for b in breeders:
        # Keyword check
        b_text = f"{b['id']} {b['variety']} {b['lineage']} {b['status']} {b.get('notes', '')}".lower()
        if query and query not in b_text:
            continue

        # Sex check
        if filter_sex != "All" and b['sex'].lower() != filter_sex.lower():
            continue

        # Grade check (matches grade mentioned in variety/notes)
        if filter_grade != "All" and filter_grade.lower() not in b_text:
            continue

        # Date of Birth check
        if use_date_filter and b.get('dob'):
            try:
                b_dob = datetime.datetime.strptime(b['dob'], "%Y-%m-%d").date()
                if not (start_date <= b_dob <= end_date):
                    continue
            except ValueError:
                pass

        matching_breeders.append(b)

    # --- FILTER SPAWNS ---
    matching_spawns = []
    for s in spawns:
        s_text = f"{s.get('id', '')} {s.get('pair_name', '')} {s.get('male_id', '')} {s.get('female_id', '')} {s.get('status', '')} {s.get('notes', '')}".lower()
        if query and query not in s_text:
            continue

        # Batch Type check
        if filter_batch_type != "All" and filter_batch_type.lower() not in s_text:
            continue

        # Date check
        if use_date_filter and s.get('spawn_date'):
            try:
                s_date = datetime.datetime.strptime(s['spawn_date'], "%Y-%m-%d").date()
                if not (start_date <= s_date <= end_date):
                    continue
            except ValueError:
                pass

        matching_spawns.append(s)

    # --- FILTER TANKS / CONTAINERS ---
    matching_tanks = []
    for t in tanks:
        t_text = f"{t['id']} {t['type']} {t['location']} {t['occupant']} {t['status']} {t.get('notes', '')}".lower()
        if query and query not in t_text:
            continue

        # Tank Type check
        if filter_tank_type != "All" and filter_tank_type.lower() not in t['type'].lower():
            continue

        matching_tanks.append(t)

    # ==============================================================================
    # DISPLAY RESULTS
    # ==============================================================================
    st.markdown("---")
    total_results = len(matching_breeders) + len(matching_spawns) + len(matching_tanks)
    st.subheader(f"Matching Results ({total_results})")

    tab_all, tab_breeders, tab_spawns, tab_tanks = st.tabs([
        f"All Results ({total_results})",
        f"🐟 Breeders ({len(matching_breeders)})",
        f"🥚 Spawns ({len(matching_spawns)})",
        f"🪣 Containers ({len(matching_tanks)})"
    ])

    with tab_all:
        if total_results == 0:
            st.warning("No records matched your search criteria or filters.")

    with tab_breeders:
        if not matching_breeders:
            st.caption("No matching breeders found.")
        for b in matching_breeders:
            with st.container(border=True):
                st.markdown(f"**Breeder ID:** `{b['id']}` ({b['sex']})")
                st.write(f"**Variety:** {b['variety']} | **Status:** `{b['status']}`")
                if b.get('dob'):
                    st.caption(f"🗓️ **DOB:** {b['dob']}")
                st.caption(f"Lineage: {b['lineage']} | Notes: {b.get('notes', 'N/A')}")

    with tab_spawns:
        if not matching_spawns:
            st.caption("No matching spawns found.")
        for s in matching_spawns:
            with st.container(border=True):
                st.markdown(f"**Spawn ID:** `{s.get('id', 'N/A')}` - {s.get('pair_name', '')}")
                st.write(f"**Parents:** `{s.get('male_id')}` × `{s.get('female_id')}`")
                st.caption(f"Status: {s.get('status')} | Date: {s.get('spawn_date')}")

    with tab_tanks:
        if not matching_tanks:
            st.caption("No matching containers found.")
        for t in matching_tanks:
            with st.container(border=True):
                st.markdown(f"**Tape Code / Location:** `{t['location']}`")
                st.caption(f"System ID: `{t['id']}`")
                st.write(f"**Type:** {t['type']} | **Occupant:** `{t['occupant'] or 'Empty'}`")
                st.caption(f"Status: {t['status']} | Notes: {t.get('notes', 'N/A')}")
