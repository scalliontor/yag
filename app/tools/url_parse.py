from __future__ import annotations

import re


def parse_spreadsheet_id(url_or_id: str) -> str:
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url_or_id)
    return match.group(1) if match else url_or_id.strip()


def parse_drive_folder_id(url_or_id: str | None) -> str | None:
    if not url_or_id:
        return None
    match = re.search(r"/folders/([a-zA-Z0-9_-]+)", url_or_id)
    return match.group(1) if match else url_or_id.strip()


def parse_drive_file_id(url_or_id: str) -> str:
    patterns = [
        r"/file/d/([a-zA-Z0-9_-]+)",
        r"[?&]id=([a-zA-Z0-9_-]+)",
        r"/document/d/([a-zA-Z0-9_-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    return url_or_id.strip()


def drive_file_url(file_id: str) -> str:
    return f"https://drive.google.com/file/d/{file_id}/view"
