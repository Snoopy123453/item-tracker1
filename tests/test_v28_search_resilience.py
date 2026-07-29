from __future__ import annotations

from pathlib import Path

import pytest

from product_finder.knowledge_base import ProductKnowledgeBase
from product_finder.research_agent import ResearchAgent
from product_finder.search import (
    SearchInfrastructureUnavailable,
    _parse_unresponsive_engines,
    searxng_everywhere_search,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._payload


def test_parse_unresponsive_engines_accepts_searxng_shape():
    data = {
        "unresponsive_engines": [
            ["brave", "Suspended: too many requests"],
            ["duckduckgo", "Suspended: access denied"],
        ]
    }
    assert _parse_unresponsive_engines(data) == [
        ("brave", "Suspended: too many requests"),
        ("duckduckgo", "Suspended: access denied"),
    ]


def test_searxng_outage_is_not_treated_as_no_match(monkeypatch):
    payload = {
        "query": "iPhone 16",
        "results": [],
        "unresponsive_engines": [
            ["brave", "Suspended: too many requests"],
            ["duckduckgo", "Suspended: access denied"],
        ],
    }
    monkeypatch.setattr("product_finder.search.requests.get", lambda *a, **k: FakeResponse(payload))
    with pytest.raises(SearchInfrastructureUnavailable) as exc:
        searxng_everywhere_search(
            query="iPhone 16",
            base_url="https://search.example.com",
            max_results=10,
        )
    assert "Search infrastructure unavailable" in str(exc.value)
    assert "brave" in str(exc.value)


def test_research_agent_does_not_cache_empty_provider_outage(tmp_path, monkeypatch):
    kb = ProductKnowledgeBase(tmp_path / "knowledge.sqlite3")
    agent = ResearchAgent(kb)

    def fail(**kwargs):
        raise SearchInfrastructureUnavailable("all upstream engines unavailable")

    monkeypatch.setattr("product_finder.research_agent.modular_everywhere_search", fail)
    results, notes, meta = agent.research(
        query="iPhone 16",
        location="",
        depth="Standard",
        searxng_url="https://search.example.com",
        brave_api_key="",
        serpapi_api_key="",
        provider_order="searxng",
        country_code="us",
        language="en",
        max_results=20,
        force_refresh=True,
    )
    assert results == []
    assert meta["provider_outage"] is True
    assert meta["status"] == "Provider outage"
    assert kb.get_research("iPhone 16", "", "Standard") is None
    assert any("Search infrastructure unavailable" in note for note in notes)


def test_research_agent_uses_stale_cache_during_outage(tmp_path, monkeypatch):
    kb = ProductKnowledgeBase(tmp_path / "knowledge.sqlite3")
    kb.save_research(
        "JOSAM 30000",
        {
            "results": [{
                "query": "JOSAM 30000", "rank": 1, "title": "JOSAM 30000 official",
                "source_name": "josam.com", "source_domain": "josam.com",
                "source_type": "Official manufacturer", "result_kind": "Product page",
                "link": "https://josam.com/30000",
            }],
            "notes": [],
        },
        ttl_hours=-1,
    )
    agent = ResearchAgent(kb)

    def fail(**kwargs):
        raise SearchInfrastructureUnavailable("engines blocked")

    monkeypatch.setattr("product_finder.research_agent.modular_everywhere_search", fail)
    results, notes, meta = agent.research(
        query="JOSAM 30000", location="", depth="Standard",
        searxng_url="https://search.example.com", brave_api_key="", serpapi_api_key="",
        provider_order="searxng", country_code="us", language="en", max_results=20,
        force_refresh=True,
    )
    assert len(results) == 1
    assert meta["used_stale_cache"] is True
    assert meta["status"] == "Stale cache fallback"
    assert any("expired cached evidence" in note for note in notes)
