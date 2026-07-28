from product_finder.models import OmniSearchResult
from product_finder.search import _classify_web_result, rank_omni_results


def test_official_exact_pdf_classification():
    result = _classify_web_result(
        query="JOSAM 30000-5A-Z",
        title="JOSAM 30000-5A-Z Spec Sheet",
        snippet="Official technical submittal",
        link="https://www.josam.com/files/30000-5A-Z.pdf",
    )
    source_type, kind, official, distributor, exact, legacy, reliability, evidence = result
    assert source_type == "Official manufacturer document"
    assert kind == "PDF / technical document"
    assert official is True
    assert exact is True
    assert reliability >= 90
    assert "Exact model" in evidence


def test_omni_dedupes_by_canonical_url():
    a = OmniSearchResult(query="x", rank=0, title="A", link="https://www.example.com/item?x=1", overall_score=70)
    b = OmniSearchResult(query="x", rank=0, title="B", link="https://example.com/item?y=2", overall_score=90)
    ranked = rank_omni_results([a, b])
    assert len(ranked) == 1
    assert ranked[0].title == "B"
    assert ranked[0].rank == 1
