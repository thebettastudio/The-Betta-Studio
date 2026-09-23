# modules/fry_batch_manager.py
# Betta Farm Management System
# Session 15 — Fry batch tracking logic.
#
# One batch per spawn (Q2=A1). Manual stage advancement (Q4=A1).
# Hybrid jarring: bulk-create placeholder fish rows (Q3=A3).

from __future__ import annotations

import datetime as _dt
from typing import Optional

import streamlit as st

from database import (
    get_all_fry_batches,
    get_fry_batch_by_id,
    get_fry_batches_for_spawn,
    create_fry_batch,
    update_fry_batch,
    delete_fry_batch,
    get_all_spawns,
    get_spawn_by_id,
    get_all_tanks,
    get_all_fish,
    log_activity,
)
from modules.fish_manager import register_fish_from_spawn


# ============================================================
# CONSTANTS
# ============================================================

VALID_STAGES = [
    "egg",
    "fry",
    "free_swimming",
    "jarred",
    "juvenile",
    "sub_adult",
    "adult",
]

ACTIVE_STAGES = {"egg", "fry", "free_swimming"}
MATURE_STAGES = {"jarred", "juvenile", "sub_adult", "adult"}


# ============================================================
# READ
# ============================================================

def list_all_batches() -> list[dict]:
    """
    All fry batches, each enriched with:
      spawn      : spawn row (or None)
      tank       : tank row (or None)
      survival   : current_count / initial_count (float 0..1) or None
    """
    spawn_by_id = {s["id"]: s for s in get_all_spawns()}
    tank_by_id = {t["id"]: t for t in get_all_tanks()}

    out = []
    for b in get_all_fry_batches():
        initial = b.get("initial_count") or 0
        current = b.get("current_count") or 0
        survival = (current / initial) if initial > 0 else None

        out.append({
            "batch": b,
            "spawn": spawn_by_id.get(b.get("spawn_id")),
            "tank": tank_by_id.get(b.get("tank_id")),
            "survival": survival,
        })
    return out


def list_active_batches() -> list[dict]:
    """Batches whose stage is still in ACTIVE_STAGES."""
    return [d for d in list_all_batches() if (d["batch"].get("stage") or "").lower() in ACTIVE_STAGES]


def list_mature_batches() -> list[dict]:
    """Batches that have reached jarred or later."""
    return [d for d in list_all_batches() if (d["batch"].get("stage") or "").lower() in MATURE_STAGES]


def list_batches_for_spawn(spawn_id: str) -> list[dict]:
    """All batches linked to a spawn (usually 0 or 1)."""
    return get_fry_batches_for_spawn(spawn_id)


def get_batch_stats() -> dict:
    """Counts for the batch view header."""
    all_batches = get_all_fry_batches()
    alive_count = sum((b.get("current_count") or 0) for b in all_batches if (b.get("stage") or "").lower() in ACTIVE_STAGES)

    return {
        "total_batches": len(all_batches),
        "active_batches": sum(1 for b in all_batches if (b.get("stage") or "").lower() in ACTIVE_STAGES),
        "mature_batches": sum(1 for b in all_batches if (b.get("stage") or "").lower() in MATURE_STAGES),
        "total_fry_alive": alive_count,
    }


def suggest_batch_tag(spawn: dict) -> str:
    """
    Suggest a batch tag based on the spawn.
    Format: {line_code}-{generation} e.g. AVT-F1
    Fallback: {spawn.system_id} if line/gen are unknown.
    """
    line = (spawn.get("line_code") or "").strip()
    gen = (spawn.get("generation") or "").strip()
    if line and line != "UNK" and len(line) <= 12:
        return f"{line}-{gen}" if gen else line
    return spawn.get("system_id") or "BATCH"


def get_spawns_available_for_batch() -> list[dict]:
    """
    Spawns in 'Free Swimming' status WITHOUT an existing batch.
    These are the ones a user can create a new batch from.
    """
    existing_spawn_ids = {b.get("spawn_id") for b in get_all_fry_batches()}
    out = []
    for s in get_all_spawns():
        if (s.get("status") or "") != "Free Swimming":
            continue
        if s["id"] in existing_spawn_ids:
            continue
        out.append(s)
    return out


# ============================================================
# CREATE
# ============================================================

def create_batch_from_spawn(
    spawn_id: str,
    *,
    batch_tag: str,
    initial_count: int,
    notes: str = "",
) -> Optional[dict]:
    """
    Create a fry batch linked to a spawn.
    Enforces: one batch per spawn.
    """
    spawn = get_spawn_by_id(spawn_id)
    if not spawn:
        st.error(f"Spawn {spawn_id} not found.")
        return None

    # Enforce one-batch-per-spawn (Q2 = A1)
    existing = get_fry_batches_for_spawn(spawn_id)
    if existing:
        st.error(f"Spawn {spawn.get('system_id')} already has a batch.")
        return None

    today = _dt.date.today().isoformat()

    record = {
        "batch_tag": batch_tag.strip() or suggest_batch_tag(spawn),
        "batch_code": spawn.get("spawn_code") or spawn.get("system_id") or "",
        "spawn_id": spawn_id,
        "hatch_date": spawn.get("free_swimming_date") or today,
        "initial_count": int(initial_count or 0),
        "current_count": int(initial_count or 0),
        "stage": "fry",
        "notes": notes,
    }

    saved = create_fry_batch(record)
    if saved:
        log_activity(
            action_type="fry_batch_created",
            description=f"Created batch '{saved.get('batch_tag')}' from {spawn.get('system_id')} with {initial_count} fry",
            entity_type="fry_batch",
            entity_id=saved["id"],
        )
    return saved


# ============================================================
# UPDATE
# ============================================================

def edit_batch(batch_id: str, updates: dict) -> bool:
    """Generic field update."""
    ok = update_fry_batch(batch_id, updates)
    if ok:
        log_activity(
            action_type="fry_batch_updated",
            description=f"Updated batch fields: {', '.join(updates.keys())}",
            entity_type="fry_batch",
            entity_id=batch_id,
        )
    return ok


def advance_stage(batch_id: str, new_stage: str) -> bool:
    """
    Manually advance a batch's stage (Q4 = A1).
    Setting stage='jarred' also sets jarring_date=today if not set.
    """
    if new_stage not in VALID_STAGES:
        st.error(f"Invalid stage: {new_stage}")
        return False

    updates = {"stage": new_stage}
    if new_stage == "jarred":
        batch = get_fry_batch_by_id(batch_id)
        if batch and not batch.get("jarring_date"):
            updates["jarring_date"] = _dt.date.today().isoformat()

    ok = update_fry_batch(batch_id, updates)
    if ok:
        b = get_fry_batch_by_id(batch_id)
        log_activity(
            action_type="fry_batch_stage_changed",
            description=f"Batch '{b.get('batch_tag')}' advanced to {new_stage}",
            entity_type="fry_batch",
            entity_id=batch_id,
        )
    return ok


def set_current_count(batch_id: str, count: int) -> bool:
    """Manual mortality update."""
    count = max(0, int(count))
    ok = update_fry_batch(batch_id, {"current_count": count})
    if ok:
        b = get_fry_batch_by_id(batch_id)
        log_activity(
            action_type="fry_batch_count_updated",
            description=f"Batch '{b.get('batch_tag')}' count set to {count}",
            entity_type="fry_batch",
            entity_id=batch_id,
        )
    return ok


def assign_batch_tank(batch_id: str, tank_id: Optional[str]) -> bool:
    """Assign or clear the batch's grow-out tank."""
    ok = update_fry_batch(batch_id, {"tank_id": tank_id})
    if ok:
        b = get_fry_batch_by_id(batch_id)
        log_activity(
            action_type="fry_batch_tank_assigned",
            description=f"Batch '{b.get('batch_tag')}' assigned to tank",
            entity_type="fry_batch",
            entity_id=batch_id,
        )
    return ok


# ============================================================
# JARRING FLOW (Q3 = A3, hybrid)
# ============================================================

def jar_fry_bulk(
    batch_id: str,
    *,
    count: int,
    gender: str = "Unsexed",
    grade: str = "Pet Grade",
    location: str = "",
) -> list[dict]:
    """
    Bulk-create `count` placeholder fish rows linked to the batch's spawn.
    Each call to register_fish_from_spawn() generates the next sequential
    system_id for that spawn (SPN-XXX-NN).

    Does NOT decrement current_count automatically — the caller should
    call set_current_count() with the remaining fry count.

    Returns: list of created fish rows.
    """
    batch = get_fry_batch_by_id(batch_id)
    if not batch:
        st.error(f"Batch {batch_id} not found.")
        return []

    spawn_id = batch.get("spawn_id")
    if not spawn_id:
        st.error("Batch is not linked to a spawn.")
        return []

    count = max(0, int(count))
    if count == 0:
        return []

    created = []
    for _ in range(count):
        fish = register_fish_from_spawn(
            spawn_id=spawn_id,
            gender=gender,
            grade=grade,
            location=location,
            notes=f"Jarred from batch '{batch.get('batch_tag')}'",
        )
        if fish:
            created.append(fish)

    if created:
        log_activity(
            action_type="fry_batch_jarred",
            description=f"Jarred {len(created)} fry from batch '{batch.get('batch_tag')}'",
            entity_type="fry_batch",
            entity_id=batch_id,
        )
    return created


# ============================================================
# DELETE
# ============================================================

def delete_batch(batch_id: str) -> bool:
    """
    Delete a batch. Does NOT delete fish rows that were jarred from it
    (their batch_id FK will be nulled by the DB).
    """
    batch = get_fry_batch_by_id(batch_id)
    if not batch:
        return False
    ok = delete_fry_batch(batch_id)
    if ok:
        log_activity(
            action_type="fry_batch_deleted",
            description=f"Deleted batch '{batch.get('batch_tag')}'",
            entity_type="fry_batch",
        )
    return ok
