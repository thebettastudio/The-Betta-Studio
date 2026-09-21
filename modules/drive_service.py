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

# Hardcode accurate fallbacks to safeguard against stale/cached secrets
DEFAULT_SPREADSHEET_ID = "1wYEjEyZgnWS7YEU_Xde4bjhQrOxMYfe2q-PV8YMVfIo"
DEFAULT_DRIVE_FOLDER_ID = "1F0PmaZN_sUP5qDfIeSvsY6hSiYFSNO0y"

def get_spreadsheet_id() -> str:
    """Dynamically retrieves and cleans the Spreadsheet ID."""
    sid = st.secrets.get("SPREADSHEET_ID", os.getenv("SPREADSHEET_ID", DEFAULT_SPREADSHEET_ID))
    sid = str(sid).strip()
    # Fallback if the secrets value is somehow truncated or invalid
    if len(sid) < 40:
        return DEFAULT_SPREADSHEET_ID
    return sid

def get_drive_folder_id() -> str:
    """Dynamically retrieves and cleans the Drive Folder ID."""
    fid = st.secrets.get("DRIVE_FOLDER_ID", os.getenv("DRIVE_FOLDER_ID", DEFAULT_DRIVE_FOLDER_ID))
    return str(fid).strip()

# Global variables for backward compatibility across existing views
SPREADSHEET_ID = get_spreadsheet_id()
DRIVE_FOLDER_ID = get_drive_folder_id()

def get_google_services():
    creds = None

    if "oauth_token" in st.secrets:
        token_info = dict(st.secrets["oauth_token"])
        
        creds = Credentials(
            token=token_info.get("token"),
            refresh_token=token_info.get("refresh_token"),
            token_uri=token_info.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=token_info.get("client_id"),
            client_secret=token_info.get("client_secret"),
            scopes=SCOPES
        )

    # Refresh expired access token using your client credentials
    if creds and (not creds.valid or creds.expired):
        try:
            creds.refresh(Request())
        except Exception as e:
            st.error(
                "Failed to refresh OAuth token. Please ensure your refresh_token, "
                "client_id, and client_secret in Streamlit secrets are valid."
            )
            raise e

    if not creds:
        raise RuntimeError("Missing [oauth_token] configuration in Streamlit secrets.")

    drive_service = build('drive', 'v3', credentials=creds)
    sheets_service = build('sheets', 'v4', credentials=creds)

    return drive_service, sheets_service
