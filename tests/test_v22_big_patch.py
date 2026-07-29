from pathlib import Path

from product_finder.knowledge_base import ProductKnowledgeBase
from product_finder.research_agent import ResearchAgent


def test_research_runs_and_saved_views(tmp_path: Path):
    kb = ProductKnowledgeBase(tmp_path / 'kb.sqlite3')
    run_id = kb.record_research_run(
        query='JOSAM 30000-5A-Z', location='Long Beach, CA', depth='Deep',
        provider_order='searxng', cache_hit=False, result_count=12,
        warning_count=1, duration_seconds=4.2,
    )
    assert run_id > 0
    rows = kb.list_research_runs()
    assert rows[0]['query'] == 'JOSAM 30000-5A-Z'
    assert kb.research_run_stats()['results'] == 12

    kb.save_view('Official exact', {
        'source_types': ['Official manufacturer'],
        'exact_only': True,
        'official_only': True,
        'min_score': 90,
    })
    views = kb.list_views()
    assert views[0]['view_name'] == 'Official exact'
    assert views[0]['filters']['min_score'] == 90
    kb.delete_view('Official exact')
    assert kb.list_views() == []


def test_snapshot_includes_v22_data(tmp_path: Path):
    kb = ProductKnowledgeBase(tmp_path / 'kb.sqlite3')
    kb.record_research_run(query='test')
    kb.save_view('All', {'min_score': 0})
    snapshot = kb.export_snapshot()
    assert len(snapshot['research_runs']) == 1
    assert len(snapshot['saved_views']) == 1
