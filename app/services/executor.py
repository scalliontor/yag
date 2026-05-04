from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from typing import Any

from app.db import db, json_dumps, json_loads, utcnow
from app.services import file_extract, gemma, google_drive, google_sheets
from app.tools.url_parse import (
    drive_file_url,
    parse_drive_file_id,
    parse_drive_folder_id,
    parse_spreadsheet_id,
)


REQUIRED_COLUMNS = [
    "Họ tên",
    "Email",
    "SĐT",
    "Năm sinh",
    "Ngày apply",
    "Trạng thái",
    "Công ty hiện tại",
    "Vị trí hiện tại",
    "Số năm kinh nghiệm",
    "Kỹ năng",
    "Link CV",
    "Link note",
    "Open",
    "YAG Summary",
    "YAG Note",
    "YAG Status",
    "YAG Last Updated",
]

DONE_STATUSES = ["done", "hired", "rejected", "closed", "xong", "đã xong", "fail"]


def setup_hr_automation(payload: dict[str, Any], user_id: str = "default") -> dict[str, Any]:
    spreadsheet_id = parse_spreadsheet_id(payload["sheet_url"])
    sheet_name = payload.get("sheet_name") or "Candidates"
    folder_id = parse_drive_folder_id(payload.get("drive_folder_url"))

    headers = google_sheets.get_headers(spreadsheet_id, sheet_name, user_id)
    detected = _infer_schema(headers)
    missing = google_sheets.add_missing_columns(spreadsheet_id, sheet_name, REQUIRED_COLUMNS, user_id)
    google_sheets.get_headers(spreadsheet_id, sheet_name, user_id)

    cv_spec = {
        "id": "auto_cv_extract_default",
        "type": "cv_extract_to_sheet",
        "name": "Trích xuất dữ liệu CV vào Google Sheet",
        "status": "active",
        "google": {
            "spreadsheet_id": spreadsheet_id,
            "sheet_name": sheet_name,
            "drive_folder_id": folder_id,
        },
        "mapping": {
            "candidate_name": detected["mapping"].get("candidate_name") or "Họ tên",
            "email": detected["mapping"].get("email") or "Email",
            "phone": detected["mapping"].get("phone") or "SĐT",
            "birth_year": detected["mapping"].get("birth_year") or "Năm sinh",
            "current_company": "Công ty hiện tại",
            "position": "Vị trí hiện tại",
            "years_experience": "Số năm kinh nghiệm",
            "skills": "Kỹ năng",
            "cv_link": detected["mapping"].get("cv_link") or "Link CV",
            "note_link": detected["mapping"].get("note_link") or "Link note",
            "open": "Open",
            "summary": "YAG Summary",
            "extract_status": "YAG Status",
            "last_updated": "YAG Last Updated",
        },
        "rules": {"skip_if_email_exists": True, "create_note_link_column": True},
    }
    overdue_spec = {
        "id": "auto_overdue_default",
        "type": "hr_overdue_checker",
        "name": "Kiểm tra ứng viên dở process",
        "status": "active",
        "schedule": {"type": "daily", "hour": 9, "minute": 0, "timezone": "Asia/Ho_Chi_Minh"},
        "google": {"spreadsheet_id": spreadsheet_id, "sheet_name": sheet_name},
        "columns": {
            "candidate_name": detected["mapping"].get("candidate_name") or "Họ tên",
            "apply_date": detected["mapping"].get("apply_date") or "Ngày apply",
            "status": detected["mapping"].get("status") or "Trạng thái",
            "note": "YAG Note",
            "yag_status": "YAG Status",
        },
        "rules": {
            "max_days_in_process": int(payload.get("max_days_in_process") or 10),
            "done_statuses": DONE_STATUSES,
            "highlight_color": {"red": 1.0, "green": 0.8, "blue": 0.8},
            "note_text": "Ứng viên này đang dở process quá hạn, cần xử lý.",
        },
    }
    _save_spec(cv_spec, user_id)
    _save_spec(overdue_spec, user_id)

    files = google_drive.list_files(folder_id, user_id) if folder_id else []
    return {
        "automation_ids": [cv_spec["id"], overdue_spec["id"]],
        "detected_columns": headers,
        "inferred_mapping": detected["mapping"],
        "missing_columns_added": missing,
        "drive_files_sample": files[:10],
        "status": "active",
    }


def run_automation(automation_id: str, input_data: dict[str, Any] | None = None, user_id: str = "default") -> dict[str, Any]:
    spec = _load_spec(automation_id)
    run_id = _start_run(automation_id, input_data or {})
    try:
        if spec["type"] == "cv_extract_to_sheet":
            result = run_cv_extractor(spec, input_data or {}, user_id)
        elif spec["type"] == "hr_overdue_checker":
            result = run_overdue_checker(spec, user_id)
        else:
            raise ValueError(f"Unsupported automation type: {spec['type']}")
        _finish_run(run_id, "success", result, None)
        return {"run_id": run_id, "status": "success", "output": result}
    except Exception as exc:
        _finish_run(run_id, "failed", None, str(exc))
        raise


def run_cv_extractor(spec: dict[str, Any], input_data: dict[str, Any], user_id: str = "default") -> dict[str, Any]:
    cv_url = input_data.get("cv_url")
    file_ids = [parse_drive_file_id(cv_url)] if cv_url else []
    folder_id = spec["google"].get("drive_folder_id")
    if not file_ids and folder_id:
        file_ids = [f["id"] for f in google_drive.list_files(folder_id, user_id)]
    if not file_ids:
        raise ValueError("Provide cv_url or configure drive_folder_id")

    processed = []
    for file_id in file_ids:
        data, meta = google_drive.download_file(file_id, user_id)
        text = file_extract.extract_text(data, meta.get("name", file_id), meta.get("mimeType"))
        extracted = _normalize_cv(gemma.extract_cv(text))
        upsert = upsert_candidate(spec, extracted, meta, user_id)
        processed.append({"file_id": file_id, "file_name": meta.get("name"), **upsert})
    return {"processed": processed, "count": len(processed)}


def run_overdue_checker(spec: dict[str, Any], user_id: str = "default") -> dict[str, Any]:
    spreadsheet_id = spec["google"]["spreadsheet_id"]
    sheet_name = spec["google"]["sheet_name"]
    headers, rows = google_sheets.read_rows(spreadsheet_id, sheet_name, user_id)
    columns = spec["columns"]
    rules = spec["rules"]
    overdue = []

    for row in rows:
        apply_date = parse_date(str(row.get(columns["apply_date"], "")).strip())
        if not apply_date:
            continue
        status = normalize_status(str(row.get(columns["status"], "")))
        days = (date.today() - apply_date).days
        if days >= rules["max_days_in_process"] and status not in set(rules["done_statuses"]):
            row_number = int(row["_row_number"])
            google_sheets.highlight_row(spreadsheet_id, sheet_name, row_number, rules["highlight_color"], user_id)
            google_sheets.update_cell(spreadsheet_id, sheet_name, row_number, columns["note"], rules["note_text"], user_id)
            google_sheets.update_cell(spreadsheet_id, sheet_name, row_number, columns["yag_status"], "overdue", user_id)
            overdue.append({"row_number": row_number, "candidate": row.get(columns["candidate_name"]), "days": days})
        elif columns.get("yag_status") in headers:
            google_sheets.update_cell(spreadsheet_id, sheet_name, int(row["_row_number"]), columns["yag_status"], "ok", user_id)

    return {"overdue_count": len(overdue), "overdue": overdue}


def upsert_candidate(spec: dict[str, Any], extracted: dict[str, Any], meta: dict[str, Any], user_id: str) -> dict[str, Any]:
    spreadsheet_id = spec["google"]["spreadsheet_id"]
    sheet_name = spec["google"]["sheet_name"]
    mapping = spec["mapping"]
    headers, rows = google_sheets.read_rows(spreadsheet_id, sheet_name, user_id)
    key_email = normalize_email(extracted.get("email"))
    key_phone = normalize_phone(extracted.get("phone"))

    target = None
    for row in rows:
        row_email = normalize_email(row.get(mapping["email"]))
        row_phone = normalize_phone(row.get(mapping["phone"]))
        if key_email and row_email == key_email:
            target = row
            break
        if not key_email and key_phone and row_phone == key_phone:
            target = row
            break

    file_url = meta.get("webViewLink") or drive_file_url(meta["id"])
    values = dict(target or {})
    values.update(
        {
            mapping["candidate_name"]: extracted.get("full_name") or values.get(mapping["candidate_name"], ""),
            mapping["email"]: extracted.get("email") or values.get(mapping["email"], ""),
            mapping["phone"]: extracted.get("phone") or values.get(mapping["phone"], ""),
            mapping["birth_year"]: extracted.get("birth_year") or values.get(mapping["birth_year"], ""),
            mapping["current_company"]: extracted.get("current_company") or "",
            mapping["position"]: extracted.get("current_position") or "",
            mapping["years_experience"]: extracted.get("years_experience") or "",
            mapping["skills"]: ", ".join(extracted.get("skills") or []),
            mapping["cv_link"]: file_url,
            mapping["open"]: f'=HYPERLINK("{file_url}", "Mở CV")',
            mapping["summary"]: extracted.get("summary") or "",
            mapping["extract_status"]: "extracted" if key_email or key_phone else "needs_review",
            mapping["last_updated"]: utcnow(),
        }
    )
    values.pop("_row_number", None)

    if target:
        row_number = int(target["_row_number"])
        google_sheets.update_row(spreadsheet_id, sheet_name, row_number, headers, values, user_id)
        action = "updated"
    else:
        google_sheets.append_row(spreadsheet_id, sheet_name, headers, values, user_id)
        row_number = None
        action = "appended"
    return {"action": action, "row_number": row_number, "candidate": extracted.get("full_name")}


def parse_date(value: str) -> date | None:
    if not value:
        return None
    value = value.strip()
    formats = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m", "%d-%m"]
    for fmt in formats:
        try:
            parsed = datetime.strptime(value, fmt)
            year = parsed.year if "%Y" in fmt else date.today().year
            return date(year, parsed.month, parsed.day)
        except ValueError:
            continue
    return None


def normalize_status(value: str) -> str:
    return value.strip().lower()


def normalize_email(value: Any) -> str:
    text = str(value or "").strip().lower()
    match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text)
    return match.group(0) if match else ""


def normalize_phone(value: Any) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def list_runs(automation_id: str) -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM automation_runs WHERE automation_id=? ORDER BY started_at DESC LIMIT 50",
            (automation_id,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "automation_id": row["automation_id"],
            "status": row["status"],
            "input": json_loads(row["input_json"], {}),
            "output": json_loads(row["output_json"], None),
            "error_message": row["error_message"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }
        for row in rows
    ]


def list_specs() -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute("SELECT spec_json FROM automation_specs ORDER BY created_at").fetchall()
    return [json_loads(row["spec_json"]) for row in rows]


def _infer_schema(headers: list[str]) -> dict[str, Any]:
    try:
        return gemma.infer_sheet_schema(headers)
    except Exception:
        lower = {h.lower(): h for h in headers}
        def pick(*needles: str) -> str | None:
            for needle in needles:
                for key, original in lower.items():
                    if needle in key:
                        return original
            return None

        return {
            "mapping": {
                "candidate_name": pick("họ tên", "ho ten", "name", "ứng viên", "ung vien"),
                "email": pick("email", "mail"),
                "phone": pick("sđt", "sdt", "phone", "điện thoại", "dien thoai"),
                "birth_year": pick("năm sinh", "nam sinh", "birth"),
                "apply_date": pick("ngày apply", "ngay apply", "apply", "date"),
                "status": pick("trạng thái", "trang thai", "status"),
                "cv_link": pick("cv", "resume"),
                "note_link": pick("note", "ghi chú", "ghi chu"),
            },
            "missing_recommended_columns": [],
        }


def _normalize_cv(data: dict[str, Any]) -> dict[str, Any]:
    email = normalize_email(data.get("email"))
    if email:
        data["email"] = email
    year = data.get("birth_year")
    if year is not None:
        try:
            year = int(year)
            data["birth_year"] = year if 1960 <= year <= 2010 else None
        except (TypeError, ValueError):
            data["birth_year"] = None
    exp = data.get("years_experience")
    if exp is not None:
        try:
            exp = float(exp)
            data["years_experience"] = exp if 0 <= exp <= 50 else None
        except (TypeError, ValueError):
            data["years_experience"] = None
    if not isinstance(data.get("skills"), list):
        data["skills"] = []
    return data


def _save_spec(spec: dict[str, Any], user_id: str) -> None:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO automation_specs
              (id, user_id, name, type, status, spec_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              name=excluded.name,
              type=excluded.type,
              status=excluded.status,
              spec_json=excluded.spec_json,
              updated_at=excluded.updated_at
            """,
            (spec["id"], user_id, spec["name"], spec["type"], spec["status"], json_dumps(spec), utcnow(), utcnow()),
        )


def _load_spec(automation_id: str) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute("SELECT spec_json FROM automation_specs WHERE id=?", (automation_id,)).fetchone()
    if not row:
        raise ValueError(f"Automation not found: {automation_id}")
    return json_loads(row["spec_json"])


def _start_run(automation_id: str, input_data: dict[str, Any]) -> str:
    run_id = str(uuid.uuid4())
    with db() as conn:
        conn.execute(
            "INSERT INTO automation_runs (id, automation_id, status, input_json, started_at) VALUES (?, ?, ?, ?, ?)",
            (run_id, automation_id, "running", json_dumps(input_data), utcnow()),
        )
    return run_id


def _finish_run(run_id: str, status: str, output: dict[str, Any] | None, error: str | None) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE automation_runs SET status=?, output_json=?, error_message=?, finished_at=? WHERE id=?",
            (status, json_dumps(output) if output is not None else None, error, utcnow(), run_id),
        )
