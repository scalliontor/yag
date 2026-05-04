from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from openai import OpenAI

from app.config import get_settings


def _client() -> OpenAI:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for LLM extraction")
    return OpenAI(base_url=settings.openai_base_url, api_key=settings.openai_api_key)


def _prompt(name: str, **values: str) -> str:
    text = Path(__file__).resolve().parents[1].joinpath("prompts", name).read_text()
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def infer_sheet_schema(headers: list[str]) -> dict[str, Any]:
    return call_json(_prompt("infer_sheet_schema.txt", headers=json.dumps(headers, ensure_ascii=False)))


def extract_cv(cv_text: str) -> dict[str, Any]:
    return call_json(_prompt("extract_cv.txt", cv_text=cv_text[:45000]))


def call_json(prompt: str) -> dict[str, Any]:
    settings = get_settings()
    response = _client().chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": "Return valid JSON only. Do not use markdown."},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )
    content = response.choices[0].message.content or "{}"
    try:
        return parse_json(content)
    except Exception:
        return repair_json(content)


def parse_json(content: str) -> dict[str, Any]:
    code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, flags=re.S)
    if code_block:
        content = code_block.group(1)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        candidate = _first_json_object(content)
        if candidate:
            return json.loads(candidate)
        raise


def repair_json(content: str) -> dict[str, Any]:
    settings = get_settings()
    response = _client().chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": "You fix malformed JSON. Return valid JSON only."},
            {
                "role": "user",
                "content": (
                    "Convert this malformed response into one valid JSON object. "
                    "Keep the original meaning. Do not add markdown.\n\n" + content
                ),
            },
        ],
        temperature=0,
    )
    repaired = response.choices[0].message.content or "{}"
    return parse_json(repaired)


def _first_json_object(content: str) -> str | None:
    start = content.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(content)):
        char = content[idx]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return content[start : idx + 1]
    return None
