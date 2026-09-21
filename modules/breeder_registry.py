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
    """Uploads a file stream or local path to Google Drive."""
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
    
    return uploaded.get('id'), uploaded.get('webViewLink')

def register_breeder(sex, variety, lineage, dob, photo_path, notes=""):
    """
    1. Generates a unique Breeder ID.
    2. Creates and uploads a QR Code image to Drive.
    3. Uploads the breeder photo to Drive.
    4. Records the breeder row in Google Sheets ('Breeders' tab).
    """
    drive_service, sheets_service = get_google_services()

    prefix = "BRD-M" if sex.lower() == "male" else "BRD-F"
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    breeder_id = f"{prefix}-{timestamp}"

    # 1. Upload Photo (if provided)
    photo_url = ""
    if photo_path:
        try:
            photo_name = f"{breeder_id}_photo.jpg"
            _, photo_url = upload_to_drive(drive_service, photo_path, photo_name, 'image/jpeg')
        except Exception as e:
            print(f"Warning: Photo upload failed: {e}")

    # 2. Upload QR Code
    qr_url = ""
    try:
        qr_stream = generate_qr_code(breeder_id)
        qr_name = f"{breeder_id}_QR.png"
        _, qr_url = upload_to_drive(drive_service, qr_stream, qr_name, 'image/png')
    except Exception as e:
        print(f"Warning: QR upload failed: {e}")

    # 3. Append to Google Sheets
    row = [
        breeder_id,
        sex.capitalize(),
        variety,
        lineage,
        dob,
        "Available",
        photo_url,
        qr_url,
        notes,
        datetime.datetime.now().isoformat()
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
