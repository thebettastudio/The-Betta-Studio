# modules/inheritance.py
# Betta Farm Management System
# Session 25 — Inheritance analysis: parent pairs + trait heritability.
#
# All analysis is COMPUTED from existing data — no manual input.
#
# Uses:
#   fish (parents + offspring)
#   spawns (linking pairs to batches)
#
# Only analyzes offspring that came from a spawn (batch_id set).
# Offspring with unreliable lineage are ignored.

from __future__ import annotations

from typing import Optional

from database import (
    get_all_fish,
    get_all_spawns,
)


# ============================================================
# CONSTANTS
# ============================================================

MIN_OFFSPRING_FOR_ANALYSIS = 3     # need at least this many jarred fish to analyze a pair
GRADE_ORDER = ["Show Grade", "High Grade", "Breeder Grade", "Material Grade", "Pet Grade"]

_GRADE_RANK = {
    "Show Grade": 5,
    "High Grade": 4,
    "Breeder Grade": 3,
    "Material Grade": 2,
    "Pet Grade": 1,
}


# ============================================================
# HELPERS
# ============================================================

def _safe_int(val, default: int = 0) -> int:
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _avg(values: list) -> Optional[float]:
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _fish_by_id() -> dict:
    return {f["id"]: f for f in get_all_fish()}


def _offspring_by_spawn() -> dict:
    """Returns { spawn_id: [offspring fish rows] } for fish with batch_id set."""
    out: dict[str, list[dict]] = {}
    for f in get_all_fish():
        batch_id = f.get("batch_id")
        if not batch_id:
            continue
        out.setdefault(batch_id, []).append(f)
    return out


def _grade_distribution(fish_list: list[dict]) -> dict:
    """Return {grade: count}."""
    out: dict = {}
    for f in fish_list:
        g = f.get("grade") or "Unspecified"
        out[g] = out.get(g, 0) + 1
    return out


def _dominant_grade(fish_list: list[dict]) -> Optional[str]:
    """Highest grade present (in a single fish)."""
    if not fish_list:
        return None
    return max(
        (f.get("grade") for f in fish_list if f.get("grade")),
        key=lambda g: _GRADE_RANK.get(g, 0),
        default=None,
    )


def _avg_form_score(fish_list: list[dict]) -> Optional[float]:
    scores = [_safe_int(f.get("form_score")) for f in fish_list if f.get("form_score") is not None]
    return _avg(scores)


def _trait_of(fish: dict, trait: str) -> Optional[str]:
    """Extract a trait value from a fish row."""
    if not fish:
        return None
    if trait == "body_shape":
        return fish.get("body_shape")
    if trait == "grade":
        return fish.get("grade")
    if trait == "line_code":
        return fish.get("line_code")
    if trait == "generation":
        return fish.get("generation")
    # fin_checks stored as JSONB dict
    if trait.startswith("fin_"):
        fc = fish.get("fin_checks") or {}
        if isinstance(fc, dict):
            key = trait.replace("fin_", "")
            return "pass" if fc.get(key) else "fail"
    return None


# ============================================================
# PAIR LEADERBOARD
# ============================================================

def compute_pair_leaderboard(min_offspring: int = MIN_OFFSPRING_FOR_ANALYSIS) -> list[dict]:
    """
    For each spawn, compute:
      - parent IDs and their grades/form scores
      - offspring count, avg offspring form, grade distribution
      - delta of offspring form vs parent avg

    Returns a list of dicts, sorted by avg_offspring_form descending.
    Only spawns with >= min_offspring jarred fish are included.
    """
    fish_by_id = _fish_by_id()
    offspring_by_spawn = _offspring_by_spawn()
    spawns = get_all_spawns()

    out = []
    for s in spawns:
        spawn_id = s["id"]
        offspring = offspring_by_spawn.get(spawn_id, [])
        if len(offspring) < min_offspring:
            continue

        male = fish_by_id.get(s.get("male_id"))
        female = fish_by_id.get(s.get("female_id"))
        if not male or not female:
            continue

        parent_scores = [
            _safe_int(male.get("form_score"))
            for _ in [0] if male.get("form_score") is not None
        ]
        if female.get("form_score") is not None:
            parent_scores.append(_safe_int(female.get("form_score")))
        parent_avg = _avg(parent_scores)

        offspring_avg = _avg_form_score(offspring)

        delta = None
        if parent_avg is not None and offspring_avg is not None:
            delta = offspring_avg - parent_avg

        out.append({
            "spawn_id": spawn_id,
            "spawn_system_id": s.get("system_id"),
            "spawn_code": s.get("spawn_code"),
            "male_id": male.get("id"),
            "male_system_id": male.get("system_id"),
            "male_grade": male.get("grade"),
            "male_form": _safe_int(male.get("form_score")) if male.get("form_score") is not None else None,
            "female_id": female.get("id"),
            "female_system_id": female.get("system_id"),
            "female_grade": female.get("grade"),
            "female_form": _safe_int(female.get("form_score")) if female.get("form_score") is not None else None,
            "offspring_count": len(offspring),
            "offspring_avg_form": offspring_avg,
            "parent_avg_form": parent_avg,
            "delta": delta,
            "offspring_grades": _grade_distribution(offspring),
            "line_code": s.get("line_code"),
            "generation": s.get("generation"),
        })

    # Sort by offspring avg form descending (None last)
    out.sort(
        key=lambda x: (x["offspring_avg_form"] is None, -(x["offspring_avg_form"] or 0)),
    )
    return out


# ============================================================
# GRADE INHERITANCE MATRIX
# ============================================================

def compute_grade_inheritance_matrix(min_offspring: int = MIN_OFFSPRING_FOR_ANALYSIS) -> dict:
    """
    Build a matrix:
      rows = (male_grade, female_grade) combos
      cols = offspring grades (Show, High, Breeder, Material, Pet)
      values = % of offspring in that grade (per pair combo)

    Returns:
      {
        "rows": [{"male_grade": ..., "female_grade": ..., "count": N, "dist": {...percentages}}],
        "total_offspring": N,
        "combos_with_data": N,
      }
    """
    fish_by_id = _fish_by_id()
    offspring_by_spawn = _offspring_by_spawn()
    spawns = get_all_spawns()

    # Group offspring by (male_grade, female_grade)
    combos: dict[tuple, list[dict]] = {}

    for s in spawns:
        offspring = offspring_by_spawn.get(s["id"], [])
        if len(offspring) < min_offspring:
            continue

        male = fish_by_id.get(s.get("male_id"))
        female = fish_by_id.get(s.get("female_id"))
        if not male or not female:
            continue

        male_g = male.get("grade") or "Unspecified"
        female_g = female.get("grade") or "Unspecified"

        # Normalize order so Show×High and High×Show are the same combo
        combo_key = tuple(sorted([male_g, female_g], key=lambda g: -_GRADE_RANK.get(g, 0)))
        combos.setdefault(combo_key, []).extend(offspring)

    rows = []
    total_offspring = 0
    for combo, offspring in combos.items():
        total_offspring += len(offspring)
        dist = _grade_distribution(offspring)
        total = len(offspring)
        pct = {g: (dist.get(g, 0) / total * 100) if total else 0 for g in GRADE_ORDER}
        rows.append({
            "male_grade": combo[0],
            "female_grade": combo[1],
            "count": total,
            "dist": pct,
        })

    # Sort rows by male grade rank, then female
    rows.sort(
        key=lambda r: (
            -_GRADE_RANK.get(r["male_grade"], 0),
            -_GRADE_RANK.get(r["female_grade"], 0),
        ),
    )

    return {
        "rows": rows,
        "total_offspring": total_offspring,
        "combos_with_data": len(rows),
        "grade_order": GRADE_ORDER,
    }


# ============================================================
# BODY SHAPE INHERITANCE
# ============================================================

def compute_body_shape_inheritance(min_offspring: int = MIN_OFFSPRING_FOR_ANALYSIS) -> dict:
    """
    For each (male_shape, female_shape) combo, show offspring body_shape distribution.
    """
    fish_by_id = _fish_by_id()
    offspring_by_spawn = _offspring_by_spawn()
    spawns = get_all_spawns()

    combos: dict[tuple, list[dict]] = {}

    for s in spawns:
        offspring = offspring_by_spawn.get(s["id"], [])
        if len(offspring) < min_offspring:
            continue

        male = fish_by_id.get(s.get("male_id"))
        female = fish_by_id.get(s.get("female_id"))
        if not male or not female:
            continue

        m_shape = male.get("body_shape") or "Unspecified"
        f_shape = female.get("body_shape") or "Unspecified"
        key = tuple(sorted([m_shape, f_shape]))
        combos.setdefault(key, []).extend(offspring)

    rows = []
    for combo, offspring in combos.items():
        dist = _grade_distribution_by_field(offspring, "body_shape")
        total = len(offspring)
        pct = {k: (v / total * 100) if total else 0 for k, v in dist.items()}
        rows.append({
            "male_shape": combo[0],
            "female_shape": combo[1],
            "count": total,
            "dist": pct,
        })

    rows.sort(key=lambda r: -r["count"])
    return {
        "rows": rows,
        "total_offspring": sum(r["count"] for r in rows),
    }


def _grade_distribution_by_field(fish_list: list[dict], field: str) -> dict:
    """Generic distribution over any field."""
    out: dict = {}
    for f in fish_list:
        val = f.get(field) or "Unspecified"
        out[val] = out.get(val, 0) + 1
    return out


# ============================================================
# FIN CHECK INHERITANCE
# ============================================================

FIN_CHECK_LABELS = {
    "caudal_spread": "Caudal 180°",
    "caudal_prop": "Caudal branching",
    "dorsal_struct": "Dorsal structure",
    "anal_struct": "Anal structure",
    "ventral_fins": "Ventral fins",
    "pectoral_fins": "Pectoral fins",
}


def compute_fin_check_inheritance(min_offspring: int = MIN_OFFSPRING_FOR_ANALYSIS) -> dict:
    """
    For each fin check, compute:
      - % of offspring passing when both parents pass
      - % of offspring passing when one parent passes
      - % of offspring passing when neither parent passes

    Returns:
      {
        "checks": [
          {
            "key": "caudal_spread",
            "label": "Caudal 180°",
            "both_pass": {"n": N, "pct": X},
            "one_pass": {"n": N, "pct": X},
            "neither_pass": {"n": N, "pct": X},
          },
          ...
        ]
      }
    """
    fish_by_id = _fish_by_id()
    offspring_by_spawn = _offspring_by_spawn()
    spawns = get_all_spawns()

    # For each fin check, tally offspring outcomes by parent combo
    results = {key: {"both": [], "one": [], "neither": []} for key in FIN_CHECK_LABELS}

    for s in spawns:
        offspring = offspring_by_spawn.get(s["id"], [])
        if len(offspring) < min_offspring:
            continue

        male = fish_by_id.get(s.get("male_id"))
        female = fish_by_id.get(s.get("female_id"))
        if not male or not female:
            continue

        m_fc = male.get("fin_checks") or {}
        f_fc = female.get("fin_checks") or {}
        if not isinstance(m_fc, dict):
            m_fc = {}
        if not isinstance(f_fc, dict):
            f_fc = {}

        for key in FIN_CHECK_LABELS:
            m_pass = bool(m_fc.get(key))
            f_pass = bool(f_fc.get(key))

            if m_pass and f_pass:
                bucket = "both"
            elif m_pass or f_pass:
                bucket = "one"
            else:
                bucket = "neither"

            # Offspring: pass or fail this check
            for child in offspring:
                child_fc = child.get("fin_checks") or {}
                if not isinstance(child_fc, dict):
                    child_fc = {}
                child_pass = bool(child_fc.get(key))
                results[key][bucket].append(1 if child_pass else 0)

    checks_out = []
    for key, label in FIN_CHECK_LABELS.items():
        buckets = results[key]
        row = {"key": key, "label": label}
        for bucket in ("both", "one", "neither"):
            vals = buckets[bucket]
            n = len(vals)
            pct = (sum(vals) / n * 100) if n else None
            row[f"{bucket}_pass"] = {"n": n, "pct": pct}
        checks_out.append(row)

    return {"checks": checks_out}


# ============================================================
# SUMMARY STATS
# ============================================================

def get_inheritance_summary() -> dict:
    """Top-level metrics for the Inheritance page header."""
    fish_by_id = _fish_by_id()
    offspring_by_spawn = _offspring_by_spawn()
    spawns = get_all_spawns()

    spawns_with_offspring = 0
    total_offspring = 0

    for s in spawns:
        offspring = offspring_by_spawn.get(s["id"], [])
        if len(offspring) >= MIN_OFFSPRING_FOR_ANALYSIS:
            spawns_with_offspring += 1
            total_offspring += len(offspring)

    # Distinct parent pairs (unique male+female combos across qualifying spawns)
    pairs = set()
    for s in spawns:
        offspring = offspring_by_spawn.get(s["id"], [])
        if len(offspring) < MIN_OFFSPRING_FOR_ANALYSIS:
            continue
        m = s.get("male_id")
        f = s.get("female_id")
        if m and f:
            pairs.add((m, f))

    return {
        "spawns_with_offspring": spawns_with_offspring,
        "total_offspring_analyzed": total_offspring,
        "distinct_pairs": len(pairs),
        "min_offspring_required": MIN_OFFSPRING_FOR_ANALYSIS,
    }
