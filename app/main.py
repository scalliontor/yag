from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app.db import init_db
from app.services import executor, scheduler
from app.services.google_oauth import authorization_url, save_callback_credentials


app = FastAPI(title="YAG HR Automation POC", version="0.1.0")


class HRSetupRequest(BaseModel):
    sheet_url: str
    sheet_name: str = "Candidates"
    drive_folder_url: Optional[str] = None
    max_days_in_process: int = 10


class CVLinkRequest(BaseModel):
    cv_url: str


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


@app.get("/oauth/google/callback")
def google_callback(request: Request) -> HTMLResponse:
    save_callback_credentials(str(request.url))
    return HTMLResponse("<h1>Google connected</h1><p>You can close this tab and call the setup API.</p>")


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
