# modules/spawn_manager.py
# Betta Farm Management System
# Session 8 — Spawn lifecycle ported to Supabase.

from __future__ import annotations

import datetime as _dt
from typing import Optional

import streamlit as st

from database import (
    get_all_spawns,
    get_spawn_by_id,
    create_spawn,
    update_spawn,
    delete_spawn,
    get_fish_by_id,
    get_all_fish,
    log_activity,
)
from modules.id_generator import (
    generate_spawn_system_id,
    generate_spawn_code,
    calculate_child_lineage,
)
from modules.fish_manager import (
    get_breeder_pairs_data,
    sync_breeder_status,
)
from modules.tank_registry import (
    get_tank_dropdown_items,
    find_tank,
    assign_fish_to_tank,
    unassign_tank,
)


# ============================================================
# VALID STATUSES (used by UI)
# ============================================================

VALID_SPAWN_STATUSES = [
    "In Pairing",
    "Pending (Success)",
    "Free Swimming",
    "Failed",
    "Completed",
]

ACTIVE_STATUSES = {"In Pairing", "Pending (Success)"}
SUCCESS_STATUSES = {"Pending (Success)", "Free Swimming", "Completed"}


# ============================================================
# READ
# ============================================================

def list_all_spawns() -> list[dict]:
    return get_all_spawns()


def list_active_spawns() -> list[dict]:
    return [s for s in get_all_spawns() if (s.get("status") in ACTIVE_STATUSES)]


def list_spawns_with_details() -> list[dict]:
    """
    Returns all spawns, each enriched with:
      male: fish row of sire (or None)
      female: fish row of dam (or None)
      tank: tank row (or None)
    """
    fish_by_id = {f["id"]: f for f in get_all_fish()}
    out = []
    for s in get_all_spawns():
        out.append({
            "spawn": s,
            "male": fish_by_id.get(s.get("male_id")),
            "female": fish_by_id.get(s.get("female_id")),
        })
    return out


def list_active_pairings_with_details() -> list[dict]:
    return [d for d in list_spawns_with_details() if d["spawn"].get("status") in ACTIVE_STATUSES]


def get_pairing_dropdown_data() -> tuple[list[dict], list[dict]]:
    """Returns (males, females) dropdown items from available breeders."""
    return get_breeder_pairs_data()


# ============================================================
# CREATE
# ============================================================

def create_new_spawn(
    male_id: str,               # fish uuid
    female_id: str,             # fish uuid
    tank_id: Optional[str] = None,   # tank uuid
    line_goal: str = "",
    notes: str = "",
) -> Optional[dict]:
    """
    Create a new spawn record.
    - Calculates child line_code + generation from parents
    - Generates system_id (SPN-{LINE}-{GEN}-NN) and spawn_code (SPN-YY-NN)
    - Sets both parents to breeder_status 'In Pairing'
    - Assigns tank to the spawn (marks 'Occupied')
    """
    sire = get_fish_by_id(male_id)
    dam  = get_fish_by_id(female_id)
    if not sire or not dam:
        st.error("Both parents must be valid fish.")
        return None

    # Lineage calculation
    line_code, generation = calculate_child_lineage(
        male_line=sire.get("line_code") or "UNK",
        male_gen=sire.get("generation") or "P1",
        female_line=dam.get("line_code") or "UNK",
        female_gen=dam.get("generation") or "P1",
    )

    system_id  = generate_spawn_system_id(
        male_line=sire.get("line_code") or "UNK",
        male_gen=sire.get("generation") or "P1",
        female_line=dam.get("line_code") or "UNK",
        female_gen=dam.get("generation") or "P1",
    )
    spawn_code = generate_spawn_code()
    pairing_date = _dt.date.today().isoformat()

    record = {
        "system_id": system_id,
        "spawn_code": spawn_code,
        "line_code": line_code,
        "generation": generation,
        "male_id": male_id,
        "female_id": female_id,
        "pairing_date": pairing_date,
        "status": "In Pairing",
        "tank_id": tank_id,
        "line_goal": line_goal,
        "notes": notes,
    }

    saved = create_spawn(record)
    if not saved:
        return None

    # Update parents
    sync_breeder_status(male_id, "In Pairing")
    sync_breeder_status(female_id, "In Pairing")

    # Assign tank
    if tank_id:
        tank = find_tank(tank_id)
        if tank:
            from database import assign_occupant
            assign_occupant(tank_id, None, f"Spawn {system_id}")
            # We still track the spawn-tank link on the spawn row via tank_id

    log_activity(
        action_type="spawn_created",
        description=f"Started pairing {sire.get('system_id')} × {dam.get('system_id')} ({system_id})",
        entity_type="spawn",
        entity_id=saved["id"],
    )
    return saved


# ============================================================
# LIFECYCLE
# ============================================================

def mark_pairing_success_pending(spawn_id: str) -> bool:
    """Move status to 'Pending (Success)'."""
    ok = update_spawn(spawn_id, {"status": "Pending (Success)"})
    if ok:
        s = get_spawn_by_id(spawn_id)
        log_activity(
            action_type="spawn_pending_success",
            description=f"{s.get('system_id')} marked Pending (Success)",
            entity_type="spawn",
            entity_id=spawn_id,
        )
    return ok


def mark_free_swimming(
    spawn_id: str,
    batch_name: str,
    est_fry_count: int = 0,
) -> bool:
    """
    Transition to Free Swimming. Sets dates/counts, releases breeders,
    and frees the tank.
    """
    spawn = get_spawn_by_id(spawn_id)
    if not spawn:
        return False

    free_swim_date = _dt.date.today().isoformat()

    ok = update_spawn(spawn_id, {
        "status": "Free Swimming",
        "batch_name": batch_name,
        "free_swimming_date": free_swim_date,
        "estimated_fry_count": int(est_fry_count or 0),
    })
    if not ok:
        return False

    # Release parents
    sync_breeder_status(spawn.get("male_id"), "Available")
    sync_breeder_status(spawn.get("female_id"), "Available")

    # Free tank
    if spawn.get("tank_id"):
        unassign_tank(spawn["tank_id"])

    log_activity(
        action_type="spawn_free_swimming",
        description=f"{spawn.get('system_id')} free swimming — batch '{batch_name}', ~{est_fry_count} fry",
        entity_type="spawn",
        entity_id=spawn_id,
    )
    return True


def mark_pairing_failed(spawn_id: str, failure_reason: str) -> bool:
    """Mark Failed, log reason, release parents, free tank."""
    spawn = get_spawn_by_id(spawn_id)
    if not spawn:
        return False

    ok = update_spawn(spawn_id, {
        "status": "Failed",
        "failure_reason": failure_reason or "",
    })
    if not ok:
        return False

    sync_breeder_status(spawn.get("male_id"), "Available")
    sync_breeder_status(spawn.get("female_id"), "Available")

    if spawn.get("tank_id"):
        unassign_tank(spawn["tank_id"])

    log_activity(
        action_type="spawn_failed",
        description=f"{spawn.get('system_id')} failed — {failure_reason or 'no reason given'}",
        entity_type="spawn",
        entity_id=spawn_id,
    )
    return True


def mark_completed(spawn_id: str, fry_count: Optional[int] = None) -> bool:
    """
    Final close-out. Sets status='Completed' and optionally the final fry count.
    Parents/tank should already be released by Free Swimming transition.
    """
    updates = {"status": "Completed"}
    if fry_count is not None:
        updates["fry_count"] = int(fry_count)

    ok = update_spawn(spawn_id, updates)
    if ok:
        s = get_spawn_by_id(spawn_id)
        log_activity(
            action_type="spawn_completed",
            description=f"{s.get('system_id')} completed",
            entity_type="spawn",
            entity_id=spawn_id,
        )
    return ok


# ============================================================
# EDIT
# ============================================================

def update_spawn_details(
    spawn_id: str,
    batch_name: Optional[str] = None,
    fry_count: Optional[int] = None,
    status: Optional[str] = None,
    line_goal: Optional[str] = None,
    notes: Optional[str] = None,
) -> bool:
    """Edit arbitrary fields on a spawn. Only non-None args are applied."""
    updates = {}
    if batch_name is not None: updates["batch_name"] = batch_name
    if fry_count is not None:  updates["fry_count"] = int(fry_count)
    if status is not None:     updates["status"] = status
    if line_goal is not None:  updates["line_goal"] = line_goal
    if notes is not None:      updates["notes"] = notes

    if not updates:
        return False

    ok = update_spawn(spawn_id, updates)
    if ok:
        log_activity(
            action_type="spawn_updated",
            description=f"Updated {spawn_id}: {', '.join(updates.keys())}",
            entity_type="spawn",
            entity_id=spawn_id,
        )
    return ok


def delete_spawn_record(spawn_id: str) -> bool:
    """Delete a spawn. Fish with batch_id pointing here have their FK nulled."""
    spawn = get_spawn_by_id(spawn_id)
    if not spawn:
        return False
    ok = delete_spawn(spawn_id)
    if ok:
        log_activity(
            action_type="spawn_deleted",
            description=f"Deleted {spawn.get('system_id')}",
            entity_type="spawn",
        )
    return ok
