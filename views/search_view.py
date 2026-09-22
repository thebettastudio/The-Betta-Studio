# views/search_view.py
import datetime
import streamlit as st
from modules.breeder_registry import get_all_breeders
from modules.tank_registry import get_all_tanks
from modules.spawn_manager import get_all_spawns

def parse_date(date_str):
    """Safely parses YYYY-MM-DD date strings."""
    try:
        return datetime.datetime.strptime(str(date_str).strip(), "%Y-%m-%d").date()
    except Exception:
        return None

def get_image_url(image_val):
    """
    Formats image value into a viewable URL.
    Handles direct web URLs or Google Drive File IDs.
    """
    if not image_val or not str(image_val).strip():
        return None
    val = str(image_val).strip()
    if val.startswith("http://") or val.startswith("https://"):
        return val
    # Assume it's a Google Drive File ID
    return f"https://drive.google.com/thumbnail?id={val}&sz=w800"

def render_search_page():
    st.title("🔍 Advanced Studio Search & Filters")
    st.caption("Locate breeders, spawn batches, and containers with live image previews and biological filters.")

    # Load All Data First to Extract Dynamic Options
    breeders = get_all_breeders()
    tanks = get_all_tanks()
    try:
        spawns = get_all_spawns()
    except Exception:
        spawns = []

    # --------------------------------------------------------------------------
    # DYNAMIC DATA EXTRACTION FOR FILTERS
    # --------------------------------------------------------------------------
    existing_varieties = sorted(list(set(
        [b.get('variety', '').strip() for b in breeders if b.get('variety')] +
        [s.get('variety', '').strip() for s in spawns if s.get('variety')]
    )))

    existing_tank_types = sorted(list(set(
        [t.get('type', '').strip() for t in tanks if t.get('type')]
    )))

    # Main Keyword Search
    query = st.text_input("🔍 Global Keyword Search", placeholder="Search by ID, tape code (e.g., GO-01), lineage, notes...").strip().lower()

    # Expandable Filter Panel
    with st.expander("🎛️ Advanced Filters (Grade, Variety, Dates, Tank Types, etc.)", expanded=False):
        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("**🐟 Breeder Filters**")
            filter_sex = st.multiselect("Sex", ["Male", "Female"])
            filter_grade = st.multiselect("Betta Grade", ["Show / Competition", "High Grade Breeder", "Standard Breeder", "Pet / Commercial Grade"])
            filter_variety = st.multiselect("Variety / Color Tag", options=existing_varieties)

        with col2:
            st.markdown("**🥚 Spawn Filters**")
            filter_batch_type = st.multiselect("Batch / Spawn Type", ["Pure Line", "Cross / Experimental", "F1 Lineage", "F2 Lineage", "Commercial Batch"])
            filter_spawn_status = st.multiselect("Spawn Status", ["Pairing", "Eggs / Free Swimming", "Fry Grow-Out", "Jarred / Separated", "Completed"])

        with col3:
            st.markdown("**🪣 Container & Date Filters**")
            filter_tank_type = st.multiselect("Tank / Container Type", options=existing_tank_types)
            filter_tank_status = st.multiselect("Container Status", ["Active", "Cleaning / Quarantine", "Empty / Idle", "Retired"])
            
            enable_dob_filter = st.checkbox("Filter by Date Range")
            if enable_dob_filter:
                dob_range = st.date_input("Date Range (DOB / Spawn Date)", value=(datetime.date(2025, 1, 1), datetime.date.today()))
            else:
                dob_range = None

    # --------------------------------------------------------------------------
    # 1. FILTER BREEDERS
    # --------------------------------------------------------------------------
    matching_breeders = []
    for b in breeders:
        b_text = f"{b.get('id','')} {b.get('variety','')} {b.get('lineage','')} {b.get('notes','')} {b.get('status','')}".lower()
        if query and query not in b_text:
            continue

        if filter_sex and b.get('sex', '').capitalize() not in filter_sex:
            continue

        if filter_grade:
            b_grade = b.get('grade', b.get('notes', ''))
            if not any(g.lower() in str(b_grade).lower() for g in filter_grade):
                continue

        if filter_variety and b.get('variety', '').strip() not in filter_variety:
            continue

        if dob_range and len(dob_range) == 2:
            b_dob = parse_date(b.get('dob', ''))
            if not b_dob or not (dob_range[0] <= b_dob <= dob_range[1]):
                continue

        matching_breeders.append(b)

    # --------------------------------------------------------------------------
    # 2. FILTER SPAWNS
    # --------------------------------------------------------------------------
    matching_spawns = []
    for s in spawns:
        s_text = f"{s.get('id','')} {s.get('pair_name','')} {s.get('male_id','')} {s.get('female_id','')} {s.get('variety','')} {s.get('notes','')} {s.get('status','')}".lower()
        if query and query not in s_text:
            continue

        if filter_batch_type:
            s_type = s.get('batch_type', s.get('notes', ''))
            if not any(bt.lower() in str(s_type).lower() for bt in filter_batch_type):
                continue

        if filter_variety and s.get('variety', '').strip() not in filter_variety:
            continue

        if filter_spawn_status and s.get('status', '') not in filter_spawn_status:
            continue

        if dob_range and len(dob_range) == 2:
            s_date = parse_date(s.get('spawn_date', ''))
            if not s_date or not (dob_range[0] <= s_date <= dob_range[1]):
                continue

        matching_spawns.append(s)

    # --------------------------------------------------------------------------
    # 3. FILTER TANKS / CONTAINERS
    # --------------------------------------------------------------------------
    matching_tanks = []
    for t in tanks:
        t_text = f"{t.get('id','')} {t.get('type','')} {t.get('location','')} {t.get('occupant','')} {t.get('notes','')} {t.get('status','')}".lower()
        if query and query not in t_text:
            continue

        if filter_tank_type and t.get('type', '').strip() not in filter_tank_type:
            continue

        if filter_tank_status and t.get('status', '') not in filter_tank_status:
            continue

        matching_tanks.append(t)

    # --------------------------------------------------------------------------
    # DISPLAY RESULTS WITH IMAGES
    # --------------------------------------------------------------------------
    st.markdown("---")
    total_results = len(matching_breeders) + len(matching_spawns) + len(matching_tanks)
    st.subheader(f"Results Found: {total_results}")

    tab_all, tab_breeders, tab_spawns, tab_tanks = st.tabs([
        f"All Results ({total_results})",
        f"🐟 Breeders ({len(matching_breeders)})",
        f"🥚 Spawns ({len(matching_spawns)})",
        f"🪣 Containers ({len(matching_tanks)})"
    ])

    with tab_all:
        if total_results == 0:
            st.warning("No records matched your search query and filters.")

    # BREEDERS TAB
    with tab_breeders:
        if not matching_breeders:
            st.caption("No matching breeders found.")
        for b in matching_breeders:
            with st.container(border=True):
                img_url = get_image_url(b.get('image_id') or b.get('photo_id') or b.get('image_url'))
                if img_url:
                    col_img, col_info, col_extra = st.columns([1, 2, 1])
                    with col_img:
                        st.image(img_url, use_container_width=True)
                else:
                    col_info, col_extra = st.columns([3, 1])

                with col_info:
                    st.markdown(f"### 🐟 `{b['id']}` ({b.get('sex', 'N/A')})")
                    st.write(f"**Variety:** {b.get('variety', 'N/A')} | **Status:** `{b.get('status', 'N/A')}`")
                    st.caption(f"Lineage: {b.get('lineage', 'N/A')} | DOB: {b.get('dob', 'N/A')}")
                with col_extra:
                    if b.get('notes'):
                        st.info(f"**Notes:** {b['notes']}")

    # SPAWNS TAB
    with tab_spawns:
        if not matching_spawns:
            st.caption("No matching spawns found.")
        for s in matching_spawns:
            with st.container(border=True):
                img_url = get_image_url(s.get('image_id') or s.get('photo_id') or s.get('image_url'))
                if img_url:
                    col_img, col_info = st.columns([1, 3])
                    with col_img:
                        st.image(img_url, use_container_width=True)
                else:
                    col_info = st.container()

                with col_info:
                    st.markdown(f"### 🥚 Spawn `{s.get('id', 'N/A')}` - {s.get('pair_name', '')}")
                    st.write(f"**Parents:** `{s.get('male_id')}` × `{s.get('female_id')}` | **Status:** `{s.get('status')}`")
                    st.caption(f"Spawn Date: {s.get('spawn_date', 'N/A')} | Notes: {s.get('notes', 'N/A')}")

    # CONTAINERS TAB
    with tab_tanks:
        if not matching_tanks:
            st.caption("No matching containers found.")
        for t in matching_tanks:
            with st.container(border=True):
                qr_url = get_image_url(t.get('qr_id'))
                if qr_url:
                    col_qr, col_info = st.columns([1, 3])
                    with col_qr:
                        st.image(qr_url, caption="Container QR Tag", width=120)
                else:
                    col_info = st.container()

                with col_info:
                    st.markdown(f"### 🏷️ Tape Tag: `{t['location']}`")
                    st.caption(f"System ID: `{t['id']}`")
                    st.write(f"**Type:** {t['type']} | **Capacity:** {t['capacity']} L | **Status:** `{t['status']}`")
                    st.write(f"🐟 **Occupant:** `{t['occupant'] or 'Empty'}`")
                    if t.get('notes'):
                        st.caption(f"📝 {t['notes']}")
