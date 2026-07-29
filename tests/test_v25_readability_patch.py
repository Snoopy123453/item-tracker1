from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app.py"
TEXT = APP.read_text(encoding="utf-8")


def test_v25_version_is_present():
    assert 'APP_VERSION = "25.0"' in TEXT
    assert "Procurement Intelligence Platform · v25" in TEXT


def test_readable_theme_tokens_exist():
    for token in (
        "--ph-text-strong",
        "--ph-muted",
        "--ph-border-strong",
        "--ph-focus",
        "--ph-info-bg",
    ):
        assert token in TEXT


def test_text_size_and_contrast_controls_exist():
    assert 'st.session_state.setdefault("ui_text_size", "Standard")' in TEXT
    assert 'st.selectbox("Text size", ["Standard", "Large"]' in TEXT
    assert "High-contrast text enabled" in TEXT


def test_undefined_legacy_resource_tokens_removed():
    assert "var(--surface-soft)" not in TEXT
    assert "var(--text-strong)" not in TEXT
