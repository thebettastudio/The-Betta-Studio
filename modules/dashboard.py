# modules/dashboard.py
# Betta Farm Management System
# Session 13 — Ported to Supabase via database + module helpers.

import streamlit as st
import pandas as pd
import plotly.express as px

from database import get_all_fish, get_all_tanks, get_all_spawns, get_dashboard_counts


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
    # 2. KPI METRICS (use database aggregate for speed)
    # --------------------------------------------------------------------------
    counts = get_dashboard_counts() or {}

    total_tanks = counts.get("total_tanks", len(tanks))
    available_tanks = counts.get("available_tanks", 0)
    total_breeders = counts.get("total_breeders", 0)
    male_breeders = counts.get("male_breeders", 0)
    female_breeders = counts.get("female_breeders", 0)
    total_spawns = counts.get("total_spawns", len(spawns))
    active_spawns = counts.get("active_spawns", 0)

    st.subheader("🚀 Operational Quick Metrics")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Total Tanks", total_tanks)
    c2.metric("Available Tanks", available_tanks)
    c3.metric("Total Breeders", total_breeders)
    c4.metric("Males / Females", f"{male_breeders} M / {female_breeders} F")
    c5.metric("Total Spawns", total_spawns)
    c6.metric("Active Pairs/Spawns", active_spawns)

    st.markdown("---")

    # --------------------------------------------------------------------------
    # 3. CHARTS
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
    # 4. TABBED INVENTORY VIEWS
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
