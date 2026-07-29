from product_finder.models import OmniSearchResult
from product_finder.search import discover_manufacturer_domains


def result(domain, title, snippet="", pdf=False, source_type="General web"):
    return OmniSearchResult(query="Acme ZX-900 valve", rank=0, title=title, source_domain=domain,
        link=f"https://{domain}/products/zx-900" + (".pdf" if pdf else ""), snippet=snippet,
        document_pdf=pdf, source_type=source_type)


def test_unknown_manufacturer_is_discovered_without_fixed_list():
    rows = [
        result("acmeflow.com", "Acme ZX-900 Control Valve"),
        result("acmeflow.com", "ZX-900 technical data", "official product technical data", True),
        result("amazon.com", "Acme ZX-900 valve"),
    ]
    found = discover_manufacturer_domains(query="Acme ZX-900 valve", results=rows)
    assert found
    assert found[0][0] == "acmeflow.com"


def test_marketplaces_are_not_manufacturer_candidates():
    rows = [result("amazon.com", "Acme ZX-900 valve"), result("ebay.com", "Acme ZX-900 valve")]
    assert discover_manufacturer_domains(query="Acme ZX-900 valve", results=rows) == []
