from __future__ import annotations

from typing import Any

from googleapiclient.discovery import build

from app.services.google_oauth import load_credentials


def sheets_service(user_id: str = "default"):
    return build("sheets", "v4", credentials=load_credentials(user_id), cache_discovery=False)


def get_headers(spreadsheet_id: str, sheet_name: str, user_id: str = "default") -> list[str]:
    service = sheets_service(user_id)
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!1:1",
    ).execute()
    return result.get("values", [[]])[0]


def read_rows(spreadsheet_id: str, sheet_name: str, user_id: str = "default") -> tuple[list[str], list[dict[str, Any]]]:
    service = sheets_service(user_id)
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=sheet_name,
    ).execute()
    values = result.get("values", [])
    headers = values[0] if values else []
    rows: list[dict[str, Any]] = []
    for offset, raw in enumerate(values[1:], start=2):
        row = {header: raw[idx] if idx < len(raw) else "" for idx, header in enumerate(headers)}
        row["_row_number"] = offset
        rows.append(row)
    return headers, rows


def add_missing_columns(spreadsheet_id: str, sheet_name: str, required: list[str], user_id: str = "default") -> list[str]:
    headers = get_headers(spreadsheet_id, sheet_name, user_id)
    missing = [col for col in required if col not in headers]
    if missing:
        new_headers = headers + missing
        sheets_service(user_id).spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!1:1",
            valueInputOption="USER_ENTERED",
            body={"values": [new_headers]},
        ).execute()
    return missing


def update_row(spreadsheet_id: str, sheet_name: str, row_number: int, headers: list[str], values: dict[str, Any], user_id: str = "default") -> None:
    row = [values.get(header, "") for header in headers]
    sheets_service(user_id).spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A{row_number}",
        valueInputOption="USER_ENTERED",
        body={"values": [row]},
    ).execute()


def append_row(spreadsheet_id: str, sheet_name: str, headers: list[str], values: dict[str, Any], user_id: str = "default") -> None:
    row = [values.get(header, "") for header in headers]
    sheets_service(user_id).spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=sheet_name,
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()


def update_cell(spreadsheet_id: str, sheet_name: str, row_number: int, header: str, value: Any, user_id: str = "default") -> None:
    headers = get_headers(spreadsheet_id, sheet_name, user_id)
    col = headers.index(header) + 1
    sheets_service(user_id).spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!{_a1_col(col)}{row_number}",
        valueInputOption="USER_ENTERED",
        body={"values": [[value]]},
    ).execute()


def highlight_row(spreadsheet_id: str, sheet_name: str, row_number: int, color: dict, user_id: str = "default") -> None:
    service = sheets_service(user_id)
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet_id = next(s["properties"]["sheetId"] for s in meta["sheets"] if s["properties"]["title"] == sheet_name)
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": row_number - 1,
                            "endRowIndex": row_number,
                        },
                        "cell": {"userEnteredFormat": {"backgroundColor": color}},
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                }
            ]
        },
    ).execute()


def _a1_col(index: int) -> str:
    letters = ""
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters
