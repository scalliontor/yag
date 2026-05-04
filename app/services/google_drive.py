from __future__ import annotations

from io import BytesIO

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from app.services.google_oauth import load_credentials


def drive_service(user_id: str = "default"):
    return build("drive", "v3", credentials=load_credentials(user_id), cache_discovery=False)


def list_files(folder_id: str, user_id: str = "default") -> list[dict]:
    service = drive_service(user_id)
    query = f"'{folder_id}' in parents and trashed = false"
    result = service.files().list(
        q=query,
        fields="files(id,name,mimeType,webViewLink,modifiedTime,size)",
        orderBy="modifiedTime desc",
        pageSize=100,
    ).execute()
    return result.get("files", [])


def get_file(file_id: str, user_id: str = "default") -> dict:
    return drive_service(user_id).files().get(
        fileId=file_id,
        fields="id,name,mimeType,webViewLink,modifiedTime,size",
    ).execute()


def download_file(file_id: str, user_id: str = "default") -> tuple[bytes, dict]:
    service = drive_service(user_id)
    meta = get_file(file_id, user_id)
    request = service.files().get_media(fileId=file_id)
    buffer = BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _status, done = downloader.next_chunk()
    return buffer.getvalue(), meta
