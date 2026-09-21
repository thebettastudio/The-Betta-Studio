import os
import io
import datetime
import qrcode
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

SCOPES = [
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/spreadsheets'
]

SPREADSHEET_ID = 'YOUR_SPREADSHEET_ID_HERE'
DRIVE_FOLDER_ID = 'YOUR_DRIVE_FOLDER_ID_HERE'  # Google Drive folder for photos & QRs

def get_services():
    if not os.path.exists('token.json'):
        raise FileNotFoundError("token.json not found. Run authentication first.")
    creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    return build('drive', 'v3', credentials=creds), build('sheets', 'v4', credentials=creds)

def generate_qr_code(breeder_id):
    """Generates a QR Code image in memory for a given Breeder ID."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(breeder_id)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    return img_byte_arr

def upload_file_to_drive(drive_service, file_data, file_name, mime_type, folder_id=None):
    """Uploads a file stream or local path to Google Drive."""
    file_metadata = {'name': file_name}
    if folder_id:
        file_metadata['parents'] = [folder_id]

    if isinstance(file_data, str):  # Local file path
        media = MediaFileUpload(file_data, mimetype=mime_type, resumable=True)
    else:  # BytesIO stream
        media = MediaIoBaseUpload(file_data, mimetype=mime_type, resumable=True)

    uploaded = drive_service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id, webViewLink'
    ).execute()
    
    return uploaded.get('id'), uploaded.get('webViewLink')

def register_breeder(sex, variety, lineage, dob, photo_path, notes=""):
    """
    Registers a new male/female breeder:
    1. Assigns a unique Breeder ID.
    2. Generates and uploads a QR Code to Google Drive.
    3. Uploads the breeder photo to Google Drive.
    4. Appends all data to Google Sheets ('Breeders' tab).
    """
    drive_service, sheets_service = get_services()
    
    # 1. Generate Breeder ID (e.g., BRD-M-20260921-1034)
    prefix = "BRD-M" if sex.lower() == "male" else "BRD-F"
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    breeder_id = f"{prefix}-{timestamp}"

    # 2. Upload Photo to Drive
    photo_name = f"{breeder_id}_photo.jpg"
    photo_id, photo_url = upload_file_to_drive(
        drive_service, photo_path, photo_name, 'image/jpeg', DRIVE_FOLDER_ID
    )

    # 3. Generate & Upload QR Code to Drive
    qr_stream = generate_qr_code(breeder_id)
    qr_name = f"{breeder_id}_QR.png"
    qr_id, qr_url = upload_file_to_drive(
        drive_service, qr_stream, qr_name, 'image/png', DRIVE_FOLDER_ID
    )

    # 4. Save Record to Google Sheets
    row = [
        breeder_id,
        sex.capitalize(),
        variety,
        lineage,
        dob,
        "Available",  # Default status
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

    print(f"✅ Registered Breeder: {breeder_id}")
    print(f"   Photo URL: {photo_url}")
    print(f"   QR Code URL: {qr_url}")
    
    return {
        "breeder_id": breeder_id,
        "photo_url": photo_url,
        "qr_url": qr_url
    }

if __name__ == '__main__':
    # Test registering a Male Avatar Plakat Breeder
    register_breeder(
        sex="Male",
        variety="Avatar Black Star HMPK",
        lineage="Line A - Grand Champion Sire",
        dob="2026-01-15",
        photo_path="male_avatar.jpg",
        notes="Strong dorsal spread, high aggression, clean iridescent star spots."
    )
