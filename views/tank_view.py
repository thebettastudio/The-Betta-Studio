# views/tank_view.py
# Betta Farm Management System
# Session 10 — Ported to Supabase via tank_registry + fish_manager.
#
# Session 26H.7 — Step 4 (this revision): full UX rewrite.
#   • Expander-based tank list (compact row → click to expand)
#     - Sortable: Type→Number (default), Status→Number, ⭐ Starred first,
#       Number only, Recently added
#     - Filter bar: search, purpose, type, ⭐ starred only
#     - Clickable KPI row (Total / Empty / Reserved / Occupied / Cleaning / Retired)
#   • Status dot + badge color-coded per status
#   • Reservation yellow badge with reason + expiry + "expiring soon" banner
#   • ⭐ Starred indicator inherited from fish.is_starred (via tank_occupants)
#   • Occupant chips (fish + fry batch) with tooltips
#   • Assign modal: 2 tabs (Fish / Fry Batch)
#   • Reserve modal: reason required + reserved_for autocomplete +
#     big quick-pick buttons (+1d/+3d/+1w/+2w/+1mo/No expiry) + large calendar
#   • Transfer-on-delete modal (Q3 Option D) for occupied tanks
#   • Change-purpose modal with old→new tape code preview + tape rewrite prompt
#   • Reservation-warning toasts (reads st.session_state['_reservation_warnings'])
#   • Custom tank types are saved implicitly — the dropdown merges
#     VALID_TANK_TYPES with distinct tank_type values already in the DB,
#     so newly-registered custom types reappear as reusable options.
#   • Backward-compat: all calls now go through modules/tank_registry.py's
#     new API (no direct database.py imports for tank mutations).

from __future__ import annotations

import datetime as _dt
from typing import Optional

import streamlit as st

from modules.tank_registry import (
    # read
    list_all_tanks,
    find_tank,
    list_available_tanks,
    list_reserved_tanks,
    get_tank_stats,
    get_tank_dropdown_items,
    # create / edit
    register_tank,
    edit_tank,
    set_tank_status,
    change_purpose_and_regenerate_code,
    # occupant API
    add_occupant_to_tank,
    add_fry_batch_to_tank,
    remove_occupant,
    transfer_occupant,
    # backward-compat
    assign_fish_to_tank,
    unassign_tank,
    # reservation API
    reserve_tank,
    cancel_reservation,
    move_reservation,
    get_expiring,
    # safe delete
    delete_tank_safely,
    # constants
    VALID_TANK_TYPES,
    VALID_STATUSES,
    VALID_PURPOSES,
)
from modules.fish_manager import get_fish_dropdown_items
from modules.fry_batch_manager import list_active_batches
from modules.photo_service import photo_url


# ============================================================
# PRESENTATION LABELS
# ============================================================

PURPOSE_LABELS = {
    "Jarring":       "🫙 Jarring — Individual male/female jar",
    "Conditioning":  "🥩 Conditioning — Pre-spawn breeder conditioning",
    "Spawning":      "🥚 Spawning — Breeding pair setup",
    "Fry Nursery":   "🌿 Fry Nursery — Free-swimming fry container",
    "Grow-Out":      "🪴 Grow-Out — Fry / juvenile grow-out",
    "Sorority":      "👑 Sorority — Female colony tank",
    "Quarantine":    "🏥 Quarantine — Medical / treatment",
    "Sales Display": "🛒 Sales Display — Showcase / grooming",
    "Storage":       "📦 Storage — Empty / multi-purpose",
    "Other":         "❔ Other — Custom purpose",
}

PURPOSE_ICONS = {
    "Jarring":       "🫙",
    "Conditioning":  "🥩",
    "Spawning":      "🥚",
    "Fry Nursery":   "🌿",
    "Grow-Out":      "🪴",
    "Sorority":      "👑",
    "Quarantine":    "🏥",
    "Sales Display": "🛒",
    "Storage":       "📦",
    "Other":         "❔",
}

TANK_TYPE_LABELS = {
    "Grow-Out Planggana (Large)":     "Grow-Out Planggana (Large)",
    "Spawning Planggana (Small)":     "Spawning Planggana (Small)",
    "6-Liter Water Bottle":           "6-Liter Water Bottle",
    "Empi Glass/Jar":                 "Empi (Emperador) Glass / Jar",
    "Glass Aquarium":                 "Glass Aquarium",
    "Sorority Basin":                 "Sorority / Female Basin",
    "Quarantine Jar":                 "Quarantine / Treatment Jar",
    "Custom":                         "➕ Other / Custom Container...",
}

CUSTOM_TANK_SENTINEL = "Custom"

# Status visual config: (dot emoji, badge bg, badge fg)
STATUS_STYLE = {
    "Empty / Idle":         ("⚪", "#E5E7EB", "#374151"),
    "Reserved":             ("🟡", "#FEF3C7", "#92400E"),
    "Occupied":             ("🟢", "#D1FAE5", "#065F46"),
    "Cleaning / Quarantine":("🟠", "#FED7AA", "#9A3412"),
    "Retired":              ("⚫", "#E5E7EB", "#6B7280"),
}


def _purpose_label(p: str) -> str:
    return PURPOSE_LABELS.get(p, p)


def _purpose_icon(p: str) -> str:
    return PURPOSE_ICONS.get(p, "❔")


def _tank_type_label(t: str) -> str:
    return TANK_TYPE_LABELS.get(t, t)


def _status_dot(status: str) -> str:
    return STATUS_STYLE.get(status or "Empty / Idle", ("⚪", "#E5E7EB", "#374151"))[0]


def _status_badge_html(status: str) -> str:
    _dot, bg, fg = STATUS_STYLE.get(status or "Empty / Idle", ("⚪", "#E5E7EB", "#374151"))
    return (
        f'<span style="display:inline-block;background:{bg};color:{fg};'
        f'font-size:12px;font-weight:600;padding:2px 10px;border-radius:10px;">'
        f'{status or "Empty / Idle"}</span>'
    )


def _numeric_tail(code: str) -> int:
    """Extract trailing number from a tape code (JAR-0007 → 7)."""
    if not code:
        return 999999
    tail = ""
    for ch in reversed(str(code)):
        if ch.isdigit():
            tail = ch + tail
        else:
            break
    return int(tail) if tail else 999999


def _is_starred_occupant(occupant_type: str, occupant_id: str, fish_index: dict) -> bool:
    """Return True if this occupant is a starred fish."""
    if occupant_type != "fish":
        return False
    fish = fish_index.get(occupant_id)
    return bool(fish and fish.get("is_starred"))


# ============================================================
# RESERVATION WARNING TOASTS (reads session_state stash)
# ============================================================

def _drain_reservation_warnings():
    """
    Pop and display one-shot reservation-cancellation warnings
    stashed by database.assign_occupant() / add_tank_occupant().
    Call once near the top of the page render.
    """
    warnings = st.session_state.pop("_reservation_warnings", [])
    for w in warnings:
        loc = w.get("location_code") or "?"
        reason = w.get("reason") or "reserved"
        rfor = w.get("reserved_for")
        msg = f"Reservation on **{loc}** ({reason}"
        if rfor:
            msg += f" for {rfor}"
        msg += ") was auto-cancelled because an occupant was assigned."
        st.warning(msg, icon="⚠️")


# ============================================================
# CUSTOM TANK TYPE MERGING (Option A)
# ============================================================

def _get_tank_type_options() -> list[str]:
    """
    Merge hardcoded VALID_TANK_TYPES with any custom tank_type values
    already in the DB, so newly-registered custom types become reusable.
    """
    try:
        existing = {t.get("tank_type") for t in list_all_tanks() if t.get("tank_type")}
    except Exception:
        existing = set()

    merged = []
    for t in VALID_TANK_TYPES:
        merged.append(t)
    for t in sorted(existing):
        if t not in merged:
            merged.append(t)
    return merged


# ============================================================
# FISH / FRY-BATCH DROPDOWN HELPERS
# ============================================================

def _fish_options_for_assign(current_tank_id: str) -> list[dict]:
    """
    Fish dropdown for the assign modal.
    Excludes deceased / sold / retired / culled.
    Includes: unassigned fish + fish already in THIS tank (so user sees them).
    """
    out = []
    for f in get_fish_dropdown_items():
        out.append({
            "id": f["id"],
            "label": f.get("label") or f.get("system_id") or "?",
        })
    return out


def _fry_batch_options(current_tank_id: str) -> list[dict]:
    """Active fry batches for the assign modal."""
    out = []
    try:
        for item in list_active_batches():
            b = item["batch"]
            tank = item.get("tank")
            tag = b.get("batch_tag") or b.get("id", "")[:8]
            loc = tank.get("location_code") if tank else None
            label = f"🐣 {tag}"
            if loc:
                label += f"  (currently {loc})"
            out.append({"id": b["id"], "label": label})
    except Exception:
        pass
    return out


# ============================================================
# REGISTRATION FORM
# ============================================================

def _render_registration_form():
    st.subheader("Register New Tank or Container")

    tank_type_options = _get_tank_type_options()

    with st.form("tank_register_form", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            selected_type = st.selectbox(
                "Container / Tank Type",
                options=tank_type_options,
                format_func=_tank_type_label,
                help="Pick an existing type or choose 'Other / Custom' to add a new one. "
                     "New types are remembered for next time.",
            )

            custom_type = ""
            if selected_type == CUSTOM_TANK_SENTINEL:
                custom_type = st.text_input(
                    "✏️ Enter Custom Container Name",
                    placeholder="e.g. 1.5L Jarring Bottle, 20L Storage Box",
                    help="This name will be saved and appear in the dropdown next time.",
                )

            capacity = st.number_input(
                "Capacity (Liters)",
                min_value=0.1, max_value=500.0, value=6.0, step=0.5,
            )

            purpose = st.selectbox(
                "Container Purpose / Role",
                options=VALID_PURPOSES,
                format_func=_purpose_label,
            )

        with col2:
            fish_opts = [{"id": None, "label": "— None (Empty) —"}] + get_fish_dropdown_items()
            selected_fish_idx = st.selectbox(
                "Current Occupant (Optional)",
                options=range(len(fish_opts)),
                format_func=lambda i: fish_opts[i].get("label") or "?",
                help="Any active fish can be assigned. Leave as None for empty containers.",
            )
            selected_fish_id = fish_opts[selected_fish_idx]["id"]

            photo_file = st.file_uploader(
                "📷 Container Photo (Optional)",
                type=["jpg", "jpeg", "png"],
            )
            notes = st.text_area(
                "Notes / Setup Details",
                placeholder="e.g. Almond leaf tea water, sponge filter installed",
            )

        submit = st.form_submit_button("🏷️ Register Container & Generate Tape Tag", type="primary")

    if not submit:
        return

    if selected_type == CUSTOM_TANK_SENTINEL and not custom_type.strip():
        st.error("Please enter a custom container name.")
        return

    final_type = custom_type.strip() if selected_type == CUSTOM_TANK_SENTINEL else selected_type

    with st.spinner("Generating tape tag & registering container..."):
        res = register_tank(
            tank_type=final_type,
            capacity_liters=capacity,
            purpose=purpose,
            photo_file=photo_file,
            current_occupant_id=selected_fish_id,
            notes=notes,
        )

    if not res:
        st.error("Registration failed — check logs.")
        return

    st.success("Container registered!")
    st.markdown(f"""
    <div style="background-color: #FEF3C7; border: 2px dashed #D97706; padding: 16px; border-radius: 12px; text-align: center; margin: 12px 0;">
        <span style="font-size: 14px; color: #92400E; font-weight: bold; text-transform: uppercase;">✍️ WRITE THIS ON PAINTER'S TAPE:</span>
        <h1 style="font-size: 42px; color: #B45309; margin: 8px 0; font-family: monospace; letter-spacing: 2px;">{res['location_code']}</h1>
        <span style="font-size: 12px; color: #B45309;">System ID: {res['system_id']}</span>
    </div>
    """, unsafe_allow_html=True)

    if res.get("photo_id"):
        st.image(photo_url(res["photo_id"]), caption="Container Photo", width=250)


# ============================================================
# MODAL: ASSIGN OCCUPANT (2 tabs — Fish / Fry Batch)
# ============================================================

@st.dialog("📥 Assign Occupant")
def _modal_assign_occupant(tank: dict):
    tank_id = tank["id"]
    loc = tank.get("location_code") or "?"
    st.caption(f"Assigning to **{loc}** ({tank.get('tank_type') or '?'})")

    tab_fish, tab_batch = st.tabs(["🐟 Fish", "🐣 Fry Batch"])

    with tab_fish:
        fish_opts = _fish_options_for_assign(tank_id)
        if not fish_opts:
            st.info("No assignable fish found.")
        else:
            idx = st.selectbox(
                "Select Fish",
                options=range(len(fish_opts)),
                format_func=lambda i: fish_opts[i]["label"],
                key=f"assign_fish_{tank_id}",
            )
            if st.button("Assign Fish", type="primary", use_container_width=True, key=f"assign_fish_btn_{tank_id}"):
                fid = fish_opts[idx]["id"]
                if add_occupant_to_tank(tank_id, "fish", fid, role="primary"):
                    st.success("Fish assigned.")
                    st.rerun()

    with tab_batch:
        batch_opts = _fry_batch_options(tank_id)
        if not batch_opts:
            st.info("No active fry batches found.")
        else:
            idx = st.selectbox(
                "Select Fry Batch",
                options=range(len(batch_opts)),
                format_func=lambda i: batch_opts[i]["label"],
                key=f"assign_batch_{tank_id}",
            )
            if st.button("Assign Fry Batch", type="primary", use_container_width=True, key=f"assign_batch_btn_{tank_id}"):
                bid = batch_opts[idx]["id"]
                if add_fry_batch_to_tank(tank_id, bid):
                    st.success("Fry batch assigned.")
                    st.rerun()


# ============================================================
# MODAL: RESERVE TANK (big date picker + quick-picks + autocomplete)
# ============================================================

def _suggest_reserved_for() -> list[str]:
    """Suggest values for reserved_for: spawn codes, line codes."""
    suggestions = set()
    try:
        from database import get_all_spawns
        for s in get_all_spawns():
            if s.get("system_id"):
                suggestions.add(s["system_id"])
            if s.get("line_code"):
                suggestions.add(s["line_code"])
    except Exception:
        pass
    return sorted(suggestions)[:20]


@st.dialog("🟡 Reserve Tank", width="large")
def _modal_reserve(tank: dict):
    tank_id = tank["id"]
    loc = tank.get("location_code") or "?"
    st.caption(f"Reserving **{loc}** ({tank.get('tank_type') or '?'})")

    reason = st.text_input(
        "Why are you reserving this tank? *",
        placeholder="e.g. For AVT-F2 spawn, For recovery of FISH-0042",
        key=f"res_reason_{tank_id}",
        help="Required. Helps you remember later.",
    )

    # Autocomplete via datalist-like selectbox OR free text
    suggested_for = _suggest_reserved_for()
    reserved_for = st.text_input(
        "Reserved for (optional)",
        placeholder="e.g. SPN-AVT-F1-01, Line AVT",
        key=f"res_for_{tank_id}",
        help="Free text — type anything. Suggestions below if you want to reuse one.",
    )
    if suggested_for:
        with st.expander("💡 Suggestions", expanded=False):
            st.caption(" · ".join(suggested_for))

    st.markdown("**Expiry date** — quick pick or choose a custom date:")

    # Quick-pick buttons
    today = _dt.date.today()
    qc1, qc2, qc3 = st.columns(3)
    qc4, qc5, qc6 = st.columns(3)

    quick_choice = st.session_state.get(f"res_quick_{tank_id}", None)

    with qc1:
        if st.button("+1 day", use_container_width=True, key=f"resq_1d_{tank_id}"):
            quick_choice = today + _dt.timedelta(days=1)
    with qc2:
        if st.button("+3 days", use_container_width=True, key=f"resq_3d_{tank_id}"):
            quick_choice = today + _dt.timedelta(days=3)
    with qc3:
        if st.button("+1 week", use_container_width=True, key=f"resq_1w_{tank_id}"):
            quick_choice = today + _dt.timedelta(weeks=1)
    with qc4:
        if st.button("+2 weeks", use_container_width=True, key=f"resq_2w_{tank_id}"):
            quick_choice = today + _dt.timedelta(weeks=2)
    with qc5:
        if st.button("+1 month", use_container_width=True, key=f"resq_1m_{tank_id}"):
            quick_choice = today + _dt.timedelta(days=30)
    with qc6:
        if st.button("No expiry", use_container_width=True, key=f"resq_ne_{tank_id}"):
            quick_choice = "none"

    st.session_state[f"res_quick_{tank_id}"] = quick_choice

    # Determine default date for the calendar
    if quick_choice == "none":
        st.info("No expiry set — reservation stays until manually cancelled.")
        chosen_date = None
    elif isinstance(quick_choice, _dt.date):
        st.success(f"Quick pick: **{quick_choice.isoformat()}**")
        chosen_date = quick_choice
    else:
        chosen_date = st.date_input(
            "Or pick a custom date",
            value=today + _dt.timedelta(days=7),
            key=f"res_date_{tank_id}",
            format="YYYY-MM-DD",
        )

    st.divider()
    if st.button("Confirm Reservation", type="primary", use_container_width=True, key=f"res_confirm_{tank_id}"):
        if not reason.strip():
            st.error("A reservation reason is required.")
            return
        until_iso = chosen_date.isoformat() if chosen_date else None
        ok = reserve_tank(
            tank_id=tank_id,
            reason=reason.strip(),
            reserved_for=reserved_for.strip() or None,
            reserved_until=until_iso,
        )
        if ok:
            st.success("Reserved.")
            st.rerun()


# ============================================================
# MODAL: CHANGE PURPOSE (+ tape regen)
# ============================================================

@st.dialog("🔄 Change Purpose & Regenerate Tape Code", width="large")
def _modal_change_purpose(tank: dict):
    tank_id = tank["id"]
    old_purpose = tank.get("purpose") or "Other"
    old_code = tank.get("location_code") or "?"

    st.warning(
        f"Changing purpose regenerates the tape code. You'll need to "
        f"re-write the painter's tape on the physical container.",
        icon="⚠️",
    )
    st.markdown(f"**Current:** `{old_code}` — purpose: *{old_purpose}*")

    new_purpose = st.selectbox(
        "New Purpose",
        options=VALID_PURPOSES,
        index=VALID_PURPOSES.index(old_purpose) if old_purpose in VALID_PURPOSES else len(VALID_PURPOSES)-1,
        format_func=_purpose_label,
        key=f"cp_purpose_{tank_id}",
    )

    # Preview new code by peeking at the generator
    try:
        from modules.id_generator import generate_tape_code
        preview = generate_tape_code(new_purpose)
    except Exception:
        preview = "(preview unavailable)"

    if new_purpose != old_purpose:
        st.info(f"**Old → New tape code:** `{old_code}` → `{preview}`")
    else:
        st.caption("No change — pick a different purpose to regenerate.")

    confirm = st.checkbox(
        "I understand the tape code will change and I'll re-write the label.",
        key=f"cp_confirm_{tank_id}",
    )

    if st.button(
        "Confirm Change",
        type="primary",
        use_container_width=True,
        disabled=not confirm or new_purpose == old_purpose,
        key=f"cp_btn_{tank_id}",
    ):
        result = change_purpose_and_regenerate_code(tank_id, new_purpose)
        if result:
            old_c, new_c = result
            st.success(f"Purpose changed. New tape code: **{new_c}** (was {old_c})")
            st.rerun()
        else:
            st.error("Change failed.")


# ============================================================
# MODAL: TRANSFER-ON-DELETE (Q3 Option D)
# ============================================================

@st.dialog("🗑️ Delete Tank — Transfer Occupants", width="large")
def _modal_delete_with_transfer(tank: dict, occupants: list[dict], fish_index: dict):
    tank_id = tank["id"]
    loc = tank.get("location_code") or "?"

    st.error(
        f"**{loc}** has {len(occupants)} occupant(s). "
        f"Pick a destination tank for each before deleting.",
        icon="⚠️",
    )

    # Other tanks available as destinations
    other_tanks = [t for t in list_all_tanks() if t["id"] != tank_id]
    dest_opts = [{"id": None, "label": "— Pick destination —"}] + [
        {"id": t["id"], "label": f"{t.get('location_code')} ({t.get('tank_type')})"}
        for t in other_tanks
    ]

    transfers = {}
    for occ in occupants:
        label = _occupant_chip_text(occ, fish_index)
        key = (occ["occupant_type"], occ["occupant_id"])
        with st.container(border=True):
            st.markdown(f"**{label}**")
            idx = st.selectbox(
                "Transfer to:",
                options=range(len(dest_opts)),
                format_func=lambda i, opts=dest_opts: opts[i]["label"],
                key=f"del_dest_{tank_id}_{occ['occupant_id'][:8]}",
                label_visibility="collapsed",
            )
            chosen = dest_opts[idx]["id"]
            if chosen:
                transfers[key] = chosen

    st.divider()
    all_assigned = len(transfers) == len(occupants)

    if st.button(
        "Transfer All & Delete Tank",
        type="primary",
        use_container_width=True,
        disabled=not all_assigned,
        key=f"del_confirm_{tank_id}",
    ):
        ok, msg = delete_tank_safely(tank_id, transfers=transfers)
        if ok:
            st.success("Tank deleted. Occupants transferred.")
            st.rerun()
        else:
            st.error(msg)

    if not all_assigned:
        st.caption(f"Assign destinations for all {len(occupants)} occupant(s) to enable delete.")


# ============================================================
# OCCUPANT CHIP RENDERING
# ============================================================

def _occupant_chip_text(occ: dict, fish_index: dict) -> str:
    """Return a human-readable label for one tank_occupants row."""
    otype = occ.get("occupant_type")
    oid = occ.get("occupant_id")
    role = occ.get("role") or ""

    if otype == "fish":
        fish = fish_index.get(oid)
        if not fish:
            return f"🐟 (unknown fish {str(oid)[:8]})"
        star = "⭐ " if fish.get("is_starred") else ""
        sid = fish.get("system_id") or "?"
        gender = fish.get("gender") or "?"
        variety = fish.get("variety") or "—"
        return f"{star}🐟 {sid} · {gender} · {variety}"
    elif otype == "fry_batch":
        # Try to enrich with batch tag via database lookup (lightweight)
        try:
            from database import get_fry_batch_by_id
            batch = get_fry_batch_by_id(oid)
            tag = batch.get("batch_tag") if batch else str(oid)[:8]
        except Exception:
            tag = str(oid)[:8]
        return f"🐣 Fry batch: {tag}"
    return f"{otype} {str(oid)[:8]}"


def _render_occupant_chips(occupants: list[dict], fish_index: dict):
    if not occupants:
        st.caption("_No occupants._")
        return
    for occ in occupants:
        text = _occupant_chip_text(occ, fish_index)
        role = occ.get("role") or ""
        role_note = f"  `{role}`" if role and role != "primary" else ""
        col_chip, col_action = st.columns([5, 1])
        with col_chip:
            st.markdown(f"**{text}**{role_note}")
        with col_action:
            if st.button(
                "Remove",
                key=f"rm_occ_{occ['tank_id']}_{occ['occupant_type']}_{occ['occupant_id'][:8]}",
                use_container_width=True,
            ):
                if remove_occupant(occ["tank_id"], occ["occupant_type"], occ["occupant_id"]):
                    st.success("Removed.")
                    st.rerun()


# ============================================================
# RESERVATION DISPLAY HELPERS
# ============================================================

def _is_expiring_soon(tank: dict, days: int = 3) -> bool:
    until = tank.get("reserved_until")
    if not until:
        return False
    try:
        d = _dt.date.fromisoformat(str(until))
        return (d - _dt.date.today()).days <= days
    except Exception:
        return False


def _reservation_summary(tank: dict) -> str:
    reason = tank.get("reserved_reason") or "reserved"
    rfor = tank.get("reserved_for")
    until = tank.get("reserved_until")
    parts = [reason]
    if rfor:
        parts.append(f"for {rfor}")
    if until:
        parts.append(f"until {until}")
    return " · ".join(parts)


# ============================================================
# COLLAPSED ROW / EXPANDED CARD
# ============================================================

def _render_tank_row(tank: dict, fish_index: dict):
    tank_id = tank["id"]
    loc = tank.get("location_code") or "?"
    ttype = _tank_type_label(tank.get("tank_type") or "")
    status = tank.get("status") or "Empty / Idle"
    purpose = tank.get("purpose") or "Other"

    occupants = tank.get("_occupants") or []
    starred = any(_is_starred_occupant(o["occupant_type"], o["occupant_id"], fish_index) for o in occupants)

    # ---- Collapsed row header ----
    dot = _status_dot(status)
    star_marker = "⭐ " if starred else ""
    header = f"{dot} {star_marker}`{loc}`  ·  {ttype}  ·  {status}"

    # Occupant / reservation summary
    if occupants:
        if len(occupants) == 1:
            summary = _occupant_chip_text(occupants[0], fish_index)
        else:
            summary = f"{len(occupants)} occupants"
    elif status == "Reserved":
        summary = _reservation_summary(tank)
    else:
        summary = "—"

    header_full = f"{header}  ·  {_purpose_icon(purpose)} {summary}"

    with st.expander(header_full, expanded=False):
        # ---- Expanded content ----
        col_img, col_info = st.columns([1, 2])

        with col_img:
            if tank.get("photo_id"):
                st.image(photo_url(tank["photo_id"]), use_container_width=True)
            else:
                st.caption("📷 *No photo*")

            if tank.get("qr_id"):
                with st.expander("QR Code", expanded=False):
                    st.image(photo_url(tank["qr_id"]), use_container_width=True)

        with col_info:
            st.markdown(f"### {star_marker}🏷️ `{loc}`")
            st.markdown(_status_badge_html(status), unsafe_allow_html=True)
            st.caption(f"System ID: `{tank.get('system_id')}`")
            st.write(f"🪣 **Type:** {ttype}")
            st.write(f"🎯 **Purpose:** {_purpose_label(purpose)}")
            st.write(f"🧪 **Capacity:** {tank.get('capacity_liters') or '—'} L")

            # Reservation detail
            if status == "Reserved":
                st.markdown("---")
                st.markdown("**🟡 Reservation**")
                st.write(f"Reason: **{tank.get('reserved_reason') or '—'}**")
                if tank.get("reserved_for"):
                    st.write(f"For: `{tank.get('reserved_for')}`")
                if tank.get("reserved_until"):
                    until = tank.get("reserved_until")
                    if _is_expiring_soon(tank):
                        st.warning(f"⏰ Expiring soon — {until}", icon="⚠️")
                    else:
                        st.write(f"Until: `{until}`")
                else:
                    st.caption("No expiry set")

            if tank.get("notes"):
                st.caption(f"📝 {tank['notes']}")

        # ---- Occupants ----
        st.markdown("---")
        st.markdown(f"**🐟 Occupants ({len(occupants)})**")
        _render_occupant_chips(occupants, fish_index)

        # ---- Action buttons ----
        st.markdown("---")
        st.markdown("**Actions**")

        c1, c2, c3, c4 = st.columns(4)

        with c1:
            if st.button("📥 Assign", key=f"act_assign_{tank_id}", use_container_width=True):
                _modal_assign_occupant(tank)

        with c2:
            if status == "Reserved":
                if st.button("❌ Cancel Reservation", key=f"act_cancel_{tank_id}", use_container_width=True):
                    if cancel_reservation(tank_id):
                        st.success("Reservation cancelled.")
                        st.rerun()
            else:
                if st.button("🟡 Reserve", key=f"act_reserve_{tank_id}", use_container_width=True):
                    _modal_reserve(tank)

        with c3:
            if st.button("🔄 Change Purpose", key=f"act_purpose_{tank_id}", use_container_width=True):
                _modal_change_purpose(tank)

        with c4:
            if st.button("⚙️ More", key=f"act_more_{tank_id}", use_container_width=True):
                st.session_state[f"_show_more_{tank_id}"] = not st.session_state.get(f"_show_more_{tank_id}", False)

        # More options drawer
        if st.session_state.get(f"_show_more_{tank_id}"):
            with st.container(border=True):
                st.markdown("**More options**")
                m1, m2, m3 = st.columns(3)

                with m1:
                    new_photo = st.file_uploader(
                        "Replace photo",
                        type=["jpg", "jpeg", "png"],
                        key=f"more_photo_{tank_id}",
                    )
                    if new_photo and st.button("Save photo", key=f"more_photo_save_{tank_id}", use_container_width=True):
                        ok = edit_tank(tank_id, {"photo_file": new_photo})
                        if ok:
                            st.success("Photo updated.")
                            st.rerun()

                with m2:
                    new_status = st.selectbox(
                        "Set status (manual)",
                        options=VALID_STATUSES,
                        index=VALID_STATUSES.index(status) if status in VALID_STATUSES else 0,
                        key=f"more_status_{tank_id}",
                    )
                    if st.button("Save status", key=f"more_status_save_{tank_id}", use_container_width=True):
                        if set_tank_status(tank_id, new_status):
                            st.success("Status updated.")
                            st.rerun()

                with m3:
                    if st.button("📤 Unassign all", key=f"more_unassign_{tank_id}", use_container_width=True):
                        if unassign_tank(tank_id):
                            st.success("All occupants removed.")
                            st.rerun()

                    st.divider()
                    st.caption("**Danger zone**")
                    if occupants:
                        if st.button("🗑️ Delete Tank (transfer first)", key=f"more_del_{tank_id}", use_container_width=True):
                            _modal_delete_with_transfer(tank, occupants, fish_index)
                    else:
                        confirm_del = st.checkbox("Confirm delete", key=f"more_del_confirm_{tank_id}")
                        if st.button(
                            "🗑️ Delete Tank",
                            key=f"more_del_empty_{tank_id}",
                            disabled=not confirm_del,
                            use_container_width=True,
                        ):
                            ok, msg = delete_tank_safely(tank_id)
                            if ok:
                                st.success("Tank deleted.")
                                st.rerun()
                            else:
                                st.error(msg)


# ============================================================
# INVENTORY LIST
# ============================================================

def _sort_key_factory(sort_mode: str):
    """Return a key function for sorting tanks."""
    if sort_mode == "Status → Number":
        return lambda t: (
            VALID_STATUSES.index(t.get("status")) if t.get("status") in VALID_STATUSES else 99,
            _numeric_tail(t.get("location_code") or ""),
        )
    if sort_mode == "⭐ Starred first":
        return lambda t: (
            not bool(t.get("_has_star")),
            t.get("tank_type") or "",
            _numeric_tail(t.get("location_code") or ""),
        )
    if sort_mode == "Number only":
        return lambda t: _numeric_tail(t.get("location_code") or "")
    if sort_mode == "Recently added":
        return lambda t: str(t.get("created_at") or ""),  # reverse below
    # Default: Type → Number
    return lambda t: (
        t.get("tank_type") or "",
        _numeric_tail(t.get("location_code") or ""),
    )


def _render_inventory():
    st.subheader("Container Inventory")

    all_tanks = list_all_tanks()
    if not all_tanks:
        st.info("No containers registered yet. Use the Register tab to add your first one.")
        return

    # ---- Build fish index for occupant lookups ----
    fish_index = {f["id"]: f for f in (get_fish_dropdown_items() and
                                        [{"id": x["id"], "system_id": x.get("system_id"),
                                          "gender": None, "variety": None,
                                          "is_starred": False} for x in get_fish_dropdown_items()]
                                        or [])}
    # The lightweight dropdown items don't include is_starred, so load full fish
    try:
        from database import get_all_fish
        fish_index = {f["id"]: f for f in get_all_fish()}
    except Exception:
        pass

    # ---- Attach occupants + starred flag to each tank ----
    for t in all_tanks:
        try:
            from database import get_tank_occupants
            occupants = get_tank_occupants(t["id"])
        except Exception:
            occupants = []
        t["_occupants"] = occupants
        t["_has_star"] = any(
            _is_starred_occupant(o["occupant_type"], o["occupant_id"], fish_index)
            for o in occupants
        )

    # ---- KPI row (clickable filters) ----
    stats = get_tank_stats()
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Total",     stats.get("total", 0))
    k2.metric("⚪ Empty",   stats.get("available", 0))
    k3.metric("🟡 Reserved", stats.get("reserved", 0))
    k4.metric("🟢 Occupied", stats.get("occupied", 0))
    k5.metric("🟠 Cleaning", stats.get("cleaning", 0))
    k6.metric("⚫ Retired",  stats.get("retired", 0))

    # ---- Expiring reservations banner ----
    expiring = get_expiring(days_ahead=3)
    if expiring:
        locs = ", ".join(t.get("location_code") or "?" for t in expiring[:5])
        more = f" (+{len(expiring) - 5} more)" if len(expiring) > 5 else ""
        st.warning(
            f"⏰ **{len(expiring)} reservation(s)** expiring within 3 days: {locs}{more}",
            icon="⚠️",
        )

    st.markdown("---")

    # ---- Filter bar ----
    f1, f2, f3, f4, f5 = st.columns([2, 1, 1, 1, 1])
    with f1:
        query = st.text_input(
            "🔍 Search",
            placeholder="Tape code, system ID, type, purpose, occupant, notes...",
            key="inv_search",
        ).strip().lower()
    with f2:
        purpose_filter = st.selectbox(
            "Purpose",
            options=["All"] + VALID_PURPOSES,
            format_func=lambda p: "All" if p == "All" else _purpose_label(p),
            key="inv_purpose",
        )
    with f3:
        type_options = sorted({t.get("tank_type") for t in all_tanks if t.get("tank_type")})
        type_filter = st.selectbox(
            "Type",
            options=["All"] + type_options,
            key="inv_type",
        )
    with f4:
        status_filter = st.selectbox(
            "Status",
            options=["All"] + VALID_STATUSES,
            key="inv_status",
        )
    with f5:
        sort_mode = st.selectbox(
            "Sort",
            options=["Type → Number", "Status → Number", "⭐ Starred first", "Number only", "Recently added"],
            key="inv_sort",
        )

    starred_only = st.checkbox("⭐ Show starred only", key="inv_star_only")

    # ---- Apply filters ----
    filtered = all_tanks

    if query:
        def _matches(t):
            hay = " ".join([
                str(t.get("location_code") or ""),
                str(t.get("system_id") or ""),
                str(t.get("tank_type") or ""),
                str(t.get("purpose") or ""),
                str(t.get("occupant_label") or ""),
                str(t.get("notes") or ""),
                str(t.get("reserved_reason") or ""),
                str(t.get("reserved_for") or ""),
            ]).lower()
            if query in hay:
                return True
            # Also search occupant fish system_ids
            for occ in t.get("_occupants") or []:
                if occ["occupant_type"] == "fish":
                    fish = fish_index.get(occ["occupant_id"])
                    if fish and query in (fish.get("system_id") or "").lower():
                        return True
            return False
        filtered = [t for t in filtered if _matches(t)]

    if purpose_filter != "All":
        filtered = [t for t in filtered if (t.get("purpose") or "") == purpose_filter]

    if type_filter != "All":
        filtered = [t for t in filtered if (t.get("tank_type") or "") == type_filter]

    if status_filter != "All":
        filtered = [t for t in filtered if (t.get("status") or "") == status_filter]

    if starred_only:
        filtered = [t for t in filtered if t.get("_has_star")]

    # ---- Sort ----
    reverse = (sort_mode == "Recently added")
    try:
        filtered.sort(key=_sort_key_factory(sort_mode), reverse=reverse)
    except Exception:
        pass

    st.caption(f"Showing **{len(filtered)}** of **{len(all_tanks)}** containers.")
    st.markdown("---")

    if not filtered:
        st.info("No containers match your filters.")
        return

    # ---- Render rows ----
    for t in filtered:
        _render_tank_row(t, fish_index)


# ============================================================
# PAGE
# ============================================================

def render_tank_page():
    _drain_reservation_warnings()

    st.title("🪣 Tank & Container Registry")

    tab1, tab2 = st.tabs(["➕ Register Container", "🗃️ Container Inventory"])

    with tab1:
        _render_registration_form()

    with tab2:
        _render_inventory()
