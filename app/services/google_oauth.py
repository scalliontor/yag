from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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


def build_flow(state: str | None = None) -> Flow:
    flow = Flow.from_client_config(
        _client_config(),
        scopes=SCOPES,
        redirect_uri=get_settings().google_redirect_uri,
        state=state,
    )
    return flow


def authorization_url() -> str:
    flow = build_flow()
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
        "message": _status_message(configured, bool(row)),
    }


def save_callback_credentials(authorization_response: str, user_id: str = "default") -> None:
    flow = build_flow()
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
                json_dumps(creds.scopes or SCOPES),
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
