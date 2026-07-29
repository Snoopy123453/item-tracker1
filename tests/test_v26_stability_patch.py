import pandas as pd

from product_finder.procurement_controls import OFFER_BASE_COLUMNS, normalize_offer_dataframe


def test_offer_dataframe_has_streamlit_compatible_dtypes():
    raw = pd.DataFrame([
        {
            "title": "Pump",
            "quantity": "2",
            "unit_price": "$125.50",
            "shipping": None,
            "tax_rate": "0.1025",
            "match_score": "96",
            "approved": "yes",
            "exact_model_match": "TRUE",
            "authorized_distributor": 0,
        }
    ])
    # Currency strings intentionally become zero instead of crashing the editor;
    # import-specific parsers may clean symbols before this final schema guard.
    result = normalize_offer_dataframe(raw)
    assert list(result.columns) == OFFER_BASE_COLUMNS
    assert result["quantity"].dtype.kind == "f"
    assert result["unit_price"].dtype.kind == "f"
    assert result["approved"].dtype.kind == "b"
    assert result["exact_model_match"].iloc[0]
    assert not result["authorized_distributor"].iloc[0]
    assert result["status"].iloc[0] == "Needs review"


def test_empty_offer_dataframe_is_editor_safe():
    result = normalize_offer_dataframe(pd.DataFrame())
    assert list(result.columns) == OFFER_BASE_COLUMNS
    for col in ["quantity", "unit_price", "shipping", "tax_rate", "match_score"]:
        assert result[col].dtype.kind == "f"
    for col in ["approved", "exact_model_match", "authorized_distributor"]:
        assert result[col].dtype.kind == "b"
