from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import os
import threading
import uuid
from typing import Any

from product_finder.config import load_config
from product_finder.knowledge_base import ProductKnowledgeBase
from product_finder.research_agent import ResearchAgent


DB_PATH = Path(os.getenv("PRODUCT_HUNTER_DB", ".product_hunter/knowledge.sqlite3"))
kb = ProductKnowledgeBase(DB_PATH)
agent = ResearchAgent(kb)
_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def create_job(query: str) -> dict[str, Any]:
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "status": "queued",
        "query": query,
        "progress": 0,
        "stage": "Queued",
        "results": [],
        "warnings": [],
        "metadata": {},
        "error": None,
    }
    with _lock:
        _jobs[job_id] = job
    return dict(job)


def update_job(job_id: str, **values: Any) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(values)


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def run_research_job(job_id: str, payload: dict[str, Any]) -> None:
    config = load_config()
    try:
        update_job(job_id, status="running", progress=8, stage="Preparing research")

        def progress(message: str) -> None:
            current = get_job(job_id) or {}
            pct = min(88, int(current.get("progress", 8)) + 10)
            update_job(job_id, progress=pct, stage=message)

        results, warnings, metadata = agent.research(
            query=payload["query"],
            location=payload.get("location", ""),
            depth=payload.get("depth", "Standard"),
            searxng_url=config.searxng_url,
            brave_api_key=config.brave_search_api_key,
            serpapi_api_key=config.serpapi_api_key,
            provider_order=config.search_provider_order,
            country_code=config.country_code,
            language=config.language,
            max_results=payload.get("max_results", 25),
            force_refresh=payload.get("force_refresh", False),
            progress=progress,
            cache_ttl_hours=config.research_cache_hours,
            max_workers=config.search_max_workers,
            query_budget=config.search_query_budget,
            request_timeout=config.search_request_timeout,
        )
        update_job(
            job_id,
            status="completed",
            progress=100,
            stage="Complete",
            results=[asdict(item) for item in results],
            warnings=warnings,
            metadata=metadata,
        )
    except Exception as exc:  # defensive API boundary
        update_job(job_id, status="failed", stage="Failed", error=str(exc), progress=100)
