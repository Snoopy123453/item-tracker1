from __future__ import annotations

from typing import Any

import requests

from .models import InputRecord, ProductResult, StoreResult
from .utils import clean_text, unique_keep_order

SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
USER_AGENT = "ProductHunterWebApp/1.0"


def _serpapi_get(params: dict[str, Any], *, timeout: int = 60) -> dict[str, Any]:
    """Call SerpApi without ever surfacing a URL that contains the API key."""
    api_key = clean_text(params.get("api_key"))
    if not api_key:
        raise ValueError("SerpApi is not configured for live product and store searches.")

    try:
        response = requests.get(
            SERPAPI_ENDPOINT,
            params=params,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=(10, timeout),
        )
    except requests.Timeout as exc:
        raise RuntimeError("The retailer search service timed out. Please try again.") from exc
    except requests.RequestException as exc:
        raise RuntimeError("The retailer search service could not be reached.") from exc

    if not response.ok:
        raise RuntimeError(f"The retailer search service returned HTTP {response.status_code}.")

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError("The retailer search service returned an invalid response.") from exc

    if isinstance(data, dict) and data.get("error"):
        # Keep provider feedback useful while redacting the configured key if a
        # remote error message unexpectedly echoes it.
        message = clean_text(data["error"]) or "The retailer search service returned an error."
        if api_key:
            message = message.replace(api_key, "[redacted]")
        raise RuntimeError(message)
    return data if isinstance(data, dict) else {}


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _delivery_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, dict):
        return "; ".join(f"{k}: {v}" for k, v in value.items() if v)
    if isinstance(value, list):
        return "; ".join(clean_text(v) for v in value if clean_text(v))
    return clean_text(value)


def google_lens_queries_from_url(
    *,
    image_url: str,
    api_key: str,
    country_code: str = "us",
    language: str = "en",
    extra_query_hint: str = "",
    max_queries: int = 4,
) -> InputRecord:
    """Use SerpApi Google Lens for a publicly reachable image URL."""
    params: dict[str, Any] = {
        "engine": "google_lens",
        "url": image_url,
        "type": "products",
        "country": country_code,
        "hl": language,
        "api_key": api_key,
    }
    if clean_text(extra_query_hint):
        params["q"] = clean_text(extra_query_hint)

    try:
        data = _serpapi_get(params)
    except Exception as exc:  # noqa: BLE001 - return a per-input note instead of aborting the run.
        return InputRecord(
            input_type="image_url",
            label=image_url,
            source_url=image_url,
            notes=f"Google Lens lookup failed: {exc}",
        )

    candidate_titles: list[str] = []
    for block_name in ["visual_matches", "shopping_results", "products", "exact_matches", "matches"]:
        block = data.get(block_name, [])
        if isinstance(block, list):
            for item in block:
                if isinstance(item, dict):
                    title = clean_text(item.get("title") or item.get("name"))
                    source = clean_text(item.get("source"))
                    if title:
                        candidate_titles.append(f"{title} {source}".strip())

    queries = unique_keep_order(candidate_titles, max_items=max_queries)
    product_name = queries[0] if queries else ""
    return InputRecord(
        input_type="image_url",
        label=image_url,
        source_url=image_url,
        extracted_product_name=product_name,
        generated_queries=queries,
        notes="Queries generated from Google Lens product matches."
        if queries
        else "No Google Lens product matches were returned.",
    )


def google_shopping_search(
    *,
    query: str,
    input_source: str,
    api_key: str,
    location: str = "",
    country_code: str = "us",
    language: str = "en",
    max_results: int = 10,
) -> list[ProductResult]:
    params: dict[str, Any] = {
        "engine": "google_shopping",
        "q": query,
        "gl": country_code,
        "hl": language,
        "api_key": api_key,
    }
    if clean_text(location):
        params["location"] = clean_text(location)

    data = _serpapi_get(params)
    items = data.get("shopping_results") or data.get("inline_shopping_results") or []
    results: list[ProductResult] = []
    if not isinstance(items, list):
        return results

    for idx, item in enumerate(items[:max_results], start=1):
        if not isinstance(item, dict):
            continue
        results.append(
            ProductResult(
                query=query,
                input_source=input_source,
                rank=idx,
                title=clean_text(item.get("title")),
                seller=clean_text(item.get("source") or item.get("seller")),
                price=clean_text(item.get("price")),
                extracted_price=_as_float(item.get("extracted_price")),
                delivery=_delivery_to_text(item.get("delivery")),
                rating=_as_float(item.get("rating")),
                reviews=_as_int(item.get("reviews")),
                condition=clean_text(item.get("second_hand_condition") or item.get("condition")),
                snippet=clean_text(item.get("snippet") or item.get("extensions")),
                product_link=clean_text(item.get("product_link") or item.get("link")),
                seller_link=clean_text(item.get("link") or item.get("product_link")),
                thumbnail=clean_text(item.get("thumbnail") or item.get("serpapi_thumbnail")),
                search_location=clean_text(location),
            )
        )
    return results


def google_maps_nearby_stores(
    *,
    query: str,
    api_key: str,
    location: str = "",
    country_code: str = "us",
    language: str = "en",
    max_results: int = 5,
) -> list[StoreResult]:
    if max_results <= 0:
        return []
    maps_query = f"{query} near {location}" if clean_text(location) else f"{query} retailer store"
    params: dict[str, Any] = {
        "engine": "google_maps",
        "type": "search",
        "q": maps_query,
        "gl": country_code,
        "hl": language,
        "api_key": api_key,
    }
    data = _serpapi_get(params)
    items = data.get("local_results") or []
    results: list[StoreResult] = []
    if not isinstance(items, list):
        return results

    for idx, item in enumerate(items[:max_results], start=1):
        if not isinstance(item, dict):
            continue
        links = item.get("links") if isinstance(item.get("links"), dict) else {}
        gps = item.get("gps_coordinates") if isinstance(item.get("gps_coordinates"), dict) else {}
        maps_link = clean_text(item.get("place_id_search") or item.get("link"))
        if not maps_link and gps.get("latitude") and gps.get("longitude"):
            maps_link = (
                "https://www.google.com/maps/search/?api=1&query="
                f"{gps.get('latitude')},{gps.get('longitude')}"
            )
        store_types = item.get("types", []) if isinstance(item.get("types"), list) else []
        results.append(
            StoreResult(
                query=query,
                rank=idx,
                title=clean_text(item.get("title")),
                store_type=clean_text(item.get("type") or ", ".join(store_types)),
                address=clean_text(item.get("address")),
                phone=clean_text(item.get("phone")),
                rating=_as_float(item.get("rating")),
                reviews=_as_int(item.get("reviews")),
                hours=clean_text(item.get("hours") or item.get("open_state")),
                website=clean_text(links.get("website") or item.get("website")),
                directions=clean_text(links.get("directions") or item.get("directions")),
                maps_link=maps_link,
                search_location=clean_text(location),
            )
        )
    return results
