# modules/drive_service.py
import os
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/spreadsheets'
]

SPREADSHEET_ID = 'YOUR_SPREADSHEET_ID_HERE'
DRIVE_FOLDER_ID = 'YOUR_DRIVE_FOLDER_ID_HERE'

def get_google_services():
    """Returns authenticated Drive and Sheets service objects."""
    # Read token/credentials from config directory or root
    token_path = 'config/token.json' if os.path.exists('config/token.json') else 'token.json'
    
    if not os.path.exists(token_path):
        raise FileNotFoundError(f"{token_path} not found. Run local auth first.")

    creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    drive_service = build('drive', 'v3', credentials=creds)
    sheets_service = build('sheets', 'v4', credentials=creds)
    
    return drive_service, sheets_service
