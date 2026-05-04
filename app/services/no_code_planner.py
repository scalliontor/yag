from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.db import db, json_dumps, json_loads, utcnow
from app.services import executor, gemma


def handle_chat_message(message: str, session_id: str = "default") -> Dict[str, Any]:
    context = _known_context(session_id, message)
    _save_message(session_id, "user", message, {})

    blueprint = _build_blueprint(message, context)
    blueprint_id = _save_blueprint(session_id, blueprint)

    setup_result: Optional[Dict[str, Any]] = None
    if _can_auto_create(blueprint, context):
        setup_payload = {
            "sheet_url": context["sheet_url"],
            "sheet_name": context.get("sheet_name") or "Candidates",
            "drive_folder_url": context.get("drive_folder_url"),
            "max_days_in_process": context.get("max_days_in_process") or 10,
        }
        setup_result = executor.setup_hr_automation(setup_payload)
        blueprint["status"] = "activated"
        blueprint["automation_ids"] = setup_result["automation_ids"]
        _save_blueprint(session_id, blueprint, blueprint_id)

    reply = _assistant_reply(blueprint, setup_result)
    _save_message(session_id, "assistant", reply, {"blueprint_id": blueprint_id})

    return {
        "session_id": session_id,
        "assistant_message": reply,
        "blueprint_id": blueprint_id,
        "blueprint": blueprint,
        "setup_result": setup_result,
    }


def get_chat_history(session_id: str = "default") -> List[Dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            "SELECT role, content, metadata_json, created_at FROM chat_messages WHERE session_id=? ORDER BY created_at",
            (session_id,),
        ).fetchall()
    return [
        {
            "role": row["role"],
            "content": row["content"],
            "metadata": json_loads(row["metadata_json"], {}),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def list_blueprints(session_id: Optional[str] = None) -> List[Dict[str, Any]]:
    with db() as conn:
        if session_id:
            rows = conn.execute(
                "SELECT id, blueprint_json FROM workflow_blueprints WHERE session_id=? ORDER BY created_at DESC",
                (session_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT id, blueprint_json FROM workflow_blueprints ORDER BY created_at DESC").fetchall()
    return [{"id": row["id"], **json_loads(row["blueprint_json"], {})} for row in rows]


def _build_blueprint(message: str, context: Dict[str, Any]) -> Dict[str, Any]:
    known_context = json.dumps(context, ensure_ascii=False)
    try:
        prompt = _prompt("create_workflow_from_chat.txt", message=message, known_context=known_context)
        blueprint = gemma.call_json(prompt)
    except Exception as exc:
        blueprint = _fallback_hr_blueprint(message, context)
        blueprint["planner_warning"] = f"LLM planner fallback used: {exc}"

    blueprint.setdefault("status", "draft")
    blueprint.setdefault("missing_inputs", _missing_inputs(context))
    blueprint.setdefault("connections_needed", ["Google Workspace"])
    return blueprint


def _fallback_hr_blueprint(message: str, context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "intent": "hr_candidate_workflow",
        "confidence": 0.82 if _looks_like_hr(message) else 0.35,
        "workflow_name": "HR candidate automation",
        "user_goal_summary": "Tự động lấy dữ liệu ứng viên từ CV vào Google Sheet, tạo link mở nhanh CV/note, và highlight ứng viên quá hạn process.",
        "can_build_with_current_tools": True,
        "missing_inputs": _missing_inputs(context),
        "connections_needed": ["Google Workspace"],
        "workflow": {
            "trigger": {"type": "drive_polling", "description": "Quét folder Drive hoặc nhận link CV thủ công."},
            "nodes": [
                {
                    "id": "connect_google",
                    "type": "google.oauth.connect",
                    "label": "Kết nối Google Drive/Sheets",
                    "uses_ai": False,
                    "inputs": {},
                    "outputs": {"credentials": "google_credentials"},
                    "error_shield": {"retry": 0, "fallback": "Yêu cầu user connect lại Google"},
                },
                {
                    "id": "infer_sheet",
                    "type": "ai.infer_sheet_schema",
                    "label": "AI hiểu cấu trúc Sheet ứng viên",
                    "uses_ai": True,
                    "inputs": {"headers": "Google Sheet row 1"},
                    "outputs": {"mapping": "candidate fields to sheet columns"},
                    "error_shield": {"retry": 1, "fallback": "Dùng mapping mặc định tiếng Việt"},
                },
                {
                    "id": "extract_cv",
                    "type": "ai.extract_cv",
                    "label": "AI đọc CV và trích xuất họ tên/email/SĐT/năm sinh",
                    "uses_ai": True,
                    "inputs": {"cv_text": "file.extract_text"},
                    "outputs": {"candidate_profile": "structured JSON"},
                    "error_shield": {"retry": 1, "fallback": "Ghi YAG Status = needs_review"},
                },
                {
                    "id": "write_sheet",
                    "type": "google.sheets.append_or_update_candidate",
                    "label": "Ghi dữ liệu vào Google Sheet và tạo nút Mở CV",
                    "uses_ai": False,
                    "inputs": {"candidate_profile": "extract_cv.output"},
                    "outputs": {"sheet_row": "updated candidate row"},
                    "error_shield": {"retry": 2, "fallback": "Ghi run log để xử lý lại"},
                },
                {
                    "id": "daily_overdue",
                    "type": "google.sheets.highlight_row",
                    "label": "Mỗi ngày highlight ứng viên quá hạn process",
                    "uses_ai": False,
                    "inputs": {"max_days_in_process": context.get("max_days_in_process") or 10},
                    "outputs": {"overdue_rows": "highlighted rows"},
                    "error_shield": {"retry": 2, "fallback": "Ghi lỗi vào run log"},
                },
            ],
            "loop_mode": {"enabled": True, "over": "drive_files"},
            "schedule": {"type": "daily", "time": "09:00", "timezone": "Asia/Ho_Chi_Minh"},
        },
        "next_assistant_message": "",
    }


def _assistant_reply(blueprint: Dict[str, Any], setup_result: Optional[Dict[str, Any]]) -> str:
    if setup_result:
        return (
            "Mình đã tạo workflow HR và activate automation thật. "
            f"Automation IDs: {', '.join(setup_result['automation_ids'])}. "
            "Bạn có thể chạy thử endpoint CV link hoặc overdue checker ngay."
        )

    missing = blueprint.get("missing_inputs") or []
    if missing:
        lines = [
            "Mình hiểu use case này và đã dựng workflow draft. Để chạy thật, mình cần thêm:",
        ]
        for item in missing:
            lines.append(f"- {item['label']}: {item.get('example', '')}")
        lines.append("Sau khi bạn gửi các thông tin này trong chat, YAG sẽ tự tạo automation Google Drive/Sheets.")
        return "\n".join(lines)

    return blueprint.get("next_assistant_message") or "Mình đã tạo workflow draft. Bạn có thể review blueprint hoặc yêu cầu activate."


def _known_context(session_id: str, message: str) -> Dict[str, Any]:
    text = "\n".join([m["content"] for m in get_chat_history(session_id) if m["role"] == "user"] + [message])
    return {
        "sheet_url": _first_match(r"https://docs\.google\.com/spreadsheets/[^\s]+", text),
        "drive_folder_url": _first_match(r"https://drive\.google\.com/drive/folders/[^\s]+", text),
        "cv_url": _first_match(r"https://drive\.google\.com/file/d/[^\s]+", text),
        "sheet_name": _first_match(r"(?:sheet|tab|sheet_name)\s*[:=]\s*([^\n,]+)", text, group=1),
        "max_days_in_process": _extract_days(text),
        "looks_like_hr": _looks_like_hr(text),
    }


def _missing_inputs(context: Dict[str, Any]) -> List[Dict[str, str]]:
    missing = []
    if not context.get("sheet_url"):
        missing.append(
            {
                "key": "sheet_url",
                "label": "Link Google Sheet quản lý ứng viên",
                "why_needed": "YAG cần đọc header, thêm cột YAG và ghi dữ liệu ứng viên.",
                "example": "https://docs.google.com/spreadsheets/d/xxx/edit",
            }
        )
    if not context.get("drive_folder_url") and not context.get("cv_url"):
        missing.append(
            {
                "key": "drive_folder_url",
                "label": "Link folder Drive chứa CV hoặc một link CV mẫu",
                "why_needed": "YAG cần nơi lấy CV để extract dữ liệu.",
                "example": "https://drive.google.com/drive/folders/yyy",
            }
        )
    return missing


def _can_auto_create(blueprint: Dict[str, Any], context: Dict[str, Any]) -> bool:
    return (
        blueprint.get("intent") == "hr_candidate_workflow"
        and bool(context.get("sheet_url"))
        and bool(context.get("drive_folder_url") or context.get("cv_url"))
    )


def _looks_like_hr(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in ["hr", "ứng viên", "uv", "cv", "phỏng vấn", "pv", "apply"])


def _extract_days(text: str) -> Optional[int]:
    explicit = re.search(r"quá\s+(\d+)\s+ngày|sau\s+(\d+)\s+ngày|(\d+)\s+ngày", text, flags=re.I)
    if explicit:
        for value in explicit.groups():
            if value:
                return int(value)
    dates = re.findall(r"(\d{1,2})/(\d{1,2})", text)
    if len(dates) >= 2:
        start_day, start_month = map(int, dates[0])
        end_day, end_month = map(int, dates[1])
        if start_month == end_month:
            return max(1, end_day - start_day)
    return None


def _first_match(pattern: str, text: str, group: int = 0) -> Optional[str]:
    match = re.search(pattern, text, flags=re.I)
    if not match:
        return None
    return match.group(group).strip().rstrip(".,)")


def _save_message(session_id: str, role: str, content: str, metadata: Dict[str, Any]) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO chat_messages (id, session_id, role, content, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), session_id, role, content, json_dumps(metadata), utcnow()),
        )


def _save_blueprint(session_id: str, blueprint: Dict[str, Any], blueprint_id: Optional[str] = None) -> str:
    blueprint_id = blueprint_id or str(uuid.uuid4())
    with db() as conn:
        conn.execute(
            """
            INSERT INTO workflow_blueprints (id, session_id, name, status, blueprint_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              name=excluded.name,
              status=excluded.status,
              blueprint_json=excluded.blueprint_json,
              updated_at=excluded.updated_at
            """,
            (
                blueprint_id,
                session_id,
                blueprint.get("workflow_name") or "Untitled workflow",
                blueprint.get("status") or "draft",
                json_dumps(blueprint),
                utcnow(),
                utcnow(),
            ),
        )
    return blueprint_id


def _prompt(name: str, **values: str) -> str:
    text = Path(__file__).resolve().parents[1].joinpath("prompts", name).read_text()
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text

