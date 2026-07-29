from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


class ProductKnowledgeBase:
    """Small SQLite cache suitable for a single Streamlit deployment.

    The database stores normalized research packages, source evidence, and user
    verification state. It is deliberately provider-neutral so the search layer
    can evolve without changing saved project data.
    """

    def __init__(self, path: str | Path = ".product_hunter/knowledge.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS research_cache (
                    cache_key TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    location TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_research_query ON research_cache(query);

                CREATE TABLE IF NOT EXISTS verified_products (
                    product_key TEXT PRIMARY KEY,
                    manufacturer TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'Needs review',
                    notes TEXT NOT NULL DEFAULT '',
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS research_runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    location TEXT NOT NULL DEFAULT '',
                    depth TEXT NOT NULL DEFAULT 'Standard',
                    provider_order TEXT NOT NULL DEFAULT '',
                    cache_hit INTEGER NOT NULL DEFAULT 0,
                    result_count INTEGER NOT NULL DEFAULT 0,
                    warning_count INTEGER NOT NULL DEFAULT 0,
                    duration_seconds REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'Completed',
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_research_runs_created ON research_runs(created_at);

                CREATE TABLE IF NOT EXISTS saved_views (
                    view_name TEXT PRIMARY KEY,
                    filters_json TEXT NOT NULL DEFAULT '{}',
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS product_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_key TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    actor TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_product_events_key ON product_events(product_key, created_at);

                CREATE TABLE IF NOT EXISTS product_notes (
                    note_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_key TEXT NOT NULL,
                    note TEXT NOT NULL,
                    author TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_product_notes_key ON product_notes(product_key, created_at);
                """
            )

    @staticmethod
    def cache_key(query: str, location: str = "", depth: str = "Standard") -> str:
        raw = "|".join([query.strip().casefold(), location.strip().casefold(), depth.casefold()])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get_research(self, query: str, location: str = "", depth: str = "Standard") -> dict[str, Any] | None:
        key = self.cache_key(query, location, depth)
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM research_cache WHERE cache_key=? AND expires_at>?",
                (key, now),
            ).fetchone()
        if not row:
            return None
        try:
            value = json.loads(row["payload_json"])
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None


    def get_stale_research(self, query: str, location: str = "", depth: str = "Standard") -> dict[str, Any] | None:
        """Return the newest cached package even when expired, for outage fallback."""
        key = self.cache_key(query, location, depth)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json, created_at, expires_at FROM research_cache WHERE cache_key=?",
                (key,),
            ).fetchone()
        if not row:
            return None
        try:
            value = json.loads(row["payload_json"])
        except json.JSONDecodeError:
            return None
        if not isinstance(value, dict):
            return None
        value["_cache_created_at"] = row["created_at"]
        value["_cache_expired_at"] = row["expires_at"]
        return value

    def save_research(
        self,
        query: str,
        payload: dict[str, Any],
        location: str = "",
        depth: str = "Standard",
        ttl_hours: int = 72,
    ) -> None:
        now = time.time()
        key = self.cache_key(query, location, depth)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO research_cache(cache_key, query, location, payload_json, created_at, expires_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    created_at=excluded.created_at,
                    expires_at=excluded.expires_at
                """,
                (key, query, location, json.dumps(_jsonable(payload)), now, now + ttl_hours * 3600),
            )

    def upsert_verified_product(
        self,
        *,
        manufacturer: str,
        model: str,
        title: str,
        status: str,
        notes: str = "",
        evidence: Iterable[dict[str, Any]] = (),
    ) -> str:
        identity = f"{manufacturer}|{model}|{title}".strip().casefold()
        key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO verified_products(product_key, manufacturer, model, title, status, notes, evidence_json, updated_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(product_key) DO UPDATE SET
                    status=excluded.status,
                    notes=excluded.notes,
                    evidence_json=excluded.evidence_json,
                    updated_at=excluded.updated_at
                """,
                (key, manufacturer, model, title, status, notes, json.dumps(list(evidence)), time.time()),
            )
        return key



    def record_research_run(
        self,
        *,
        query: str,
        location: str = "",
        depth: str = "Standard",
        provider_order: str = "",
        cache_hit: bool = False,
        result_count: int = 0,
        warning_count: int = 0,
        duration_seconds: float = 0.0,
        status: str = "Completed",
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO research_runs(
                    query, location, depth, provider_order, cache_hit, result_count,
                    warning_count, duration_seconds, status, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (query, location, depth, provider_order, int(cache_hit), int(result_count),
                 int(warning_count), float(duration_seconds), status, time.time()),
            )
            return int(cursor.lastrowid or 0)

    def list_research_runs(self, limit: int = 250) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM research_runs ORDER BY created_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def research_run_stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS runs, COALESCE(SUM(result_count),0) AS results,
                       COALESCE(SUM(warning_count),0) AS warnings,
                       COALESCE(AVG(duration_seconds),0) AS avg_duration,
                       COALESCE(SUM(cache_hit),0) AS cache_hits
                FROM research_runs
                """
            ).fetchone()
        return dict(row) if row else {"runs": 0, "results": 0, "warnings": 0, "avg_duration": 0, "cache_hits": 0}

    def save_view(self, view_name: str, filters: dict[str, Any]) -> None:
        name = str(view_name).strip()
        if not name:
            raise ValueError("View name is required")
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO saved_views(view_name, filters_json, updated_at) VALUES(?,?,?)
                ON CONFLICT(view_name) DO UPDATE SET filters_json=excluded.filters_json, updated_at=excluded.updated_at""",
                (name, json.dumps(_jsonable(filters)), time.time()),
            )

    def list_views(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT view_name, filters_json, updated_at FROM saved_views ORDER BY view_name").fetchall()
        output=[]
        for row in rows:
            item=dict(row)
            try:
                item["filters"]=json.loads(item.pop("filters_json", "{}"))
            except json.JSONDecodeError:
                item["filters"]={}
            output.append(item)
        return output

    def delete_view(self, view_name: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM saved_views WHERE view_name=?", (view_name,))

    def list_cached_research(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT cache_key, query, location, created_at, expires_at FROM research_cache ORDER BY created_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_verified_products(self, limit: int = 500) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT product_key, manufacturer, model, title, status, notes, evidence_json, updated_at FROM verified_products ORDER BY updated_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["evidence"] = json.loads(item.pop("evidence_json", "[]"))
            except json.JSONDecodeError:
                item["evidence"] = []
            output.append(item)
        return output

    def get_verified_product(self, product_key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT product_key, manufacturer, model, title, status, notes, evidence_json, updated_at FROM verified_products WHERE product_key=?",
                (product_key,),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        try:
            item["evidence"] = json.loads(item.pop("evidence_json", "[]"))
        except json.JSONDecodeError:
            item["evidence"] = []
        return item

    def update_verified_product_status(self, product_key: str, status: str, notes: str | None = None) -> None:
        with self._connect() as conn:
            if notes is None:
                conn.execute("UPDATE verified_products SET status=?, updated_at=? WHERE product_key=?", (status, time.time(), product_key))
            else:
                conn.execute("UPDATE verified_products SET status=?, notes=?, updated_at=? WHERE product_key=?", (status, notes, time.time(), product_key))

    def add_product_event(self, product_key: str, stage: str, detail: str = "", actor: str = "") -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO product_events(product_key, stage, detail, actor, created_at) VALUES(?,?,?,?,?)",
                (product_key, stage.strip(), detail.strip(), actor.strip(), time.time()),
            )
            return int(cursor.lastrowid or 0)

    def list_product_events(self, product_key: str, limit: int = 250) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT event_id, product_key, stage, detail, actor, created_at FROM product_events WHERE product_key=? ORDER BY created_at DESC LIMIT ?",
                (product_key, max(1, int(limit))),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_product_note(self, product_key: str, note: str, author: str = "") -> int:
        text = note.strip()
        if not text:
            raise ValueError("Note is required")
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO product_notes(product_key, note, author, created_at) VALUES(?,?,?,?)",
                (product_key, text, author.strip(), time.time()),
            )
            return int(cursor.lastrowid or 0)

    def list_product_notes(self, product_key: str, limit: int = 250) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT note_id, product_key, note, author, created_at FROM product_notes WHERE product_key=? ORDER BY created_at DESC LIMIT ?",
                (product_key, max(1, int(limit))),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_verified_product(self, product_key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM product_events WHERE product_key=?", (product_key,))
            conn.execute("DELETE FROM product_notes WHERE product_key=?", (product_key,))
            conn.execute("DELETE FROM verified_products WHERE product_key=?", (product_key,))

    def clear_expired_cache(self) -> int:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM research_cache WHERE expires_at<=?", (time.time(),))
            return int(cursor.rowcount or 0)

    def clear_research_cache(self) -> int:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM research_cache")
            return int(cursor.rowcount or 0)

    def export_snapshot(self) -> dict[str, Any]:
        return {
            "exported_at": time.time(),
            "cached_research": self.list_cached_research(limit=10000),
            "verified_products": self.list_verified_products(limit=10000),
            "research_runs": self.list_research_runs(limit=10000),
            "saved_views": self.list_views(),
            "product_events": [event for product in self.list_verified_products(limit=10000) for event in self.list_product_events(product["product_key"], limit=10000)],
            "product_notes": [note for product in self.list_verified_products(limit=10000) for note in self.list_product_notes(product["product_key"], limit=10000)],
        }

    def stats(self) -> dict[str, int]:
        with self._connect() as conn:
            cached = conn.execute("SELECT COUNT(*) AS n FROM research_cache").fetchone()["n"]
            verified = conn.execute("SELECT COUNT(*) AS n FROM verified_products").fetchone()["n"]
            runs = conn.execute("SELECT COUNT(*) AS n FROM research_runs").fetchone()["n"]
            views = conn.execute("SELECT COUNT(*) AS n FROM saved_views").fetchone()["n"]
        return {"cached_research": int(cached), "verified_products": int(verified), "research_runs": int(runs), "saved_views": int(views)}
