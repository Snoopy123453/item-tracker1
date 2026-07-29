from product_finder.quote_center import QuoteLine, quote_dataframe, vendor_summary, award_recommendation, create_bid_tab_workbook

def test_quote_summary_and_recommendation():
    lines = [
        QuoteLine(vendor='Vendor A', model='X', quantity=2, unit_price=10, freight=5, lead_time_days=3),
        QuoteLine(vendor='Vendor B', model='X', quantity=2, unit_price=9, freight=10, lead_time_days=7),
    ]
    summary = vendor_summary(quote_dataframe(lines))
    assert len(summary) == 2
    assert award_recommendation(summary)['vendor'] in {'Vendor A', 'Vendor B'}

def test_bid_tab_is_xlsx():
    data = create_bid_tab_workbook([QuoteLine(vendor='Vendor A', model='X', quantity=1, unit_price=10)], 'Test')
    assert data[:2] == b'PK'
