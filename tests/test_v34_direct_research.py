from __future__ import annotations

from unittest.mock import Mock, patch

from product_finder.direct_sources import (
    bing_rss_search,
    discover_official_pages,
    extract_model_tokens,
    infer_manufacturer_domains,
)


def test_infers_just_manufacturing_domain_and_model():
    query = "Just Manufacturing USXN1824A-J stainless steel sink"
    assert extract_model_tokens(query) == ["USXN1824A-J"]
    assert "justmfg.com" in infer_manufacturer_domains(query)


def test_direct_sitemap_finds_exact_model():
    sitemap = b'''<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://justmfg.com/products/usxn1824a-j</loc></url>
    </urlset>'''
    response = Mock(ok=True, content=sitemap)
    with patch("product_finder.direct_sources.requests.get", return_value=response):
        results, report = discover_official_pages(
            query="Just Manufacturing USXN1824A-J sink",
            domains=["justmfg.com"],
            max_results=5,
        )
    assert report.status == "healthy"
    assert any(item.exact_model_mentioned for item in results)
    assert results[0].official_source is True


def test_bing_rss_isolated_fallback_parses_results():
    rss = b'''<?xml version="1.0"?><rss><channel><item>
    <title>USXN1824A-J Sink</title><link>https://example.com/usxn1824a-j</link>
    <description>Commercial stainless steel sink</description></item></channel></rss>'''
    response = Mock(ok=True, content=rss)
    with patch("product_finder.direct_sources.requests.get", return_value=response):
        results, report = bing_rss_search(query='"USXN1824A-J" sink')
    assert report.status == "healthy"
    assert len(results) == 1
    assert results[0].exact_model_mentioned is True
