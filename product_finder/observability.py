from __future__ import annotations

import json
import os
import platform
import sqlite3
import sys
import time
import traceback
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import requests


DEFAULT_RUNTIME_DIR = Path(os.getenv("PRODUCT_HUNTER_RUNTIME_DIR", ".product_hunter_runtime"))
ERROR_LOG = DEFAULT_RUNTIME_DIR / "errors.jsonl"
EVENT_LOG = DEFAULT_RUNTIME_DIR / "events.jsonl"


@dataclass(frozen=True)
class HealthCheck:
    name: str
    status: str
    detail: str
    latency_ms: int | None = None
    action: str = ""

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


def _ensure_runtime_dir() -> None:
    DEFAULT_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    _ensure_runtime_dir()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def record_event(event_type: str, message: str, **metadata: Any) -> str:
    event_id = uuid.uuid4().hex[:12]
    _append_jsonl(
        EVENT_LOG,
        {
            "event_id": event_id,
            "timestamp": time.time(),
            "event_type": event_type,
            "message": message,
            "metadata": metadata,
        },
    )
    return event_id


def record_exception(exc: BaseException, *, workspace: str = "unknown", context: dict[str, Any] | None = None) -> str:
    incident_id = uuid.uuid4().hex[:12]
    _append_jsonl(
        ERROR_LOG,
        {
            "incident_id": incident_id,
            "timestamp": time.time(),
            "workspace": workspace,
            "error_type": type(exc).__name__,
            "message": str(exc),
            "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            "context": context or {},
        },
    )
    return incident_id


def read_jsonl(path: Path, limit: int = 100) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-max(1, limit):][::-1]


def recent_errors(limit: int = 100) -> list[dict[str, Any]]:
    return read_jsonl(ERROR_LOG, limit=limit)


def recent_events(limit: int = 100) -> list[dict[str, Any]]:
    return read_jsonl(EVENT_LOG, limit=limit)


def clear_error_log() -> None:
    if ERROR_LOG.exists():
        ERROR_LOG.unlink()


def diagnostics_snapshot(*, app_version: str, config_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "generated_at": time.time(),
        "app_version": app_version,
        "python": sys.version,
        "platform": platform.platform(),
        "config": config_summary or {},
        "recent_errors": recent_errors(50),
        "recent_events": recent_events(50),
    }


def check_searxng(base_url: str, timeout: float = 12.0) -> HealthCheck:
    if not base_url:
        return HealthCheck("SearXNG", "Not configured", "No SEARXNG_URL is configured.", action="Add SEARXNG_URL to Streamlit Secrets.")
    started = time.perf_counter()
    try:
        response = requests.get(
            f"{base_url.rstrip('/')}/search",
            params={"q": "Product Hunter health check", "format": "json"},
            timeout=timeout,
            headers={"User-Agent": "ProductHunterHealth/1.0"},
        )
        latency = round((time.perf_counter() - started) * 1000)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or "results" not in payload:
            return HealthCheck("SearXNG", "Degraded", "Endpoint responded but did not return the expected JSON schema.", latency, "Confirm JSON output is enabled in settings.yml.")
        return HealthCheck("SearXNG", "Healthy", f"JSON search endpoint responded with {len(payload.get('results', []))} result(s).", latency)
    except requests.Timeout:
        latency = round((time.perf_counter() - started) * 1000)
        return HealthCheck("SearXNG", "Degraded", "The server timed out, possibly while waking from sleep.", latency, "Retry after 30–60 seconds or use an always-on Render plan.")
    except Exception as exc:
        latency = round((time.perf_counter() - started) * 1000)
        return HealthCheck("SearXNG", "Down", f"{type(exc).__name__}: {exc}", latency, "Verify the Render URL and deployment logs.")


def check_openai_key(api_key: str) -> HealthCheck:
    if not api_key:
        return HealthCheck("OpenAI", "Not configured", "No OpenAI API key is configured.", action="Add OPENAI_API_KEY to Streamlit Secrets.")
    prefix_ok = api_key.startswith(("sk-", "sk-proj-"))
    return HealthCheck(
        "OpenAI",
        "Configured" if prefix_ok else "Review",
        "API key is present. Live billing/model access is checked only when an AI feature runs." if prefix_ok else "A value is present, but it does not resemble an OpenAI project key.",
        action="Rotate exposed keys and verify API billing." if not prefix_ok else "",
    )


def check_database(db_path: str | Path) -> HealthCheck:
    path = Path(db_path)
    started = time.perf_counter()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS health_check (id INTEGER PRIMARY KEY, checked_at REAL NOT NULL)")
            conn.execute("INSERT INTO health_check (checked_at) VALUES (?)", (time.time(),))
            conn.execute("DELETE FROM health_check WHERE id NOT IN (SELECT id FROM health_check ORDER BY id DESC LIMIT 3)")
            conn.commit()
        latency = round((time.perf_counter() - started) * 1000)
        return HealthCheck("Knowledge database", "Healthy", f"Writable SQLite database at {path}.", latency)
    except Exception as exc:
        latency = round((time.perf_counter() - started) * 1000)
        return HealthCheck("Knowledge database", "Down", f"{type(exc).__name__}: {exc}", latency, "Check filesystem permissions or configure external PostgreSQL storage.")


def run_health_checks(*, searxng_url: str, openai_api_key: str, db_path: str | Path) -> list[HealthCheck]:
    return [
        check_searxng(searxng_url),
        check_openai_key(openai_api_key),
        check_database(db_path),
    ]
