# views/fry_batch_view.py
# Betta Farm Management System
# Session 15 — Fry batch tracking UI.
# Session 24B — Outcome panel + culled/female count editors.
# Session 24C — 4-row outcome layout + reconciliation badge.
#
# Session 28A/B2 — Jar Fry popover: Jarring Date picker; batch's
#   jarring_date updated; passed to jar_fry_bulk for birth_date.
#
# Session 29 (this revision) — Fry batch fixes:
#   • Parent thumbnails (♂ + ♀) rendered inline with the spawn
#     caption using get_batch_parents().
#   • Jarring failures surfaced (jar_fry_bulk now returns
#     (created, failed)).
#   • _render_list_section() fetches list_all_batches() once and
#     filters locally — no re-fetch per filter branch.
#   • "Stage due?" hint when fry/free_swimming batch is older
#     than STAGE_DUE_DAYS.

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
    get_batch_parents,
    edit_batch,
    advance_stage,
    set_current_count,
    assign_batch_tank,
    jar_fry_bulk,
    delete_batch,
    VALID_STAGES,
    ACTIVE_STAGES,
)
from modules.tank_registry import get_tank_dropdown_items
from modules.fish_manager import VALID_GENDERS, VALID_GRADES
from modules.photo_service import photo_url
from modules.spawn_outcome import (
    compute_spawn_outcome,
    compute_all_spawn_outcomes,
    verdict_badge_html,
    grade_breakdown_short,
    reconciliation_html,
)


# ============================================================
# CONSTANTS
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

# If a batch has been in fry/free_swimming for this many days since
# hatch, show a soft "may be ready to advance" hint.
STAGE_DUE_DAYS = 60

PARENT_THUMB_SIZE = 56


# ============================================================
# HELPERS
# ============================================================

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


def _days_since(date_iso) -> Optional[int]:
    if not date_iso:
        return None
    try:
        d = datetime.date.fromisoformat(str(date_iso)[:10])
        return (datetime.date.today() - d).days
    except Exception:
        return None


def _parent_thumb_html(fish: Optional[dict], gender_sym: str) -> str:
    """
    Small rounded thumbnail for a parent fish. Falls back to a gray
    circle with the gender symbol if no photo_id.
    """
    if fish and fish.get("photo_id"):
        url = photo_url(fish["photo_id"])
        return (
            f'<div style="display:inline-block;text-align:center;margin-right:8px;">'
            f'<div style="width:{PARENT_THUMB_SIZE}px;height:{PARENT_THUMB_SIZE}px;'
            f'border-radius:10px;overflow:hidden;background:#F3F4F6;'
            f'border:1px solid #E5E7EB;">'
            f'<img src="{url}" style="width:100%;height:100%;object-fit:cover;display:block;" />'
            f'</div>'
            f'<div style="font-size:10px;color:#6B7280;margin-top:2px;">{gender_sym}</div>'
            f'</div>'
        )
    # Fallback: gray circle with gender symbol
    return (
        f'<div style="display:inline-block;text-align:center;margin-right:8px;">'
        f'<div style="width:{PARENT_THUMB_SIZE}px;height:{PARENT_THUMB_SIZE}px;'
        f'border-radius:10px;background:#F3F4F6;border:1px solid #E5E7EB;'
        f'display:flex;align-items:center;justify-content:center;'
        f'color:#9CA3AF;font-size:22px;">{gender_sym}</div>'
        f'<div style="font-size:10px;color:#9CA3AF;margin-top:2px;">'
        f'{fish.get("system_id") if fish else "—"}</div>'
        f'</div>'
    )


def _render_parent_photos(parents: dict):
    """Render ♂ + ♀ thumbnails inline (right-aligned)."""
    html = (
        f'<div style="display:flex;align-items:flex-start;justify-content:flex-end;">'
        + _parent_thumb_html(parents.get("male"), "♂")
        + _parent_thumb_html(parents.get("female"), "♀")
        + '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def _stage_due_hint(batch: dict) -> Optional[str]:
    """Return a soft warning if this batch may be ready to advance."""
    stage = (batch.get("stage") or "").lower()
    if stage not in ("fry", "free_swimming"):
        return None
    days = _days_since(batch.get("hatch_date"))
    if days is None or days < STAGE_DUE_DAYS:
        return None
    return (
        f"⏰ This batch hatched **{days}d** ago and is still marked "
        f"`{stage}` — may be ready to advance or jar."
    )


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
            s["id"]: (
                f"{s.get('system_id')} | {s.get('line_code')} "
                f"({s.get('generation')}) — {s.get('batch_name') or 'no batch name'}"
            )
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

        # Default hatch date = free_swimming_date - 3 days
        default_hatch = datetime.date.today()
        if selected_spawn and selected_spawn.get("free_swimming_date"):
            try:
                fsd = datetime.date.fromisoformat(
                    str(selected_spawn["free_swimming_date"])[:10]
                )
                default_hatch = fsd - datetime.timedelta(days=3)
            except Exception:
                pass

        with col2:
            batch_tag = st.text_input(
                "Batch Tag",
                value=suggested_tag,
                key="create_batch_tag",
                help="Short label for this batch.",
            )

        col3, col4, col5 = st.columns([1, 1, 2])
        with col3:
            initial_count = st.number_input(
                "Initial Fry Count",
                min_value=0,
                value=default_count,
                step=1,
                key="create_batch_initial",
            )
        with col4:
            hatch_date = st.date_input(
                "Hatch Date",
                value=default_hatch,
                key="create_batch_hatch",
                help="Date eggs hatched. Defaults to 3 days before "
                     "the spawn's free-swimming date.",
            )
        with col5:
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
                hatch_date=str(hatch_date),
            )
            if saved:
                st.success(f"Batch '{saved.get('batch_tag')}' created.")
                st.rerun()


# ============================================================
# OUTCOME PANEL (4-row layout)
# ============================================================

def _render_outcome_panel(outcome: dict):
    st.markdown("**📊 Batch Outcome**")

    initial   = outcome.get("initial_count", 0)
    current   = outcome.get("current_count", 0)
    jarred    = outcome.get("jarred_alive", 0)
    culled_pre    = outcome.get("culled_pre", 0)
    culled_jarred = outcome.get("culled_jarred", 0)
    died      = outcome.get("died", 0)
    females   = outcome.get("female_count", 0)
    total_alive = current + jarred

    st.caption(f"**📦 Inventory** — Initial: {initial}")
    col1, col2, col3 = st.columns(3)
    col1.metric("Current (unjarred)", current)
    col2.metric("Jarred alive", jarred)
    col3.metric("Total alive", total_alive)

    st.caption("**💀 Losses**")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Culled (pre-jar)", culled_pre)
    col2.metric("Culled (jarred)", culled_jarred)
    col3.metric("Died", died)
    col4.metric("♀ Females kept", females)

    st.caption("**📈 Quality**")
    surv = outcome.get("survival")
    col1, col2, col3 = st.columns(3)
    col1.metric("Survival %", f"{surv*100:.0f}%" if surv is not None else "—")
    with col2:
        st.markdown(
            f'<div style="margin-top:6px;">{verdict_badge_html(outcome)}</div>',
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f'<div style="margin-top:8px;">{reconciliation_html(outcome)}</div>',
            unsafe_allow_html=True,
        )

    st.caption(f"_{outcome.get('verdict_reason', '')}_")

    breakdown = grade_breakdown_short(outcome)
    if breakdown and breakdown != "—":
        st.caption(f"**🏅 Grades:** {breakdown}")

    best = outcome.get("best_fish")
    if best:
        st.caption(
            f"🏆 Best: `{best.get('system_id') or '?'}` "
            f"({best.get('grade') or '—'})"
        )


# ============================================================
# JAR POPOVER
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

        jarring_date = st.date_input(
            "Jarring Date",
            value=datetime.date.today(),
            key=f"jar_date_{batch_uuid}",
            help="Backdate if jarring happened earlier. This date becomes "
                 "each jarred fish's birth_date for age/stage computation.",
        )

        if st.button(
            "Confirm Jar",
            type="primary",
            key=f"jar_confirm_{batch_uuid}",
            use_container_width=True,
        ):
            created, failed = jar_fry_bulk(
                batch_id=batch_uuid,
                count=int(jar_count),
                gender=gender,
                grade=grade,
                location=location.strip(),
                jarring_date=str(jarring_date),
            )
            if created:
                new_count = max(0, (batch.get("current_count") or 0) - len(created))
                set_current_count(batch_uuid, new_count)
                if failed:
                    st.warning(
                        f"Jarred {len(created)} fry — **{failed} failed** to create. "
                        f"Remaining in batch: {new_count}. Check logs."
                    )
                else:
                    st.success(
                        f"Jarred {len(created)} fry. Remaining in batch: {new_count}."
                    )
                st.rerun()
            elif failed:
                st.error(f"Jarring failed — {failed} fry could not be created. Check logs.")


# ============================================================
# COUNTS POPOVER
# ============================================================

def _render_counts_popover(batch: dict):
    batch_uuid = batch["id"]

    with st.popover("🔢 Update Counts", use_container_width=True):
        st.markdown("**Update batch counts**")
        st.caption(
            "Current = unjarred fry alive. "
            "Culled = fry culled before jarring. "
            "Died = natural loss. "
            "Females = fry kept in sorority (not individually tracked)."
        )

        new_current = st.number_input(
            "Current fry count (unjarred, alive)",
            min_value=0,
            value=int(batch.get("current_count") or 0),
            step=1,
            key=f"count_cur_{batch_uuid}",
        )
        new_culled_pre = st.number_input(
            "Culled (pre-jar)",
            min_value=0,
            value=int(batch.get("culled_count") or 0),
            step=1,
            key=f"count_culled_{batch_uuid}",
        )
        new_died = st.number_input(
            "Died (natural loss)",
            min_value=0,
            value=int(batch.get("died_count") or 0),
            step=1,
            key=f"count_died_{batch_uuid}",
        )
        new_female = st.number_input(
            "Female count (kept in sorority)",
            min_value=0,
            value=int(batch.get("female_count") or 0),
            step=1,
            key=f"count_female_{batch_uuid}",
        )

        if st.button(
            "Save Counts",
            type="primary",
            use_container_width=True,
            key=f"save_counts_{batch_uuid}",
        ):
            ok = edit_batch(batch_uuid, {
                "current_count": int(new_current),
                "culled_count":  int(new_culled_pre),
                "died_count":    int(new_died),
                "female_count":  int(new_female),
            })
            if ok:
                st.success("Counts updated.")
                st.rerun()


# ============================================================
# BATCH CARD
# ============================================================

def _render_batch_card(item: dict, outcome: Optional[dict] = None):
    batch = item["batch"]
    spawn = item.get("spawn")
    tank = item.get("tank")
    survival = item.get("survival")

    batch_uuid = batch["id"]
    batch_tag = batch.get("batch_tag") or "?"
    stage = (batch.get("stage") or "fry").lower()
    icon = _stage_icon(stage)

    # Session 29 — fetch parents once per card
    parents = get_batch_parents(batch)

    with st.container(border=True):
        col_h, col_thumbs = st.columns([3, 2])

        with col_h:
            st.markdown(f"### {icon} `{batch_tag}`")
            if spawn:
                st.caption(
                    f"From spawn **{spawn.get('system_id')}** — "
                    f"Line: `{spawn.get('line_code')}` (`{spawn.get('generation')}`)"
                )
            else:
                st.caption("_No linked spawn._")

        with col_thumbs:
            _render_parent_photos(parents)

        # Stage selector row
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

        # Stage-due hint
        hint = _stage_due_hint(batch)
        if hint:
            st.info(hint, icon="⏰")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Initial", batch.get("initial_count") or 0)
        col2.metric("Current", batch.get("current_count") or 0)
        col3.metric("Survival", _survival_label(survival))
        col4.metric("Stage", f"{icon} {stage}")

        culled_pre_n = batch.get("culled_count") or 0
        died_n = batch.get("died_count") or 0
        female_n = batch.get("female_count") or 0
        st.caption(
            f"🥚 Hatch: {_format_date(batch.get('hatch_date'))} | "
            f"🫙 Jarred: {_format_date(batch.get('jarring_date'))} | "
            f"🪣 Tank: {tank.get('location_code') if tank else 'Unassigned'} | "
            f"🚫 Culled: {culled_pre_n} | 💀 Died: {died_n} | ♀ Females: {female_n}"
        )

        if batch.get("notes"):
            st.info(batch["notes"])

        if outcome and outcome.get("verdict_key") not in ("unknown",):
            st.divider()
            _render_outcome_panel(outcome)

        st.divider()

        col_a, col_b, col_c, col_d = st.columns(4)

        with col_a:
            _render_jar_popover(batch)

        with col_b:
            _render_counts_popover(batch)

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

    # Session 29 — fetch once, filter locally.
    all_items = list_all_batches()

    if view_filter == "Active only":
        items = [
            d for d in all_items
            if (d["batch"].get("stage") or "").lower() in ACTIVE_STAGES
        ]
    elif view_filter == "Mature only":
        items = [
            d for d in all_items
            if (d["batch"].get("stage") or "").lower() not in ACTIVE_STAGES
        ]
    else:
        items = all_items

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

    outcome_map = compute_all_spawn_outcomes()

    for it in items:
        batch = it["batch"]
        spawn_id = batch.get("spawn_id")
        outcome = outcome_map.get(spawn_id) if spawn_id else None
        _render_batch_card(it, outcome=outcome)


# ============================================================
# PAGE
# ============================================================

def render_fry_batch_page():
    st.title("🐣 Fry Batch Tracking")
    st.caption("Track fry from hatch to jarring. One batch per spawn.")

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
