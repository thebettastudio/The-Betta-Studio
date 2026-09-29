# views/fry_batch_view.py
# Betta Farm Management System
# Session 15 — Fry batch tracking UI.
# Session 24B — Outcome panel + culled/female count editors.
# Session 24C — 4-row outcome layout + reconciliation badge.
#
# Session 28A/B2 — Jar Fry popover: Jarring Date picker.
# Session 29 — Fry batch fixes + M/F layout.
# Session 29/C — Batch-scoped outcomes.
# Session 29/D — Undo Jar + Delete Batch & Fish.
# Session 29/F — DERIVED current_count.
#
# Session 29/G (this revision) — Deferred initial count:
#   • Create Batch form has "Skip initial count (count later)" checkbox.
#   • Batch card shows ⏳ Awaiting count badge when deferred.
#   • New "📝 Set Initial Count" button opens a modal to set it later.
#   • List filter "Awaiting count".
#   • Stats row adds an "Awaiting count" metric.
#   • Outcome panel hides Initial/Current/Survival while deferred.

import datetime
from typing import Optional

import streamlit as st

from modules.fry_batch_manager import (
    list_all_batches,
    get_batch_stats,
    get_spawns_available_for_batch,
    suggest_batch_tag,
    create_batch_from_spawn,
    get_batch_parents,
    count_batch_jarred_fish,
    is_count_deferred,
    edit_batch,
    set_initial_count,
    advance_stage,
    assign_batch_tank,
    jar_fry_bulk,
    undo_batch_jar,
    delete_batch,
    delete_batch_and_fish,
    VALID_STAGES,
    ACTIVE_STAGES,
)
from modules.tank_registry import get_tank_dropdown_items
from modules.fish_manager import (
    VALID_GRADES,
    get_fish_age_days,
    format_fish_age,
    variety_of,
)
from modules.photo_service import photo_url
from modules.spawn_outcome import (
    compute_all_batch_outcomes,
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

STAGE_DUE_DAYS = 14
STAGE_DUE_HINT_STAGES = ("fry", "free_swimming")

PARENT_PHOTO_RADIUS = 24
PARENT_PHOTO_BORDER = "#E5E7EB"
PARENT_PHOTO_BG = "#F3F4F6"
PARENT_PHOTO_ASPECT = "4/3"

OUTCOME_COL_WEIGHT = 35
MF_COL_WEIGHT = 65

_JAR_MESSAGE_KEY = "_fry_jar_pending_message"
_DANGER_MESSAGE_KEY = "_fry_danger_pending_message"


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


def _survival_label(survival: Optional[float], deferred: bool = False) -> str:
    if deferred:
        return "—"
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


def _stage_due_hint(batch: dict, spawn: Optional[dict]) -> Optional[str]:
    stage = (batch.get("stage") or "").lower()
    if stage not in STAGE_DUE_HINT_STAGES:
        return None

    anchor_iso = None
    anchor_label = ""
    if spawn and spawn.get("free_swimming_date"):
        anchor_iso = spawn.get("free_swimming_date")
        anchor_label = "started free-swimming"
    elif batch.get("hatch_date"):
        anchor_iso = batch.get("hatch_date")
        anchor_label = "hatched"

    days = _days_since(anchor_iso)
    if days is None or days < STAGE_DUE_DAYS:
        return None

    return (
        f"⏰ This batch {anchor_label} **{days}d** ago and is still "
        f"marked `{stage}` — may be ready to advance or jar."
    )


def _queue_message(key: str, kind: str, text: str) -> None:
    st.session_state[key] = {"kind": kind, "text": text}


def _drain_message(key: str) -> None:
    msg = st.session_state.pop(key, None)
    if not msg:
        return
    kind = msg.get("kind")
    text = msg.get("text") or ""
    if kind == "success":
        st.success(text)
    elif kind == "warning":
        st.warning(text)
    elif kind == "error":
        st.error(text)
    else:
        st.info(text)


# ============================================================
# SET INITIAL COUNT MODAL
# ============================================================

@st.dialog("📝 Set Initial Count")
def _modal_set_initial_count(batch: dict):
    batch_uuid = batch["id"]
    batch_tag = batch.get("batch_tag") or "?"

    st.caption(
        f"Enter the final fry count for batch **{batch_tag}**. "
        f"This becomes the Initial value used in all metrics."
    )

    new_count = st.number_input(
        "Initial fry count",
        min_value=0,
        value=0,
        step=1,
        key=f"modal_initial_{batch_uuid}",
    )

    col_cancel, col_save = st.columns(2)

    with col_cancel:
        if st.button("Cancel", use_container_width=True, key=f"modal_cancel_{batch_uuid}"):
            st.rerun()

    with col_save:
        if st.button("Save", type="primary", use_container_width=True, key=f"modal_save_{batch_uuid}"):
            if set_initial_count(batch_uuid, int(new_count)):
                _queue_message(
                    _DANGER_MESSAGE_KEY, "success",
                    f"Initial count set to **{new_count}** for batch '{batch_tag}'.",
                )
                st.rerun()


# ============================================================
# M/F SHOWCASE
# ============================================================

def _parent_photo_html(fish: Optional[dict], gender_sym: str) -> str:
    wrapper_style = (
        f"width:100%;aspect-ratio:{PARENT_PHOTO_ASPECT};"
        f"border-radius:{PARENT_PHOTO_RADIUS}px;"
        f"border:1px solid {PARENT_PHOTO_BORDER};"
        f"background:{PARENT_PHOTO_BG};"
        f"display:flex;align-items:center;justify-content:center;"
        f"overflow:hidden;"
    )
    if fish and fish.get("photo_id"):
        url = photo_url(fish["photo_id"])
        inner = (
            f'<img src="{url}" '
            f'style="width:100%;height:100%;object-fit:cover;display:block;" />'
        )
    else:
        inner = (
            f'<div style="color:#9CA3AF;font-size:clamp(48px,8vw,96px);'
            f'line-height:1;">{gender_sym}</div>'
        )
    return f'<div style="{wrapper_style}">{inner}</div>'


def _parent_details_html(fish: Optional[dict], gender_sym: str, label: str) -> str:
    if not fish:
        return (
            f'<div style="text-align:center;margin-top:10px;">'
            f'<div style="font-weight:700;font-size:15px;color:#374151;">'
            f'{gender_sym} {label}</div>'
            f'<div style="font-size:12px;color:#9CA3AF;margin-top:2px;">'
            f'Unknown</div>'
            f'</div>'
        )

    sid = fish.get("system_id") or "?"
    grade = fish.get("grade") or "—"
    variety = variety_of(fish) or "—"
    age_days = get_fish_age_days(fish)
    age_txt = format_fish_age(age_days) if age_days is not None else "—"

    return (
        f'<div style="text-align:center;margin-top:10px;">'
        f'<div style="font-weight:700;font-size:15px;color:#374151;line-height:1.3;">'
        f'{gender_sym} {label}</div>'
        f'<div style="font-size:13px;color:#111827;margin-top:4px;font-family:monospace;">'
        f'{sid}</div>'
        f'<div style="font-size:12px;color:#6B7280;margin-top:4px;line-height:1.5;">'
        f'{grade} · {age_txt}<br/>{variety}</div>'
        f'</div>'
    )


def _render_mf_showcase(parents: dict, batch_uuid: str):
    st.markdown("##### 🧬 Parents")

    male = parents.get("male")
    female = parents.get("female")

    col_m, col_f = st.columns(2, gap="small")

    with col_m:
        st.markdown(_parent_photo_html(male, "♂"), unsafe_allow_html=True)
        st.markdown(_parent_details_html(male, "♂", "Male"), unsafe_allow_html=True)
        if male and male.get("id"):
            if st.button(
                "View fish →",
                key=f"view_male_{batch_uuid}_{male['id']}",
                use_container_width=True,
            ):
                st.session_state["fish_registry_focus_id"] = male["id"]
                st.session_state["_nav_to"] = "fish_registry"
                st.toast(
                    f"Open Fish Registry to view {male.get('system_id')}.",
                    icon="🐠",
                )

    with col_f:
        st.markdown(_parent_photo_html(female, "♀"), unsafe_allow_html=True)
        st.markdown(_parent_details_html(female, "♀", "Female"), unsafe_allow_html=True)
        if female and female.get("id"):
            if st.button(
                "View fish →",
                key=f"view_female_{batch_uuid}_{female['id']}",
                use_container_width=True,
            ):
                st.session_state["fish_registry_focus_id"] = female["id"]
                st.session_state["_nav_to"] = "fish_registry"
                st.toast(
                    f"Open Fish Registry to view {female.get('system_id')}.",
                    icon="🐠",
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

        # Session 29/G — deferred count checkbox
        skip_count = st.checkbox(
            "☐ Skip initial count (count later)",
            value=False,
            key="create_batch_skip_count",
            help="Check this if some fry are injured/weak and you want "
                 "to defer counting for 2–3 weeks. The batch will be "
                 "created without an Initial count; you set it later "
                 "from the batch card.",
        )

        col3, col4, col5 = st.columns([1, 1, 2])
        with col3:
            if skip_count:
                st.markdown(
                    '<div style="background:#FEF3C7;border-radius:8px;'
                    'padding:8px;color:#92400E;font-size:13px;text-align:center;'
                    'margin-top:8px;">Initial: <b>deferred</b></div>',
                    unsafe_allow_html=True,
                )
                initial_count = 0
            else:
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
                skip_initial_count=bool(skip_count),
            )
            if saved:
                if skip_count:
                    st.success(
                        f"Batch '{saved.get('batch_tag')}' created — "
                        f"Initial count deferred."
                    )
                else:
                    st.success(f"Batch '{saved.get('batch_tag')}' created.")
                st.rerun()


# ============================================================
# OUTCOME PANEL
# ============================================================

def _render_outcome_panel(outcome: dict, deferred: bool = False):
    st.markdown("##### 📊 Batch Outcome")

    if deferred:
        st.info(
            "⏳ Initial count not yet set. Set it to unlock metrics.",
            icon="⏳",
        )
        return

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
    current_count = int(batch.get("current_count") or 0)
    deferred = is_count_deferred(batch)

    with st.popover("🫙 Jar Fry", use_container_width=True):
        st.markdown(f"**Jar fry from batch '{batch_tag}'**")
        st.caption(
            "Bulk-create placeholder fish rows. You can edit grade, photo, "
            "and details later in Fish Registry."
        )

        if deferred:
            st.warning(
                "⚠️ Initial count is deferred. Set it from the card first "
                "so jarring counts make sense.",
                icon="⏳",
            )

        if not deferred and current_count == 0:
            st.warning(
                "⚠️ This batch has **0 unjarred fry** (derived). "
                "Nothing to jar. Check Initial count if this is wrong.",
                icon="⚠️",
            )

        jar_count = st.number_input(
            "How many fry to jar?",
            min_value=1,
            max_value=max(1, current_count or 1),
            value=min(10, current_count or 1),
            key=f"jar_count_{batch_uuid}",
        )

        gender = st.selectbox(
            "Assigned Gender",
            options=["Unsexed", "Male", "Female"],
            index=0,
            key=f"jar_gender_{batch_uuid}",
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
        )

        if st.button(
            "Confirm Jar",
            type="primary",
            key=f"jar_confirm_{batch_uuid}",
            use_container_width=True,
            disabled=deferred,
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
                new_derived = max(0, current_count - len(created))

                if failed:
                    _queue_message(
                        _JAR_MESSAGE_KEY, "warning",
                        f"Jarred {len(created)} fry — **{failed} failed** to create. "
                        f"Remaining in batch: {new_derived}. Check logs.",
                    )
                else:
                    _queue_message(
                        _JAR_MESSAGE_KEY, "success",
                        f"Jarred {len(created)} fry. Remaining in batch: {new_derived}.",
                    )
                st.rerun()

            elif failed:
                _queue_message(
                    _JAR_MESSAGE_KEY, "error",
                    f"Jarring failed — {failed} fry could not be created. Check logs.",
                )
                st.rerun()

            else:
                _queue_message(
                    _JAR_MESSAGE_KEY, "info",
                    "No fry were created. Check that the batch is linked to a spawn.",
                )
                st.rerun()


# ============================================================
# COUNTS POPOVER
# ============================================================

def _render_counts_popover(batch: dict):
    batch_uuid = batch["id"]
    current_count = int(batch.get("current_count") or 0)
    deferred = is_count_deferred(batch)

    with st.popover("🔢 Update Counts", use_container_width=True):
        st.markdown("**Update batch counts**")
        st.caption(
            "**Current** is derived automatically: "
            "`Initial − Jarred − Culled(pre) − Died`."
        )

        if deferred:
            st.warning(
                "⏳ Initial count deferred. Use **📝 Set Initial Count** "
                "on the card to set it.",
                icon="⏳",
            )

        # --- Read-only derived Current ---
        if not deferred:
            st.markdown(
                f'<div style="background:#F3F4F6;border-radius:8px;padding:10px;'
                f'margin-bottom:8px;">'
                f'<div style="font-size:11px;color:#6B7280;font-weight:600;'
                f'text-transform:uppercase;letter-spacing:0.5px;">Current (derived)</div>'
                f'<div style="font-size:22px;color:#111827;font-weight:700;'
                f'margin-top:2px;">{current_count}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        # --- Editable Initial ---
        default_initial = int(batch.get("initial_count") or 0)
        new_initial = st.number_input(
            "Initial fry count (total at hatch)",
            min_value=0,
            value=default_initial,
            step=1,
            key=f"count_init_{batch_uuid}",
            help="Total fry counted at hatch. If wrong, correct it here.",
        )

        new_culled_pre = st.number_input(
            "Culled (pre-jar)",
            min_value=0,
            value=int(batch.get("culled_count") or 0),
            step=1,
            key=f"count_culled_{batch_uuid}",
        )

        new_died = st.number_input(
            "Died (natural loss, pre-jar)",
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
                "initial_count": int(new_initial),
                "culled_count":  int(new_culled_pre),
                "died_count":    int(new_died),
                "female_count":  int(new_female),
            })
            if ok:
                st.success("Counts updated.")
                st.rerun()


# ============================================================
# EDIT / DELETE POPOVER
# ============================================================

def _render_edit_delete_popover(batch: dict):
    batch_uuid = batch["id"]
    batch_tag = batch.get("batch_tag") or "?"
    jarring_date = batch.get("jarring_date")

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

        if jarring_date:
            jarred_count = count_batch_jarred_fish(batch)

            st.markdown("**↩️ Undo Jar**")
            st.caption(
                f"Deletes all **{jarred_count}** fish jarred by this batch. "
                f"Current count will increase automatically (derived). "
                f"Clears jarring_date."
            )
            if jarred_count == 0:
                st.info(
                    "No matching jarred fish found.",
                    icon="ℹ️",
                )
            if st.button(
                "↩️ Undo Jar",
                key=f"undo_jar_{batch_uuid}",
                use_container_width=True,
                disabled=(jarred_count == 0),
            ):
                deleted, failed, err = undo_batch_jar(batch, delete_photos=True)
                if err:
                    _queue_message(_DANGER_MESSAGE_KEY, "error", f"Undo Jar failed: {err}")
                elif failed:
                    _queue_message(
                        _DANGER_MESSAGE_KEY, "warning",
                        f"Undo Jar: deleted {deleted}, {failed} failed. Check logs.",
                    )
                else:
                    _queue_message(
                        _DANGER_MESSAGE_KEY, "success",
                        f"Undo Jar complete — deleted {deleted} fish.",
                    )
                st.rerun()

            st.divider()

        jarred_count = count_batch_jarred_fish(batch)
        st.markdown("**🔥 Delete Batch & Jarred Fish**")
        st.caption(
            f"Deletes the batch **AND** all **{jarred_count}** fish jarred "
            f"by it. This is **permanent**. Type the batch tag "
            f"`{batch_tag}` to confirm."
        )
        confirm_tag = st.text_input(
            "Type batch tag to confirm",
            value="",
            key=f"confirm_tag_full_{batch_uuid}",
            placeholder=batch_tag,
        )
        tag_matches = (confirm_tag or "").strip() == batch_tag

        if st.button(
            "🔥 Delete Batch & Jarred Fish",
            key=f"del_full_{batch_uuid}",
            disabled=not tag_matches,
            use_container_width=True,
        ):
            d_fish, f_fish, b_ok, err = delete_batch_and_fish(batch, delete_photos=True)
            if err:
                _queue_message(_DANGER_MESSAGE_KEY, "error", f"Delete failed: {err}")
            elif not b_ok:
                _queue_message(
                    _DANGER_MESSAGE_KEY, "warning",
                    f"Deleted {d_fish} fish, but batch delete failed. Check logs.",
                )
            else:
                _queue_message(
                    _DANGER_MESSAGE_KEY, "success",
                    f"Deleted batch '{batch_tag}' and {d_fish} jarred fish."
                    + (f" ({f_fish} failed)" if f_fish else ""),
                )
            st.rerun()

        st.divider()

        st.markdown("**🗑️ Delete Batch Only**")
        st.caption("Deletes the batch record. Jarred fish are kept in Fish Registry.")
        confirm_del = st.checkbox(
            "Confirm delete batch (fish kept)",
            key=f"confirm_del_{batch_uuid}",
        )
        if st.button(
            "🗑️ Delete Batch Only",
            key=f"del_{batch_uuid}",
            disabled=not confirm_del,
            use_container_width=True,
        ):
            if delete_batch(batch_uuid):
                _queue_message(
                    _DANGER_MESSAGE_KEY, "success",
                    f"Batch '{batch_tag}' deleted. Jarred fish kept.",
                )
                st.rerun()


# ============================================================
# BATCH CARD
# ============================================================

def _render_batch_card(item: dict, outcome: Optional[dict] = None):
    batch = item["batch"]
    spawn = item.get("spawn")
    tank = item.get("tank")
    survival = item.get("survival")
    derived = item.get("derived") or {}

    batch_uuid = batch["id"]
    batch_tag = batch.get("batch_tag") or "?"
    stage = (batch.get("stage") or "fry").lower()
    icon = _stage_icon(stage)
    deferred = bool(derived.get("deferred"))

    parents = get_batch_parents(batch)

    with st.container(border=True):
        # Title + optional awaiting-count badge
        if deferred:
            st.markdown(f"### {icon} `{batch_tag}`  &nbsp; ⏳ _Awaiting count_")
        else:
            st.markdown(f"### {icon} `{batch_tag}`")

        if spawn:
            st.caption(
                f"From spawn **{spawn.get('system_id')}** — "
                f"Line: `{spawn.get('line_code')}` (`{spawn.get('generation')}`)"
            )
        else:
            st.caption("_No linked spawn._")

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

        hint = _stage_due_hint(batch, spawn)
        if hint:
            st.info(hint, icon="⏰")

        # Negative-derived warning (skip when deferred)
        if not deferred and derived.get("negative_warning"):
            st.error(
                f"⚠️ **Data inconsistency.** Derived Current would be "
                f"**{derived.get('raw_current')}** (negative). "
                f"Initial is lower than Jarred + Culled + Died. "
                f"Check Initial fry count and the jarred/culled/died numbers.",
                icon="🚨",
            )

        # Metric row
        col1, col2, col3, col4 = st.columns(4)

        if deferred:
            col1.metric("Initial", "—")
            col2.metric("Current", "—")
            col3.metric("Survival", "—")
        else:
            col1.metric("Initial", batch.get("initial_count") or 0)
            col2.metric("Current", batch.get("current_count") or 0)
            col3.metric("Survival", _survival_label(survival, deferred=False))

        col4.metric("Stage", f"{icon} {stage}")

        # Session 29/G — Set Initial Count CTA
        if deferred:
            st.info(
                "⏳ Initial count not yet set. Fry are still in the batch — "
                "set the count when they've stabilized (2–3 weeks).",
                icon="📝",
            )
            if st.button(
                "📝 Set Initial Count",
                type="primary",
                key=f"set_initial_btn_{batch_uuid}",
                use_container_width=True,
            ):
                _modal_set_initial_count(batch)

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

        if outcome and not deferred and outcome.get("verdict_key") not in ("unknown",):
            st.divider()
            col_outcome, col_mf = st.columns([OUTCOME_COL_WEIGHT, MF_COL_WEIGHT])

            with col_outcome:
                _render_outcome_panel(outcome, deferred=False)

            with col_mf:
                with st.container(border=True):
                    _render_mf_showcase(parents, batch_uuid=batch_uuid)

        elif deferred:
            st.divider()
            col_outcome, col_mf = st.columns([OUTCOME_COL_WEIGHT, MF_COL_WEIGHT])

            with col_outcome:
                _render_outcome_panel({}, deferred=True)

            with col_mf:
                with st.container(border=True):
                    _render_mf_showcase(parents, batch_uuid=batch_uuid)

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
            _render_edit_delete_popover(batch)


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
            options=["All", "Active only", "Mature only", "Awaiting count"],
            key="batch_filter",
        )

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
    elif view_filter == "Awaiting count":
        items = [
            d for d in all_items
            if (d.get("derived") or {}).get("deferred")
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

    outcome_map = compute_all_batch_outcomes()

    for it in items:
        batch = it["batch"]
        batch_id = batch.get("id")
        outcome = outcome_map.get(batch_id) if batch_id else None
        _render_batch_card(it, outcome=outcome)


# ============================================================
# PAGE
# ============================================================

def render_fry_batch_page():
    st.title("🐣 Fry Batch Tracking")
    st.caption("Track fry from hatch to jarring. One batch per spawn.")

    _drain_message(_JAR_MESSAGE_KEY)
    _drain_message(_DANGER_MESSAGE_KEY)

    stats = get_batch_stats()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Batches", stats["total_batches"])
    c2.metric("Active", stats["active_batches"])
    c3.metric("Mature", stats["mature_batches"])
    c4.metric("Total Fry Alive", stats["total_fry_alive"])
    c5.metric("⏳ Awaiting count", stats.get("awaiting_count", 0))

    st.markdown("---")

    _render_create_section()

    st.markdown("---")

    _render_list_section()


def render_fry_batches():
    """Alias entrypoint."""
    render_fry_batch_page()
