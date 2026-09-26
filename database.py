# database.py
# Betta Farm Management System — Supabase wrapper
# Session 3  — replaces all Google Sheets access.
# Session 11 — added delete_strain().
# Session 15 — added fry batch read/delete helpers.
# Session 20 — added fish_milestones CRUD.
# Session 22 — added culled_count + female_count to FRY_BATCH_FIELDS.
# Session 24C — added died_count to FRY_BATCH_FIELDS.
# Session 26A — added color_primary, color_secondary, color_palette,
#               pattern_hint, iridescence_level to FISH_FIELDS.
# Session 26H.7 — Tank model redesign:
#   • tank_occupants join table (multi-occupant support)
#   • reservation fields (reserved_for/reason/until/ref_id)
#   • "Active" status removed → "Occupied"
#   • transfer_occupant(), reserve_tank(), cancel_reservation()

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
    "color_primary", "color_secondary", "color_palette",
    "pattern_hint", "iridescence_level",
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

    # Clear occupants from any tank
    for occ in get_occupants_for_fish(fish_id):
        remove_tank_occupant(occ["tank_id"], "fish", fish_id)

    ok = update_fish(fish_id, {
        "is_breeder": False,
        "breeder_status": "Retired",
        "status": "Retired",
        "notes": new_notes,
        "location": None,
        "tank_id": None,
    })
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
    "reserved_for", "reserved_reason", "reserved_until", "reserved_ref_id",
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
    payload = {k: v for k, v in updates.items()
               if k in TANK_FIELDS or k in ("date_registered",)}
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
# TANK OCCUPANTS (Session 26H.7 — join table)
# ============================================================

def get_tank_occupants(tank_id: str) -> list[dict]:
    """All occupants of a tank."""
    try:
        res = (_sb().table("tank_occupants")
               .select("*")
               .eq("tank_id", tank_id)
               .order("added_at")
               .execute())
        return res.data or []
    except Exception as e:
        st.error(f"get_tank_occupants failed: {e}")
        return []


def get_occupants_for_fish(fish_id: str) -> list[dict]:
    """Find which tank(s) a fish is in."""
    try:
        res = (_sb().table("tank_occupants")
               .select("*")
               .eq("occupant_type", "fish")
               .eq("occupant_id", fish_id)
               .execute())
        return res.data or []
    except Exception as e:
        st.error(f"get_occupants_for_fish failed: {e}")
        return []


def get_occupants_for_fry_batch(batch_id: str) -> list[dict]:
    """Find which tank(s) a fry batch is in."""
    try:
        res = (_sb().table("tank_occupants")
               .select("*")
               .eq("occupant_type", "fry_batch")
               .eq("occupant_id", batch_id)
               .execute())
        return res.data or []
    except Exception as e:
        st.error(f"get_occupants_for_fry_batch failed: {e}")
        return []


def add_tank_occupant(
    tank_id: str,
    occupant_type: str,
    occupant_id: str,
    role: str = "primary",
    spawn_id: Optional[str] = None,
) -> Optional[dict]:
    """
    Add an occupant to a tank.
    Also updates the denormalized cache on tanks (occupant_fish_id/label)
    and flips status to Occupied.
    """
    try:
        record = {
            "tank_id": tank_id,
            "occupant_type": occupant_type,
            "occupant_id": occupant_id,
            "role": role,
        }
        if spawn_id:
            record["spawn_id"] = spawn_id

        res = _sb().table("tank_occupants").insert(record).execute()
        new_row = (res.data or [None])[0]

        # Refresh cache + status
        _refresh_tank_cache(tank_id)

        return new_row
    except Exception as e:
        st.error(f"add_tank_occupant failed: {e}")
        return None


def remove_tank_occupant(tank_id: str, occupant_type: str, occupant_id: str) -> bool:
    """Remove an occupant from a tank."""
    try:
        (_sb().table("tank_occupants")
         .delete()
         .eq("tank_id", tank_id)
         .eq("occupant_type", occupant_type)
         .eq("occupant_id", occupant_id)
         .execute())

        # Refresh cache + status
        _refresh_tank_cache(tank_id)
        return True
    except Exception as e:
        st.error(f"remove_tank_occupant failed: {e}")
        return False


def _refresh_tank_cache(tank_id: str) -> None:
    """
    Recompute occupant_fish_id / occupant_label / status for a tank
    based on current tank_occupants rows.
    """
    try:
        occupants = get_tank_occupants(tank_id)

        primary_fish_id = None
        primary_label = None
        status = "Empty / Idle"

        if occupants:
            status = "Occupied"
            # Pick the primary fish (role='primary' or first fish)
            for occ in occupants:
                if occ.get("occupant_type") == "fish":
                    if occ.get("role") == "primary" or primary_fish_id is None:
                        primary_fish_id = occ["occupant_id"]
                        break

            if primary_fish_id:
                fish = get_fish_by_id(primary_fish_id)
                if fish:
                    primary_label = (
                        f"{fish.get('system_id')} | "
                        f"{fish.get('gender') or ''} | "
                        f"{fish.get('variety') or ''}"
                    ).strip(" |")
            else:
                # Only fry batches — use first batch label
                for occ in occupants:
                    if occ.get("occupant_type") == "fry_batch":
                        primary_label = f"Fry batch ({occ['occupant_id'][:8]})"
                        break

        # Preserve reservation status if Reserved
        current = get_tank_by_id(tank_id)
        if current and current.get("status") == "Reserved" and not occupants:
            status = "Reserved"

        update_tank(tank_id, {
            "occupant_fish_id": primary_fish_id,
            "occupant_label": primary_label,
            "status": status,
        })
    except Exception as e:
        st.error(f"_refresh_tank_cache failed: {e}")


def transfer_occupant(
    fish_id: str,
    from_tank_id: Optional[str],
    to_tank_id: str,
    role: str = "primary",
) -> bool:
    """
    Move a fish from one tank to another.
    Removes from old, adds to new, mirrors fish.location + tank_id.
    """
    try:
        # Remove from old
        if from_tank_id:
            remove_tank_occupant(from_tank_id, "fish", fish_id)

        # Add to new
        add_tank_occupant(to_tank_id, "fish", fish_id, role=role)

        # Mirror to fish
        new_tank = get_tank_by_id(to_tank_id)
        loc = new_tank.get("location_code") if new_tank else None
        update_fish(fish_id, {"tank_id": to_tank_id, "location": loc})
        return True
    except Exception as e:
        st.error(f"transfer_occupant failed: {e}")
        return False


# ============================================================
# TANK RESERVATIONS (Session 26H.7)
# ============================================================

def reserve_tank(
    tank_id: str,
    reason: str,
    reserved_for: Optional[str] = None,
    reserved_until: Optional[str] = None,
    reserved_ref_id: Optional[str] = None,
) -> bool:
    """
    Set a reservation on a tank.
    Cannot reserve a tank that already has occupants.
    """
    try:
        tank = get_tank_by_id(tank_id)
        if not tank:
            return False

        occupants = get_tank_occupants(tank_id)
        if occupants:
            st.error(f"Cannot reserve — tank has {len(occupants)} occupant(s).")
            return False

        updates = {
            "status": "Reserved",
            "reserved_for": reserved_for,
            "reserved_reason": reason,
            "reserved_until": reserved_until,
            "reserved_ref_id": reserved_ref_id,
        }
        return update_tank(tank_id, updates)
    except Exception as e:
        st.error(f"reserve_tank failed: {e}")
        return False


def cancel_reservation(tank_id: str) -> bool:
    """Clear reservation and flip to Empty / Idle."""
    try:
        return update_tank(tank_id, {
            "status": "Empty / Idle",
            "reserved_for": None,
            "reserved_reason": None,
            "reserved_until": None,
            "reserved_ref_id": None,
        })
    except Exception as e:
        st.error(f"cancel_reservation failed: {e}")
        return False


def move_reservation(from_tank_id: str, to_tank_id: str) -> bool:
    """Move a reservation from one tank to another."""
    try:
        src = get_tank_by_id(from_tank_id)
        if not src or src.get("status") != "Reserved":
            st.error("Source tank is not Reserved.")
            return False

        dst = get_tank_by_id(to_tank_id)
        if not dst:
            return False
        if get_tank_occupants(to_tank_id):
            st.error("Destination tank is occupied — cannot move reservation.")
            return False

        # Copy reservation fields
        update_tank(to_tank_id, {
            "status": "Reserved",
            "reserved_for": src.get("reserved_for"),
            "reserved_reason": src.get("reserved_reason"),
            "reserved_until": src.get("reserved_until"),
            "reserved_ref_id": src.get("reserved_ref_id"),
        })

        # Clear source
        cancel_reservation(from_tank_id)
        return True
    except Exception as e:
        st.error(f"move_reservation failed: {e}")
        return False


def get_expiring_reservations(days_ahead: int = 3) -> list[dict]:
    """
    Reservations whose reserved_until is within `days_ahead` days
    or already past.
    """
    try:
        today = _dt.date.today()
        cutoff = today + _dt.timedelta(days=days_ahead)

        res = (_sb().table("tanks")
               .select("*")
               .eq("status", "Reserved")
               .not_.is_("reserved_until", "null")
               .lte("reserved_until", cutoff.isoformat())
               .execute())

        return res.data or []
    except Exception as e:
        st.error(f"get_expiring_reservations failed: {e}")
        return []


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
    "initial_count", "current_count", "culled_count", "female_count",
    "died_count",
    "stage", "tank_id", "notes",
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
    """Returns { fish_id: count } for all fish that have milestones."""
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
# DASHBOARD AGGREGATES
# ============================================================

def get_dashboard_counts() -> dict:
    """Returns the KPI numbers the dashboard needs in one call."""
    try:
        fish = _sb().table("fish").select("id,is_breeder,breeder_status,status,gender").execute().data or []
        tanks = _sb().table("tanks").select("id,status").execute().data or []
        spawns = _sb().table("spawns").select("id,status").execute().data or []

        total_tanks = len(tanks)

        # Available = Empty / Idle only (Reserved excluded)
        available_tanks = sum(
            1 for t in tanks
            if (t.get("status") or "").lower() in ("empty / idle", "empty", "idle")
        )

        reserved_tanks = sum(
            1 for t in tanks
            if (t.get("status") or "").lower() == "reserved"
        )

        occupied_tanks = sum(
            1 for t in tanks
            if (t.get("status") or "").lower() == "occupied"
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
            "reserved_tanks": reserved_tanks,
            "occupied_tanks": occupied_tanks,
            "total_breeders": total_breeders,
            "male_breeders": males,
            "female_breeders": females,
            "total_spawns": len(spawns),
            "active_spawns": active_spawns,
        }
    except Exception as e:
        st.error(f"get_dashboard_counts failed: {e}")
        return {}
