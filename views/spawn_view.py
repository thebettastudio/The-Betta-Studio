# views/spawn_view.py
# Betta Farm Management System
# Session 12 — Ported to Supabase via spawn_manager, fish_manager,
# tank_registry, database, photo_service.

import datetime
from typing import Optional

import pandas as pd
import streamlit as st

from modules.spawn_manager import (
    list_all_spawns,
    list_active_pairings_with_details,
    list_spawns_with_details,
    create_new_spawn,
    mark_pairing_success_pending,
    mark_free_swimming,
    mark_pairing_failed,
    mark_completed,
    update_spawn_details,
)
from modules.fish_manager import (
    get_fish_dropdown_items,
    register_fish_from_spawn,
    VALID_GENDERS,
)
from modules.tank_registry import (
    get_tank_dropdown_items,
    list_available_tanks,
)
from modules.id_generator import calculate_child_lineage
from modules.photo_service import photo_url


# ============================================================
# HELPERS
# ============================================================

def _fish_display(fish: Optional[dict], fallback_id: str = "?") -> dict:
    """Return a display-friendly dict from a fish row, with safe fallbacks."""
    if not fish:
        return {
            "system_id": fallback_id,
            "variety": "N/A",
            "grade": "N/A",
            "line_code": "UNK",
            "generation": "P1",
            "photo_id": None,
        }
    return {
        "system_id": fish.get("system_id") or fallback_id,
        "variety": fish.get("variety") or "N/A",
        "grade": fish.get("grade") or "N/A",
        "line_code": fish.get("line_code") or "UNK",
        "generation": fish.get("generation") or "P1",
        "photo_id": fish.get("photo_id"),
    }


def _render_breeder_block(fish: dict, fallback_id: str, gender_label: str):
    """Render one breeder's info + image. Compact 2-column inner layout."""
    info = _fish_display(fish, fallback_id)
    col_info, col_img = st.columns([2, 1.5])

    with col_info:
        st.markdown(f"#### {gender_label}")
        st.markdown(f"**ID:** `{info['system_id']}`")
        st.markdown(f"**Variety:** {info['variety']}")
        st.markdown(f"**Grade:** `{info['grade']}`")
        st.markdown(f"**Line:** `{info['line_code']}` (`{info['generation']}`)")

    with col_img:
        if info["photo_id"]:
            st.image(photo_url(info["photo_id"]), use_container_width=True)
        else:
            st.caption(f"📷 *No {gender_label.split()[0]} image*")


def _default_batch_name(spawn: dict) -> str:
    """Generate a default batch name from line_code + generation."""
    line = (spawn.get("line_code") or "").strip()
    gen = (spawn.get("generation") or "").strip()
    if not line or line == "UNK" or len(line) > 12:
        base = spawn.get("system_id") or "BATCH"
    else:
        base = line
    return f"{base}-{gen}" if gen else base


# ============================================================
# TAB 1: ACTIVE PAIRINGS
# ============================================================

def _render_lifecycle_buttons(item: dict):
    spawn = item["spawn"]
    spawn_uuid = spawn["id"]
    system_id = spawn.get("system_id") or "?"
    status = spawn.get("status") or "In Pairing"
    line_code = spawn.get("line_code") or "N/A"
    generation = spawn.get("generation") or "N/A"

    col_a, col_b, col_c = st.columns(3)

    # --- Eggs Dropped ---
    with col_a:
        if status == "In Pairing":
            if st.button("🥚 Eggs Dropped", key=f"egg_{spawn_uuid}", use_container_width=True):
                mark_pairing_success_pending(spawn_uuid)
                st.success("Status → Pending (Success)")
                st.rerun()
        elif status == "Pending (Success)":
            st.caption("✅ Eggs pending")

    # --- Mark Free Swimming ---
    with col_b:
        with st.popover("🏊 Mark Free Swimming", use_container_width=True):
            default_batch = _default_batch_name(spawn)
            batch_name = st.text_input(
                "Batch Name / Code",
                value=default_batch,
                key=f"batch_{spawn_uuid}",
                help="Short prefix used when jarring individual fish (e.g. SP01-F1-01)",
            )
            fry_cnt = st.number_input(
                "Estimated Fry",
                min_value=1, value=50, key=f"cnt_{spawn_uuid}",
            )
            if st.button("Confirm Free Swim", key=f"confirm_swim_{spawn_uuid}"):
                if batch_name.strip():
                    mark_free_swimming(spawn_uuid, batch_name.strip(), int(fry_cnt))
                    st.success("Spawn marked Free Swimming. Tank released. Parents available.")
                    st.rerun()
                else:
                    st.error("Please enter a batch name.")

    # --- Mark Failed ---
    with col_c:
        with st.popover("❌ Mark Failed", use_container_width=True):
            reason = st.selectbox(
                "Reason",
                [
                    "Aggression / Fighting",
                    "Eaten Eggs",
                    "Infertility / Unhatched Eggs",
                    "Fungal / Mold Infection",
                    "Other",
                ],
                key=f"fail_reason_{spawn_uuid}",
            )
            if st.button("Confirm Failure", key=f"confirm_fail_{spawn_uuid}", type="primary"):
                mark_pairing_failed(spawn_uuid, reason)
                st.success("Spawn marked Failed. Tank released. Parents available.")
                st.rerun()


def _render_edit_popover(spawn: dict):
    spawn_uuid = spawn["id"]
    system_id = spawn.get("system_id") or "?"

    with st.popover("✏️ Edit Spawn", use_container_width=True):
        st.write(f"**Edit Spawn {system_id}**")
        edit_goal = st.text_input(
            "Line Goal",
            value=spawn.get("line_goal") or "",
            key=f"edit_goal_{spawn_uuid}",
        )
        edit_notes = st.text_area(
            "Notes",
            value=spawn.get("notes") or "",
            key=f"edit_notes_{spawn_uuid}",
        )
        if st.button("Save Changes", key=f"save_edit_{spawn_uuid}"):
            if update_spawn_details(spawn_uuid, line_goal=edit_goal, notes=edit_notes):
                st.success("Updated.")
                st.rerun()
            else:
                st.error("Failed to update spawn.")


def _render_active_pairing_card(item: dict):
    spawn = item["spawn"]
    male = item["male"]
    female = item["female"]
    tank_loc = item.get("tank_location") or "Unassigned"
    days_paired = item.get("days_paired") or 0

    system_id = spawn.get("system_id") or "?"
    status = spawn.get("status") or "In Pairing"
    pairing_date = spawn.get("pairing_date") or "—"
    line_code = spawn.get("line_code") or "N/A"
    generation = spawn.get("generation") or "N/A"

    with st.container(border=True):
        col_title, col_edit = st.columns([4, 1])
        with col_title:
            st.markdown(f"### 🧪 Spawn: `{system_id}` | Line: `{line_code}` (`{generation}`)")
        with col_edit:
            _render_edit_popover(spawn)

        st.caption(
            f"📍 **Tank:** {tank_loc} | "
            f"📅 **Paired:** {pairing_date} ({days_paired} days ago) | "
            f"🏷️ **Status:** `{status}`"
        )

        if spawn.get("line_goal"):
            st.write(f"🎯 **Goal:** {spawn['line_goal']}")
        if spawn.get("notes"):
            st.info(f"**Notes:** {spawn['notes']}")

        st.divider()

        # Breeder info: 2-column top-level, each column has info + image
        col_male, col_female = st.columns(2)
        with col_male:
            _render_breeder_block(male, spawn.get("male_id") or "?", "♂️ Male Breeder")
        with col_female:
            _render_breeder_block(female, spawn.get("female_id") or "?", "♀️ Female Breeder")

        st.divider()

        _render_lifecycle_buttons(item)


def render_active_pairings_tab():
    st.subheader("Currently Active Pairings")

    col_ref, _ = st.columns([1, 3])
    with col_ref:
        if st.button("🔄 Refresh", key="btn_refresh_spawns", use_container_width=True):
            st.rerun()

    active = list_active_pairings_with_details()

    if not active:
        st.info("No active pairings. Start one in the 'Start New Pairing' tab.")
        return

    for item in active:
        _render_active_pairing_card(item)


# ============================================================
# TAB 2: START NEW PAIRING
# ============================================================

def render_start_pairing_tab():
    st.subheader("Pair Male & Female Breeder")

    # --- Breeder dropdowns (only available ones) ---
    males_dd, females_dd = [], []
    for f in get_fish_dropdown_items():
        # get_fish_dropdown_items excludes Deceased/Sold/Retired but includes all fish.
        # For pairing we want only fish with gender Male/Female.
        pass

    # Actually filter from database fish directly for full control
    from database import get_all_fish
    all_fish = get_all_fish()
    for f in all_fish:
        if not f.get("system_id"):
            continue
        status = (f.get("status") or "").lower()
        if status in ("deceased", "sold", "retired"):
            continue
        gender = (f.get("gender") or "").lower()
        item = {
            "id": f["id"],
            "label": f"{f['system_id']} | {f.get('variety') or 'no variety'}",
        }
        if gender == "male":
            males_dd.append(item)
        elif gender == "female":
            females_dd.append(item)

    # --- Tank dropdown (available spawning tanks) ---
    tank_dd = get_tank_dropdown_items(purpose="Spawning")

    if not males_dd or not females_dd:
        st.warning("⚠️ You need at least one Male and one Female fish to create a pair.")
        return

    if not tank_dd:
        st.error("⚠️ No available Spawning-purpose tanks. Create or free up a tank first.")
        return

    col1, col2 = st.columns(2)

    with col1:
        male_idx = st.selectbox(
            "Select Male Breeder",
            options=range(len(males_dd)),
            format_func=lambda i: males_dd[i]["label"],
        )
        male_uuid = males_dd[male_idx]["id"]

        tank_idx = st.selectbox(
            "Select Spawning Tank",
            options=range(len(tank_dd)),
            format_func=lambda i: tank_dd[i]["label"],
        )
        tank_uuid = tank_dd[tank_idx]["id"]

    with col2:
        female_idx = st.selectbox(
            "Select Female Breeder",
            options=range(len(females_dd)),
            format_func=lambda i: females_dd[i]["label"],
        )
        female_uuid = females_dd[female_idx]["id"]

        line_goal = st.text_input(
            "Line / Breeding Goal",
            placeholder="e.g. Improve caudal spread & clean dorsal",
        )

    # --- Live preview of line/gen/spawn_id ---
    male_fish = next((f for f in all_fish if f["id"] == male_uuid), None)
    female_fish = next((f for f in all_fish if f["id"] == female_uuid), None)

    if male_fish and female_fish:
        preview_line, preview_gen = calculate_child_lineage(
            male_line=male_fish.get("line_code") or "UNK",
            male_gen=male_fish.get("generation") or "P1",
            female_line=female_fish.get("line_code") or "UNK",
            female_gen=female_fish.get("generation") or "P1",
        )
        from modules.id_generator import generate_spawn_code
        preview_code = generate_spawn_code()

        st.info(
            f"📋 **Compact Code:** `{preview_code}` | "
            f"🧬 **Target Line:** `{preview_line}` | "
            f"🏷️ **Resulting Gen:** `{preview_gen}`"
        )

    notes = st.text_area(
        "Pairing Notes",
        placeholder="e.g. Both pre-conditioned for 7 days on bloodworms",
    )

    if st.button("💞 Initiate Pairing", type="primary", use_container_width=True):
        with st.spinner("Setting up pairing..."):
            saved = create_new_spawn(
                male_id=male_uuid,
                female_id=female_uuid,
                tank_id=tank_uuid,
                line_goal=line_goal,
                notes=notes,
            )
        if not saved:
            st.error("Failed to create spawn.")
            return
        st.success(
            f"Pairing initiated! **{saved.get('system_id')}** "
            f"(code: {saved.get('spawn_code')}) assigned to tank."
        )
        st.rerun()


# ============================================================
# TAB 3: ALL SPAWN HISTORY
# ============================================================

def render_history_tab():
    st.subheader("All Spawn Records")

    items = list_spawns_with_details()
    if not items:
        st.info("No spawn history recorded yet.")
        return

    rows = []
    for it in items:
        s = it["spawn"]
        male = it.get("male")
        female = it.get("female")
        rows.append({
            "Spawn ID": s.get("system_id") or "?",
            "Code": s.get("spawn_code") or "",
            "Line": s.get("line_code") or "",
            "Gen": s.get("generation") or "",
            "Male": (male or {}).get("system_id") or s.get("male_id") or "—",
            "Female": (female or {}).get("system_id") or s.get("female_id") or "—",
            "Pairing Date": s.get("pairing_date") or "",
            "Status": s.get("status") or "",
            "Batch": s.get("batch_name") or "",
            "Free Swim": s.get("free_swimming_date") or "",
            "Fry (est)": s.get("estimated_fry_count") or 0,
            "Fry (final)": s.get("fry_count") or 0,
            "Tank": it.get("tank_location") or "Unassigned",
            "Goal": s.get("line_goal") or "",
            "Notes": s.get("notes") or "",
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


# ============================================================
# PAGE
# ============================================================

def render_spawn_page():
    st.title("🧬 Pair & Spawn Tracker")

    tab1, tab2, tab3 = st.tabs([
        "💞 Active Pairings",
        "➕ Start New Pairing",
        "📜 All Spawn History",
    ])

    with tab1:
        render_active_pairings_tab()

    with tab2:
        render_start_pairing_tab()

    with tab3:
        render_history_tab()


def render_spawn_tracker():
    """Alias entrypoint."""
    render_spawn_page()
