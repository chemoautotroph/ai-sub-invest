"""SQLite-backed cache for free-backend data sources.

Schema and TTL values are pinned to PROJECT_SPEC.md Phase 0 决议. Any change
here must update the spec first; ``test_cache.py`` enforces both.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Final


logger = logging.getLogger(__name__)


# Module-level alias so unit tests can patch the clock (see frozen_clock fixture).
def _now() -> float:
    return time.time()


class CacheTTL:
    """TTL constants in seconds. Values frozen to PROJECT_SPEC.md TTL 表."""

    AGGREGATOR_FINANCIAL_METRICS: Final[int] = 7 * 86400  # 7d  季报跨季度才刷新
    AGGREGATOR_PRICES: Final[int] = 1 * 86400             # 1d  日线 OHLCV
    SEC_EDGAR_CIK_MAPPING: Final[int] = 30 * 86400        # 30d CIK 几乎不变
    YFINANCE_BASIC_INFO: Final[int] = 30 * 86400          # 30d sector/industry 长期稳定
    AGGREGATOR_COMPANY_NEWS: Final[int] = 1 * 3600        # 1h  防抖,但保持新鲜
    SEC_EDGAR_COMPANY_FACTS: Final[int] = 1 * 86400       # 1d  SEC 不会一天多发
    AGGREGATOR_INSIDER_TRADES: Final[int] = 4 * 3600      # 4h  Form 4 当天交付


_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS cache (
    source       TEXT      NOT NULL,
    endpoint     TEXT      NOT NULL,
    key          TEXT      NOT NULL,
    fetched_at   TIMESTAMP NOT NULL,
    ttl_seconds  INTEGER   NOT NULL,
    payload      BLOB      NOT NULL,
    PRIMARY KEY (source, endpoint, key)
);
"""


class Cache:
    """Thread-safe SQLite cache.

    Concurrency model: one fresh ``sqlite3.Connection`` per call, WAL mode
    enabled at init. WAL allows concurrent readers + a single writer; the
    30-second busy-timeout makes contending writers wait instead of failing
    with ``database is locked``.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(_SCHEMA_DDL)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        # check_same_thread=False is safe because we never share a connection
        # across threads — we open a fresh one per call.
        return sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)

    def get(self, source: str, endpoint: str, key: str) -> bytes | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT fetched_at, ttl_seconds, payload "
                "FROM cache WHERE source = ? AND endpoint = ? AND key = ?",
                (source, endpoint, key),
            ).fetchone()
        if row is None:
            return None
        fetched_at, ttl_seconds, payload = row
        if _now() - float(fetched_at) >= int(ttl_seconds):
            logger.debug(
                "cache miss (expired): %s.%s key=%s age=%.1fs ttl=%ds",
                source, endpoint, key, _now() - float(fetched_at), ttl_seconds,
            )
            return None
        return bytes(payload)

    def set(
        self,
        source: str,
        endpoint: str,
        key: str,
        payload: bytes,
        ttl_seconds: int,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache "
                "(source, endpoint, key, fetched_at, ttl_seconds, payload) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (source, endpoint, key, _now(), int(ttl_seconds), payload),
            )
            conn.commit()
