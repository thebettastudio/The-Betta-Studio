# views/pairing_calendar_view.py
# Betta Farm Management System
# Session 32 — Pairing Calendar (new).
#
# Shows a unified calendar of:
#   • Planned pairings (pairing_plans table)
#   • Breeder recovery ends (derived from fish.breeder_status_started_at)
#   • Eggs due / Free swim est / Jarring est (derived from active spawns)
#
# Three views:
#   📅 Week  — 7-column grid, current week
#   📆 Month — compact 4–6 week grid
#   📋 List  — chronological stream
#
# Plan cards support Start / Move / Abort actions.

import datetime
from typing import Optional

import streamlit as st

from modules.spawn_manager import (
    get_calendar_events,
    list_upcoming_pairing_plans,
    start_pairing_plan,
    move_pairing_plan,
    abort_pairing_plan,
    list_pairing_plans,
)
from modules.fish_manager import (
    get_fish_age_days,
    format_fish_age,
    variety_of,
)
from modules.tank_registry import get_tank_dropdown_items


# ============================================================
# CONSTANTS
# ============================================================

EVENT_ICONS = {
    "plan":          "🔵",
    "recovery_end":  "🟢",
    "eggs_due":      "🥚",
    "free_swim_est": "🐟",
    "jarring_est":   "🫙",
}

EVENT_LABELS = {
    "plan":          "Planned pairing",
    "recovery_end":  "Breeder recovery ends",
    "eggs_due":      "Eggs due",
    "free_swim_est": "Free swim (est)",
    "jarring_est":   "Jarring window (est)",
}

EVENT_COLORS = {
    "plan":          "#DBEAFE",  # blue
    "recovery_end":  "#D1FAE5",  # green
    "eggs_due":      "#FEF3C7",  # amber
    "free_swim_est": "#E0E7FF",  # indigo
    "jarring_est":   "#F3E8FF",  # purple
}

EVENT_TEXT_COLORS = {
    "plan":          "#1E40AF",
    "recovery_end":  "#065F46",
    "eggs_due":      "#92400E",
    "free_swim_est": "#3730A3",
    "jarring_est":   "#6B21A8",
}

_MOVE_MESSAGE_KEY = "_calendar_move_pending_message"
_ABORT_MESSAGE_KEY = "_calendar_abort_pending_message"


# ============================================================
# MESSAGE QUEUE
# ============================================================

def _queue_message(key: str, kind: str, text: str) -> None:
    st.session_state[key] = {"kind": kind, "text": text}


def _drain_message(key: str) -> None:
    msg = st.session_state.pop(key, None)
    if not msg:
        return
    kind = msg.get("kind")
    text = msg.get("text") or ""
    if kind == "success":
        st.success(text)
    elif kind == "warning":
        st.warning(text)
    elif kind == "error":
        st.error(text)
    else:
        st.info(text)


# ============================================================
# HELPERS
# ============================================================

def _parse_date(iso: str) -> Optional[datetime.date]:
    try:
        return datetime.date.fromisoformat(str(iso)[:10])
    except Exception:
        return None


def _group_events_by_date(events: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for e in events:
        d = e.get("date") or ""
        out.setdefault(d, []).append(e)
    return out


def _render_legend():
    with st.expander("🔑 Legend", expanded=False):
        cols = st.columns(5)
        for i, (kind, label) in enumerate(EVENT_LABELS.items()):
            with cols[i]:
                st.markdown(
                    f'<div style="background:{EVENT_COLORS[kind]};'
                    f'color:{EVENT_TEXT_COLORS[kind]};border-radius:6px;'
                    f'padding:6px 8px;font-size:12px;text-align:center;">'
                    f'{EVENT_ICONS[kind]} {label}</div>',
                    unsafe_allow_html=True,
                )


def _render_plan_card(event: dict):
    """Render an actionable card for a pairing_plan event."""
    meta = event.get("meta") or {}
    plan_id = event.get("ref_id") or ""
    date_iso = event.get("date") or "?"

    male_id = meta.get("male_id")
    female_id = meta.get("female_id")
    tank_code = meta.get("tank_code")
    line_goal = (meta.get("line_goal") or "").strip()
    notes = (meta.get("notes") or "").strip()

    # Load the male/female rows to show IDs
    from database import get_fish_by_id
    male_row = get_fish_by_id(male_id) if male_id else None
    female_row = get_fish_by_id(female_id) if female_id else None

    male_sid = (male_row or {}).get("system_id") or "?"
    female_sid = (female_row or {}).get("system_id") or "?"

    with st.container(border=True):
        st.markdown(f"#### 🔵 Planned for `{date_iso}`")
        st.markdown(f"**{male_sid} × {female_sid}**")
        if tank_code:
            st.caption(f"📍 Tank: `{tank_code}`")
        if line_goal:
            st.caption(f"🎯 Goal: {line_goal}")
        if notes:
            st.caption(f"📝 {notes}")

        st.markdown("---")

        # ---- Action row 1: Start + Move ----
        col_start, col_move = st.columns(2)

        with col_start:
            if st.button(
                "▶️ Start Pairing",
                key=f"cal_start_{plan_id}",
                type="primary",
                use_container_width=True,
            ):
                spawn = start_pairing_plan(plan_id)
                if spawn:
                    _queue_message(
                        _MOVE_MESSAGE_KEY, "success",
                        f"Pairing started — spawn {spawn.get('system_id')} created.",
                    )
                else:
                    _queue_message(
                        _MOVE_MESSAGE_KEY, "error",
                        "Failed to start the plan. Check for conflicting statuses.",
                    )
                st.rerun()

        with col_move:
            with st.popover("📅 Move date", use_container_width=True):
                new_date = st.date_input(
                    "New planned date",
                    value=_parse_date(date_iso) or datetime.date.today(),
                    key=f"cal_move_date_{plan_id}",
                )
                if st.button(
                    "Save new date",
                    key=f"cal_move_save_{plan_id}",
                    use_container_width=True,
                    type="primary",
                ):
                    if move_pairing_plan(plan_id, str(new_date)):
                        _queue_message(
                            _MOVE_MESSAGE_KEY, "success",
                            f"Plan moved to {new_date}.",
                        )
                    else:
                        _queue_message(
                            _MOVE_MESSAGE_KEY, "error",
                            "Failed to move the plan.",
                        )
                    st.rerun()

        # ---- Action row 2: Abort ----
        with st.popover("🚫 Abort plan", use_container_width=True):
            st.markdown("**Abort this planned pairing**")
            abort_reason = st.text_area(
                "Reason (required)",
                placeholder="e.g. Not enough fry from current batch, tank needed elsewhere",
                key=f"cal_abort_reason_{plan_id}",
            )
            confirm_abort = st.checkbox(
                "I understand — abort this plan",
                key=f"cal_abort_confirm_{plan_id}",
            )
            if st.button(
                "Confirm Abort",
                key=f"cal_abort_save_{plan_id}",
                type="primary",
                use_container_width=True,
                disabled=not (confirm_abort and abort_reason.strip()),
            ):
                if abort_pairing_plan(plan_id, abort_reason.strip()):
                    _queue_message(
                        _ABORT_MESSAGE_KEY, "success",
                        f"Plan aborted — {abort_reason.strip()}.",
                    )
                else:
                    _queue_message(
                        _ABORT_MESSAGE_KEY, "error",
                        "Failed to abort the plan.",
                    )
                st.rerun()


def _render_event_badge(event: dict, compact: bool = False):
    """Small inline badge for an event (used in week/month grids)."""
    kind = event.get("kind") or "plan"
    icon = EVENT_ICONS.get(kind, "•")
    title = event.get("title") or ""
    bg = EVENT_COLORS.get(kind, "#F3F4F6")
    fg = EVENT_TEXT_COLORS.get(kind, "#374151")

    if compact:
        return (
            f'<div style="background:{bg};color:{fg};border-radius:6px;'
            f'padding:3px 6px;font-size:11px;margin:2px 0;'
            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
            f'{icon} {title[:30]}</div>'
        )
    return (
        f'<div style="background:{bg};color:{fg};border-radius:6px;'
        f'padding:6px 8px;font-size:12px;margin:2px 0;">'
        f'{icon} {title}</div>'
    )


# ============================================================
# VIEW: WEEK
# ============================================================

def _render_week_view(events: list[dict]):
    grouped = _group_events_by_date(events)

    # Week navigation
    if "cal_week_start" not in st.session_state:
        # Start on the Monday of the current week
        today = datetime.date.today()
        st.session_state["cal_week_start"] = today - datetime.timedelta(days=today.weekday())

    week_start = st.session_state["cal_week_start"]

    nav1, nav2, nav3 = st.columns([1, 4, 1])
    with nav1:
        if st.button("← Prev week", key="cal_week_prev", use_container_width=True):
            st.session_state["cal_week_start"] = week_start - datetime.timedelta(days=7)
            st.rerun()
    with nav2:
        week_end = week_start + datetime.timedelta(days=6)
        st.markdown(
            f"<div style='text-align:center;font-size:16px;font-weight:600;'>"
            f"Week of {week_start.strftime('%b %d')} – {week_end.strftime('%b %d, %Y')}"
            f"</div>",
            unsafe_allow_html=True,
        )
    with nav3:
        if st.button("Next week →", key="cal_week_next", use_container_width=True):
            st.session_state["cal_week_start"] = week_start + datetime.timedelta(days=7)
            st.rerun()

    st.markdown("---")

    cols = st.columns(7)
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    for i in range(7):
        day = week_start + datetime.timedelta(days=i)
        day_iso = day.isoformat()
        is_today = (day == datetime.date.today())

        with cols[i]:
            header_style = (
                "background:#FEE2E2;color:#991B1B;"
                if is_today
                else "background:#F3F4F6;color:#374151;"
            )
            st.markdown(
                f'<div style="{header_style}border-radius:8px;'
                f'padding:6px;text-align:center;font-weight:600;font-size:13px;'
                f'margin-bottom:6px;">'
                f'{day_names[i]}<br/>{day.strftime("%b %d")}</div>',
                unsafe_allow_html=True,
            )

            day_events = grouped.get(day_iso, [])
            if not day_events:
                st.markdown(
                    '<div style="color:#9CA3AF;font-size:11px;'
                    'text-align:center;padding:8px;">—</div>',
                    unsafe_allow_html=True,
                )
            else:
                for e in day_events:
                    st.markdown(_render_event_badge(e, compact=True), unsafe_allow_html=True)


# ============================================================
# VIEW: MONTH
# ============================================================

def _render_month_view(events: list[dict]):
    grouped = _group_events_by_date(events)

    if "cal_month_anchor" not in st.session_state:
        st.session_state["cal_month_anchor"] = datetime.date.today().replace(day=1)

    anchor = st.session_state["cal_month_anchor"]

    nav1, nav2, nav3 = st.columns([1, 4, 1])
    with nav1:
        if st.button("← Prev", key="cal_month_prev", use_container_width=True):
            anchor = (anchor - datetime.timedelta(days=1)).replace(day=1)
            st.session_state["cal_month_anchor"] = anchor
            st.rerun()
    with nav2:
        st.markdown(
            f"<div style='text-align:center;font-size:16px;font-weight:600;'>"
            f"{anchor.strftime('%B %Y')}</div>",
            unsafe_allow_html=True,
        )
    with nav3:
        if st.button("Next →", key="cal_month_next", use_container_width=True):
            # Advance to the 1st of next month
            if anchor.month == 12:
                anchor = datetime.date(anchor.year + 1, 1, 1)
            else:
                anchor = datetime.date(anchor.year, anchor.month + 1, 1)
            st.session_state["cal_month_anchor"] = anchor
            st.rerun()

    st.markdown("---")

    # First day of grid is Monday on or before the 1st
    first = anchor
    grid_start = first - datetime.timedelta(days=first.weekday())
    # 6 rows of 7 = 42 cells
    weeks = 6

    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    header_cols = st.columns(7)
    for i, name in enumerate(day_names):
        with header_cols[i]:
            st.markdown(
                f"<div style='text-align:center;font-weight:600;"
                f"color:#6B7280;font-size:12px;padding:4px;'>{name}</div>",
                unsafe_allow_html=True,
            )

    today = datetime.date.today()

    for w in range(weeks):
        row_cols = st.columns(7)
        for i in range(7):
            day = grid_start + datetime.timedelta(days=w * 7 + i)
            day_iso = day.isoformat()
            in_month = (day.month == anchor.month and day.year == anchor.year)
            is_today = (day == today)

            with row_cols[i]:
                border_color = "#EF4444" if is_today else "#E5E7EB"
                bg_color = "#FEF2F2" if is_today else ("#FFFFFF" if in_month else "#F9FAFB")
                text_color = "#111827" if in_month else "#9CA3AF"

                st.markdown(
                    f'<div style="border:1px solid {border_color};'
                    f'background:{bg_color};border-radius:6px;'
                    f'padding:4px;min-height:80px;margin-bottom:4px;">'
                    f'<div style="font-size:11px;font-weight:600;'
                    f'color:{text_color};">{day.day}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                day_events = grouped.get(day_iso, [])
                for e in day_events[:3]:  # cap at 3 per cell
                    st.markdown(
                        _render_event_badge(e, compact=True),
                        unsafe_allow_html=True,
                    )
                if len(day_events) > 3:
                    st.caption(f"+{len(day_events) - 3} more")


# ============================================================
# VIEW: LIST
# ============================================================

def _render_list_view(events: list[dict]):
    if not events:
        st.info("No events in the selected range.")
        return

    # Group by date, show plan cards separately from other event types
    grouped = _group_events_by_date(events)

    for date_iso in sorted(grouped.keys()):
        date_obj = _parse_date(date_iso)
        header = (
            date_obj.strftime("%A, %B %d, %Y")
            if date_obj else date_iso
        )
        st.markdown(f"### 📅 {header}")

        day_events = grouped[date_iso]

        # Plans first (actionable)
        plans = [e for e in day_events if e.get("kind") == "plan"]
        others = [e for e in day_events if e.get("kind") != "plan"]

        for e in plans:
            _render_plan_card(e)

        for e in others:
            kind = e.get("kind") or "plan"
            icon = EVENT_ICONS.get(kind, "•")
            label = EVENT_LABELS.get(kind, kind)
            st.markdown(
                f"- {icon} **{label}:** {e.get('title') or ''}"
                + (f" — _{e.get('detail')}_" if e.get("detail") else "")
            )

        st.markdown("")


# ============================================================
# PAGE
# ============================================================

def render_pairing_calendar_page():
    st.title("📅 Pairing Calendar")

    _drain_message(_MOVE_MESSAGE_KEY)
    _drain_message(_ABORT_MESSAGE_KEY)

    st.caption(
        "Upcoming pairings, breeder recovery windows, and estimated fry milestones."
    )

    # ---------- Top actions ----------
    top_col1, top_col2, top_col3 = st.columns([1, 1, 2])

    with top_col1:
        view_mode = st.radio(
            "View",
            options=["📅 Week", "📆 Month", "📋 List"],
            key="cal_view_mode",
            label_visibility="collapsed",
            horizontal=False,
        )

    with top_col2:
        days_ahead = st.number_input(
            "Days ahead",
            min_value=7, max_value=365, value=60, step=7,
            key="cal_days_ahead",
            label_visibility="collapsed",
        )

    with top_col3:
        _render_legend()

    # ---------- Load events ----------
    events = get_calendar_events(days_ahead=int(days_ahead))

    # Quick summary line
    plan_count = sum(1 for e in events if e.get("kind") == "plan")
    recovery_count = sum(1 for e in events if e.get("kind") == "recovery_end")
    spawn_events = sum(1 for e in events if e.get("kind") in ("eggs_due", "free_swim_est", "jarring_est"))

    if not events:
        st.info(
            "No events in the next "
            f"{int(days_ahead)} days. Plan a pairing from the "
            "**Start New Pairing** tab to see it here."
        )
        return

    st.markdown(
        f"**{len(events)}** events — "
        f"🔵 {plan_count} planned · "
        f"🟢 {recovery_count} recovery windows · "
        f"🐟 {spawn_events} spawn milestones"
    )

    st.markdown("---")

    # ---------- Render ----------
    if view_mode == "📅 Week":
        _render_week_view(events)
    elif view_mode == "📆 Month":
        _render_month_view(events)
    else:
        _render_list_view(events)


def render_pairing_calendar():
    """Alias entrypoint."""
    render_pairing_calendar_page()
