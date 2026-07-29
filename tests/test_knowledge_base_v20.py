from product_finder.knowledge_base import ProductKnowledgeBase


def test_cache_round_trip(tmp_path):
    kb = ProductKnowledgeBase(tmp_path / "kb.sqlite3")
    payload = {"provider": "searxng", "results": [{"title": "Example"}]}
    kb.save_research("ABC-123", payload, "Long Beach", "Standard")
    assert kb.get_research("ABC-123", "Long Beach", "Standard") == payload
    assert kb.stats()["cached_research"] == 1


def test_verified_product_upsert(tmp_path):
    kb = ProductKnowledgeBase(tmp_path / "kb.sqlite3")
    kb.upsert_verified_product(manufacturer="Acme", model="X1", title="Valve", status="Approved")
    assert kb.stats()["verified_products"] == 1
