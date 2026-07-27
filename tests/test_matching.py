from product_finder.matching import rank_product_matches
from product_finder.models import ProductResult


def test_exact_model_is_ranked_best():
    query = 'JOSAM 30000-5A-Z FLOOR DRAIN, WEJLOC, NO HUB CI BODY WITH 5" ROUND ADJUSTABLE NICKALOY TOP, TRAP PRIMER TAP AND CLAMPING FLANGE.'
    results = [
        ProductResult(query=query, input_source='text', rank=1, title='Josam 30003-Z-5A 5 inch floor drain with Nickaloy strainer', seller='Store A', extracted_price=265.98),
        ProductResult(query=query, input_source='text', rank=2, title='JOSAM 30000-5A-Z floor drain Wejloc no-hub cast iron body 5 inch adjustable Nickaloy top with trap primer and clamping flange', seller='Store B', extracted_price=364.87),
    ]
    ranked = rank_product_matches(results)
    assert ranked[0].best_match is True
    assert ranked[0].exact_model_match is True
    assert ranked[0].match_score > ranked[1].match_score
    assert ranked[0].seller == 'Store B'


def test_one_best_match_per_query():
    results = [
        ProductResult(query='ABC X-100 stainless steel', input_source='text', rank=1, title='ABC X-100 stainless steel'),
        ProductResult(query='ABC X-100 stainless steel', input_source='text', rank=2, title='ABC X-101 steel'),
        ProductResult(query='XYZ Z-20 brass valve', input_source='text', rank=1, title='XYZ Z-20 brass valve'),
    ]
    ranked = rank_product_matches(results)
    assert sum(item.best_match for item in ranked) == 2


def test_electronics_exact_semantic_match_scores_high():
    query = 'iPhone 15 Pro 256GB Titanium Unlocked'
    result = ProductResult(
        query=query,
        input_source='text',
        rank=1,
        title='Apple iPhone 15 Pro - Titanium - 256GB - Unlocked',
        seller='eBay',
        condition='New',
    )
    ranked = rank_product_matches([result])
    assert ranked[0].match_score >= 94
    assert ranked[0].match_profile == 'Electronics'
    assert ranked[0].exact_model_match is True


def test_wrong_storage_and_refurbished_are_penalized():
    query = 'Apple iPhone 15 Pro 256GB Titanium Unlocked'
    exact = ProductResult(query=query, input_source='text', rank=1, title='Apple iPhone 15 Pro 256GB Titanium Unlocked', condition='New')
    wrong = ProductResult(query=query, input_source='text', rank=2, title='Restored Apple iPhone 15 Pro 128GB Titanium Unlocked', condition='Refurbished')
    ranked = rank_product_matches([wrong, exact])
    assert ranked[0].title.startswith('Apple iPhone')
    assert ranked[0].match_score > ranked[1].match_score
    assert 'condition differs' in ranked[1].differences
    assert 'storage differs' in ranked[1].differences
