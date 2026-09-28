# modules/fry_batch_manager.py
# Betta Farm Management System
# Session 15 — Fry batch tracking logic.
#
# One batch per spawn (Q2=A1). Manual stage advancement (Q4=A1).
# Hybrid jarring: bulk-create placeholder fish rows (Q3=A3).
#
# Session 28A/B2b — jar_fry_bulk() accepts optional jarring_date;
#   each jarred fish inherits birth_date = jarring_date; batch's own
#   jarring_date set on first jarring if empty.
#
# Session 29 (this revision) — Fry batch fixes:
#   • create_batch_from_spawn() accepts hatch_date (defaults to
#     free_swimming_date - 3 days) — fixes hatch_date bug.
#   • jar_fry_bulk() auto-advances batch stage → jarred after bulk
#     create; returns (created, failed_count).
#   • New get_batch_parents(batch) → {male, female} for thumbnails.
#   • get_batch_parents() now surfaces exceptions via st.warning
#     instead of silently swallowing them (an unreachable parent
#     no longer shows as "Unknown").
#   • Removed unused get_all_fish import.

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
    get_fish_by_id,
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

# Default hatch offset from free-swimming date (days before free-swim).
DEFAULT_HATCH_OFFSET_DAYS = 3


# ============================================================
# READ
# ============================================================

def list_all_batches() -> list[dict]:
    """All fry batches enriched with spawn, tank, survival."""
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
    alive_count = sum(
        (b.get("current_count") or 0)
        for b in all_batches
        if (b.get("stage") or "").lower() in ACTIVE_STAGES
    )

    return {
        "total_batches": len(all_batches),
        "active_batches": sum(1 for b in all_batches if (b.get("stage") or "").lower() in ACTIVE_STAGES),
        "mature_batches": sum(1 for b in all_batches if (b.get("stage") or "").lower() in MATURE_STAGES),
        "total_fry_alive": alive_count,
    }


def suggest_batch_tag(spawn: dict) -> str:
    """Suggest a batch tag: {line_code}-{generation} or fallback."""
    line = (spawn.get("line_code") or "").strip()
    gen = (spawn.get("generation") or "").strip()
    if line and line != "UNK" and len(line) <= 12:
        return f"{line}-{gen}" if gen else line
    return spawn.get("system_id") or "BATCH"


def get_spawns_available_for_batch() -> list[dict]:
    """Spawns in 'Free Swimming' status WITHOUT an existing batch."""
    existing_spawn_ids = {b.get("spawn_id") for b in get_all_fry_batches()}
    out = []
    for s in get_all_spawns():
        if (s.get("status") or "") != "Free Swimming":
            continue
        if s["id"] in existing_spawn_ids:
            continue
        out.append(s)
    return out


def get_batch_parents(batch: dict) -> dict:
    """
    Session 29 — return the sire and dam fish rows for a batch's spawn.
    Returns {"male": fish_row | None, "female": fish_row | None}.

    Session 29 fix — surfaces exceptions via st.warning instead of
    silently swallowing them. An unreachable parent now tells you
    something went wrong, rather than masquerading as "Unknown".
    """
    out = {"male": None, "female": None}
    try:
        spawn_id = batch.get("spawn_id")
        if not spawn_id:
            return out
        spawn = next((s for s in get_all_spawns() if s["id"] == spawn_id), None)
        if not spawn:
            return out
        if spawn.get("male_id"):
            out["male"] = get_fish_by_id(spawn["male_id"])
        if spawn.get("female_id"):
            out["female"] = get_fish_by_id(spawn["female_id"])
    except Exception as e:
        st.warning(f"get_batch_parents failed: {e}")
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
    hatch_date: Optional[str] = None,
) -> Optional[dict]:
    """
    Create a fry batch linked to a spawn. Enforces one-per-spawn.

    Session 29 — accepts optional hatch_date (ISO 'YYYY-MM-DD').
    If omitted, defaults to spawn.free_swimming_date minus 3 days
    (DEFAULT_HATCH_OFFSET_DAYS), falling back to today.
    """
    spawn = get_spawn_by_id(spawn_id)
    if not spawn:
        st.error(f"Spawn {spawn_id} not found.")
        return None

    existing = get_fry_batches_for_spawn(spawn_id)
    if existing:
        st.error(f"Spawn {spawn.get('system_id')} already has a batch.")
        return None

    today = _dt.date.today().isoformat()

    # Resolve hatch_date: explicit → free_swimming_date - 3d → today
    resolved_hatch = hatch_date
    if not resolved_hatch:
        fsd = spawn.get("free_swimming_date")
        if fsd:
            try:
                fsd_date = _dt.date.fromisoformat(str(fsd)[:10])
                resolved_hatch = (
                    fsd_date - _dt.timedelta(days=DEFAULT_HATCH_OFFSET_DAYS)
                ).isoformat()
            except Exception:
                resolved_hatch = today
        else:
            resolved_hatch = today

    record = {
        "batch_tag": batch_tag.strip() or suggest_batch_tag(spawn),
        "batch_code": spawn.get("spawn_code") or spawn.get("system_id") or "",
        "spawn_id": spawn_id,
        "hatch_date": resolved_hatch,
        "initial_count": int(initial_count or 0),
        "current_count": int(initial_count or 0),
        "stage": "fry",
        "notes": notes,
    }

    saved = create_fry_batch(record)
    if saved:
        log_activity(
            action_type="fry_batch_created",
            description=(
                f"Created batch '{saved.get('batch_tag')}' from "
                f"{spawn.get('system_id')} with {initial_count} fry "
                f"(hatch {resolved_hatch})"
            ),
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
    """Manually advance a batch's stage."""
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
# JARRING FLOW
# ============================================================

def jar_fry_bulk(
    batch_id: str,
    *,
    count: int,
    gender: str = "Unsexed",
    grade: str = "Pet Grade",
    location: str = "",
    jarring_date: Optional[str] = None,
) -> tuple[list[dict], int]:
    """
    Bulk-create `count` placeholder fish rows linked to the batch's spawn.

    Session 28A/B2b — accepts an optional jarring_date (ISO 'YYYY-MM-DD').
    Session 29 — auto-advances batch stage → jarred after bulk create;
    returns (created_list, failed_count) so the caller can surface
    partial failures.

    Does NOT decrement current_count — caller does that via set_current_count().

    Returns: (created_fish_rows, failed_count).
    """
    batch = get_fry_batch_by_id(batch_id)
    if not batch:
        st.error(f"Batch {batch_id} not found.")
        return ([], 0)

    spawn_id = batch.get("spawn_id")
    if not spawn_id:
        st.error("Batch is not linked to a spawn.")
        return ([], 0)

    count = max(0, int(count))
    if count == 0:
        return ([], 0)

    # Resolve the effective jarring date
    resolved_date = jarring_date or _dt.date.today().isoformat()

    # Update batch's jarring_date if empty
    if not batch.get("jarring_date"):
        update_fry_batch(batch_id, {"jarring_date": resolved_date})

    created = []
    failed = 0
    for _ in range(count):
        fish = register_fish_from_spawn(
            spawn_id=spawn_id,
            gender=gender,
            grade=grade,
            location=location,
            notes=f"Jarred from batch '{batch.get('batch_tag')}'",
            birth_date=resolved_date,
        )
        if fish:
            created.append(fish)
        else:
            failed += 1

    # Auto-advance stage → jarred after successful bulk create
    if created and (batch.get("stage") or "").lower() not in ("jarred", "juvenile", "sub_adult", "adult"):
        update_fry_batch(batch_id, {"stage": "jarred"})

    if created:
        log_activity(
            action_type="fry_batch_jarred",
            description=(
                f"Jarred {len(created)} fry from batch '{batch.get('batch_tag')}' "
                f"(jarring date {resolved_date})"
                + (f" — {failed} failed" if failed else "")
            ),
            entity_type="fry_batch",
            entity_id=batch_id,
        )
    return (created, failed)


# ============================================================
# DELETE
# ============================================================

def delete_batch(batch_id: str) -> bool:
    """Delete a batch. Fish rows that were jarred from it keep their FK (nulled by DB)."""
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
