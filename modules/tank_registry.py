import datetime
import uuid
import re
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from modules.google_auth import get_credentials, SPREADSHEET_ID, PARENT_FOLDER_ID

# Define Google Sheets Worksheet Name for Containers
TANK_SHEET_NAME = "Tanks_Registry"


def get_sheets_service():
    """Initializes and returns the Google Sheets API service."""
    creds = get_credentials()
    return build("sheets", "v4", credentials=creds)


def get_drive_service():
    """Initializes and returns the Google Drive API service."""
    creds = get_credentials()
    return build("drive", "v3", credentials=creds)


def _ensure_sheet_exists():
    """Ensures that the 'Tanks_Registry' worksheet exists and has header row."""
    service = get_sheets_service()
    sheet_metadata = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    sheets = sheet_metadata.get("sheets", [])
    
    sheet_names = [s["properties"]["title"] for s in sheets]
    
    if TANK_SHEET_NAME not in sheet_names:
        # Create worksheet
        body = {
            "requests": [{
                "addSheet": {
                    "properties": {
                        "title": TANK_SHEET_NAME
                    }
                }
            }]
        }
        service.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, body=body).execute()
        
        # Add headers
        headers = [
            "Tank ID",
            "Location Code",
            "Type",
            "Capacity (L)",
            "Purpose",
            "Status",
            "Current Occupant",
            "Notes",
            "Photo ID",
            "Registered Date"
        ]
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{TANK_SHEET_NAME}!A1",
            valueInputOption="USER_ENTERED",
            body={"values": [headers]}
        ).execute()


def upload_container_photo(file_obj, filename_prefix="TANK"):
    """
    Uploads a photo to Google Drive and sets public read permissions for display in Streamlit.
    Returns (file_id, direct_view_url).
    """
    if not file_obj:
        return "", ""

    drive_service = get_drive_service()
    
    # Define file metadata
    file_metadata = {
        "name": f"{filename_prefix}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg",
        "parents": [PARENT_FOLDER_ID] if PARENT_FOLDER_ID else []
    }
    
    # Upload media
    media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type or "image/jpeg", resumable=True)
    uploaded_file = drive_service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, webViewLink"
    ).execute()
    
    file_id = uploaded_file.get("id")
    
    # Make file publicly readable for image rendering
    try:
        drive_service.permissions().create(
            fileId=file_id,
            body={"role": "reader", "type": "anyone"}
        ).execute()
    except Exception:
        pass

    direct_url = f"https://drive.google.com/thumbnail?id={file_id}&sz=w800"
    return file_id, direct_url


def generate_location_code(container_type, existing_tanks):
    """
    Generates a concise, short code suitable for writing on painter's tape.
    E.g., Grow-Out Planggana -> PLG-G-001
    """
    type_clean = container_type.upper()
    
    if "PLANGGANA" in type_clean:
        prefix = "PLG-G" if "GROW" in type_clean or "LARGE" in type_clean else "PLG-S"
    elif "BOTTLE" in type_clean or "WATER" in type_clean:
        prefix = "BOT-6L"
    elif "EMPI" in type_clean or "EMPERADOR" in type_clean:
        prefix = "JAR-EMP"
    elif "AQUARIUM" in type_clean or "GLASS" in type_clean:
        prefix = "AQ-GLS"
    elif "SORORITY" in type_clean or "BASIN" in type_clean:
        prefix = "PLG-SOR"
    elif "QUARANTINE" in type_clean or "TREATMENT" in type_clean:
        prefix = "JAR-MED"
    else:
        # Fallback short code generator for custom entries
        clean_words = re.sub(r'[^A-Z0-9 ]', '', type_clean).split()
        prefix = "".join([w[0] for w in clean_words[:3]]) if clean_words else "TNK"

    # Find highest current index with this prefix
    count = 1
    for t in existing_tanks:
        code = t.get("location", "")
        if code.startswith(prefix):
            try:
                num_part = int(code.split("-")[-1])
                if num_part >= count:
                    count = num_part + 1
            except ValueError:
                pass

    return f"{prefix}-{count:03d}"


def register_tank(tank_type, capacity_liters, purpose, photo_file=None, current_occupant="", notes=""):
    """
    Registers a new container/tank entry into Google Sheets.
    """
    _ensure_sheet_exists()
    
    existing_tanks = get_all_tanks()
    
    tank_id = f"TNK-{datetime.datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"
    location_code = generate_location_code(tank_type, existing_tanks)
    
    # Upload photo if supplied
    photo_id, direct_photo_url = "", ""
    if photo_file:
        photo_id, direct_photo_url = upload_container_photo(photo_file, filename_prefix=location_code)

    registered_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    initial_status = "Active"

    row_data = [
        tank_id,
        location_code,
        tank_type,
        capacity_liters,
        purpose,
        initial_status,
        current_occupant,
        notes,
        photo_id,
        registered_date
    ]

    service = get_sheets_service()
    service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{TANK_SHEET_NAME}!A:J",
        valueInputOption="USER_ENTERED",
        body={"values": [row_data]}
    ).execute()

    return {
        "tank_id": tank_id,
        "location_code": location_code,
        "direct_photo_url": direct_photo_url
    }


def get_all_tanks():
    """
    Fetches all registered tanks/containers from Google Sheets.
    """
    _ensure_sheet_exists()
    service = get_sheets_service()
    
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{TANK_SHEET_NAME}!A:J"
    ).execute()
    
    rows = result.get("values", [])
    if len(rows) <= 1:
        return []

    tanks = []
    # Skip header row
    for row in rows[1:]:
        # Safeguard against short rows missing trailing columns
        row_padded = row + [""] * (10 - len(row))
        tanks.append({
            "id": row_padded[0],
            "location": row_padded[1],
            "type": row_padded[2],
            "capacity": row_padded[3],
            "purpose": row_padded[4],
            "status": row_padded[5],
            "occupant": row_padded[6],
            "notes": row_padded[7],
            "photo_id": row_padded[8],
            "registered_date": row_padded[9]
        })

    return tanks


def update_tank_status(tank_id, new_status, new_purpose, new_occupant, new_notes):
    """
    Updates status, purpose, occupant, and notes for an existing tank ID in Google Sheets.
    """
    _ensure_sheet_exists()
    service = get_sheets_service()
    
    # Read existing rows to find matching row index
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{TANK_SHEET_NAME}!A:A"
    ).execute()
    
    id_column = result.get("values", [])
    row_index = None

    for idx, row in enumerate(id_column):
        if row and row[0] == tank_id:
            row_index = idx + 1  # 1-based index for Google Sheets API
            break

    if not row_index:
        return False

    # Update columns E to H (Purpose, Status, Current Occupant, Notes)
    # Col E (5) = Purpose, Col F (6) = Status, Col G (7) = Occupant, Col H (8) = Notes
    update_values = [[new_purpose, new_status, new_occupant, new_notes]]
    
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{TANK_SHEET_NAME}!E{row_index}:H{row_index}",
        valueInputOption="USER_ENTERED",
        body={"values": update_values}
    ).execute()

    return True
