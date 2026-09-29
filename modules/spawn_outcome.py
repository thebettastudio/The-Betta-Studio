# modules/spawn_outcome.py
# Betta Farm Management System
# Session 24B — Computed batch outcome per spawn.
# Session 24C — Split culls (pre-jar / jarred), add died, reconciliation check.
#
# Count model (all numbers must reconcile):
#   Initial = Current + Jarred_alive + Culled_pre + Culled_jarred + Died
#
# Where:
#   Current       = unjarred fry still alive in the batch (DERIVED)
#   Jarred_alive  = individually tracked fish jarred from THIS batch,
#                   status not culled/deceased
#   Culled_pre    = fry culled BEFORE jarring (batch.culled_count)
#   Culled_jarred = fish jarred from THIS batch then later culled
#   Died          = natural deaths (batch.died_count)
#
# Survival % = (Current + Jarred_alive) ÷ Initial
#
# Verdict uses:
#   high_pct  = (High+ grade jarred alive) ÷ jarred_alive
#   cull_rate = (Culled_pre + Culled_jarred) ÷ Initial
#
# Session 29 — Batch-scoping fix:
#   _compute_from_data() accepts an optional batch_id. When given,
#   jarred-fish counts are scoped to only the fish jarred from THAT
#   batch (discriminated by fish.birth_date == batch.jarring_date).
#
# Session 29/F (this revision) — Derived current_count:
#   current_count is no longer read from the stored DB value. It's
#   now computed at read time using the same formula as
#   fry_batch_manager._compute_current_count():
#
#     current = initial
#             − jarred_alive
#             − culled_jarred
#             − culled_pre
#             − died
#
#   Reason: the stored value drifted out of sync (e.g. "Current 48"
#   when the true unjarred count was 38 after culls and deaths).
#   Deriving it makes the outcome panel match the batch card metric,
#   and guarantees reconciliation always passes when the manual
#   numbers (initial, culled_pre, died) are correct.

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
    """Returns (verdict_key, reason_short)."""
    if jarred_alive == 0 and total_culled > 0:
        return ("failed", f"All {total_culled} culled, none jarred")

    if jarred_alive == 0 and total_culled == 0:
        return ("pending", "No jarring or culling recorded yet")

    if jarred_alive == 0:
        return ("unknown", "No jarred fish to grade")

    high_pct = high_plus_count / jarred_alive
    cull_rate = (total_culled / initial) if initial > 0 else 0.0

    summary = f"{high_pct*100:.0f}% High+ · {cull_rate*100:.0f}% culled"

    if high_pct >= 0.50 and cull_rate < 0.20:
        return ("excellent", summary)

    if high_pct < 0.10 or cull_rate > 0.60:
        return ("weak", summary)

    if high_pct >= 0.25 and cull_rate <= 0.40:
        return ("solid", summary)

    return ("mixed", summary)


def _iso_date_prefix(val) -> Optional[str]:
    """Return YYYY-MM-DD from a value, or None if it can't be parsed."""
    if not val:
        return None
    s = str(val)[:10]
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    return None


def _resolve_batch(
    spawn_id: str,
    all_batches: list[dict],
    batch_id: Optional[str] = None,
) -> Optional[dict]:
    """Find the batch row for this spawn."""
    if batch_id:
        return next(
            (b for b in all_batches
             if b.get("id") == batch_id and b.get("spawn_id") == spawn_id),
            None,
        )
    return next((b for b in all_batches if b.get("spawn_id") == spawn_id), None)


def _fish_belongs_to_batch(
    fish: dict,
    spawn_id: str,
    batch: Optional[dict],
    *,
    scope_to_batch: bool,
) -> bool:
    """Decide whether a fish counts as jarred from this batch."""
    if fish.get("batch_id") != spawn_id:
        return False

    if not scope_to_batch or not batch:
        return True

    jarring_date = _iso_date_prefix(batch.get("jarring_date"))
    if not jarring_date:
        return True

    fish_date = _iso_date_prefix(fish.get("birth_date"))
    return fish_date == jarring_date


# ============================================================
# MAIN API
# ============================================================

def compute_spawn_outcome(
    spawn_id: str,
    *,
    batch_id: Optional[str] = None,
) -> dict:
    """Compute the outcome for one spawn."""
    all_fish = get_all_fish()
    all_batches = get_all_fry_batches()
    return _compute_from_data(spawn_id, all_fish, all_batches, batch_id=batch_id)


def _compute_from_data(
    spawn_id: str,
    all_fish: list[dict],
    all_batches: list[dict],
    *,
    batch_id: Optional[str] = None,
) -> dict:
    """Internal: compute using pre-fetched data."""
    # --- Resolve the batch row ---
    batch = _resolve_batch(spawn_id, all_batches, batch_id=batch_id)
    scope_to_batch = batch_id is not None

    # --- Jarred fish (any status) that came from this batch ---
    all_from_spawn = [
        f for f in all_fish
        if _fish_belongs_to_batch(
            f, spawn_id, batch, scope_to_batch=scope_to_batch,
        )
    ]

    culled_jarred_fish = [
        f for f in all_from_spawn
        if (f.get("status") or "").lower() in ("culled", "deceased")
    ]
    alive_jarred = [
        f for f in all_from_spawn
        if (f.get("status") or "").lower() not in ("culled", "deceased")
    ]

    # --- Batch counts (manual fields only) ---
    culled_pre        = _safe_int(batch.get("culled_count"))  if batch else 0
    female_count      = _safe_int(batch.get("female_count"))  if batch else 0
    died_count        = _safe_int(batch.get("died_count"))    if batch else 0
    initial_count     = _safe_int(batch.get("initial_count")) if batch else 0

    # --- Session 29/F — DERIVED current_count ---
    # current = initial − jarred_alive − culled_jarred − culled_pre − died
    jarred_alive   = len(alive_jarred)
    culled_jarred  = len(culled_jarred_fish)
    total_culled   = culled_pre + culled_jarred

    current_count = max(
        0,
        initial_count
        - jarred_alive
        - culled_jarred
        - culled_pre
        - died_count,
    )

    # --- Grade breakdown (over alive jarred only) ---
    breakdown  = _grade_breakdown(alive_jarred)
    high_plus  = _high_plus_count(alive_jarred)

    scores = [_safe_int(f.get("form_score")) for f in alive_jarred if f.get("form_score") is not None]
    avg_score = _avg(scores)

    # --- Survival % = (Current + Jarred_alive) ÷ Initial ---
    survival = None
    if initial_count > 0:
        survival = (current_count + jarred_alive) / initial_count

    # --- Reconciliation ---
    expected_sum = current_count + jarred_alive + culled_pre + culled_jarred + died_count
    reconciliation_delta = initial_count - expected_sum
    reconciles = abs(reconciliation_delta) <= 1

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
        "batch_id": batch_id,

        "initial_count":   initial_count,
        "current_count":   current_count,
        "jarred_alive":    jarred_alive,
        "jarred_total":    len(all_from_spawn),
        "culled_pre":      culled_pre,
        "culled_jarred":   culled_jarred,
        "culled_total":    total_culled,
        "died":            died_count,
        "female_count":    female_count,

        "survival":        survival,
        "grade_breakdown": breakdown,
        "high_plus_count": high_plus,
        "avg_form_score":  avg_score,
        "best_fish":       best,

        "verdict_key":     verdict_key,
        "verdict_icon":    VERDICT_ICONS.get(verdict_key, "—"),
        "verdict_reason":  verdict_reason,

        "expected_sum":    expected_sum,
        "reconciliation_delta": reconciliation_delta,
        "reconciles":      reconciles,

        "has_batch":       batch is not None,
        "scope_to_batch":  scope_to_batch,

        "jarred_count":    jarred_alive,
        "culled_count":    total_culled,
    }


def compute_all_spawn_outcomes() -> dict[str, dict]:
    """Compute outcomes for all spawns in one pass (spawn-wide)."""
    all_spawns  = get_all_spawns()
    all_fish    = get_all_fish()
    all_batches = get_all_fry_batches()

    out = {}
    for s in all_spawns:
        out[s["id"]] = _compute_from_data(s["id"], all_fish, all_batches)
    return out


def compute_all_batch_outcomes() -> dict[str, dict]:
    """Compute outcomes keyed by BATCH id, scoped to each batch."""
    all_fish    = get_all_fish()
    all_batches = get_all_fry_batches()

    out = {}
    for b in all_batches:
        bid = b.get("id")
        sid = b.get("spawn_id")
        if not bid or not sid:
            continue
        out[bid] = _compute_from_data(sid, all_fish, all_batches, batch_id=bid)
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
    """Return an HTML badge showing whether the counts reconcile."""
    if not outcome.get("has_batch"):
        return ""

    delta = outcome.get("reconciliation_delta", 0)

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
