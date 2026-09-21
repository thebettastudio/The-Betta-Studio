# app.py
import streamlit as st
from views.breeder_view import render_breeder_page
from views.spawn_view import render_spawn_page
from views.activity_log_view import render_activity_log_page

st.set_page_config(page_title="The Betta Studio", page_icon="🐟", layout="wide")

st.sidebar.title("🐟 The Betta Studio")
page = st.sidebar.radio("Navigation Menu", [
    "Breeder Registry", 
    "Pair & Spawn Tracker", 
    "Activity Log"
])

if page == "Breeder Registry":
    render_breeder_page()

elif page == "Pair & Spawn Tracker":
    render_spawn_page()

elif page == "Activity Log":
    render_activity_log_page()
