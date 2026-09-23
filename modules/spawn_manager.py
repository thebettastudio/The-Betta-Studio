# modules/spawn_manager.py
import datetime
import re
import streamlit as st
from modules.drive_service import get_google_services, SPREADSHEET_ID
from modules.tank_registry import get_all_tanks

# ==========================================
# 0. SHEET FORMATTING & MOTIVATIONAL STYLING
# ==========================================

def format_spawns_sheet():
    """
    Applies clean, professional formatting to the 'Spawns' sheet:
    - Navy blue Header Row with white bold text on Row 1
    - Resets rows 2+ to plain white background and dark text
    - Freezes top header row & configures row height
    - Conditional color formatting for lifecycle statuses
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

    # Standardized 14-column headers
    headers = [
        ["Spawn ID", "Line Code", "Generation", "Male ID", "Female ID", 
         "Pairing Date", "Status", "Batch Name", "Free Swim Date", 
         "Fry Count", "Failure Reason", "Tank Location", "Line Goal", "Notes"]
    ]

    # Write headers to Row 1
    sheets_service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range='Spawns!A1:N1',
        valueInputOption='USER_ENTERED',
        body={'values': headers}
    ).execute()

    # Batch styling requests
    requests = [
        # Reset background and font color for Data Rows (Rows 2 to 200)
        {
            "repeatCell": {
                "range": {
                    "sheetId": spawns_sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": 200,
                    "startColumnIndex": 0,
                    "endColumnIndex": 14
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                        "textFormat": {
                            "bold": False,
                            "foregroundColor": {"red": 0.1, "green": 0.1, "blue": 0.1},
                            "fontSize": 10
                        },
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE"
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)"
            }
        },
        # Header Styling: Dark Navy background, bold white text
        {
            "repeatCell": {
                "range": {
                    "sheetId": spawns_sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": 14
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
        },
        # Set column width dimensions
        {"updateDimensionProperties": {"range": {"sheetId": spawns_sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1}, "properties": {"pixelSize": 140}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": spawns_sheet_id, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2}, "properties": {"pixelSize": 220}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": spawns_sheet_id, "dimension": "COLUMNS", "startIndex": 3, "endIndex": 5}, "properties": {"pixelSize": 180}, "fields": "pixelSize"}}
    ]

    # Conditional Formatting Rules strictly for Column G (Status)
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
                        "endRowIndex": 200,
                        "startColumnIndex": 6,
                        "endColumnIndex": 7
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

    # Execute batch formatting update
    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": requests}
    ).execute()


# ==========================================
# 1. READ / FETCH DATA
# ==========================================

def clean_text(text: str) -> str:
    """Strips special characters/emojis for reliable keyword matching."""
    return re.sub(r'[^\w\s]', '', str(text)).strip().lower()


def generate_short_spawn_id():
    """Generates sequential Spawn IDs in the format SPN-YY-XX (e.g. SPN-26-01)."""
    all_spawns = get_all_spawns()
    year_short = datetime.date.today().strftime("%y")
    prefix = f"SPN-{year_short}-"
    
    current_year_spawns = [
        s for s in all_spawns 
        if str(s.get("id", "")).startswith(prefix)
    ]
    
    next_num = len(current_year_spawns) + 1
    return f"{prefix}{next_num:02d}"


def calculate_child_generation(male_gen: str, female_gen: str, male_line: str, female_line: str):
    """Calculates child line code and generation based on parent lineage rules."""
    m_gen = (male_gen or "P1").strip().upper()
    f_gen = (female_gen or "P1").strip().upper()
    m_line = (male_line or "UNK").strip().upper()
    f_line = (female_line or "UNK").strip().upper()

    # Guard against notes leaking into line code
    if len(m_line) > 25 or "[" in m_line:
        m_line = "LINE"
    if len(f_line) > 25 or "[" in f_line:
        f_line = "LINE"

    if m_line != f_line:
        new_line = f"{m_line}x{f_line}"
        return new_line, "F1 (Outcross)"

    line_code = m_line

    if m_gen == f_gen and m_gen.startswith("F"):
        try:
            curr_num = int(m_gen.replace("F", ""))
            return line_code, f"F{curr_num + 1}"
        except ValueError:
            pass

    if m_gen in ["P1", "F0"] and f_gen in ["P1", "F0"]:
        return line_code, "F1"

    if ("P1" in [m_gen, f_gen] or "F0" in [m_gen, f_gen]) and ("F1" in [m_gen, f_gen]):
        return line_code, "BC1"

    return line_code, f"{m_gen}x{f_gen}"


def get_available_spawning_tanks():
    """Fetches available tanks directly using get_all_tanks()."""
    try:
        tanks = get_all_tanks()
        if not tanks:
            return []

        available_tanks = []
        valid_statuses = ["empty / idle", "empty", "idle", "available", "ready", "clean", "vacant", ""]

        for t in tanks:
            status_clean = clean_text(t.get('status', ''))
            occupant_clean = clean_text(t.get('occupant', ''))
            purpose_clean = clean_text(t.get('purpose', ''))
            type_clean = clean_text(t.get('type', ''))

            is_available = (status_clean in valid_statuses) or (occupant_clean in ["", "none", "empty", "na"])
            is_spawning_suitable = (
                "spaw" in purpose_clean or "breed" in purpose_clean or
                "spaw" in type_clean or "breed" in type_clean or
                purpose_clean in ["", "general", "multi-purpose", "unassigned"]
            )

            if is_available and is_spawning_suitable:
                tank_id = t.get('id', '')
                location_code = t.get('location', tank_id)
                tank_type = t.get('type', '')

                label_text = f"📍 {location_code} ({tank_type})" if tank_type else f"📍 {location_code}"

                available_tanks.append({
                    "id": tank_id,
                    "location": location_code,
                    "label": label_text
                })

        if not available_tanks:
            for t in tanks:
                status_clean = clean_text(t.get('status', ''))
                occupant_clean = clean_text(t.get('occupant', ''))

                if (status_clean in valid_statuses) or (occupant_clean in ["", "none", "empty", "na"]):
                    tank_id = t.get('id', '')
                    location_code = t.get('location', tank_id)
                    tank_type = t.get('type', '')

                    available_tanks.append({
                        "id": tank_id,
                        "location": location_code,
                        "label": f"📍 {location_code}" + (f" ({tank_type})" if tank_type else "")
                    })

        return available_tanks

    except Exception as e:
        st.error(f"Error loading spawning tanks: {e}")
        return []


def get_breeder_details_map():
    """Fetches all breeders and maps them by Breeder ID with correct column indices."""
    _, sheets_service = get_google_services()
    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Breeders!A2:J'
        ).execute()

        rows = result.get('values', [])
        breeders_map = {}

        for idx, row in enumerate(rows, start=2):
            if not row or not row[0].strip():
                continue

            breeder_id = row[0].strip()
            variety = row[2].strip() if len(row) > 2 else ""
            lineage = row[3].strip() if len(row) > 3 else "UNK"
            status = row[5].strip() if len(row) > 5 else "Available"
            photo_val = row[6] if len(row) > 6 else ""
            notes = row[8] if len(row) > 8 else ""

            # Extract Grade from Notes if present
            grade = "N/A"
            if "Grade:" in notes:
                try:
                    grade = notes.split("Grade:")[1].split("|")[0].strip()
                except Exception:
                    pass

            breeders_map[breeder_id] = {
                "row_index": idx,
                "id": breeder_id,
                "sex": row[1] if len(row) > 1 else "",
                "variety": variety,
                "lineage": lineage,
                "dob": row[4] if len(row) > 4 else "",
                "status": status,
                "photo_id": photo_val,
                "image_url": photo_val,
                "grade": grade,
                "notes": notes,
                "line_code": lineage or variety,
                "generation": "P1"
            }
        return breeders_map
    except Exception as e:
        st.error(f"Error fetching breeder details map: {e}")
        return {}


def get_available_breeders():
    """Fetches active male and female breeders ready for pairing (Col F = Status)."""
    _, sheets_service = get_google_services()
    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Breeders!A2:F'
        ).execute()

        rows = result.get('values', [])
        males, females = [], []

        active_statuses = ["available", "conditioning", "idle", "ready"]

        for idx, row in enumerate(rows, start=2):
            if len(row) < 6:
                continue

            breeder_id = row[0].strip()
            sex = row[1].strip().lower()
            variety = row[2].strip()
            status = row[5].strip().lower()  # Column F (Index 5) is Status

            if status in active_statuses:
                label = f"{breeder_id} | {variety}"
                item = {"row_index": idx, "id": breeder_id, "label": label}
                if sex == "male":
                    males.append(item)
                elif sex == "female":
                    females.append(item)

        return males, females
    except Exception:
        return [], []


def get_all_spawns():
    """Fetches all spawn records safely with row index and explicit tank key included."""
    _, sheets_service = get_google_services()
    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Spawns!A2:N'
        ).execute()

        rows = result.get('values', [])
        spawns = []

        for idx, row in enumerate(rows, start=2):
            if not row or not row[0].strip():
                continue

            batch_id = row[0].strip() if len(row) > 0 else ""
            is_legacy_row = len(row) > 3 and re.match(r'^\d{4}-\d{2}-\d{2}$', row[3].strip())

            if is_legacy_row:
                line_code = "UNK"
                generation = "F1"
                sire_id = row[1].strip() if len(row) > 1 else ""
                dam_id = row[2].strip() if len(row) > 2 else ""
                variety = row[5].strip() if len(row) > 5 else ""
                pair_date = row[3].strip() if len(row) > 3 else ""
                spawn_date = row[6].strip() if len(row) > 6 else ""
                hatch_date = row[7].strip() if len(row) > 7 else ""
                free_swimming_date = row[8].strip() if len(row) > 8 else ""
                jarring_date = ""
                fry_count = row[11].strip() if len(row) > 11 else "0"
                status = row[4].strip() if len(row) > 4 else "In Pairing"
                notes = row[13].strip() if len(row) > 13 else ""
            else:
                line_code = row[1].strip() if len(row) > 1 else "UNK"
                generation = row[2].strip() if len(row) > 2 else "F1"
                sire_id = row[3].strip() if len(row) > 3 else ""
                dam_id = row[4].strip() if len(row) > 4 else ""
                variety = row[5].strip() if len(row) > 5 else ""
                pair_date = row[6].strip() if len(row) > 6 else ""
                spawn_date = row[7].strip() if len(row) > 7 else ""
                hatch_date = row[8].strip() if len(row) > 8 else ""
                free_swimming_date = row[9].strip() if len(row) > 9 else ""
                jarring_date = row[10].strip() if len(row) > 10 else ""
                fry_count = row[11].strip() if len(row) > 11 else "0"
                status = row[12].strip() if len(row) > 12 else "In Pairing"
                notes = row[13].strip() if len(row) > 13 else ""

            # Safely extract tank location embedded in notes string
            tank_loc = "Unassigned"
            if "Tank:" in notes:
                try:
                    tank_loc = notes.split("Tank:")[1].split("|")[0].strip()
                except Exception:
                    pass

            spawns.append({
                "row_index": idx,
                "id": batch_id,
                "batch_id": batch_id,
                "line_code": line_code,
                "generation": generation,
                "sire_id": sire_id,
                "male_id": sire_id,
                "dam_id": dam_id,
                "female_id": dam_id,
                "variety": variety,
                "pair_date": pair_date,
                "pairing_date": pair_date,
                "spawn_date": spawn_date,
                "hatch_date": hatch_date,
                "free_swimming_date": free_swimming_date,
                "free_swim_date": free_swimming_date,
                "jarring_date": jarring_date,
                "estimated_fry_count": fry_count,
                "fry_count": fry_count,
                "status": status,
                "tank": tank_loc,
                "notes": notes
            })
        return spawns
    except Exception:
        return []


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
    """Appends clean 14-column spawn row under Spawns sheet and updates breeder/tank statuses."""
    _, sheets_service = get_google_services()
    breeders_map = get_breeder_details_map()

    male_info = breeders_map.get(male_breeder_id, {})
    female_info = breeders_map.get(female_breeder_id, {})

    line_code, child_gen = calculate_child_generation(
        male_gen=male_info.get("generation"),
        female_gen=female_info.get("generation"),
        male_line=male_info.get("line_code"),
        female_line=female_info.get("line_code")
    )

    spawn_id = generate_short_spawn_id()
    pairing_date = datetime.date.today().isoformat()
    variety = male_info.get("variety") or female_info.get("variety") or ""

    full_notes = f"Goal: {line_goal} | Tank: {tank_location} | {notes}".strip(" |")

    row = [
        spawn_id,          # A: Batch ID
        line_code,         # B: Line Code
        child_gen,         # C: Generation
        male_breeder_id,   # D: Sire ID
        female_breeder_id, # E: Dam ID
        variety,           # F: Variety
        pairing_date,      # G: Pair Date
        "",                # H: Spawn Date
        "",                # I: Hatch Date
        "",                # J: Free Swimming Date
        "",                # K: Jarring Date
        0,                 # L: Estimated Fry Count
        "In Pairing",      # M: Status
        full_notes         # N: Notes
    ]

    sheets_service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range='Spawns!A1:N1',
        valueInputOption='USER_ENTERED',
        insertDataOption='INSERT_ROWS',
        body={'values': [row]}
    ).execute()

    _update_breeder_status(sheets_service, male_breeder_id, "In Pairing")
    _update_breeder_status(sheets_service, female_breeder_id, "In Pairing")

    if tank_location:
        _update_tank_status(sheets_service, tank_location, "Occupied", occupant=f"Spawn {spawn_id}")

    return spawn_id, line_code, child_gen


# ==========================================
# 3. LIFECYCLE STATE TRANSITIONS & EDITING
# ==========================================

def mark_pairing_success_pending(spawn_id):
    """Updates status to Pending (Success) in Column M."""
    _, sheets_service = get_google_services()
    row_idx, _ = _find_spawn_by_id(sheets_service, spawn_id)
    if row_idx:
        sheets_service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f'Spawns!M{row_idx}',
            valueInputOption='USER_ENTERED',
            body={'values': [["Pending (Success)"]]}
        ).execute()


def mark_free_swimming(spawn_id, batch_name, est_fry_count=0):
    """Transitions spawn to Free Swimming, releases breeders back to Available, and frees tank."""
    _, sheets_service = get_google_services()
    row_idx, spawn_data = _find_spawn_by_id(sheets_service, spawn_id)
    if row_idx:
        male_id = spawn_data[3] if len(spawn_data) > 3 else ""
        female_id = spawn_data[4] if len(spawn_data) > 4 else ""
        
        notes_str = spawn_data[13] if len(spawn_data) > 13 else ""
        tank_location = None
        if "Tank:" in notes_str:
            tank_location = notes_str.split("Tank:")[1].split("|")[0].strip()

        free_swim_date = datetime.date.today().isoformat()

        sheets_service.spreadsheets().values().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={
                'valueInputOption': 'USER_ENTERED',
                'data': [
                    {'range': f'Spawns!J{row_idx}', 'values': [[free_swim_date]]},
                    {'range': f'Spawns!L{row_idx}', 'values': [[est_fry_count]]},
                    {'range': f'Spawns!M{row_idx}', 'values': [["Free Swimming"]]}
                ]
            }
        ).execute()

        _update_breeder_status(sheets_service, male_id, "Available")
        _update_breeder_status(sheets_service, female_id, "Available")
        if tank_location:
            _update_tank_status(sheets_service, tank_location, "Empty / Idle", occupant="")


def mark_pairing_failed(spawn_id, failure_reason):
    """Marks spawn as Failed, logs reason in Notes, releases breeders, and frees tank."""
    _, sheets_service = get_google_services()
    row_idx, spawn_data = _find_spawn_by_id(sheets_service, spawn_id)
    if row_idx:
        male_id = spawn_data[3] if len(spawn_data) > 3 else ""
        female_id = spawn_data[4] if len(spawn_data) > 4 else ""
        current_notes = spawn_data[13] if len(spawn_data) > 13 else ""
        
        tank_location = None
        if "Tank:" in current_notes:
            tank_location = current_notes.split("Tank:")[1].split("|")[0].strip()

        updated_notes = f"{current_notes} | Reason: {failure_reason}".strip(" |")

        sheets_service.spreadsheets().values().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={
                'valueInputOption': 'USER_ENTERED',
                'data': [
                    {'range': f'Spawns!M{row_idx}', 'values': [["Failed"]]},
                    {'range': f'Spawns!N{row_idx}', 'values': [[updated_notes]]}
                ]
            }
        ).execute()

        _update_breeder_status(sheets_service, male_id, "Available")
        _update_breeder_status(sheets_service, female_id, "Available")
        if tank_location:
            _update_tank_status(sheets_service, tank_location, "Empty / Idle", occupant="")


def update_spawn_details(spawn_id, batch_name=None, fry_count=None, status=None, line_goal=None, notes=None):
    """Allows general editing of an existing spawn record."""
    _, sheets_service = get_google_services()
    row_idx, spawn_data = _find_spawn_by_id(sheets_service, spawn_id)
    if not row_idx:
        return False

    current_fry = spawn_data[11] if len(spawn_data) > 11 else "0"
    current_status = spawn_data[12] if len(spawn_data) > 12 else "In Pairing"
    current_notes = spawn_data[13] if len(spawn_data) > 13 else ""

    new_fry = fry_count if fry_count is not None else current_fry
    new_status = status if status is not None else current_status
    new_notes = notes if notes is not None else current_notes

    if line_goal:
        new_notes = f"Goal: {line_goal} | {new_notes}".strip(" |")

    sheets_service.spreadsheets().values().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={
            'valueInputOption': 'USER_ENTERED',
            'data': [
                {'range': f'Spawns!L{row_idx}', 'values': [[new_fry]]},
                {'range': f'Spawns!M{row_idx}:N{row_idx}', 'values': [[new_status, new_notes]]}
            ]
        }
    ).execute()

    return True


# ==========================================
# 4. INTERNAL HELPERS
# ==========================================

def _find_spawn_by_id(sheets_service, spawn_id):
    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Spawns!A2:N'
        ).execute()
        rows = result.get('values', [])
        for idx, row in enumerate(rows, start=2):
            if row and row[0].strip() == spawn_id.strip():
                return idx, row
        return None, None
    except Exception:
        return None, None


def _update_breeder_status(sheets_service, breeder_id, new_status):
    """Updates breeder status in Column F (Index 5)."""
    if not breeder_id:
        return
    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Breeders!A2:F'
        ).execute()
        rows = result.get('values', [])
        for idx, row in enumerate(rows, start=2):
            if row and row[0].strip() == breeder_id.strip():
                sheets_service.spreadsheets().values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f'Breeders!F{idx}',
                    valueInputOption='USER_ENTERED',
                    body={'values': [[new_status]]}
                ).execute()
                break
    except Exception:
        pass


def _update_tank_status(sheets_service, tank_identifier, new_status, occupant=None):
    if not tank_identifier:
        return
    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Tanks!A2:G'
        ).execute()
        rows = result.get('values', [])
        for idx, row in enumerate(rows, start=2):
            if not row:
                continue

            tid = row[0].strip() if len(row) > 0 else ""
            tloc = row[2].strip() if len(row) > 2 else ""

            if tid == tank_identifier or tloc == tank_identifier:
                data_updates = [{'range': f'Tanks!D{idx}', 'values': [[new_status]]}]

                if occupant is not None:
                    data_updates.append({'range': f'Tanks!G{idx}', 'values': [[occupant]]})

                sheets_service.spreadsheets().values.batchUpdate(
                    spreadsheetId=SPREADSHEET_ID,
                    body={
                        'valueInputOption': 'USER_ENTERED',
                        'data': data_updates
                    }
                ).execute()
                break
    except Exception:
        pass
