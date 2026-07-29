from app import _route_omni_results
from product_finder.models import OmniSearchResult


def test_routes_omni_results_to_professional_views():
    rows = [
        OmniSearchResult(query='x', rank=1, title='Official spec PDF', source_name='Acme', source_domain='acme.com', source_type='Official manufacturer document', result_kind='PDF / technical document', link='https://acme.com/spec.pdf', official_source=True, exact_model_mentioned=True, document_pdf=True, overall_score=98),
        OmniSearchResult(query='x', rank=2, title='Buy exact model', source_name='Grainger', source_domain='grainger.com', source_type='Distributor', result_kind='Product page', link='https://grainger.com/x', exact_model_mentioned=True, overall_score=88),
        OmniSearchResult(query='x', rank=3, title='Local supplier', source_name='Local Supply', source_type='Local supplier', result_kind='Nearby store', link='https://local.example', location='Long Beach, CA'),
    ]
    products, stores, docs, manufacturers = _route_omni_results(rows)
    assert len(products) == 1
    assert products[0].seller == 'Grainger'
    assert len(stores) == 1
    assert len(docs) == 1
    assert docs[0].official_source is True
    assert len(manufacturers) == 1
