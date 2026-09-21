# modules/drive_service.py
import os
import streamlit as st
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# Ensure DRIVE_FOLDER_ID pulls from Streamlit secrets or environment variables
DRIVE_FOLDER_ID = st.secrets.get("DRIVE_FOLDER_ID", os.getenv("DRIVE_FOLDER_ID", ""))
SPREADSHEET_ID = st.secrets.get("SPREADSHEET_ID", os.getenv("SPREADSHEET_ID", ""))

def get_google_services():
    scopes = [
        'https://www.googleapis.com/auth/drive',
        'https://www.googleapis.com/auth/spreadsheets'
    ]
    
    if "gcp_service_account" in st.secrets:
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    else:
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")
        creds = Credentials.from_service_account_file(creds_path, scopes=scopes)

    drive_service = build('drive', 'v3', credentials=creds)
    sheets_service = build('sheets', 'v4', credentials=creds)
    
    return drive_service, sheets_service
