# modules/photo_service.py
# Betta Farm Management System
# Session 4 — unified Google Drive photo upload + URL builder.
# Session 18 — photo_url() now uses lh3.googleusercontent.com for faster loads.

from __future__ import annotations

import io
import datetime as _dt
from typing import Optional, Tuple

import streamlit as st
from PIL import Image

# Optional HEIC support (iPhone photos)
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

from googleapiclient.http import MediaIoBaseUpload

from modules.drive_service import get_google_services, get_drive_folder_id


# ============================================================
# IMAGE PROCESSING
# ============================================================

def compress_image(
    raw_bytes: bytes,
    max_dimension: int = 1280,
    quality: int = 85,
) -> bytes:
    """
    Downscale + compress an image for mobile-friendly storage.
    Falls back to original bytes if processing fails.
    """
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        img.thumbnail((max_dimension, max_dimension))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()
    except Exception as e:
        st.warning(f"Could not compress image, using original ({e})")
        return raw_bytes


# ============================================================
# DRIVE UPLOAD
# ============================================================

def _upload_bytes(
    raw_bytes: bytes,
    file_name: str,
    mime_type: str = "image/jpeg",
    make_public: bool = True,
) -> Optional[str]:
    """
    Upload bytes to Google Drive. Returns the Drive file ID, or None on failure.
    """
    try:
        drive_service, _ = get_google_services()
        stream = io.BytesIO(raw_bytes)
        stream.seek(0)

        metadata = {"name": file_name}
        folder_id = get_drive_folder_id()
        if folder_id:
            metadata["parents"] = [folder_id.strip()]

        media = MediaIoBaseUpload(stream, mimetype=mime_type, resumable=False)
        uploaded = drive_service.files().create(
            body=metadata,
            media_body=media,
            fields="id",
        ).execute()

        file_id = uploaded.get("id")
        if not file_id:
            return None

        if make_public:
            try:
                drive_service.permissions().create(
                    fileId=file_id,
                    body={"type": "anyone", "role": "reader"},
                ).execute()
            except Exception as e:
                print(f"Warning: could not make {file_id} public: {e}")

        return file_id
    except Exception as e:
        st.error(f"Drive upload failed: {e}")
        return None


# ============================================================
# PUBLIC API
# ============================================================

def upload_photo(
    file_data,
    entity_type: str,
    entity_id: str,
    make_public: bool = True,
) -> Optional[str]:
    """
    Compress + upload a photo. `file_data` can be a Streamlit UploadedFile,
    raw bytes, or a file-like object.

    Returns: Drive file ID (store this in `photo_id` column), or None.
    """
    raw_bytes = _read_bytes(file_data)
    if not raw_bytes:
        return None

    compressed = compress_image(raw_bytes)
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"{entity_type}_{entity_id}_{ts}.jpg"

    return _upload_bytes(compressed, file_name, "image/jpeg", make_public)


def upload_qr(
    qr_bytes: bytes,
    entity_type: str,
    entity_id: str,
) -> Optional[str]:
    """
    Upload a pre-generated QR PNG. Returns Drive file ID.
    """
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"{entity_type}_{entity_id}_QR_{ts}.png"
    return _upload_bytes(qr_bytes, file_name, "image/png", make_public=True)


def upload_bytes_as_photo(
    raw_bytes: bytes,
    entity_type: str,
    entity_id: str,
) -> Optional[str]:
    """
    Convenience for callers that already have compressed bytes.
    """
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"{entity_type}_{entity_id}_{ts}.jpg"
    return _upload_bytes(raw_bytes, file_name, "image/jpeg", make_public=True)


# ============================================================
# DELETION
# ============================================================

def delete_drive_file(file_id: Optional[str]) -> bool:
    """Best-effort delete. Returns True on success, False otherwise."""
    if not file_id:
        return False
    try:
        drive_service, _ = get_google_services()
        drive_service.files().delete(fileId=file_id).execute()
        return True
    except Exception as e:
        print(f"Could not delete Drive file {file_id}: {e}")
        return False


# ============================================================
# URL HELPERS
# ============================================================

def photo_url(file_id: Optional[str], size: int = 800) -> Optional[str]:
    """
    Build a Google Drive thumbnail URL from a raw file ID.

    Uses lh3.googleusercontent.com — the same format the legacy Sheets
    code used. It renders faster than drive.google.com/thumbnail for
    freshly-uploaded files.

    Returns None if `file_id` is empty.
    """
    if not file_id:
        return None
    fid = str(file_id).strip()
    if not fid:
        return None
    # If caller passed a full URL, return it unchanged
    if fid.startswith("http://") or fid.startswith("https://"):
        return fid
    return f"https://lh3.googleusercontent.com/d/{fid}=w{size}"


def qr_url(file_id: Optional[str], size: int = 800) -> Optional[str]:
    """Alias for photo_url — QR codes use the same Drive URL scheme."""
    return photo_url(file_id, size=size)


# ============================================================
# INTERNAL
# ============================================================

def _read_bytes(file_data) -> Optional[bytes]:
    """Normalize UploadedFile / BytesIO / bytes to raw bytes."""
    if file_data is None:
        return None
    try:
        if hasattr(file_data, "getvalue"):
            return file_data.getvalue()
        if hasattr(file_data, "read"):
            file_data.seek(0)
            return file_data.read()
        if isinstance(file_data, (bytes, bytearray)):
            return bytes(file_data)
    except Exception as e:
        st.error(f"Could not read file data: {e}")
    return None
