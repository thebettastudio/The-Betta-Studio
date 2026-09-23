# modules/id_generator.py
# Betta Farm Management System
# Session 5 — centralized ID generation. Single source of truth.
#
# ID schemes:
#   Fish (manual)      : FISH-NNNN              e.g. FISH-0042
#   Fish (batch-born)  : {SPAWN_SYS_ID}-NN      e.g. SPN-AVT-F1-01-03
#   Tank system_id     : TNNNNN                 e.g. T00042
#   Tank tape code     : {PREFIX}-NNNN          e.g. JAR-0007, SPN-0012
#   Spawn system_id    : SPN-{LINE}-{GEN}-NN    e.g. SPN-AVT-F1-01
#   Spawn spawn_code   : SPN-YY-NN              e.g. SPN-26-01
#
# Lineage is NEVER reconstructed from IDs. It comes from DB relationships
# (fish.sire_id, fish.dam_id, fish.batch_id). IDs are human labels only.

from __future__ import annotations

import datetime as _dt
import re
from typing import Iterable, Optional, Tuple

from database import (
    get_all_fish,
    get_all_tanks,
    get_all_spawns,
)


# ============================================================
# CONSTANTS
# ============================================================

PURPOSE_TO_PREFIX = {
    "Jarring":        "JAR",
    "Conditioning":   "COND",
    "Spawning":       "SPN",
    "Fry Nursery":    "FRY",
    "Grow-Out":       "GO",
    "Sorority":       "SOR",
    "Quarantine":     "QT",
    "Sales Display":  "SALES",
    "Storage":        "STOR",
    "Other":          "MISC",
}

FISH_PREFIX = "FISH-"
TANK_PREFIX = "T"
SPAWN_PREFIX = "SPN-"

SANITIZE_RE = re.compile(r"[^A-Z0-9]")


# ============================================================
# LOW-LEVEL HELPERS
# ============================================================

def _sanitize(code: str, max_len: int = 8) -> str:
    """
    Uppercase, strip non-alphanumerics. Used for line codes in IDs.
    If empty after sanitizing, returns 'UNK'.
    """
    if not code:
        return "UNK"
    clean = SANITIZE_RE.sub("", str(code).upper())
    if not clean:
        return "UNK"
    return clean[:max_len]


def _next_sequence(existing: Iterable[str], prefix: str, width: int) -> int:
    """
    Return the next integer N such that prefix+N doesn't collide.
    Existing must be an iterable of strings like 'FISH-0042' or 'JAR-0007'.
    """
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    nums = []
    for item in existing:
        m = pattern.match(str(item).strip())
        if m:
            nums.append(int(m.group(1)))
    nxt = (max(nums) + 1) if nums else 1
    return nxt


# ============================================================
# FISH IDs
# ============================================================

def generate_fish_id() -> str:
    """
    Manual / purchased fish. Format: FISH-NNNN
    Sequential across all manual fish.
    """
    existing = [f.get("system_id") or "" for f in get_all_fish()]
    nxt = _next_sequence(existing, FISH_PREFIX, width=4)
    return f"{FISH_PREFIX}{nxt:04d}"


def generate_batch_fish_id(spawn_system_id: str, batch_size_hint: Optional[int] = None) -> str:
    """
    Batch-born fish. Format: {SPAWN_SYS_ID}-NN
    e.g. SPN-AVT-F1-01-03  (3rd fish from that spawn)

    `batch_size_hint` is ignored — kept for API compatibility.
    """
    if not spawn_system_id:
        spawn_system_id = "SPN-UNK-P1-01"

    prefix = f"{spawn_system_id}-"
    existing = [f.get("system_id") or "" for f in get_all_fish()]
    nxt = _next_sequence(existing, prefix, width=2)
    return f"{prefix}{nxt:02d}"


# ============================================================
# TANK IDs
# ============================================================

def generate_tank_system_id() -> str:
    """
    Tank internal system_id. Format: TNNNNN
    Sequential, unique across all tanks.
    """
    existing = [t.get("system_id") or "" for t in get_all_tanks()]
    nxt = _next_sequence(existing, TANK_PREFIX, width=5)
    return f"{TANK_PREFIX}{nxt:05d}"


def generate_tape_code(purpose: str) -> str:
    """
    Human-readable tape label. Format: {PREFIX}-NNNN
    Prefix is derived from PURPOSE, not tank type.
    Sequential per prefix — no random collisions.

    e.g. purpose='Jarring'  -> JAR-0007
         purpose='Spawning' -> SPN-0012
         purpose='Grow-Out' -> GO-0003
    """
    prefix = PURPOSE_TO_PREFIX.get((purpose or "").strip(), "MISC")
    label_prefix = f"{prefix}-"

    existing = [t.get("location_code") or "" for t in get_all_tanks()]
    nxt = _next_sequence(existing, label_prefix, width=4)
    return f"{label_prefix}{nxt:04d}"


# ============================================================
# SPAWN IDs
# ============================================================

def calculate_child_lineage(
    male_line: str,
    male_gen: str,
    female_line: str,
    female_gen: str,
) -> Tuple[str, str]:
    """
    Returns (child_line_code, child_generation).

    Rules (ported from spawn_manager.calculate_child_generation):
      - Different lines  -> '{M}x{F}' and 'F1'
      - Same line, both F -> increment gen
      - Both P1/F0        -> F1
      - One P1/F0 + F1    -> BC1 (backcross)
      - Otherwise         -> '{M}x{F}'
    """
    m_gen  = (male_gen  or "P1").strip().upper()
    f_gen  = (female_gen or "P1").strip().upper()
    m_line = _sanitize(male_line  or "UNK", max_len=8)
    f_line = _sanitize(female_line or "UNK", max_len=8)

    # Different lines -> outcross
    if m_line != f_line:
        return f"{m_line}x{f_line}", "F1"

    line_code = m_line

    # Same line, same F-generation -> increment
    if m_gen == f_gen and m_gen.startswith("F"):
        try:
            curr = int(m_gen.replace("F", ""))
            return line_code, f"F{curr + 1}"
        except ValueError:
            pass

    # Both wild / P1 -> F1
    if m_gen in ("P1", "F0") and f_gen in ("P1", "F0"):
        return line_code, "F1"

    # P1 x F1 -> backcross
    if (m_gen in ("P1", "F0") or f_gen in ("P1", "F0")) and \
       ("F1" in (m_gen, f_gen)):
        return line_code, "BC1"

    # Fallback: encode both gens
    return line_code, f"{m_gen}x{f_gen}"


def generate_spawn_system_id(
    male_line: str,
    male_gen: str,
    female_line: str,
    female_gen: str,
) -> str:
    """
    Genealogical spawn ID. Format: SPN-{LINE}-{GEN}-NN
    e.g. SPN-AVT-F1-01
         SPN-AVTxRDG-F1-01  (outcross)
    """
    line_code, generation = calculate_child_lineage(
        male_line, male_gen, female_line, female_gen
    )

    prefix = f"{SPAWN_PREFIX}{line_code}-{generation}-"
    existing = [s.get("system_id") or "" for s in get_all_spawns()]
    nxt = _next_sequence(existing, prefix, width=2)
    return f"{prefix}{nxt:02d}"


def generate_spawn_code() -> str:
    """
    Compact year-scoped serial. Format: SPN-YY-NN
    e.g. SPN-26-01  (1st spawn of 2026)
    Resets each year.
    """
    yy = _dt.date.today().strftime("%y")
    prefix = f"{SPAWN_PREFIX}{yy}-"
    existing = [s.get("spawn_code") or "" for s in get_all_spawns()]
    nxt = _next_sequence(existing, prefix, width=2)
    return f"{prefix}{nxt:02d}"


# ============================================================
# CONVENIENCE
# ============================================================

def get_tank_prefix_for_purpose(purpose: str) -> str:
    """Expose prefix lookup for UI (e.g. showing what tape code will be generated)."""
    return PURPOSE_TO_PREFIX.get((purpose or "").strip(), "MISC")


def all_purposes() -> list[str]:
    """Return the canonical list of purposes for dropdowns."""
    return list(PURPOSE_TO_PREFIX.keys())
