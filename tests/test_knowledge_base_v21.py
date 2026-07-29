from product_finder.knowledge_base import ProductKnowledgeBase


def test_kb_management_round_trip(tmp_path):
    kb = ProductKnowledgeBase(tmp_path / "kb.sqlite3")
    kb.save_research("JOSAM 30000", {"omni_results": []}, ttl_hours=1)
    assert kb.list_cached_research()[0]["query"] == "JOSAM 30000"
    key = kb.upsert_verified_product(manufacturer="JOSAM", model="30000", title="Floor Drain", status="Verified exact", evidence=[{"source": "official"}])
    rows = kb.list_verified_products()
    assert rows[0]["product_key"] == key
    assert rows[0]["evidence"][0]["source"] == "official"
    snapshot = kb.export_snapshot()
    assert snapshot["verified_products"]
    kb.delete_verified_product(key)
    assert kb.list_verified_products() == []
    assert kb.clear_research_cache() == 1
