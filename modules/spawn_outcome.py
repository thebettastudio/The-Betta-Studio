# modules/spawn_outcome.py
# Betta Farm Management System
# Session 24B — Computed batch outcome per spawn.
# Session 24C — Split culls (pre-jar / jarred), add died, reconciliation check.
#
# Count model (all numbers must reconcile):
#   Initial = Current + Jarred_alive + Culled_pre + Culled_jarred + Died
#
# Where:
#   Current       = unjarred fry still alive in the batch
#   Jarred_alive  = individually tracked fish with this batch_id, status not culled/deceased
#   Culled_pre    = fry culled BEFORE jarring (batch.culled_count)
#   Culled_jarred = fish jarred then later culled (fish.status = "Culled" with this batch_id)
#   Died          = natural deaths (batch.died_count)
#
# Survival % = (Current + Jarred_alive) ÷ Initial
#   Represents "of everything we started with, how many are still alive with us"
#
# Verdict uses:
#   high_pct  = (High+ grade jarred alive) ÷ jarred_alive
#   cull_rate = (Culled_pre + Culled_jarred) ÷ Initial

from __future__ import annotations

from typing import Optional

from database import (
    get_all_fish,
    get_all_spawns,
    get_all_fry_batches,
)


# ============================================================
# CONSTANTS
# ============================================================

HIGH_GRADES = {"Show Grade", "High Grade"}

_GRADE_RANK = {
    "Show Grade": 5,
    "High Grade": 4,
    "Breeder Grade": 3,
    "Material Grade": 2,
    "Pet Grade": 1,
}

VERDICT_ICONS = {
    "excellent": "🌟",
    "solid": "✅",
    "mixed": "⚠️",
    "weak": "❌",
    "failed": "🚫",
    "pending": "⏳",
    "unknown": "—",
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


def _grade_breakdown(jarred: list[dict]) -> dict:
    out: dict = {}
    for f in jarred:
        g = f.get("grade") or "Unspecified"
        out[g] = out.get(g, 0) + 1
    return out


def _high_plus_count(jarred: list[dict]) -> int:
    return sum(1 for f in jarred if (f.get("grade") or "") in HIGH_GRADES)


def _best_fish(jarred: list[dict]) -> Optional[dict]:
    if not jarred:
        return None
    def _key(f):
        rank = _GRADE_RANK.get(f.get("grade") or "", 0)
        score = _safe_int(f.get("form_score"))
        return (rank, score)
    return max(jarred, key=_key)


def _compute_verdict(
    jarred_alive: int,
    high_plus_count: int,
    total_culled: int,
    initial: int,
) -> tuple[str, str]:
    """
    Returns (verdict_key, reason_short).
    cull_rate = total_culled ÷ initial (of all fry started, how many culled).
    """
    # Failed: no jarred survivors, but something was culled
    if jarred_alive == 0 and total_culled > 0:
        return ("failed", f"All {total_culled} culled, none jarred")

    # Pending: no jarring yet
    if jarred_alive == 0 and total_culled == 0:
        return ("pending", "No jarring or culling recorded yet")

    if jarred_alive == 0:
        return ("unknown", "No jarred fish to grade")

    high_pct = high_plus_count / jarred_alive
    cull_rate = (total_culled / initial) if initial > 0 else 0.0

    summary = f"{high_pct*100:.0f}% High+ · {cull_rate*100:.0f}% culled"

    # Excellent
    if high_pct >= 0.50 and cull_rate < 0.20:
        return ("excellent", summary)

    # Weak (checked before Mixed so cull rate dominates if extreme)
    if high_pct < 0.10 or cull_rate > 0.60:
        return ("weak", summary)

    # Solid
    if high_pct >= 0.25 and cull_rate <= 0.40:
        return ("solid", summary)

    # Mixed (fallback)
    return ("mixed", summary)


# ============================================================
# MAIN API
# ============================================================

def compute_spawn_outcome(spawn_id: str) -> dict:
    """Compute the outcome for one spawn."""
    all_fish = get_all_fish()
    all_batches = get_all_fry_batches()
    return _compute_from_data(spawn_id, all_fish, all_batches)


def _compute_from_data(
    spawn_id: str,
    all_fish: list[dict],
    all_batches: list[dict],
) -> dict:
    """Internal: compute using pre-fetched data."""
    # --- Jarred fish (any status) that came from this spawn ---
    all_from_spawn = [f for f in all_fish if f.get("batch_id") == spawn_id]

    culled_jarred_fish = [
        f for f in all_from_spawn
        if (f.get("status") or "").lower() in ("culled", "deceased")
    ]
    alive_jarred = [
        f for f in all_from_spawn
        if (f.get("status") or "").lower() not in ("culled", "deceased")
    ]

    # --- Batch record (fry_batches) ---
    batch = next((b for b in all_batches if b.get("spawn_id") == spawn_id), None)

    current_count     = _safe_int(batch.get("current_count")) if batch else 0
    culled_pre        = _safe_int(batch.get("culled_count"))  if batch else 0
    female_count      = _safe_int(batch.get("female_count"))  if batch else 0
    died_count        = _safe_int(batch.get("died_count"))    if batch else 0
    initial_count     = _safe_int(batch.get("initial_count")) if batch else 0

    # --- Counts for the count model ---
    jarred_alive   = len(alive_jarred)
    culled_jarred  = len(culled_jarred_fish)
    total_culled   = culled_pre + culled_jarred

    # --- Grade breakdown (over alive jarred only) ---
    breakdown  = _grade_breakdown(alive_jarred)
    high_plus  = _high_plus_count(alive_jarred)

    scores = [_safe_int(f.get("form_score")) for f in alive_jarred if f.get("form_score") is not None]
    avg_score = _avg(scores)

    # --- Survival % = (Current + Jarred_alive) ÷ Initial ---
    survival = None
    if initial_count > 0:
        survival = (current_count + jarred_alive) / initial_count

    # --- Reconciliation: Initial = Current + Jarred_alive + Culled_pre + Culled_jarred + Died ---
    expected_sum = current_count + jarred_alive + culled_pre + culled_jarred + died_count
    reconciliation_delta = initial_count - expected_sum
    reconciles = abs(reconciliation_delta) <= 1  # allow ±1 for rounding noise

    # --- Verdict ---
    verdict_key, verdict_reason = _compute_verdict(
        jarred_alive=jarred_alive,
        high_plus_count=high_plus,
        total_culled=total_culled,
        initial=initial_count,
    )

    best = _best_fish(alive_jarred)

    return {
        "spawn_id": spawn_id,

        # Core counts
        "initial_count":   initial_count,
        "current_count":   current_count,
        "jarred_alive":    jarred_alive,
        "jarred_total":    len(all_from_spawn),
        "culled_pre":      culled_pre,
        "culled_jarred":   culled_jarred,
        "culled_total":    total_culled,
        "died":            died_count,
        "female_count":    female_count,

        # Quality
        "survival":        survival,
        "grade_breakdown": breakdown,
        "high_plus_count": high_plus,
        "avg_form_score":  avg_score,
        "best_fish":       best,

        # Verdict
        "verdict_key":     verdict_key,
        "verdict_icon":    VERDICT_ICONS.get(verdict_key, "—"),
        "verdict_reason":  verdict_reason,

        # Reconciliation
        "expected_sum":    expected_sum,
        "reconciliation_delta": reconciliation_delta,
        "reconciles":      reconciles,

        # Meta
        "has_batch":       batch is not None,

        # Aliases for backward-compat with earlier code
        "jarred_count":    jarred_alive,   # older field name
        "culled_count":    total_culled,   # older field name
    }


def compute_all_spawn_outcomes() -> dict[str, dict]:
    """Compute outcomes for all spawns in one pass."""
    all_spawns  = get_all_spawns()
    all_fish    = get_all_fish()
    all_batches = get_all_fry_batches()

    out = {}
    for s in all_spawns:
        out[s["id"]] = _compute_from_data(s["id"], all_fish, all_batches)
    return out


# ============================================================
# DISPLAY HELPERS
# ============================================================

def verdict_badge_html(outcome: dict) -> str:
    """Return an inline HTML badge for the verdict."""
    key = outcome.get("verdict_key", "unknown")
    icon = outcome.get("verdict_icon", "—")
    label_map = {
        "excellent": "Excellent",
        "solid": "Solid",
        "mixed": "Mixed",
        "weak": "Weak",
        "failed": "Failed",
        "pending": "Pending",
        "unknown": "Unknown",
    }
    label = label_map.get(key, "—")

    color_map = {
        "excellent": ("#D1FAE5", "#065F46"),
        "solid":     ("#DBEAFE", "#1E40AF"),
        "mixed":     ("#FEF3C7", "#92400E"),
        "weak":      ("#FEE2E2", "#991B1B"),
        "failed":    ("#F3F4F6", "#6B7280"),
        "pending":   ("#F3F4F6", "#374151"),
        "unknown":   ("#F3F4F6", "#6B7280"),
    }
    bg, fg = color_map.get(key, ("#F3F4F6", "#374151"))

    return (
        f'<span style="display:inline-block;background:{bg};color:{fg};'
        f'font-size:12px;font-weight:600;padding:3px 10px;border-radius:10px;">'
        f'{icon} {label}</span>'
    )


def grade_breakdown_short(outcome: dict) -> str:
    """Return '5 Show · 2 High · 3 Pet' style summary."""
    breakdown = outcome.get("grade_breakdown") or {}
    if not breakdown:
        return "—"
    order = ["Show Grade", "High Grade", "Breeder Grade", "Material Grade", "Pet Grade"]
    parts = []
    for g in order:
        if g in breakdown:
            short = g.replace(" Grade", "")
            parts.append(f"{breakdown[g]} {short}")
    for g, count in breakdown.items():
        if g not in order:
            parts.append(f"{count} {g}")
    return " · ".join(parts) if parts else "—"


def reconciliation_html(outcome: dict) -> str:
    """
    Return an HTML badge showing whether the counts reconcile.
    """
    if not outcome.get("has_batch"):
        return ""

    delta = outcome.get("reconciliation_delta", 0)
    initial = outcome.get("initial_count", 0)

    if abs(delta) <= 1:
        return (
            '<span style="display:inline-block;background:#D1FAE5;color:#065F46;'
            'font-size:11px;font-weight:600;padding:2px 8px;border-radius:10px;">'
            '✓ Counts reconcile</span>'
        )

    sign = "+" if delta > 0 else ""
    return (
        f'<span style="display:inline-block;background:#FEF3C7;color:#92400E;'
        f'font-size:11px;font-weight:600;padding:2px 8px;border-radius:10px;">'
        f'⚠️ Off by {sign}{delta}</span>'
    )
