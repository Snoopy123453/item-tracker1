from pathlib import Path


def test_rfq_ribbon_uses_real_streamlit_navigation():
    source = (Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8")
    assert 'st.radio(' in source
    assert 'quote_center_page' in source
    assert '<span class="cmd active">RFQ Home</span>' not in source


def test_all_rfq_destinations_are_wired():
    source = (Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8")
    for page in ["RFQ Home", "Create RFQ", "Import Quotes", "Compare", "Award Review", "Bid Tab", "Export", "Audit"]:
        assert page in source
