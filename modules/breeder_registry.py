def register_breeder(sex, variety, lineage, dob, photo_path, notes=""):
    """
    1. Generates a unique Breeder ID.
    2. Creates and uploads a QR Code image to Drive.
    3. Uploads the breeder photo to Drive.
    4. Records the breeder row in Google Sheets ('Breeders' tab).
    """
    drive_service, sheets_service = get_google_services()

    prefix = "BRD-M" if sex.lower() == "male" else "BRD-F"
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    breeder_id = f"{prefix}-{timestamp}"

    # 1. Upload Photo (if provided)
    photo_id, photo_url = "", ""
    if photo_path:
        try:
            photo_name = f"{breeder_id}_photo.jpg"
            photo_id, photo_url = upload_to_drive(drive_service, photo_path, photo_name, 'image/jpeg')
        except Exception as e:
            print(f"Warning: Photo upload failed: {e}")

    # 2. Upload QR Code
    qr_id, qr_url = "", ""
    try:
        qr_stream = generate_qr_code(breeder_id)
        qr_name = f"{breeder_id}_QR.png"
        qr_id, qr_url = upload_to_drive(drive_service, qr_stream, qr_name, 'image/png')
    except Exception as e:
        print(f"Warning: QR upload failed: {e}")

    photo_cell = f'=HYPERLINK("{photo_url}", "View Photo")' if photo_url else "No Photo"
    qr_cell = f'=HYPERLINK("{qr_url}", "View QR")' if qr_url else "No QR"

    dob_str = str(dob) if dob else ""
    date_registered = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    row = [
        breeder_id,            # A: Breeder ID
        sex.capitalize(),      # B: Sex
        variety,               # C: Variety
        lineage,               # D: Lineage / Breeder
        dob_str,               # E: DOB
        "Available",           # F: Status
        photo_cell,            # G: Photo Link
        qr_cell,               # H: QR Code Link
        notes,                 # I: Notes
        date_registered        # J: Date Registered
    ]

    sheets_service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range='Breeders!A:J',
        valueInputOption='USER_ENTERED',
        body={'values': [row]}
    ).execute()

    # Build direct thumbnail URLs for Streamlit display
    direct_photo_url = f"https://drive.google.com/thumbnail?id={photo_id}&sz=w800" if photo_id else None
    direct_qr_url = f"https://drive.google.com/thumbnail?id={qr_id}&sz=w800" if qr_id else None

    return {
        "breeder_id": breeder_id,
        "photo_url": photo_url,
        "qr_url": qr_url,
        "direct_photo_url": direct_photo_url,
        "direct_qr_url": direct_qr_url
    }
