# modules/drive_service.py
import os
import json
import streamlit as st
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/spreadsheets'
]

# Fetch spreadsheet & folder IDs from st.secrets if available, else local defaults
SPREADSHEET_ID = st.secrets.get("SPREADSHEET_ID", "YOUR_SPREADSHEET_ID_HERE")
DRIVE_FOLDER_ID = st.secrets.get("DRIVE_FOLDER_ID", "YOUR_DRIVE_FOLDER_ID_HERE")


def get_google_services():
    """
    Returns authenticated Drive and Sheets clients.
    Reads credentials from st.secrets (Streamlit Cloud) or token.json (local).
    """
    creds = None

    # 1. Check if running on Streamlit Cloud using st.secrets
    if "google_oauth" in st.secrets:
        oauth_dict = dict(st.secrets["google_oauth"])
        creds = Credentials.from_authorized_user_info(oauth_dict, SCOPES)

    # 2. Otherwise, fallback to local token.json file for local testing
    else:
        token_path = 'config/token.json' if os.path.exists('config/token.json') else 'token.json'
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds:
        raise FileNotFoundError(
            "Google credentials not found! Please configure st.secrets on Streamlit Cloud or provide a local token.json."
        )

    drive_service = build('drive', 'v3', credentials=creds)
    sheets_service = build('sheets', 'v4', credentials=creds)

    return drive_service, sheets_service
