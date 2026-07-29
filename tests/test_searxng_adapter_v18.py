from unittest.mock import Mock, patch

from product_finder.search import searxng_everywhere_search


def _response(payload):
    response = Mock()
    response.status_code = 200
    response.ok = True
    response.json.return_value = payload
    return response


def test_searxng_uses_minimal_params_and_normalizes_results():
    payload = {"results": [{"title": "Apple iPhone 15", "url": "https://www.apple.com/iphone-15/", "content": "Official iPhone 15 page"}]}
    with patch("product_finder.search.requests.get", return_value=_response(payload)) as get:
        results = searxng_everywhere_search(query="iPhone 15", base_url="https://search.example", language="en")
    assert len(results) == 1
    assert results[0].title == "Apple iPhone 15"
    assert get.call_args.kwargs["params"] == {"q": "iPhone 15", "format": "json"}


def test_searxng_retries_localized_when_minimal_is_empty():
    empty = _response({"results": []})
    populated = _response({"results": [{"title": "Result", "url": "https://example.com/item", "content": "item"}]})
    with patch("product_finder.search.requests.get", side_effect=[empty, populated]) as get:
        results = searxng_everywhere_search(query="item", base_url="https://search.example", language="en")
    assert len(results) == 1
    assert get.call_count == 2
    assert get.call_args_list[1].kwargs["params"]["language"] == "en-US"
    assert get.call_args_list[1].kwargs["params"]["safesearch"] == 0
