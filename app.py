import streamlit as st
import pandas as pd
from modules.database import init_db, get_connection

# Initialize SQLite database
init_db()

st.set_page_config(page_title="Betta Farm Tracker", layout="wide")
st.title("🐟 Betta Farm Management")

tab1, tab2, tab3 = st.tabs(["Inventory Dashboard", "Add New Betta", "Breeding Spawns"])

# --- TAB 1: INVENTORY ---
with tab1:
    st.subheader("Current Betta Stock")
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM bettas", conn)
    conn.close()
    
    if not df.empty:
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No bettas logged yet. Use the 'Add New Betta' tab to register your stock.")

# --- TAB 2: ADD BETTA ---
with tab2:
    st.subheader("Register New Fish")
    with st.form("add_betta_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            code = st.text_input("Fish ID / Code (e.g., HM-M-001)")
            variety = st.selectbox("Variety", ["Halfmoon", "Crowntail", "Plakat", "Veiltail", "Alien", "Giant"])
            gender = st.radio("Gender", ["Male", "Female"])
        with col2:
            location = st.text_input("Location (e.g., Jar #12, Tub A)")
            status = st.selectbox("Status", ["Available", "Breeding", "Sold"])
            birth_date = st.date_input("Birth / Hatch Date")

        submitted = st.form_submit_button("Save Betta")
        if submitted:
            if code:
                try:
                    conn = get_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO bettas (code, variety, gender, location, status, birth_date) VALUES (?, ?, ?, ?, ?, ?)",
                        (code, variety, gender, location, status, str(birth_date))
                    )
                    conn.commit()
                    conn.close()
                    st.success(f"Successfully added Betta: {code}")
                except Exception as e:
                    st.error(f"Error saving data: {e}")
            else:
                st.warning("Please enter a Fish ID.")

# --- TAB 3: BREEDING ---
with tab3:
    st.subheader("Spawn Log")
    st.caption("Track active breeding pairs and fry production.")
