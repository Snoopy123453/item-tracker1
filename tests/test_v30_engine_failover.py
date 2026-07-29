from product_finder.search import (
    _fallback_engine_attempts,
    searxng_everywhere_search,
    SearchInfrastructureUnavailable,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = status_code == 200
    def json(self):
        return self._payload


def test_fallback_engine_attempts_skip_failed_engines():
    attempts = _fallback_engine_attempts(
        query="black nike hoodie",
        failed_engines=[("brave", "too many requests"), ("duckduckgo", "access denied")],
        language="en",
    )
    assert attempts
    joined = " ".join(item["engines"] for item in attempts)
    assert "brave" not in joined
    assert "duckduckgo" not in joined
    assert any("google" in item["engines"] or "bing" in item["engines"] for item in attempts)


def test_searxng_retries_healthy_engine_pool(monkeypatch):
    calls = []
    responses = [
        FakeResponse({"results": [], "unresponsive_engines": [["startpage", "Suspended: CAPTCHA"]]}),
        FakeResponse({"results": [{"title": "Nike Black Hoodie", "url": "https://www.nike.com/t/hoodie", "content": "Black Nike hoodie"}], "unresponsive_engines": []}),
    ]
    def fake_get(url, params, headers, timeout):
        calls.append(params)
        return responses.pop(0)
    monkeypatch.setattr("product_finder.search.requests.get", fake_get)
    results = searxng_everywhere_search(query="black nike hoodie", base_url="https://search.example")
    assert len(results) == 1
    assert len(calls) == 2
    assert "engines" in calls[1]
    assert "startpage" not in calls[1]["engines"]


def test_searxng_raises_after_all_failover_attempts(monkeypatch):
    def fake_get(url, params, headers, timeout):
        return FakeResponse({"results": [], "unresponsive_engines": [["startpage", "Suspended: CAPTCHA"]]})
    monkeypatch.setattr("product_finder.search.requests.get", fake_get)
    try:
        searxng_everywhere_search(query="black nike hoodie", base_url="https://search.example")
    except SearchInfrastructureUnavailable as exc:
        assert "engine-level failover" in str(exc)
    else:
        raise AssertionError("Expected SearchInfrastructureUnavailable")
