# views/search_view.py
# Betta Farm Management System
# Session 13 — Ported to Supabase. Global search over fish, spawns, tanks.

import datetime
from typing import Optional

import streamlit as st

from database import get_all_fish, get_all_tanks, get_all_spawns
from modules.photo_service import photo_url
from modules.fish_manager import VALID_GRADES


# ============================================================
# HELPERS
# ============================================================

def _parse_date(date_str) -> Optional[datetime.date]:
    """Safely parse YYYY-MM-DD."""
    try:
        return datetime.datetime.strptime(str(date_str).strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _fish_label(b: dict) -> str:
    sid = b.get("system_id") or "?"
    gender = b.get("gender") or "?"
    return f"{sid} ({gender})"


def _resolve_tank_location(tank_id, tank_by_id: dict) -> str:
    if not tank_id:
        return "Unassigned"
    t = tank_by_id.get(tank_id)
    return (t.get("location_code") if t else None) or "Unassigned"


# ============================================================
# FILTER FUNCTIONS
# ============================================================

def _filter_fish(
    fish: list,
    query: str,
    filter_gender: list,
    filter_grade: list,
    filter_variety: list,
    dob_range,
) -> list:
    out = []
    for f in fish:
        text = " ".join([
            str(f.get("system_id") or ""),
            str(f.get("variety") or ""),
            str(f.get("line_code") or ""),
            str(f.get("notes") or ""),
            str(f.get("status") or ""),
            str(f.get("breeder_status") or ""),
            str(f.get("location") or ""),
        ]).lower()
        if query and query not in text:
            continue

        if filter_gender and (f.get("gender") or "").capitalize() not in filter_gender:
            continue

        if filter_grade and f.get("grade") not in filter_grade:
            continue

        if filter_variety and (f.get("variety") or "").strip() not in filter_variety:
            continue

        if dob_range and len(dob_range) == 2:
            f_date = _parse_date(f.get("purchase_date") or "")
            if not f_date or not (dob_range[0] <= f_date <= dob_range[1]):
                continue

        out.append(f)
    return out


def _filter_spawns(
    spawns: list,
    fish_by_id: dict,
    tank_by_id: dict,
    query: str,
    filter_variety: list,
    filter_spawn_status: list,
    dob_range,
) -> list:
    out = []
    for s in spawns:
        male = fish_by_id.get(s.get("male_id"))
        female = fish_by_id.get(s.get("female_id"))
        text = " ".join([
            str(s.get("system_id") or ""),
            str(s.get("spawn_code") or ""),
            str(male.get("system_id") if male else ""),
            str(female.get("system_id") if female else ""),
            str(s.get("line_code") or ""),
            str(s.get("notes") or ""),
            str(s.get("status") or ""),
        ]).lower()
        if query and query not in text:
            continue

        if filter_variety:
            # match any of the parent's variety or spawn line
            parent_varieties = {
                (male.get("variety") if male else ""),
                (female.get("variety") if female else ""),
            }
            if not (filter_variety[0] in parent_varieties or (s.get("line_code") in filter_variety)):
                # simpler: match if any filter item appears in parent varieties or line_code
                hit = False
                for fv in filter_variety:
                    if fv in parent_varieties or fv == s.get("line_code"):
                        hit = True
                        break
                if not hit:
                    continue

        if filter_spawn_status and s.get("status") not in filter_spawn_status:
            continue

        if dob_range and len(dob_range) == 2:
            s_date = _parse_date(s.get("pairing_date") or "")
            if not s_date or not (dob_range[0] <= s_date <= dob_range[1]):
                continue

        out.append(s)
    return out


def _filter_tanks(
    tanks: list,
    query: str,
    filter_tank_type: list,
    filter_tank_status: list,
) -> list:
    out = []
    for t in tanks:
        text = " ".join([
            str(t.get("system_id") or ""),
            str(t.get("location_code") or ""),
            str(t.get("tank_type") or ""),
            str(t.get("occupant_label") or ""),
            str(t.get("notes") or ""),
            str(t.get("status") or ""),
            str(t.get("purpose") or ""),
        ]).lower()
        if query and query not in text:
            continue

        if filter_tank_type and (t.get("tank_type") or "").strip() not in filter_tank_type:
            continue

        if filter_tank_status and (t.get("status") or "").strip() not in filter_tank_status:
            continue

        out.append(t)
    return out


# ============================================================
# RESULT RENDERERS
# ============================================================

def _render_fish_result(f: dict):
    with st.container(border=True):
        col_img, col_info = st.columns([1, 3])

        with col_img:
            if f.get("photo_id"):
                st.image(photo_url(f["photo_id"]), use_container_width=True)
            else:
                st.caption("📷 *No photo*")

        with col_info:
            is_br = " ⭐" if f.get("is_breeder") else ""
            st.markdown(f"### 🐟 `{f.get('system_id')}` {is_br}")
            st.write(
                f"**{f.get('gender') or '?'}** | "
                f"Variety: **{f.get('variety') or '—'}** | "
                f"Status: `{f.get('status') or '—'}`"
            )
            if f.get("grade"):
                st.caption(f"Grade: {f['grade']} | Line: {f.get('line_code') or '—'} ({f.get('generation') or 'P1'})")
            if f.get("breeder_status"):
                st.caption(f"Breeder status: `{f['breeder_status']}`")
            if f.get("location"):
                st.caption(f"📍 Location: `{f['location']}`")
            if f.get("notes"):
                st.info(f["notes"])


def _render_spawn_result(s: dict, fish_by_id: dict, tank_by_id: dict):
    male = fish_by_id.get(s.get("male_id"))
    female = fish_by_id.get(s.get("female_id"))
    tank_loc = _resolve_tank_location(s.get("tank_id"), tank_by_id)

    with st.container(border=True):
        st.markdown(f"### 🥚 Spawn `{s.get('system_id')}`")
        st.write(
            f"**Parents:** `{male.get('system_id') if male else s.get('male_id')}` × "
            f"`{female.get('system_id') if female else s.get('female_id')}` | "
            f"**Status:** `{s.get('status')}`"
        )
        st.caption(
            f"Line: {s.get('line_code') or '—'} ({s.get('generation') or 'F1'}) | "
            f"Tank: {tank_loc} | "
            f"Paired: {s.get('pairing_date') or '—'}"
        )
        if s.get("batch_name"):
            st.caption(f"Batch: `{s['batch_name']}`")
        if s.get("notes"):
            st.info(s["notes"])


def _render_tank_result(t: dict):
    with st.container(border=True):
        col_img, col_info = st.columns([1, 3])

        with col_img:
            if t.get("qr_id"):
                st.image(photo_url(t["qr_id"]), caption="QR", use_container_width=True)
            elif t.get("photo_id"):
                st.image(photo_url(t["photo_id"]), use_container_width=True)
            else:
                st.caption("📷 *No image*")

        with col_info:
            st.markdown(f"### 🏷️ `{t.get('location_code')}`")
            st.caption(f"System ID: `{t.get('system_id')}`")
            st.write(
                f"**Type:** {t.get('tank_type') or '—'} | "
                f"**Capacity:** {t.get('capacity_liters') or '—'} L | "
                f"**Status:** `{t.get('status') or '—'}`"
            )
            st.write(f"🎯 **Purpose:** {t.get('purpose') or '—'}")
            st.write(f"🐟 **Occupant:** `{t.get('occupant_label') or 'Empty'}`")
            if t.get("notes"):
                st.caption(f"📝 {t['notes']}")


# ============================================================
# PAGE
# ============================================================

def render_search_page():
    st.title("🔍 Advanced Studio Search & Filters")
    st.caption("Locate fish, spawn batches, and containers with live previews and filters.")

    # Load everything
    fish = get_all_fish() or []
    tanks = get_all_tanks() or []
    spawns = get_all_spawns() or []

    fish_by_id = {f["id"]: f for f in fish}
    tank_by_id = {t["id"]: t for t in tanks}

    # Dynamic filter options
    existing_varieties = sorted({
        f.get("variety", "").strip() for f in fish if f.get("variety")
    } | {
        (fish_by_id.get(s.get("male_id"), {}).get("variety") or "").strip()
        for s in spawns
    } | {
        (fish_by_id.get(s.get("female_id"), {}).get("variety") or "").strip()
        for s in spawns
    } - {""})

    existing_tank_types = sorted({
        t.get("tank_type", "").strip() for t in tanks if t.get("tank_type")
    })

    existing_grades = sorted({
        f.get("grade") for f in fish if f.get("grade")
    } | set(VALID_GRADES))

    existing_spawn_statuses = sorted({
        s.get("status") for s in spawns if s.get("status")
    })

    existing_tank_statuses = sorted({
        t.get("status") for t in tanks if t.get("status")
    })

    # Search input
    query = st.text_input(
        "🔍 Global Keyword Search",
        placeholder="Search by ID, tape code (e.g., JAR-0007), lineage, notes...",
    ).strip().lower()

    # Advanced filters
    with st.expander("🎛️ Advanced Filters", expanded=False):
        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("**🐟 Fish Filters**")
            filter_gender = st.multiselect("Gender", ["Male", "Female", "Unsexed"])
            filter_grade = st.multiselect("Grade", options=existing_grades)
            filter_variety = st.multiselect("Variety", options=existing_varieties)

        with col2:
            st.markdown("**🥚 Spawn Filters**")
            filter_spawn_status = st.multiselect("Spawn Status", options=existing_spawn_statuses)

        with col3:
            st.markdown("**🪣 Container & Date Filters**")
            filter_tank_type = st.multiselect("Tank Type", options=existing_tank_types)
            filter_tank_status = st.multiselect("Tank Status", options=existing_tank_statuses)

            enable_date_filter = st.checkbox("Filter by Date Range")
            if enable_date_filter:
                dob_range = st.date_input(
                    "Date Range",
                    value=(datetime.date(2025, 1, 1), datetime.date.today()),
                )
            else:
                dob_range = None

    # Apply filters
    matching_fish = _filter_fish(fish, query, filter_gender, filter_grade, filter_variety, dob_range)
    matching_spawns = _filter_spawns(spawns, fish_by_id, tank_by_id, query, filter_variety, filter_spawn_status, dob_range)
    matching_tanks = _filter_tanks(tanks, query, filter_tank_type, filter_tank_status)

    # Results header
    st.markdown("---")
    total = len(matching_fish) + len(matching_spawns) + len(matching_tanks)
    st.subheader(f"Results Found: {total}")

    tab_all, tab_fish, tab_spawns, tab_tanks = st.tabs([
        f"All ({total})",
        f"🐟 Fish ({len(matching_fish)})",
        f"🥚 Spawns ({len(matching_spawns)})",
        f"🪣 Containers ({len(matching_tanks)})",
    ])

    with tab_all:
        if total == 0:
            st.warning("No records matched your search query and filters.")

    with tab_fish:
        if not matching_fish:
            st.caption("No matching fish found.")
        for f in matching_fish:
            _render_fish_result(f)

    with tab_spawns:
        if not matching_spawns:
            st.caption("No matching spawns found.")
        for s in matching_spawns:
            _render_spawn_result(s, fish_by_id, tank_by_id)

    with tab_tanks:
        if not matching_tanks:
            st.caption("No matching containers found.")
        for t in matching_tanks:
            _render_tank_result(t)
