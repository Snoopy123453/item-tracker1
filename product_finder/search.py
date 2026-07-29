from __future__ import annotations

from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed

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


def google_spec_sheet_search(
    *,
    query: str,
    api_key: str,
    country_code: str = "us",
    language: str = "en",
    max_results: int = 5,
) -> list["SpecDocument"]:
    """Find likely product spec sheets, submittals, and technical PDFs."""
    from urllib.parse import urlparse
    from .models import SpecDocument

    if max_results <= 0:
        return []
    search_query = f'"{query}" (spec sheet OR submittal OR technical data OR installation manual OR warranty OR parts diagram OR CAD OR BIM OR Revit)'
    data = _serpapi_get(
        {
            "engine": "google",
            "q": search_query,
            "gl": country_code,
            "hl": language,
            "num": min(max_results * 2, 10),
            "api_key": api_key,
        }
    )
    items = data.get("organic_results") or []
    results: list[SpecDocument] = []
    query_tokens = [token.lower() for token in query.replace("/", " ").replace("-", " ").split() if len(token) > 2]
    for item in items:
        if not isinstance(item, dict):
            continue
        link = clean_text(item.get("link"))
        title = clean_text(item.get("title"))
        snippet = clean_text(item.get("snippet"))
        displayed = clean_text(item.get("displayed_link"))
        if not link:
            continue
        domain = urlparse(link).netloc.lower().removeprefix("www.")
        text = f"{title} {snippet} {link}".lower()
        token_hits = sum(1 for token in query_tokens if token in text)
        confidence = "Exact" if query_tokens and token_hits >= max(1, len(query_tokens) - 1) else "Likely" if token_hits else "Possible"
        doc_type = (
            "Installation manual" if "installation" in text or "manual" in text
            else "Warranty" if "warranty" in text
            else "Parts diagram" if "parts" in text or "exploded" in text
            else "CAD/BIM/Revit" if any(term in text for term in ("cad", "bim", "revit"))
            else "Submittal" if "submittal" in text
            else "Spec sheet"
        )
        results.append(
            SpecDocument(
                query=query,
                rank=len(results) + 1,
                title=title,
                document_type=doc_type,
                source_domain=domain,
                link=link,
                displayed_link=displayed,
                snippet=snippet,
                official_source=bool(query_tokens and any(token in domain for token in query_tokens[:2])),
                pdf_link=link.lower().split("?")[0].endswith(".pdf"),
                match_confidence=confidence,
            )
        )
        if len(results) >= max_results:
            break
    return results


def google_manufacturer_search(
    *,
    query: str,
    api_key: str,
    country_code: str = "us",
    language: str = "en",
    max_results: int = 5,
) -> list["ManufacturerResult"]:
    """Search official manufacturer websites and rank product/catalog pages above marketplaces."""
    from urllib.parse import urlparse
    from .models import ManufacturerResult

    if max_results <= 0:
        return []

    cleaned_query = clean_text(query)
    tokens = [t for t in cleaned_query.replace("/", " ").replace("-", " ").split() if t]
    manufacturer = " ".join(tokens[:2]) if len(tokens) > 1 else (tokens[0] if tokens else "")
    model_tokens = [t for t in tokens if any(ch.isdigit() for ch in t)]
    search_query = f'"{cleaned_query}" (official OR manufacturer OR product OR catalog OR specification) -amazon -ebay -walmart'
    data = _serpapi_get({
        "engine": "google",
        "q": search_query,
        "gl": country_code,
        "hl": language,
        "num": min(max_results * 3, 20),
        "api_key": api_key,
    })
    items = data.get("organic_results") or []
    marketplace_domains = {
        "amazon.com", "ebay.com", "walmart.com", "homedepot.com", "lowes.com",
        "zoro.com", "grainger.com", "build.com", "supplyhouse.com", "ferguson.com",
    }
    manufacturer_terms = [t.lower() for t in tokens[:2] if len(t) > 2]
    results: list[ManufacturerResult] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        link = clean_text(item.get("link"))
        if not link:
            continue
        domain = urlparse(link).netloc.lower().removeprefix("www.")
        if domain in seen:
            continue
        title = clean_text(item.get("title"))
        snippet = clean_text(item.get("snippet"))
        haystack = f"{title} {snippet} {link}".lower()
        exact_model = bool(model_tokens and all(token.lower() in haystack for token in model_tokens))
        domain_tokens = domain.replace("-", " ").replace(".", " ").split()
        official = domain not in marketplace_domains and any(term in domain_tokens or term in domain for term in manufacturer_terms)
        if not official and domain in marketplace_domains:
            continue
        page_type = (
            "PDF / technical document" if link.lower().split("?")[0].endswith(".pdf")
            else "Catalog page" if "catalog" in haystack
            else "Support / documentation" if any(x in haystack for x in ("manual", "spec", "submittal", "support", "download"))
            else "Product page"
        )
        confidence = "Official exact model" if official and exact_model else "Likely official" if official else "Possible manufacturer source"
        results.append(ManufacturerResult(
            query=cleaned_query,
            rank=0,
            title=title,
            manufacturer=manufacturer,
            source_domain=domain,
            page_type=page_type,
            link=link,
            snippet=snippet,
            official_source=official,
            exact_model_mentioned=exact_model,
            source_confidence=confidence,
        ))
        seen.add(domain)

    results.sort(key=lambda r: (not r.official_source, not r.exact_model_mentioned, r.source_domain))
    for idx, result in enumerate(results[:max_results], start=1):
        result.rank = idx
    return results[:max_results]

# --- OmniSearch v12 ---------------------------------------------------------
from urllib.parse import urlparse, urlunparse
from .models import OmniSearchResult

_MARKETPLACE_DOMAINS = {
    "amazon.com", "ebay.com", "walmart.com", "homedepot.com", "lowes.com",
    "bestbuy.com", "target.com", "etsy.com", "aliexpress.com",
}
_DISTRIBUTOR_DOMAINS = {
    "ferguson.com", "grainger.com", "supplyhouse.com", "zoro.com", "build.com",
    "hdsupplysolutions.com", "fastenal.com", "mcmaster.com", "winsupplyinc.com",
    "globalindustrial.com", "uline.com", "hajoca.com", "firstsupply.com",
}
_DOC_TERMS = ("spec", "submittal", "manual", "installation", "warranty", "parts", "cad", "bim", "revit", "datasheet", "technical")
_LEGACY_TERMS = ("discontinued", "obsolete", "legacy", "superseded", "replacement", "archived", "archive")


def _canonical_url(url: str) -> str:
    try:
        parsed = urlparse(url.strip())
        return urlunparse((parsed.scheme.lower(), parsed.netloc.lower().removeprefix("www."), parsed.path.rstrip("/"), "", "", ""))
    except Exception:
        return url.strip().lower()


def _query_model_tokens(query: str) -> list[str]:
    return [t.lower() for t in clean_text(query).replace("/", " ").split() if any(ch.isdigit() for ch in t) and len(t) >= 3]


def _classify_web_result(*, query: str, title: str, snippet: str, link: str) -> tuple[str, str, bool, bool, bool, bool, float, str]:
    domain = urlparse(link).netloc.lower().removeprefix("www.")
    text = f"{title} {snippet} {link}".lower()
    model_tokens = _query_model_tokens(query)
    exact_model = bool(model_tokens and all(token in text for token in model_tokens))
    is_pdf = link.lower().split("?")[0].endswith(".pdf")
    legacy = any(term in text for term in _LEGACY_TERMS)
    document = is_pdf or any(term in text for term in _DOC_TERMS)
    marketplace = domain in _MARKETPLACE_DOMAINS or any(domain.endswith("." + d) for d in _MARKETPLACE_DOMAINS)
    distributor = domain in _DISTRIBUTOR_DOMAINS or any(domain.endswith("." + d) for d in _DISTRIBUTOR_DOMAINS)

    query_words = [w.lower() for w in clean_text(query).replace("-", " ").split() if len(w) > 2 and not any(ch.isdigit() for ch in w)]
    likely_brand = query_words[0] if query_words else ""
    official = bool(likely_brand and likely_brand in domain.replace("-", "")) and not marketplace and not distributor

    if legacy:
        source_type = "Legacy / discontinued"
    elif official and document:
        source_type = "Official manufacturer document"
    elif official:
        source_type = "Official manufacturer"
    elif distributor:
        source_type = "Distributor"
    elif marketplace:
        source_type = "Retailer / marketplace"
    elif document:
        source_type = "Technical document"
    else:
        source_type = "General web"

    if document:
        result_kind = "PDF / technical document" if is_pdf else "Documentation page"
    elif "product" in text or exact_model:
        result_kind = "Product page"
    elif legacy:
        result_kind = "Archive / lifecycle page"
    else:
        result_kind = "Web result"

    reliability = 95.0 if official and exact_model else 90.0 if official else 85.0 if distributor and exact_model else 78.0 if distributor else 68.0 if document else 58.0 if marketplace else 45.0
    evidence_parts = []
    if exact_model: evidence_parts.append("Exact model text found")
    if official: evidence_parts.append("Likely official manufacturer domain")
    if distributor: evidence_parts.append("Known distributor domain")
    if is_pdf: evidence_parts.append("Direct PDF")
    if legacy: evidence_parts.append("Lifecycle/legacy terms found")
    return source_type, result_kind, official, distributor, exact_model, legacy, reliability, "; ".join(evidence_parts)


def google_everywhere_search(
    *, query: str, api_key: str, country_code: str = "us", language: str = "en", max_results: int = 20,
) -> list[OmniSearchResult]:
    """Broad organic search covering manufacturers, distributors, documents, retailers, and legacy pages."""
    if max_results <= 0:
        return []
    q = clean_text(query)
    broad_query = (
        f'"{q}" (product OR manufacturer OR distributor OR supplier OR price OR buy OR '
        '"spec sheet" OR submittal OR manual OR warranty OR CAD OR BIM OR Revit OR '
        'discontinued OR obsolete OR superseded OR replacement)'
    )
    data = _serpapi_get({
        "engine": "google", "q": broad_query, "gl": country_code, "hl": language,
        "num": min(max_results, 100), "api_key": api_key,
    })
    items = data.get("organic_results") or []
    results: list[OmniSearchResult] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        link = clean_text(item.get("link"))
        if not link:
            continue
        title = clean_text(item.get("title"))
        snippet = clean_text(item.get("snippet"))
        domain = urlparse(link).netloc.lower().removeprefix("www.")
        source_type, kind, official, distributor, exact_model, legacy, reliability, evidence = _classify_web_result(
            query=q, title=title, snippet=snippet, link=link
        )
        match = 100.0 if exact_model else 72.0 if all(tok in f"{title} {snippet}".lower() for tok in q.lower().split()[:2]) else 55.0
        overall = round(match * 0.62 + reliability * 0.38, 1)
        status = "Verified exact source" if exact_model and official else "Exact model found" if exact_model else "Likely relevant" if overall >= 65 else "Needs review"
        results.append(OmniSearchResult(
            query=q, rank=0, title=title, source_name=domain, source_domain=domain,
            source_type=source_type, result_kind=kind, link=link, snippet=snippet,
            official_source=official, authorized_distributor=distributor,
            exact_model_mentioned=exact_model, document_pdf=link.lower().split("?")[0].endswith(".pdf"),
            legacy_or_discontinued=legacy, source_reliability=reliability,
            match_score=match, overall_score=overall, verification_status=status,
            evidence=evidence, raw_source="Google organic / SerpApi",
        ))
    return rank_omni_results(results)


def omni_from_existing(
    *, products: list[ProductResult], specs: list["SpecDocument"], manufacturers: list["ManufacturerResult"], stores: list[StoreResult],
) -> list[OmniSearchResult]:
    """Convert existing specialized search results into the unified OmniSearch schema."""
    out: list[OmniSearchResult] = []
    for p in products:
        domain = urlparse(p.product_link or p.seller_link).netloc.lower().removeprefix("www.")
        distributor = domain in _DISTRIBUTOR_DOMAINS
        reliability = 78.0 if distributor else 58.0
        score = float(p.match_score or 0.0)
        out.append(OmniSearchResult(query=p.query, rank=0, title=p.title, source_name=p.seller, source_domain=domain,
            source_type="Distributor" if distributor else "Retailer / marketplace", result_kind="Shopping listing",
            link=p.product_link or p.seller_link, snippet=p.snippet, price=p.price, extracted_price=p.extracted_price,
            delivery=p.delivery, authorized_distributor=distributor, exact_model_mentioned=bool(p.exact_model_match),
            source_reliability=reliability, match_score=score, overall_score=round(score*0.72+reliability*0.28,1),
            verification_status="Exact model found" if p.exact_model_match else "Needs review", evidence=p.score_breakdown,
            raw_source=p.raw_source))
    for d in specs:
        reliability = 92.0 if d.official_source else 70.0
        match = 98.0 if d.match_confidence == "Exact" else 82.0 if d.match_confidence == "Likely" else 62.0
        out.append(OmniSearchResult(query=d.query, rank=0, title=d.title, source_name=d.source_domain, source_domain=d.source_domain,
            source_type="Official manufacturer document" if d.official_source else "Technical document", result_kind=d.document_type,
            link=d.link, snippet=d.snippet, official_source=d.official_source, exact_model_mentioned=d.match_confidence=="Exact",
            document_pdf=d.pdf_link, source_reliability=reliability, match_score=match,
            overall_score=round(match*0.6+reliability*0.4,1), verification_status="Document evidence" if d.match_confidence != "Possible" else "Needs review",
            evidence=f"Document confidence: {d.match_confidence}", raw_source=d.raw_source))
    for m in manufacturers:
        reliability = 98.0 if m.official_source else 62.0
        match = 100.0 if m.exact_model_mentioned else 75.0
        out.append(OmniSearchResult(query=m.query, rank=0, title=m.title, source_name=m.manufacturer or m.source_domain,
            source_domain=m.source_domain, source_type="Official manufacturer" if m.official_source else "General web",
            result_kind=m.page_type, link=m.link, snippet=m.snippet, official_source=m.official_source,
            exact_model_mentioned=m.exact_model_mentioned, document_pdf=m.page_type.startswith("PDF"),
            source_reliability=reliability, match_score=match, overall_score=round(match*0.6+reliability*0.4,1),
            verification_status="Verified exact source" if m.official_source and m.exact_model_mentioned else m.source_confidence,
            evidence=m.source_confidence, raw_source=m.raw_source))
    for s in stores:
        out.append(OmniSearchResult(query=s.query, rank=0, title=s.title, source_name=s.title,
            source_domain=urlparse(s.website).netloc.lower().removeprefix("www."), source_type="Local supplier",
            result_kind="Nearby store", link=s.website or s.maps_link, snippet=f"{s.address}; {s.phone}; {s.hours}",
            location=s.address, source_reliability=55.0, match_score=45.0, overall_score=49.0,
            verification_status="Local lead — inventory unconfirmed", evidence="Google Maps business result", raw_source=s.raw_source))
    return out


def rank_omni_results(results: list[OmniSearchResult]) -> list[OmniSearchResult]:
    seen: dict[str, OmniSearchResult] = {}
    for item in results:
        key = _canonical_url(item.link) or f"{item.query.lower()}|{item.title.lower()}|{item.source_domain}"
        prior = seen.get(key)
        if prior is None or item.overall_score > prior.overall_score:
            seen[key] = item
    ranked = list(seen.values())
    ranked.sort(key=lambda r: (
        r.query.lower(), -float(r.overall_score), not r.official_source, not r.exact_model_mentioned,
        r.source_type, r.title.lower()
    ))
    counters: dict[str, int] = {}
    for item in ranked:
        counters[item.query] = counters.get(item.query, 0) + 1
        item.rank = counters[item.query]
    return ranked

# --- Modular search providers v14 -------------------------------------------
BRAVE_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


def _organic_to_omni(*, query: str, items: list[dict[str, Any]], raw_source: str) -> list[OmniSearchResult]:
    """Normalize generic web-search responses into OmniSearch results."""
    results: list[OmniSearchResult] = []
    q = clean_text(query)
    for item in items:
        if not isinstance(item, dict):
            continue
        link = clean_text(item.get("url") or item.get("link"))
        if not link:
            continue
        title = clean_text(item.get("title") or item.get("name"))
        snippet = clean_text(item.get("description") or item.get("content") or item.get("snippet"))
        domain = urlparse(link).netloc.lower().removeprefix("www.")
        source_type, kind, official, distributor, exact_model, legacy, reliability, evidence = _classify_web_result(
            query=q, title=title, snippet=snippet, link=link
        )
        query_terms = [t.lower() for t in q.replace("-", " ").split() if len(t) > 2]
        haystack = f"{title} {snippet} {link}".lower()
        coverage = sum(1 for t in query_terms if t in haystack) / max(1, len(query_terms))
        match = 100.0 if exact_model else round(45.0 + 45.0 * coverage, 1)
        overall = round(match * 0.62 + reliability * 0.38, 1)
        status = "Verified exact source" if exact_model and official else "Exact model found" if exact_model else "Likely relevant" if overall >= 65 else "Needs review"
        results.append(OmniSearchResult(
            query=q, rank=0, title=title, source_name=domain, source_domain=domain,
            source_type=source_type, result_kind=kind, link=link, snippet=snippet,
            official_source=official, authorized_distributor=distributor,
            exact_model_mentioned=exact_model, document_pdf=link.lower().split("?")[0].endswith(".pdf"),
            legacy_or_discontinued=legacy, source_reliability=reliability,
            match_score=match, overall_score=overall, verification_status=status,
            evidence=evidence, raw_source=raw_source,
        ))
    return results


def brave_everywhere_search(
    *, query: str, api_key: str, country_code: str = "us", language: str = "en", max_results: int = 20,
) -> list[OmniSearchResult]:
    """Search Brave's independent web index and normalize results."""
    if not clean_text(api_key):
        return []
    params = {
        "q": clean_text(query),
        "count": max(1, min(int(max_results), 20)),
        "country": (country_code or "us").upper(),
        "search_lang": language or "en",
        "safesearch": "moderate",
        "text_decorations": "false",
    }
    try:
        response = requests.get(
            BRAVE_SEARCH_ENDPOINT,
            params=params,
            headers={"X-Subscription-Token": api_key, "Accept": "application/json", "User-Agent": USER_AGENT},
            timeout=(10, 45),
        )
    except requests.Timeout as exc:
        raise RuntimeError("Brave Search timed out.") from exc
    except requests.RequestException as exc:
        raise RuntimeError("Brave Search could not be reached.") from exc
    if not response.ok:
        raise RuntimeError(f"Brave Search returned HTTP {response.status_code}.")
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError("Brave Search returned invalid JSON.") from exc
    items = ((data.get("web") or {}).get("results") or []) if isinstance(data, dict) else []
    return _organic_to_omni(query=query, items=items, raw_source="Brave Search API")


def searxng_everywhere_search(
    *, query: str, base_url: str, language: str = "en", max_results: int = 20, request_timeout: int = 45,
) -> list[OmniSearchResult]:
    """Search SearXNG and normalize its JSON results.

    Some SearXNG engines return no results when a generic language code such as ``en`` or
    safe-search parameters are forced.  The first request therefore mirrors the simplest
    working browser/API URL (q + format only).  A localized retry is used only when needed.
    """
    base = clean_text(base_url).rstrip("/")
    if not base:
        return []

    endpoint = f"{base}/search"
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    attempts = [
        {"q": clean_text(query), "format": "json"},
    ]
    language_value = clean_text(language)
    if language_value:
        if language_value.lower() == "en":
            language_value = "en-US"
        attempts.append({"q": clean_text(query), "format": "json", "language": language_value, "safesearch": 0})

    last_response = None
    for params in attempts:
        try:
            response = requests.get(endpoint, params=params, headers=headers, timeout=(10, max(10, int(request_timeout))))
        except requests.Timeout as exc:
            raise RuntimeError("SearXNG timed out. The Render free service may still be waking up.") from exc
        except requests.RequestException as exc:
            raise RuntimeError("SearXNG could not be reached.") from exc
        last_response = response
        if response.status_code == 403:
            raise RuntimeError("SearXNG JSON output is disabled on this instance. Enable format: json in settings.yml.")
        if not response.ok:
            raise RuntimeError(f"SearXNG returned HTTP {response.status_code}.")
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError("SearXNG returned invalid JSON.") from exc
        items = (data.get("results") or []) if isinstance(data, dict) else []
        normalized = _organic_to_omni(query=query, items=items[:max_results], raw_source="SearXNG")
        if normalized:
            return normalized

    return []



def searxng_health_check(*, base_url: str, language: str = "en") -> tuple[bool, str]:
    """Verify that a SearXNG instance is reachable and permits JSON output."""
    base = clean_text(base_url).rstrip("/")
    if not base:
        return False, "SearXNG URL is empty."
    try:
        response = requests.get(
            f"{base}/search",
            params={"q": "test", "format": "json", "language": language or "en", "safesearch": 1},
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            timeout=(8, 20),
        )
    except requests.Timeout:
        return False, "The SearXNG instance timed out."
    except requests.RequestException:
        return False, "The SearXNG instance could not be reached."
    if response.status_code == 403:
        return False, "JSON output is disabled. Add json to search.formats in SearXNG settings.yml."
    if not response.ok:
        return False, f"SearXNG returned HTTP {response.status_code}."
    try:
        data = response.json()
    except ValueError:
        return False, "The instance did not return JSON. Confirm format=json is enabled."
    if not isinstance(data, dict) or "results" not in data:
        return False, "The response is JSON but does not look like a SearXNG search response."
    return True, "SearXNG is reachable and JSON search is enabled."


def targeted_searxng_search(
    *, query: str, base_url: str, language: str = "en", max_results: int = 30,
) -> tuple[list[OmniSearchResult], list[str]]:
    """Search SearXNG with procurement-specific query variants and merge the evidence.

    The variants cover the exact product, official/manufacturer sources, technical PDFs,
    distributors, pricing/lead-time pages, and legacy/discontinued references.
    """
    q = clean_text(query)
    variants = [
        q,
        f'"{q}" manufacturer official product',
        f'"{q}" (spec sheet OR submittal OR installation manual OR technical data) filetype:pdf',
        f'"{q}" (distributor OR supplier OR price OR quote OR lead time)',
        f'"{q}" (discontinued OR obsolete OR superseded OR replacement OR legacy)',
    ]
    merged: list[OmniSearchResult] = []
    notes: list[str] = []
    per_query = max(4, min(10, max_results // max(1, len(variants))))
    for variant in variants:
        try:
            merged.extend(searxng_everywhere_search(
                query=variant, base_url=base_url, language=language, max_results=per_query
            ))
        except Exception as exc:
            notes.append(f"searxng: query failed ({variant}): {exc}")
    # Re-attach the user's original query so grouped ranking/export remains clean.
    for item in merged:
        item.query = q
    return rank_omni_results(merged)[:max_results], notes



# --- Dynamic manufacturer discovery v16 ------------------------------------
_GENERIC_SEARCH_DOMAINS = {
    *_MARKETPLACE_DOMAINS, *_DISTRIBUTOR_DOMAINS,
    "google.com", "bing.com", "yahoo.com", "duckduckgo.com", "youtube.com",
    "facebook.com", "instagram.com", "linkedin.com", "pinterest.com", "reddit.com",
    "manualslib.com", "scribd.com", "issuu.com", "pdfcoffee.com", "catalogs.com",
}


def _root_domain(domain: str) -> str:
    parts = clean_text(domain).lower().removeprefix("www.").split(".")
    if len(parts) <= 2:
        return ".".join(parts)
    # Good-enough public-suffix handling for common US/UK/AU domains without an extra dependency.
    if parts[-2] in {"co", "com", "org", "net"} and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _brand_hint(query: str) -> str:
    words = clean_text(query).split()
    before_model: list[str] = []
    for word in words:
        if any(ch.isdigit() for ch in word):
            break
        if word.lower() not in {"the", "a", "an", "model", "no.", "number"}:
            before_model.append(word)
    return " ".join(before_model[:4]).strip()


def discover_manufacturer_domains(*, query: str, results: list[OmniSearchResult], max_domains: int = 3) -> list[tuple[str, float, str]]:
    """Infer likely official manufacturer domains from broad results.

    This intentionally supports manufacturers never seen before. It uses repeated exact-model
    evidence, brand/domain similarity, technical-document presence, and non-marketplace status.
    The output is a ranked list of (domain, confidence, evidence).
    """
    model_tokens = _query_model_tokens(query)
    brand = _brand_hint(query).lower().replace(" ", "")
    grouped: dict[str, dict[str, Any]] = {}
    for item in results:
        domain = _root_domain(item.source_domain or urlparse(item.link).netloc)
        if not domain or domain in _GENERIC_SEARCH_DOMAINS or any(domain.endswith("." + d) for d in _GENERIC_SEARCH_DOMAINS):
            continue
        row = grouped.setdefault(domain, {"score": 0.0, "count": 0, "exact": 0, "docs": 0, "reasons": []})
        row["count"] += 1
        hay = f"{item.title} {item.snippet} {item.link}".lower()
        exact = bool(model_tokens and all(tok in hay for tok in model_tokens))
        if exact:
            row["score"] += 40
            row["exact"] += 1
            row["reasons"].append("exact model appears")
        if item.document_pdf or any(term in hay for term in _DOC_TERMS):
            row["score"] += 14
            row["docs"] += 1
            row["reasons"].append("technical document found")
        compact_domain = domain.replace("-", "").replace(".", "")
        if brand and (brand in compact_domain or compact_domain.split("com")[0] in brand):
            row["score"] += 28
            row["reasons"].append("brand resembles domain")
        if any(token in hay for token in ("official", "manufacturer", "product catalog", "technical data")):
            row["score"] += 8
        if item.source_type in {"Official manufacturer", "Official manufacturer document"}:
            row["score"] += 20
        row["score"] += min(12, row["count"] * 3)
    ranked: list[tuple[str, float, str]] = []
    for domain, row in grouped.items():
        # Require meaningful evidence; one unrelated organic result is not enough.
        if row["score"] < 30 or (not row["exact"] and not brand):
            continue
        confidence = min(99.0, round(row["score"], 1))
        evidence = "; ".join(unique_keep_order(row["reasons"], max_items=4))
        ranked.append((domain, confidence, evidence or "repeated relevant results"))
    ranked.sort(key=lambda x: (-x[1], x[0]))
    return ranked[:max_domains]


def build_procurement_query_variants(query: str, *, research_depth: str = "standard", query_budget: int = 10) -> list[str]:
    """Build focused searches for procurement research instead of one generic query."""
    q = clean_text(query)
    quoted = f'"{q}"'
    base = [
        q,
        quoted,
        f'{quoted} manufacturer official product',
        f'{quoted} (spec sheet OR submittal OR technical data) filetype:pdf',
        f'{quoted} (installation manual OR instructions OR O&M) filetype:pdf',
        f'{quoted} (supplier OR distributor OR price OR buy)',
        f'{quoted} (quote OR RFQ OR lead time OR availability OR in stock)',
        f'{quoted} (discontinued OR obsolete OR superseded OR replacement OR legacy)',
    ]
    if research_depth == "deep":
        base.extend([
            f'{quoted} (warranty OR parts diagram OR replacement parts) filetype:pdf',
            f'{quoted} (CAD OR BIM OR Revit OR DWG)',
            f'{quoted} authorized distributor',
            f'{quoted} catalog filetype:pdf',
            f'{quoted} dimensions material finish connections',
            f'{quoted} site:archive.org OR site:webcache.googleusercontent.com',
        ])
    return unique_keep_order(base)[:max(2, int(query_budget))]


def adaptive_searxng_search(
    *, query: str, base_url: str, language: str = "en", max_results: int = 30,
    max_domains: int = 3, research_depth: str = "standard", max_workers: int = 3,
    query_budget: int = 10, request_timeout: int = 45,
) -> tuple[list[OmniSearchResult], list[str], list[tuple[str, float, str]]]:
    """Run parallel procurement research, discover manufacturers, then deep-search official domains."""
    q = clean_text(query)
    notes: list[str] = []
    variants = build_procurement_query_variants(q, research_depth=research_depth, query_budget=query_budget)
    broad: list[OmniSearchResult] = []
    per_query = max(3, min(8, max_results // max(1, min(len(variants), 8))))

    # Search variants concurrently so a deep research run does not become excessively slow.
    workers = min(max(1, int(max_workers)), max(1, len(variants)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                searxng_everywhere_search,
                query=variant,
                base_url=base_url,
                language=language,
                max_results=per_query,
                request_timeout=request_timeout,
            ): variant
            for variant in variants
        }
        for future in as_completed(futures):
            variant = futures[future]
            try:
                broad.extend(future.result())
            except Exception as exc:
                notes.append(f"searxng: research query failed ({variant}): {exc}")

    for item in broad:
        item.query = q
    discovered = discover_manufacturer_domains(query=q, results=broad, max_domains=max_domains)

    deep_variants: list[tuple[str, str, float, str]] = []
    for domain, confidence, evidence in discovered:
        domain_queries = [
            f'site:{domain} {q}',
            f'site:{domain} "{q}"',
            f'site:{domain} "{q}" (spec OR submittal OR manual OR technical OR catalog)',
            f'site:{domain} "{q}" filetype:pdf',
        ]
        if research_depth == "deep":
            domain_queries.extend([
                f'site:{domain} "{q}" (warranty OR parts OR CAD OR BIM OR Revit)',
                f'site:{domain} "{q}" (replacement OR discontinued OR superseded)',
            ])
        for variant in unique_keep_order(domain_queries):
            deep_variants.append((variant, domain, confidence, evidence))

    deep: list[OmniSearchResult] = []
    if deep_variants:
        with ThreadPoolExecutor(max_workers=min(max(1, int(max_workers)), len(deep_variants))) as executor:
            futures = {
                executor.submit(
                    searxng_everywhere_search,
                    query=variant,
                    base_url=base_url,
                    language=language,
                    max_results=6,
                    request_timeout=request_timeout,
                ): (variant, domain, confidence, evidence)
                for variant, domain, confidence, evidence in deep_variants
            }
            for future in as_completed(futures):
                variant, domain, confidence, evidence = futures[future]
                try:
                    found = future.result()
                    for item in found:
                        item.query = q
                        item.official_source = True
                        item.source_type = "Discovered manufacturer document" if item.document_pdf else "Discovered manufacturer source"
                        item.source_reliability = max(item.source_reliability, min(97.0, 74.0 + confidence * 0.22))
                        item.overall_score = round(item.match_score * 0.62 + item.source_reliability * 0.38, 1)
                        item.evidence = "; ".join(x for x in [item.evidence, f"Dynamic domain discovery: {evidence}"] if x)
                        item.verification_status = "Official-domain candidate — verify" if not item.exact_model_mentioned else "Exact model on discovered manufacturer domain"
                    deep.extend(found)
                except Exception as exc:
                    notes.append(f"searxng: manufacturer deep search failed ({domain}): {exc}")

    merged = rank_omni_results(broad + deep)[:max_results]
    notes.append(
        f"Research engine ran {len(variants)} broad queries and {len(deep_variants)} manufacturer-domain queries."
    )
    return merged, notes, discovered

def modular_everywhere_search(
    *, query: str, searxng_url: str = "", brave_api_key: str = "", serpapi_api_key: str = "",
    provider_order: str = "searxng,serpapi", country_code: str = "us", language: str = "en",
    max_results: int = 20, research_depth: str = "standard", max_workers: int = 3,
    query_budget: int = 10, request_timeout: int = 45,
) -> tuple[list[OmniSearchResult], list[str]]:
    """Run enabled providers in priority order, merge, deduplicate, and report provider errors.

    SearXNG is the recommended primary provider because it can be self-hosted without per-query fees.
    SerpApi remains optional for Google Shopping, Maps, and Lens compatibility. Brave support is retained
    only for backward compatibility and is not required.
    """
    providers = [p.strip().lower() for p in clean_text(provider_order).split(",") if p.strip()]
    results: list[OmniSearchResult] = []
    notes: list[str] = []
    for provider in unique_keep_order(providers):
        try:
            if provider == "searxng" and searxng_url:
                provider_results, provider_notes, discovered = adaptive_searxng_search(
                    query=query, base_url=searxng_url, language=language, max_results=max_results, research_depth=research_depth,
                    max_workers=max_workers, query_budget=query_budget, request_timeout=request_timeout
                )
                results.extend(provider_results)
                notes.extend(provider_notes)
                if discovered:
                    summary = ", ".join(f"{domain} ({confidence:.0f}%)" for domain, confidence, _ in discovered)
                    notes.append(f"Dynamic manufacturer candidates: {summary}")
            elif provider == "brave" and brave_api_key:
                results.extend(brave_everywhere_search(query=query, api_key=brave_api_key, country_code=country_code, language=language, max_results=max_results))
            elif provider == "serpapi" and serpapi_api_key:
                results.extend(google_everywhere_search(query=query, api_key=serpapi_api_key, country_code=country_code, language=language, max_results=max_results))
        except Exception as exc:  # isolate provider outages and continue with fallbacks
            notes.append(f"{provider}: {exc}")
    return rank_omni_results(results), notes
