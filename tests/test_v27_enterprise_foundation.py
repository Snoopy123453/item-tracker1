from pathlib import Path

from product_finder import observability


def test_record_and_read_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(observability, "DEFAULT_RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(observability, "ERROR_LOG", tmp_path / "errors.jsonl")
    try:
        raise ValueError("bad input")
    except ValueError as exc:
        incident = observability.record_exception(exc, workspace="test")
    rows = observability.recent_errors()
    assert rows[0]["incident_id"] == incident
    assert rows[0]["workspace"] == "test"
    assert rows[0]["error_type"] == "ValueError"


def test_openai_health_without_key():
    result = observability.check_openai_key("")
    assert result.status == "Not configured"


def test_database_health(tmp_path):
    result = observability.check_database(tmp_path / "kb.sqlite3")
    assert result.status == "Healthy"


def test_diagnostics_snapshot_contains_version(tmp_path, monkeypatch):
    monkeypatch.setattr(observability, "DEFAULT_RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(observability, "ERROR_LOG", tmp_path / "errors.jsonl")
    monkeypatch.setattr(observability, "EVENT_LOG", tmp_path / "events.jsonl")
    snapshot = observability.diagnostics_snapshot(app_version="27.0")
    assert snapshot["app_version"] == "27.0"
    assert "python" in snapshot
