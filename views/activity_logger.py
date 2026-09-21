# modules/activity_logger.py
from modules.drive_service import get_google_services, SPREADSHEET_ID

def fetch_activity_logs():
    """Fetches all activity entries from the Google Sheet for the UI."""
    _, sheets_service = get_google_services()
    
    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Activity_Log!A2:E'  # Reads from Activity_Log sheet
        ).execute()

        rows = result.get('values', [])
        logs = []
        
        for row in rows:
            logs.append({
                "timestamp": row[0] if len(row) > 0 else "",
                "action_type": row[1] if len(row) > 1 else "",
                "description": row[2] if len(row) > 2 else "",
                "photo_id": row[3] if len(row) > 3 else "",
                "photo_url": row[4] if len(row) > 4 else ""
            })
            
        return logs
    except Exception as e:
        print(f"Error fetching activity logs: {e}")
        return []
