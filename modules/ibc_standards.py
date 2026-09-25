# modules/ibc_standards.py
# Betta Farm Management System
# Session 26E — IBC standards extracted as reference rules.
#
# Source: International Betta Congress (IBC) Exhibition Standards.
# This module is DATA + pure functions — no app dependencies.
#
# Used by:
#   modules/fish_grader.py (future Session 26F) — applies rules
#   to measurements from color_detector.py
#
# Nothing in here talks to Supabase, Streamlit, or the color detector.
# It's a portable reference.

from __future__ import annotations
from typing import Optional


# ============================================================
# SCORING SYSTEM
# ============================================================

IBC_BASE_SCORE = 100

FAULT_DEDUCTIONS = {
    "slight":        3,     # cosmetic
    "minor":         5,     # noticeable but not disqualifying
    "major":         9,     # significant defect
    "severe":       17,     # very serious
    "disqualifying": 999,   # DQ — fish cannot be shown
}

GRADE_THRESHOLDS = [
    # (minimum_score, grade_name)
    (95, "Show Grade"),
    (85, "High Grade"),
    (70, "Breeder Grade"),
    (0,  "Pet Grade"),
]


# ============================================================
# MEASURABLE CRITERIA — shared across form types
# ============================================================
# These ranges define acceptable values for measurable properties.
# App-side measurements come from the 5-region color_detector split.

MEASURABLE_CRITERIA = {
    "body_length_depth_ratio": {
        "ideal_min": 3.0,
        "ideal_max": 4.0,
        "fault_if_below": 2.5,      # too stubby → major fault
        "fault_if_above": 4.5,      # too elongated → minor fault
        "description": "Length to depth ratio (male typical 3:1 to 4:1)",
    },
    "caudal_spread_degrees": {
        "ideal": 180,
        "preferred_min": 180,
        "preferred_max": 190,       # over-180 slightly preferred, not faulted
        "minor_fault_below": 170,
        "major_fault_below": 165,
        "description": "Angle between top and bottom caudal edges",
    },
    "caudal_length_to_body": {
        "ideal_min": 0.5,           # caudal ≥ 1/2 body length
        "fault_if_below": 0.4,
        "description": "Caudal fin length as fraction of body length",
    },
    "anal_length_to_body": {
        "ideal_min": 0.5,
        "fault_if_below": 0.4,
        "description": "Anal fin length as fraction of body length",
    },
    "ventral_length_to_body": {
        "ideal_min": 0.66,          # ~2/3 body length
        "fault_if_below": 0.5,
        "description": "Ventral fin length as fraction of body length",
    },
    "pectoral_length_to_body": {
        "ideal_min": 0.5,
        "fault_if_below": 0.35,
        "description": "Pectoral fin length as fraction of body length",
    },
    "dorsal_base_to_anal_base": {
        "ideal_max": 0.5,           # dorsal base ≤ 1/2 anal base
        "fault_if_above": 0.7,
        "description": "Dorsal fin base width relative to anal fin base width",
    },
}


# ============================================================
# FIN SHAPE RULES
# ============================================================
# These describe ideal/accepted/unacceptable shapes per fin.
# "Auto-detectable" flags note whether our classical CV can
# realistically classify them.

FIN_SHAPE_RULES = {
    "dorsal": {
        "accepted_shapes": ["semi_circle", "quarter_circle", "rectangular"],
        "unacceptable_shapes": ["triangular", "spiky"],
        "must_overlap_caudal": False,   # preferred but not required
        "auto_detectable": False,       # needs landmark model
        "ibc_notes": "Full, wide base, no rounded edges at corners",
    },
    "caudal": {
        "accepted_shapes": ["semi_circle", "180_spread"],
        "unacceptable_shapes": ["spade", "spike", "forked"],
        "spread_ideal_degrees": 180,
        "rays_uniform_required": True,
        "auto_detectable": True,        # via spread angle
        "ibc_notes": "Rays evenly spaced with no gaps",
    },
    "anal": {
        "accepted_shapes": ["trapezoid_pointed_tip"],
        "unacceptable_shapes": ["triangle", "flat", "rounded"],
        "must_slope_front_to_back": True,
        "parallel_rays_required": True,
        "auto_detectable": True,        # via slope measurement
        "ibc_notes": "Distinct corners, pointed tip, front-to-back slope",
    },
    "ventral": {
        "accepted_shapes": ["straight_broad"],
        "unacceptable_shapes": ["curled", "twisted", "narrow"],
        "must_be_straight": True,
        "auto_detectable": False,
        "ibc_notes": "Straight, broad, no curl",
    },
    "pectoral": {
        "accepted_shapes": ["full_rounded"],
        "unacceptable_shapes": ["short", "torn", "thin"],
        "auto_detectable": False,
        "ibc_notes": "Large, full, ~1/2 body length",
    },
}


# ============================================================
# FORM TYPE STANDARDS
# ============================================================
# Per-morph requirements. The 5 most common betta show classes.

FORM_TYPES = {
    "HMPK": {   # Halfmoon Plakat
        "display_name": "Halfmoon Plakat",
        "caudal_spread_ideal": 180,
        "caudal_spread_minor_fault": 170,
        "body_length_depth_ratio": (3.0, 4.0),
        "anal_trapezoid_required": True,
        "dorsal_overlap_required": True,
        "ventral_broad_required": True,
        "notes": "Symmetrical show class; 180° spread and matched fins required",
    },
    "HM": {     # Halfmoon
        "display_name": "Halfmoon",
        "caudal_spread_ideal": 180,
        "caudal_spread_minor_fault": 170,
        "body_length_depth_ratio": (3.0, 4.0),
        "caudal_must_reach_anal_fin": True,
        "dorsal_overlap_required": True,
        "notes": "Long-finned; caudal must reach past anal fin base",
    },
    "PK": {     # Plakat (traditional)
        "display_name": "Plakat",
        "caudal_spread_ideal": 180,
        "caudal_spread_minor_fault": 160,
        "body_length_depth_ratio": (2.8, 3.5),
        "short_fins": True,
        "notes": "Short-finned; fins shorter than HMPK",
    },
    "CT": {     # Crowntail
        "display_name": "Crowntail",
        "caudal_spread_ideal": 180,
        "webbing_reduction_min_pct": 33,      # minimum reduction in webbing vs ray
        "webbing_reduction_ideal_pct": 50,
        "webbing_reduction_dq_threshold": 33, # below this in 2+ fins = DQ
        "random_rays_fault": "minor",
        "curled_rays_fault": "minor",
        "notes": "Webbing reduced ≥33% in primary fins for males",
    },
    "DT": {     # Double Tail
        "display_name": "Double Tail",
        "caudal_spread_ideal": 180,
        "body_length_depth_ratio": (3.0, 4.0),
        "two_lobes_required": True,
        "notes": "Caudal split into two distinct lobes",
    },
}


# ============================================================
# COLOR CLASS RULES
# ============================================================
# Faults per color class. These apply to specific color morphs.

COLOR_CLASS_RULES = {
    "red": {
        "required_traits": ["dark_undercoat"],
        "minor_faults": ["black_edges"],
        "major_faults": ["iridescence"],
        "severe_faults": ["yellow_presence", "orange_presence"],
        "slight_faults": ["white_ventrals"],
    },
    "black": {
        "ideal_trait": "black_mollic",
        "minor_faults": ["red_on_fins"],
        "major_faults": ["extensive_iridescence"],
        "notes": "Black mollic = deep opaque black",
    },
    "blue_iridescent": {
        "minor_faults": ["anal_fin_wash"],
        "major_faults": [],
        "notes": "Blue / Steel / Turquoise / Green iridescent classes",
    },
    "marble": {
        "ideal_blend_pct": 50,               # 50% light / 50% dark
        "major_fault_if_below_pct": 25,      # <25% of either color
        "butterfly_accepted": True,
        "notes": "Random patches of light and dark",
    },
    "multicolor": {
        "min_colors_required": 3,
        "min_bright_colors": 1,
        "minor_fault_if_all_fins_only_2_colors": True,
        "major_fault_if_dull": True,
        "notes": "At least 3 distinct colors with at least 1 bright",
    },
    "butterfly": {
        "required_pattern": "color_on_fin_edges",
        "notes": "Butterfly = color edge on fins against solid body",
    },
}


# ============================================================
# PUBLIC HELPERS
# ============================================================

def get_fault_deduction(fault_type: str) -> int:
    """Return the point deduction for a fault type."""
    return FAULT_DEDUCTIONS.get(fault_type, 0)


def score_to_grade(score: int) -> str:
    """Convert a 0-100 IBC score to a grade label."""
    for min_score, label in GRADE_THRESHOLDS:
        if score >= min_score:
            return label
    return "Pet Grade"


def get_form_standard(form_type: str) -> Optional[dict]:
    """Look up standards for a form type (e.g. 'HMPK', 'HM')."""
    return FORM_TYPES.get((form_type or "").upper())


def get_criteria(key: str) -> Optional[dict]:
    """Look up a measurable criterion definition."""
    return MEASURABLE_CRITERIA.get(key)


def get_fin_rules(fin: str) -> Optional[dict]:
    """Look up shape rules for a fin type."""
    return FIN_SHAPE_RULES.get((fin or "").lower())


def get_color_class_rules(color_class: str) -> Optional[dict]:
    """Look up fault rules for a color class."""
    return COLOR_CLASS_RULES.get((color_class or "").lower())


def evaluate_measurement(
    key: str,
    value: float,
) -> Optional[dict]:
    """
    Given a measurement key and its numeric value, return a dict:
      {
        "key": key,
        "value": value,
        "status": "pass" | "slight" | "minor" | "major" | "severe",
        "fault_points": int,
        "reason": str,
      }
    Or None if the criterion isn't defined.

    Uses MEASURABLE_CRITERIA ranges to determine fault level.
    """
    crit = MEASURABLE_CRITERIA.get(key)
    if not crit or value is None:
        return None

    status = "pass"
    reason = "Within IBC range"
    fault_points = 0

    # Handle different criterion shapes
    if "ideal_min" in crit and "ideal_max" in crit:
        lo = crit["ideal_min"]
        hi = crit["ideal_max"]
        if value < lo:
            if "fault_if_below" in crit and value < crit["fault_if_below"]:
                status = "major"
            else:
                status = "minor"
            reason = f"Below ideal minimum {lo}"
        elif value > hi:
            if "fault_if_above" in crit and value > crit["fault_if_above"]:
                status = "major"
            else:
                status = "minor"
            reason = f"Above ideal maximum {hi}"
    elif "ideal_min" in crit:
        lo = crit["ideal_min"]
        if value < lo:
            if "fault_if_below" in crit and value < crit["fault_if_below"]:
                status = "major"
            else:
                status = "minor"
            reason = f"Below ideal minimum {lo}"
    elif "ideal_max" in crit:
        hi = crit["ideal_max"]
        if value > hi:
            if "fault_if_above" in crit and value > crit["fault_if_above"]:
                status = "major"
            else:
                status = "minor"
            reason = f"Above ideal maximum {hi}"

    if status != "pass":
        fault_points = get_fault_deduction(status)

    return {
        "key": key,
        "value": value,
        "status": status,
        "fault_points": fault_points,
        "reason": reason,
    }
