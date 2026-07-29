from pathlib import Path


def test_enterprise_css_braces_are_escaped_inside_fstring():
    source = Path(__file__).resolve().parents[1].joinpath("app.py").read_text(encoding="utf-8")
    assert ".enterprise-ribbon{{display:flex" in source
    assert ".award-card{{padding:1rem" in source
    assert ".enterprise-ribbon{display:flex" not in source


def test_project_compiles_after_css_hotfix():
    source = Path(__file__).resolve().parents[1].joinpath("app.py").read_text(encoding="utf-8")
    compile(source, "app.py", "exec")
