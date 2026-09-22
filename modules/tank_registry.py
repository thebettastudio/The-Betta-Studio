# modules/tank_registry.py
import io
import random
import datetime
import qrcode
import streamlit as st
from googleapiclient.http import MediaIoBaseUpload
from modules.drive_service import (
    get_google_services,
    get_spreadsheet_id,
    get_drive_folder_id
)

def ensure_tanks_tab_exists(sheets_service, spreadsheet_id: str) -> None:
    """
    Ensures the 'Tanks' worksheet tab exists with proper headers in Google Sheets.
    """
    try:
        sheet_metadata = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets = sheet_metadata.get('sheets', [])
        sheet_titles = [s['properties']['title'] for s in sheets]

        # 1. Create 'Tanks' tab if missing
        if "Tanks" not in sheet_titles:
            body = {
                'requests': [{
                    'addSheet': {
                        'properties': {'title': 'Tanks'}
                    }
                }]
            }
            sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=body
            ).execute()

        # 2. Add header row if empty
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range='Tanks!A1:K1'
        ).execute()

        headers = result.get('values', [])
        if not headers:
            header_row = [
                "System ID", "Tank Type", "Tape Code", "Capacity (Liters)",
                "Status", "Purpose", "Current Occupant", "Photo Drive ID",
                "QR Drive ID", "Notes", "Date Registered"
            ]
            sheets_service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range='Tanks!A1:K1',
                valueInputOption='USER_ENTERED',
                body={'values': [header_row]}
            ).execute()

    except Exception as e:
        print(f"Warning: Failed during ensure_tanks_tab_exists execution: {e}")

def get_next_tank_id(sheets_service, spreadsheet_id: str) -> str:
    """Fetches existing IDs to compute the next sequential integer ID."""
    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range='Tanks!A2:A'
        ).execute()

        rows = result.get('values', [])
        max_id = 0

        for row in rows:
            if row and row[0]:
                val = str(row[0]).strip()
                if val.isdigit():
                    max_id = max(max_id, int(val))

        return str(max_id + 1)
    except Exception as e:
        print(f"Error fetching next tank ID: {e}")
        return "1"

def generate_tape_code(tank_type: str) -> str:
    """Generates a short code for painter's tape labeling."""
    type_upper = tank_type.upper()
    if "GROW-OUT" in type_upper or "PLANGGANA" in type_upper:
        prefix = "GO"
    elif "SPAWNING" in type_upper:
        prefix = "SPN"
    elif any(k in type_upper for k in ["JAR", "EMPI", "BOTTLE"]):
        prefix = "JAR"
    elif "SORORITY" in type_upper:
        prefix = "SOR"
    elif "QUARANTINE" in type_upper:
        prefix = "QT"
    else:
        prefix = "TNK"

    random_num = random.randint(1000, 9999)
    return f"{prefix}-{random_num}"

def generate_tank_qr(tank_id: str) -> io.BytesIO:
    """Generates a QR Code PNG stream for a given Tank ID."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(str(tank_id))
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    img_stream = io.BytesIO()
    img.save(img_stream, format='PNG')
    img_stream.seek(0)
    return img_stream

def upload_to_drive(drive_service, file_data, file_name: str, mime_type: str) -> str:
    """Uploads a file directly to Google Drive and makes it readable."""
    if hasattr(file_data, 'seek'):
        file_data.seek(0)

    if hasattr(file_data, 'getvalue'):
        raw_bytes = file_data.getvalue()
    elif hasattr(file_data, 'read'):
        raw_bytes = file_data.read()
    else:
        raw_bytes = file_data

    stream = io.BytesIO(raw_bytes)
    media = MediaIoBaseUpload(stream, mimetype=mime_type, resumable=False)
    folder_id = get_drive_folder_id()

    metadata = {'name': file_name}
    if folder_id:
        metadata['parents'] = [folder_id]

    uploaded = drive_service.files().create(
        body=metadata,
        media_body=media,
        fields='id'
    ).execute()
    
    file_id = uploaded.get('id')

    try:
        drive_service.permissions().create(
            fileId=file_id,
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()
    except Exception as e:
        print(f"Warning: Could not set permission on file {file_id}: {e}")

    return file_id

def register_tank(tank_type: str, capacity_liters: float, purpose: str = "General / Multi-purpose", photo_file=None, current_occupant: str = "", notes: str = "") -> dict:
    """
    Registers a new container, auto-syncs status based on occupant presence, 
    uploads media (photo & QR) to Google Drive, and writes to Google Sheets.
    """
    drive_service, sheets_service = get_google_services()
    spreadsheet_id = get_spreadsheet_id()

    ensure_tanks_tab_exists(sheets_service, spreadsheet_id)

    tank_id = get_next_tank_id(sheets_service, spreadsheet_id)
    location_code = generate_tape_code(tank_type)

    # Auto-determine status based on occupant presence
    status = "Active" if current_occupant.strip() else "Empty / Idle"

    photo_id = ""
    if photo_file is not None:
        try:
            photo_name = f"tank_{tank_id}_photo.jpg"
            photo_id = upload_to_drive(drive_service, photo_file, photo_name, 'image/jpeg')
        except Exception as e:
            st.error(f"Failed to upload photo: {e}")

    qr_id = ""
    try:
        qr_stream = generate_tank_qr(tank_id)
        qr_name = f"tank_{tank_id}_QR.png"
        qr_id = upload_to_drive(drive_service, qr_stream, qr_name, 'image/png')
    except Exception as e:
        print(f"Warning: Failed to generate QR Code: {e}")

    date_registered = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    row = [
        tank_id, tank_type, location_code, str(capacity_liters),
        status, purpose, current_occupant.strip(), photo_id,
        qr_id, notes, date_registered
    ]

    sheets_service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range='Tanks!A:K',
        valueInputOption='USER_ENTERED',
        body={'values': [row]}
    ).execute()

    direct_photo_url = f"https://drive.google.com/thumbnail?id={photo_id}&sz=w800" if photo_id else None

    return {
        "tank_id": tank_id,
        "location_code": location_code,
        "photo_id": photo_id,
        "qr_id": qr_id,
        "direct_photo_url": direct_photo_url
    }

def get_all_tanks() -> list:
    """Fetches all registered tank records from Google Sheets (Columns A through K)."""
    drive_service, sheets_service = get_google_services()
    spreadsheet_id = get_spreadsheet_id()

    try:
        ensure_tanks_tab_exists(sheets_service, spreadsheet_id)

        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range='Tanks!A2:K'
        ).execute()

        rows = result.get('values', [])
        tanks = []

        for row in rows:
            if not row or len(row) == 0:
                continue
            while len(row) < 11:
                row.append("")

            tanks.append({
                "id": str(row[0]),
                "type": str(row[1]),
                "location": str(row[2]),
                "capacity": str(row[3]),
                "status": str(row[4]) if row[4] else "Empty / Idle",
                "purpose": str(row[5]) if row[5] else "General / Multi-purpose",
                "occupant": str(row[6]),
                "photo_id": str(row[7]),
                "qr_id": str(row[8]),
                "notes": str(row[9]),
                "date_registered": str(row[10])
            })

        return tanks
    except Exception as e:
        print(f"Error fetching tanks: {e}")
        return []

def update_tank_status(tank_id: str, new_status: str, purpose: str = "", occupant: str = "", notes: str = "") -> bool:
    """
    Locates tank row by ID and updates status, purpose, occupant, and notes across the 11-column schema.
    Auto-syncs status to 'Active' if an occupant is assigned and status was 'Empty / Idle'.
    Auto-syncs status to 'Empty / Idle' if occupant is removed and status was 'Active'.
    """
    try:
        drive_service, sheets_service = get_google_services()
        spreadsheet_id = get_spreadsheet_id()

        ensure_tanks_tab_exists(sheets_service, spreadsheet_id)

        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range='Tanks!A:K'
        ).execute()

        rows = result.get('values', [])
        target_row = None

        for idx, row in enumerate(rows):
            if row and len(row) > 0 and str(row[0]).strip() == str(tank_id).strip():
                target_row = idx + 1
                break

        if not target_row:
            return False

        clean_occ = occupant.strip()

        # Automatic status sync rule
        if clean_occ and new_status == "Empty / Idle":
            final_status = "Active"
        elif not clean_occ and new_status == "Active":
            final_status = "Empty / Idle"
        else:
            final_status = new_status

        data = [
            {
                'range': f'Tanks!E{target_row}:G{target_row}',
                'values': [[final_status, purpose, clean_occ]]
            },
            {
                'range': f'Tanks!J{target_row}',
                'values': [[notes]]
            }
        ]

        sheets_service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                'valueInputOption': 'USER_ENTERED',
                'data': data
            }
        ).execute()

        return True
    except Exception as e:
        print(f"Error updating tank status: {e}")
        return False
