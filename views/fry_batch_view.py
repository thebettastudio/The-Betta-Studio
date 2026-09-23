# views/fry_batch_view.py
# Betta Farm Management System
# Session 15 — Fry batch tracking UI.

import datetime
from typing import Optional

import streamlit as st

from modules.fry_batch_manager import (
    list_all_batches,
    list_active_batches,
    list_mature_batches,
    get_batch_stats,
    get_spawns_available_for_batch,
    suggest_batch_tag,
    create_batch_from_spawn,
    edit_batch,
    advance_stage,
    set_current_count,
    assign_batch_tank,
    jar_fry_bulk,
    delete_batch,
    VALID_STAGES,
)
from modules.tank_registry import get_tank_dropdown_items
from modules.fish_manager import VALID_GENDERS, VALID_GRADES


# ============================================================
# HELPERS
# ============================================================

STAGE_ICONS = {
    "egg":           "🥚",
    "fry":           "🐣",
    "free_swimming": "🐟",
    "jarred":        "🫙",
    "juvenile":      "🌱",
    "sub_adult":     "🌿",
    "adult":         "🌳",
}


def _stage_icon(stage: str) -> str:
    return STAGE_ICONS.get((stage or "").lower(), "•")


def _format_date(val) -> str:
    if not val:
        return "—"
    try:
        return datetime.date.fromisoformat(str(val)).strftime("%Y-%m-%d")
    except Exception:
        return str(val)


def _survival_label(survival: Optional[float]) -> str:
    if survival is None:
        return "—"
    return f"{survival * 100:.0f}%"


# ============================================================
# CREATE NEW BATCH
# ============================================================

def _render_create_section():
    with st.expander("➕ Create Batch from Spawn", expanded=False):
        available = get_spawns_available_for_batch()

        if not available:
            st.info(
                "No spawns available. A spawn must be in 'Free Swimming' status "
                "and not yet have a batch."
            )
            return

        spawn_labels = {
            s["id"]: f"{s.get('system_id')} | {s.get('line_code')} ({s.get('generation')}) — {s.get('batch_name') or 'no batch name'}"
            for s in available
        }

        col1, col2 = st.columns([2, 1])
        with col1:
            selected_spawn_id = st.selectbox(
                "Select Spawn",
                options=list(spawn_labels.keys()),
                format_func=lambda sid: spawn_labels[sid],
                key="create_batch_spawn",
            )

        selected_spawn = next((s for s in available if s["id"] == selected_spawn_id), None)
        suggested_tag = suggest_batch_tag(selected_spawn) if selected_spawn else ""
        default_count = int(selected_spawn.get("estimated_fry_count") or 0) if selected_spawn else 0

        with col2:
            batch_tag = st.text_input(
                "Batch Tag",
                value=suggested_tag,
                key="create_batch_tag",
                help="Short label for this batch.",
            )

        col3, col4 = st.columns([1, 3])
        with col3:
            initial_count = st.number_input(
                "Initial Fry Count",
                min_value=0,
                value=default_count,
                step=1,
                key="create_batch_initial",
            )
        with col4:
            notes = st.text_input(
                "Notes",
                placeholder="Optional — e.g. hatched overnight, most look strong",
                key="create_batch_notes",
            )

        if st.button("Create Batch", type="primary", key="create_batch_btn"):
            saved = create_batch_from_spawn(
                spawn_id=selected_spawn_id,
                batch_tag=batch_tag,
                initial_count=int(initial_count),
                notes=notes,
            )
            if saved:
                st.success(f"Batch '{saved.get('batch_tag')}' created.")
                st.rerun()


# ============================================================
# BATCH CARD
# ============================================================

def _render_jar_popover(batch: dict):
    batch_uuid = batch["id"]
    batch_tag = batch.get("batch_tag") or "?"

    with st.popover("🫙 Jar Fry", use_container_width=True):
        st.markdown(f"**Jar fry from batch '{batch_tag}'**")
        st.caption(
            "Bulk-create placeholder fish rows. You can edit grade, photo, "
            "and details later in Fish Registry."
        )

        jar_count = st.number_input(
            "How many fry to jar?",
            min_value=1,
            max_value=max(1, batch.get("current_count") or 1),
            value=min(10, batch.get("current_count") or 1),
            key=f"jar_count_{batch_uuid}",
        )

        gender = st.selectbox(
            "Assigned Gender",
            options=["Unsexed", "Male", "Female"],
            index=0,
            key=f"jar_gender_{batch_uuid}",
            help="Leave as Unsexed for young fry; update later when sex is clear.",
        )

        grade = st.selectbox(
            "Initial Grade",
            options=VALID_GRADES,
            index=VALID_GRADES.index("Pet Grade") if "Pet Grade" in VALID_GRADES else 0,
            key=f"jar_grade_{batch_uuid}",
        )

        location = st.text_input(
            "Location (tape code)",
            value="",
            placeholder="e.g. JAR-0012 (optional)",
            key=f"jar_location_{batch_uuid}",
        )

        if st.button(
            "Confirm Jar",
            type="primary",
            key=f"jar_confirm_{batch_uuid}",
            use_container_width=True,
        ):
            created = jar_fry_bulk(
                batch_id=batch_uuid,
                count=int(jar_count),
                gender=gender,
                grade=grade,
                location=location.strip(),
            )
            if created:
                # Decrement current_count by how many we jarred
                new_count = max(0, (batch.get("current_count") or 0) - len(created))
                set_current_count(batch_uuid, new_count)
                st.success(f"Jarred {len(created)} fry. Remaining in batch: {new_count}.")
                st.rerun()


def _render_batch_card(item: dict):
    batch = item["batch"]
    spawn = item.get("spawn")
    tank = item.get("tank")
    survival = item.get("survival")

    batch_uuid = batch["id"]
    batch_tag = batch.get("batch_tag") or "?"
    stage = (batch.get("stage") or "fry").lower()
    icon = _stage_icon(stage)

    with st.container(border=True):
        # Header
        col_h, col_actions = st.columns([3, 2])

        with col_h:
            st.markdown(f"### {icon} `{batch_tag}`")
            if spawn:
                st.caption(
                    f"From spawn **{spawn.get('system_id')}** — "
                    f"Line: `{spawn.get('line_code')}` (`{spawn.get('generation')}`)"
                )

        with col_actions:
            new_stage = st.selectbox(
                "Stage",
                options=VALID_STAGES,
                index=VALID_STAGES.index(stage) if stage in VALID_STAGES else 1,
                key=f"stage_{batch_uuid}",
                label_visibility="collapsed",
            )
            if new_stage != stage:
                if st.button("Save Stage", key=f"save_stage_{batch_uuid}", use_container_width=True):
                    if advance_stage(batch_uuid, new_stage):
                        st.success(f"Stage → {new_stage}")
                        st.rerun()

        # Counts
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Initial", batch.get("initial_count") or 0)
        col2.metric("Current", batch.get("current_count") or 0)
        col3.metric("Survival", _survival_label(survival))
        col4.metric("Stage", f"{icon} {stage}")

        # Dates + tank
        st.caption(
            f"🥚 Hatch: {_format_date(batch.get('hatch_date'))} | "
            f"🫙 Jarred: {_format_date(batch.get('jarring_date'))} | "
            f"🪣 Tank: {tank.get('location_code') if tank else 'Unassigned'}"
        )

        if batch.get("notes"):
            st.info(batch["notes"])

        st.divider()

        # Action row
        col_a, col_b, col_c, col_d = st.columns(4)

        with col_a:
            _render_jar_popover(batch)

        with col_b:
            with st.popover("📊 Update Count", use_container_width=True):
                new_count = st.number_input(
                    "Current fry count",
                    min_value=0,
                    value=int(batch.get("current_count") or 0),
                    step=1,
                    key=f"count_{batch_uuid}",
                )
                if st.button("Save Count", key=f"save_count_{batch_uuid}", use_container_width=True):
                    if set_current_count(batch_uuid, int(new_count)):
                        st.success("Count updated.")
                        st.rerun()

        with col_c:
            with st.popover("🪣 Assign Tank", use_container_width=True):
                tank_opts = get_tank_dropdown_items()
                dd = [{"id": None, "label": "— Clear Tank —"}] + tank_opts
                idx = 0
                if batch.get("tank_id"):
                    for i, t in enumerate(dd):
                        if t["id"] == batch.get("tank_id"):
                            idx = i
                            break
                selected_idx = st.selectbox(
                    "Tank",
                    options=range(len(dd)),
                    index=idx,
                    format_func=lambda i: dd[i]["label"],
                    key=f"tank_sel_{batch_uuid}",
                )
                if st.button("Save Tank", key=f"save_tank_{batch_uuid}", use_container_width=True):
                    if assign_batch_tank(batch_uuid, dd[selected_idx]["id"]):
                        st.success("Tank updated.")
                        st.rerun()

        with col_d:
            with st.popover("⚙️ Edit / Delete", use_container_width=True):
                edit_tag = st.text_input(
                    "Batch Tag",
                    value=batch.get("batch_tag") or "",
                    key=f"edit_tag_{batch_uuid}",
                )
                edit_notes = st.text_area(
                    "Notes",
                    value=batch.get("notes") or "",
                    key=f"edit_notes_{batch_uuid}",
                )
                if st.button("Save Edits", key=f"save_edit_{batch_uuid}", use_container_width=True):
                    if edit_batch(batch_uuid, {"batch_tag": edit_tag, "notes": edit_notes}):
                        st.success("Saved.")
                        st.rerun()

                st.divider()
                confirm_del = st.checkbox(
                    "Confirm delete batch",
                    key=f"confirm_del_{batch_uuid}",
                )
                if st.button(
                    "🗑️ Delete Batch",
                    key=f"del_{batch_uuid}",
                    disabled=not confirm_del,
                    use_container_width=True,
                ):
                    if delete_batch(batch_uuid):
                        st.success("Batch deleted.")
                        st.rerun()


# ============================================================
# LIST SECTION
# ============================================================

def _render_list_section():
    st.subheader("Batches")

    col_search, col_filter = st.columns([2, 1])

    with col_search:
        query = st.text_input(
            "🔍 Search batches",
            placeholder="Search by tag, spawn ID, notes...",
            key="batch_search",
        ).strip().lower()

    with col_filter:
        view_filter = st.selectbox(
            "Show",
            options=["All", "Active only", "Mature only"],
            key="batch_filter",
        )

    if view_filter == "Active only":
        items = list_active_batches()
    elif view_filter == "Mature only":
        items = list_mature_batches()
    else:
        items = list_all_batches()

    # Apply search
    if query:
        filtered = []
        for it in items:
            b = it["batch"]
            s = it.get("spawn") or {}
            haystack = " ".join([
                str(b.get("batch_tag") or ""),
                str(b.get("batch_code") or ""),
                str(b.get("notes") or ""),
                str(s.get("system_id") or ""),
                str(s.get("line_code") or ""),
            ]).lower()
            if query in haystack:
                filtered.append(it)
        items = filtered

    if not items:
        st.info("No batches match the current filter.")
        return

    for it in items:
        _render_batch_card(it)


# ============================================================
# PAGE
# ============================================================

def render_fry_batch_page():
    st.title("🐣 Fry Batch Tracking")
    st.caption("Track fry from hatch to jarring. One batch per spawn.")

    # KPIs
    stats = get_batch_stats()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Batches", stats["total_batches"])
    c2.metric("Active", stats["active_batches"])
    c3.metric("Mature", stats["mature_batches"])
    c4.metric("Fry Alive", stats["total_fry_alive"])

    st.markdown("---")

    _render_create_section()

    st.markdown("---")

    _render_list_section()


def render_fry_batches():
    """Alias entrypoint."""
    render_fry_batch_page()
