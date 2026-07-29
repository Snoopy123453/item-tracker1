from pathlib import Path


def _source() -> str:
    return Path(__file__).resolve().parents[1].joinpath('app.py').read_text(encoding='utf-8')


def test_v23_version_and_application_shell_present():
    source = _source()
    assert 'APP_VERSION = "23.0"' in source
    assert 'class="app-shell"' in source
    assert 'Quick navigation' in source


def test_light_and_dark_text_tokens_are_explicit():
    source = _source()
    assert '"#f3f6fb"' in source
    assert '"#172033"' in source
    assert '--ph-text:' in source
    assert 'color:var(--ph-text)!important' in source


def test_research_summary_and_empty_state_present():
    source = _source()
    assert 'Exact-model evidence' in source
    assert 'Top evidence:' in source
    assert 'No research results yet' in source
