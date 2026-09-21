import os
import datetime
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/spreadsheets'
]

SPREADSHEET_ID = 'YOUR_SPREADSHEET_ID_HERE'

def get_sheets_service():
    if not os.path.exists('token.json'):
        raise FileNotFoundError("token.json not found. Run authentication first.")
    creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    return build('sheets', 'v4', credentials=creds)


def get_available_breeders():
    """
    Fetches all registered breeders and filters them into available 
    males and females for selection menus.
    """
    service = get_sheets_service()
    
    # Read row data from Breeders sheet
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range='Breeders!A2:J'  # Skip header row
    ).execute()

    rows = result.get('values', [])
    males = []
    females = []

    for idx, row in enumerate(rows, start=2):  # Row index in Google Sheets
        if len(row) < 6:
            continue
            
        breeder_id = row[0]
        sex = row[1]
        variety = row[2] if len(row) > 2 else ""
        status = row[5] if len(row) > 5 else "Available"

        # Filter only active/available breeders
        if status in ["Available", "Conditioning"]:
            label = f"{breeder_id} | {variety}"
            item = {"row_index": idx, "id": breeder_id, "label": label, "sex": sex}
            
            if sex.lower() == "male":
                males.append(item)
            elif sex.lower() == "female":
                females.append(item)

    return males, females


def create_new_spawn(male_breeder_id, female_breeder_id, tank_location, line_goal="", notes=""):
    """
    1. Generates a new Spawn ID.
    2. Writes the spawn record to the 'Spawns' sheet.
    3. Updates both breeders' statuses to 'In Pairing' in the 'Breeders' sheet.
    """
    service = get_sheets_service()
    
    # 1. Generate Spawn ID (e.g., SPN-20260921-1045)
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    spawn_id = f"SPN-{timestamp}"
    pairing_date = datetime.date.today().isoformat()

    # 2. Append new row to 'Spawns' sheet
    spawn_row = [
        spawn_id,
        male_breeder_id,
        female_breeder_id,
        pairing_date,
        "",  # Spawn Date (to be updated when eggs drop)
        "",  # Free Swimming Date
        0,   # Estimated Fry Count
        "In Pairing",
        tank_location,
        line_goal,
        notes
    ]

    service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range='Spawns!A:K',
        valueInputOption='USER_ENTERED',
        body={'values': [spawn_row]}
    ).execute()

    # 3. Update both Breeders' status to "In Pairing" in 'Breeders' sheet
    _update_breeder_status(service, male_breeder_id, "In Pairing")
    _update_breeder_status(service, female_breeder_id, "In Pairing")

    print(f"✅ Created Spawn Record: {spawn_id}")
    print(f"   Male: {male_breeder_id} | Female: {female_breeder_id}")
    return spawn_id


def _update_breeder_status(service, breeder_id, new_status):
    """Helper function to update a breeder's status column (Column F)."""
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range='Breeders!A2:F'
    ).execute()
    
    rows = result.get('values', [])
    for idx, row in enumerate(rows, start=2):
        if row and row[0] == breeder_id:
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f'Breeders!F{idx}',
                valueInputOption='USER_ENTERED',
                body={'values': [[new_status]]}
            ).execute()
            break


if __name__ == '__main__':
    # Test 1: Load available parent stock
    males, females = get_available_breeders()
    print("--- Available Male Breeders ---")
    for m in males:
        print(f"  {m['label']}")

    print("\n--- Available Female Breeders ---")
    for f in females:
        print(f"  {f['label']}")

    # Test 2: Create a spawn if at least one male and female are available
    if males and females:
        selected_male = males[0]['id']
        selected_female = females[0]['id']
        
        create_new_spawn(
            male_breeder_id=selected_male,
            female_breeder_id=selected_female,
            tank_location="Tank-B01",
            line_goal="Improve iridescence and star pattern density",
            notes="First attempt pairing this pair."
        )
