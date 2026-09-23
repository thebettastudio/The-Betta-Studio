# modules/activity_logger.py
# Betta Farm Management System
# Session 14 — Ported to Supabase.
#
# Note: the DB table is `activity_log` (with an underscore).
# All writes happen via database.log_activity() from other modules.
# This module just provides read/filter helpers.

from database import get_activity_log


def fetch_activity_logs(limit: int = 500) -> list[dict]:
    """
    Fetch the most recent activity entries, newest first.
    Each row: {id, ts, action_type, entity_type, entity_id,
               description, photo_id, photo_url, metadata}
    """
    return get_activity_log(limit=limit)


def filter_logs(
    logs: list[dict],
    query: str = "",
    action_type: str = "",
    entity_type: str = "",
) -> list[dict]:
    """
    Filter activity entries by free-text query and/or exact action/entity type.
    Query is matched against description, action_type, entity_type.
    """
    q = (query or "").strip().lower()
    out = []
    for entry in logs:
        if action_type and (entry.get("action_type") or "") != action_type:
            continue
        if entity_type and (entry.get("entity_type") or "") != entity_type:
            continue
        if q:
            haystack = " ".join([
                str(entry.get("description") or ""),
                str(entry.get("action_type") or ""),
                str(entry.get("entity_type") or ""),
            ]).lower()
            if q not in haystack:
                continue
        out.append(entry)
    return out


def distinct_action_types(logs: list[dict]) -> list[str]:
    return sorted({(e.get("action_type") or "").strip() for e in logs if e.get("action_type")})


def distinct_entity_types(logs: list[dict]) -> list[str]:
    return sorted({(e.get("entity_type") or "").strip() for e in logs if e.get("entity_type")})
