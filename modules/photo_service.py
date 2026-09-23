"""
Handles photo uploads to Google Drive and registers them in Supabase.

Assumes existing Drive upload logic in modules/drive_service.py.
If drive_service.py has a different upload function name, adjust
the import at the top.
"""
from typing import Optional
from modules.drive_service import get_google_services, DRIVE_FOLDER_ID
import database


def upload_photo_for_entity(
    file_bytes: bytes,
    filename: str,
    mime_type: str,
    entity_type: str,
    entity_id: str,
    is_primary: bool = False,
    caption: Optional[str] = None,
) -> Optional[dict]:
    """
    Upload a photo to Google Drive, then record it in Supabase.

    Args:
        file_bytes:  raw file bytes
        filename:    target filename in Drive (e.g., 'BRD-F-20260921-075204.jpg')
        mime_type:   e.g., 'image/jpeg'
        entity_type: 'fish' | 'tank' | 'spawn' | 'batch'
        entity_id:   UUID of the entity in Supabase
        is_primary:  mark as the primary photo
        caption:     optional caption

    Returns:
        The created Supabase `photos` row, or None on failure.
    """
    import io
    from googleapiclient.http import MediaIoBaseUpload

    drive_service, _ = get_google_services()
    file_stream = io.BytesIO(file_bytes)

    metadata = {"name": filename}
    if DRIVE_FOLDER_ID:
        metadata["parents"] = [DRIVE_FOLDER_ID.strip()]

    media = MediaIoBaseUpload(file_stream, mimetype=mime_type, resumable=False)

    # Upload to Drive
    uploaded = drive_service.files().create(
        body=metadata, media_body=media, fields="id, webViewLink"
    ).execute()

    drive_file_id = uploaded.get("id")
    photo_url = uploaded.get("webViewLink")

    # If this is primary, clear existing primary first
    if is_primary:
        existing = database.get_primary_photo(entity_type, entity_id)
        if existing:
            database.set_primary_photo(entity_type, entity_id, existing["id"])
            # (the set_primary_photo helper will handle clearing)

    # Record in Supabase
    return database.add_photo(
        entity_type=entity_type,
        entity_id=entity_id,
        photo_url=photo_url,
        drive_file_id=drive_file_id,
        caption=caption,
        is_primary=is_primary,
    )
