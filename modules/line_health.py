# modules/line_health.py
# Betta Farm Management System
# Session 21 — Line and variety health aggregation.
#
# Groups fish + spawns + fry_batches into "lines" (by line_code) or
# "varieties" (by variety) and computes per-group stats.
#
# No DB schema changes — reads existing tables.

from __future__ import annotations

import datetime as _dt
from typing import Optional

import streamlit as st

from database import get_all_fish, get_all_spawns, get_all_fry_batches


# ============================================================
# CONSTANTS
# ============================================================

STAGNANT_DAYS = 90
DECLINING_SURVIVAL_THRESHOLD = 0.50   # < 50% counts as poor
NARROWING_MIN_PAIRS = 1                # fewer than 2 active pairs = narrowing


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


def _safe_int(val, default: int = 0) -> int:
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _avg(values: list) -> Optional[float]:
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _active_breeders(fish_list: list[dict]) -> list[dict]:
    return [
        f for f in fish_list
        if f.get("is_breeder")
        and (f.get("breeder_status") or "").lower()
            not in ("retired", "inactive")
    ]


def _count_active_pairs(fish_list: list[dict], spawns_list: list[dict]) -> int:
    """
    Rough count of active breeding pairs in a group.
    Counts unique (male_id, female_id) combos where the spawn is
    active OR recent (within last 90 days).
    """
    pairs = set()
    for s in spawns_list:
        status = (s.get("status") or "").lower()
        if status in ("failed", "completed"):
            continue
        days = _days_since(s.get("pairing_date"))
        if days is not None and days > STAGNANT_DAYS:
            continue
        m = s.get("male_id")
        f = s.get("female_id")
        if m and f:
            pairs.add((m, f))
    return len(pairs)


def _compute_warnings(
    *,
    fish_list: list[dict],
    spawns_list: list[dict],
    batches_list: list[dict],
) -> list[dict]:
    """
    Returns a list of warning dicts:
      { "kind": "narrowing"|"stagnant"|"declining",
        "icon": emoji, "label": str, "reason": str }
    """
    warnings = []

    # Narrowing — fewer than 2 active pairs
    pairs = _count_active_pairs(fish_list, spawns_list)
    if pairs < 2 and len(_active_breeders(fish_list)) >= 2:
        warnings.append({
            "kind": "narrowing",
            "icon": "⚠️",
            "label": "Narrowing",
            "reason": f"Only {pairs} active breeding pair{'s' if pairs != 1 else ''}.",
        })

    # Stagnant — no spawns in 90 days and line has at least 2 fish
    if len(fish_list) >= 2:
        recent_spawns = [
            s for s in spawns_list
            if (_days_since(s.get("pairing_date")) or 9999) <= STAGNANT_DAYS
        ]
        if not recent_spawns and spawns_list:
            warnings.append({
                "kind": "stagnant",
                "icon": "💤",
                "label": "Stagnant",
                "reason": f"No spawns in {STAGNANT_DAYS}+ days.",
            })

    # Declining — last 2 spawns failed OR had < 50% survival
    if len(spawns_list) >= 2:
        sorted_spawns = sorted(
            spawns_list,
            key=lambda s: s.get("pairing_date") or "",
            reverse=True,
        )
        last_two = sorted_spawns[:2]
        declining_count = 0
        for s in last_two:
            status = (s.get("status") or "").lower()
            if status == "failed":
                declining_count += 1
                continue
            # Find batches for this spawn
            s_batches = [b for b in batches_list if b.get("spawn_id") == s["id"]]
            for b in s_batches:
                initial = _safe_int(b.get("initial_count"))
                current = _safe_int(b.get("current_count"))
                if initial > 0 and (current / initial) < DECLINING_SURVIVAL_THRESHOLD:
                    declining_count += 1
                    break

        if declining_count >= 2:
            warnings.append({
                "kind": "declining",
                "icon": "📉",
                "label": "Declining",
                "reason": "Last 2 spawns failed or had low survival.",
            })

    return warnings


# ============================================================
# AGGREGATION
# ============================================================

def _stats_for_group(
    fish_list: list[dict],
    spawns_list: list[dict],
    batches_list: list[dict],
) -> dict:
    """Compute stats for one group of fish + its spawns + batches."""
    # Population
    total_fish = len(fish_list)
    breeders = _active_breeders(fish_list)
    males = sum(1 for b in breeders if (b.get("gender") or "").lower() == "male")
    females = sum(1 for b in breeders if (b.get("gender") or "").lower() == "female")

    # Generations
    gen_counts: dict[str, int] = {}
    for f in fish_list:
        gen = (f.get("generation") or "P1").upper()
        # Bucket F3+ together
        if gen.startswith("F") and gen[1:].isdigit():
            n = int(gen[1:])
            if n >= 3:
                gen = "F3+"
        gen_counts[gen] = gen_counts.get(gen, 0) + 1

    # Spawns
    total_spawns = len(spawns_list)
    success_states = {"free swimming", "completed"}
    success_count = sum(
        1 for s in spawns_list
        if (s.get("status") or "").lower() in success_states
    )
    success_rate = (success_count / total_spawns * 100) if total_spawns else None

    active_spawns = sum(
        1 for s in spawns_list
        if (s.get("status") or "").lower() in ("in pairing", "pending (success)")
    )

    # Survival — avg of current/initial across batches
    survivals = []
    for b in batches_list:
        initial = _safe_int(b.get("initial_count"))
        current = _safe_int(b.get("current_count"))
        if initial > 0:
            survivals.append(current / initial)
    survival_avg = (sum(survivals) / len(survivals)) if survivals else None

    # Form score — avg over fish in this group that have form_score
    scores = [_safe_int(f.get("form_score")) for f in fish_list if f.get("form_score") is not None]
    form_avg = _avg(scores)

    # Warnings
    warnings = _compute_warnings(
        fish_list=fish_list,
        spawns_list=spawns_list,
        batches_list=batches_list,
    )

    return {
        "total_fish": total_fish,
        "total_breeders": len(breeders),
        "male_breeders": males,
        "female_breeders": females,
        "generations": gen_counts,
        "total_spawns": total_spawns,
        "active_spawns": active_spawns,
        "success_count": success_count,
        "success_rate": success_rate,
        "survival_avg": survival_avg,
        "form_avg": form_avg,
        "warnings": warnings,
    }


def compute_line_health() -> list[dict]:
    """
    Group by line_code. Returns one entry per line:
      { "line_code": str, "stats": {...}, "is_unassigned": bool }
    UNK / empty line_codes are grouped as "Unassigned" at the end.
    """
    fish = get_all_fish()
    spawns = get_all_spawns()
    batches = get_all_fry_batches()

    spawn_by_id = {s["id"]: s for s in spawns}

    # Group fish by line_code
    by_line: dict[str, list[dict]] = {}
    for f in fish:
        code = (f.get("line_code") or "UNK").strip().upper()
        by_line.setdefault(code, []).append(f)

    # For each line, find its spawns by looking at male_id/female_id in its fish
    result = []
    for code, fish_list in by_line.items():
        fish_ids = {f["id"] for f in fish_list}
        line_spawns = [
            s for s in spawns
            if s.get("male_id") in fish_ids or s.get("female_id") in fish_ids
        ]
        line_spawn_ids = {s["id"] for s in line_spawns}
        line_batches = [b for b in batches if b.get("spawn_id") in line_spawn_ids]

        stats = _stats_for_group(fish_list, line_spawns, line_batches)

        result.append({
            "line_code": code,
            "stats": stats,
            "is_unassigned": code in ("UNK", "N/A", "", "NONE"),
        })

    # Sort: real lines first (alphabetically), UNK last
    result.sort(key=lambda r: (r["is_unassigned"], r["line_code"]))
    return result


def compute_variety_health() -> list[dict]:
    """
    Group by variety. Returns one entry per variety:
      { "variety": str, "stats": {...} }
    """
    fish = get_all_fish()
    spawns = get_all_spawns()
    batches = get_all_fry_batches()

    by_variety: dict[str, list[dict]] = {}
    for f in fish:
        v = (f.get("variety") or "Unspecified").strip()
        by_variety.setdefault(v, []).append(f)

    result = []
    for variety, fish_list in by_variety.items():
        fish_ids = {f["id"] for f in fish_list}
        var_spawns = [
            s for s in spawns
            if s.get("male_id") in fish_ids or s.get("female_id") in fish_ids
        ]
        var_spawn_ids = {s["id"] for s in var_spawns}
        var_batches = [b for b in batches if b.get("spawn_id") in var_spawn_ids]

        stats = _stats_for_group(fish_list, var_spawns, var_batches)

        result.append({
            "variety": variety,
            "stats": stats,
        })

    # Sort alphabetically, "Unspecified" last
    result.sort(key=lambda r: (r["variety"] == "Unspecified", r["variety"]))
    return result
