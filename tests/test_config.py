from __future__ import annotations

from unittest.mock import patch

from product_finder.config import load_config


def test_placeholder_secrets_are_not_treated_as_real_keys() -> None:
    with patch.dict(
        "os.environ",
        {
            "SERPAPI_API_KEY": "paste_your_serpapi_key_here",
            "OPENAI_API_KEY": "paste-your-openai-key",
            "APP_PASSWORD": "choose_a_strong_private_passphrase",
        },
        clear=True,
    ):
        config = load_config()
    assert config.serpapi_api_key == ""
    assert config.openai_api_key == ""
    assert config.app_password == ""


def test_limits_are_clamped() -> None:
    with patch.dict(
        "os.environ",
        {
            "MAX_UPLOAD_MB": "999",
            "MAX_INPUTS": "0",
            "MAX_SEARCH_JOBS": "1000",
        },
        clear=True,
    ):
        config = load_config()
    assert config.max_upload_mb == 25
    assert config.max_inputs == 1
    assert config.max_search_jobs == 60
