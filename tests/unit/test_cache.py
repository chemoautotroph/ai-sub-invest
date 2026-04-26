"""Unit tests for src/data_sources/cache.py.

覆盖 PROJECT_SPEC.md Phase 1.1 要求:
- 必测的 5 个 case (TTL hit / TTL miss / source 隔离 / 并发 / 大 payload)
- TTL 表 7 个 (source, endpoint) 组合的 set→hit→expire 生命周期
- CacheTTL 常量值与 spec 表格完全一致
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from src.data_sources.cache import Cache, CacheTTL


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    return Cache(tmp_path / "cache.sqlite")


@pytest.fixture
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Deterministic clock injected into the cache module.

    Tests mutate `clock[0]` to advance virtual time without sleeping.
    """
    clock = [1_700_000_000.0]
    monkeypatch.setattr("src.data_sources.cache._now", lambda: clock[0])
    return clock


# ---------------------------------------------------------------------------
# spec § "必测的 case" — five items in PROJECT_SPEC.md lines 122-128
# ---------------------------------------------------------------------------


def test_get_within_ttl_returns_payload(cache: Cache, frozen_clock: list[float]) -> None:
    """Spec case 1: TTL 内 hit 返回缓存."""
    cache.set("aggregator", "financial_metrics", "NVDA", b"payload-1", ttl_seconds=60)
    frozen_clock[0] += 30  # well within ttl
    assert cache.get("aggregator", "financial_metrics", "NVDA") == b"payload-1"


def test_get_after_ttl_returns_none(cache: Cache, frozen_clock: list[float]) -> None:
    """Spec case 2: TTL 过期返回 None."""
    cache.set("aggregator", "prices", "NVDA", b"payload-2", ttl_seconds=60)
    frozen_clock[0] += 61  # past ttl
    assert cache.get("aggregator", "prices", "NVDA") is None


def test_same_key_different_source_isolated(
    cache: Cache, frozen_clock: list[float]
) -> None:
    """Spec case 3a: 同一 key 不同 source 互不干扰."""
    cache.set("sec_edgar", "company_facts", "NVDA", b"sec-blob", ttl_seconds=60)
    cache.set("yfinance", "basic_info", "NVDA", b"yf-blob", ttl_seconds=60)
    assert cache.get("sec_edgar", "company_facts", "NVDA") == b"sec-blob"
    assert cache.get("yfinance", "basic_info", "NVDA") == b"yf-blob"


def test_same_key_same_source_different_endpoint_isolated(
    cache: Cache, frozen_clock: list[float]
) -> None:
    """Spec case 3b: 同一 (source, key) 但不同 endpoint 互不干扰.

    Why: aggregator 同时缓存 financial_metrics / prices / company_news 等多个
    endpoint,key 都是 ticker,如果只用 (source, key) 索引会撞车.
    """
    cache.set("aggregator", "financial_metrics", "NVDA", b"fm", ttl_seconds=60)
    cache.set("aggregator", "prices", "NVDA", b"px", ttl_seconds=60)
    assert cache.get("aggregator", "financial_metrics", "NVDA") == b"fm"
    assert cache.get("aggregator", "prices", "NVDA") == b"px"


def test_concurrent_writes_no_data_loss(cache: Cache) -> None:
    """Spec case 4: 并发写入(threading)不丢数据."""
    n_threads = 16
    n_writes = 8
    errors: list[BaseException] = []

    def writer(thread_id: int) -> None:
        try:
            for i in range(n_writes):
                cache.set(
                    "aggregator",
                    "financial_metrics",
                    f"key-{thread_id}-{i}",
                    f"payload-{thread_id}-{i}".encode(),
                    ttl_seconds=600,
                )
        except BaseException as exc:  # pragma: no cover - error path
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    for thread_id in range(n_threads):
        for i in range(n_writes):
            expected = f"payload-{thread_id}-{i}".encode()
            actual = cache.get(
                "aggregator", "financial_metrics", f"key-{thread_id}-{i}"
            )
            assert actual == expected, f"lost write thread={thread_id} i={i}"


def test_payload_larger_than_one_megabyte(
    cache: Cache, frozen_clock: list[float]
) -> None:
    """Spec case 5: payload 大小 > 1MB 不报错.

    Why: SEC companyfacts JSON 单文件经常 5-10MB,SQLite 默认 BLOB 上限够用,
    但要确认我们没在中间套了 TEXT 列或别的限制.
    """
    big = b"x" * (5 * 1024 * 1024)  # 5 MiB
    cache.set("sec_edgar", "company_facts", "NVDA", big, ttl_seconds=86400)
    out = cache.get("sec_edgar", "company_facts", "NVDA")
    assert out is not None
    assert len(out) == len(big)
    assert out == big


# ---------------------------------------------------------------------------
# spec § "Cache TTL 表" — parametrize 7 (source, endpoint) combinations
# ---------------------------------------------------------------------------


# 规格冻结:任何修改必须先改 PROJECT_SPEC.md 的 TTL 表
TTL_CASES: list[tuple[str, str, int, int]] = [
    ("aggregator", "financial_metrics", CacheTTL.AGGREGATOR_FINANCIAL_METRICS, 7 * 86400),
    ("aggregator", "prices", CacheTTL.AGGREGATOR_PRICES, 1 * 86400),
    ("sec_edgar", "cik_mapping", CacheTTL.SEC_EDGAR_CIK_MAPPING, 30 * 86400),
    ("yfinance", "basic_info", CacheTTL.YFINANCE_BASIC_INFO, 30 * 86400),
    ("aggregator", "company_news", CacheTTL.AGGREGATOR_COMPANY_NEWS, 1 * 3600),
    ("sec_edgar", "company_facts", CacheTTL.SEC_EDGAR_COMPANY_FACTS, 1 * 86400),
    ("aggregator", "insider_trades", CacheTTL.AGGREGATOR_INSIDER_TRADES, 4 * 3600),
]


@pytest.mark.parametrize(
    "source,endpoint,ttl_const,expected_seconds",
    TTL_CASES,
    ids=[f"{s}.{e}" for s, e, _, _ in TTL_CASES],
)
def test_ttl_constant_matches_spec_table(
    source: str, endpoint: str, ttl_const: int, expected_seconds: int
) -> None:
    """CacheTTL 常量值必须与 PROJECT_SPEC.md 的 TTL 表逐字一致."""
    assert ttl_const == expected_seconds, (
        f"{source}.{endpoint} TTL drift: spec={expected_seconds}s, code={ttl_const}s"
    )


@pytest.mark.parametrize(
    "source,endpoint,ttl_const,expected_seconds",
    TTL_CASES,
    ids=[f"{s}.{e}" for s, e, _, _ in TTL_CASES],
)
def test_lifecycle_set_hit_expire_per_endpoint(
    cache: Cache,
    frozen_clock: list[float],
    source: str,
    endpoint: str,
    ttl_const: int,
    expected_seconds: int,
) -> None:
    """每个 (source, endpoint):set → 立即 hit → TTL 边界内 hit → 边界外 miss."""
    base = frozen_clock[0]

    cache.set(source, endpoint, "NVDA", b"payload", ttl_seconds=ttl_const)

    # Immediate hit
    assert cache.get(source, endpoint, "NVDA") == b"payload"

    # Just inside TTL boundary
    frozen_clock[0] = base + ttl_const - 1
    assert cache.get(source, endpoint, "NVDA") == b"payload", (
        f"unexpected miss inside TTL for {source}.{endpoint}"
    )

    # Just outside TTL boundary
    frozen_clock[0] = base + ttl_const + 1
    assert cache.get(source, endpoint, "NVDA") is None, (
        f"unexpected hit past TTL for {source}.{endpoint}"
    )


# ---------------------------------------------------------------------------
# additional sanity tests — small, but worth pinning
# ---------------------------------------------------------------------------


def test_get_missing_key_returns_none(cache: Cache) -> None:
    assert cache.get("aggregator", "prices", "DOES_NOT_EXIST") is None


def test_set_overwrites_existing_entry(
    cache: Cache, frozen_clock: list[float]
) -> None:
    """Re-setting (source, endpoint, key) replaces value AND refreshes fetched_at.

    Why: a fresh fetch invalidates old TTL — caller expects the new TTL window
    to start from the new write, not be stuck on the original write time.
    """
    cache.set("aggregator", "prices", "NVDA", b"v1", ttl_seconds=10)
    frozen_clock[0] += 9  # nearly expired under v1
    cache.set("aggregator", "prices", "NVDA", b"v2", ttl_seconds=10)
    frozen_clock[0] += 5  # 14s from v1, but only 5s from v2
    assert cache.get("aggregator", "prices", "NVDA") == b"v2"


def test_schema_matches_spec(cache: Cache) -> None:
    """Schema columns must match PROJECT_SPEC.md SQL DDL exactly.

    Why: locked-in column names give the cache file a stable on-disk format —
    upstream callers that ever inspect the DB directly (debug scripts, ops
    tooling) shouldn't have to chase column renames.
    """
    with sqlite3.connect(cache.db_path) as conn:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(cache)").fetchall()]
    assert cols == [
        "source",
        "endpoint",
        "key",
        "fetched_at",
        "ttl_seconds",
        "payload",
    ]


def test_primary_key_is_source_endpoint_key(cache: Cache) -> None:
    """PK must be (source, endpoint, key) — protects spec case 3 isolation invariant."""
    with sqlite3.connect(cache.db_path) as conn:
        pk_cols = [
            row[1]
            for row in conn.execute("PRAGMA table_info(cache)").fetchall()
            if row[5] > 0  # pk column index, 0 means not in PK
        ]
        pk_cols.sort(key=lambda c: ["source", "endpoint", "key"].index(c))
    assert pk_cols == ["source", "endpoint", "key"]


def test_db_file_is_created(tmp_path: Path) -> None:
    db = tmp_path / "nested" / "cache.sqlite"
    Cache(db)
    assert db.exists(), "Cache must create its DB file (and parent dirs) on init"
