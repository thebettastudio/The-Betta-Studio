# modules/dashboard.py
# Betta Farm Management System
# Session 13 — Ported to Supabase via database + module helpers.
#
# Session 26H.7 — Step 6 (this revision):
#   • KPI row updated for 5-status model:
#       - Available = Empty / Idle only
#       - Reserved count added
#       - Occupied count added
#       - "Available Jars" = Empty/Idle tanks with purpose=Jarring
#   • ⚠️ Action Needed panel: expiring reservations
#   • ⭐ Starred Fish panel: your high-expectation fish
#   • 🫙 Jarring Capacity indicator
#   • All counts computed from the same loaded lists (no drift)

import datetime as _dt

import streamlit as st
import pandas as pd
import plotly.express as px

from database import (
    get_all_fish,
    get_all_tanks,
    get_all_spawns,
    get_dashboard_counts,
    get_expiring_reservations,
    get_tank_occupants,
)
from modules.photo_service import photo_url


# ============================================================
# HELPERS
# ============================================================

def _resolve_tank_location(tank_id, tank_by_id: dict) -> str:
    """Given a tank uuid, return its location_code. Fallback: 'Unassigned'."""
    if not tank_id:
        return "Unassigned"
    t = tank_by_id.get(tank_id)
    return (t.get("location_code") if t else None) or "Unassigned"


def _tanks_dataframe(tanks: list) -> pd.DataFrame:
    """Build a display-ready dataframe from tank rows."""
    if not tanks:
        return pd.DataFrame()
    rows = []
    for t in tanks:
        rows.append({
            "System ID": t.get("system_id") or t.get("id"),
            "Location": t.get("location_code") or "",
            "Type": t.get("tank_type") or "",
            "Capacity (L)": t.get("capacity_liters") or 0,
            "Status": t.get("status") or "",
            "Purpose": t.get("purpose") or "",
            "Occupant": t.get("occupant_label") or "",
            "Reserved For": t.get("reserved_for") or "",
            "Reserved Until": t.get("reserved_until") or "",
            "Notes": t.get("notes") or "",
        })
    return pd.DataFrame(rows)


def _breeders_dataframe(fish: list) -> pd.DataFrame:
    """Build a display-ready dataframe from breeder fish rows."""
    breeders = [f for f in fish if f.get("is_breeder")]
    if not breeders:
        return pd.DataFrame()
    rows = []
    for f in breeders:
        rows.append({
            "System ID": f.get("system_id") or "",
            "Gender": f.get("gender") or "",
            "Variety": f.get("variety") or "",
            "Line": f.get("line_code") or "",
            "Gen": f.get("generation") or "",
            "Grade": f.get("grade") or "",
            "Breeder Status": f.get("breeder_status") or "",
            "Location": f.get("location") or "",
            "⭐": "⭐" if f.get("is_starred") else "",
            "Notes": f.get("notes") or "",
        })
    return pd.DataFrame(rows)


def _spawns_dataframe(spawns: list, tank_by_id: dict) -> pd.DataFrame:
    """Build a display-ready dataframe from spawn rows."""
    if not spawns:
        return pd.DataFrame()
    rows = []
    for s in spawns:
        rows.append({
            "Spawn ID": s.get("system_id") or s.get("id"),
            "Code": s.get("spawn_code") or "",
            "Line": s.get("line_code") or "",
            "Gen": s.get("generation") or "",
            "Male": s.get("male_id") or "",
            "Female": s.get("female_id") or "",
            "Pairing Date": s.get("pairing_date") or "",
            "Status": s.get("status") or "",
            "Batch": s.get("batch_name") or "",
            "Free Swim": s.get("free_swimming_date") or "",
            "Fry (est)": s.get("estimated_fry_count") or 0,
            "Fry (final)": s.get("fry_count") or 0,
            "Tank": _resolve_tank_location(s.get("tank_id"), tank_by_id),
            "Goal": s.get("line_goal") or "",
            "Notes": s.get("notes") or "",
        })
    return pd.DataFrame(rows)


# ============================================================
# SECTION: ACTION NEEDED (expiring reservations)
# ============================================================

def _render_action_needed(tanks: list):
    expiring = get_expiring_reservations(days_ahead=3)
    if not expiring:
        return

    today = _dt.date.today()

    with st.container(border=True):
        st.markdown(f"### ⚠️ Action Needed — {len(expiring)} reservation(s) expiring soon")

        for t in expiring[:10]:
            loc = t.get("location_code") or "?"
            reason = t.get("reserved_reason") or "reserved"
            rfor = t.get("reserved_for")
            until_raw = t.get("reserved_until")

            days_left_txt = ""
            if until_raw:
                try:
                    until = _dt.date.fromisoformat(str(until_raw))
                    delta = (until - today).days
                    if delta < 0:
                        days_left_txt = f" — **expired {abs(delta)}d ago**"
                    elif delta == 0:
                        days_left_txt = " — **expires today**"
                    else:
                        days_left_txt = f" — in {delta}d"
                except Exception:
                    pass

            line = f"🟡 **`{loc}`** — {reason}"
            if rfor:
                line += f" (for {rfor})"
            line += days_left_txt
            st.markdown(line)

        if len(expiring) > 10:
            st.caption(f"... and {len(expiring) - 10} more")

        st.caption("→ Open **🪣 Tank & Container Registry** to review or cancel.")


# ============================================================
# SECTION: STARRED FISH
# ============================================================

def _render_starred_panel(fish: list):
    starred = [f for f in fish if f.get("is_starred")]
    if not starred:
        return

    with st.container(border=True):
        st.markdown(f"### ⭐ Starred Fish ({len(starred)})")
        st.caption("Your high-expectation fish. Tanks holding them show ⭐ automatically.")

        cols = st.columns(min(4, len(starred)))
        for idx, f in enumerate(starred[:8]):
            with cols[idx % 4]:
                if f.get("photo_id"):
                    st.image(photo_url(f["photo_id"]), use_container_width=True)
                else:
                    st.markdown(
                        '<div style="width:100%;aspect-ratio:4/3;background:#F3F4F6;'
                        'border-radius:10px;display:flex;align-items:center;'
                        'justify-content:center;color:#9CA3AF;font-size:12px;">'
                        'No Photo</div>',
                        unsafe_allow_html=True,
                    )
                st.markdown(f"**{f.get('system_id') or '?'}**")
                st.caption(
                    f"{f.get('gender') or '?'} · {f.get('variety') or '—'}"
                )
                if f.get("starred_reason"):
                    st.caption(f"⭐ *{f['starred_reason']}*")

        if len(starred) > 8:
            st.caption(f"... and {len(starred) - 8} more — filter by ⭐ in Fish Registry.")


# ============================================================
# SECTION: JARRING CAPACITY
# ============================================================

def _render_jarring_capacity(tanks: list):
    jarring_empty = [
        t for t in tanks
        if (t.get("purpose") or "").strip() == "Jarring"
        and (t.get("status") or "").strip() == "Empty / Idle"
    ]
    if not jarring_empty:
        return

    with st.container(border=True):
        n = len(jarring_empty)
        st.markdown(f"### 🫙 Jarring Capacity: **{n}** empty jar(s) ready")
        st.caption(
            "Empty/Idle tanks with purpose = **Jarring**. "
            "These are ready for individual male/female jarring."
        )

        # Show first 20 tape codes as a compact list
        codes = [t.get("location_code") or "?" for t in jarring_empty]
        if codes:
            display = " · ".join(f"`{c}`" for c in codes[:20])
            if len(codes) > 20:
                display += f" ... (+{len(codes) - 20} more)"
            st.markdown(display)


# ============================================================
# DASHBOARD
# ============================================================

def render_dashboard():
    st.title("📊 Studio Overview Dashboard")
    st.caption("Central hub for tanks, breeder inventory, active spawning pairs, and facility metrics.")

    # --------------------------------------------------------------------------
    # 1. DATA FETCH
    # --------------------------------------------------------------------------
    fish = get_all_fish() or []
    tanks = get_all_tanks() or []
    spawns = get_all_spawns() or []

    tank_by_id = {t["id"]: t for t in tanks}
    fish_by_id = {f["id"]: f for f in fish}

    # --------------------------------------------------------------------------
    # 2. KPI METRICS
    # --------------------------------------------------------------------------
    counts = get_dashboard_counts() or {}

    total_tanks = counts.get("total_tanks", len(tanks))
    available_tanks = counts.get("available_tanks", 0)
    reserved_tanks = counts.get("reserved_tanks", 0)
    occupied_tanks = counts.get("occupied_tanks", 0)
    total_breeders = counts.get("total_breeders", 0)
    male_breeders = counts.get("male_breeders", 0)
    female_breeders = counts.get("female_breeders", 0)
    total_spawns = counts.get("total_spawns", len(spawns))
    active_spawns = counts.get("active_spawns", 0)

    # Available jarring jars
    available_jars = sum(
        1 for t in tanks
        if (t.get("purpose") or "").strip() == "Jarring"
        and (t.get("status") or "").strip() == "Empty / Idle"
    )

    st.subheader("🚀 Operational Quick Metrics")
    c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(8)
    c1.metric("Total Tanks", total_tanks)
    c2.metric("⚪ Available", available_tanks)
    c3.metric("🟡 Reserved", reserved_tanks)
    c4.metric("🟢 Occupied", occupied_tanks)
    c5.metric("🫙 Empty Jars", available_jars)
    c6.metric("Total Breeders", total_breeders)
    c7.metric("M / F", f"{male_breeders} / {female_breeders}")
    c8.metric("Active Spawns", active_spawns)

    st.markdown("---")

    # --------------------------------------------------------------------------
    # 3. ACTION NEEDED + JARRING CAPACITY + STARRED PANEL
    # --------------------------------------------------------------------------
    _render_action_needed(tanks)

    col_jars, col_starred = st.columns([1, 2])
    with col_jars:
        _render_jarring_capacity(tanks)
    with col_starred:
        _render_starred_panel(fish)

    st.markdown("---")

    # --------------------------------------------------------------------------
    # 4. CHARTS
    # --------------------------------------------------------------------------
    st.subheader("📈 Studio Status & Asset Breakdown")
    chart_col1, chart_col2, chart_col3 = st.columns(3)

    # Tank statuses
    with chart_col1:
        st.markdown("**🪣 Tank Statuses**")
        if tanks:
            df_t = pd.DataFrame([{"Status": t.get("status") or "Empty / Idle"} for t in tanks])
            tank_counts = df_t["Status"].value_counts().reset_index()
            tank_counts.columns = ["Status", "Count"]
            fig = px.pie(
                tank_counts, names="Status", values="Count",
                hole=0.4,
                color_discrete_sequence=px.colors.qualitative.Pastel,
            )
            fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=True)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No tank data available.")

    # Breeder gender balance
    with chart_col2:
        st.markdown("**🐟 Breeder Gender Balance**")
        breeders = [f for f in fish if f.get("is_breeder")]
        if breeders:
            df_b = pd.DataFrame([{"Gender": b.get("gender") or "Unknown"} for b in breeders])
            gender_counts = df_b["Gender"].value_counts().reset_index()
            gender_counts.columns = ["Gender", "Count"]
            fig = px.pie(
                gender_counts, names="Gender", values="Count",
                hole=0.4,
                color_discrete_sequence=["#1f77b4", "#e377c2", "#7f7f7f"],
            )
            fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=True)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No breeder data available.")

    # Spawn status breakdown
    with chart_col3:
        st.markdown("**🧬 Spawn Stages**")
        if spawns:
            df_s = pd.DataFrame([{"Stage": s.get("status") or "In Pairing"} for s in spawns])
            spawn_counts = df_s["Stage"].value_counts().reset_index()
            spawn_counts.columns = ["Stage", "Count"]
            fig = px.bar(
                spawn_counts, x="Stage", y="Count",
                text="Count", color="Stage",
            )
            fig.update_traces(textposition="outside")
            fig.update_layout(showlegend=False, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No spawn records available.")

    st.markdown("---")

    # --------------------------------------------------------------------------
    # 5. TABBED INVENTORY VIEWS
    # --------------------------------------------------------------------------
    st.subheader("📋 Studio Inventory Quick Inspection")
    tab_tanks, tab_breeders, tab_spawns = st.tabs([
        "🪣 Tanks & Containers",
        "🐟 Breeder Inventory",
        "❤️ Pairings & Spawns",
    ])

    with tab_tanks:
        df = _tanks_dataframe(tanks)
        if not df.empty:
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.write("No registered tanks.")

    with tab_breeders:
        df = _breeders_dataframe(fish)
        if not df.empty:
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.write("No registered breeders.")

    with tab_spawns:
        df = _spawns_dataframe(spawns, tank_by_id)
        if not df.empty:
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.write("No spawns.")
