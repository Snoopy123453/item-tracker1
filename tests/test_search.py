from __future__ import annotations

import requests
import pytest

from product_finder.search import _serpapi_get


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
