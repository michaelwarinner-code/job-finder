"""
Appends one row per submitted application to your real "Jobs I applied to"
Google Sheet tab -- Date, Job Title, Company, Job Description.

Uses OAuth as YOU (your own Google account) rather than a service account
key, since service account key creation is blocked by an organization
policy on this Google Cloud project -- an increasingly common Google
default. This only needs a one-time browser approval; after that, a
cached refresh token in token.json lets every future run happen with no
interaction at all.

Setup:
1. Google Cloud Console -> APIs & Services -> Credentials -> Create
   Credentials -> OAuth client ID.
2. If prompted, configure the OAuth consent screen first (User type:
   External is fine; add your own email as a test user).
3. Application type: Desktop app. Name it anything.
4. Download the resulting JSON, save it as auto-apply/client_secret.json.
   Do NOT commit this file to the repo.

First run opens a browser window asking you to log in and approve access.
That creates auto-apply/token.json (also don't commit this) -- every run
after that is silent.
"""
import os
import re

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SPREADSHEET_ID = "1U72lvejgdJet3j53Nc5oWedHln7H1GqkSB4nWrG0ruQ"
SHEET_TAB_NAME = "Jobs I applied to"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

CLIENT_SECRET_PATH = os.path.join(os.path.dirname(__file__), "client_secret.json")
TOKEN_PATH = os.path.join(os.path.dirname(__file__), "token.json")


def _get_credentials():
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_PATH, SCOPES)
            creds = flow.run_local_server(port=0)  # opens a browser for one-time approval
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return creds


def _get_sheets_service():
    creds = _get_credentials()
    return build("sheets", "v4", credentials=creds)


def _get_sheet_id(service) -> int:
    """Looks up the numeric sheetId for SHEET_TAB_NAME -- cell-note updates
    address a sheet by this numeric id, not its display name."""
    meta = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    for sheet in meta.get("sheets", []):
        if sheet["properties"]["title"] == SHEET_TAB_NAME:
            return sheet["properties"]["sheetId"]
    raise ValueError(f"No tab named {SHEET_TAB_NAME!r} found in this spreadsheet")


def append_application_row(date: str, job_title: str, company: str, job_description: str):
    """Appends one row: Date, Job Title, Company -- the job description
    goes on as a hover NOTE on the Job Description cell (column D), not as
    literal text, so the sheet stays readable instead of one column
    holding a giant wall of text. Hover over column D to read it."""
    service = _get_sheets_service()

    values = [[date, job_title, company]]
    body = {"values": values}
    result = service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_TAB_NAME}!A:C",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body=body,
    ).execute()

    updated_range = result["updates"]["updatedRange"]  # e.g. "'Jobs I applied to'!A64:C64"
    row_number = int(re.search(r"(\d+):[A-Z]+\d+$", updated_range).group(1))
    row_index = row_number - 1  # batchUpdate rows/columns are 0-indexed

    sheet_id = _get_sheet_id(service)
    note_request = {
        "updateCells": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": row_index,
                "endRowIndex": row_index + 1,
                "startColumnIndex": 3,  # column D (Job Description)
                "endColumnIndex": 4,
            },
            "rows": [{"values": [{"note": job_description}]}],
            "fields": "note",
        }
    }
    service.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": [note_request]},
    ).execute()

    return result
