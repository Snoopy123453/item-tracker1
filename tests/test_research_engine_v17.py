from product_finder.search import build_procurement_query_variants


def test_standard_research_variants_cover_core_procurement_sources():
    variants = build_procurement_query_variants("JOSAM 30000-5A-Z", research_depth="standard")
    joined = " ".join(variants).lower()
    assert "spec sheet" in joined
    assert "lead time" in joined
    assert "discontinued" in joined
    assert len(variants) >= 8


def test_deep_research_adds_cad_warranty_and_catalog_queries():
    variants = build_procurement_query_variants("JOSAM 30000-5A-Z", research_depth="deep")
    joined = " ".join(variants).lower()
    assert "warranty" in joined
    assert "cad" in joined
    assert "catalog" in joined
    assert len(variants) > 10
