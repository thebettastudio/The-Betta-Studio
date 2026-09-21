# modules/breeder_registry.py
import os
import io
import re
import datetime
import qrcode
import streamlit as st
from googleapiclient.http import MediaIoBaseUpload
from modules.drive_service import (
    get_google_services,
    get_spreadsheet_id,
    get_drive_folder_id
)

def generate_qr_code(breeder_id):
    """Generates a QR Code image stream for a given Breeder ID."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(breeder_id)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    img_stream = io.BytesIO()
    img.save(img_stream, format='PNG')
    img_stream.seek(0)
    return img_stream

def upload_to_drive(drive_service, file_data, file_name, mime_type):
    """Uploads a file directly to your personal Google Drive storage."""
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
        fields='id, webViewLink'
    ).execute()
    
    file_id = uploaded.get('id')
    web_link = uploaded.get('webViewLink')

    try:
        drive_service.permissions().create(
            fileId=file_id,
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()
    except Exception as e:
        print(f"Warning: Could not set public permission on file {file_id}: {e}")

    return file_id, web_link

def register_breeder(sex, variety, lineage, dob, photo_path, notes=""):
    """
    1. Generates a unique Breeder ID.
    2. Uploads QR Code and Photo directly to Google Drive.
    3. Saves raw Drive File IDs in Google Sheets.
    """
    drive_service, sheets_service = get_google_services()
    spreadsheet_id = get_spreadsheet_id()

    prefix = "BRD-M" if sex.lower() == "male" else "BRD-F"
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    breeder_id = f"{prefix}-{timestamp}"

    # 1. Upload Photo
    photo_id, photo_url = "", ""
    if photo_path is not None:
        try:
            photo_name = f"{breeder_id}_photo.jpg"
            photo_id, photo_url = upload_to_drive(drive_service, photo_path, photo_name, 'image/jpeg')
        except Exception as e:
            st.error(f"Photo upload error: {e}")

    # 2. Upload QR Code
    qr_id, qr_url = "", ""
    try:
        qr_stream = generate_qr_code(breeder_id)
        qr_name = f"{breeder_id}_QR.png"
        qr_id, qr_url = upload_to_drive(drive_service, qr_stream, qr_name, 'image/png')
    except Exception as e:
        st.error(f"QR Code upload error: {e}")

    dob_str = str(dob) if dob else ""
    date_registered = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    row = [
        breeder_id,           # A: Breeder ID
        sex.capitalize(),     # B: Sex
        variety,              # C: Variety
        lineage,              # D: Lineage / Breeder
        dob_str,              # E: DOB
        "Available",          # F: Status
        photo_id,             # G: Raw Photo Drive ID
        qr_id,                # H: Raw QR Code Drive ID
        notes,                # I: Notes
        date_registered       # J: Date Registered
    ]

    sheets_service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range='Breeders!A:J',
        valueInputOption='USER_ENTERED',
        body={'values': [row]}
    ).execute()

    direct_photo_url = f"https://drive.google.com/thumbnail?id={photo_id}&sz=w800" if photo_id else None
    direct_qr_url = f"https://drive.google.com/thumbnail?id={qr_id}&sz=w800" if qr_id else None

    return {
        "breeder_id": breeder_id,
        "photo_id": photo_id,
        "qr_id": qr_id,
        "direct_photo_url": direct_photo_url,
        "direct_qr_url": direct_qr_url
    }

def clean_drive_id(val):
    """Cleans up formula leftovers or extracts plain Drive File IDs."""
    if not val or "No Photo" in val or "No QR" in val:
        return ""
    
    match = re.search(r'([a-zA-Z0-9_-]{25,})', val)
    if match:
        return match.group(1)
    return ""

def format_excel_date(date_val):
    """Converts Excel serial dates to YYYY-MM-DD."""
    try:
        val = float(date_val)
        base_date = datetime.datetime(1899, 12, 30)
        return (base_date + datetime.timedelta(days=val)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return str(date_val)

def get_all_breeders():
    """Fetches all registered breeders from Google Sheets."""
    drive_service, sheets_service = get_google_services()
    spreadsheet_id = get_spreadsheet_id()
    
    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range='Breeders!A2:J'
        ).execute()
        
        rows = result.get('values', [])
        breeders = []
        
        for row in rows:
            if not row or len(row) == 0:
                continue

            while len(row) < 10:
                row.append("")

            breeders.append({
                "id": str(row[0]),
                "sex": str(row[1]),
                "variety": str(row[2]),
                "lineage": str(row[3]),
                "dob": format_excel_date(row[4]),
                "status": str(row[5]) if row[5] else "Available",
                "photo_id": clean_drive_id(str(row[6])),
                "qr_id": clean_drive_id(str(row[7])),
                "notes": str(row[8]),
                "date_registered": str(row[9])
            })
            
        return breeders
    except Exception as e:
        print(f"Error fetching breeders: {e}")
        return []

def delete_breeder(breeder_id: str) -> bool:
    """
    1. Finds breeder row by Breeder ID in Google Sheets.
    2. Deletes row dimensions via batchUpdate.
    3. Purges associated Photo and QR Code from Google Drive.
    """
    try:
        drive_service, sheets_service = get_google_services()
        spreadsheet_id = get_spreadsheet_id()

        # 1. Get all values to locate row index & Drive IDs
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range='Breeders!A:J'
        ).execute()
        
        rows = result.get('values', [])
        if not rows:
            return False

        target_row_idx = None
        photo_id = ""
        qr_id = ""

        for idx, row in enumerate(rows):
            if row and len(row) > 0 and str(row[0]).strip() == str(breeder_id).strip():
                target_row_idx = idx
                if len(row) > 6:
                    photo_id = clean_drive_id(str(row[6]))
                if len(row) > 7:
                    qr_id = clean_drive_id(str(row[7]))
                break

        if target_row_idx is None:
            return False

        # 2. Get Sheet ID (gid) for the 'Breeders' tab
        sheet_metadata = sheets_service.spreadsheets().get(
            spreadsheetId=spreadsheet_id
        ).execute()
        
        sheet_gid = 0
        for sheet in sheet_metadata.get('sheets', []):
            if sheet.get('properties', {}).get('title') == 'Breeders':
                sheet_gid = sheet.get('properties', {}).get('sheetId', 0)
                break

        # 3. Delete row via batchUpdate
        delete_body = {
            "requests": [
                {
                    "deleteDimension": {
                        "range": {
                            "sheetId": sheet_gid,
                            "dimension": "ROWS",
                            "startIndex": target_row_idx,
                            "endIndex": target_row_idx + 1
                        }
                    }
                }
            ]
        }
        
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=delete_body
        ).execute()

        # 4. Clean up files from Google Drive
        for f_id in [photo_id, qr_id]:
            if f_id:
                try:
                    drive_service.files().delete(fileId=f_id).execute()
                except Exception as e:
                    print(f"Warning: Failed to delete Drive file {f_id}: {e}")

        return True
    except Exception as e:
        print(f"Error deleting breeder {breeder_id}: {e}")
        return False
