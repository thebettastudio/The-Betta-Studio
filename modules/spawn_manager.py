# modules/spawn_manager.py
# Betta Farm Management System
# Session 8 — Spawn lifecycle ported to Supabase.
# Session 12 — list_active_pairings_with_details() enriched with tank + days_paired.
# Session 27B — Round 1: free-swimming triggers parent transitions.
#
# Session 28A — create_new_spawn() accepts optional pairing_date.
#
# Session 29/E — Pairing duplicate guard:
#   • get_active_pairing_fish_ids()
#   • create_new_spawn() refuses if male == female or either parent
#     is already on another active spawn.
#   • Rollback on partial failure.
#
# Session 30 — Round H Part 3: get_pairing_performance().
#
# Session 32 (this revision) — PAIRING PLANS:
#   • list_pairing_plans / list_upcoming_pairing_plans
#   • is_fish_planned
#   • create_pairing_plan / update_planned_pairing / move_pairing_plan
#   • abort_pairing_plan / start_pairing_plan
#   • get_calendar_events — derived event list for the calendar view

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
    get_all_fry_batches,
    get_all_tanks,
    log_activity,
    get_all_pairing_plans,
    get_pairing_plan_by_id,
    create_pairing_plan as db_create_pairing_plan,
    update_pairing_plan as db_update_pairing_plan,
    delete_pairing_plan as db_delete_pairing_plan,
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
# VALID STATUSES
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

PAIRING_PLAN_ACTIVE_STATUSES = {"planned"}

GRADE_ORDER = [
    "Show Grade",
    "High Grade",
    "Breeder Grade",
    "Material Grade",
    "Pet Grade",
]
QUALITY_GRADES = {"Show Grade", "High Grade", "Breeder Grade"}


# ============================================================
# HELPERS
# ============================================================

def _iso_date_prefix(val) -> Optional[str]:
    if not val:
        return None
    s = str(val)[:10]
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    return None


def _date_from_iso(val) -> Optional[_dt.date]:
    if not val:
        return None
    try:
        return _dt.date.fromisoformat(str(val)[:10])
    except Exception:
        return None


# ============================================================
# READ — SPAWNS
# ============================================================

def list_all_spawns() -> list[dict]:
    return get_all_spawns()


def list_active_spawns() -> list[dict]:
    return [s for s in get_all_spawns() if (s.get("status") in ACTIVE_STATUSES)]


def get_active_pairing_fish_ids() -> set[str]:
    out: set[str] = set()
    for s in get_all_spawns():
        if s.get("status") in ACTIVE_STATUSES:
            if s.get("male_id"):
                out.add(s["male_id"])
            if s.get("female_id"):
                out.add(s["female_id"])
    return out


def list_spawns_with_details() -> list[dict]:
    fish_by_id = {f["id"]: f for f in get_all_fish()}
    tank_by_id = {t["id"]: t for t in get_all_tanks()}

    out = []
    for s in get_all_spawns():
        tank = tank_by_id.get(s.get("tank_id"))
        tank_loc = tank.get("location_code") if tank else None

        if not tank_loc:
            notes_text = s.get("notes") or ""
            if "Tank:" in notes_text:
                try:
                    tank_loc = notes_text.split("Tank:")[1].split("|")[0].strip()
                except Exception:
                    tank_loc = None

        pairing_date = s.get("pairing_date")
        days_paired = 0
        if pairing_date:
            try:
                days_paired = (_dt.date.today() - _dt.date.fromisoformat(str(pairing_date))).days
            except Exception:
                days_paired = 0

        out.append({
            "spawn": s,
            "male": fish_by_id.get(s.get("male_id")),
            "female": fish_by_id.get(s.get("female_id")),
            "tank": tank,
            "tank_location": tank_loc or "Unassigned",
            "days_paired": days_paired,
        })
    return out


def list_active_pairings_with_details() -> list[dict]:
    return [d for d in list_spawns_with_details() if d["spawn"].get("status") in ACTIVE_STATUSES]


def get_pairing_dropdown_data() -> tuple[list[dict], list[dict]]:
    return get_breeder_pairs_data()


def get_pairing_performance() -> list[dict]:
    """Per parent-pair rollup of all their batches."""
    try:
        spawns = get_all_spawns()
        batches = get_all_fry_batches()
        all_fish = get_all_fish()

        fish_by_id = {f["id"]: f for f in all_fish}

        batches_by_spawn: dict[str, list[dict]] = {}
        for b in batches:
            sid = b.get("spawn_id")
            if sid:
                batches_by_spawn.setdefault(sid, []).append(b)

        pairs: dict[tuple, dict] = {}

        for s in spawns:
            mid = s.get("male_id")
            fid = s.get("female_id")
            if not mid or not fid:
                continue

            key = (mid, fid)
            if key not in pairs:
                male_row = fish_by_id.get(mid) or {}
                female_row = fish_by_id.get(fid) or {}
                male_sid = male_row.get("system_id") or "?"
                female_sid = female_row.get("system_id") or "?"
                pairs[key] = {
                    "male_id":          mid,
                    "female_id":        fid,
                    "male_system_id":   male_sid,
                    "female_system_id": female_sid,
                    "pair_label":       f"{male_sid} × {female_sid}",
                    "spawn_ids":        [],
                    "batch_count":      0,
                    "fry_count":        0,
                    "counts":           {g: 0 for g in GRADE_ORDER},
                    "quality_count":    0,
                    "quality_score":    0,
                }

            pairs[key]["spawn_ids"].append(s["id"])

        for pair in pairs.values():
            for sid in pair["spawn_ids"]:
                for b in batches_by_spawn.get(sid, []):
                    pair["batch_count"] += 1

                    spawn_id_for_batch = b.get("spawn_id")
                    jarring_date = _iso_date_prefix(b.get("jarring_date"))
                    if not spawn_id_for_batch or not jarring_date:
                        continue

                    for f in all_fish:
                        if f.get("batch_id") != spawn_id_for_batch:
                            continue
                        if _iso_date_prefix(f.get("birth_date")) != jarring_date:
                            continue
                        if (f.get("status") or "").lower() in ("culled", "deceased"):
                            continue

                        pair["fry_count"] += 1
                        g = (f.get("grade") or "").strip()
                        if g in pair["counts"]:
                            pair["counts"][g] += 1

            total = pair["fry_count"]
            quality_count = sum(pair["counts"][g] for g in QUALITY_GRADES)
            pair["quality_count"] = quality_count
            pair["quality_score"] = (
                int(round((quality_count / total) * 100)) if total > 0 else 0
            )

        rows = list(pairs.values())
        rows.sort(key=lambda r: (r["quality_score"], r["fry_count"]), reverse=True)
        return rows
    except Exception as e:
        st.error(f"get_pairing_performance failed: {e}")
        return []


# ============================================================
# PAIRING PLANS  (Session 32)
# ============================================================

def list_pairing_plans(status: Optional[str] = None) -> list[dict]:
    """List pairing plans, optionally filtered by status."""
    plans = get_all_pairing_plans()
    if status:
        plans = [p for p in plans if (p.get("status") or "") == status]
    return plans


def list_upcoming_pairing_plans(days_ahead: int = 60) -> list[dict]:
    """Plans with status='planned' and planned_date within the next N days."""
    today = _dt.date.today()
    cutoff = today + _dt.timedelta(days=days_ahead)
    out = []
    for p in get_all_pairing_plans():
        if (p.get("status") or "") != "planned":
            continue
        pd = _date_from_iso(p.get("planned_date"))
        if pd and today <= pd <= cutoff:
            out.append(p)
    out.sort(key=lambda p: p.get("planned_date") or "")
    return out


def is_fish_planned(fish_id: str, exclude_plan_id: Optional[str] = None) -> Optional[dict]:
    """Return the plan if this fish is committed to any active planned pairing."""
    for p in get_all_pairing_plans():
        if (p.get("status") or "") != "planned":
            continue
        if exclude_plan_id and p.get("id") == exclude_plan_id:
            continue
        if fish_id in (p.get("male_id"), p.get("female_id")):
            return p
    return None


def create_pairing_plan(
    male_id: str,
    female_id: str,
    planned_date: str,
    tank_id: Optional[str] = None,
    line_goal: str = "",
    notes: str = "",
) -> Optional[dict]:
    """
    Create a pairing plan. Validation:
      • male != female
      • both fish exist
      • neither is on an active spawn
      • neither is on another planned pairing
    """
    if male_id == female_id:
        st.error("Male and female must be different fish.")
        return None

    sire = get_fish_by_id(male_id)
    dam = get_fish_by_id(female_id)
    if not sire or not dam:
        st.error("Both fish must exist.")
        return None

    # Guard: neither can be on an active spawn
    active = get_active_pairing_fish_ids()
    conflicts = []
    if male_id in active:
        conflicts.append(sire.get("system_id") or male_id)
    if female_id in active:
        conflicts.append(dam.get("system_id") or female_id)
    if conflicts:
        st.error(
            f"⛔ Already In Pairing: {', '.join(conflicts)}. "
            f"Finish or abort that spawn first."
        )
        return None

    # Guard: neither can be on another planned pairing
    if is_fish_planned(male_id):
        st.error(f"⛔ {sire.get('system_id')} is already on a planned pairing.")
        return None
    if is_fish_planned(female_id):
        st.error(f"⛔ {dam.get('system_id')} is already on a planned pairing.")
        return None

    record = {
        "male_id": male_id,
        "female_id": female_id,
        "tank_id": tank_id,
        "planned_date": planned_date,
        "status": "planned",
        "line_goal": line_goal,
        "notes": notes,
    }

    saved = db_create_pairing_plan(record)
    if saved:
        log_activity(
            action_type="pairing_plan_created",
            description=(
                f"Planned pairing {sire.get('system_id')} × {dam.get('system_id')} "
                f"for {planned_date}"
            ),
            entity_type="pairing_plan",
            entity_id=saved["id"],
        )
    return saved


def update_planned_pairing(plan_id: str, **fields) -> bool:
    """Update any subset of plan fields."""
    allowed = {
        "male_id", "female_id", "tank_id",
        "planned_date", "line_goal", "notes",
    }
    payload = {k: v for k, v in fields.items() if k in allowed}
    if not payload:
        return False
    return db_update_pairing_plan(plan_id, payload)


def move_pairing_plan(plan_id: str, new_date: str) -> bool:
    """Change a plan's date, keeps status='planned'."""
    plan = get_pairing_plan_by_id(plan_id)
    if not plan:
        st.error("Plan not found.")
        return False
    if (plan.get("status") or "") != "planned":
        st.error("Only 'planned' plans can be moved.")
        return False

    ok = db_update_pairing_plan(plan_id, {"planned_date": new_date})
    if ok:
        log_activity(
            action_type="pairing_plan_moved",
            description=f"Moved plan {plan_id[:8]} to {new_date}",
            entity_type="pairing_plan",
            entity_id=plan_id,
        )
    return ok


def abort_pairing_plan(plan_id: str, reason: str) -> bool:
    """Mark a plan as aborted with a required reason."""
    if not reason or not reason.strip():
        st.error("An abort reason is required.")
        return False

    plan = get_pairing_plan_by_id(plan_id)
    if not plan:
        st.error("Plan not found.")
        return False
    if (plan.get("status") or "") != "planned":
        st.error("Only 'planned' plans can be aborted.")
        return False

    ok = db_update_pairing_plan(plan_id, {
        "status": "aborted",
        "abort_reason": reason.strip(),
    })
    if ok:
        log_activity(
            action_type="pairing_plan_aborted",
            description=f"Aborted plan {plan_id[:8]} — {reason.strip()}",
            entity_type="pairing_plan",
            entity_id=plan_id,
        )
    return ok


def start_pairing_plan(plan_id: str, actual_date: Optional[str] = None) -> Optional[dict]:
    """
    Start a planned pairing now (or on a given date). Creates a real
    spawn via create_new_spawn(), links the plan's spawn_id, marks the
    plan as 'started'.
    """
    plan = get_pairing_plan_by_id(plan_id)
    if not plan:
        st.error("Plan not found.")
        return None
    if (plan.get("status") or "") != "planned":
        st.error("Only 'planned' plans can be started.")
        return None

    male_id = plan.get("male_id")
    female_id = plan.get("female_id")
    tank_id = plan.get("tank_id")
    pairing_date = actual_date or _dt.date.today().isoformat()

    spawn = create_new_spawn(
        male_id=male_id,
        female_id=female_id,
        tank_id=tank_id,
        line_goal=plan.get("line_goal") or "",
        notes=plan.get("notes") or "",
        pairing_date=pairing_date,
    )
    if not spawn:
        return None

    ok = db_update_pairing_plan(plan_id, {
        "status": "started",
        "spawn_id": spawn["id"],
        "planned_date": pairing_date,
    })
    if ok:
        log_activity(
            action_type="pairing_plan_started",
            description=(
                f"Started planned pairing {plan_id[:8]} → spawn "
                f"{spawn.get('system_id')}"
            ),
            entity_type="pairing_plan",
            entity_id=plan_id,
        )
    return spawn


def delete_pairing_plan(plan_id: str) -> bool:
    """Hard delete a plan (only for aborted plans or corrections)."""
    return db_delete_pairing_plan(plan_id)


# ============================================================
# CALENDAR EVENTS  (Session 32)
# ============================================================

def get_calendar_events(days_ahead: int = 60) -> list[dict]:
    """
    Return a flat list of calendar events for the next N days.

    Event shape:
      {
        "date":    ISO 'YYYY-MM-DD',
        "kind":    'plan' | 'recovery_end' | 'eggs_due' | 'free_swim_est' | 'jarring_est',
        "title":   short string,
        "detail":  longer string,
        "ref_id":  uuid (plan id or spawn id),
        "ref_type":"pairing_plan" | "spawn",
        "meta":    dict (extra data for the card)
      }

    Derived events:
      • Plan         — status='planned', on planned_date
      • Recovery end — Recovering breeders, on started_at + recovery_days
      • Eggs due     — active spawns 'In Pairing', on pairing_date + 3d
      • Free swim    — active spawns, on pairing_date + 7d (estimate)
      • Jarring      — active spawns, on pairing_date + 21d (estimate)
    """
    today = _dt.date.today()
    cutoff = today + _dt.timedelta(days=days_ahead)

    events: list[dict] = []

    fish_by_id = {f["id"]: f for f in get_all_fish()}
    tanks_by_id = {t["id"]: t for t in get_all_tanks()}

    # ---------- Plans ----------
    for p in get_all_pairing_plans():
        if (p.get("status") or "") != "planned":
            continue
        pd = _date_from_iso(p.get("planned_date"))
        if not pd or pd < today or pd > cutoff:
            continue

        male = fish_by_id.get(p.get("male_id")) or {}
        female = fish_by_id.get(p.get("female_id")) or {}
        tank = tanks_by_id.get(p.get("tank_id")) or {}

        events.append({
            "date": pd.isoformat(),
            "kind": "plan",
            "title": f"Plan: {male.get('system_id','?')} × {female.get('system_id','?')}",
            "detail": (p.get("line_goal") or "").strip() or "Planned pairing",
            "ref_id": p["id"],
            "ref_type": "pairing_plan",
            "meta": {
                "male_id": p.get("male_id"),
                "female_id": p.get("female_id"),
                "tank_id": p.get("tank_id"),
                "tank_code": tank.get("location_code"),
                "line_goal": p.get("line_goal") or "",
                "notes": p.get("notes") or "",
            },
        })

    # ---------- Spawn-derived events ----------
    for s in get_all_spawns():
        status = (s.get("status") or "")
        pairing_date = _date_from_iso(s.get("pairing_date"))
        if not pairing_date:
            continue

        male = fish_by_id.get(s.get("male_id")) or {}
        female = fish_by_id.get(s.get("female_id")) or {}

        if status == "In Pairing":
            # Eggs due ~3 days after pairing
            eggs_due = pairing_date + _dt.timedelta(days=3)
            if today <= eggs_due <= cutoff:
                events.append({
                    "date": eggs_due.isoformat(),
                    "kind": "eggs_due",
                    "title": f"🥚 Eggs due: {s.get('system_id')}",
                    "detail": f"{male.get('system_id','?')} × {female.get('system_id','?')}",
                    "ref_id": s["id"],
                    "ref_type": "spawn",
                    "meta": {},
                })

        if status in ("In Pairing", "Pending (Success)"):
            # Free swim estimate ~7 days after pairing
            free_swim_est = pairing_date + _dt.timedelta(days=7)
            if today <= free_swim_est <= cutoff:
                events.append({
                    "date": free_swim_est.isoformat(),
                    "kind": "free_swim_est",
                    "title": f"🐟 Free swim est: {s.get('system_id')}",
                    "detail": "Estimated free-swimming window",
                    "ref_id": s["id"],
                    "ref_type": "spawn",
                    "meta": {},
                })

            # Jarring estimate ~21 days after pairing
            jarring_est = pairing_date + _dt.timedelta(days=21)
            if today <= jarring_est <= cutoff:
                events.append({
                    "date": jarring_est.isoformat(),
                    "kind": "jarring_est",
                    "title": f"🫙 Jarring est: {s.get('system_id')}",
                    "detail": "Estimated jarring window",
                    "ref_id": s["id"],
                    "ref_type": "spawn",
                    "meta": {},
                })

    # ---------- Breeder recovery ends ----------
    for f in get_all_fish():
        bs = (f.get("breeder_status") or "").strip()
        if bs not in ("Recovering", "Conditioning"):
            continue
        started_iso = f.get("breeder_status_started_at")
        if not started_iso:
            continue
        try:
            started_dt = _dt.datetime.fromisoformat(
                str(started_iso).replace("Z", "")
            )
            started_date = started_dt.date()
        except Exception:
            continue

        gender = (f.get("gender") or "").lower()
        if bs == "Recovering" and gender == "male":
            end_date = started_date + _dt.timedelta(days=4)
            next_status = "Conditioning"
        elif bs == "Recovering" and gender == "female":
            end_date = started_date + _dt.timedelta(days=14)
            next_status = "Available"
        elif bs == "Conditioning" and gender == "male":
            end_date = started_date + _dt.timedelta(days=10)
            next_status = "Available"
        else:
            continue

        if today <= end_date <= cutoff:
            events.append({
                "date": end_date.isoformat(),
                "kind": "recovery_end",
                "title": f"🟢 {f.get('system_id','?')} → {next_status}",
                "detail": f"{gender.capitalize()} {bs} ends",
                "ref_id": f["id"],
                "ref_type": "fish",
                "meta": {"next_status": next_status},
            })

    events.sort(key=lambda e: e["date"])
    return events
