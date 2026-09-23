# modules/drive_service.py
# Betta Farm Management System
# Session 7 — Drive-only. No import-time secret crash.
# Session 17 — Removed Sheets remnants (SPREADSHEET_ID, get_spreadsheet_id).

import os

import streamlit as st
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


SCOPES = [
    'https://www.googleapis.com/auth/drive.file',
]

DEFAULT_DRIVE_FOLDER_ID = "1F0PmaZN_sUP5qDfIeSvsY6hSiYFSNO0y"


# ============================================================
# SECRET READERS
# ============================================================

def _secret(name: str, default: str = "") -> str:
    """Read a secret from streamlit secrets or environment. Never raises."""
    try:
        val = st.secrets.get(name)
        if val is not None:
            return str(val).strip()
    except Exception:
        pass
    env = os.getenv(name)
    if env:
        return str(env).strip()
    return default


def get_drive_folder_id() -> str:
    """Returns the Drive folder ID, or a safe default."""
    return _secret("DRIVE_FOLDER_ID", DEFAULT_DRIVE_FOLDER_ID)


# Backward-compat global (nothing reads it anymore, but kept for safety)
DRIVE_FOLDER_ID = get_drive_folder_id()


# ============================================================
# GOOGLE DRIVE
# ============================================================

def get_google_services():
    """
    Returns (drive_service, None). The second element is always None
    now that Sheets is retired — kept for backward-compat callers.
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
    return drive_service, None


def get_drive_service():
    """Returns just the Drive service. Preferred for new code."""
    drive_service, _ = get_google_services()
    return drive_service
