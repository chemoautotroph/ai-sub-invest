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


def test_set_resets_ttl_window(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """重新 set 后,TTL 从新写入时刻重新计算.

    护栏:其他 caller 假设 "我刚写完 = 至少能活 ttl 秒"。如果 INSERT OR REPLACE
    保留了原 fetched_at 而只覆盖 payload,刚 set 完立即过期会导致 cache 永远
    miss + 把外部 API 打爆。这个测试用 absolute 时间断言锁住该不变量。
    """
    cache = Cache(tmp_path / "c.db")
    fake_time = [1000.0]
    monkeypatch.setattr("src.data_sources.cache._now", lambda: fake_time[0])

    cache.set("yfinance", "ohlcv", "NVDA", b"old", ttl_seconds=100)
    fake_time[0] = 1090  # 距首次写入 90s,TTL=100,本应仍 hit
    cache.set("yfinance", "ohlcv", "NVDA", b"new", ttl_seconds=100)  # 重写
    fake_time[0] = 1180  # 距首次写入 180s 但距重写仅 90s
    assert cache.get("yfinance", "ohlcv", "NVDA") == b"new"  # 还活着


def test_corrupted_db_raises_clear_error(tmp_path: Path) -> None:
    """损坏的 db 文件应该抛清晰异常,不是 silent return None.

    Spec § "工程标准" 第 5 条:不允许 silent failure。如果 SQLite 在打开损坏
    db 时 fallthrough 成空查询,会变成永久 cache miss + 疯狂打外部 API 撞限速。

    实现细节:当前实现在 ``__init__`` 阶段 (PRAGMA journal_mode=WAL) 触发
    sqlite3.DatabaseError,所以构造和读取都包进 ``pytest.raises`` 范围里——
    无论错误抛在哪一阶段,大声 raise 都满足 "不 silent" 不变量;如果未来
    改成 lazy init,这个测试依然成立 (get() 仍会 raise)。
    """
    db_path = tmp_path / "broken.db"
    db_path.write_bytes(b"this is not sqlite")
    with pytest.raises(sqlite3.DatabaseError):
        cache = Cache(db_path)
        cache.get("yfinance", "ohlcv", "NVDA")


def test_default_db_path_under_workspace_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """没传 db_path 时应该落在 host bind mount 下 (容器重建后仍存在).

    护栏:Phase 4 verification matrix 重跑依赖持久化 cache,不能写到容器
    ephemeral fs (例如 /tmp 或容器内 site-packages 旁边)。
    """
    fake_default = tmp_path / "subdir" / "cache.db"
    monkeypatch.setattr("src.data_sources.cache.DEFAULT_DB_PATH", fake_default)
    cache = Cache()  # 无参数
    assert cache.db_path == fake_default
    assert fake_default.exists()


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
