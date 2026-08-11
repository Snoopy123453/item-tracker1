from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import quote_plus, urlparse
import re
import time
import xml.etree.ElementTree as ET

import requests

from .models import OmniSearchResult
from .utils import clean_text, unique_keep_order

USER_AGENT = "ProductHunterDirectResearch/1.0"
MODEL_RE = re.compile(r"(?=\S*[A-Za-z])(?=\S*\d)[A-Za-z0-9][A-Za-z0-9._/\-]{3,}")

# Seed knowledge is intentionally small. It is a bootstrap layer, not a closed
# manufacturer list. Verified domains discovered by the knowledge base continue
# to take priority and can grow without code changes.
MANUFACTURER_DOMAINS: dict[str, tuple[str, ...]] = {
    "just manufacturing": ("justmfg.com",),
    "just": ("justmfg.com",),
    "josam": ("josam.com",),
    "chicago faucets": ("chicagofaucets.com",),
    "mcguire": ("mcguiremfg.com",),
    "precision plumbing products": ("pppinc.net",),
    "p.p.p.": ("pppinc.net",),
    "watersaver": ("watersaver.com", "watersaverfaucets.com"),
    "crucial": ("crucial.com",),
    "apple": ("apple.com",),
    "nike": ("nike.com",),
    "zurn": ("zurn.com",),
    "sloan": ("sloan.com",),
    "elkay": ("elkay.com",),
    "bradley": ("bradleycorp.com",),
}

DISTRIBUTOR_DOMAINS: tuple[str, ...] = (
    "ferguson.com",
    "grainger.com",
    "zoro.com",
    "supplyhouse.com",
    "build.com",
    "webstaurantstore.com",
    "equiparts.com",
)


@dataclass
class DirectSourceReport:
    provider: str
    status: str
    result_count: int
    latency_ms: int
    message: str = ""


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", clean_text(value).casefold())


def extract_model_tokens(query: str) -> list[str]:
    return unique_keep_order(MODEL_RE.findall(clean_text(query)), max_items=4)


def infer_manufacturer_domains(query: str, known_domains: Iterable[str] = ()) -> list[str]:
    q = clean_text(query).casefold()
    output = [clean_text(d).casefold().removeprefix("www.") for d in known_domains if clean_text(d)]
    # Prefer longer aliases to avoid treating an ordinary word as a brand unless
    # the query also contains a model-like token.
    has_model = bool(extract_model_tokens(query))
    for alias in sorted(MANUFACTURER_DOMAINS, key=len, reverse=True):
        if alias in q and (len(alias) > 4 or has_model):
            output.extend(MANUFACTURER_DOMAINS[alias])
    return unique_keep_order(output, max_items=8)


def _parse_sitemap(content: bytes) -> tuple[list[str], list[str]]:
    root = ET.fromstring(content)
    page_urls: list[str] = []
    sitemap_urls: list[str] = []
    root_name = root.tag.casefold()
    for node in root.iter():
        if not node.tag.casefold().endswith("loc") or not node.text:
            continue
        url = clean_text(node.text)
        if "sitemapindex" in root_name or url.lower().endswith(".xml") or "sitemap" in url.lower():
            sitemap_urls.append(url)
        else:
            page_urls.append(url)
    return page_urls, sitemap_urls


def _sitemap_candidates(domain: str) -> list[str]:
    return [
        f"https://{domain}/sitemap.xml",
        f"https://{domain}/sitemap_index.xml",
        f"https://www.{domain}/sitemap.xml",
    ]


def discover_official_pages(
    *, query: str, domains: Iterable[str], timeout: int = 14, max_results: int = 12
) -> tuple[list[OmniSearchResult], DirectSourceReport]:
    started = time.monotonic()
    models = extract_model_tokens(query)
    compact_models = [_compact(model) for model in models]
    results: list[OmniSearchResult] = []
    checked = 0
    sitemap_errors = 0
    headers = {"User-Agent": USER_AGENT, "Accept": "application/xml,text/xml,*/*"}

    for domain in unique_keep_order(domains, max_items=6):
        checked += 1
        page_urls: list[str] = []
        child_sitemaps: list[str] = []
        for sitemap_url in _sitemap_candidates(domain):
            try:
                response = requests.get(sitemap_url, headers=headers, timeout=(5, timeout))
                if not response.ok or len(response.content) > 8_000_000:
                    continue
                pages, children = _parse_sitemap(response.content)
                page_urls.extend(pages)
                child_sitemaps.extend(children[:12])
                if pages or children:
                    break
            except Exception:
                sitemap_errors += 1

        # One bounded sitemap-index expansion. This is direct manufacturer
        # research and does not depend on a general web-search engine.
        for child_url in child_sitemaps[:8]:
            try:
                response = requests.get(child_url, headers=headers, timeout=(5, timeout))
                if not response.ok or len(response.content) > 8_000_000:
                    continue
                pages, _ = _parse_sitemap(response.content)
                page_urls.extend(pages)
            except Exception:
                sitemap_errors += 1

        matched_urls: list[str] = []
        for url in page_urls:
            compact_url = _compact(url)
            if compact_models and any(model in compact_url for model in compact_models):
                matched_urls.append(url)

        for url in unique_keep_order(matched_urls, max_items=max_results):
            is_pdf = urlparse(url).path.lower().endswith(".pdf")
            results.append(
                OmniSearchResult(
                    query=query,
                    rank=0,
                    title=f"Official {'document' if is_pdf else 'product page'} for {models[0] if models else query}",
                    source_name=domain,
                    source_domain=domain,
                    source_type="Official manufacturer",
                    result_kind="Technical document" if is_pdf else "Product page",
                    link=url,
                    official_source=True,
                    exact_model_mentioned=bool(models),
                    document_pdf=is_pdf,
                    source_reliability=97.0,
                    match_score=99.0 if models else 88.0,
                    overall_score=98.3 if models else 91.2,
                    verification_status="Exact model on official manufacturer domain" if models else "Official manufacturer source",
                    evidence="Direct official-domain sitemap discovery; no metasearch engine required.",
                    raw_source="Direct manufacturer research",
                )
            )

        # Even when a sitemap does not expose the exact page, return an honest
        # manufacturer search lead rather than claiming an exact match.
        if not matched_urls:
            search_url = f"https://{domain}/?s={quote_plus(models[0] if models else query)}"
            results.append(
                OmniSearchResult(
                    query=query,
                    rank=0,
                    title=f"Search {domain} for {models[0] if models else query}",
                    source_name=domain,
                    source_domain=domain,
                    source_type="Official manufacturer candidate",
                    result_kind="Official-site search lead",
                    link=search_url,
                    official_source=True,
                    exact_model_mentioned=False,
                    source_reliability=91.0,
                    match_score=62.0,
                    overall_score=72.4,
                    verification_status="Official domain identified; exact page not yet verified",
                    evidence="Manufacturer domain inferred from product identity. Open the link to verify the exact model.",
                    raw_source="Direct manufacturer research",
                )
            )

    latency = int((time.monotonic() - started) * 1000)
    exact_count = sum(1 for item in results if item.exact_model_mentioned)
    status = "healthy" if exact_count else ("degraded" if results else "empty")
    message = f"Checked {checked} manufacturer domain(s); found {exact_count} exact official page(s)."
    if sitemap_errors:
        message += f" {sitemap_errors} sitemap request(s) failed but research continued."
    return results[:max_results], DirectSourceReport("direct_manufacturer", status, len(results[:max_results]), latency, message)


def bing_rss_search(*, query: str, max_results: int = 10, timeout: int = 16) -> tuple[list[OmniSearchResult], DirectSourceReport]:
    """Keyless secondary discovery using Bing's public RSS response.

    This is deliberately isolated from SearXNG. It is a fallback, not a promise
    of unlimited access, and failures never stop manufacturer or cached research.
    """
    started = time.monotonic()
    endpoint = "https://www.bing.com/search"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml,application/xml,text/xml"}
    results: list[OmniSearchResult] = []
    message = ""
    status = "empty"
    try:
        response = requests.get(endpoint, params={"q": clean_text(query), "format": "rss"}, headers=headers, timeout=(5, timeout))
        if not response.ok:
            raise RuntimeError(f"HTTP {response.status_code}")
        root = ET.fromstring(response.content)
        models = extract_model_tokens(query)
        compact_models = [_compact(model) for model in models]
        for idx, item in enumerate(root.findall(".//item")[:max_results], start=1):
            title = clean_text(item.findtext("title"))
            link = clean_text(item.findtext("link"))
            snippet = clean_text(item.findtext("description"))
            if not link:
                continue
            domain = urlparse(link).netloc.casefold().removeprefix("www.")
            combined = _compact(f"{title} {link} {snippet}")
            exact = bool(compact_models and any(model in combined for model in compact_models))
            results.append(
                OmniSearchResult(
                    query=query,
                    rank=idx,
                    title=title or link,
                    source_name=domain,
                    source_domain=domain,
                    source_type="General web",
                    result_kind="Web result",
                    link=link,
                    snippet=snippet,
                    exact_model_mentioned=exact,
                    source_reliability=72.0,
                    match_score=93.0 if exact else 64.0,
                    overall_score=85.4 if exact else 66.9,
                    verification_status="Exact model found" if exact else "Discovery lead — verify",
                    evidence="Independent keyless discovery fallback; verify source authority and product specifications.",
                    raw_source="Bing RSS fallback",
                )
            )
        status = "healthy" if results else "empty"
        message = f"Bing RSS returned {len(results)} result(s)."
    except Exception as exc:
        status = "unavailable"
        message = f"{type(exc).__name__}: {exc}"
    latency = int((time.monotonic() - started) * 1000)
    return results, DirectSourceReport("bing_rss", status, len(results), latency, message)
