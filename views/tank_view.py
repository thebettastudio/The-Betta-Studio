# views/tank_view.py
# Betta Farm Management System
# Session 10 — Ported to Supabase via tank_registry + fish_manager.
#
# Session 26H.7 — Step 4 v2 (this revision): compact single-line rows.
#   • Each tank = ONE horizontal line:  [stripe] CODE · Type · Purpose · Occupant  [STATUS] [▸]
#   • Click anywhere on the row to expand (toggle via chevron on the right)
#   • Expanded card: 2 columns (photo | details + occupants + actions stacked)
#   • KPI row: native clickable buttons
#   • Filter bar: search + sort inline; advanced filters in expander
#   • ⭐ Starred indicator inherited from fish.is_starred
#   • Modals: Assign (Fish/Fry Batch tabs), Reserve (quick-picks + big calendar),
#     Change Purpose, Transfer-on-delete
#   • Reservation warning toasts + expiring banner
#   • Custom tank types remembered (merged from DB values)
#   • All mutations go through modules/tank_registry.py

from __future__ import annotations

import datetime as _dt
from typing import Optional

import streamlit as st

from modules.tank_registry import (
    list_all_tanks,
    list_available_tanks,
    list_reserved_tanks,
    get_tank_stats,
    get_tank_dropdown_items,
    register_tank,
    edit_tank,
    set_tank_status,
    change_purpose_and_regenerate_code,
    add_occupant_to_tank,
    add_fry_batch_to_tank,
    remove_occupant,
    transfer_occupant,
    unassign_tank,
    reserve_tank,
    cancel_reservation,
    move_reservation,
    get_expiring,
    delete_tank_safely,
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
    "Jarring":       "🫙 Jarring",
    "Conditioning":  "🥩 Conditioning",
    "Spawning":      "🥚 Spawning",
    "Fry Nursery":   "🌿 Fry Nursery",
    "Grow-Out":      "🪴 Grow-Out",
    "Sorority":      "👑 Sorority",
    "Quarantine":    "🏥 Quarantine",
    "Sales Display": "🛒 Sales Display",
    "Storage":       "📦 Storage",
    "Other":         "❔ Other",
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
    "Grow-Out Planggana (Large)":     "Grow-Out Planggana",
    "Spawning Planggana (Small)":     "Spawning Planggana",
    "6-Liter Water Bottle":           "6-Liter Bottle",
    "Empi Glass/Jar":                 "Empi Glass",
    "Glass Aquarium":                 "Glass Aquarium",
    "Sorority Basin":                 "Sorority Basin",
    "Quarantine Jar":                 "Quarantine Jar",
    "Custom":                         "➕ Other / Custom...",
}

CUSTOM_TANK_SENTINEL = "Custom"

STATUS_STYLE = {
    "Empty / Idle":          ("#9CA3AF", "⚪", "#F3F4F6", "#374151", "EMPTY"),
    "Reserved":              ("#F59E0B", "🟡", "#FEF3C7", "#92400E", "RESERVED"),
    "Occupied":              ("#10B981", "🟢", "#D1FAE5", "#065F46", "OCCUPIED"),
    "Cleaning / Quarantine": ("#F97316", "🟠", "#FED7AA", "#9A3412", "CLEANING"),
    "Retired":               ("#4B5563", "⚫", "#E5E7EB", "#6B7280", "RETIRED"),
}


def _purpose_label(p: str) -> str:
    return PURPOSE_LABELS.get(p, p)


def _purpose_icon(p: str) -> str:
    return PURPOSE_ICONS.get(p, "❔")


def _tank_type_label(t: str) -> str:
    return TANK_TYPE_LABELS.get(t, t)


def _status_parts(status: str):
    return STATUS_STYLE.get(status or "Empty / Idle",
                            ("#9CA3AF", "⚪", "#F3F4F6", "#374151", "EMPTY"))


def _status_badge_html(status: str) -> str:
    _stripe, _dot, bg, fg, short = _status_parts(status)
    return (
        f'<span style="display:inline-block;background:{bg};color:{fg};'
        f'font-size:10px;font-weight:700;padding:3px 9px;border-radius:10px;'
        f'letter-spacing:0.5px;">{short}</span>'
    )


def _numeric_tail(code: str) -> int:
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
    if occupant_type != "fish":
        return False
    fish = fish_index.get(occupant_id)
    return bool(fish and fish.get("is_starred"))


# ============================================================
# RESERVATION WARNING TOASTS
# ============================================================

def _drain_reservation_warnings():
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
# CUSTOM TANK TYPE MERGING
# ============================================================

def _get_tank_type_options() -> list[str]:
    try:
        existing = {t.get("tank_type") for t in list_all_tanks() if t.get("tank_type")}
    except Exception:
        existing = set()

    merged = list(VALID_TANK_TYPES)
    for t in sorted(existing):
        if t not in merged:
            merged.append(t)
    return merged


# ============================================================
# FISH / FRY-BATCH DROPDOWN HELPERS
# ============================================================

def _fish_options_for_assign(current_tank_id: str) -> list[dict]:
    return [{"id": f["id"], "label": f.get("label") or f.get("system_id") or "?"}
            for f in get_fish_dropdown_items()]


def _fry_batch_options(current_tank_id: str) -> list[dict]:
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
    tank_type_options = _get_tank_type_options()

    with st.form("tank_register_form", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            selected_type = st.selectbox(
                "Container / Tank Type",
                options=tank_type_options,
                format_func=_tank_type_label,
                help="Pick a type or choose 'Other / Custom' to add a new one.",
            )

            custom_type = ""
            if selected_type == CUSTOM_TANK_SENTINEL:
                custom_type = st.text_input(
                    "✏️ Custom Container Name",
                    placeholder="e.g. 1.5L Jarring Bottle",
                    help="Saved for next time — appears in the dropdown.",
                )

            capacity = st.number_input(
                "Capacity (Liters)",
                min_value=0.1, max_value=500.0, value=6.0, step=0.5,
            )

            purpose = st.selectbox(
                "Purpose / Role",
                options=VALID_PURPOSES,
                format_func=_purpose_label,
            )

        with col2:
            fish_opts = [{"id": None, "label": "— None (Empty) —"}] + get_fish_dropdown_items()
            selected_fish_idx = st.selectbox(
                "Current Occupant (Optional)",
                options=range(len(fish_opts)),
                format_func=lambda i: fish_opts[i].get("label") or "?",
                help="Leave as None for empty containers.",
            )
            selected_fish_id = fish_opts[selected_fish_idx]["id"]

            photo_file = st.file_uploader(
                "📷 Container Photo (Optional)",
                type=["jpg", "jpeg", "png"],
            )
            notes = st.text_area(
                "Notes / Setup",
                placeholder="e.g. Almond leaf tea water, sponge filter",
            )

        submit = st.form_submit_button("🏷️ Register Container", type="primary", use_container_width=True)

    if not submit:
        return

    if selected_type == CUSTOM_TANK_SENTINEL and not custom_type.strip():
        st.error("Please enter a custom container name.")
        return

    final_type = custom_type.strip() if selected_type == CUSTOM_TANK_SENTINEL else selected_type

    with st.spinner("Generating tape tag & registering..."):
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
    <div style="background-color: #FEF3C7; border: 2px dashed #D97706;
                padding: 16px; border-radius: 12px; text-align: center; margin: 12px 0;">
        <span style="font-size: 13px; color: #92400E; font-weight: bold;
                     text-transform: uppercase; letter-spacing: 0.5px;">
            ✍️ WRITE THIS ON PAINTER'S TAPE
        </span>
        <h1 style="font-size: 40px; color: #B45309; margin: 8px 0;
                   font-family: monospace; letter-spacing: 3px;">
            {res['location_code']}
        </h1>
        <span style="font-size: 11px; color: #B45309;">System ID: {res['system_id']}</span>
    </div>
    """, unsafe_allow_html=True)

    if res.get("photo_id"):
        st.image(photo_url(res["photo_id"]), caption="Container Photo", width=220)


# ============================================================
# MODAL: ASSIGN OCCUPANT
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
            if st.button("Assign Fish", type="primary", use_container_width=True,
                         key=f"assign_fish_btn_{tank_id}"):
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
            if st.button("Assign Fry Batch", type="primary", use_container_width=True,
                         key=f"assign_batch_btn_{tank_id}"):
                bid = batch_opts[idx]["id"]
                if add_fry_batch_to_tank(tank_id, bid):
                    st.success("Fry batch assigned.")
                    st.rerun()


# ============================================================
# MODAL: RESERVE TANK
# ============================================================

def _suggest_reserved_for() -> list[str]:
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

    reserved_for = st.text_input(
        "Reserved for (optional)",
        placeholder="e.g. SPN-AVT-F1-01, Line AVT",
        key=f"res_for_{tank_id}",
    )
    suggested_for = _suggest_reserved_for()
    if suggested_for:
        with st.expander("💡 Suggestions", expanded=False):
            st.caption(" · ".join(suggested_for))

    st.markdown("**Expiry date** — quick pick or custom:")

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
    if st.button("Confirm Reservation", type="primary", use_container_width=True,
                 key=f"res_confirm_{tank_id}"):
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
# MODAL: CHANGE PURPOSE
# ============================================================

@st.dialog("🔄 Change Purpose & Regenerate Tape Code", width="large")
def _modal_change_purpose(tank: dict):
    tank_id = tank["id"]
    old_purpose = tank.get("purpose") or "Other"
    old_code = tank.get("location_code") or "?"

    st.warning(
        "Changing purpose regenerates the tape code. You'll need to "
        "re-write the painter's tape on the physical container.",
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

    try:
        from modules.id_generator import generate_tape_code
        preview = generate_tape_code(new_purpose)
    except Exception:
        preview = "(preview unavailable)"

    if new_purpose != old_purpose:
        st.info(f"**Old → New tape code:** `{old_code}` → `{preview}`")
    else:
        st.caption("No change — pick a different purpose.")

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
# MODAL: TRANSFER-ON-DELETE
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
# OCCUPANT CHIP TEXT
# ============================================================

def _occupant_chip_text(occ: dict, fish_index: dict) -> str:
    otype = occ.get("occupant_type")
    oid = occ.get("occupant_id")

    if otype == "fish":
        fish = fish_index.get(oid)
        if not fish:
            return f"🐟 (unknown {str(oid)[:8]})"
        star = "⭐ " if fish.get("is_starred") else ""
        sid = fish.get("system_id") or "?"
        gender = fish.get("gender") or "?"
        variety = fish.get("variety") or "—"
        return f"{star}🐟 {sid} · {gender} · {variety}"
    elif otype == "fry_batch":
        try:
            from database import get_fry_batch_by_id
            batch = get_fry_batch_by_id(oid)
            tag = batch.get("batch_tag") if batch else str(oid)[:8]
        except Exception:
            tag = str(oid)[:8]
        return f"🐣 {tag}"
    return f"{otype} {str(oid)[:8]}"


def _occupant_short(occ: dict, fish_index: dict) -> str:
    """Very short occupant label for the collapsed row."""
    otype = occ.get("occupant_type")
    oid = occ.get("occupant_id")

    if otype == "fish":
        fish = fish_index.get(oid)
        if not fish:
            return f"🐟 {str(oid)[:8]}"
        star = "⭐" if fish.get("is_starred") else ""
        return f"{star}🐟 {fish.get('system_id') or '?'}"
    elif otype == "fry_batch":
        try:
            from database import get_fry_batch_by_id
            batch = get_fry_batch_by_id(oid)
            tag = batch.get("batch_tag") if batch else str(oid)[:8]
        except Exception:
            tag = str(oid)[:8]
        return f"🐣 {tag}"
    return str(oid)[:8]


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


# ============================================================
# COMPACT ROW (single-line) + EXPANDED CARD
# ============================================================

def _render_tank_row(tank: dict, fish_index: dict):
    tank_id = tank["id"]
    loc = tank.get("location_code") or "?"
    ttype = _tank_type_label(tank.get("tank_type") or "")
    status = tank.get("status") or "Empty / Idle"
    purpose = tank.get("purpose") or "Other"

    stripe_color, _dot, _bg, _fg, _short = _status_parts(status)

    occupants = tank.get("_occupants") or []
    starred = any(_is_starred_occupant(o["occupant_type"], o["occupant_id"], fish_index)
                  for o in occupants)

    # Occupant short summary for collapsed row
    if occupants:
        if len(occupants) == 1:
            occ_short = _occupant_short(occupants[0], fish_index)
        else:
            occ_short = f"{len(occupants)} occupants"
    elif status == "Reserved":
        occ_short = "reserved"
    else:
        occ_short = ""

    star_prefix = "⭐ " if starred else ""
    badge_html = _status_badge_html(status)
    purpose_str = _purpose_label(purpose)

    # ---- Single-line collapsed header ----
    hc = st.columns([3, 5, 3, 2, 1])

    with hc[0]:
        st.markdown(
            f'<div style="border-left:5px solid {stripe_color};'
            f'padding:4px 0 4px 10px;font-family:monospace;font-weight:700;'
            f'font-size:14px;line-height:1.4;">'
            f'{star_prefix}{loc}</div>',
            unsafe_allow_html=True,
        )
    with hc[1]:
        st.markdown(
            f'<div style="padding:4px 0;color:#4B5563;font-size:13px;'
            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'
            f'line-height:1.4;">{ttype}</div>',
            unsafe_allow_html=True,
        )
    with hc[2]:
        st.markdown(
            f'<div style="padding:4px 0;color:#4B5563;font-size:13px;'
            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'
            f'line-height:1.4;">{purpose_str}</div>',
            unsafe_allow_html=True,
        )
    with hc[3]:
        st.markdown(
            f'<div style="padding:4px 0;color:#6B7280;font-size:12px;'
            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'
            f'line-height:1.4;">{occ_short}</div>',
            unsafe_allow_html=True,
        )
    with hc[4]:
        st.markdown(
            f'<div style="padding:4px 0;text-align:right;line-height:1.4;">'
            f'{badge_html}</div>',
            unsafe_allow_html=True,
        )

    # ---- Toggle button (full-width, small) ----
    toggle_key = f"_expand_{tank_id}"
    is_open = st.session_state.get(toggle_key, False)

    label = "▴  collapse" if is_open else "▾  details"
    if st.button(
        label,
        key=f"tog_{tank_id}",
        use_container_width=True,
        type="secondary",
    ):
        st.session_state[toggle_key] = not is_open
        st.rerun()

    if not is_open:
        st.markdown(
            '<hr style="margin:4px 0 8px 0;border:none;border-top:1px solid #F3F4F6;">',
            unsafe_allow_html=True,
        )
        return

    # ---- Expanded card ----
    with st.container(border=True):
        col_photo, col_main = st.columns([2, 5])

        with col_photo:
            if tank.get("photo_id"):
                st.image(photo_url(tank["photo_id"]), use_container_width=True)
            else:
                st.markdown(
                    '<div style="width:100%;aspect-ratio:4/3;background:#F3F4F6;'
                    'border-radius:10px;display:flex;align-items:center;'
                    'justify-content:center;color:#9CA3AF;font-size:13px;">'
                    'No Photo</div>',
                    unsafe_allow_html=True,
                )
            if tank.get("qr_id"):
                with st.expander("QR Code", expanded=False):
                    st.image(photo_url(tank["qr_id"]), use_container_width=True)

        with col_main:
            # ---- Details ----
            st.markdown("##### 📋 Details")
            d1, d2 = st.columns(2)
            with d1:
                st.caption(f"System ID: `{tank.get('system_id')}`")
                st.markdown(f"**Type:** {ttype}")
            with d2:
                st.markdown(f"**Purpose:** {purpose_str}")
                st.markdown(f"**Capacity:** {tank.get('capacity_liters') or '—'} L")

            if status == "Reserved":
                st.markdown("---")
                st.markdown("**🟡 Reservation**")
                r1, r2 = st.columns(2)
                with r1:
                    st.markdown(f"**Reason:** {tank.get('reserved_reason') or '—'}")
                    if tank.get("reserved_for"):
                        st.markdown(f"**For:** `{tank.get('reserved_for')}`")
                with r2:
                    if tank.get("reserved_until"):
                        until = tank.get("reserved_until")
                        if _is_expiring_soon(tank):
                            st.warning(f"⏰ Expires soon — {until}", icon="⚠️")
                        else:
                            st.markdown(f"**Until:** `{until}`")
                    else:
                        st.caption("No expiry set")

            if tank.get("notes"):
                st.markdown("---")
                st.markdown(f"**📝 Notes:** {tank['notes']}")

            # ---- Occupants ----
            st.markdown("---")
            st.markdown(f"##### 🐟 Occupants ({len(occupants)})")
            if not occupants:
                st.caption("_None_")
            else:
                for occ in occupants:
                    text = _occupant_chip_text(occ, fish_index)
                    row_c1, row_c2 = st.columns([6, 1])
                    with row_c1:
                        st.markdown(text)
                    with row_c2:
                        if st.button(
                            "✕",
                            key=f"rm_occ_{occ['tank_id']}_{occ['occupant_type']}_{occ['occupant_id'][:8]}",
                            help="Remove this occupant",
                        ):
                            if remove_occupant(occ["tank_id"], occ["occupant_type"], occ["occupant_id"]):
                                st.success("Removed.")
                                st.rerun()

            # ---- Actions ----
            st.markdown("---")
            st.markdown("##### ⚡ Actions")

            a1, a2, a3, a4 = st.columns(4)
            with a1:
                if st.button("📥 Assign", key=f"act_assign_{tank_id}", use_container_width=True):
                    _modal_assign_occupant(tank)
            with a2:
                if status == "Reserved":
                    if st.button("❌ Cancel", key=f"act_cancel_{tank_id}", use_container_width=True):
                        if cancel_reservation(tank_id):
                            st.success("Reservation cancelled.")
                            st.rerun()
                else:
                    if st.button("🟡 Reserve", key=f"act_reserve_{tank_id}", use_container_width=True):
                        _modal_reserve(tank)
            with a3:
                if st.button("🔄 Purpose", key=f"act_purpose_{tank_id}", use_container_width=True):
                    _modal_change_purpose(tank)
            with a4:
                if st.button("⚙️ More", key=f"act_more_{tank_id}", use_container_width=True):
                    st.session_state[f"_show_more_{tank_id}"] = not st.session_state.get(f"_show_more_{tank_id}", False)
                    st.rerun()

            if st.session_state.get(f"_show_more_{tank_id}"):
                with st.container(border=True):
                    st.markdown("**More options**")
                    mo1, mo2 = st.columns(2)

                    with mo1:
                        new_photo = st.file_uploader(
                            "Replace photo",
                            type=["jpg", "jpeg", "png"],
                            key=f"more_photo_{tank_id}",
                        )
                        if new_photo and st.button("Save photo", key=f"more_photo_save_{tank_id}", use_container_width=True):
                            if edit_tank(tank_id, {"photo_file": new_photo}):
                                st.success("Photo updated.")
                                st.rerun()

                        new_status = st.selectbox(
                            "Set status",
                            options=VALID_STATUSES,
                            index=VALID_STATUSES.index(status) if status in VALID_STATUSES else 0,
                            key=f"more_status_{tank_id}",
                        )
                        if st.button("Save status", key=f"more_status_save_{tank_id}", use_container_width=True):
                            if set_tank_status(tank_id, new_status):
                                st.success("Status updated.")
                                st.rerun()

                    with mo2:
                        if st.button("📤 Unassign all", key=f"more_unassign_{tank_id}", use_container_width=True):
                            if unassign_tank(tank_id):
                                st.success("All occupants removed.")
                                st.rerun()

                        st.divider()
                        st.caption("**Danger zone**")
                        if occupants:
                            if st.button("🗑️ Delete (transfer first)", key=f"more_del_{tank_id}", use_container_width=True):
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

    st.markdown(
        '<hr style="margin:6px 0 10px 0;border:none;border-top:1px solid #E5E7EB;">',
        unsafe_allow_html=True,
    )


# ============================================================
# SORT FACTORY
# ============================================================

def _sort_key_factory(sort_mode: str):
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
        return lambda t: str(t.get("created_at") or "")
    return lambda t: (
        t.get("tank_type") or "",
        _numeric_tail(t.get("location_code") or ""),
    )


# ============================================================
# INVENTORY
# ============================================================

def _render_inventory():
    all_tanks = list_all_tanks()
    if not all_tanks:
        st.info("No containers registered yet. Use the Register tab to add your first one.")
        return

    fish_index = {}
    try:
        from database import get_all_fish
        fish_index = {f["id"]: f for f in get_all_fish()}
    except Exception:
        pass

    from database import get_tank_occupants
    for t in all_tanks:
        try:
            occupants = get_tank_occupants(t["id"])
        except Exception:
            occupants = []
        t["_occupants"] = occupants
        t["_has_star"] = any(
            _is_starred_occupant(o["occupant_type"], o["occupant_id"], fish_index)
            for o in occupants
        )

    counts = {s: 0 for s in VALID_STATUSES}
    for t in all_tanks:
        s = t.get("status") or "Empty / Idle"
        if s in counts:
            counts[s] += 1
    total = len(all_tanks)

    # ---- KPI row: native clickable buttons ----
    selected_kpi = st.session_state.get("_inv_kpi", "All")

    kpi_cols = st.columns(6)
    chips = [
        ("All", f"📦 All  ·  {total}"),
        ("Empty / Idle", f"⚪ Empty  ·  {counts['Empty / Idle']}"),
        ("Reserved", f"🟡 Reserved  ·  {counts['Reserved']}"),
        ("Occupied", f"🟢 Occupied  ·  {counts['Occupied']}"),
        ("Cleaning / Quarantine", f"🟠 Cleaning  ·  {counts['Cleaning / Quarantine']}"),
        ("Retired", f"⚫ Retired  ·  {counts['Retired']}"),
    ]
    for col, (key, label) in zip(kpi_cols, chips):
        with col:
            is_active = (selected_kpi == key)
            btn_type = "primary" if is_active else "secondary"
            if st.button(
                label,
                key=f"kpi_{key}",
                use_container_width=True,
                type=btn_type,
            ):
                st.session_state["_inv_kpi"] = key
                st.rerun()

    expiring = get_expiring(days_ahead=3)
    if expiring:
        locs = ", ".join(t.get("location_code") or "?" for t in expiring[:5])
        more = f" (+{len(expiring) - 5} more)" if len(expiring) > 5 else ""
        st.warning(
            f"⏰ **{len(expiring)} reservation(s)** expiring within 3 days: {locs}{more}",
            icon="⚠️",
        )

    f1, f2 = st.columns([4, 2])
    with f1:
        query = st.text_input(
            "🔍 Search",
            placeholder="Tape code, system ID, type, purpose, occupant, notes...",
            key="inv_search",
            label_visibility="collapsed",
        ).strip().lower()
    with f2:
        sort_mode = st.selectbox(
            "Sort",
            options=["Type → Number", "Status → Number", "⭐ Starred first",
                     "Number only", "Recently added"],
            key="inv_sort",
            label_visibility="collapsed",
        )

    with st.expander("🎛️ Advanced filters", expanded=False):
        af1, af2, af3 = st.columns(3)
        with af1:
            purpose_filter = st.selectbox(
                "Purpose",
                options=["All"] + VALID_PURPOSES,
                format_func=lambda p: "All" if p == "All" else _purpose_label(p),
                key="inv_purpose",
            )
        with af2:
            type_options = sorted({t.get("tank_type") for t in all_tanks if t.get("tank_type")})
            type_filter = st.selectbox(
                "Type",
                options=["All"] + type_options,
                key="inv_type",
            )
        with af3:
            starred_only = st.checkbox("⭐ Show starred only", key="inv_star_only")

    filtered = all_tanks

    if selected_kpi != "All":
        filtered = [t for t in filtered if (t.get("status") or "Empty / Idle") == selected_kpi]

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

    if starred_only:
        filtered = [t for t in filtered if t.get("_has_star")]

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
