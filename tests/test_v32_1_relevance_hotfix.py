from product_finder.search import _organic_to_omni, _query_model_tokens, build_procurement_query_variants


def test_model_token_preserves_hyphenated_model_semantics():
    assert _query_model_tokens("Just Manufacturing USXN1824A-J stainless steel sink") == ["usxn1824aj"]


def test_dictionary_results_are_removed_for_product_model_search():
    items = [
        {
            "url": "https://www.merriam-webster.com/dictionary/just",
            "title": "JUST Definition & Meaning - Merriam-Webster",
            "content": "The meaning of JUST is having a basis in or conforming to fact or reason.",
        },
        {
            "url": "https://www.justmfg.com/products/details/USXN1824A-J",
            "title": "USXN1824A-J Stainless Steel Sink | Just Manufacturing",
            "content": "Single bowl 18 gauge stainless steel sink model USXN1824A-J.",
        },
    ]
    results = _organic_to_omni(
        query="Just Manufacturing USXN1824A-J stainless steel sink",
        items=items,
        raw_source="test",
    )
    assert len(results) == 1
    assert results[0].source_domain == "justmfg.com"
    assert results[0].exact_model_mentioned is True
    assert results[0].official_source is True


def test_exact_model_queries_run_before_broad_variants():
    variants = build_procurement_query_variants(
        "Just Manufacturing USXN1824A-J stainless steel sink",
        research_depth="standard",
        query_budget=10,
    )
    assert variants[0] == '"usxn1824aj"'
    assert "usxn1824aj" in variants[1].lower()
