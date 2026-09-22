# views/search_view.py
import streamlit as st
from modules.breeder_registry import get_all_breeders
from modules.tank_registry import get_all_tanks
from modules.spawn_manager import get_all_spawns

def render_search_page():
    st.title("🔍 Global Search Studio")
    st.caption("Quickly locate any breeder, spawn batch, or container by typing an ID, tape code, variety, or location.")

    query = st.text_input("Type to search...", placeholder="e.g. BRD-M, GO-01, ST-01, Avatar, Spawn #001...").strip().lower()

    if not query:
        st.info("Enter a keyword or tape code above to search across all registries.")
        return

    # 1. Search Breeders
    breeders = get_all_breeders()
    matching_breeders = [
        b for b in breeders
        if query in b['id'].lower()
        or query in b['variety'].lower()
        or query in b['lineage'].lower()
        or query in b['status'].lower()
        or query in b.get('notes', '').lower()
    ]

    # 2. Search Spawns
    try:
        spawns = get_all_spawns()
    except Exception:
        spawns = []
        
    matching_spawns = [
        s for s in spawns
        if query in str(s.get('id', '')).lower()
        or query in str(s.get('pair_name', '')).lower()
        or query in str(s.get('male_id', '')).lower()
        or query in str(s.get('female_id', '')).lower()
        or query in str(s.get('status', '')).lower()
    ]

    # 3. Search Tanks/Containers
    tanks = get_all_tanks()
    matching_tanks = [
        t for t in tanks
        if query in t['id'].lower()
        or query in t['type'].lower()
        or query in t['location'].lower()
        or query in t['occupant'].lower()
        or query in t['status'].lower()
    ]

    st.markdown("---")
    st.subheader(f"Search Results for: *'{query}'*")

    tab_all, tab_breeders, tab_spawns, tab_tanks = st.tabs([
        f"All Results ({len(matching_breeders) + len(matching_spawns) + len(matching_tanks)})",
        f"🐟 Breeders ({len(matching_breeders)})",
        f"🥚 Spawns ({len(matching_spawns)})",
        f"🪣 Containers ({len(matching_tanks)})"
    ])

    with tab_all:
        if not (matching_breeders or matching_spawns or matching_tanks):
            st.warning("No records matched your query.")

    with tab_breeders:
        if not matching_breeders:
            st.caption("No matching breeders found.")
        for b in matching_breeders:
            with st.container(border=True):
                st.markdown(f"**Breeder ID:** `{b['id']}` ({b['sex']})")
                st.write(f"**Variety:** {b['variety']} | **Status:** `{b['status']}`")
                st.caption(f"Lineage: {b['lineage']} | Notes: {b.get('notes', 'N/A')}")

    with tab_spawns:
        if not matching_spawns:
            st.caption("No matching spawns found.")
        for s in matching_spawns:
            with st.container(border=True):
                st.markdown(f"**Spawn:** `{s.get('id', 'N/A')}` - {s.get('pair_name', '')}")
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
