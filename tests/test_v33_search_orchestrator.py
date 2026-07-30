from __future__ import annotations

from product_finder.knowledge_base import ProductKnowledgeBase
from product_finder.orchestrator import ProductResearchOrchestrator, build_research_plan


def test_plan_preserves_exact_model():
    plan = build_research_plan("Just Manufacturing USXN1824A-J stainless steel sink")
    assert plan.model_tokens == ["USXN1824A-J"]
    assert '"USXN1824A-J"' in plan.exact_query
    assert "official manufacturer" in plan.manufacturer_query


def test_knowledge_first_returns_saved_evidence(tmp_path):
    kb = ProductKnowledgeBase(tmp_path / "knowledge.sqlite3")
    kb.upsert_verified_product(
        manufacturer="Just Manufacturing",
        model="USXN1824A-J",
        title="Single bowl stainless steel sink",
        status="Verified exact",
        evidence=[{
            "title": "USXN1824A-J official product",
            "link": "https://justmfg.example/products/usxn1824a-j",
            "source_domain": "justmfg.example",
            "official_source": True,
            "exact_model_mentioned": True,
        }],
    )
    orchestrator = ProductResearchOrchestrator(kb)
    results, notes = orchestrator._knowledge_results("Just Manufacturing USXN1824A-J")
    assert len(results) == 1
    assert results[0].official_source is True
    assert results[0].exact_model_mentioned is True
    assert "Knowledge-first" in notes[0]


def test_orchestrator_survives_without_live_provider(tmp_path):
    kb = ProductKnowledgeBase(tmp_path / "knowledge.sqlite3")
    kb.upsert_verified_product(
        manufacturer="JOSAM",
        model="30000-5A-Z",
        title="Floor drain",
        status="Verified exact",
        evidence=[{
            "title": "JOSAM floor drain submittal",
            "link": "https://josam.example/30000-5a-z.pdf",
            "source_domain": "josam.example",
            "official_source": True,
            "exact_model_mentioned": True,
            "document_pdf": True,
        }],
    )
    orchestrator = ProductResearchOrchestrator(kb)
    results, notes, meta = orchestrator.research(
        query="JOSAM 30000-5A-Z",
        searxng_url="",
        brave_api_key="",
        serpapi_api_key="",
        provider_order="searxng",
        country_code="us",
        language="en",
        max_results=20,
        depth="Standard",
        query_budget=8,
        request_timeout=20,
    )
    assert results
    assert meta["knowledge_result_count"] == 1
    assert meta["provider_health"][0]["name"] == "knowledge_base"
