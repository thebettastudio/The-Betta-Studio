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
# Session 29 — Fry batch fixes:
#   • create_batch_from_spawn() accepts hatch_date (defaults to
#     free_swimming_date - 3 days) — fixes hatch_date bug.
#   • jar_fry_bulk() auto-advances batch stage → jarred after bulk
#     create; returns (created, failed_count).
#   • New get_batch_parents(batch) → {male, female} for thumbnails.
#   • Removed unused get_all_fish import.
#
# Session 29/D — Undo Jar + Delete Batch & Fish:
#   • get_batch_jarred_fish(batch) → fish rows jarred by this batch
#   • count_batch_jarred_fish(batch) → fast count for preview
#   • undo_batch_jar(batch, delete_photos=True) → deletes jarred
#     fish, restores current_count, clears jarring_date, stage→free_swimming
#   • delete_batch_and_fish(batch, delete_photos=True) → deletes all
#     jarred fish + the batch itself

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
    get_all_fish,
    delete_fish,
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
    return [d for d in list_all_batches() if (d["batch"].get("stage") or "").lower() in ACTIVE_STAGES]


def list_mature_batches() -> list[dict]:
    return [d for d in list_all_batches() if (d["batch"].get("stage") or "").lower() in MATURE_STAGES]


def list_batches_for_spawn(spawn_id: str) -> list[dict]:
    return get_fry_batches_for_spawn(spawn_id)


def get_batch_stats() -> dict:
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
    line = (spawn.get("line_code") or "").strip()
    gen = (spawn.get("generation") or "").strip()
    if line and line != "UNK" and len(line) <= 12:
        return f"{line}-{gen}" if gen else line
    return spawn.get("system_id") or "BATCH"


def get_spawns_available_for_batch() -> list[dict]:
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
    Return the sire and dam fish rows for a batch's spawn.
    Returns {"male": fish_row | None, "female": fish_row | None}.
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
# BATCH ↔ FISH LINKING (Session 29/D)
# ============================================================

def _iso_date_prefix(val) -> Optional[str]:
    """Return YYYY-MM-DD from a value, or None if it can't be parsed."""
    if not val:
        return None
    s = str(val)[:10]
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    return None


def get_batch_jarred_fish(batch: dict) -> list[dict]:
    """
    Return all fish rows that were jarred by this specific batch.

    Discriminator: fish.batch_id == spawn_id (spawn id, not fry_batch
    id — see register_fish_from_spawn) AND fish.birth_date matches
    the batch's jarring_date.

    If the batch has no jarring_date, returns [] — we can't safely
    discriminate which fish belong to which batch of a multi-batch
    spawn. Set jarring_date first.
    """
    try:
        spawn_id = batch.get("spawn_id")
        if not spawn_id:
            return []
        jarring_date = _iso_date_prefix(batch.get("jarring_date"))
        if not jarring_date:
            return []

        out = []
        for f in get_all_fish():
            if f.get("batch_id") != spawn_id:
                continue
            if _iso_date_prefix(f.get("birth_date")) != jarring_date:
                continue
            out.append(f)
        return out
    except Exception as e:
        st.warning(f"get_batch_jarred_fish failed: {e}")
        return []


def count_batch_jarred_fish(batch: dict) -> int:
    """Fast count of jarred fish for this batch (for preview UI)."""
    try:
        spawn_id = batch.get("spawn_id")
        if not spawn_id:
            return 0
        jarring_date = _iso_date_prefix(batch.get("jarring_date"))
        if not jarring_date:
            return 0

        count = 0
        for f in get_all_fish():
            if f.get("batch_id") != spawn_id:
                continue
            if _iso_date_prefix(f.get("birth_date")) == jarring_date:
                count += 1
        return count
    except Exception:
        return 0


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
    """Create a fry batch linked to a spawn. Enforces one-per-spawn."""
    spawn = get_spawn_by_id(spawn_id)
    if not spawn:
        st.error(f"Spawn {spawn_id} not found.")
        return None

    existing = get_fry_batches_for_spawn(spawn_id)
    if existing:
        st.error(f"Spawn {spawn.get('system_id')} already has a batch.")
        return None

    today = _dt.date.today().isoformat()

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
    Returns (created_fish_rows, failed_count).
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

    resolved_date = jarring_date or _dt.date.today().isoformat()

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
# UNDO JAR  (Session 29/D)
# ============================================================

def undo_batch_jar(
    batch: dict,
    *,
    delete_photos: bool = True,
) -> tuple[int, int, Optional[str]]:
    """
    Reverse a batch's jarring: delete every fish jarred by this
    batch, restore current_count, clear jarring_date, flip stage
    back to free_swimming.

    Returns: (deleted_count, failed_count, error_message_or_None).
    """
    try:
        batch_id = batch.get("id")
        if not batch_id:
            return (0, 0, "Missing batch id.")

        jarred = get_batch_jarred_fish(batch)

        deleted = 0
        failed = 0
        for f in jarred:
            fid = f.get("id")
            if not fid:
                failed += 1
                continue

            # Optionally delete the Drive file(s) first.
            if delete_photos:
                try:
                    from modules.photo_service import delete_drive_file
                    for key in ("photo_id", "qr_id"):
                        if f.get(key):
                            delete_drive_file(f[key])
                except Exception:
                    # Non-fatal — proceed with row delete.
                    pass

            ok = delete_fish(fid)
            if ok:
                deleted += 1
            else:
                failed += 1

        # Restore count + clear jarring state
        restored_count = (batch.get("current_count") or 0) + deleted
        current_stage = (batch.get("stage") or "").lower()
        updates = {
            "current_count": restored_count,
            "jarring_date": None,
        }
        # Only step back to free_swimming if we were still in jarred.
        if current_stage == "jarred":
            updates["stage"] = "free_swimming"

        update_fry_batch(batch_id, updates)

        log_activity(
            action_type="fry_batch_jar_undone",
            description=(
                f"Undid jar for batch '{batch.get('batch_tag')}': "
                f"deleted {deleted} fish, restored current_count to {restored_count}"
                + (f" ({failed} failed)" if failed else "")
            ),
            entity_type="fry_batch",
            entity_id=batch_id,
        )
        return (deleted, failed, None)
    except Exception as e:
        return (0, 0, str(e))


# ============================================================
# DELETE BATCH & FISH  (Session 29/D)
# ============================================================

def delete_batch_and_fish(
    batch: dict,
    *,
    delete_photos: bool = True,
) -> tuple[int, int, bool, Optional[str]]:
    """
    Delete every fish jarred by this batch AND the batch itself.

    Returns: (deleted_fish, failed_fish, batch_deleted, error_or_None).
    """
    try:
        batch_id = batch.get("id")
        if not batch_id:
            return (0, 0, False, "Missing batch id.")

        jarred = get_batch_jarred_fish(batch)

        deleted = 0
        failed = 0
        for f in jarred:
            fid = f.get("id")
            if not fid:
                failed += 1
                continue

            if delete_photos:
                try:
                    from modules.photo_service import delete_drive_file
                    for key in ("photo_id", "qr_id"):
                        if f.get(key):
                            delete_drive_file(f[key])
                except Exception:
                    pass

            ok = delete_fish(fid)
            if ok:
                deleted += 1
            else:
                failed += 1

        batch_ok = delete_batch(batch_id)
        if batch_ok:
            log_activity(
                action_type="fry_batch_deleted_with_fish",
                description=(
                    f"Deleted batch '{batch.get('batch_tag')}' and "
                    f"{deleted} jarred fish"
                    + (f" ({failed} failed)" if failed else "")
                ),
                entity_type="fry_batch",
            )
        return (deleted, failed, batch_ok, None)
    except Exception as e:
        return (0, 0, False, str(e))


# ============================================================
# DELETE (existing, keeps fish)
# ============================================================

def delete_batch(batch_id: str) -> bool:
    """Delete a batch only. Jarred fish are kept."""
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
