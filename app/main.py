from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app.db import init_db
from app.services import executor, scheduler
from app.services.google_oauth import authorization_url, connection_status, save_callback_credentials
from app.services.no_code_planner import get_chat_history, handle_chat_message, list_blueprints


app = FastAPI(title="YAG HR Automation POC", version="0.1.0")


class HRSetupRequest(BaseModel):
    sheet_url: str
    sheet_name: str = "Candidates"
    drive_folder_url: Optional[str] = None
    max_days_in_process: int = 10


class CVLinkRequest(BaseModel):
    cv_url: str


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


@app.on_event("startup")
def startup() -> None:
    init_db()
    scheduler.start_scheduler()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/connect/google")
def connect_google() -> RedirectResponse:
    return RedirectResponse(authorization_url())


@app.get("/connections/google/status")
def google_connection_status() -> Dict:
    return connection_status()


@app.get("/chat", response_class=HTMLResponse)
def chat_page() -> HTMLResponse:
    return HTMLResponse(
        """
<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>YAG Chat Workflow</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, sans-serif; margin: 0; background: #f7f7f5; color: #1d1d1f; }
    main { max-width: 920px; margin: 0 auto; padding: 28px 18px; }
    header { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
    h1 { font-size: 24px; margin: 0; }
    .connection { display: flex; align-items: center; gap: 10px; }
    #googleStatus { font-size: 14px; color: #555; }
    #googleButton { width: auto; min-width: 150px; padding: 10px 14px; border: 1px solid #1d1d1f; background: #fff; color: #1d1d1f; border-radius: 6px; }
    #googleButton.connected { border-color: #2e7d32; color: #2e7d32; }
    #googleButton:disabled { opacity: 0.55; cursor: not-allowed; }
    #log { min-height: 58vh; border: 1px solid #ddd; background: #fff; padding: 16px; overflow: auto; }
    .msg { white-space: pre-wrap; padding: 12px; margin: 0 0 10px; border-left: 3px solid #bbb; }
    .user { background: #f0f6ff; border-color: #3578e5; }
    .assistant { background: #f8f8f8; border-color: #2e7d32; }
    form { display: flex; gap: 10px; margin-top: 12px; }
    textarea { flex: 1; min-height: 100px; padding: 12px; font: inherit; resize: vertical; }
    button { width: 120px; border: 0; background: #1d1d1f; color: #fff; font: inherit; cursor: pointer; }
  </style>
</head>
<body>
<main>
  <header>
    <h1>YAG Chat Workflow</h1>
    <div class="connection">
      <span id="googleStatus">Đang kiểm tra Google...</span>
      <button id="googleButton" type="button">Connect Google</button>
    </div>
  </header>
  <div id="log"></div>
  <form id="form">
    <textarea id="message" placeholder="Paste use case hoặc link Google Sheet/Drive ở đây..."></textarea>
    <button>Gửi</button>
  </form>
</main>
<script>
const log = document.getElementById('log');
const form = document.getElementById('form');
const message = document.getElementById('message');
const googleButton = document.getElementById('googleButton');
const googleStatus = document.getElementById('googleStatus');
let googleConnectPopup = null;

function add(role, text) {
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.textContent = (role === 'user' ? 'Bạn: ' : 'YAG: ') + text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

async function refreshGoogleStatus() {
  const res = await fetch('/connections/google/status');
  const status = await res.json();
  googleStatus.textContent = status.message;
  googleButton.disabled = !status.configured || status.connected;
  googleButton.classList.toggle('connected', status.connected);
  googleButton.textContent = status.connected ? 'Google Connected' : 'Connect Google';
  return status;
}

googleButton.addEventListener('click', async () => {
  const status = await refreshGoogleStatus();
  if (!status.configured || status.connected) return;
  googleConnectPopup = window.open(
    status.connect_url,
    'yag_google_connect',
    'width=520,height=720,menubar=no,toolbar=no,location=yes,status=no'
  );
  if (!googleConnectPopup) {
    add('assistant', 'Trình duyệt đang chặn popup. Hãy cho phép popup rồi bấm Connect Google lại.');
  }
});

window.addEventListener('message', (event) => {
  if (event.origin !== window.location.origin) return;
  if (event.data && event.data.type === 'yag.google.connected') {
    refreshGoogleStatus();
    add('assistant', 'Google đã kết nối. Bây giờ bạn gửi link Google Sheet và Drive/CV trong chat, YAG sẽ tự tạo workflow.');
  }
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const text = message.value.trim();
  if (!text) return;
  add('user', text);
  message.value = '';
  const res = await fetch('/chat/messages', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({message: text, session_id: 'default'})
  });
  const data = await res.json();
  add('assistant', data.assistant_message || JSON.stringify(data, null, 2));
  refreshGoogleStatus();
});

refreshGoogleStatus();
</script>
</body>
</html>
        """
    )


@app.get("/oauth/google/callback")
def google_callback(request: Request) -> HTMLResponse:
    save_callback_credentials(str(request.url))
    return HTMLResponse(
        """
<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8" />
  <title>Google Connected</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, sans-serif; padding: 32px; }
    h1 { font-size: 22px; }
  </style>
</head>
<body>
  <h1>Google đã kết nối</h1>
  <p>Cửa sổ này sẽ tự đóng. Bạn có thể quay lại YAG chat.</p>
  <script>
    if (window.opener) {
      window.opener.postMessage({type: 'yag.google.connected'}, window.location.origin);
      window.close();
    }
  </script>
</body>
</html>
        """
    )


@app.post("/chat/messages")
def chat_message(payload: ChatRequest) -> Dict:
    result = handle_chat_message(payload.message, payload.session_id)
    scheduler.reload_jobs()
    return result


@app.get("/chat/history")
def chat_history(session_id: str = "default") -> List[Dict]:
    return get_chat_history(session_id)


@app.get("/workflows")
def workflows(session_id: Optional[str] = None) -> List[Dict]:
    return list_blueprints(session_id)


@app.post("/automations/hr/setup")
def setup_hr(payload: HRSetupRequest) -> dict:
    result = executor.setup_hr_automation(payload.model_dump())
    scheduler.reload_jobs()
    return result


@app.get("/automations")
def automations() -> List[Dict]:
    return executor.list_specs()


@app.post("/automations/{automation_id}/run")
def run_automation(automation_id: str) -> dict:
    return executor.run_automation(automation_id)


@app.post("/automations/{automation_id}/cv-link")
def add_cv_link(automation_id: str, payload: CVLinkRequest) -> dict:
    return executor.run_automation(automation_id, payload.model_dump())


@app.get("/automations/{automation_id}/runs")
def runs(automation_id: str) -> List[Dict]:
    return executor.list_runs(automation_id)
