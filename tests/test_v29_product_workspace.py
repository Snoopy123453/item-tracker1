from pathlib import Path
from product_finder.knowledge_base import ProductKnowledgeBase

def test_product_workspace_storage(tmp_path: Path):
    kb = ProductKnowledgeBase(tmp_path / "knowledge.sqlite3")
    key = kb.upsert_verified_product(manufacturer="JOSAM", model="30002-5A-Z-50", title="Floor drain", status="Verified exact", evidence=[{"title": "Official spec"}])
    kb.add_product_event(key, "Reviewed", "Approved", "Daniel")
    kb.add_product_note(key, "Confirm lead time", "Daniel")
    kb.update_verified_product_status(key, "Quoted", "Awaiting vendor")
    assert kb.get_verified_product(key)["status"] == "Quoted"
    assert len(kb.list_product_events(key)) == 1
    assert len(kb.list_product_notes(key)) == 1

def test_delete_product_cascades_workspace_records(tmp_path: Path):
    kb = ProductKnowledgeBase(tmp_path / "knowledge.sqlite3")
    key = kb.upsert_verified_product(manufacturer="Acme", model="A-1", title="Test", status="Needs review")
    kb.add_product_event(key, "Specified")
    kb.add_product_note(key, "Test note")
    kb.delete_verified_product(key)
    assert kb.get_verified_product(key) is None
    assert kb.list_product_events(key) == []
    assert kb.list_product_notes(key) == []
