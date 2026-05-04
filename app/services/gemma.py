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
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    content = response.choices[0].message.content or "{}"
    return parse_json(content)


def parse_json(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))
