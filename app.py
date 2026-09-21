import streamlit as st
from spawn_manager import get_available_breeders, create_new_spawn

st.title("🐟 Pair & Spawn Management")
st.subheader("Create New Breeding Pair")

# Load available males and females from Google Sheets
males, females = get_available_breeders()

if not males or not females:
    st.warning("⚠️ You need at least 1 Available Male and 1 Available Female in the Breeders registry to start a Spawn.")
else:
    with st.form("new_spawn_form"):
        # Selectors using Breeder IDs and labels
        male_option = st.selectbox(
            "Select Male Sire (Sire ID):",
            options=males,
            format_func=lambda x: x['label']
        )
        
        female_option = st.selectbox(
            "Select Female Dam (Dam ID):",
            options=females,
            format_func=lambda x: x['label']
        )

        tank_location = st.text_input("Tank / Pairing Unit ID:", value="Tank-B01")
        line_goal = st.text_area("Genetics / Line Goal:", placeholder="e.g. Improve tail spread and iridescence...")
        notes = st.text_area("Notes:", placeholder="Optional conditioning notes...")

        submit = st.form_submit_button("🚀 Start Pairing / Create Spawn")

        if submit:
            spawn_id = create_new_spawn(
                male_breeder_id=male_option['id'],
                female_breeder_id=female_option['id'],
                tank_location=tank_location,
                line_goal=line_goal,
                notes=notes
            )
            st.success(f"Spawn **{spawn_id}** created successfully! Both parents set to 'In Pairing'.")
