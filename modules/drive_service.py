# modules/drive_service.py
# Betta Farm Management System
# Drive stays; Sheets support is being phased out (Session 18).
# Session 7 fix: no import-time secret loading, safe fallbacks.

import os
import streamlit as st
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


SCOPES = [
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/spreadsheets',   # kept for legacy modules
]

DEFAULT_SPREADSHEET_ID = "1wYEjEyZgnWS7YEU_Xde4bjhQrOxMYfe2q-PV8YMVfIo"
DEFAULT_DRIVE_FOLDER_ID = "1F0PmaZN_sUP5qDfIeSvsY6hSiYFSNO0y"


# ============================================================
# SECRET READERS — never raise at import time
# ============================================================

def _secret(name: str, default: str = "") -> str:
    """
    Read a secret from streamlit secrets or environment.
    Returns default if secrets aren't available (e.g., local import tests).
    """
    # try streamlit secrets (may raise if no secrets file exists)
    try:
        val = st.secrets.get(name)
        if val is not None:
            return str(val).strip()
    except Exception:
        pass
    # try environment
    env = os.getenv(name)
    if env:
        return str(env).strip()
    return default


def get_spreadsheet_id() -> str:
    """Returns the sheet ID, or a safe default. Never raises."""
    sid = _secret("SPREADSHEET_ID", DEFAULT_SPREADSHEET_ID)
    if len(sid) < 40:
        return DEFAULT_SPREADSHEET_ID
    return sid


def get_drive_folder_id() -> str:
    """Returns the Drive folder ID, or a safe default. Never raises."""
    return _secret("DRIVE_FOLDER_ID", DEFAULT_DRIVE_FOLDER_ID)


# ============================================================
# BACKWARD-COMPAT GLOBALS
# ============================================================
# Old modules do `from modules.drive_service import SPREADSHEET_ID`.
# We still define it, but now it can't crash at import time.
SPREADSHEET_ID = get_spreadsheet_id()
DRIVE_FOLDER_ID = get_drive_folder_id()


# ============================================================
# GOOGLE SERVICES
# ============================================================

def get_google_services():
    """
    Returns (drive_service, sheets_service).
    Only called from functions that actually need Drive/Sheets —
    not at import time.
    """
    creds = None

    try:
        if "oauth_token" in st.secrets:
            token_info = dict(st.secrets["oauth_token"])
            creds = Credentials(
                token=token_info.get("token"),
                refresh_token=token_info.get("refresh_token"),
                token_uri=token_info.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=token_info.get("client_id"),
                client_secret=token_info.get("client_secret"),
                scopes=SCOPES,
            )
    except Exception:
        # No secrets file available (local import test) — fall through
        pass

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


# ============================================================
# DRIVE-ONLY (no Sheets) — used by photo_service and new modules
# ============================================================

def get_drive_service():
    """Returns just the Drive service. Preferred for new code."""
    drive_service, _ = get_google_services()
    return drive_service
