# modules/spawn_manager.py
import datetime
from modules.drive_service import get_google_services, SPREADSHEET_ID

# ==========================================
# 0. SHEET FORMATTING & MOTIVATIONAL STYLING
# ==========================================

def format_spawns_sheet():
    """
    Applies professional, motivating formatting to the 'Spawns' sheet:
    - Bold colorful Header Row with dark theme
    - Conditional color formatting for lifecycle statuses
    - Freeze header row & auto row height
    - Proper column alignment
    """
    _, sheets_service = get_google_services()

    # Get spreadsheet metadata to locate sheet ID for 'Spawns'
    spreadsheet = sheets_service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    spawns_sheet_id = None
    for sheet in spreadsheet.get('sheets', []):
        if sheet['properties']['title'] == 'Spawns':
            spawns_sheet_id = sheet['properties']['sheetId']
            break

    if spawns_sheet_id is None:
        return

    # 1. Define standard headers
    headers = [
        ["Spawn ID", "Male ID", "Female ID", "Pairing Date", "Status", 
         "Batch Name", "Free Swim Date", "Fry Count", "Failure Reason", 
         "Tank Location", "Line Goal", "Notes"]
    ]

    # Write headers to Row 1
    sheets_service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range='Spawns!A1:L1',
        valueInputOption='USER_ENTERED',
        body={'values': headers}
    ).execute()

    # 2. Batch styling requests
    requests = [
        # Header Styling: Dark Blue background, bold white text
        {
            "repeatCell": {
                "range": {
                    "sheetId": spawns_sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": 12
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": 0.1, "green": 0.25, "blue": 0.45},
                        "textFormat": {"bold": True, "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}, "fontSize": 11},
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE"
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)"
            }
        },
        # Freeze top header row
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": spawns_sheet_id,
                    "gridProperties": {"frozenRowCount": 1}
                },
                "fields": "gridProperties.frozenRowCount"
            }
        },
        # Align center for dates, status, IDs, tank location
        {
            "repeatCell": {
                "range": {
                    "sheetId": spawns_sheet_id,
                    "startRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": 10
                },
                "cell": {
                    "userEnteredFormat": {
                        "verticalAlignment": "MIDDLE"
                    }
                },
                "fields": "userEnteredFormat(verticalAlignment)"
            }
        },
        # Set Row Height for Header
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": spawns_sheet_id,
                    "dimension": "ROWS",
                    "startIndex": 0,
                    "endIndex": 1
                },
                "properties": {"pixelSize": 38},
                "fields": "pixelSize"
            }
        }
    ]

    # Add Conditional Formatting Rules for Status (Col E)
    # Status "In Pairing" -> Warm Vibrant Amber/Yellow
    # Status "Free Swimming" -> Lively Soft Green
    # Status "Pending (Success)" -> Light Cyan/Blue
    # Status "Failed" -> Soft Crimson Red
    status_rules = [
        ("In Pairing", {"red": 1.0, "green": 0.94, "blue": 0.8}, {"red": 0.6, "green": 0.4, "blue": 0.0}),
        ("Free Swimming", {"red": 0.85, "green": 0.95, "blue": 0.85}, {"red": 0.1, "green": 0.5, "blue": 0.2}),
        ("Pending (Success)", {"red": 0.85, "green": 0.92, "blue": 1.0}, {"red": 0.0, "green": 0.3, "blue": 0.7}),
        ("Failed", {"red": 0.98, "green": 0.85, "blue": 0.85}, {"red": 0.6, "green": 0.1, "blue": 0.1})
    ]

    for val, bg, text_color in status_rules:
        requests.append({
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{
                        "sheetId": spawns_sheet_id,
                        "startRowIndex": 1,
                        "startColumnIndex": 4,
                        "endColumnIndex": 5
                    }],
                    "booleanRule": {
                        "condition": {
                            "type": "TEXT_EQ",
                            "values": [{"userEnteredValue": val}]
                        },
                        "format": {
                            "backgroundColor": bg,
                            "textFormat": {"bold": True, "foregroundColor": text_color}
                        }
                    }
                },
                "index": 0
            }
        })

    # Execute formatting
    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": requests}
    ).execute()


# ==========================================
# 1. READ / FETCH DATA
# ==========================================

def get_breeder_details_map():
    """Fetches all breeders and maps them by Breeder ID for fast lookup."""
    _, sheets_service = get_google_services()
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range='Breeders!A2:J'
    ).execute()

    rows = result.get('values', [])
    breeders_map = {}

    for idx, row in enumerate(rows, start=2):
        if not row:
            continue
        breeder_id = row[0]
        breeders_map[breeder_id] = {
            "row_index": idx,
            "id": breeder_id,
            "sex": row[1] if len(row) > 1 else "",
            "variety": row[2] if len(row) > 2 else "",
            "grade": row[3] if len(row) > 3 else "N/A",
            "image_url": row[4] if len(row) > 4 else "",
            "status": row[5] if len(row) > 5 else "",
            "tank": row[6] if len(row) > 6 else "",
            "notes": row[7] if len(row) > 7 else ""
        }
    return breeders_map


def get_available_breeders():
    """Fetches active male and female breeders ready for pairing."""
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


def get_all_spawns():
    """Fetches all spawn records from canonical range A2:L."""
    _, sheets_service = get_google_services()
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range='Spawns!A2:L'
    ).execute()

    rows = result.get('values', [])
    spawns = []

    for row in rows:
        if not row:
            continue
        spawns.append({
            "id": row[0] if len(row) > 0 else "",
            "male_id": row[1] if len(row) > 1 else "",
            "female_id": row[2] if len(row) > 2 else "",
            "pairing_date": row[3] if len(row) > 3 else "",
            "status": row[4] if len(row) > 4 else "In Pairing",
            "batch_name": row[5] if len(row) > 5 else "",
            "free_swim_date": row[6] if len(row) > 6 else "",
            "fry_count": row[7] if len(row) > 7 else "0",
            "failure_reason": row[8] if len(row) > 8 else "",
            "tank": row[9] if len(row) > 9 else "",
            "line_goal": row[10] if len(row) > 10 else "",
            "notes": row[11] if len(row) > 11 else ""
        })
    return spawns


def get_active_pairings_with_details():
    """Fetches active pairings enriched with full breeder details."""
    all_spawns = get_all_spawns()
    breeders_map = get_breeder_details_map()
    
    active_statuses = ["In Pairing", "Pending (Success)"]
    active_pairs = []

    for spawn in all_spawns:
        if spawn.get("status") in active_statuses:
            male_info = breeders_map.get(spawn["male_id"], {})
            female_info = breeders_map.get(spawn["female_id"], {})
            
            active_pairs.append({
                "spawn": spawn,
                "male": male_info,
                "female": female_info
            })

    return active_pairs


# ==========================================
# 2. CREATE SPAWN
# ==========================================

def create_new_spawn(male_breeder_id, female_breeder_id, tank_location, line_goal="", notes=""):
    """Appends clean 12-column spawn row under Spawns sheet."""
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
        range='Spawns!A1:L1',
        valueInputOption='USER_ENTERED',
        insertDataOption='INSERT_ROWS',
        body={'values': [row]}
    ).execute()

    _update_breeder_status(sheets_service, male_breeder_id, "In Pairing")
    _update_breeder_status(sheets_service, female_breeder_id, "In Pairing")

    return spawn_id


# ==========================================
# 3. LIFECYCLE STATE TRANSITIONS
# ==========================================

def mark_pairing_success_pending(spawn_id):
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

        _update_breeder_status(sheets_service, male_id, "Available")
        _update_breeder_status(sheets_service, female_id, "Available")


def mark_pairing_failed(spawn_id, failure_reason):
    _, sheets_service = get_google_services()
    row_idx, spawn_data = _find_spawn_by_id(sheets_service, spawn_id)
    if row_idx:
        male_id, female_id = spawn_data[1], spawn_data[2]

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

        _update_breeder_status(sheets_service, male_id, "Available")
        _update_breeder_status(sheets_service, female_id, "Available")


# ==========================================
# 4. INTERNAL HELPERS
# ==========================================

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
