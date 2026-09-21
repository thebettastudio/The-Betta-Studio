import os
import json
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ['https://www.googleapis.com/auth/drive.file']

def authenticate_google_drive():
    creds = None
    
    # Read token directly from Environment Variable (GitHub Actions) or local file
    token_data = os.environ.get('GOOGLE_TOKEN')
    
    if token_data:
        # Loaded from GitHub Secrets
        info = json.loads(token_data)
        creds = Credentials.from_authorized_user_info(info, SCOPES)
    elif os.path.exists('token.json'):
        # Loaded from local file
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    return build('drive', 'v3', credentials=creds)
