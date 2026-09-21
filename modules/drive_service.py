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

SPREADSHEET_ID = st.secrets.get("SPREADSHEET_ID", "YOUR_SPREADSHEET_ID_HERE")
DRIVE_FOLDER_ID = st.secrets.get("DRIVE_FOLDER_ID", "YOUR_DRIVE_FOLDER_ID_HERE")

def get_google_services():
    """
    Returns authenticated Drive and Sheets clients.
    Handles automatic token refresh via google.auth.transport.requests.Request.
    """
    creds = None

    # 1. Load from Streamlit Cloud Secrets
    if "google_oauth" in st.secrets:
        oauth_dict = dict(st.secrets["google_oauth"])
        creds = Credentials.from_authorized_user_info(oauth_dict, SCOPES)

    # 2. Fallback to local file for local development
    else:
        token_path = 'config/token.json' if os.path.exists('config/token.json') else 'token.json'
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds:
        raise FileNotFoundError(
            "Google credentials not found! Configure st.secrets or provide token.json."
        )

    # 3. Refresh token if expired
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:
            st.error("⚠️ Google OAuth Refresh Error: Your refresh token may be expired or invalid.")
            raise e

    drive_service = build('drive', 'v3', credentials=creds)
    sheets_service = build('sheets', 'v4', credentials=creds)

    return drive_service, sheets_service
