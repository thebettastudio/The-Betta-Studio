# modules/fish_milestones.py
# Betta Farm Management System
# Session 20 — Fish milestone tracking + trend-based suggestions.
#
# A milestone is a photo + optional re-score at a point in a fish's life.
# We use the same form-scoring checklist as fish registration, so scores
# are comparable across time.
#
# Suggestions are simple and explainable:
#   - If last 2+ scores are rising → suggest promote to breeder
#   - If last 2+ scores are falling → suggest reconsider / retire
#   - Otherwise → no suggestion

from __future__ import annotations

import datetime as _dt
from typing import Optional

import streamlit as st

from database import (
    get_milestones_for_fish,
    create_milestone,
    update_milestone,
    delete_milestone,
    get_fish_by_id,
    log_activity,
)
from modules.photo_service import upload_photo, delete_drive_file


# ============================================================
# CONSTANTS
# ============================================================

MILESTONE_INTERVAL_DAYS = 30

# Suggestion thresholds
TREND_DELTA = 5              # min score change to count as "rising"/"falling"
MIN_TREND_POINTS = 2         # need this many milestones to even suggest
PROMOTE_SCORE_FLOOR = 70     # only suggest promote if latest score >= this


# ============================================================
# HELPERS
# ============================================================

def _days_since(date_str: Optional[str]) -> Optional[int]:
    """Return days since a YYYY-MM-DD date, or None if unparseable."""
    if not date_str:
        return None
    try:
        d = _dt.date.fromisoformat(str(date_str)[:10])
        return (_dt.date.today() - d).days
    except Exception:
        return None


def _latest_milestone(milestones: list[dict]) -> Optional[dict]:
    """Return the newest milestone by date."""
    if not milestones:
        return None
    # Assume caller passes them sorted newest-first from get_milestones_for_fish
    return milestones[0]


def milestone_is_due(fish: dict, milestones: list[dict]) -> bool:
    """
    True if a milestone should be prompted for this fish.
    Rule: at least MILESTONE_INTERVAL_DAYS since the last milestone,
    or since the fish was created (if no milestones yet).
    """
    status = (fish.get("status") or "").lower()
    if status in ("sold", "deceased", "retired"):
        return False

    latest = _latest_milestone(milestones)
    if latest:
        days = _days_since(latest.get("milestone_date"))
    else:
        days = _days_since(fish.get("created_at"))

    if days is None:
        return False
    return days >= MILESTONE_INTERVAL_DAYS


def compute_trend(milestones: list[dict]) -> dict:
    """
    Analyze the score trend from a list of milestones (newest-first).
    Returns:
      {
        "direction": "rising" | "falling" | "flat" | "insufficient",
        "delta": int or None,
        "latest_score": int or None,
        "previous_score": int or None,
      }
    Only uses milestones that actually have a form_score.
    """
    scored = [m for m in milestones if m.get("form_score") is not None]

    if len(scored) < MIN_TREND_POINTS:
        return {
            "direction": "insufficient",
            "delta": None,
            "latest_score": (scored[0].get("form_score") if scored else None),
            "previous_score": None,
        }

    latest = scored[0].get("form_score")
    previous = scored[1].get("form_score")
    delta = int(latest) - int(previous)

    if delta >= TREND_DELTA:
        direction = "rising"
    elif delta <= -TREND_DELTA:
        direction = "falling"
    else:
        direction = "flat"

    return {
        "direction": direction,
        "delta": delta,
        "latest_score": latest,
        "previous_score": previous,
    }


def suggest_action(fish: dict, milestones: list[dict]) -> Optional[dict]:
    """
    Suggest a next action based on the score trend and current fish state.
    Returns None if no suggestion, or:
      { "kind": "promote"|"reconsider", "label": str, "icon": str, "reason": str }
    """
    trend = compute_trend(milestones)
    direction = trend["direction"]
    latest = trend["latest_score"]

    is_breeder = bool(fish.get("is_breeder"))
    status = (fish.get("status") or "").lower()

    # Don't suggest anything for retired/sold/deceased
    if status in ("retired", "sold", "deceased"):
        return None

    # Rising + not yet a breeder + score is decent → suggest promote
    if direction == "rising" and not is_breeder and latest is not None and latest >= PROMOTE_SCORE_FLOOR:
        return {
            "kind": "promote",
            "icon": "⭐",
            "label": "Consider promoting to breeder",
            "reason": (
                f"Score rose by {trend['delta']} points over last milestone "
                f"(now {latest})."
            ),
        }

    # Falling twice in a row (or by a big delta) → suggest reconsider / retire
    if direction == "falling":
        # Only nudge toward retiring if it's a breeder (promoted fish is worth revisiting)
        if is_breeder:
            return {
                "kind": "reconsider",
                "icon": "⚠️",
                "label": "Consider retiring",
                "reason": (
                    f"Score dropped by {abs(trend['delta'])} points "
                    f"(now {latest})."
                ),
            }
        return {
            "kind": "reconsider",
            "icon": "⚠️",
            "label": "Form appears to be declining",
            "reason": (
                f"Score dropped by {abs(trend['delta'])} points "
                f"(now {latest})."
            ),
        }

    return None


# ============================================================
# CREATE / UPDATE
# ============================================================

def add_milestone(
    *,
    fish_id: str,
    milestone_date: Optional[str] = None,
    photo_file=None,
    form_score: Optional[int] = None,
    body_shape: str = "",
    fin_checks: Optional[dict] = None,
    notes: str = "",
) -> Optional[dict]:
    """
    Add a milestone. Uploads photo to Drive if provided.
    Logs activity on success.
    """
    fish = get_fish_by_id(fish_id)
    if not fish:
        st.error("Fish not found.")
        return None

    photo_id = None
    if photo_file is not None:
        with st.spinner("Uploading photo..."):
            photo_id = upload_photo(photo_file, entity_type="milestone", entity_id=fish_id)
        if not photo_id:
            st.warning("Photo upload failed. Saving milestone without photo.")

    record = {
        "fish_id": fish_id,
        "milestone_date": milestone_date or _dt.date.today().isoformat(),
        "photo_id": photo_id,
        "form_score": form_score,
        "body_shape": body_shape or None,
        "fin_checks": fin_checks or {},
        "notes": notes or None,
    }

    saved = create_milestone(record)
    if saved:
        log_activity(
            action_type="fish_milestone_added",
            description=(
                f"Milestone for {fish.get('system_id')}"
                + (f" (score {form_score})" if form_score is not None else "")
            ),
            entity_type="fish",
            entity_id=fish_id,
        )
    return saved


def edit_milestone(
    milestone_id: str,
    *,
    photo_file=None,
    updates: Optional[dict] = None,
) -> bool:
    """Edit an existing milestone. If photo_file is passed, replaces the photo."""
    updates = dict(updates or {})

    if photo_file is not None:
        from database import get_milestone_by_id
        existing = get_milestone_by_id(milestone_id)
        old_photo = existing.get("photo_id") if existing else None

        new_photo = upload_photo(photo_file, entity_type="milestone", entity_id=milestone_id)
        if new_photo:
            updates["photo_id"] = new_photo
            if old_photo:
                delete_drive_file(old_photo)

    return update_milestone(milestone_id, updates)


def remove_milestone(milestone_id: str) -> bool:
    """Delete a milestone and its Drive photo (best effort)."""
    from database import get_milestone_by_id
    milestone = get_milestone_by_id(milestone_id)
    if not milestone:
        return False

    if milestone.get("photo_id"):
        delete_drive_file(milestone["photo_id"])

    ok = delete_milestone(milestone_id)
    if ok:
        log_activity(
            action_type="fish_milestone_deleted",
            description=f"Deleted milestone {milestone_id[:8]}",
            entity_type="fish",
            entity_id=milestone.get("fish_id"),
        )
    return ok


# ============================================================
# AGGREGATES
# ============================================================

def get_fish_due_for_milestone() -> list[dict]:
    """
    Return fish that are due for a milestone prompt.
    Uses the same rule as milestone_is_due().
    """
    from database import get_all_fish
    from database import get_milestone_counts_by_fish  # not needed but keep imports lazy

    due = []
    for fish in get_all_fish():
        milestones = get_milestones_for_fish(fish["id"])
        if milestone_is_due(fish, milestones):
            due.append({
                "fish": fish,
                "milestone_count": len(milestones),
                "last_date": (milestones[0].get("milestone_date") if milestones else None),
            })
    return due
