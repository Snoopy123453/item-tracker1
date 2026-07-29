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

    def delete_verified_product(self, product_key: str) -> None:
        with self._connect() as conn:
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
        }

    def stats(self) -> dict[str, int]:
        with self._connect() as conn:
            cached = conn.execute("SELECT COUNT(*) AS n FROM research_cache").fetchone()["n"]
            verified = conn.execute("SELECT COUNT(*) AS n FROM verified_products").fetchone()["n"]
        return {"cached_research": int(cached), "verified_products": int(verified)}
