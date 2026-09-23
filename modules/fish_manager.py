# modules/fish_manager.py
# Betta Farm Management System
# Session 6 — Fish + Breeder unified. Uses Supabase via database.py.
# Session 9 — Added list_breeders() and register_breeder() for breeder_view.
# breeder_registry.py is retired; all breeder logic lives here.

from __future__ import annotations

from typing import Optional

import streamlit as st

from database import (
    get_all_fish,
    get_fish_by_id,
    get_fish_by_system_id,
    create_fish,
    update_fish,
    delete_fish,
    promote_fish_to_breeder,
    retire_fish,
    get_available_breeders,
    get_all_tanks,
    get_all_spawns,
    log_activity,
)
from modules.id_generator import generate_fish_id, generate_batch_fish_id
from modules.photo_service import upload_photo, delete_drive_file, photo_url


# ============================================================
# VALID VALUES (used by UI dropdowns and validation)
# ============================================================

VALID_GENDERS = ["Male", "Female", "Unsexed"]

VALID_GRADES = [
    "Show Grade",
    "High Grade",
    "Breeder Grade",
    "Material Grade",
    "Pet Grade",
]

VALID_STAGES = [
    "egg", "fry", "free_swimming", "jarred",
    "juvenile", "sub_adult", "adult", "breeder", "retired",
]

VALID_STATUSES = [
    "Active", "Jarred", "For Sale", "Sold",
    "Deceased", "Retired", "Conditioning",
]

VALID_BREEDER_STATUSES = [
    "Available", "Conditioning", "Ready",
    "In Pairing", "Retired", "Inactive",
]

VALID_ORIGINS = ["Purchased", "Batch Spawn"]


# ============================================================
# READ
# ============================================================

def list_all_fish() -> list[dict]:
    """All fish, newest first."""
    return get_all_fish()


def list_fish_by_status(status: str) -> list[dict]:
    return [f for f in get_all_fish() if (f.get("status") or "") == status]


def list_fish_by_location(location_code: str) -> list[dict]:
    return [f for f in get_all_fish() if (f.get("location") or "") == location_code]


def find_fish(identifier: str) -> Optional[dict]:
    """
    Look up a fish by uuid (id) OR human-readable system_id.
    """
    if not identifier:
        return None
    fish = get_fish_by_system_id(identifier)
    if fish:
        return fish
    return get_fish_by_id(identifier)


def get_fish_dropdown_items() -> list[dict]:
    """
    Lightweight list for dropdowns. Excludes Deceased / Sold / Retired.
    """
    out = []
    for f in get_all_fish():
        status = (f.get("status") or "").lower()
        if status in ("deceased", "sold", "retired"):
            continue
        out.append({
            "id": f["id"],
            "system_id": f.get("system_id"),
            "label": _fish_label(f),
        })
    return out


def _fish_label(f: dict) -> str:
    """Format: 'FISH-0042 | Male | Avatar | High Grade'"""
    parts = [f.get("system_id") or "?"]
    if f.get("gender"):    parts.append(f["gender"])
    if f.get("variety"):   parts.append(f["variety"])
    if f.get("grade"):     parts.append(f["grade"])
    return " | ".join(str(p) for p in parts)


# ============================================================
# CREATE
# ============================================================

def register_new_fish(
    *,
    origin: str = "Purchased",
    gender: str = "Unsexed",
    variety: str = "",
    strain: str = "",
    form_type: str = "",
    grade: str = "Pet Grade",
    body_shape: str = "",
    form_score: Optional[int] = None,
    fin_checks: Optional[dict] = None,
    seller: str = "",
    purchase_date: Optional[str] = None,
    purchase_cost: float = 0.0,
    location: str = "",
    notes: str = "",
    photo_file=None,
    sire_id: Optional[str] = None,
    dam_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    line_code: str = "UNK",
    generation: str = "P1",
    status: str = "Active",
) -> Optional[dict]:
    """
    Register a manually-acquired fish (purchased or unknown origin).
    Generates FISH-NNNN system_id.

    For batch-born fish use `register_fish_from_spawn()` instead.
    """
    system_id = generate_fish_id()

    photo_id = None
    if photo_file is not None:
        photo_id = upload_photo(photo_file, entity_type="fish", entity_id=system_id)

    record = {
        "system_id": system_id,
        "origin": origin,
        "gender": gender,
        "variety": variety,
        "strain": strain,
        "form_type": form_type,
        "grade": grade,
        "body_shape": body_shape,
        "form_score": form_score,
        "fin_checks": fin_checks or {},
        "seller": seller,
        "purchase_date": purchase_date,
        "purchase_cost": purchase_cost or 0,
        "location": location,
        "notes": notes,
        "photo_id": photo_id,
        "sire_id": sire_id,
        "dam_id": dam_id,
        "batch_id": batch_id,
        "line_code": line_code or "UNK",
        "generation": generation or "P1",
        "status": status,
        "is_breeder": False,
        "breeder_status": None,
    }

    saved = create_fish(record)
    if saved:
        log_activity(
            action_type="fish_registered",
            description=f"Registered {system_id} ({gender}, {variety or 'no variety'})",
            entity_type="fish",
            entity_id=saved["id"],
        )
    return saved


def register_fish_from_spawn(
    *,
    spawn_id: str,                 # spawn uuid
    gender: str,
    grade: str = "Pet Grade",
    location: str = "",
    notes: str = "",
    photo_file=None,
) -> Optional[dict]:
    """
    Register a jarred fry from a spawn. Inherits lineage:
      - sire_id, dam_id from spawn
      - line_code, generation from spawn
      - batch_id = spawn.id
      - system_id = {spawn.system_id}-NN
    """
    spawn = next((s for s in get_all_spawns() if s["id"] == spawn_id), None)
    if not spawn:
        st.error(f"Spawn {spawn_id} not found.")
        return None

    spawn_sys = spawn.get("system_id") or "SPN-UNK-P1-01"
    system_id = generate_batch_fish_id(spawn_sys)

    photo_id = None
    if photo_file is not None:
        photo_id = upload_photo(photo_file, entity_type="fish", entity_id=system_id)

    variety = ""
    sire = get_fish_by_id(spawn.get("male_id"))
    if sire:
        variety = sire.get("variety") or ""

    record = {
        "system_id": system_id,
        "origin": "Batch Spawn",
        "gender": gender,
        "variety": variety,
        "grade": grade,
        "location": location,
        "notes": f"Jarred from {spawn_sys}. {notes}".strip(),
        "photo_id": photo_id,
        "sire_id": spawn.get("male_id"),
        "dam_id": spawn.get("female_id"),
        "batch_id": spawn["id"],
        "line_code": spawn.get("line_code") or "UNK",
        "generation": spawn.get("generation") or "F1",
        "status": "Jarred",
        "is_breeder": False,
        "breeder_status": None,
    }

    saved = create_fish(record)
    if saved:
        log_activity(
            action_type="fish_registered",
            description=f"Jarred {system_id} from {spawn_sys}",
            entity_type="fish",
            entity_id=saved["id"],
        )
    return saved


# ============================================================
# UPDATE
# ============================================================

def edit_fish(fish_id: str, updates: dict) -> bool:
    """
    Update any allowed fields. If a `photo_file` is passed in updates,
    uploads it and replaces photo_id (deletes old Drive file).
    """
    photo_file = updates.pop("photo_file", None)
    if photo_file is not None:
        fish = get_fish_by_id(fish_id)
        old_id = fish.get("photo_id") if fish else None
        new_id = upload_photo(photo_file, entity_type="fish", entity_id=fish_id)
        if new_id:
            updates["photo_id"] = new_id
            if old_id:
                delete_drive_file(old_id)

    ok = update_fish(fish_id, updates)
    if ok:
        log_activity(
            action_type="fish_updated",
            description=f"Updated fields: {', '.join(updates.keys())}",
            entity_type="fish",
            entity_id=fish_id,
        )
    return ok


def change_location(fish_id: str, new_location: str) -> bool:
    """Move a fish to a new tank/jar (tape code). Updates both fish and old tank."""
    fish = get_fish_by_id(fish_id)
    if not fish:
        return False

    old_loc = fish.get("location")
    if old_loc:
        for t in get_all_tanks():
            if t.get("location_code") == old_loc and t.get("occupant_fish_id") == fish_id:
                from database import clear_occupant
                clear_occupant(t["id"])
                break

    if new_location:
        for t in get_all_tanks():
            if t.get("location_code") == new_location:
                from database import assign_occupant
                assign_occupant(t["id"], fish_id, _fish_label(fish))
                break

    return update_fish(fish_id, {"location": new_location})


def delete_fish_and_photos(fish_id: str) -> bool:
    """Delete a fish and its Drive photo."""
    fish = get_fish_by_id(fish_id)
    if not fish:
        return False

    for t in get_all_tanks():
        if t.get("occupant_fish_id") == fish_id:
            from database import clear_occupant
            clear_occupant(t["id"])

    for f_id in (fish.get("photo_id"), fish.get("qr_id")):
        if f_id:
            delete_drive_file(f_id)

    ok = delete_fish(fish_id)
    if ok:
        log_activity(
            action_type="fish_deleted",
            description=f"Deleted {fish.get('system_id')}",
            entity_type="fish",
        )
    return ok


# ============================================================
# BREEDER BEHAVIOR
# ============================================================

def list_breeders(include_retired: bool = False) -> list[dict]:
    """
    Return all fish marked as breeders.
    By default excludes Retired / Inactive breeder_status.
    Used by breeder_view and any breeder inventory UI.
    """
    out = []
    for f in get_all_fish():
        if not f.get("is_breeder"):
            continue
        bs = (f.get("breeder_status") or "").strip().lower()
        if not include_retired and bs in ("retired", "inactive"):
            continue
        out.append(f)
    return out


def register_breeder(
    *,
    sex: str,
    variety: str,
    lineage: str = "",
    dob: Optional[str] = None,
    photo_file=None,
    notes: str = "",
    grade: str = "Pet Grade",
    body_shape: str = "",
    fin_checks: Optional[dict] = None,
) -> Optional[dict]:
    """
    Convenience wrapper: register a new fish AND immediately promote to breeder.
    Used by breeder_view's Register Breeder form.

    `lineage` becomes line_code (sanitized, upper-cased).
    `dob` is stored in purchase_date (schema has no separate dob column).
    """
    from modules.id_generator import _sanitize

    line_code = _sanitize(lineage, max_len=16) if lineage else "UNK"

    fish = register_new_fish(
        origin="Purchased",
        gender=sex,
        variety=variety,
        form_type="HMPK",       # matches old breeder_view hardcoded prefix
        grade=grade,
        body_shape=body_shape,
        fin_checks=fin_checks or {},
        purchase_date=dob,
        notes=notes,
        photo_file=photo_file,
        line_code=line_code,
        generation="P1",
        status="Conditioning",
    )
    if not fish:
        return None

    promote_to_breeder(fish["id"], breeder_status="Available")
    return get_fish_by_id(fish["id"])


def promote_to_breeder(fish_id: str, breeder_status: str = "Available") -> bool:
    """
    Promote a fish to breeder. Fish keeps its system_id.
    Fish status becomes 'Conditioning'.
    """
    ok = promote_fish_to_breeder(fish_id, breeder_status)
    if ok:
        fish = get_fish_by_id(fish_id)
        log_activity(
            action_type="fish_promoted",
            description=f"Promoted {fish.get('system_id')} to breeder ({breeder_status})",
            entity_type="fish",
            entity_id=fish_id,
        )
    return ok


def retire_breeder(fish_id: str, reason: str = "", notes: str = "") -> bool:
    """Retire a breeder. Frees tank, sets status=Retired, is_breeder=false."""
    fish = get_fish_by_id(fish_id)
    if not fish:
        return False
    ok = retire_fish(fish_id, reason, notes)
    if ok:
        log_activity(
            action_type="breeder_retired",
            description=f"Retired {fish.get('system_id')} — {reason or 'no reason given'}",
            entity_type="fish",
            entity_id=fish_id,
        )
    return ok


def list_available_breeders(gender: Optional[str] = None) -> list[dict]:
    """
    Available breeders, optionally filtered by gender. Returns fish rows.
    """
    breeders = get_available_breeders()
    if gender:
        g = gender.strip().lower()
        breeders = [b for b in breeders if (b.get("gender") or "").lower() == g]
    return breeders


def get_breeder_pairs_data() -> tuple[list[dict], list[dict]]:
    """
    Returns (males, females) as dropdown items for pairing UI.
    Each item: {'id': uuid, 'system_id': 'FISH-0042', 'label': '...'}
    """
    males, females = [], []
    for b in get_available_breeders():
        item = {
            "id": b["id"],
            "system_id": b.get("system_id"),
            "label": _fish_label(b),
        }
        g = (b.get("gender") or "").lower()
        if g == "male":
            males.append(item)
        elif g == "female":
            females.append(item)
    return males, females


def get_breeder_stats() -> dict:
    """Counts for dashboard."""
    all_fish = get_all_fish()
    breeders = [f for f in all_fish if f.get("is_breeder")]
    return {
        "total_fish": len(all_fish),
        "total_breeders": len(breeders),
        "males": sum(1 for b in breeders if (b.get("gender") or "").lower() == "male"),
        "females": sum(1 for b in breeders if (b.get("gender") or "").lower() == "female"),
        "available": sum(1 for b in breeders if b.get("breeder_status") == "Available"),
        "in_pairing": sum(1 for b in breeders if b.get("breeder_status") == "In Pairing"),
        "conditioning": sum(1 for b in breeders if b.get("breeder_status") == "Conditioning"),
    }


def sync_breeder_status(fish_id: str, new_status: str) -> bool:
    """
    Called by spawn_manager when a pairing starts/ends.
    Updates only breeder_status (not overall fish status).
    """
    return update_fish(fish_id, {"breeder_status": new_status})


# ============================================================
# LINEAGE HELPERS (used by Session 17 lineage tree)
# ============================================================

def get_parents(fish_id: str) -> tuple[Optional[dict], Optional[dict]]:
    """Return (sire, dam) for a fish."""
    fish = get_fish_by_id(fish_id)
    if not fish:
        return None, None
    sire = get_fish_by_id(fish["sire_id"]) if fish.get("sire_id") else None
    dam  = get_fish_by_id(fish["dam_id"])  if fish.get("dam_id")  else None
    return sire, dam


def get_spawn_for_fish(fish_id: str) -> Optional[dict]:
    """Return the spawn this fish was born from, if any."""
    fish = get_fish_by_id(fish_id)
    if not fish or not fish.get("batch_id"):
        return None
    return next((s for s in get_all_spawns() if s["id"] == fish["batch_id"]), None)
