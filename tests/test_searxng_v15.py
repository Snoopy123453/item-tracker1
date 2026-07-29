from product_finder.config import load_config
from product_finder.search import targeted_searxng_search


def test_default_provider_order_excludes_brave(monkeypatch):
    for key in ("SEARCH_PROVIDER_ORDER", "SEARXNG_URL", "BRAVE_SEARCH_API_KEY", "SERPAPI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    cfg = load_config()
    assert cfg.search_provider_order == "searxng,serpapi"


def test_targeted_search_uses_multiple_variants(monkeypatch):
    calls=[]
    def fake(**kwargs):
        calls.append(kwargs["query"])
        return []
    monkeypatch.setattr("product_finder.search.searxng_everywhere_search", fake)
    results, notes = targeted_searxng_search(query="JOSAM 30000-5A-Z", base_url="https://search.example")
    assert results == []
    assert notes == []
    assert len(calls) == 5
    assert any("spec sheet" in q for q in calls)
    assert any("discontinued" in q for q in calls)
