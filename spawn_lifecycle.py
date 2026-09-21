import datetime
from spawn_manager import get_sheets_service, SPREADSHEET_ID, _update_breeder_status

def mark_pairing_failed(spawn_id, failure_reason):
    """
    1. Sets spawn status to 'Failed' and records the failure reason.
    2. Resets both parent breeders' statuses back to 'Available'.
    """
    service = get_sheets_service()
    row_idx, spawn_data = _find_spawn_by_id(service, spawn_id)
    
    if not row_idx:
        raise ValueError(f"Spawn ID {spawn_id} not found.")

    male_id = spawn_data[1]
    female_id = spawn_data[2]

    # Update Status (Col E) to 'Failed' and Failure Reason (Col I)
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f'Spawns!E{row_idx}',
        valueInputOption='USER_ENTERED',
        body={'values': [["Failed"]]}
    ).execute()

    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f'Spawns!I{row_idx}',
        valueInputOption='USER_ENTERED',
        body={'values': [[failure_reason]]}
    ).execute()

    # Reset parents so they can be paired again
    _update_breeder_status(service, male_id, "Available")
    _update_breeder_status(service, female_id, "Available")

    print(f"❌ Spawn {spawn_id} marked as Failed. Reason: {failure_reason}")
    print(f"   Parents {male_id} & {female_id} reset to 'Available'.")


def mark_pairing_success_pending(spawn_id, notes="Eggs dropped successfully"):
    """
    Sets spawn status to 'Pending (Success)' while eggs hatch / male tends nest.
    """
    service = get_sheets_service()
    row_idx, _ = _find_spawn_by_id(service, spawn_id)

    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f'Spawns!E{row_idx}',
        valueInputOption='USER_ENTERED',
        body={'values': [["Pending (Success)"]]}
    ).execute()

    print(f"⏳ Spawn {spawn_id} marked as Pending (Success). Waiting for free swimming stage.")


def mark_free_swimming(spawn_id, batch_name, est_fry_count=0):
    """
    1. Sets spawn status to 'Free Swimming'.
    2. Assigns the custom Batch Name and Free Swim Date.
    3. Resets parents to 'Available' (female already removed, male can now be removed).
    """
    service = get_sheets_service()
    row_idx, spawn_data = _find_spawn_by_id(service, spawn_id)

    male_id = spawn_data[1]
    female_id = spawn_data[2]
    free_swim_date = datetime.date.today().isoformat()

    # Update Status (Col E), Batch Name (Col F), Free Swim Date (Col G), Fry Count (Col H)
    update_values = [
        ["Free Swimming", batch_name, free_swim_date, est_fry_count]
    ]

    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f'Spawns!E{row_idx}:H{row_idx}',
        valueInputOption='USER_ENTERED',
        body={'values': update_values}
    ).execute()

    # Reset parents to Available for future spawns
    _update_breeder_status(service, male_id, "Available")
    _update_breeder_status(service, female_id, "Available")

    print(f"🎉 Spawn {spawn_id} is now FREE SWIMMING!")
    print(f"   Batch Name: {batch_name} | Est. Fry: {est_fry_count}")


def _find_spawn_by_id(service, spawn_id):
    """Helper to locate the row index of a given Spawn ID."""
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range='Spawns!A2:K'
    ).execute()
    
    rows = result.get('values', [])
    for idx, row in enumerate(rows, start=2):
        if row and row[0] == spawn_id:
            return idx, row
    return None, None
