# modules/drive_service.py
import json
import streamlit as st
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# Full Google Drive scope is required to upload into pre-existing shared folders
SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/spreadsheets'
]

SPREADSHEET_ID = st.secrets.get("SPREADSHEET_ID", "1wYEjEyZgnWS7YEU_Xde4bjhQrOxMYfe2q-PV8YMVfIo")
DRIVE_FOLDER_ID = st.secrets.get("DRIVE_FOLDER_ID", "1F0PmaZN_sUP5qDfIeSvsY6hSiYFSNO0y")

@st.cache_resource
def get_google_services():
    """
    Returns authenticated Drive and Sheets clients using Service Account credentials.
    Uses st.cache_resource to avoid re-authenticating on every app interaction.
    """
    if "gcp_service_account" not in st.secrets:
        raise ValueError("gcp_service_account missing from Streamlit secrets!")

    service_account_info = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)

    drive_service = build('drive', 'v3', credentials=creds)
    sheets_service = build('sheets', 'v4', credentials=creds)

    return drive_service, sheets_service
