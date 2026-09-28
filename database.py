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
# Session 26H.7 — Tank model redesign.
# Session 27B — Round 1: molt fields, fish_photos CRUD, compute_stage,
#               display_variety, advance_breeder_status.
#
# Session 28A (this revision):
#   • FISH_FIELDS: added birth_date
#   • compute_stage() reads birth_date (fallback: created_at)
#     so backdated fish compute the correct stage.

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
    "sire_id", "dam_id", "gender", "variety", "form_type",
    "grade", "body_shape", "form_score", "fin_checks",
    "seller", "purchase_date", "purchase_cost",
    "photo_id", "qr_id", "location", "tank_id",
    "status", "is_breeder", "breeder_status",
    "breeder_status_started_at",
    "birth_date",
    "notes",
    # molt checkpoints (Session 27A Q1)
    "variety_3mo", "variety_3mo_date",
    "variety_4mo", "variety_4mo_date",
    # color analysis (Session 26A)
    "color_primary", "color_secondary", "color_palette",
    "pattern_hint", "iridescence_level",
    # starring (Session 26H.7 Step 5)
    "is_starred", "starred_reason",
]


# ------------------------------------------------------------
# Computed stage (Session 27A Q2 / 28A backdating)
# ------------------------------------------------------------

STAGE_THRESHOLDS = {
    "fry":       (1, 45),
    "juvenile":  (45, 60),
    "sub_adult": (60, 120),
    "adult":     (120, 365),
    "senior":    (365, None),
}

STAGE_LABELS = {
    "fry":       "🥚 Fry",
    "juvenile":  "🐟 Juvenile",
    "sub_adult": "🐠 Sub-adult",
    "adult":     "🐡 Adult",
    "senior":    "🌿 Senior",
}


def _fish_age_date(fish: dict) -> Optional[_dt.date]:
    """
    Return the date to use for age/stage computation.
    Prefers birth_date (may be backdated); falls back to created_at
    for older records that predate the birth_date field.
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


def compute_stage(fish: dict) -> Optional[str]:
    """
    Return the fish's current growth stage, computed from age.

    Uses birth_date when present, else created_at (Session 28A).
    Stage boundaries (Session 27A Q2):
        fry        1–45 days
        juvenile   45–60 days
        sub_adult  60 days – 4 months (~120 days)
        adult      4 months – 1 year
        senior     1 year+
    """
    d = _fish_age_date(fish)
    if d is None:
        return None
    age_days = (_dt.date.today() - d).days

    if age_days < 45:
        return "fry"
    if age_days < 60:
        return "juvenile"
    if age_days < 120:
        return "sub_adult"
    if age_days < 365:
        return "adult"
    return "senior"


def stage_label(stage: Optional[str]) -> str:
    """Display label with emoji for a stage string."""
    if not stage:
        return "—"
    return STAGE_LABELS.get(stage, stage)


# ------------------------------------------------------------
# Display variety helper (Session 27A Q1)
# ------------------------------------------------------------

def display_variety(fish: dict) -> str:
    """
    Return the variety to show for this fish.
    Priority: variety_4mo > variety_3mo > variety (placeholder).
    """
    return (
        fish.get("variety_4mo")
        or fish.get("variety_3mo")
        or fish.get("variety")
        or "—"
    )


# ------------------------------------------------------------
# Breeder status auto-flip (Session 27A Q2)
# ------------------------------------------------------------

MALE_RECOVERY_DAYS = 4
MALE_CONDITIONING_DAYS = 10
FEMALE_RECOVERY_DAYS = 14


def advance_breeder_status(fish: dict) -> Optional[str]:
    """
    Auto-flip a fish's breeder_status if its current state has
    exceeded its duration.

    Rules (Session 27A Q2):
      MALE:
        Recovering   → after 4 days  → Conditioning
        Conditioning → after 10 days → Available
      FEMALE:
        Recovering   → after 14 days → Available

    Returns the new breeder_status if a flip happened, else None.
    Caller persists the change via update_fish.
    """
    bs = (fish.get("breeder_status") or "").strip()
    started = fish.get("breeder_status_started_at")
    if not bs or not started:
        return None

    try:
        started_dt = _dt.datetime.fromisoformat(str(started).replace("Z", ""))
    except Exception:
        return None

    elapsed_days = (_dt.datetime.now() - started_dt).days
    gender = (fish.get("gender") or "").lower()

    if bs == "Recovering":
        if gender == "male" and elapsed_days >= MALE_RECOVERY_DAYS:
            return "Conditioning"
        if gender == "female" and elapsed_days >= FEMALE_RECOVERY_DAYS:
            return "Available"
    elif bs == "Conditioning":
        if gender == "male" and elapsed_days >= MALE_CONDITIONING_DAYS:
            return "Available"

    return None


# ------------------------------------------------------------
# Fish CRUD
# ------------------------------------------------------------

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
        "breeder_status_started_at": _now_iso(),
        "status": "Active",
    })


def retire_fish(fish_id: str, reason: str = "", extra_notes: str = "") -> bool:
    """Retire a breeder — clears tank link, sets status."""
    fish = get_fish_by_id(fish_id)
    if not fish:
        return False
    tag = f"[Retired: {reason}]" if reason else "[Retired]"
    new_notes = (fish.get("notes") or "").strip()
    new_notes = f"{new_notes} | {tag} {extra_notes}".strip(" |") if new_notes else f"{tag} {extra_notes}".strip()

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
# FISH PHOTOS
# ============================================================

def get_fish_photos(fish_id: str) -> list[dict]:
    """All side photos for a fish, newest first."""
    try:
        res = (_sb().table("fish_photos")
               .select("*")
               .eq("fish_id", fish_id)
               .order("captured_at", desc=True)
               .execute())
        return res.data or []
    except Exception as e:
        st.error(f"get_fish_photos failed: {e}")
        return []


def add_fish_photo(
    fish_id: str,
    photo_id: str,
    side: Optional[str] = None,
    photo_type: str = "profile_side",
    captured_at: Optional[str] = None,
    analysis: Optional[dict] = None,
    notes: str = "",
) -> Optional[dict]:
    """Add a side photo for a fish."""
    try:
        record = {
            "fish_id": fish_id,
            "photo_id": photo_id,
            "side": side,
            "photo_type": photo_type,
            "captured_at": captured_at or _today_iso(),
            "analysis": analysis or {},
            "notes": notes,
        }
        res = _sb().table("fish_photos").insert(record).execute()
        return (res.data or [None])[0]
    except Exception as e:
        st.error(f"add_fish_photo failed: {e}")
        return None


def set_profile_photo(fish_id: str, photo_id: str) -> bool:
    """Mark a photo as the profile for a fish."""
    try:
        (_sb().table("fish_photos")
         .update({"is_profile": False})
         .eq("fish_id", fish_id)
         .execute())

        (_sb().table("fish_photos")
         .update({"is_profile": True})
         .eq("fish_id", fish_id)
         .eq("photo_id", photo_id)
         .execute())

        update_fish(fish_id, {"photo_id": photo_id})
        return True
    except Exception as e:
        st.error(f"set_profile_photo failed: {e}")
        return False


def delete_fish_photo(photo_row_id: str) -> bool:
    """Delete a fish_photos row (does NOT delete the Drive file)."""
    try:
        _sb().table("fish_photos").delete().eq("id", photo_row_id).execute()
        return True
    except Exception as e:
        st.error(f"delete_fish_photo failed: {e}")
        return False


# ============================================================
# TANKS
# ============================================================

VALID_STATUSES = [
    "Empty / Idle",
    "Reserved",
    "Occupied",
    "Cleaning / Quarantine",
    "Retired",
]

TANK_FIELDS = [
    "system_id", "tank_type", "location_code", "capacity_liters",
    "status", "purpose", "occupant_fish_id", "occupant_label",
    "photo_id", "qr_id", "notes",
    "reserved_for", "reserved_reason", "reserved_until", "reserved_ref_id",
]

RESERVATION_FIELDS = [
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
    """Raw delete — does NOT check occupants."""
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


def get_tank_stats() -> dict:
    """Dashboard-level tank counts. Available = Empty / Idle only."""
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
# TANK OCCUPANTS
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
    """Add an occupant to a tank. Auto-cancels any reservation."""
    try:
        tank = get_tank_by_id(tank_id)
        if tank and tank.get("status") == "Reserved":
            _stash_reservation_warning(tank)
            update_tank(tank_id, {
                "reserved_for": None,
                "reserved_reason": None,
                "reserved_until": None,
                "reserved_ref_id": None,
            })

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

        _refresh_tank_cache(tank_id)
        return True
    except Exception as e:
        st.error(f"remove_tank_occupant failed: {e}")
        return False


# ---------- Backward-compat wrappers ----------

def assign_occupant(
    tank_id: str,
    fish_id: Optional[str],
    label: Optional[str] = None,
) -> bool:
    """Backward-compatible occupant assignment."""
    try:
        if fish_id:
            if not label:
                fish = get_fish_by_id(fish_id)
                if fish:
                    label = (
                        f"{fish.get('system_id')} | "
                        f"{fish.get('gender') or ''} | "
                        f"{fish.get('variety') or ''}"
                    ).strip(" |")
            row = add_tank_occupant(tank_id, "fish", fish_id, role="primary")
            if row is None:
                return False
            if label:
                update_tank(tank_id, {"occupant_label": label})
            tank = get_tank_by_id(tank_id)
            loc = tank.get("location_code") if tank else None
            update_fish(fish_id, {"tank_id": tank_id, "location": loc})
            return True
        else:
            _refresh_tank_cache(tank_id)
            updates = {"status": "Occupied"}
            if label:
                updates["occupant_label"] = label
            return update_tank(tank_id, updates)
    except Exception as e:
        st.error(f"assign_occupant failed: {e}")
        return False


def clear_occupant(tank_id: str) -> bool:
    """Remove ALL occupants from a tank."""
    try:
        occupants = get_tank_occupants(tank_id)

        for occ in occupants:
            if occ.get("occupant_type") == "fish":
                update_fish(occ["occupant_id"], {"tank_id": None, "location": None})

        (_sb().table("tank_occupants")
         .delete()
         .eq("tank_id", tank_id)
         .execute())

        _refresh_tank_cache(tank_id)
        return True
    except Exception as e:
        st.error(f"clear_occupant failed: {e}")
        return False


# ---------- Internal cache refresh ----------

def _stash_reservation_warning(tank: dict) -> None:
    """Record a one-shot warning for the UI that a reservation was auto-cancelled."""
    try:
        warnings = st.session_state.setdefault("_reservation_warnings", [])
        warnings.append({
            "tank_id": tank.get("id"),
            "location_code": tank.get("location_code"),
            "reason": tank.get("reserved_reason"),
            "reserved_for": tank.get("reserved_for"),
            "until": tank.get("reserved_until"),
        })
    except Exception:
        pass


def _refresh_tank_cache(tank_id: str) -> None:
    """Recompute occupant_fish_id / occupant_label / status for a tank."""
    try:
        occupants = get_tank_occupants(tank_id)
        current = get_tank_by_id(tank_id)
        current_status = (current.get("status") if current else None) or "Empty / Idle"

        primary_fish_id = None
        primary_label = None

        if occupants:
            for occ in occupants:
                if occ.get("occupant_type") == "fish" and occ.get("role") == "primary":
                    primary_fish_id = occ["occupant_id"]
                    break

            if primary_fish_id is None:
                for occ in occupants:
                    if occ.get("occupant_type") == "fish":
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
                batch_count = sum(1 for o in occupants if o.get("occupant_type") == "fry_batch")
                if batch_count == 1:
                    primary_label = "Fry batch (1)"
                elif batch_count > 1:
                    primary_label = f"Fry batches ({batch_count})"

            if current_status == "Cleaning / Quarantine":
                status = "Cleaning / Quarantine"
            else:
                status = "Occupied"
        else:
            if current_status in ("Reserved", "Cleaning / Quarantine", "Retired"):
                status = current_status
            else:
                status = "Empty / Idle"

        update_tank(tank_id, {
            "occupant_fish_id": primary_fish_id,
            "occupant_label": primary_label,
            "status": status,
        })
    except Exception as e:
        st.error(f"_refresh_tank_cache failed: {e}")


# ---------- Transfer ----------

def transfer_occupant(
    fish_id: str,
    from_tank_id: Optional[str],
    to_tank_id: str,
    role: str = "primary",
    occupant_type: str = "fish",
) -> bool:
    """Move an occupant (fish OR fry batch) from one tank to another."""
    try:
        if from_tank_id:
            remove_tank_occupant(from_tank_id, occupant_type, fish_id)

        add_tank_occupant(to_tank_id, occupant_type, fish_id, role=role)

        if occupant_type == "fish":
            new_tank = get_tank_by_id(to_tank_id)
            loc = new_tank.get("location_code") if new_tank else None
            update_fish(fish_id, {"tank_id": to_tank_id, "location": loc})
        return True
    except Exception as e:
        st.error(f"transfer_occupant failed: {e}")
        return False


# ---------- Safe delete ----------

def delete_tank_safely_impl(
    tank_id: str,
    transfers: Optional[dict] = None,
) -> tuple[bool, str]:
    """Delete a tank only if it has no occupants, OR if transfers map is complete."""
    try:
        tank = get_tank_by_id(tank_id)
        if not tank:
            return False, "Tank not found."

        occupants = get_tank_occupants(tank_id)

        if occupants:
            transfers = transfers or {}
            missing = []
            for occ in occupants:
                key = (occ["occupant_type"], occ["occupant_id"])
                if key not in transfers or not transfers[key]:
                    missing.append(occ)

            if missing:
                return False, (
                    f"Tank has {len(occupants)} occupant(s); "
                    f"{len(missing)} have no transfer destination."
                )

            for occ in occupants:
                key = (occ["occupant_type"], occ["occupant_id"])
                dest = transfers[key]
                transfer_occupant(
                    fish_id=occ["occupant_id"],
                    from_tank_id=tank_id,
                    to_tank_id=dest,
                    role=occ.get("role") or "primary",
                    occupant_type=occ["occupant_type"],
                )

        return (delete_tank(tank_id), "Tank deleted.")
    except Exception as e:
        st.error(f"delete_tank_safely_impl failed: {e}")
        return False, str(e)


# ============================================================
# TANK RESERVATIONS
# ============================================================

def reserve_tank(
    tank_id: str,
    reason: str,
    reserved_for: Optional[str] = None,
    reserved_until: Optional[str] = None,
    reserved_ref_id: Optional[str] = None,
) -> bool:
    """Set a reservation on a tank. Cannot reserve a tank with occupants."""
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

        update_tank(to_tank_id, {
            "status": "Reserved",
            "reserved_for": src.get("reserved_for"),
            "reserved_reason": src.get("reserved_reason"),
            "reserved_until": src.get("reserved_until"),
            "reserved_ref_id": src.get("reserved_ref_id"),
        })

        cancel_reservation(from_tank_id)
        return True
    except Exception as e:
        st.error(f"move_reservation failed: {e}")
        return False


def get_expiring_reservations(days_ahead: int = 3) -> list[dict]:
    """Reservations whose reserved_until is within days_ahead days or already past."""
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
# TAPE-CODE REGENERATION
# ============================================================

def regenerate_tape_code(
    tank_id: str,
    new_purpose: str,
) -> Optional[tuple[str, str]]:
    """Regenerate a tank's tape code after a purpose change."""
    try:
        from modules.id_generator import generate_tape_code

        tank = get_tank_by_id(tank_id)
        if not tank:
            return None

        old_code = tank.get("location_code") or "?"
        new_code = generate_tape_code(new_purpose)

        ok = update_tank(tank_id, {
            "location_code": new_code,
            "purpose": new_purpose,
        })
        if not ok:
            return None

        for occ in get_tank_occupants(tank_id):
            if occ.get("occupant_type") == "fish":
                update_fish(occ["occupant_id"], {"location": new_code})

        return (old_code, new_code)
    except Exception as e:
        st.error(f"regenerate_tape_code failed: {e}")
        return None


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
        res = _sb
