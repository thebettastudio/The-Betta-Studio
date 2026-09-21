# generate_token.py
from google_auth_oauthlib.flow import InstalledAppFlow

# Scopes needed for Google Drive and Google Sheets access
SCOPES = [
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/spreadsheets'
]

def main():
    flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
    creds = flow.run_local_server(port=0)

    # Save credentials for future use
    with open('token.json', 'w') as token_file:
        token_file.write(creds.to_json())

    print("\n✅ Successfully authenticated! 'token.json' has been created.")

if __name__ == '__main__':
    main()
