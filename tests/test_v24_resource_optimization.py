from pathlib import Path
from product_finder.config import load_config
from product_finder.search import build_procurement_query_variants

def test_resource_defaults(monkeypatch):
    for name in ["RESOURCE_PROFILE", "RESEARCH_CACHE_HOURS", "SEARCH_MAX_WORKERS", "SEARCH_QUERY_BUDGET", "SEARCH_REQUEST_TIMEOUT"]:
        monkeypatch.delenv(name, raising=False)
    cfg = load_config()
    assert cfg.resource_profile == "Balanced"
    assert cfg.research_cache_hours == 72
    assert cfg.search_max_workers == 3
    assert cfg.search_query_budget == 10
    assert cfg.search_request_timeout == 45

def test_query_budget_is_enforced():
    rows = build_procurement_query_variants("JOSAM 30000-5A-Z", research_depth="deep", query_budget=5)
    assert len(rows) == 5
    assert rows[0] == "JOSAM 30000-5A-Z"

def test_v24_ui_contains_profiles():
    text = (Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8")
    assert 'APP_VERSION = "25.0"' in text
    assert '"Efficient", "Balanced", "Thorough"' in text
    assert "resource-card" in text
