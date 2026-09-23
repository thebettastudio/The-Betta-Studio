# database.py
# Betta Farm Management System — Supabase wrapper
# Session 3  — replaces all Google Sheets access.
# Session 11 — added delete_strain().
# Session 15 — added fry batch read/delete helpers.
# Session 20 — added fish_milestones CRUD.

from __future__ import annotations

import datetime as _dt
from typing import Optional

import streamlit as st
from supabase import create_client, Client

from modules.supabase_client import get_supabase_client


# ============================================================
# HELPERS
# ============================================================

def _sb() -> Client:
    """Returns the shared Supabase client."""
    return get_supabase_client()


def _today_iso() -> str:
    return _dt.date.today().isoformat()


def _now_iso() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


# ============================================================
# FISH
# ============================================================

FISH_FIELDS = [
    "system_id", "origin", "batch_id", "line_code", "generation",
    "sire_id", "dam_id", "gender", "variety", "strain", "form_type",
    "grade", "body_shape", "form_score", "fin_checks",
    "seller", "purchase_date", "purchase_cost",
    "photo_id", "qr_id", "location", "tank_id",
    "status", "is_breeder", "breeder_status",
    "notes", "stage",
]


def get_all_fish() -> list[dict]:
    """Return every fish row, newest first."""
    try:
        res = _sb().table("fish").select("*").order("created_at", desc=True).execute()
        return res.data or []
    except Exception as e:
        st.error(f"get_all_fish failed: {e}")
        return []


def get_fish_by_id(fish_id: str) -> Optional[dict]:
    """Fetch one fish by its uuid."""
    try:
        res = _sb().table("fish").select("*").eq("id", fish_id).limit(1).execute()
        return (res.data or [None])[0]
    except Exception as e:
        st.error(f"get_fish_by_id failed: {e}")
        return None


def get_fish_by_system_id(system_id: str) -> Optional[dict]:
    """Fetch one fish by its human-readable ID (e.g. FISH-0042)."""
    try:
        res = _sb().table("fish").select("*").eq("system_id", system_id).limit(1).execute()
        return (res.data or [None])[0]
    except Exception as e:
        st.error(f"get_fish_by_system_id failed: {e}")
        return None


def create_fish(data: dict) -> Optional[dict]:
    """Insert a new fish row. `data` keys must match FISH_FIELDS."""
    payload = {k: data.get(k) for k in FISH_FIELDS if k in data}
    try:
        res = _sb().table("fish").insert(payload).execute()
        return (res.data or [None])[0]
    except Exception as e:
        st.error(f"create_fish failed: {e}")
        return None


def update_fish(fish_id: str, updates: dict) -> bool:
    """Update a fish row by uuid. Only FISH_FIELDS keys are accepted."""
    payload = {k: v for k, v in updates.items() if k in FISH_FIELDS}
    if not payload:
        return False
    try:
        _sb().table("fish").update(payload).eq("id", fish_id).execute()
        return True
    except Exception as e:
        st.error(f"update_fish failed: {e}")
        return False


def delete_fish(fish_id: str) -> bool:
    try:
        _sb().table("fish").delete().eq("id", fish_id).execute()
        return True
    except Exception as e:
        st.error(f"delete_fish failed: {e}")
        return False


def promote_fish_to_breeder(fish_id: str, breeder_status: str = "Available") -> bool:
    """Flip is_breeder=true and set breeder_status."""
    return update_fish(fish_id, {
        "is_breeder": True,
        "breeder_status": breeder_status,
        "status": "Conditioning",
    })


def retire_fish(fish_id: str, reason: str = "", extra_notes: str = "") -> bool:
    """Retire a breeder — clears tank link, sets status."""
    fish = get_fish_by_id(fish_id)
    if not fish:
        return False
    tag = f"[Retired: {reason}]" if reason else "[Retired]"
    new_notes = (fish.get("notes") or "").strip()
    new_notes = f"{new_notes} | {tag} {extra_notes}".strip(" |") if new_notes else f"{tag} {extra_notes}".strip()

    ok = update_fish(fish_id, {
        "is_breeder": False,
        "breeder_status": "Retired",
        "status": "Retired",
        "notes": new_notes,
        "location": None,
        "tank_id": None,
    })

    if fish.get("tank_id"):
        update_tank(fish["tank_id"], {"occupant_fish_id": None, "occupant_label": None, "status": "Empty / Idle"})
    return ok


def get_available_breeders() -> list[dict]:
    """Active breeders ready for pairing."""
    try:
        res = (_sb().table("fish")
               .select("*")
               .eq("is_breeder", True)
               .in_("breeder_status", ["Available", "Conditioning", "Ready", "Idle"])
               .execute())
        return res.data or []
    except Exception as e:
        st.error(f"get_available_breeders failed: {e}")
        return []


def get_next_fish_sequence(prefix: str = "FISH-") -> str:
    """Generate FISH-NNNN by counting existing system_ids with the prefix."""
    try:
        res = _sb().table("fish").select("system_id").like("system_id", f"{prefix}%").execute()
        nums = []
        for r in (res.data or []):
            sid = r.get("system_id") or ""
            tail = sid.replace(prefix, "").strip()
            if tail.isdigit():
                nums.append(int(tail))
        nxt = (max(nums) + 1) if nums else 1
        return f"{prefix}{nxt:04d}"
    except Exception as e:
        st.error(f"get_next_fish_sequence failed: {e}")
        return f"{prefix}0001"


# ============================================================
# TANKS
# ============================================================

TANK_FIELDS = [
    "system_id", "tank_type", "location_code", "capacity_liters",
    "status", "purpose", "occupant_fish_id", "occupant_label",
    "photo_id", "qr_id", "notes",
]


def get_all_tanks() -> list[dict]:
    try:
        res = _sb().table("tanks").select("*").order("created_at", desc=True).execute()
        return res.data or []
    except Exception as e:
        st.error(f"get_all_tanks failed: {e}")
        return []


def get_tank_by_id(tank_id: str) -> Optional[dict]:
    try:
        res = _sb().table("tanks").select("*").eq("id", tank_id).limit(1).execute()
        return (res.data or [None])[0]
    except Exception as e:
        st.error(f"get_tank_by_id failed: {e}")
        return None


def create_tank(data: dict) -> Optional[dict]:
    payload = {k: data.get(k) for k in TANK_FIELDS if k in data}
    try:
        res = _sb().table("tanks").insert(payload).execute()
        return (res.data or [None])[0]
    except Exception as e:
        st.error(f"create_tank failed: {e}")
        return None


def update_tank(tank_id: str, updates: dict) -> bool:
    payload = {k: v for k, v in updates.items() if k in TANK_FIELDS or k in ("date_registered",)}
    if not payload:
        return False
    try:
        _sb().table("tanks").update(payload).eq("id", tank_id).execute()
        return True
    except Exception as e:
        st.error(f"update_tank failed: {e}")
        return False


def delete_tank(tank_id: str) -> bool:
    try:
        _sb().table("tanks").delete().eq("id", tank_id).execute()
        return True
    except Exception as e:
        st.error(f"delete_tank failed: {e}")
        return False


def assign_occupant(tank_id: str, fish_id: Optional[str], label: str) -> bool:
    return update_tank(tank_id, {
        "occupant_fish_id": fish_id,
        "occupant_label": label,
        "status": "Active" if fish_id else "Empty / Idle",
    })


def clear_occupant(tank_id: str) -> bool:
    return update_tank(tank_id, {
        "occupant_fish_id": None,
        "occupant_label": None,
        "status": "Empty / Idle",
    })


def get_next_tank_sequence() -> str:
    """Sequential integer string ("1", "2", "3", ...)."""
    try:
        res = _sb().table("tanks").select("system_id").execute()
        nums = [int(r["system_id"]) for r in (res.data or []) if str(r.get("system_id", "")).isdigit()]
        return str((max(nums) + 1) if nums else 1)
    except Exception as e:
        st.error(f"get_next_tank_sequence failed: {e}")
        return "1"


# ============================================================
# SPAWNS
# ============================================================

SPAWN_FIELDS = [
    "system_id", "spawn_code", "line_code", "generation",
    "male_id", "female_id",
    "pairing_date", "status",
    "batch_name", "free_swimming_date", "jarring_date",
    "estimated_fry_count", "fry_count",
    "failure_reason", "tank_id", "line_goal", "notes",
]


def get_all_spawns() -> list[dict]:
    try:
        res = _sb().table("spawns").select("*").order("created_at", desc=True).execute()
        return res.data or []
    except Exception as e:
        st.error(f"get_all_spawns failed: {e}")
        return []


def get_spawn_by_id(spawn_id: str) -> Optional[dict]:
    try:
        res = _sb().table("spawns").select("*").eq("id", spawn_id).limit(1).execute()
        return (res.data or [None])[0]
    except Exception as e:
        st.error(f"get_spawn_by_id failed: {e}")
        return None


def create_spawn(data: dict) -> Optional[dict]:
    payload = {k: data.get(k) for k in SPAWN_FIELDS if k in data}
    try:
        res = _sb().table("spawns").insert(payload).execute()
        return (res.data or [None])[0]
    except Exception as e:
        st.error(f"create_spawn failed: {e}")
        return None


def update_spawn(spawn_id: str, updates: dict) -> bool:
    payload = {k: v for k, v in updates.items() if k in SPAWN_FIELDS}
    if not payload:
        return False
    try:
        _sb().table("spawns").update(payload).eq("id", spawn_id).execute()
        return True
    except Exception as e:
        st.error(f"update_spawn failed: {e}")
        return False


def delete_spawn(spawn_id: str) -> bool:
    try:
        _sb().table("spawns").delete().eq("id", spawn_id).execute()
        return True
    except Exception as e:
        st.error(f"delete_spawn failed: {e}")
        return False


def get_next_spawn_code() -> str:
    """SPN-YY-NN, resetting per year."""
    yy = _dt.date.today().strftime("%y")
    prefix = f"SPN-{yy}-"
    try:
        res = _sb().table("spawns").select("system_id").like("system_id", f"{prefix}%").execute()
        nums = []
        for r in (res.data or []):
            tail = (r.get("system_id") or "").replace(prefix, "").strip()
            if tail.isdigit():
                nums.append(int(tail))
        nxt = (max(nums) + 1) if nums else 1
        return f"{prefix}{nxt:02d}"
    except Exception as e:
        st.error(f"get_next_spawn_code failed: {e}")
        return f"{prefix}01"


# ============================================================
# STRAINS
# ============================================================

def get_all_strains() -> list[dict]:
    try:
        res = _sb().table("strains").select("*").order("name").execute()
        return res.data or []
    except Exception as e:
        st.error(f"get_all_strains failed: {e}")
        return []


def create_strain(name: str, line_code: str = "", description: str = "") -> Optional[dict]:
    try:
        res = _sb().table("strains").insert({
            "name": name, "line_code": line_code, "description": description,
        }).execute()
        return (res.data or [None])[0]
    except Exception as e:
        st.error(f"create_strain failed: {e}")
        return None


def delete_strain(strain_id: str) -> bool:
    """Delete a strain by uuid."""
    try:
        _sb().table("strains").delete().eq("id", strain_id).execute()
        return True
    except Exception as e:
        st.error(f"delete_strain failed: {e}")
        return False


# ============================================================
# ACTIVITY LOG
# ============================================================

def log_activity(
    action_type: str,
    description: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    photo_id: Optional[str] = None,
    photo_url: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> bool:
    try:
        _sb().table("activity_log").insert({
            "action_type": action_type,
            "description": description,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "photo_id": photo_id,
            "photo_url": photo_url,
            "metadata": metadata or {},
        }).execute()
        return True
    except Exception as e:
        print(f"log_activity failed: {e}")
        return False


def get_activity_log(limit: int = 200) -> list[dict]:
    try:
        res = (_sb().table("activity_log")
               .select("*")
               .order("ts", desc=True)
               .limit(limit)
               .execute())
        return res.data or []
    except Exception as e:
        st.error(f"get_activity_log failed: {e}")
        return []


# ============================================================
# FRY BATCHES
# ============================================================

FRY_BATCH_FIELDS = [
    "batch_tag", "batch_code", "spawn_id", "hatch_date", "jarring_date",
    "initial_count", "current_count", "stage", "tank_id", "notes",
]


def get_all_fry_batches() -> list[dict]:
    try:
        res = _sb().table("fry_batches").select("*").order("created_at", desc=True).execute()
        return res.data or []
    except Exception as e:
        st.error(f"get_all_fry_batches failed: {e}")
        return []


def create_fry_batch(data: dict) -> Optional[dict]:
    payload = {k: data.get(k) for k in FRY_BATCH_FIELDS if k in data}
    try:
        res = _sb().table("fry_batches").insert(payload).execute()
        return (res.data or [None])[0]
    except Exception as e:
        st.error(f"create_fry_batch failed: {e}")
        return None


def update_fry_batch(batch_id: str, updates: dict) -> bool:
    payload = {k: v for k, v in updates.items() if k in FRY_BATCH_FIELDS}
    if not payload:
        return False
    try:
        _sb().table("fry_batches").update(payload).eq("id", batch_id).execute()
        return True
    except Exception as e:
        st.error(f"update_fry_batch failed: {e}")
        return False


def get_fry_batch_by_id(batch_id: str) -> Optional[dict]:
    """Fetch one fry batch by uuid."""
    try:
        res = _sb().table("fry_batches").select("*").eq("id", batch_id).limit(1).execute()
        return (res.data or [None])[0]
    except Exception as e:
        st.error(f"get_fry_batch_by_id failed: {e}")
        return None


def get_fry_batches_for_spawn(spawn_id: str) -> list[dict]:
    """All batches linked to a specific spawn."""
    try:
        res = (_sb().table("fry_batches")
               .select("*")
               .eq("spawn_id", spawn_id)
               .order("created_at", desc=True)
               .execute())
        return res.data or []
    except Exception as e:
        st.error(f"get_fry_batches_for_spawn failed: {e}")
        return []


def delete_fry_batch(batch_id: str) -> bool:
    """Delete a fry batch by uuid."""
    try:
        _sb().table("fry_batches").delete().eq("id", batch_id).execute()
        return True
    except Exception as e:
        st.error(f"delete_fry_batch failed: {e}")
        return False


# ============================================================
# FISH MILESTONES (Session 20)
# ============================================================

MILESTONE_FIELDS = [
    "fish_id", "milestone_date", "photo_id",
    "form_score", "body_shape", "fin_checks",
    "notes",
]


def get_milestones_for_fish(fish_id: str) -> list[dict]:
    """All milestones for a fish, newest first."""
    try:
        res = (_sb().table("fish_milestones")
               .select("*")
               .eq("fish_id", fish_id)
               .order("milestone_date", desc=True)
               .execute())
        return res.data or []
    except Exception as e:
        st.error(f"get_milestones_for_fish failed: {e}")
        return []


def get_milestone_by_id(milestone_id: str) -> Optional[dict]:
    """Fetch one milestone by uuid."""
    try:
        res = (_sb().table("fish_milestones").select("*").eq("id", milestone_id).limit(1).execute()
        return (res.data or [None])[0]
    except Exception as e:
        st.error(f"get_milestone_by_id failed: {e}")
        return None


def create_milestone(data: dict) -> Optional[dict]:
    """Insert a milestone. `data` keys must match MILESTONE_FIELDS."""
    payload = {k: data.get(k) for k in MILESTONE_FIELDS if k in data}
    try:
        res = _sb().table("fish_milestones").insert(payload).execute()
        return (res.data or [None])[0]
    except Exception as e:
        st.error(f"create_milestone failed: {e}")
        return None


def update_milestone(milestone_id: str, updates: dict) -> bool:
    """Update a milestone. Only MILESTONE_FIELDS keys are accepted."""
    payload = {k: v for k, v in updates.items() if k in MILESTONE_FIELDS}
    if not payload:
        return False
    try:
        _sb().table("fish_milestones").update(payload).eq("id", milestone_id).execute()
        return True
    except Exception as e:
        st.error(f"update_milestone failed: {e}")
        return False


def delete_milestone(milestone_id: str) -> bool:
    """Delete a milestone by uuid."""
    try:
        _sb().table("fish_milestones").delete().eq("id", milestone_id).execute()
        return True
    except Exception as e:
        st.error(f"delete_milestone failed: {e}")
        return False


def get_milestone_counts_by_fish() -> dict:
    """
    Returns { fish_id: count } for all fish that have milestones.
    Single round-trip for the list view.
    """
    try:
        res = _sb().table("fish_milestones").select("fish_id").execute()
        counts: dict[str, int] = {}
        for row in (res.data or []):
            fid = row.get("fish_id")
            if fid:
                counts[fid] = counts.get(fid, 0) + 1
        return counts
    except Exception as e:
        st.error(f"get_milestone_counts_by_fish failed: {e}")
        return {}


# ============================================================
# DASHBOARD AGGREGATES (single round-trip)
# ============================================================

def get_dashboard_counts() -> dict:
    """Returns the 6 KPI numbers the dashboard needs in one call."""
    try:
        fish = _sb().table("fish").select("id,is_breeder,breeder_status,status,gender").execute().data or []
        tanks = _sb().table("tanks").select("id,status").execute().data or []
        spawns = _sb().table("spawns").select("id,status").execute().data or []

        total_tanks = len(tanks)
        available_tanks = sum(
            1 for t in tanks
            if (t.get("status") or "").lower() in ("empty / idle", "empty", "idle", "available", "ready")
        )

        total_breeders = sum(1 for f in fish if f.get("is_breeder"))
        males = sum(1 for f in fish if f.get("is_breeder") and (f.get("gender") or "").lower() == "male")
        females = sum(1 for f in fish if f.get("is_breeder") and (f.get("gender") or "").lower() == "female")

        active_spawn_states = {"in pairing", "pending (success)", "free swimming", "pairing", "eggs"}
        active_spawns = sum(
            1 for s in spawns
            if (s.get("status") or "").lower() in active_spawn_states
        )

        return {
            "total_tanks": total_tanks,
            "available_tanks": available_tanks,
            "total_breeders": total_breeders,
            "male_breeders": males,
            "female_breeders": females,
            "total_spawns": len(spawns),
            "active_spawns": active_spawns,
        }
    except Exception as e:
        st.error(f"get_dashboard_counts failed: {e}")
        return {}



# ============================================================
# FISH MILESTONES (Session 20)
# ============================================================

MILESTONE_FIELDS = [
    "fish_id", "milestone_date", "photo_id",
    "form_score", "body_shape", "fin_checks",
    "notes",
]


def get_milestones_for_fish(fish_id: str) -> list[dict]:
    """All milestones for a fish, newest first."""
    try:
        res = (_sb().table("fish_milestones")
               .select("*")
               .eq("fish_id", fish_id)
               .order("milestone_date", desc=True)
               .execute())
        return res.data or []
    except Exception as e:
        st.error(f"get_milestones_for_fish failed: {e}")
        return []


def get_milestone_by_id(milestone_id: str) -> Optional[dict]:
    """Fetch one milestone by uuid."""
    try:
        res = _sb().table("fish_milestones").select("*").eq("id", milestone_id).limit(1).execute()
        return (res.data or [None])[0]
    except Exception as e:
        st.error(f"get_milestone_by_id failed: {e}")
        return None


def create_milestone(data: dict) -> Optional[dict]:
    """Insert a milestone. `data` keys must match MILESTONE_FIELDS."""
    payload = {k: data.get(k) for k in MILESTONE_FIELDS if k in data}
    try:
        res = _sb().table("fish_milestones").insert(payload).execute()
        return (res.data or [None])[0]
    except Exception as e:
        st.error(f"create_milestone failed: {e}")
        return None


def update_milestone(milestone_id: str, updates: dict) -> bool:
    """Update a milestone. Only MILESTONE_FIELDS keys are accepted."""
    payload = {k: v for k, v in updates.items() if k in MILESTONE_FIELDS}
    if not payload:
        return False
    try:
        _sb().table("fish_milestones").update(payload).eq("id", milestone_id).execute()
        return True
    except Exception as e:
        st.error(f"update_milestone failed: {e}")
        return False


def delete_milestone(milestone_id: str) -> bool:
    """Delete a milestone by uuid."""
    try:
        _sb().table("fish_milestones").delete().eq("id", milestone_id).execute()
        return True
    except Exception as e:
        st.error(f"delete_milestone failed: {e}")
        return False


def get_milestone_counts_by_fish() -> dict:
    """
    Returns { fish_id: count } for all fish that have milestones.
    Single round-trip for the list view.
    """
    try:
        res = _sb().table("fish_milestones").select("fish_id").execute()
        counts: dict[str, int] = {}
        for row in (res.data or []):
            fid = row.get("fish_id")
            if fid:
                counts[fid] = counts.get(fid, 0) + 1
        return counts
    except Exception as e:
        st.error(f"get_milestone_counts_by_fish failed: {e}")
        return {}
