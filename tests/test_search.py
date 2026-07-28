from __future__ import annotations

import requests
import pytest

from product_finder.search import _serpapi_get, google_manufacturer_search


def test_http_error_does_not_expose_key(monkeypatch) -> None:
    class Response:
        ok = False
        status_code = 401

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())

    with pytest.raises(RuntimeError) as exc_info:
        _serpapi_get({"api_key": "top-secret", "q": "item"})

    assert "top-secret" not in str(exc_info.value)
    assert "401" in str(exc_info.value)


def test_request_exception_does_not_expose_key(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise requests.RequestException("https://example.test?api_key=top-secret")

    monkeypatch.setattr(requests, "get", fail)

    with pytest.raises(RuntimeError) as exc_info:
        _serpapi_get({"api_key": "top-secret", "q": "item"})

    assert "top-secret" not in str(exc_info.value)


def test_manufacturer_search_prioritizes_official(monkeypatch):
    payload = {
        "organic_results": [
            {"title": "JOSAM 30000 Floor Drain", "link": "https://www.josam.com/p/PRODUCT/30000", "snippet": "Official JOSAM product page for 30000 series"},
            {"title": "JOSAM 30000 at Amazon", "link": "https://www.amazon.com/example", "snippet": "Marketplace listing"},
        ]
    }
    monkeypatch.setattr("product_finder.search._serpapi_get", lambda params: payload)
    results = google_manufacturer_search(query="JOSAM 30000-5A-Z floor drain", api_key="test")
    assert len(results) == 1
    assert results[0].official_source is True
    assert results[0].source_domain == "josam.com"
    assert results[0].exact_model_mentioned is False
