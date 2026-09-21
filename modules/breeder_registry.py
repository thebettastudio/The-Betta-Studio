# modules/breeder_registry.py
import os
import io
import datetime
import qrcode
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
from modules.drive_service import get_google_services, SPREADSHEET_ID, DRIVE_FOLDER_ID

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
    """Uploads a file to Google Drive and sets public read permissions."""
    metadata = {'name': file_name}
    if DRIVE_FOLDER_ID:
        metadata['parents'] = [DRIVE_FOLDER_ID]

    # Handle local paths vs BytesIO vs Streamlit UploadedFile objects
    if isinstance(file_data, str):
        media = MediaFileUpload(file_data, mimetype=mime_type, resumable=False)
    else:
        if hasattr(file_data, 'getvalue'):
            stream = io.BytesIO(file_data.getvalue())
        elif hasattr(file_data, 'read'):
            stream = io.BytesIO(file_data.read())
        else:
            stream = file_data
            stream.seek(0)
            
        media = MediaIoBaseUpload(stream, mimetype=mime_type, resumable=False)

    uploaded = drive_service.files().create(
        body=metadata,
        media_body=media,
        fields='id, webViewLink'
    ).execute()
    
    file_id = uploaded.get('id')
    web_link = uploaded.get('webViewLink')

    # Make file publicly readable so =IMAGE(...) in Google Sheets can load it
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
    2. Creates and uploads a QR Code image to Drive.
    3. Uploads the breeder photo to Drive.
    4. Records the breeder row in Google Sheets ('Breeders' tab) with clickable formulas.
    """
    drive_service, sheets_service = get_google_services()

    prefix = "BRD-M" if sex.lower() == "male" else "BRD-F"
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    breeder_id = f"{prefix}-{timestamp}"

    # 1. Upload Photo (if provided)
    photo_id, photo_url = "", ""
    if photo_path:
        try:
            photo_name = f"{breeder_id}_photo.jpg"
            photo_id, photo_url = upload_to_drive(drive_service, photo_path, photo_name, 'image/jpeg')
        except Exception as e:
            print(f"Warning: Photo upload failed: {e}")

    # 2. Upload QR Code
    qr_id, qr_url = "", ""
    try:
        qr_stream = generate_qr_code(breeder_id)
        qr_name = f"{breeder_id}_QR.png"
        qr_id, qr_url = upload_to_drive(drive_service, qr_stream, qr_name, 'image/png')
    except Exception as e:
        print(f"Warning: QR upload failed: {e}")

    # HYPERLINK formula with preview link so clicking it opens the image in a browser tab
    photo_cell = f'=HYPERLINK("{photo_url}", "View Photo")' if photo_url else "No Photo"
    qr_cell = f'=HYPERLINK("{qr_url}", "View QR")' if qr_url else "No QR"

    # 3. Format date strings
    dob_str = str(dob) if dob else ""
    date_registered = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 4. Row layout aligned strictly to columns A through J
    row = [
        breeder_id,            # A: Breeder ID
        sex.capitalize(),      # B: Sex
        variety,               # C: Variety
        lineage,               # D: Lineage / Breeder
        dob_str,               # E: DOB
        "Available",           # F: Status
        photo_cell,            # G: Photo (Clickable Link)
        qr_cell,               # H: QR Code (Clickable Link)
        notes,                 # I: Notes
        date_registered        # J: Date Registered
    ]

    sheets_service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range='Breeders!A:J',
        valueInputOption='USER_ENTERED',
        body={'values': [row]}
    ).execute()

    return {
        "breeder_id": breeder_id,
        "photo_url": photo_url,
        "qr_url": qr_url
    }
