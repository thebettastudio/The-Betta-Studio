"""
Supabase client singleton.
Reads credentials from Streamlit secrets.

Secrets layout (flat, preferred):
    SUPABASE_URL = "https://xxx.supabase.co"
    SUPABASE_KEY = "eyJ..."

Secrets layout (nested, legacy) — also supported:
    [connections.supabase]
    SUPABASE_URL = "..."
    SUPABASE_KEY = "..."
"""
import streamlit as st
from supabase import create_client, Client


def _read_secret(name: str) -> str:
    """Read a secret from flat or nested layout."""
    # Try flat first
    try:
        return st.secrets[name]
    except (KeyError, FileNotFoundError):
        pass
    # Try nested
    try:
        return st.secrets["connections"]["supabase"][name]
    except (KeyError, FileNotFoundError):
        pass
    raise KeyError(f"Supabase secret '{name}' not found in either flat or nested layout.")


@st.cache_resource
def get_supabase_client() -> Client:
    """Return a cached Supabase client. Reused across sessions."""
    url = _read_secret("SUPABASE_URL")
    key = _read_secret("SUPABASE_KEY")
    return create_client(url, key)


# Backwards-compat alias for any old imports
get_supabase = get_supabase_client
