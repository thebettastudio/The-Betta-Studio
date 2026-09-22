import streamlit as st
import pandas as pd
import plotly.express as px
from modules.tank_registry import get_all_tanks
from modules.breeder_registry import get_all_breeders
from modules.spawn_manager import get_all_spawns

def render_dashboard():
    st.title("📊 Studio Overview Dashboard")
    st.caption("Central hub for tanks, breeder inventory, active spawning pairs, and facility metrics.")

    # --------------------------------------------------------------------------
    # 1. DATA FETCHING & PREPARATION
    # --------------------------------------------------------------------------
    tanks = get_all_tanks() or []
    breeders = get_all_breeders() or []
    spawns = get_all_spawns() or []

    df_tanks = pd.DataFrame(tanks) if tanks else pd.DataFrame()
    df_breeders = pd.DataFrame(breeders) if breeders else pd.DataFrame()
    df_spawns = pd.DataFrame(spawns) if spawns else pd.DataFrame()

    # Normalize column names to lowercase for safe access
    if not df_tanks.empty:
        df_tanks.columns = [str(c).strip().lower() for c in df_tanks.columns]
    if not df_breeders.empty:
        df_breeders.columns = [str(c).strip().lower() for c in df_breeders.columns]
    if not df_spawns.empty:
        df_spawns.columns = [str(c).strip().lower() for c in df_spawns.columns]

    # Normalize Tanks
    if not df_tanks.empty:
        if 'status' not in df_tanks.columns:
            df_tanks['status'] = "Active"
        else:
            df_tanks['status'] = df_tanks['status'].fillna("Active").replace("", "Active")
        
        if 'type' not in df_tanks.columns:
            df_tanks['type'] = "Unspecified"
        else:
            df_tanks['type'] = df_tanks['type'].fillna("Unspecified").replace("", "Unspecified")

        total_tanks = len(df_tanks)
        active_tanks = len(df_tanks[df_tanks['status'].astype(str).str.lower() == 'active'])
        available_tanks = len(df_tanks[df_tanks['status'].astype(str).str.lower().isin(['available', 'empty', 'ready', 'idle', 'empty / idle'])])
    else:
        total_tanks = active_tanks = available_tanks = 0

    # Normalize Breeders (handles both 'gender' and 'sex' keys)
    if not df_breeders.empty:
        if 'sex' in df_breeders.columns and 'gender' not in df_breeders.columns:
            df_breeders['gender'] = df_breeders['sex']

        if 'status' not in df_breeders.columns:
            df_breeders['status'] = "Active"
        else:
            df_breeders['status'] = df_breeders['status'].fillna("Active").replace("", "Active")

        if 'gender' not in df_breeders.columns:
            df_breeders['gender'] = "Unknown"
        else:
            df_breeders['gender'] = df_breeders['gender'].fillna("Unknown").replace("", "Unknown")

        total_breeders = len(df_breeders)
        male_breeders = len(df_breeders[df_breeders['gender'].astype(str).str.lower().isin(['male', 'm'])])
        female_breeders = len(df_breeders[df_breeders['gender'].astype(str).str.lower().isin(['female', 'f'])])
    else:
        total_breeders = male_breeders = female_breeders = 0

    # Normalize Spawns
    if not df_spawns.empty:
        if 'status' not in df_spawns.columns:
            df_spawns['status'] = "In Pairing"
        else:
            df_spawns['status'] = df_spawns['status'].fillna("In Pairing").replace("", "In Pairing")

        total_spawns = len(df_spawns)
        active_spawns = len(df_spawns[df_spawns['status'].astype(str).str.lower().isin([
            'active', 'in pairing', 'pending (success)', 'free swimming', 'pairing', 'eggs'
        ])])
    else:
        total_spawns = active_spawns = 0

    # --------------------------------------------------------------------------
    # 2. TOP KPI CARDS SUMMARY
    # --------------------------------------------------------------------------
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
    # 3. VISUAL DISTRIBUTION CHARTS
    # --------------------------------------------------------------------------
    st.subheader("📈 Studio Status & Asset Breakdown")
    chart_col1, chart_col2, chart_col3 = st.columns(3)

    with chart_col1:
        st.markdown("**🪣 Tank Statuses**")
        if not df_tanks.empty and 'status' in df_tanks.columns:
            tank_counts = df_tanks['status'].value_counts().reset_index()
            tank_counts.columns = ['Status', 'Count']
            fig_tanks = px.pie(
                tank_counts, 
                names='Status', 
                values='Count',
                hole=0.4,
                color_discrete_sequence=px.colors.qualitative.Pastel
            )
            fig_tanks.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=True)
            st.plotly_chart(fig_tanks, use_container_width=True)
        else:
            st.info("No tank data available.")

    with chart_col2:
        st.markdown("**🐟 Breeder Gender Balance**")
        if not df_breeders.empty and 'gender' in df_breeders.columns:
            breeder_counts = df_breeders['gender'].value_counts().reset_index()
            breeder_counts.columns = ['Gender', 'Count']
            fig_breeders = px.pie(
                breeder_counts,
                names='Gender',
                values='Count',
                hole=0.4,
                color_discrete_sequence=['#1f77b4', '#e377c2', '#7f7f7f']
            )
            fig_breeders.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=True)
            st.plotly_chart(fig_breeders, use_container_width=True)
        else:
            st.info("No breeder data available.")

    with chart_col3:
        st.markdown("**🧬 Active Spawning Stages**")
        if not df_spawns.empty and 'status' in df_spawns.columns:
            spawn_counts = df_spawns['status'].value_counts().reset_index()
            spawn_counts.columns = ['Stage', 'Count']
            fig_spawns = px.bar(
                spawn_counts,
                x='Stage',
                y='Count',
                text='Count',
                color='Stage'
            )
            fig_spawns.update_traces(textposition='outside')
            fig_spawns.update_layout(showlegend=False, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig_spawns, use_container_width=True)
        else:
            st.info("No spawn records available.")

    st.markdown("---")

    # --------------------------------------------------------------------------
    # 4. TABBED INVENTORY QUICK VIEWS
    # --------------------------------------------------------------------------
    st.subheader("📋 Studio Inventory Quick Inspection")
    tab_tanks, tab_breeders, tab_spawns = st.tabs(["🪣 Tanks & Containers", "🐟 Breeder Inventory", "❤️ Pairings & Spawns"])

    with tab_tanks:
        if not df_tanks.empty:
            cols_to_show = [c for c in ['id', 'location', 'type', 'capacity', 'status', 'purpose', 'occupant', 'notes'] if c in df_tanks.columns]
            st.dataframe(df_tanks[cols_to_show if cols_to_show else df_tanks.columns], use_container_width=True, hide_index=True)
        else:
            st.write("No registered tanks.")

    with tab_breeders:
        if not df_breeders.empty:
            cols_to_show = [c for c in ['id', 'tag_code', 'type', 'gender', 'sex', 'line_code', 'generation', 'status', 'variety', 'location', 'tank', 'notes'] if c in df_breeders.columns]
            st.dataframe(df_breeders[cols_to_show if cols_to_show else df_breeders.columns], use_container_width=True, hide_index=True)
        else:
            st.write("No registered breeders.")

    with tab_spawns:
        if not df_spawns.empty:
            cols_to_show = [c for c in [
                'id', 'line_code', 'generation', 'male_id', 'female_id', 
                'pairing_date', 'status', 'batch_name', 'free_swim_date', 
                'fry_count', 'failure_reason', 'tank', 'line_goal', 'notes'
            ] if c in df_spawns.columns]
            st.dataframe(df_spawns[cols_to_show if cols_to_show else df_spawns.columns], use_container_width=True, hide_index=True)
        else:
            st.write("No active spawns.")
