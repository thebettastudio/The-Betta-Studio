"""
Central place for enums and constants used across the app.
If you change a value here, it updates everywhere.
"""

# ============================================================
# FISH
# ============================================================
FISH_STAGES = [
    "egg",
    "fry",
    "juvenile",
    "sub_adult",
    "adult",
    "breeder",
    "retired",
]

FISH_STAGE_LABELS = {
    "egg":       "🥚 Egg",
    "fry":       "🐟 Fry",
    "juvenile":  "🐠 Juvenile",
    "sub_adult": "🐡 Sub-adult",
    "adult":     "🐟 Adult",
    "breeder":   "⭐ Breeder",
    "retired":   "🌿 Retired",
}

FISH_STATUSES = ["active", "sold", "deceased", "culled", "escaped"]

FISH_STATUS_LABELS = {
    "active":   "🟢 Active",
    "sold":     "💰 Sold",
    "deceased": "⚫ Deceased",
    "culled":   "🗑️ Culled",
    "escaped":  "❓ Escaped",
}

FISH_GENDERS = ["male", "female", "unknown"]

FISH_GENDER_LABELS = {
    "male":    "♂ Male",
    "female":  "♀ Female",
    "unknown": "❔ Unknown",
}

# ============================================================
# TANKS
# ============================================================
TANK_TYPES = [
    "big_plangana",       # grow-out
    "small_plangana",     # breeding pair
    "empi",               # jarring
    "wilkins_6l",         # breeder conditioning
    "community",          # mixed
    "quarantine",         # sick/new fish
    "sump",               # filtration
    "other",              # custom
]

TANK_TYPE_LABELS = {
    "big_plangana":    "🌊 Big Plangana (Grow-out)",
    "small_plangana":  "💞 Small Plangana (Breeding)",
    "empi":            "🫙 Empi (Jarring)",
    "wilkins_6l":      "💧 Wilkins 6L (Conditioning)",
    "community":       "👥 Community",
    "quarantine":      "🩺 Quarantine",
    "sump":            "⚙️ Sump",
    "other":           "📦 Other",
}

TANK_STATUSES = ["empty", "occupied", "breeding", "quarantine", "maintenance"]

TANK_STATUS_LABELS = {
    "empty":       "⚪ Empty",
    "occupied":    "🟢 Occupied",
    "breeding":    "❤️ Breeding",
    "quarantine":  "🩺 Quarantine",
    "maintenance": "🔧 Maintenance",
}

# ============================================================
# SPAWNS
# ============================================================
SPAWN_OUTCOMES = ["pending", "success", "failed", "partial"]

SPAWN_OUTCOME_LABELS = {
    "pending": "⏳ Pending",
    "success": "✅ Success",
    "failed":  "❌ Failed",
    "partial": "⚠️ Partial",
}

# ============================================================
# ID PREFIXES (structured ID generation)
# ============================================================
ID_PREFIXES = {
    "breeder_male":   "BRD-M",
    "breeder_female": "BRD-F",
    "fish":           "FSH",
    "tank":           "TNK",
    "spawn":          "SPN",
    "fry_batch":      "FBT",
    "inventory":      "INV",
}
