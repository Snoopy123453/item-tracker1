from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable
import time

from .knowledge_base import ProductKnowledgeBase
from .models import OmniSearchResult
from .search import SearchInfrastructureUnavailable, modular_everywhere_search


class ResearchAgent:
    """Provider-neutral procurement research with persistent, transparent caching."""

    def __init__(self, knowledge_base: ProductKnowledgeBase) -> None:
        self.knowledge_base = knowledge_base

    def research(
        self,
        *,
        query: str,
        location: str,
        depth: str,
        searxng_url: str,
        brave_api_key: str,
        serpapi_api_key: str,
        provider_order: str,
        country_code: str,
        language: str,
        max_results: int,
        force_refresh: bool = False,
        progress: Callable[[str], None] | None = None,
        cache_ttl_hours: int = 72,
        max_workers: int = 3,
        query_budget: int = 10,
        request_timeout: int = 45,
    ) -> tuple[list[OmniSearchResult], list[str], dict[str, Any]]:
        started = time.monotonic()
        if not force_refresh:
            cached = self.knowledge_base.get_research(query, location, depth)
            if cached:
                rows = cached.get("results", [])
                notes = list(cached.get("notes", []))
                restored = [OmniSearchResult(**row) for row in rows]
                duration = time.monotonic() - started
                run_id = self.knowledge_base.record_research_run(
                    query=query, location=location, depth=depth, provider_order=provider_order,
                    cache_hit=True, result_count=len(restored), warning_count=len(notes),
                    duration_seconds=duration, status="Cache hit",
                )
                return restored, notes, {
                    "cache_hit": True, "query": query, "duration_seconds": duration, "run_id": run_id,
                }

        if progress:
            progress(f"Researching {query}")
        provider_outage = False
        used_stale_cache = False
        try:
            results, notes = modular_everywhere_search(
                query=query,
                searxng_url=searxng_url,
                brave_api_key=brave_api_key,
                serpapi_api_key=serpapi_api_key,
                provider_order=provider_order,
                country_code=country_code,
                language=language,
                max_results=max_results,
                research_depth=depth.casefold(),
                max_workers=max_workers,
                query_budget=query_budget,
                request_timeout=request_timeout,
            )
        except SearchInfrastructureUnavailable as exc:
            provider_outage = True
            stale = self.knowledge_base.get_stale_research(query, location, depth)
            if stale and stale.get("results"):
                rows = stale.get("results", [])
                results = [OmniSearchResult(**row) for row in rows]
                notes = list(stale.get("notes", [])) + [
                    f"Search infrastructure unavailable; showing expired cached evidence: {exc}"
                ]
                used_stale_cache = True
            else:
                results = []
                notes = [f"Search infrastructure unavailable: {exc}"]
        except Exception as exc:
            stale = self.knowledge_base.get_stale_research(query, location, depth)
            if not stale or not stale.get("results"):
                raise
            rows = stale.get("results", [])
            results = [OmniSearchResult(**row) for row in rows]
            notes = list(stale.get("notes", [])) + [f"Live providers failed; showing expired cache: {exc}"]
            used_stale_cache = True

        # Never cache an empty response. A zero-result provider outage must not poison
        # future searches for hours or days.
        if results and not used_stale_cache:
            self.knowledge_base.save_research(
                query,
                {"results": [asdict(r) for r in results], "notes": notes},
                location,
                depth,
                ttl_hours=cache_ttl_hours,
            )
        duration = time.monotonic() - started
        if provider_outage and not results:
            status = "Provider outage"
        elif used_stale_cache:
            status = "Stale cache fallback"
        elif results:
            status = "Completed"
        else:
            status = "No matching results"
        run_id = self.knowledge_base.record_research_run(
            query=query, location=location, depth=depth, provider_order=provider_order,
            cache_hit=used_stale_cache, result_count=len(results), warning_count=len(notes),
            duration_seconds=duration, status=status,
        )
        return results, notes, {
            "cache_hit": used_stale_cache,
            "query": query,
            "duration_seconds": duration,
            "run_id": run_id,
            "provider_outage": provider_outage,
            "used_stale_cache": used_stale_cache,
            "status": status,
        }
