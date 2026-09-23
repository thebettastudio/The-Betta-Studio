# modules/tank_registry.py
# Betta Farm Management System
# Session 7 — Tank registry ported to Supabase.

from __future__ import annotations

from typing import Optional

import streamlit as st

from database import (
    get_all_tanks,
    get_tank_by_id,
    create_tank,
    update_tank,
    delete_tank,
    assign_occupant,
    clear_occupant,
    get_all_fish,
    get_fish_by_id,
    log_activity,
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

VALID_STATUSES = [
    "Empty / Idle",
    "Active",
    "Occupied",
    "Cleaning / Quarantine",
    "Retired",
]

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
    Tanks that are empty/idle (or active if include_active=True),
    optionally filtered by purpose.
    """
    out = []
    valid_statuses = {"empty / idle", "empty", "idle", "available", "ready"}
    if include_active:
        valid_statuses |= {"active", "occupied"}

    for t in get_all_tanks():
        status = (t.get("status") or "").lower().strip()
        if status not in valid_statuses:
            continue
        if purpose and (t.get("purpose") or "").strip() != purpose:
            continue
        out.append(t)
    return out


def list_tanks_by_purpose(purpose: str) -> list[dict]:
    return [t for t in get_all_tanks() if (t.get("purpose") or "") == purpose]


def get_tank_dropdown_items(purpose: Optional[str] = None) -> list[dict]:
    """
    Dropdown items for spawning / assignment UIs.
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
    tanks = get_all_tanks()
    def _count(status_val):
        return sum(1 for t in tanks if (t.get("status") or "").lower() == status_val)
    return {
        "total": len(tanks),
        "empty_idle": _count("empty / idle") + _count("empty") + _count("idle"),
        "active": _count("active"),
        "occupied": _count("occupied"),
        "cleaning": _count("cleaning / quarantine"),
        "retired": _count("retired"),
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
        qr_bytes = _make_qr_png(location_code)   # QR encodes tape code — that's what humans scan
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
            status = "Active"

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
        # If we set an occupant, also mirror to fish.location
        if occupant_id:
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


def set_tank_status(tank_id: str, new_status: str) -> bool:
    """
    Change status. Does NOT auto-sync occupant — use assign/clear for that.
    """
    return update_tank(tank_id, {"status": new_status})


def assign_fish_to_tank(tank_id: str, fish_id: str) -> bool:
    """
    Assign a fish to a tank. Sets occupant_fish_id, occupant_label,
    status='Active', and mirrors fish.location.
    """
    fish = get_fish_by_id(fish_id)
    if not fish:
        st.error(f"Fish {fish_id} not found.")
        return False

    label = _fish_label(fish)
    ok = assign_occupant(tank_id, fish_id, label)
    if ok:
        tank = get_tank_by_id(tank_id)
        loc = tank.get("location_code") if tank else None
        if loc:
            update_fish_location(fish_id, loc)
        log_activity(
            action_type="tank_assigned",
            description=f"Assigned {fish.get('system_id')} to {loc}",
            entity_type="tank",
            entity_id=tank_id,
        )
    return ok


def unassign_tank(tank_id: str) -> bool:
    """
    Remove occupant. Sets status='Empty / Idle'. Clears fish.location.
    """
    tank = get_tank_by_id(tank_id)
    if not tank:
        return False

    fish_id = tank.get("occupant_fish_id")
    if fish_id:
        update_fish_location(fish_id, None)

    ok = clear_occupant(tank_id)
    if ok:
        log_activity(
            action_type="tank_unassigned",
            description=f"Cleared occupant from {tank.get('location_code')}",
            entity_type="tank",
            entity_id=tank_id,
        )
    return ok


def delete_tank_and_media(tank_id: str) -> bool:
    """Delete tank + Drive media. Frees any assigned fish."""
    tank = get_tank_by_id(tank_id)
    if not tank:
        return False

    # Free the assigned fish
    if tank.get("occupant_fish_id"):
        update_fish_location(tank["occupant_fish_id"], None)

    for f_id in (tank.get("photo_id"), tank.get("qr_id")):
        if f_id:
            delete_drive_file(f_id)

    ok = delete_tank(tank_id)
    if ok:
        log_activity(
            action_type="tank_deleted",
            description=f"Deleted {tank.get('location_code')}",
            entity_type="tank",
        )
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
