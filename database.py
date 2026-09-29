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
# Session 28A — FISH_FIELDS: added birth_date; compute_stage() reads
#               birth_date; advance_breeder_status() normalizes timestamps.
# Session 28B — PERFORMANCE OPTIMIZATION ROUND 1: caching, batch
#               occupant fetch, cache invalidation.
# Session 30 — MILESTONE_FIELDS: added "grade".
# Session 31 — (no database.py change; Round G deferred count was
#               handled with existing nullable column).
# Session 32 (this revision) — PAIRING PLANS:
#   • New table pairing_plans (created via SQL migration).
#   • PAIRING_PLAN_FIELDS whitelist + CRUD helpers:
#     get_all_pairing_plans, get_pairing_plan_by_id,
#     create_pairing_plan, update_pairing_plan, delete_pairing_plan.
#   • "get_all_pairing_plans" added to _CACHE_NAMES.

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
# CACHE CONTROL
# ============================================================

CACHE_TTL = 45

_CACHE_NAMES = (
    "get_all_fish",
    "get_all_tanks",
    "get_all_spawns",
    "get_all_fry_batches",
    "get_all_strains",
    "get_all_tank_occupants",
    "get_milestone_counts_by_fish",
    "get_all_pairing_plans",
)


def _bust_cache(name: str) -> None:
    """Clear a single cached read function. Safe if cache not populated."""
    try:
        fn = globals().get(name)
        if fn is not None and hasattr(fn, "clear"):
            fn.clear()
    except Exception:
        pass


def invalidate_all_caches() -> None:
    """Clear every cached read function. Called after writes."""
    for name in _CACHE_NAMES:
        _bust_cache(name)


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
    "variety_3mo", "variety_3mo_date",
    "variety_4mo", "variety_4mo_date",
    "color_primary", "color_secondary", "color_palette",
    "pattern_hint", "iridescence_level",
    "is_starred", "starred_reason",
]


# ------------------------------------------------------------
# Computed stage
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
    """Return the date to use for age/stage computation."""
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
    """Return the fish's current growth stage, computed from age."""
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
# Display variety helper
# ------------------------------------------------------------

def display_variety(fish: dict) -> str:
    """Priority: variety_4mo > variety_3mo > variety."""
    return (
        fish.get("variety_4mo")
        or fish.get("variety_3mo")
        or fish.get("variety")
        or "—"
    )


# ------------------------------------------------------------
# Breeder status auto-flip
# ------------------------------------------------------------

MALE_RECOVERY_DAYS = 4
MALE_CONDITIONING_DAYS = 10
FEMALE_RECOVERY_DAYS = 14


def advance_breeder_status(fish: dict) -> Optional[str]:
    """Auto-flip a fish's breeder_status if its duration has expired."""
    bs = (fish.get("breeder_status") or "").strip()
    started = fish.get("breeder_status_started_at")
    if not bs or not started:
        return None

    try:
        started_dt = _dt.datetime.fromisoformat(str(started).replace("Z", ""))
    except Exception:
        return None

    if started_dt.tzinfo is None:
        started_dt = started_dt.replace(tzinfo=_dt.timezone.utc)
    now_dt = _dt.datetime.now(_dt.timezone.utc)

    elapsed_days = (now_dt - started_dt).days
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

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_all_fish() -> list[dict]:
    """Return every fish row, newest first."""
    try:
        res = _sb().table("fish").select("*").order("created_at", desc=True).execute()
        return res.data or []
    except Exception as e:
        st.error(f"get_all_fish failed: {e}")
        return []


def get_fish_by_id(fish_id: str) -> Optional[dict]:
    try:
        res = _sb().table("fish").select("*").eq("id", fish_id).limit(1).execute()
        return (res.data or [None])[0]
    except Exception as e:
        st.error(f"get_fish_by_id failed: {e}")
        return None


def get_fish_by_system_id(system_id: str) -> Optional[dict]:
    try:
        res = _sb().table("fish").select("*").eq("system_id", system_id).limit(1).execute()
        return (res.data or [None])[0]
    except Exception as e:
        st.error(f"get_fish_by_system_id failed: {e}")
        return None


def create_fish(data: dict) -> Optional[dict]:
    payload = {k: data.get(k) for k in FISH_FIELDS if k in data}
    try:
        res = _sb().table("fish").insert(payload).execute()
        invalidate_all_caches()
        return (res.data or [None])[0]
    except Exception as e:
        st.error(f"create_fish failed: {e}")
        return None


def update_fish(fish_id: str, updates: dict) -> bool:
    payload = {k: v for k, v in updates.items() if k in FISH_FIELDS}
    if not payload:
        return False
    try:
        _sb().table("fish").update(payload).eq("id", fish_id).execute()
        invalidate_all_caches()
        return True
    except Exception as e:
        st.error(f"update_fish failed: {e}")
        return False


def delete_fish(fish_id: str) -> bool:
    try:
        _sb().table("fish").delete().eq("id", fish_id).execute()
        invalidate_all_caches()
        return True
    except Exception as e:
        st.error(f"delete_fish failed: {e}")
        return False


def promote_fish_to_breeder(fish_id: str, breeder_status: str = "Available") -> bool:
    return update_fish(fish_id, {
        "is_breeder": True,
        "breeder_status": breeder_status,
        "breeder_status_started_at": _now_iso(),
        "status": "Active",
    })


def retire_fish(fish_id: str, reason: str = "", extra_notes: str = "") -> bool:
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


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
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
        invalidate_all_caches()
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
        invalidate_all_caches()
        return True
    except Exception as e:
        st.error(f"update_tank failed: {e}")
        return False


def delete_tank(tank_id: str) -> bool:
    try:
        _sb().table("tanks").delete().eq("id", tank_id).execute()
        invalidate_all_caches()
        return True
    except Exception as e:
        st.error(f"delete_tank failed: {e}")
        return False


def get_next_tank_sequence() -> str:
    try:
        res = _sb().table("tanks").select("system_id").execute()
        nums = [int(r["system_id"]) for r in (res.data or []) if str(r.get("system_id", "")).isdigit()]
        return str((max(nums) + 1) if nums else 1)
    except Exception as e:
        st.error(f"get_next_tank_sequence failed: {e}")
        return "1"


def get_tank_stats() -> dict:
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

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_all_tank_occupants() -> dict[str, list[dict]]:
    try:
        res = (_sb().table("tank_occupants")
               .select("*")
               .order("added_at")
               .execute())
        grouped: dict[str, list[dict]] = {}
        for row in (res.data or []):
            tid = row.get("tank_id")
            if tid:
                grouped.setdefault(tid, []).append(row)
        return grouped
    except Exception as e:
        st.error(f"get_all_tank_occupants failed: {e}")
        return {}


def get_all_occupants_for_fish() -> dict[str, list[dict]]:
    try:
        all_occ = get_all_tank_occupants()
        by_fish: dict[str, list[dict]] = {}
        for tid, rows in all_occ.items():
            for row in rows:
                if row.get("occupant_type") == "fish":
                    fid = row.get("occupant_id")
                    if fid:
                        by_fish.setdefault(fid, []).append(row)
        return by_fish
    except Exception as e:
        st.error(f"get_all_occupants_for_fish failed: {e}")
        return {}


def get_tank_occupants(tank_id: str) -> list[dict]:
    try:
        batch = get_all_tank_occupants()
        if batch:
            return batch.get(tank_id, [])
    except Exception:
        pass
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

        invalidate_all_caches()
        _refresh_tank_cache(tank_id)
        return new_row
    except Exception as e:
        st.error(f"add_tank_occupant failed: {e}")
        return None


def remove_tank_occupant(tank_id: str, occupant_type: str, occupant_id: str) -> bool:
    try:
        (_sb().table("tank_occupants")
         .delete()
         .eq("tank_id", tank_id)
         .eq("occupant_type", occupant_type)
         .eq("occupant_id", occupant_id)
         .execute())

        invalidate_all_caches()
        _refresh_tank_cache(tank_id)
        return True
    except Exception as e:
        st.error(f"remove_tank_occupant failed: {e}")
        return False


def assign_occupant(
    tank_id: str,
    fish_id: Optional[str],
    label: Optional[str] = None,
) -> bool:
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
    try:
        occupants = get_tank_occupants(tank_id)

        for occ in occupants:
            if occ.get("occupant_type") == "fish":
                update_fish(occ["occupant_id"], {"tank_id": None, "location": None})

        (_sb().table("tank_occupants")
         .delete()
         .eq("tank_id", tank_id)
         .execute())

        invalidate_all_caches()
        _refresh_tank_cache(tank_id)
        return True
    except Exception as e:
        st.error(f"clear_occupant failed: {e}")
        return False


def _stash_reservation_warning(tank: dict) -> None:
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


def transfer_occupant(
    fish_id: str,
    from_tank_id: Optional[str],
    to_tank_id: str,
    role: str = "primary",
    occupant_type: str = "fish",
) -> bool:
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


def delete_tank_safely_impl(
    tank_id: str,
    transfers: Optional[dict] = None,
) -> tuple[bool, str]:
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


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
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
        invalidate_all_caches()
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
        invalidate_all_caches()
        return True
    except Exception as e:
        st.error(f"update_spawn failed: {e}")
        return False


def delete_spawn(spawn_id: str) -> bool:
    try:
        _sb().table("spawns").delete().eq("id", spawn_id).execute()
        invalidate_all_caches()
        return True
    except Exception as e:
        st.error(f"delete_spawn failed: {e}")
        return False


def get_next_spawn_code() -> str:
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

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
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
        invalidate_all_caches()
        return (res.data or [None])[0]
    except Exception as e:
        st.error(f"create_strain failed: {e}")
        return None


def delete_strain(strain_id: str) -> bool:
    try:
        _sb().table("strains").delete().eq("id", strain_id).execute()
        invalidate_all_caches()
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


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
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
        invalidate_all_caches()
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
        invalidate_all_caches()
        return True
    except Exception as e:
        st.error(f"update_fry_batch failed: {e}")
        return False


def get_fry_batch_by_id(batch_id: str) -> Optional[dict]:
    try:
        res = _sb().table("fry_batches").select("*").eq("id", batch_id).limit(1).execute()
        return (res.data or [None])[0]
    except Exception as e:
        st.error(f"get_fry_batch_by_id failed: {e}")
        return None


def get_fry_batches_for_spawn(spawn_id: str) -> list[dict]:
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
    try:
        _sb().table("fry_batches").delete().eq("id", batch_id).execute()
        invalidate_all_caches()
        return True
    except Exception as e:
        st.error(f"delete_fry_batch failed: {e}")
        return False


# ============================================================
# FISH MILESTONES
# ============================================================

MILESTONE_FIELDS = [
    "fish_id", "milestone_date", "photo_id",
    "form_score", "body_shape", "fin_checks",
    "grade",
    "notes",
]


def get_milestones_for_fish(fish_id: str) -> list[dict]:
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
    try:
        res = _sb().table("fish_milestones").select("*").eq("id", milestone_id).limit(1).execute()
        return (res.data or [None])[0]
    except Exception as e:
        st.error(f"get_milestone_by_id failed: {e}")
        return None


def create_milestone(data: dict) -> Optional[dict]:
    payload = {k: data.get(k) for k in MILESTONE_FIELDS if k in data}
    try:
        res = _sb().table("fish_milestones").insert(payload).execute()
        _bust_cache("get_milestone_counts_by_fish")
        return (res.data or [None])[0]
    except Exception as e:
        st.error(f"create_milestone failed: {e}")
        return None


def update_milestone(milestone_id: str, updates: dict) -> bool:
    payload = {k: v for k, v in updates.items() if k in MILESTONE_FIELDS}
    if not payload:
        return False
    try:
        _sb().table("fish_milestones").update(payload).eq("id", milestone_id).execute()
        _bust_cache("get_milestone_counts_by_fish")
        return True
    except Exception as e:
        st.error(f"update_milestone failed: {e}")
        return False


def delete_milestone(milestone_id: str) -> bool:
    try:
        _sb().table("fish_milestones").delete().eq("id", milestone_id).execute()
        _bust_cache("get_milestone_counts_by_fish")
        return True
    except Exception as e:
        st.error(f"delete_milestone failed: {e}")
        return False


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_milestone_counts_by_fish() -> dict:
    counts: dict[str, int] = {}
    try:
        ids_res = _sb().table("fish_milestones").select("fish_id").execute()
        fish_ids = {r.get("fish_id") for r in (ids_res.data or []) if r.get("fish_id")}

        for fid in fish_ids:
            try:
                cnt_res = (_sb().table("fish_milestones")
                           .select("id", count="exact")
                           .eq("fish_id", fid)
                           .limit(1)
                           .execute())
                counts[fid] = int(cnt_res.count or 0)
            except Exception:
                try:
                    rows = (_sb().table("fish_milestones")
                            .select("id")
                            .eq("fish_id", fid)
                            .execute())
                    counts[fid] = len(rows.data or [])
                except Exception:
                    counts[fid] = 0
        return counts
    except Exception as e:
        st.warning(f"get_milestone_counts_by_fish fallback: {e}")
        try:
            res = _sb().table("fish_milestones").select("fish_id").execute()
            for row in (res.data or []):
                fid = row.get("fish_id")
                if fid:
                    counts[fid] = counts.get(fid, 0) + 1
        except Exception:
            pass
        return counts


# ============================================================
# PAIRING PLANS  (Session 32)
# ============================================================

PAIRING_PLAN_FIELDS = [
    "male_id", "female_id", "tank_id",
    "planned_date", "status",
    "abort_reason", "spawn_id",
    "line_goal", "notes",
    "updated_at",
]


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_all_pairing_plans() -> list[dict]:
    """All pairing plans, newest planned_date first. Cached."""
    try:
        res = (_sb().table("pairing_plans")
               .select("*")
               .order("planned_date", desc=True)
               .execute())
        return res.data or []
    except Exception as e:
        st.error(f"get_all_pairing_plans failed: {e}")
        return []


def get_pairing_plan_by_id(plan_id: str) -> Optional[dict]:
    try:
        res = (_sb().table("pairing_plans").select("*").eq("id", plan_id).limit(1).execute()
        return (res.data or [None])[0]
    except Exception as e:
        st.error(f"get_pairing_plan_by_id failed: {e}")
        return None


def create_pairing_plan(data: dict) -> Optional[dict]:
    payload = {k: data.get(k) for k in PAIRING_PLAN_FIELDS if k in data}
    try:
        res = _sb().table("pairing_plans").insert(payload).execute()
        invalidate_all_caches()
        return (res.data or [None])[0]
    except Exception as e:
        st.error(f"create_pairing_plan failed: {e}")
        return None


def update_pairing_plan(plan_id: str, updates: dict) -> bool:
    payload = {k: v for k, v in updates.items() if k in PAIRING_PLAN_FIELDS}
    payload["updated_at"] = _now_iso()
    if not payload:
        return False
    try:
        _sb().table("pairing_plans").update(payload).eq("id", plan_id).execute()
        invalidate_all_caches()
        return True
    except Exception as e:
        st.error(f"update_pairing_plan failed: {e}")
        return False


def delete_pairing_plan(plan_id: str) -> bool:
    try:
        _sb().table("pairing_plans").delete().eq("id", plan_id).execute()
        invalidate_all_caches()
        return True
    except Exception as e:
        st.error(f"delete_pairing_plan failed: {e}")
        return False


# ============================================================
# DASHBOARD AGGREGATES
# ============================================================

def get_dashboard_counts() -> dict:
    try:
        fish = _sb().table("fish").select("id,is_breeder,breeder_status,status,gender").execute().data or []
        tanks = _sb().table("tanks").select("id,status").execute().data or []
        spawns = _sb().table("spawns").select("id,status").execute().data or []

        total_tanks = len(tanks)

        available_tanks = sum(
            1 for t in tanks
            if (t.get("status") or "").strip() == "Empty / Idle"
        )
        reserved_tanks = sum(
            1 for t in tanks
            if (t.get("status") or "").strip() == "Reserved"
        )
        occupied_tanks = sum(
            1 for t in tanks
            if (t.get("status") or "").strip() == "Occupied"
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
