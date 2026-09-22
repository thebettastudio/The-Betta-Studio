# modules/fish_manager.py
import re
import datetime
import pandas as pd
import streamlit as st
from typing import List, Dict, Tuple, Optional

# Standard headers for the Fish Registry sheet
FISH_REGISTRY_HEADERS = [
    "fish_id",
    "origin",            # "Purchased" or "Batch Spawn"
    "batch_id",          # e.g., "SP01" or empty if purchased
    "line_code",         # e.g., "DRG" or "UNK"
    "generation",        # e.g., "F1" or "P1"
    "sire_id",           # Male Parent Fish ID or "N/A"
    "dam_id",            # Female Parent Fish ID or "N/A"
    "gender",            # "Male", "Female", or "Unsexed"
    "variety",           # e.g., "Red Dragon HMPK"
    "grade",             # "Show Grade", "High Grade", "Pet Grade"
    "image_url",         # Drive link / Photo ID
    "location",          # Tank / Jar location
    "purchase_date",     # ISO date string or empty
    "seller",            # Seller / Import source or empty
    "purchase_cost",     # Numeric cost or 0
    "is_breeder",        # True / False
    "status",            # "Jarred", "Active", "For Sale", "Sold", "Deceased", "Retired"
    "notes",
    "created_at"
]

def generate_purchased_fish_id(variety: str, gender: str, existing_ids: List[str]) -> str:
    """
    Generates a unique ID for purchased fish.
    Format: PUR-[VARIETY_CODE]-[M/F/U][INDEX]
    Example: PUR-HMPK-M01
    """
    # Extract short code from variety (e.g. Halfmoon Plakat -> HMPK)
    words = re.findall(r'\b\w', variety.upper()) if variety else []
    var_code = "".join(words)[:4] if words else "BET"
    
    g_str = (gender or "U").strip().lower()
    if g_str.startswith("m"):
        g_code = "M"
    elif g_str.startswith("f"):
        g_code = "F"
    else:
        g_code = "U"
        
    prefix = f"PUR-{var_code}-{g_code}"
    
    # Calculate sequential index
    matches = [i for i in existing_ids if i.startswith(prefix)]
    next_idx = len(matches) + 1
    return f"{prefix}{next_idx:02d}"


def generate_batch_fish_id(batch_code: str, existing_ids: List[str]) -> str:
    """
    Generates a unique ID for jarred fry from a batch.
    Format: [BATCH_CODE]-[INDEX]
    Example: DRG-F1-01, SP01-F1-05
    """
    clean_batch = batch_code.strip() if batch_code else "BATCH"
    prefix = f"{clean_batch}-"
    
    matches = [i for i in existing_ids if i.startswith(prefix)]
    next_idx = len(matches) + 1
    return f"{prefix}{next_idx:02d}"


def get_all_fish() -> List[Dict]:
    """
    Retrieves all registered fish from session state or storage backend.
    """
    if "fish_registry" not in st.session_state:
        st.session_state["fish_registry"] = []
    return st.session_state["fish_registry"]


def register_new_fish(fish_data: Dict) -> str:
    """
    Registers a new individual fish into the Master Fish Registry.
    """
    if "fish_registry" not in st.session_state:
        st.session_state["fish_registry"] = []
        
    fish_record = {
        "fish_id": fish_data["fish_id"],
        "origin": fish_data.get("origin", "Purchased"),
        "batch_id": fish_data.get("batch_id", "N/A"),
        "line_code": fish_data.get("line_code", "UNK"),
        "generation": fish_data.get("generation", "P1"),
        "sire_id": fish_data.get("sire_id", "N/A"),
        "dam_id": fish_data.get("dam_id", "N/A"),
        "gender": fish_data.get("gender", "Unsexed"),
        "variety": fish_data.get("variety", ""),
        "grade": fish_data.get("grade", "High Grade"),
        "image_url": fish_data.get("image_url", ""),
        "location": fish_data.get("location", "Unassigned"),
        "purchase_date": fish_data.get("purchase_date", ""),
        "seller": fish_data.get("seller", ""),
        "purchase_cost": fish_data.get("purchase_cost", 0.0),
        "is_breeder": False,
        "status": fish_data.get("status", "Active"),
        "notes": fish_data.get("notes", ""),
        "created_at": datetime.date.today().isoformat()
    }
    
    st.session_state["fish_registry"].append(fish_record)
    return fish_record["fish_id"]


def promote_fish_to_breeder(fish_id: str) -> bool:
    """
    Promotes a registered fish to active breeder status while preserving its exact fish_id.
    """
    fish_list = get_all_fish()
    for fish in fish_list:
        if fish["fish_id"] == fish_id:
            fish["is_breeder"] = True
            fish["status"] = "Conditioning"
            
            # Synchronize with Breeders Registry session state if present
            if "breeders" not in st.session_state:
                st.session_state["breeders"] = []
                
            # Check if breeder entry already exists
            existing_breeder = next((b for b in st.session_state["breeders"] if b.get("id") == fish_id), None)
            if not existing_breeder:
                breeder_record = {
                    "id": fish["fish_id"],
                    "gender": fish["gender"],
                    "variety": fish["variety"],
                    "line_code": fish["line_code"],
                    "generation": fish["generation"],
                    "grade": fish["grade"],
                    "status": "Available",
                    "tank_location": fish["location"],
                    "photo_id": fish["image_url"],
                    "sire_id": fish["sire_id"],
                    "dam_id": fish["dam_id"],
                    "notes": fish["notes"]
                }
                st.session_state["breeders"].append(breeder_record)
            return True
            
    return False


def get_existing_fish_ids() -> List[str]:
    """
    Utility function to retrieve all existing fish IDs for uniqueness checking.
    """
    return [f["fish_id"] for f in get_all_fish()]
