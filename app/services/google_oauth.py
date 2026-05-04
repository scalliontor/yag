from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from app.config import get_settings
from app.db import db, json_dumps, json_loads, utcnow


SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]

IDENTITY_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]

PERMISSION_SCOPES = {
    "drive": {
        "label": "Google Drive",
        "description": "Đọc folder/file CV mà bạn chọn để YAG extract dữ liệu.",
        "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
    },
    "sheets": {
        "label": "Google Sheets",
        "description": "Đọc header, thêm cột YAG, ghi dữ liệu ứng viên và highlight dòng quá hạn.",
        "scopes": ["https://www.googleapis.com/auth/spreadsheets"],
    },
}


def _client_config() -> dict:
    settings = get_settings()
    if settings.google_client_secret_file:
        path = Path(settings.google_client_secret_file)
        if path.exists():
            return json.loads(path.read_text())
    if settings.google_client_id and settings.google_client_secret:
        return {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.google_redirect_uri],
            }
        }
    raise RuntimeError("Set GOOGLE_CLIENT_SECRET_FILE or GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET")


def build_flow(state: str | None = None, scopes: list[str] | None = None) -> Flow:
    flow = Flow.from_client_config(
        _client_config(),
        scopes=scopes or SCOPES,
        redirect_uri=get_settings().google_redirect_uri,
        state=state,
    )
    return flow


def authorization_url(permissions: str | None = None) -> str:
    selected = normalize_permissions(permissions)
    flow = build_flow(state=",".join(selected), scopes=scopes_for_permissions(selected))
    url, _state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return url


def connection_status(user_id: str = "default") -> dict[str, Any]:
    configured = _is_oauth_configured()
    with db() as conn:
        row = conn.execute(
            "SELECT expires_at, updated_at FROM google_credentials WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return {
        "provider": "google",
        "configured": configured,
        "connected": bool(row),
        "expires_at": row["expires_at"] if row else None,
        "updated_at": row["updated_at"] if row else None,
        "connect_url": "/connect/google" if configured else None,
        "default_permissions": ["drive", "sheets"],
        "available_permissions": [
            {"key": key, "label": value["label"], "description": value["description"]}
            for key, value in PERMISSION_SCOPES.items()
        ],
        "message": _status_message(configured, bool(row)),
    }


def save_callback_credentials(authorization_response: str, user_id: str = "default") -> None:
    permissions = _permissions_from_callback_url(authorization_response)
    flow = build_flow(state=",".join(permissions), scopes=scopes_for_permissions(permissions))
    flow.fetch_token(authorization_response=authorization_response)
    creds = flow.credentials
    with db() as conn:
        conn.execute(
            """
            INSERT INTO google_credentials
              (id, user_id, credentials_json, scopes_json, expires_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              credentials_json=excluded.credentials_json,
              scopes_json=excluded.scopes_json,
              expires_at=excluded.expires_at,
              updated_at=excluded.updated_at
            """,
            (
                user_id,
                user_id,
                creds.to_json(),
                json_dumps(creds.scopes or scopes_for_permissions(permissions)),
                creds.expiry.isoformat() if creds.expiry else None,
                utcnow(),
                utcnow(),
            ),
        )


def load_credentials(user_id: str = "default") -> Credentials:
    with db() as conn:
        row = conn.execute(
            "SELECT credentials_json FROM google_credentials WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        raise RuntimeError("Google is not connected. Open /connect/google first.")
    info = json_loads(row["credentials_json"])
    creds = Credentials.from_authorized_user_info(info, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with db() as conn:
            conn.execute(
                "UPDATE google_credentials SET credentials_json=?, expires_at=?, updated_at=? WHERE user_id=?",
                (
                    creds.to_json(),
                    creds.expiry.isoformat() if creds.expiry else None,
                    utcnow(),
                    user_id,
                ),
            )
    return creds


def normalize_permissions(permissions: str | list[str] | None) -> list[str]:
    if not permissions:
        return ["drive", "sheets"]
    raw = permissions if isinstance(permissions, list) else permissions.split(",")
    selected = []
    for item in raw:
        key = item.strip().lower()
        if key in PERMISSION_SCOPES and key not in selected:
            selected.append(key)
    return selected or ["drive", "sheets"]


def scopes_for_permissions(permissions: list[str]) -> list[str]:
    scopes = list(IDENTITY_SCOPES)
    for key in permissions:
        for scope in PERMISSION_SCOPES[key]["scopes"]:
            if scope not in scopes:
                scopes.append(scope)
    return scopes


def _is_oauth_configured() -> bool:
    settings = get_settings()
    if settings.google_client_secret_file and Path(settings.google_client_secret_file).exists():
        return True
    return bool(settings.google_client_id and settings.google_client_secret)


def _status_message(configured: bool, connected: bool) -> str:
    if connected:
        return "Google đã kết nối."
    if configured:
        return "Google sẵn sàng kết nối. Bấm Connect Google để mở popup consent."
    return "Google OAuth chưa được cấu hình bởi app owner."


def _permissions_from_callback_url(authorization_response: str) -> list[str]:
    query = parse_qs(urlparse(authorization_response).query)
    state = query.get("state", [""])[0]
    return normalize_permissions(state)
