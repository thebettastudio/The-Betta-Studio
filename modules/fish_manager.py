import io
import re
import datetime
import pandas as pd
import streamlit as st
from PIL import Image
from typing import List, Dict, Tuple, Optional

# Register HEIC opener for iPhone camera photos
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

# Import Drive & Sheets services
from modules.drive_service import get_google_services, SPREADSHEET_ID, DRIVE_FOLDER_ID

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


def process_and_compress_image(raw_bytes: bytes, max_dimension: int = 1280, quality: int = 85) -> bytes:
    """Processes, resizes, and compresses uploaded image bytes for mobile network optimization."""
    try:
        image = Image.open(io.BytesIO(raw_bytes))
        
        # Convert non-RGB modes (RGBA, P, HEIC) to standard RGB
        if image.mode in ("RGBA", "P"):
            image = image.convert("RGB")
            
        # Downscale photo if it exceeds max dimensions
        image.thumbnail((max_dimension, max_dimension))
        
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality)
        return buffer.getvalue()
    except Exception as e:
        st.warning(f"Note: Could not compress photo, using original file bytes ({e})")
        return raw_bytes


def upload_fish_photo_to_drive(image_bytes: bytes, filename_prefix: str = "fish_") -> Tuple[str, str]:
    """Compresses photo bytes, uploads to Google Drive, and returns (file_id, direct_view_url)."""
    from googleapiclient.http import MediaIoBaseUpload

    drive_service, _ = get_google_services()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"{filename_prefix}{timestamp}.jpg"

    compressed_bytes = process_and_compress_image(image_bytes)
    file_stream = io.BytesIO(compressed_bytes)

    metadata = {'name': file_name}
    if DRIVE_FOLDER_ID:
        metadata['parents'] = [DRIVE_FOLDER_ID.strip()]

    media = MediaIoBaseUpload(file_stream, mimetype='image/jpeg', resumable=False)
    uploaded = drive_service.files().create(
        body=metadata,
        media_body=media,
        fields='id'
    ).execute()

    file_id = uploaded.get('id')
    return file_id, f"https://lh3.googleusercontent.com/d/{file_id}"


def generate_purchased_fish_id(variety: str, gender: str, existing_ids: List[str]) -> str:
    """
    Generates a unique ID for purchased fish.
    Format: PUR-[VARIETY_CODE]-[M/F/U][INDEX]
    Example: PUR-HMPK-M01
    """
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


def register_new_fish(fish_data: Dict, image_bytes: Optional[bytes] = None) -> str:
    """
    Registers a new individual fish into the Master Fish Registry, uploading 
    the photo to Drive if photo bytes are provided.
    """
    if "fish_registry" not in st.session_state:
        st.session_state["fish_registry"] = []

    # Handle photo upload if bytes are passed
    final_image_url = fish_data.get("image_url", "")
    if image_bytes:
        try:
            file_id, drive_url = upload_fish_photo_to_drive(image_bytes)
            final_image_url = drive_url
        except Exception as e:
            st.error(f"Failed to upload fish photo to Drive: {e}")

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
        "image_url": final_image_url,
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

    # Sync to Google Sheets backend if connected
    try:
        _, sheets_service = get_google_services()
        sheet_row = [fish_record[h] for h in FISH_REGISTRY_HEADERS]
        sheets_service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range='Fish_Master!A:S',
            valueInputOption='USER_ENTERED',
            body={'values': [sheet_row]}
        ).execute()
        st.cache_data.clear()
    except Exception as e:
        st.warning(f"Note: Saved locally, but couldn't write to Google Sheets ({e})")

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
