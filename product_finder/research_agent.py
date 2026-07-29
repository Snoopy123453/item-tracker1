from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable

from .knowledge_base import ProductKnowledgeBase
from .models import OmniSearchResult
from .search import modular_everywhere_search


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
    ) -> tuple[list[OmniSearchResult], list[str], dict[str, Any]]:
        if not force_refresh:
            cached = self.knowledge_base.get_research(query, location, depth)
            if cached:
                rows = cached.get("results", [])
                return [OmniSearchResult(**row) for row in rows], list(cached.get("notes", [])), {
                    "cache_hit": True,
                    "query": query,
                }

        if progress:
            progress(f"Researching {query}")
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
        )
        self.knowledge_base.save_research(
            query,
            {"results": [asdict(r) for r in results], "notes": notes},
            location,
            depth,
        )
        return results, notes, {"cache_hit": False, "query": query}
