from __future__ import annotations

from unittest.mock import Mock, patch

from product_finder.search import brave_everywhere_search, modular_everywhere_search, searxng_everywhere_search


def _response(payload: dict, status: int = 200) -> Mock:
    response = Mock()
    response.ok = status == 200
    response.status_code = status
    response.json.return_value = payload
    return response


def test_searxng_normalizes_results() -> None:
    payload = {"results": [{"title": "JOSAM 30000 spec", "url": "https://josam.com/30000.pdf", "content": "JOSAM 30000 technical specification"}]}
    with patch("product_finder.search.requests.get", return_value=_response(payload)):
        rows = searxng_everywhere_search(query="JOSAM 30000", base_url="https://search.example.com")
    assert len(rows) == 1
    assert rows[0].official_source is True
    assert rows[0].document_pdf is True
    assert rows[0].raw_source == "SearXNG"


def test_brave_normalizes_results() -> None:
    payload = {"web": {"results": [{"title": "JOSAM 30000", "url": "https://www.josam.com/p/30000", "description": "Official product"}]}}
    with patch("product_finder.search.requests.get", return_value=_response(payload)):
        rows = brave_everywhere_search(query="JOSAM 30000", api_key="secret")
    assert len(rows) == 1
    assert rows[0].raw_source == "Brave Search API"


def test_modular_search_continues_after_provider_failure() -> None:
    with patch("product_finder.search.searxng_everywhere_search", side_effect=RuntimeError("down")), patch(
        "product_finder.search.brave_everywhere_search", return_value=[]
    ):
        rows, notes = modular_everywhere_search(
            query="test", searxng_url="https://search.example.com", brave_api_key="key", provider_order="searxng,brave"
        )
    assert rows == []
    assert notes and notes[0].startswith("searxng:")
