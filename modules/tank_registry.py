# modules/tank_registry.py
import io
import datetime
import qrcode
import streamlit as st
from googleapiclient.http import MediaIoBaseUpload
from modules.drive_service import (
    get_google_services,
    get_spreadsheet_id,
    get_drive_folder_id
)

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

def upload_tank_qr_to_drive(drive_service, qr_stream, file_name):
    """Uploads tank QR tag image to Google Drive."""
    raw_bytes = qr_stream.getvalue()
    stream = io.BytesIO(raw_bytes)
    stream.seek(0)

    media = MediaIoBaseUpload(stream, mimetype='image/png', resumable=False)
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
        print(f"Warning: Could not set permission for QR file {file_id}: {e}")

    return file_id

def register_tank(tank_type, location, capacity_liters, current_occupant="", notes=""):
    """
    Registers a new Tank/Container ID and logs it into Google Sheets.
    Format: TNK-[TYPE_PREFIX]-[TIMESTAMP]
    """
    drive_service, sheets_service = get_google_services()
    spreadsheet_id = get_spreadsheet_id()

    type_prefix = tank_type.replace(" ", "")[:3].upper()
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    tank_id = f"TNK-{type_prefix}-{timestamp}"

    # Generate & Upload Tank QR Tag (Optional usage)
    qr_id = ""
    try:
        qr_stream = generate_tank_qr(tank_id)
        qr_name = f"{tank_id}_QR.png"
        qr_id = upload_tank_qr_to_drive(drive_service, qr_stream, qr_name)
    except Exception as e:
        print(f"Warning: Failed to upload QR Code: {e}")

    date_registered = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    row = [
        tank_id,               # A: Tank ID
        tank_type,             # B: Tank / Container Type
        location,              # C: Tape Code / Location Tag
        capacity_liters,       # D: Capacity (Liters)
        "Active",              # E: Status (Active, Cleaning, Empty, Retired)
        current_occupant,      # F: Current Occupant (Breeder / Spawn ID)
        qr_id,                 # G: QR Code Drive ID
        notes,                 # H: Notes
        date_registered        # I: Date Registered
    ]

    sheets_service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range='Tanks!A:I',
        valueInputOption='USER_ENTERED',
        body={'values': [row]}
    ).execute()

    direct_qr_url = f"https://drive.google.com/thumbnail?id={qr_id}&sz=w800" if qr_id else None

    return {
        "tank_id": tank_id,
        "qr_id": qr_id,
        "direct_qr_url": direct_qr_url
    }

def get_all_tanks():
    """Fetches all registered tank records from Google Sheets."""
    drive_service, sheets_service = get_google_services()
    spreadsheet_id = get_spreadsheet_id()

    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range='Tanks!A2:I'
        ).execute()

        rows = result.get('values', [])
        tanks = []

        for row in rows:
            if not row:
                continue
            while len(row) < 9:
                row.append("")

            tanks.append({
                "id": str(row[0]),
                "type": str(row[1]),
                "location": str(row[2]),
                "capacity": str(row[3]),
                "status": str(row[4]) if row[4] else "Active",
                "occupant": str(row[5]),
                "qr_id": str(row[6]),
                "notes": str(row[7]),
                "date_registered": str(row[8])
            })

        return tanks
    except Exception as e:
        print(f"Error fetching tanks: {e}")
        return []

def update_tank_status(tank_id: str, new_status: str, occupant: str = "", notes: str = "") -> bool:
    """Updates tank status, current occupant, or maintenance notes."""
    try:
        drive_service, sheets_service = get_google_services()
        spreadsheet_id = get_spreadsheet_id()

        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range='Tanks!A:I'
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
            range=f'Tanks!E{target_row}:H{target_row}',
            valueInputOption='USER_ENTERED',
            body={'values': [[new_status, occupant, "", notes]]}
        ).execute()

        return True
    except Exception as e:
        print(f"Error updating tank status: {e}")
        return False
