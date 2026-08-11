from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import urlparse
import re
import time
import xml.etree.ElementTree as ET

import requests

from .knowledge_base import ProductKnowledgeBase
from .direct_sources import bing_rss_search, discover_official_pages, infer_manufacturer_domains
from .models import OmniSearchResult
from .search import (
    SearchInfrastructureUnavailable,
    brave_everywhere_search,
    google_everywhere_search,
    rank_omni_results,
    filter_omni_relevance,
    searxng_everywhere_search,
)
from .utils import clean_text, unique_keep_order

USER_AGENT = "ProductHunterResearchOrchestrator/2.0"
_MODEL_RE = re.compile(r"(?=\S*[A-Za-z])(?=\S*\d)[A-Za-z0-9][A-Za-z0-9._/\-]{3,}")
_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)


@dataclass
class ProviderHealth:
    name: str
    status: str = "not_run"
    latency_ms: int = 0
    result_count: int = 0
    message: str = ""

    @property
    def healthy(self) -> bool:
        return self.status in {"healthy", "degraded"} and self.result_count > 0


@dataclass
class ResearchPlan:
    original_query: str
    exact_query: str
    manufacturer_query: str
    document_query: str
    offer_query: str
    lifecycle_query: str
    model_tokens: list[str] = field(default_factory=list)

    def queries(self, depth: str, budget: int) -> list[tuple[str, str]]:
        planned = [
            ("exact", self.exact_query),
            ("manufacturer", self.manufacturer_query),
            ("documents", self.document_query),
            ("offers", self.offer_query),
        ]
        if depth.casefold() == "deep":
            planned.append(("lifecycle", self.lifecycle_query))
        return planned[: max(1, int(budget))]


def build_research_plan(query: str) -> ResearchPlan:
    q = clean_text(query)
    models = unique_keep_order(_MODEL_RE.findall(q))
    exact = f'"{models[0]}"' if models else q
    return ResearchPlan(
        original_query=q,
        exact_query=exact,
        manufacturer_query=f'{exact} official manufacturer product',
        document_query=f'{exact} (spec sheet OR submittal OR installation manual OR technical data OR PDF)',
        offer_query=f'{exact} (distributor OR supplier OR retailer OR price OR quote OR lead time)',
        lifecycle_query=f'{exact} (discontinued OR obsolete OR superseded OR replacement OR legacy)',
        model_tokens=models,
    )


def _canonical_domain(url: str) -> str:
    return urlparse(clean_text(url)).netloc.casefold().removeprefix("www.")


def _evidence_to_result(query: str, evidence: dict[str, Any], *, title_fallback: str, source: str) -> OmniSearchResult | None:
    link = clean_text(evidence.get("link") or evidence.get("url") or evidence.get("product_link"))
    if not link:
        return None
    title = clean_text(evidence.get("title") or title_fallback or link)
    domain = clean_text(evidence.get("source_domain") or evidence.get("source_name") or _canonical_domain(link))
    official = bool(evidence.get("official_source") or evidence.get("official"))
    exact = bool(evidence.get("exact_model_mentioned") or evidence.get("exact_model_match"))
    reliability = float(evidence.get("source_reliability") or (94 if official else 78))
    match = float(evidence.get("match_score") or (98 if exact else 78))
    return OmniSearchResult(
        query=query,
        rank=0,
        title=title,
        source_name=domain,
        source_domain=domain,
        source_type=clean_text(evidence.get("source_type")) or ("Official manufacturer" if official else "Knowledge base evidence"),
        result_kind=clean_text(evidence.get("result_kind")) or "Saved evidence",
        link=link,
        snippet=clean_text(evidence.get("snippet") or evidence.get("evidence")),
        price=clean_text(evidence.get("price")),
        delivery=clean_text(evidence.get("delivery")),
        official_source=official,
        authorized_distributor=bool(evidence.get("authorized_distributor")),
        exact_model_mentioned=exact,
        document_pdf=bool(evidence.get("document_pdf")) or link.lower().split("?")[0].endswith(".pdf"),
        source_reliability=reliability,
        match_score=match,
        overall_score=round(match * 0.64 + reliability * 0.36, 1),
        verification_status=clean_text(evidence.get("verification_status")) or "Previously reviewed evidence",
        evidence=clean_text(evidence.get("evidence")) or "Recovered from Product Intelligence Database",
        raw_source=source,
    )


class ProductResearchOrchestrator:
    """Knowledge-first, provider-neutral product research.

    The orchestrator does not assume SearXNG is always available. It recovers
    reviewed evidence first, refreshes known manufacturer domains through their
    sitemaps when possible, and only then spends requests on live search APIs.
    """

    def __init__(self, knowledge_base: ProductKnowledgeBase) -> None:
        self.knowledge_base = knowledge_base

    def _knowledge_results(self, query: str) -> tuple[list[OmniSearchResult], list[str]]:
        q = clean_text(query).casefold()
        query_tokens = {token for token in re.findall(r"[a-z0-9]+", q) if len(token) > 2}
        model_tokens = {m.casefold() for m in _MODEL_RE.findall(query)}
        output: list[OmniSearchResult] = []
        matched_products = 0
        for product in self.knowledge_base.list_verified_products(limit=1000):
            identity = " ".join(
                clean_text(product.get(key)) for key in ("manufacturer", "model", "title")
            ).casefold()
            identity_compact = re.sub(r"[^a-z0-9]", "", identity)
            model_match = any(re.sub(r"[^a-z0-9]", "", token) in identity_compact for token in model_tokens)
            word_overlap = len(query_tokens & set(re.findall(r"[a-z0-9]+", identity)))
            if not model_match and word_overlap < max(1, min(2, len(query_tokens))):
                continue
            matched_products += 1
            evidence_rows = product.get("evidence") or []
            for row in evidence_rows:
                if isinstance(row, dict):
                    result = _evidence_to_result(
                        query,
                        row,
                        title_fallback=clean_text(product.get("title")),
                        source="Product Intelligence Database",
                    )
                    if result:
                        result.exact_model_mentioned = result.exact_model_mentioned or model_match
                        if model_match:
                            result.match_score = max(result.match_score, 98.0)
                            result.overall_score = round(result.match_score * 0.64 + result.source_reliability * 0.36, 1)
                        output.append(result)
        notes = [f"Knowledge-first lookup matched {matched_products} reviewed product record(s)."]
        return rank_omni_results(output), notes

    def _known_domains(self, results: Iterable[OmniSearchResult]) -> list[str]:
        domains: list[str] = []
        for item in results:
            if item.official_source and item.source_domain:
                domains.append(item.source_domain)
        return unique_keep_order(domains, max_items=5)

    def _sitemap_refresh(self, query: str, domains: list[str], model_tokens: list[str]) -> tuple[list[OmniSearchResult], list[str]]:
        if not domains or not model_tokens:
            return [], []
        results: list[OmniSearchResult] = []
        notes: list[str] = []
        compact_models = [re.sub(r"[^a-z0-9]", "", token.casefold()) for token in model_tokens]
        headers = {"User-Agent": USER_AGENT, "Accept": "application/xml,text/xml,*/*"}
        for domain in domains[:3]:
            urls = [f"https://{domain}/sitemap.xml", f"https://{domain}/sitemap_index.xml"]
            found = 0
            for sitemap_url in urls:
                try:
                    response = requests.get(sitemap_url, headers=headers, timeout=(5, 12))
                    if not response.ok or len(response.content) > 5_000_000:
                        continue
                    root = ET.fromstring(response.content)
                except Exception:
                    continue
                candidates: list[str] = []
                for node in root.iter():
                    if node.tag.casefold().endswith("loc") and node.text:
                        url = clean_text(node.text)
                        compact_url = re.sub(r"[^a-z0-9]", "", url.casefold())
                        if any(model in compact_url for model in compact_models):
                            candidates.append(url)
                for url in unique_keep_order(candidates, max_items=8):
                    results.append(OmniSearchResult(
                        query=query,
                        rank=0,
                        title=f"Official manufacturer page for {model_tokens[0]}",
                        source_name=domain,
                        source_domain=domain,
                        source_type="Official manufacturer",
                        result_kind="Sitemap-discovered page",
                        link=url,
                        official_source=True,
                        exact_model_mentioned=True,
                        source_reliability=94.0,
                        match_score=99.0,
                        overall_score=97.2,
                        verification_status="Exact model on known manufacturer domain",
                        evidence="Exact model discovered in official-domain sitemap",
                        raw_source="Known manufacturer sitemap",
                    ))
                    found += 1
                if found:
                    break
            notes.append(f"Known-domain refresh checked {domain} and found {found} model URL(s).")
        return rank_omni_results(results), notes

    def research(
        self,
        *,
        query: str,
        searxng_url: str,
        brave_api_key: str,
        serpapi_api_key: str,
        provider_order: str,
        country_code: str,
        language: str,
        max_results: int,
        depth: str,
        query_budget: int,
        request_timeout: int,
    ) -> tuple[list[OmniSearchResult], list[str], dict[str, Any]]:
        plan = build_research_plan(query)
        all_results: list[OmniSearchResult] = []
        notes: list[str] = []
        health: list[ProviderHealth] = []

        started = time.monotonic()
        knowledge, knowledge_notes = self._knowledge_results(query)
        all_results.extend(knowledge)
        notes.extend(knowledge_notes)
        health.append(ProviderHealth("knowledge_base", "healthy" if knowledge else "empty", 0, len(knowledge), knowledge_notes[0]))

        known_domains = self._known_domains(knowledge)
        sitemap_results, sitemap_notes = self._sitemap_refresh(query, known_domains, plan.model_tokens)
        all_results.extend(sitemap_results)
        notes.extend(sitemap_notes)
        health.append(ProviderHealth("manufacturer_sitemap", "healthy" if sitemap_results else "empty", 0, len(sitemap_results), "; ".join(sitemap_notes)))

        # Direct manufacturer research is intentionally independent of SearXNG.
        # It uses verified/seed domains and official sitemaps, so a CAPTCHA on a
        # public search engine cannot erase all useful research.
        direct_domains = infer_manufacturer_domains(query, known_domains)
        direct_results, direct_report = discover_official_pages(
            query=query,
            domains=direct_domains,
            timeout=max(10, min(24, request_timeout)),
            max_results=max(6, min(16, max_results)),
        )
        all_results.extend(direct_results)
        notes.append(direct_report.message)
        health.append(ProviderHealth(
            direct_report.provider, direct_report.status, direct_report.latency_ms,
            direct_report.result_count, direct_report.message
        ))

        providers = unique_keep_order([p.strip().casefold() for p in clean_text(provider_order).split(",") if p.strip()])
        live_queries = plan.queries(depth, query_budget)
        # Exact query first. Expanded queries are only attempted if the provider
        # returns useful data, avoiding a burst of requests against degraded engines.
        for provider in providers:
            provider_started = time.monotonic()
            provider_results: list[OmniSearchResult] = []
            message = ""
            status = "empty"
            try:
                for index, (intent, planned_query) in enumerate(live_queries):
                    if provider == "searxng" and searxng_url:
                        found = searxng_everywhere_search(
                            query=planned_query,
                            base_url=searxng_url,
                            language=language,
                            max_results=max(4, min(10, max_results)),
                            request_timeout=request_timeout,
                        )
                    elif provider == "brave" and brave_api_key:
                        found = brave_everywhere_search(
                            query=planned_query,
                            api_key=brave_api_key,
                            country_code=country_code,
                            language=language,
                            max_results=max(4, min(10, max_results)),
                        )
                    elif provider == "serpapi" and serpapi_api_key:
                        found = google_everywhere_search(
                            query=planned_query,
                            api_key=serpapi_api_key,
                            country_code=country_code,
                            language=language,
                            max_results=max(4, min(10, max_results)),
                        )
                    else:
                        break
                    for item in found:
                        item.query = query
                        item.evidence = "; ".join(x for x in [item.evidence, f"Research intent: {intent}"] if x)
                    provider_results.extend(found)
                    # Do not fan out a degraded provider. If exact search is empty,
                    # move to the next provider immediately.
                    if index == 0 and not found:
                        message = "Exact search returned no usable results; expanded queries skipped."
                        break
                status = "healthy" if provider_results else "empty"
            except SearchInfrastructureUnavailable as exc:
                status = "unavailable"
                message = str(exc)
            except Exception as exc:  # provider isolation
                status = "error"
                message = f"{type(exc).__name__}: {exc}"
            latency = int((time.monotonic() - provider_started) * 1000)
            health.append(ProviderHealth(provider, status, latency, len(provider_results), message))
            all_results.extend(provider_results)
            if message:
                notes.append(f"{provider}: {message}")

        # Independent keyless discovery fallback. It runs only when the primary
        # providers and official-domain research have not produced an exact model
        # result, conserving resources and reducing dependence on any one service.
        if not any(item.exact_model_mentioned for item in all_results):
            rss_results, rss_report = bing_rss_search(
                query=plan.exact_query,
                max_results=max(5, min(10, max_results)),
                timeout=max(10, min(22, request_timeout)),
            )
            all_results.extend(rss_results)
            notes.append(rss_report.message)
            health.append(ProviderHealth(
                rss_report.provider, rss_report.status, rss_report.latency_ms,
                rss_report.result_count, rss_report.message
            ))

        all_results = filter_omni_relevance(query, all_results)
        ranked = rank_omni_results(all_results)[:max_results]
        metadata = {
            "provider_health": [health_item.__dict__ for health_item in health],
            "research_plan": {
                "model_tokens": plan.model_tokens,
                "queries": live_queries,
            },
            "duration_seconds": time.monotonic() - started,
            "knowledge_result_count": len(knowledge),
            "live_result_count": max(0, len(ranked) - len(knowledge)),
        }
        if not ranked and any(item.status in {"unavailable", "error"} for item in health):
            unavailable = "; ".join(f"{item.name}: {item.message or item.status}" for item in health if item.status in {"unavailable", "error"})
            raise SearchInfrastructureUnavailable(unavailable or "All live and direct research providers were unavailable.")
        return ranked, notes, metadata
