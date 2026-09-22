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

def generate_tape_code(tank_type: str) -> str:
    """Generates a short, easy-to-write code for painter's tape (e.g. GO-8492, JAR-1039)."""
    type_upper = tank_type.upper()
    if "GROW-OUT" in type_upper or "PLANGGANA" in type_upper:
        prefix = "GO"
    elif "SPAWNING" in type_upper:
        prefix = "SPN"
    elif "JAR" in type_upper or "EMPI" in type_upper or "BOTTLE" in type_upper:
        prefix = "JAR"
    elif "SORORITY" in type_upper:
        prefix = "SOR"
    elif "QUARANTINE" in type_upper:
        prefix = "QT"
    else:
        prefix = "TNK"

    random_num = random.randint(1000, 9999)
    return f"{prefix}-{random_num}"

def generate_tank_qr(tank_id):
    """Generates a QR Code image stream for a given Tank ID."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(tank_id)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    img_stream = io.BytesIO()
    img.save(img_stream, format='PNG')
    img_stream.seek(0)
    return img_stream

def upload_to_drive(drive_service, file_data, file_name, mime_type):
    """Uploads a file directly to Google Drive."""
    if hasattr(file_data, 'getvalue'):
        raw_bytes = file_data.getvalue()
    elif hasattr(file_data, 'read'):
        raw_bytes = file_data.read()
    else:
        raw_bytes = file_data

    stream = io.BytesIO(raw_bytes)
    stream.seek(0)

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

def register_tank(tank_type, capacity_liters, purpose="General / Multi-purpose", photo_file=None, current_occupant="", notes=""):
    """
    1. Generates a unique Tank ID and short Tape Code upon submission.
    2. Uploads container photo (if provided) and QR Tag to Google Drive.
    3. Saves record in Google Sheets.
    """
    drive_service, sheets_service = get_google_services()
    spreadsheet_id = get_spreadsheet_id()

    # Generate unique Tank ID and short Tape Code upon submission
    type_prefix = tank_type.replace(" ", "")[:3].upper()
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    tank_id = f"TNK-{type_prefix}-{timestamp}"
    location_code = generate_tape_code(tank_type)

    # 1. Upload Container Photo (if uploaded)
    photo_id = ""
    if photo_file is not None:
        try:
            photo_name = f"{tank_id}_photo.jpg"
            photo_id = upload_to_drive(drive_service, photo_file, photo_name, 'image/jpeg')
        except Exception as e:
            st.error(f"Failed to upload photo: {e}")

    # 2. Upload Tank QR Code
    qr_id = ""
    try:
        qr_stream = generate_tank_qr(tank_id)
        qr_name = f"{tank_id}_QR.png"
        qr_id = upload_to_drive(drive_service, qr_stream, qr_name, 'image/png')
    except Exception as e:
        print(f"Warning: Failed to generate QR Code: {e}")

    date_registered = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    row = [
        tank_id,               # A: Tank System ID
        tank_type,             # B: Tank / Container Type
        location_code,         # C: Auto-Generated Tape Code
        capacity_liters,       # D: Capacity (Liters)
        "Active",              # E: Status
        purpose,               # F: Container Purpose / Usage
        current_occupant,      # G: Current Occupant ID
        photo_id,              # H: Photo Drive ID
        qr_id,                 # I: QR Code Drive ID
        notes,                 # J: Notes
        date_registered        # K: Date Registered
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

def get_all_tanks():
    """Fetches all registered tank records from Google Sheets."""
    drive_service, sheets_service = get_google_services()
    spreadsheet_id = get_spreadsheet_id()

    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range='Tanks!A2:K'
        ).execute()

        rows = result.get('values', [])
        tanks = []

        for row in rows:
            if not row:
                continue
            while len(row) < 11:
                row.append("")

            tanks.append({
                "id": str(row[0]),
                "type": str(row[1]),
                "location": str(row[2]),
                "capacity": str(row[3]),
                "status": str(row[4]) if row[4] else "Active",
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
    """Updates tank status, purpose, current occupant, or notes."""
    try:
        drive_service, sheets_service = get_google_services()
        spreadsheet_id = get_spreadsheet_id()

        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range='Tanks!A:K'
        ).execute()

        rows = result.get('values', [])
        target_row = None

        for idx, row in enumerate(rows):
            if row and str(row[0]).strip() == str(tank_id).strip():
                target_row = idx + 1
                break

        if not target_row:
            return False

        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f'Tanks!E{target_row}:G{target_row}',
            valueInputOption='USER_ENTERED',
            body={'values': [[new_status, purpose, occupant]]}
        ).execute()

        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f'Tanks!J{target_row}',
            valueInputOption='USER_ENTERED',
            body={'values': [[notes]]}
        ).execute()

        return True
    except Exception as e:
        print(f"Error updating tank status: {e}")
        return False
