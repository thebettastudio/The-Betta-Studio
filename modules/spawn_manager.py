import datetime
from modules.drive_service import get_google_services, SPREADSHEET_ID

def get_available_breeders():
    """Fetches all active breeders eligible for pairing."""
    _, sheets_service = get_google_services()
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range='Breeders!A2:J'
    ).execute()

    rows = result.get('values', [])
    males, females = [], []

    for idx, row in enumerate(rows, start=2):
        if len(row) < 6:
            continue
        breeder_id, sex, variety, status = row[0], row[1], row[2], row[5]

        if status in ["Available", "Conditioning"]:
            label = f"{breeder_id} | {variety}"
            item = {"row_index": idx, "id": breeder_id, "label": label}
            if sex.lower() == "male":
                males.append(item)
            elif sex.lower() == "female":
                females.append(item)

    return males, females

def create_new_spawn(male_breeder_id, female_breeder_id, tank_location, line_goal="", notes=""):
    """Creates a new Spawn record and sets parent statuses to 'In Pairing'."""
    _, sheets_service = get_google_services()
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    spawn_id = f"SPN-{timestamp}"
    pairing_date = datetime.date.today().isoformat()

    row = [
        spawn_id,
        male_breeder_id,
        female_breeder_id,
        pairing_date,
        "In Pairing",
        "",  # Batch Name
        "",  # Free Swim Date
        0,   # Fry Count
        "",  # Failure Reason
        tank_location,
        line_goal,
        notes
    ]

    sheets_service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range='Spawns!A:L',
        valueInputOption='USER_ENTERED',
        body={'values': [row]}
    ).execute()

    # Update parent statuses
    _update_breeder_status(sheets_service, male_breeder_id, "In Pairing")
    _update_breeder_status(sheets_service, female_breeder_id, "In Pairing")

    return spawn_id

def mark_pairing_success_pending(spawn_id):
    """Updates spawn status to 'Pending (Success)' when eggs drop."""
    _, sheets_service = get_google_services()
    row_idx, _ = _find_spawn_by_id(sheets_service, spawn_id)
    if row_idx:
        sheets_service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f'Spawns!E{row_idx}',
            valueInputOption='USER_ENTERED',
            body={'values': [["Pending (Success)"]]}
        ).execute()

def mark_free_swimming(spawn_id, batch_name, est_fry_count=0):
    """Sets spawn status to 'Free Swimming', assigns batch name, and resets parents to 'Available'."""
    _, sheets_service = get_google_services()
    row_idx, spawn_data = _find_spawn_by_id(sheets_service, spawn_id)
    if row_idx:
        male_id, female_id = spawn_data[1], spawn_data[2]
        free_swim_date = datetime.date.today().isoformat()

        update_values = [["Free Swimming", batch_name, free_swim_date, est_fry_count]]
        sheets_service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f'Spawns!E{row_idx}:H{row_idx}',
            valueInputOption='USER_ENTERED',
            body={'values': update_values}
        ).execute()

        # Reset parents
        _update_breeder_status(sheets_service, male_id, "Available")
        _update_breeder_status(sheets_service, female_id, "Available")

def mark_pairing_failed(spawn_id, failure_reason):
    """Marks spawn as 'Failed', logs the reason, and resets parents to 'Available'."""
    _, sheets_service = get_google_services()
    row_idx, spawn_data = _find_spawn_by_id(sheets_service, spawn_id)
    if row_idx:
        male_id, female_id = spawn_data[1], spawn_data[2]

        # Update Status (Col E) & Failure Reason (Col I)
        sheets_service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f'Spawns!E{row_idx}',
            valueInputOption='USER_ENTERED',
            body={'values': [["Failed"]]}
        ).execute()

        sheets_service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f'Spawns!I{row_idx}',
            valueInputOption='USER_ENTERED',
            body={'values': [[failure_reason]]}
        ).execute()

        # Reset parents
        _update_breeder_status(sheets_service, male_id, "Available")
        _update_breeder_status(sheets_service, female_id, "Available")

# --- Helper Functions ---
def _find_spawn_by_id(sheets_service, spawn_id):
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range='Spawns!A2:L'
    ).execute()
    rows = result.get('values', [])
    for idx, row in enumerate(rows, start=2):
        if row and row[0] == spawn_id:
            return idx, row
    return None, None

def _update_breeder_status(sheets_service, breeder_id, new_status):
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range='Breeders!A2:F'
    ).execute()
    rows = result.get('values', [])
    for idx, row in enumerate(rows, start=2):
        if row and row[0] == breeder_id:
            sheets_service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f'Breeders!F{idx}',
                valueInputOption='USER_ENTERED',
                body={'values': [[new_status]]}
            ).execute()
            break
