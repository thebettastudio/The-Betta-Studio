# modules/drive_service.py
import json
import streamlit as st
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/spreadsheets'
]

SPREADSHEET_ID = st.secrets.get("SPREADSHEET_ID", "")
DRIVE_FOLDER_ID = st.secrets.get("DRIVE_FOLDER_ID", "")

def get_google_services():
    """
    Returns authenticated Drive and Sheets clients using Service Account credentials.
    Service Accounts never expire and require no user login or refresh tokens.
    """
    if "gcp_service_account" not in st.secrets:
        raise ValueError("gcp_service_account missing from Streamlit secrets!")

    service_account_info = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)

    drive_service = build('drive', 'v3', credentials=creds)
    sheets_service = build('sheets', 'v4', credentials=creds)

    return drive_service, sheets_service
