from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\u200b", "").strip()


def unique_keep_order(items: Iterable[str], max_items: int | None = None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = clean_text(item)
        if not cleaned:
            continue
        key = re.sub(r"\s+", " ", cleaned).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
        if max_items is not None and len(result) >= max_items:
            break
    return result


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract a JSON object from model output.

    Handles plain JSON and ```json fenced blocks.
    """
    text = clean_text(text)
    if not text:
        return {}
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    candidate = fenced.group(1) if fenced else text
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", candidate, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}


def safe_filename(name: str, default: str = "export") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._")
    return cleaned or default


def ensure_directory(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p
