from product_finder.models import OmniSearchResult
from product_finder.orchestrator import build_research_plan
from product_finder.search import filter_omni_relevance


def result(*, title, link, source_domain, exact=False, official=False, raw_source="Bing RSS fallback"):
    return OmniSearchResult(
        query="Just Manufacturing USXN1824A-J stainless steel sink",
        rank=0,
        title=title,
        source_name=source_domain,
        source_domain=source_domain,
        source_type="General web",
        result_kind="Web result",
        link=link,
        snippet="",
        official_source=official,
        exact_model_mentioned=exact,
        source_reliability=70,
        match_score=60,
        overall_score=64,
        verification_status="Needs review",
        evidence="",
        raw_source=raw_source,
    )


def test_exact_model_is_first_research_query():
    plan = build_research_plan("Just Manufacturing USXN1824A-J stainless steel sink")
    assert plan.exact_query == '"USXN1824A-J"'


def test_dictionary_result_is_removed_even_from_bing_rss():
    rows = [
        result(
            title="Just Definition & Meaning",
            link="https://www.merriam-webster.com/dictionary/just",
            source_domain="merriam-webster.com",
        ),
        result(
            title="Just Manufacturing USXN1824A-J sink",
            link="https://www.example.com/USXN1824A-J",
            source_domain="example.com",
        ),
    ]
    filtered = filter_omni_relevance("Just Manufacturing USXN1824A-J stainless steel sink", rows)
    assert len(filtered) == 1
    assert "USXN1824A-J" in filtered[0].title
    assert filtered[0].exact_model_mentioned is True


def test_model_mismatch_general_web_is_removed():
    rows = [
        result(title="JUST brand information", link="https://example.com/just", source_domain="example.com"),
        result(title="USXN1824A-J product page", link="https://seller.example/USXN1824A-J", source_domain="seller.example"),
    ]
    filtered = filter_omni_relevance("Just Manufacturing USXN1824A-J stainless steel sink", rows)
    assert [r.source_domain for r in filtered] == ["seller.example"]


def test_official_candidate_lead_can_survive_without_model_in_url():
    row = result(
        title="Search justmfg.com for USXN1824A-J",
        link="https://justmfg.com/?s=USXN1824A-J",
        source_domain="justmfg.com",
        official=True,
        raw_source="Direct manufacturer research",
    )
    row.source_type = "Official manufacturer candidate"
    filtered = filter_omni_relevance("Just Manufacturing USXN1824A-J stainless steel sink", [row])
    assert len(filtered) == 1
