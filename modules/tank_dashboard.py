# modules/tank_dashboard.py
import streamlit as st
import pandas as pd
import plotly.express as px
from modules.tank_registry import get_all_tanks

def render_tank_dashboard():
    st.title("📊 Tank & Container Dashboard")
    st.caption("Real-time overview of tank availability, status, and utilization across your facility.")

    # Fetch data
    tanks = get_all_tanks()

    if not tanks:
        st.info("No tanks registered yet. Go to Tank Registration to add your first container!")
        return

    df = pd.DataFrame(tanks)

    # Clean & normalize status values
    df['status'] = df['status'].fillna("Active").replace("", "Active")
    df['purpose'] = df['purpose'].fillna("General / Multi-purpose").replace("", "General / Multi-purpose")
    df['type'] = df['type'].fillna("Unspecified").replace("", "Unspecified")

    # Metrics Calculation
    total_tanks = len(df)
    active_tanks = len(df[df['status'].str.lower() == 'active'])
    available_tanks = len(df[df['status'].str.lower().isin(['available', 'empty', 'ready', 'idle'])])
    maintenance_tanks = len(df[df['status'].str.lower().isin(['maintenance', 'cleaning', 'repair'])])
    quarantine_tanks = len(df[df['status'].str.lower().isin(['quarantine', 'isolated'])])

    # Key Performance Indicator Cards
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Tanks", total_tanks)
    col2.metric("Active / Occupied", active_tanks)
    col3.metric("Available / Ready", available_tanks)
    col4.metric("In Maintenance", maintenance_tanks)
    col5.metric("Quarantined", quarantine_tanks)

    st.markdown("---")

    # Visual Charts
    col_chart1, col_chart2 = st.columns(2)

    with col_chart1:
        st.subheader("Status Breakdown")
        status_counts = df['status'].value_counts().reset_index()
        status_counts.columns = ['Status', 'Count']
        
        fig_status = px.pie(
            status_counts, 
            names='Status', 
            values='Count',
            color='Status',
            color_discrete_map={
                'Active': '#2ca02c',
                'Available': '#1f77b4',
                'Maintenance': '#ff7f0e',
                'Quarantine': '#d62728'
            },
            hole=0.4
        )
        fig_status.update_layout(margin=dict(t=20, b=20, l=10, r=10))
        st.plotly_chart(fig_status, use_container_width=True)

    with col_chart2:
        st.subheader("Tanks by Container Type")
        type_counts = df['type'].value_counts().reset_index()
        type_counts.columns = ['Tank Type', 'Count']

        fig_type = px.bar(
            type_counts,
            x='Tank Type',
            y='Count',
            text='Count',
            color='Tank Type'
        )
        fig_type.update_traces(textposition='outside')
        fig_type.update_layout(showlegend=False, margin=dict(t=20, b=20, l=10, r=10))
        st.plotly_chart(fig_type, use_container_width=True)

    st.markdown("---")

    # Detailed Table & Filter Controls
    st.subheader("📋 Container Inventory Quick View")

    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        selected_status = st.multiselect(
            "Filter by Status",
            options=list(df['status'].unique()),
            default=list(df['status'].unique())
        )
    with filter_col2:
        selected_type = st.multiselect(
            "Filter by Type",
            options=list(df['type'].unique()),
            default=list(df['type'].unique())
        )

    # Filtered view
    filtered_df = df[
        (df['status'].isin(selected_status)) &
        (df['type'].isin(selected_type))
    ]

    # Re-order columns for display
    display_df = filtered_df[['id', 'location', 'type', 'capacity', 'status', 'purpose', 'occupant', 'notes']]
    display_df.columns = ['ID', 'Tape Code', 'Type', 'Capacity (L)', 'Status', 'Purpose', 'Occupant ID', 'Notes']

    st.dataframe(display_df, use_container_width=True, hide_index=True)
