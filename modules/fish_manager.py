# modules/fish_manager.py
# Betta Farm Management System
# Session 6  — Fish + Breeder unified. Uses Supabase via database.py.
# Session 9  — Added list_breeders() and register_breeder() for breeder_view.
# Session 22 — Added cull_fish() and restore_fish_from_culled().
# Session 23 — Added get_fish_age_days() and grade color helper.
# Session 26H.7 — Step 7: change_location uses new tank API.
# Session 27B — Round 1: 6-status list, Recovering, process_breeder_transitions.
#
# Session 28A (this revision):
#   • get_fish_age_days() prefers birth_date (fallback: created_at)
#   • register_new_fish() accepts optional birth_date
#   • register_fish_from_spawn() accepts optional birth_date
#     (falls back to spawn's free_swimming_date)
#   • sync_breeder_status() accepts optional timestamp for backdating

from __future__ import annotations

import datetime as _dt
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
    # Session 27B helpers
    compute_stage,
    stage_label,
    display_variety,
    advance_breeder_status,
)
from modules.id_generator import generate_fish_id
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

VALID_STATUSES = [
    "Active",
    "For Sale",
    "Sold",
    "Deceased",
    "Culled",
    "Retired",
]

VALID_BREEDER_STATUSES = [
    "Available",
    "Conditioning",
    "Recovering",
    "Ready",
    "In Pairing",
    "Retired",
    "Inactive",
]

VALID_ORIGINS = ["Purchased", "Batch Spawn"]

CULL_REASONS = [
    "Deformity",
    "Poor form",
    "Weak color",
    "Sickly / Unhealthy",
    "Aggressive behavior",
    "Wrong sex (revealed later)",
    "Stunted growth",
    "Other",
]


# ============================================================
# DISPLAY HELPERS
# ============================================================

def grade_badge_color(grade: Optional[str]) -> str:
    """Return a hex color for a grade badge."""
    g = (grade or "").strip().lower()
    if "show" in g:
        return "#FFD700"
    if "high" in g:
        return "#C0C0C0"
    if "breeder" in g:
        return "#CD7F32"
    if "material" in g:
        return "#9CA3AF"
    if "pet" in g:
        return "#E5E7EB"
    return "#E5E7EB"


def grade_badge_text_color(grade: Optional[str]) -> str:
    """Text color that contrasts well with the badge background."""
    g = (grade or "").strip().lower()
    if "show" in g:
        return "#4A3800"
    if "high" in g:
        return "#333333"
    if "breeder" in g:
        return "#FFFFFF"
    return "#1F2937"


def _age_date(fish: dict) -> Optional[_dt.date]:
    """
    Return the date to use for age computation.
    Prefers birth_date (may be backdated); falls back to created_at.
    """
    birth = fish.get("birth_date")
    if birth:
        try:
            return _dt.date.fromisoformat(str(birth)[:10])
        except Exception:
            pass
    created = fish.get("created_at")
    if created:
        try:
            return _dt.date.fromisoformat(str(created)[:10])
        except Exception:
            pass
    return None


def get_fish_age_days(fish: dict) -> Optional[int]:
    """
    Days since the fish's birth date.
    Session 28A — prefers birth_date; falls back to created_at.
    """
    d = _age_date(fish)
    if d is None:
        return None
    return (_dt.date.today() - d).days


def format_fish_age(days: Optional[int]) -> str:
    """Humanize age for the tile badge."""
    if days is None:
        return "—"
    if days < 30:
        return f"{days}d"
    if days < 365:
        return f"{days // 30}mo"
    return f"{days // 365}y"


def stage_of(fish: dict) -> Optional[str]:
    """Return the computed growth stage for a fish."""
    return compute_stage(fish)


def variety_of(fish: dict) -> str:
    """Return the variety to display (variety_4mo > variety_3mo > variety)."""
    return display_variety(fish)


# ============================================================
# BREEDER STATUS AUTO-FLIP
# ============================================================

def process_breeder_transitions() -> int:
    """
    Walk every fish with a breeder_status and auto-flip any that
    have exceeded their duration. Call once per app load.
    Returns: number of fish flipped.
    """
    flipped = 0
    try:
        for fish in get_all_fish():
            if not fish.get("breeder_status"):
                continue
            new_status = advance_breeder_status(fish)
            if new_status and new_status != fish.get("breeder_status"):
                update_fish(fish["id"], {
                    "breeder_status": new_status,
                    "breeder_status_started_at": _dt.datetime.now().isoformat(timespec="seconds"),
                })
                log_activity(
                    action_type="breeder_status_auto_flip",
                    description=(
                        f"{fish.get('system_id')} auto-flipped "
                        f"{fish.get('breeder_status')} → {new_status}"
                    ),
                    entity_type="fish",
                    entity_id=fish["id"],
                )
                flipped += 1
    except Exception as e:
        st.warning(f"process_breeder_transitions issue: {e}")
    return flipped


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
    """Look up a fish by uuid (id) OR human-readable system_id."""
    if not identifier:
        return None
    fish = get_fish_by_system_id(identifier)
    if fish:
        return fish
    return get_fish_by_id(identifier)


def get_fish_dropdown_items() -> list[dict]:
    """Lightweight list for dropdowns. Excludes Deceased / Sold / Retired / Culled."""
    out = []
    for f in get_all_fish():
        status = (f.get("status") or "").lower()
        if status in ("deceased", "sold", "retired", "culled"):
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
    variety = display_variety(f)
    if variety and variety != "—":
        parts.append(variety)
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
    birth_date: Optional[str] = None,
) -> Optional[dict]:
    """
    Register a manually-acquired fish (purchased or unknown origin).
    Session 28A — accepts optional birth_date (ISO string 'YYYY-MM-DD').
    If omitted, age falls back to created_at.
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
        "birth_date": birth_date,
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
    spawn_id: str,
    gender: str,
    grade: str = "Pet Grade",
    location: str = "",
    notes: str = "",
    photo_file=None,
    birth_date: Optional[str] = None,
) -> Optional[dict]:
    """
    Register a jarred fry from a spawn. Inherits lineage.
    Session 28A — accepts optional birth_date; falls back to the
    spawn's free_swimming_date so backdated spawns produce
    correctly-aged fry.
    """
    spawn = next((s for s in get_all_spawns() if s["id"] == spawn_id), None)
    if not spawn:
        st.error(f"Spawn {spawn_id} not found.")
        return None

    spawn_sys = spawn.get("system_id") or "SPN-UNK-P1-01"
    system_id = generate_fish_id()

    # Resolve birth_date: explicit → spawn's free_swimming_date → None
    resolved_birth_date = birth_date or spawn.get("free_swimming_date")

    photo_id = None
    if photo_file is not None:
        photo_id = upload_photo(photo_file, entity_type="fish", entity_id=system_id)

    variety = ""
    sire = get_fish_by_id(spawn.get("male_id"))
    if sire:
        variety = display_variety(sire) or ""

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
        "status": "Active",
        "is_breeder": False,
        "breeder_status": None,
        "birth_date": resolved_birth_date,
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
    """Move a fish to a new tank (by tape code). Uses tank_occupants."""
    fish = get_fish_by_id(fish_id)
    if not fish:
        return False

    from database import get_occupants_for_fish
    from modules.tank_registry import (
        add_occupant_to_tank,
        remove_occupant,
        find_tank,
    )

    try:
        for occ in get_occupants_for_fish(fish_id):
            remove_occupant(occ["tank_id"], "fish", fish_id)
    except Exception as e:
        st.warning(f"Could not clear previous tank occupants: {e}")

    if new_location:
        tank = find_tank(new_location)
        if tank:
            add_occupant_to_tank(tank["id"], "fish", fish_id, role="primary")
        else:
            st.warning(f"No tank found with tape code '{new_location}'. Fish location field updated anyway.")

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
# CULLING
# ============================================================

def cull_fish(fish_id: str, reason: str = "", notes: str = "") -> bool:
    """Mark a fish as culled. Clears tank link, sets status='Culled'."""
    fish = get_fish_by_id(fish_id)
    if not fish:
        return False

    tag = f"[Culled: {reason}]" if reason else "[Culled]"
    existing_notes = (fish.get("notes") or "").strip()
    new_notes = (
        f"{existing_notes} | {tag} {notes}".strip(" |")
        if existing_notes
        else f"{tag} {notes}".strip()
    )

    if fish.get("tank_id"):
        from database import clear_occupant
        clear_occupant(fish["tank_id"])

    ok = update_fish(fish_id, {
        "status": "Culled",
        "notes": new_notes,
        "location": None,
        "tank_id": None,
    })
    if ok:
        log_activity(
            action_type="fish_culled",
            description=(
                f"Culled {fish.get('system_id')}"
                + (f" — {reason}" if reason else "")
            ),
            entity_type="fish",
            entity_id=fish_id,
        )
    return ok


def restore_fish_from_culled(fish_id: str, new_status: str = "Active") -> bool:
    """Undo a cull — useful if you culled by mistake."""
    fish = get_fish_by_id(fish_id)
    if not fish:
        return False

    existing_notes = (fish.get("notes") or "").strip()
    new_notes = (
        f"{existing_notes} | [Restored from culled]".strip(" |")
        if existing_notes
        else "[Restored from culled]"
    )

    ok = update_fish(fish_id, {
        "status": new_status,
        "notes": new_notes,
    })
    if ok:
        log_activity(
            action_type="fish_restored",
            description=f"Restored {fish.get('system_id')} from culled",
            entity_type="fish",
            entity_id=fish_id,
        )
    return ok


# ============================================================
# BREEDER BEHAVIOR
# ============================================================

def list_breeders(include_retired: bool = False) -> list[dict]:
    """Return all fish marked as breeders."""
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
    Convenience wrapper: register a new fish AND immediately promote
    to breeder.
    """
    from modules.id_generator import _sanitize

    line_code = _sanitize(lineage, max_len=16) if lineage else "UNK"

    fish = register_new_fish(
        origin="Purchased",
        gender=sex,
        variety=variety,
        form_type="HMPK",
        grade=grade,
        body_shape=body_shape,
        fin_checks=fin_checks or {},
        purchase_date=dob,
        notes=notes,
        photo_file=photo_file,
        line_code=line_code,
        generation="P1",
        status="Active",
    )
    if not fish:
        return None

    promote_to_breeder(fish["id"], breeder_status="Conditioning")
    return get_fish_by_id(fish["id"])


def promote_to_breeder(fish_id: str, breeder_status: str = "Available") -> bool:
    """Promote a fish to breeder."""
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
    """Available breeders, optionally filtered by gender."""
    breeders = get_available_breeders()
    if gender:
        g = gender.strip().lower()
        breeders = [b for b in breeders if (b.get("gender") or "").lower() == g]
    return breeders


def get_breeder_pairs_data() -> tuple[list[dict], list[dict]]:
    """Returns (males, females) as dropdown items for pairing UI."""
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
        "recovering": sum(1 for b in breeders if b.get("breeder_status") == "Recovering"),
    }


def sync_breeder_status(
    fish_id: str,
    new_status: str,
    timestamp: Optional[str] = None,
) -> bool:
    """
    Called by spawn_manager when a pairing starts/ends.
    Session 28A — accepts an optional timestamp so backdated
    free-swimming events correctly stamp the countdown start.

    Args:
        fish_id:    the fish uuid
        new_status: e.g. "In Pairing", "Recovering", "Available"
        timestamp:  ISO datetime string; defaults to now
    """
    return update_fish(fish_id, {
        "breeder_status": new_status,
        "breeder_status_started_at": timestamp or _dt.datetime.now().isoformat(timespec="seconds"),
    })


# ============================================================
# LINEAGE HELPERS
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
