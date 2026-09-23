# views/lineage_view.py
# Betta Farm Management System
# Session 16 — Lineage tree viewer (ancestors + descendants).

import streamlit as st

from database import get_all_fish
from modules.lineage import (
    get_ancestors,
    get_descendants,
    count_ancestors,
    count_descendants,
    has_any_lineage,
    tree_to_dot_ancestors,
    tree_to_dot_descendants,
    tree_to_text_ancestors,
    tree_to_text_descendants,
)
from modules.photo_service import photo_url


# ============================================================
# HELPERS
# ============================================================

def _fish_label(f: dict) -> str:
    sid = f.get("system_id") or "?"
    variety = f.get("variety") or "—"
    gender = f.get("gender") or "?"
    return f"{sid} | {variety} ({gender})"


def _render_focal_fish(fish: dict):
    """Small card showing the currently-selected fish."""
    with st.container(border=True):
        col_img, col_info = st.columns([1, 3])

        with col_img:
            if fish.get("photo_id"):
                st.image(photo_url(fish["photo_id"]), use_container_width=True)
            else:
                st.caption("📷 *No photo*")

        with col_info:
            st.markdown(f"### 🐟 `{fish.get('system_id')}`")
            st.write(
                f"**{fish.get('gender') or '?'}** | "
                f"Variety: **{fish.get('variety') or '—'}** | "
                f"Line: `{fish.get('line_code') or '—'}` (`{fish.get('generation') or 'P1'}`)"
            )
            if fish.get("grade"):
                st.caption(f"Grade: {fish['grade']}")
            if fish.get("origin"):
                st.caption(f"Origin: {fish['origin']}")


# ============================================================
# TAB RENDERERS
# ============================================================

def _render_ancestors_tab(fish: dict):
    tree = get_ancestors(fish["id"], depth=4)

    if not tree or not (fish.get("sire_id") or fish.get("dam_id")):
        st.info(
            "This fish has no known parents. Lineage cannot be traced further. "
            "Update parent fields if this is a batch-born fish."
        )
        return

    known = count_ancestors(tree) - 1  # exclude focal fish
    st.caption(f"Known ancestors within 4 generations: **{known}**")

    # Graphviz chart
    try:
        dot = tree_to_dot_ancestors(tree)
        st.graphviz_chart(dot, use_container_width=True)
    except Exception as e:
        st.warning(f"Could not render diagram: {e}")

    # Text fallback
    with st.expander("📄 Text view (accessible)"):
        lines = tree_to_text_ancestors(tree)
        st.code("\n".join(lines), language=None)


def _render_descendants_tab(fish: dict):
    tree = get_descendants(fish["id"], depth=4)

    if not tree or not tree.get("children"):
        st.info(
            "No known descendants. Fish become descendants when they are "
            "registered with this fish as sire or dam (either directly or "
            "via a spawn)."
        )
        return

    known = count_descendants(tree) - 1  # exclude focal fish
    st.caption(f"Known descendants within 4 generations: **{known}**")

    # Graphviz chart
    try:
        dot = tree_to_dot_descendants(tree)
        st.graphviz_chart(dot, use_container_width=True)
    except Exception as e:
        st.warning(f"Could not render diagram: {e}")

    # Text fallback
    with st.expander("📄 Text view (accessible)"):
        lines = tree_to_text_descendants(tree)
        st.code("\n".join(lines), language=None)


# ============================================================
# PAGE
# ============================================================

def render_lineage_page():
    st.title("🌳 Lineage Tree")
    st.caption("Trace ancestors and descendants across up to 4 generations.")

    all_fish = get_all_fish()
    if not all_fish:
        st.info("No fish registered yet.")
        return

    # --- Fish selector ---
    fish_by_id = {f["id"]: f for f in all_fish}

    # Default selection: session state set by fish_registry_view button
    default_id = st.session_state.get("lineage_fish_id")
    if default_id not in fish_by_id:
        default_id = all_fish[0]["id"]

    # Sort options alphabetically by system_id for the dropdown
    sorted_fish = sorted(all_fish, key=lambda f: f.get("system_id") or "")
    option_ids = [f["id"] for f in sorted_fish]
    default_index = option_ids.index(default_id) if default_id in option_ids else 0

    selected_id = st.selectbox(
        "Select Fish",
        options=option_ids,
        index=default_index,
        format_func=lambda fid: _fish_label(fish_by_id[fid]),
        key="lineage_select",
    )

    # Update session state so subsequent renders remember
    st.session_state["lineage_fish_id"] = selected_id

    selected_fish = fish_by_id[selected_id]
    _render_focal_fish(selected_fish)

    st.markdown("---")

    # --- Tabs ---
    tab_anc, tab_desc = st.tabs([
        "⬆️ Ancestors",
        "⬇️ Descendants",
    ])

    with tab_anc:
        _render_ancestors_tab(selected_fish)

    with tab_desc:
        _render_descendants_tab(selected_fish)


def render_lineage():
    """Alias entrypoint."""
    render_lineage_page()
