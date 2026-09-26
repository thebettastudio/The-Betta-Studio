# modules/tank_registry.py
# Betta Farm Management System
# Session 7 — Tank registry ported to Supabase.
#
# Session 26H.7 — Step 3 (this revision):
#   • VALID_STATUSES now re-exported from database.py (5-value canonical list,
#     "Reserved" added, "Active" removed).
#   • New occupant API:
#       add_occupant_to_tank(), add_fry_batch_to_tank(), remove_occupant(),
#       transfer_occupant()
#   • New reservation API:
#       reserve_tank(), cancel_reservation(), move_reservation()
#   • New safe-delete:
#       delete_tank_safely() — blocks occupied deletes unless transfers given
#   • New purpose change with tape regen:
#       change_purpose_and_regenerate_code()
#   • list_available_tanks() — Reserved is now excluded from availability.
#   • get_tank_stats() — includes 'reserved'.
#   • Backward-compat preserved:
#       assign_fish_to_tank(), unassign_tank(), set_tank_status(),
#       register_tank(), edit_tank(), delete_tank_and_media()
#     All existing callers (views/tank_view.py, views/fish_registry_view.py,
#     views/spawn_view.py, views/fry_batch_view.py, modules/spawn_manager.py,
#     modules/fry_batch_manager.py) keep working.

from __future__ import annotations

from typing import Optional

import streamlit as st

from database import (
    # reads
    get_all_tanks,
    get_tank_by_id,
    # create / update / delete
    create_tank,
    update_tank,
    delete_tank,
    delete_tank_safely,
    # occupants
    assign_occupant,
    clear_occupant,
    add_tank_occupant,
    remove_tank_occupant,
    transfer_occupant as db_transfer_occupant,
    get_tank_occupants,
    # reservations
    reserve_tank as db_reserve_tank,
    cancel_reservation as db_cancel_reservation,
    move_reservation as db_move_reservation,
    get_expiring_reservations,
    # tape code
    regenerate_tape_code as db_regenerate_tape_code,
    # other
    get_all_fish,
    get_fish_by_id,
    log_activity,
    VALID_STATUSES as DB_VALID_STATUSES,
)
from modules.id_generator import (
    generate_tank_system_id,
    generate_tape_code,
    get_tank_prefix_for_purpose,
    all_purposes,
)
from modules.photo_service import upload_photo, upload_qr, delete_drive_file


# ============================================================
# VALID VALUES
# ============================================================

VALID_TANK_TYPES = [
    "Grow-Out Planggana (Large)",
    "Spawning Planggana (Small)",
    "6-Liter Water Bottle",
    "Empi Glass/Jar",
    "Glass Aquarium",
    "Sorority Basin",
    "Quarantine Jar",
    "Custom",
]

# Re-exported for backward compat (views import VALID_STATUSES from here).
# Canonical list lives in database.py.
VALID_STATUSES = DB_VALID_STATUSES

VALID_PURPOSES = [
    "Jarring",
    "Conditioning",
    "Spawning",
    "Fry Nursery",
    "Grow-Out",
    "Sorority",
    "Quarantine",
    "Sales Display",
    "Storage",
    "Other",
]


# ============================================================
# READ
# ============================================================

def list_all_tanks() -> list[dict]:
    return get_all_tanks()


def find_tank(identifier: str) -> Optional[dict]:
    """Look up by uuid, system_id, or location_code."""
    if not identifier:
        return None
    ident = str(identifier).strip()
    for t in get_all_tanks():
        if t.get("id") == ident or \
           t.get("system_id") == ident or \
           t.get("location_code") == ident:
            return t
    return None


def list_available_tanks(
    purpose: Optional[str] = None,
    include_active: bool = False,
) -> list[dict]:
    """
    Tanks that are Empty / Idle. Reserved tanks are EXCLUDED (Q2 rule:
    Available = Empty / Idle only).

    include_active=True additionally includes Occupied tanks
    (kept for backward-compat; prefer explicit status filters in new code).
    """
    out = []
    allowed = {"Empty / Idle"}
    if include_active:
        allowed |= {"Occupied"}

    for t in get_all_tanks():
        status = (t.get("status") or "").strip()
        if status not in allowed:
            continue
        if purpose and (t.get("purpose") or "").strip() != purpose:
            continue
        out.append(t)
    return out


def list_reserved_tanks() -> list[dict]:
    """All tanks currently in the Reserved state."""
    return [t for t in get_all_tanks() if (t.get("status") or "").strip() == "Reserved"]


def list_tanks_by_purpose(purpose: str) -> list[dict]:
    return [t for t in get_all_tanks() if (t.get("purpose") or "") == purpose]


def get_tank_dropdown_items(purpose: Optional[str] = None) -> list[dict]:
    """
    Dropdown items for spawning / assignment UIs.
    Reserved tanks are excluded (they're spoken for).
    Each item: {'id': uuid, 'label': '📍 JAR-0007 (Empi Glass/Jar)'}
    """
    out = []
    for t in list_available_tanks(purpose=purpose):
        loc = t.get("location_code") or t.get("system_id")
        ttype = t.get("tank_type") or ""
        label = f"📍 {loc}" + (f" ({ttype})" if ttype else "")
        out.append({
            "id": t["id"],
            "system_id": t.get("system_id"),
            "location_code": loc,
            "label": label,
        })
    return out


def get_tank_stats() -> dict:
    """Dashboard-level counts. Available = Empty / Idle only."""
    tanks = get_all_tanks()

    def _c(label: str) -> int:
        return sum(1 for t in tanks if (t.get("status") or "").strip() == label)

    return {
        "total":     len(tanks),
        "available": _c("Empty / Idle"),
        "reserved":  _c("Reserved"),
        "occupied":  _c("Occupied"),
        "cleaning":  _c("Cleaning / Quarantine"),
        "retired":   _c("Retired"),
    }


# ============================================================
# CREATE
# ============================================================

def register_tank(
    *,
    tank_type: str,
    capacity_liters: float,
    purpose: str = "Other",
    photo_file=None,
    current_occupant_id: Optional[str] = None,
    notes: str = "",
) -> Optional[dict]:
    """
    Register a new tank.

    - system_id is auto-generated (T00001)
    - location_code (tape code) is auto-generated from PURPOSE
      e.g. 'Jarring' -> JAR-0001, 'Spawning' -> SPN-0003
    - status auto-detects from occupant
    - Photo upload goes to Drive via photo_service
    - QR code generated + uploaded to Drive
    """
    system_id = generate_tank_system_id()
    location_code = generate_tape_code(purpose)

    # Photo
    photo_id = None
    if photo_file is not None:
        photo_id = upload_photo(photo_file, entity_type="tank", entity_id=system_id)

    # QR
    qr_id = None
    try:
        qr_bytes = _make_qr_png(location_code)
        qr_id = upload_qr(qr_bytes, entity_type="tank", entity_id=system_id)
    except Exception as e:
        st.warning(f"QR generation failed: {e}")

    # Occupant + status
    occupant_id = current_occupant_id or None
    occupant_label = None
    status = "Empty / Idle"
    if occupant_id:
        fish = get_fish_by_id(occupant_id)
        if fish:
            occupant_label = _fish_label(fish)
            status = "Occupied"

    record = {
        "system_id": system_id,
        "tank_type": tank_type,
        "location_code": location_code,
        "capacity_liters": float(capacity_liters) if capacity_liters else None,
        "status": status,
        "purpose": purpose,
        "occupant_fish_id": occupant_id,
        "occupant_label": occupant_label,
        "photo_id": photo_id,
        "qr_id": qr_id,
        "notes": notes,
    }

    saved = create_tank(record)
    if saved:
        # If we set an occupant, also add the join row + mirror to fish
        if occupant_id:
            add_tank_occupant(saved["id"], "fish", occupant_id, role="primary")
            update_fish_location(occupant_id, location_code)

        log_activity(
            action_type="tank_registered",
            description=f"Registered {location_code} ({tank_type}, {purpose})",
            entity_type="tank",
            entity_id=saved["id"],
        )
    return saved


# ============================================================
# UPDATE
# ============================================================

def edit_tank(tank_id: str, updates: dict) -> bool:
    """
    Update tank fields. If photo_file in updates, replaces photo.
    NOTE: for a purpose change that should regenerate the tape code, use
    change_purpose_and_regenerate_code() instead.
    """
    photo_file = updates.pop("photo_file", None)
    if photo_file is not None:
        tank = get_tank_by_id(tank_id)
        old = tank.get("photo_id") if tank else None
        new_id = upload_photo(photo_file, entity_type="tank", entity_id=tank_id)
        if new_id:
            updates["photo_id"] = new_id
            if old:
                delete_drive_file(old)

    ok = update_tank(tank_id, updates)
    if ok:
        log_activity(
            action_type="tank_updated",
            description=f"Updated fields: {', '.join(updates.keys())}",
            entity_type="tank",
            entity_id=tank_id,
        )
    return ok


def change_purpose_and_regenerate_code(tank_id: str, new_purpose: str) -> Optional[tuple[str, str]]:
    """
    Change a tank's purpose and regenerate its tape code (Q4, Option C).

    Returns (old_code, new_code) or None on failure.
    The caller (UI) is responsible for showing the warning modal + tape-rewrite
    reminder. This function only performs the DB writes + activity log.
    """
    tank = get_tank_by_id(tank_id)
    if not tank:
        return None

    old_purpose = tank.get("purpose") or "Other"
    if new_purpose == old_purpose:
        return None

    result = db_regenerate_tape_code(tank_id, new_purpose)
    if not result:
        return None

    old_code, new_code = result

    log_activity(
        action_type="tank_purpose_changed",
        description=(
            f"{old_code} → {new_code}: purpose '{old_purpose}' → '{new_purpose}'. "
            f"Re-write painter's tape."
        ),
        entity_type="tank",
        entity_id=tank_id,
    )
    return (old_code, new_code)


def set_tank_status(tank_id: str, new_status: str) -> bool:
    """
    Change status. Does NOT auto-sync occupant — use assign/clear for that.
    """
    return update_tank(tank_id, {"status": new_status})


# ============================================================
# OCCUPANT — NEW API
# ============================================================

def add_occupant_to_tank(
    tank_id: str,
    occupant_type: str,
    occupant_id: str,
    role: str = "primary",
    spawn_id: Optional[str] = None,
) -> bool:
    """
    Add a fish or fry_batch occupant to a tank.
    Auto-cancels any reservation (warning surfaced by database layer via
    st.session_state['_reservation_warnings']).
    """
    row = add_tank_occupant(
        tank_id=tank_id,
        occupant_type=occupant_type,
        occupant_id=occupant_id,
        role=role,
        spawn_id=spawn_id,
    )
    if not row:
        return False

    if occupant_type == "fish":
        tank = get_tank_by_id(tank_id)
        loc = tank.get("location_code") if tank else None
        if loc:
            update_fish_location(occupant_id, loc)

    log_activity(
        action_type="tank_assigned",
        description=f"Added {occupant_type} {occupant_id[:8]} to tank {tank_id[:8]}",
        entity_type="tank",
        entity_id=tank_id,
    )
    return True


def add_fry_batch_to_tank(
    tank_id: str,
    batch_id: str,
    role: str = "batch",
    spawn_id: Optional[str] = None,
) -> bool:
    """Convenience wrapper for fry batches."""
    return add_occupant_to_tank(
        tank_id=tank_id,
        occupant_type="fry_batch",
        occupant_id=batch_id,
        role=role,
        spawn_id=spawn_id,
    )


def remove_occupant(tank_id: str, occupant_type: str, occupant_id: str) -> bool:
    """Remove a specific occupant from a tank."""
    if occupant_type == "fish":
        tank = get_tank_by_id(tank_id)
        if tank:
            update_fish_location(occupant_id, None)

    ok = remove_tank_occupant(tank_id, occupant_type, occupant_id)
    if ok:
        log_activity(
            action_type="tank_unassigned",
            description=f"Removed {occupant_type} {occupant_id[:8]} from tank {tank_id[:8]}",
            entity_type="tank",
            entity_id=tank_id,
        )
    return ok


def transfer_occupant_api(
    occupant_type: str,
    occupant_id: str,
    from_tank_id: Optional[str],
    to_tank_id: str,
    role: str = "primary",
) -> bool:
    """
    Move an occupant to a different tank. Thin wrapper over
    database.transfer_occupant() that adds the activity log entry.
    """
    ok = db_transfer_occupant(
        fish_id=occupant_id,
        from_tank_id=from_tank_id,
        to_tank_id=to_tank_id,
        role=role,
        occupant_type=occupant_type,
    )
    if ok:
        log_activity(
            action_type="tank_assigned",
            description=(
                f"Transferred {occupant_type} {occupant_id[:8]} "
                f"from {from_tank_id or 'none'} to {to_tank_id[:8]}"
            ),
            entity_type="tank",
            entity_id=to_tank_id,
        )
    return ok


# ---------- Backward-compat occupant API ----------
# Views + modules still call these names. Keep them forever or until
# Step 5/7 explicitly rewrites callers.

def assign_fish_to_tank(tank_id: str, fish_id: str) -> bool:
    """
    Assign a fish to a tank. Backward-compat wrapper over
    add_occupant_to_tank(occupant_type='fish').
    """
    fish = get_fish_by_id(fish_id)
    if not fish:
        st.error(f"Fish {fish_id} not found.")
        return False

    ok = add_occupant_to_tank(tank_id, "fish", fish_id, role="primary")
    if ok:
        tank = get_tank_by_id(tank_id)
        loc = tank.get("location_code") if tank else None
        log_activity(
            action_type="tank_assigned",
            description=f"Assigned {fish.get('system_id')} to {loc}",
            entity_type="tank",
            entity_id=tank_id,
        )
    return ok


def unassign_tank(tank_id: str) -> bool:
    """
    Remove ALL occupants from a tank. Backward-compat wrapper over
    database.clear_occupant().
    """
    tank = get_tank_by_id(tank_id)
    if not tank:
        return False

    ok = clear_occupant(tank_id)
    if ok:
        log_activity(
            action_type="tank_unassigned",
            description=f"Cleared occupant(s) from {tank.get('location_code')}",
            entity_type="tank",
            entity_id=tank_id,
        )
    return ok


# ============================================================
# RESERVATION API (delegating)
# ============================================================

def reserve_tank(
    tank_id: str,
    reason: str,
    reserved_for: Optional[str] = None,
    reserved_until: Optional[str] = None,
    reserved_ref_id: Optional[str] = None,
) -> bool:
    """Set a reservation. Reserved requires a reason (Q2)."""
    if not reason or not reason.strip():
        st.error("A reservation reason is required.")
        return False

    ok = db_reserve_tank(
        tank_id=tank_id,
        reason=reason,
        reserved_for=reserved_for,
        reserved_until=reserved_until,
        reserved_ref_id=reserved_ref_id,
    )
    if ok:
        tank = get_tank_by_id(tank_id)
        log_activity(
            action_type="tank_reserved",
            description=(
                f"Reserved {tank.get('location_code') if tank else tank_id[:8]}"
                + (f" for {reserved_for}" if reserved_for else "")
                + (f" until {reserved_until}" if reserved_until else "")
            ),
            entity_type="tank",
            entity_id=tank_id,
        )
    return ok


def cancel_reservation(tank_id: str) -> bool:
    """Clear a reservation and return to Empty / Idle."""
    tank = get_tank_by_id(tank_id)
    ok = db_cancel_reservation(tank_id)
    if ok and tank:
        log_activity(
            action_type="tank_reservation_cancelled",
            description=f"Cancelled reservation on {tank.get('location_code')}",
            entity_type="tank",
            entity_id=tank_id,
        )
    return ok


def move_reservation(from_tank_id: str, to_tank_id: str) -> bool:
    """Move a reservation to another tank."""
    ok = db_move_reservation(from_tank_id, to_tank_id)
    if ok:
        log_activity(
            action_type="tank_reservation_moved",
            description=f"Moved reservation from {from_tank_id[:8]} to {to_tank_id[:8]}",
            entity_type="tank",
            entity_id=to_tank_id,
        )
    return ok


def get_expiring(days_ahead: int = 3) -> list[dict]:
    """Convenience re-export for dashboards."""
    return get_expiring_reservations(days_ahead=days_ahead)


# ============================================================
# SAFE DELETE (Q3 Option D)
# ============================================================

def delete_tank_safely(
    tank_id: str,
    transfers: Optional[dict] = None,
) -> tuple[bool, str]:
    """
    Delete a tank only if:
      - it has no occupants, OR
      - `transfers` maps every occupant to a destination tank.

    transfers: { (occupant_type, occupant_id): destination_tank_id }
    """
    tank = get_tank_by_id(tank_id)
    if not tank:
        return False, "Tank not found."

    ok, msg = delete_tank_safely_db(tank_id, transfers=transfers)
    if ok:
        # Delete Drive media (best effort)
        for f_id in (tank.get("photo_id"), tank.get("qr_id")):
            if f_id:
                delete_drive_file(f_id)

        log_activity(
            action_type="tank_deleted",
            description=f"Deleted {tank.get('location_code')}",
            entity_type="tank",
        )
    return ok, msg


# We imported delete_tank_safely from database as the same name; give it
# a local alias so we can call it without shadowing this function name.
from database import delete_tank_safely as delete_tank_safely_db  # noqa: E402


# ---------- Backward-compat delete ----------

def delete_tank_and_media(tank_id: str) -> bool:
    """
    Legacy delete path used by views/tank_view.py.
    For an occupied tank this now BLOCKS (Q3 Option D) — the view must
    be updated (Step 4) to route through delete_tank_safely() with a
    transfer dialog. Until then this wrapper refuses occupied deletes
    rather than orphaning fish.
    """
    occupants = get_tank_occupants(tank_id)
    if occupants:
        st.error(
            f"Cannot delete — tank has {len(occupants)} occupant(s). "
            "Transfer occupants first (use the transfer dialog)."
        )
        return False

    ok, _msg = delete_tank_safely(tank_id, transfers=None)
    return ok


# ============================================================
# INTERNAL HELPERS
# ============================================================

def update_fish_location(fish_id: str, location: Optional[str]) -> bool:
    """Mirror the tank tape code onto the fish row."""
    from database import update_fish
    return update_fish(fish_id, {"location": location})


def _fish_label(fish: dict) -> str:
    parts = [fish.get("system_id") or "?"]
    if fish.get("gender"):  parts.append(fish["gender"])
    if fish.get("variety"): parts.append(fish["variety"])
    return " | ".join(str(p) for p in parts)


def _make_qr_png(data: str):
    """Generate a QR code PNG as bytes. Matches old box_size/border for printed labels."""
    import io
    import qrcode
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(str(data))
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()
