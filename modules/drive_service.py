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
