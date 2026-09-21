# modules/drive_service.py
import os
import streamlit as st
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/spreadsheets'
]

DRIVE_FOLDER_ID = st.secrets.get("DRIVE_FOLDER_ID", os.getenv("DRIVE_FOLDER_ID", ""))
SPREADSHEET_ID = st.secrets.get("SPREADSHEET_ID", os.getenv("SPREADSHEET_ID", ""))

def get_google_services():
    creds = None

    if "oauth_token" in st.secrets:
        token_info = dict(st.secrets["oauth_token"])
        creds = Credentials(
            token=token_info.get("token"),
            refresh_token=token_info.get("refresh_token"),
            token_uri=token_info.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=token_info.get("client_id", "407408718192.apps.googleusercontent.com"),
            client_secret=token_info.get("client_secret", ""),
            scopes=SCOPES
        )

    # Refresh expired access token automatically using refresh_token
    if creds and (not creds.valid or creds.expired):
        creds.refresh(Request())

    if not creds:
        raise RuntimeError("Missing [oauth_token] configuration in Streamlit secrets.")

    drive_service = build('drive', 'v3', credentials=creds)
    sheets_service = build('sheets', 'v4', credentials=creds)

    return drive_service, sheets_service
