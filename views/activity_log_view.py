# views/activity_log_view.py
# Betta Farm Management System
# Session 14 — Ported to Supabase. Reads from activity_log table.

import datetime
from typing import Optional

import streamlit as st

from modules.activity_logger import (
    fetch_activity_logs,
    filter_logs,
    distinct_action_types,
    distinct_entity_types,
)
from modules.photo_service import photo_url


# ============================================================
# ACTION / ENTITY ICONS
# ============================================================

ACTION_ICONS = {
    "fish_registered":        "🐟",
    "fish_updated":           "✏️",
    "fish_deleted":           "🗑️",
    "fish_promoted":          "⭐",
    "breeder_retired":        "🚫",
    "tank_registered":        "🪣",
    "tank_updated":           "✏️",
    "tank_assigned":          "📥",
    "tank_unassigned":        "📤",
    "tank_deleted":           "🗑️",
    "spawn_created":          "💞",
    "spawn_pending_success":  "🥚",
    "spawn_free_swimming":    "🏊",
    "spawn_failed":           "❌",
    "spawn_completed":        "✅",
    "spawn_updated":          "✏️",
    "spawn_deleted":          "🗑️",
}

ENTITY_ICONS = {
    "fish":  "🐟",
    "tank":  "🪣",
    "spawn": "🥚",
}


def _action_icon(action_type: str) -> str:
    return ACTION_ICONS.get(action_type, "•")


def _entity_icon(entity_type: Optional[str]) -> str:
    return ENTITY_ICONS.get(entity_type or "", "")


def _format_ts(ts) -> str:
    """Format an ISO timestamp into a readable string."""
    if not ts:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)


# ============================================================
# ENTRY RENDERER
# ============================================================

def _render_entry(entry: dict):
    action = entry.get("action_type") or "—"
    icon = _action_icon(action)
    entity = entry.get("entity_type")
    e_icon = _entity_icon(entity)
    description = entry.get("description") or "—"
    ts = _format_ts(entry.get("ts") or entry.get("created_at") or "")

    with st.container(border=True):
        col_main, col_img = st.columns([4, 1])

        with col_main:
            st.markdown(f"**{icon} {description}**")
            badge_parts = []
            if ts:
                badge_parts.append(f"🕐 {ts}")
            if action and action != "—":
                badge_parts.append(f"`{action}`")
            if entity:
                badge_parts.append(f"{e_icon} {entity}")
            if badge_parts:
                st.caption(" • ".join(badge_parts))

        with col_img:
            pid = entry.get("photo_id")
            purl = entry.get("photo_url")
            if purl:
                st.image(purl, use_container_width=True)
            elif pid:
                st.image(photo_url(pid), use_container_width=True)


# ============================================================
# PAGE
# ============================================================

def render_activity_log_page():
    st.title("📜 Activity Log")
    st.caption("Every action recorded by the system. Newest first.")

    all_logs = fetch_activity_logs(limit=500)

    if not all_logs:
        st.info("No activity recorded yet.")
        return

    # ---- Filters ----
    col_q, col_a, col_e, col_limit = st.columns([2, 1, 1, 1])

    with col_q:
        query = st.text_input(
            "🔍 Search",
            placeholder="Search descriptions, actions, entities...",
        ).strip()

    with col_a:
        action_options = ["All"] + distinct_action_types(all_logs)
        action_filter = st.selectbox("Action Type", options=action_options)

    with col_e:
        entity_options = ["All"] + distinct_entity_types(all_logs)
        entity_filter = st.selectbox("Entity Type", options=entity_options)

    with col_limit:
        show_limit = st.selectbox("Show", options=[25, 50, 100, 250, 500], index=1)

    # Apply filters
    filtered = filter_logs(
        all_logs,
        query=query,
        action_type="" if action_filter == "All" else action_filter,
        entity_type="" if entity_filter == "All" else entity_filter,
    )

    filtered = filtered[:show_limit]

    st.markdown("---")
    st.caption(f"Showing **{len(filtered)}** of **{len(all_logs)}** total log entries.")

    if not filtered:
        st.warning("No log entries matched your filters.")
        return

    for entry in filtered:
        _render_entry(entry)


def render_activity_logger():
    """Alias entrypoint (matches old module name)."""
    render_activity_log_page()
