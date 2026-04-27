# Free Backend — User Guide

短指南:如何启用 / 禁用 free backend(SEC EDGAR + yfinance + OpenInsider 替代 financialdatasets),以及部署期需要注意的事。

## 启用

在 repo 根目录的 `.env` 文件加一行(`.env` 已经在 `.gitignore`,不会进 git):

```
USE_FREE_BACKEND=1
```

**必填**:同时需要把你的姓名 + 邮箱告诉 SEC EDGAR(SEC 强制要求 UA;没设直接抛 `SecEdgarUserAgentMissing`,不会 fallback):

```
SEC_EDGAR_USER_AGENT=Your Name your-email@example.com
```

启用后所有 persona 脚本的数据访问会自动路由到 `src/data_sources/aggregator`,代码不需要任何改动。

## 禁用回到 paid

把上面那行删掉,或者改成:

```
USE_FREE_BACKEND=0
```

paid 实现(financialdatasets API)在 `src/tools/api.py` 里完全没动,Phase 1/2 的工作只在文件末尾加了 15 行 env 路由。禁用 free 后行为与升级前完全一致。

## 必需的 env vars

| 变量 | 何时必需 | 格式 |
|---|---|---|
| `USE_FREE_BACKEND` | 启用 free 时 | `1` 启用、`0` 或不设走 paid |
| `SEC_EDGAR_USER_AGENT` | `USE_FREE_BACKEND=1` 时 | `"Your Name your-email@example.com"`,SEC 必填 |
| `FINANCIAL_DATASETS_API_KEY` | 走 paid backend 时 | financialdatasets 账户 key |

## 防火墙 / 网络要求

`/workspace/.devcontainer/init-firewall.sh` 已加白名单(devcontainer 重建后自动生效)。如果在别的环境部署,确保以下域名可达:

- `www.sec.gov`、`data.sec.gov` — SEC EDGAR XBRL 公司数据
- `query1.finance.yahoo.com`、`query2.finance.yahoo.com`、`finance.yahoo.com` — yfinance OHLCV / 公司元信息 / 新闻
- `openinsider.com` — Form 4 insider trades scrape

撞到 `[Errno 101] Network is unreachable` 时,先查白名单。`sec_edgar._http_get` 的 `SecEdgarNetworkError` 异常 message 会显式提示 "If new SEC domain, may need firewall whitelist update"。

## 已知限制

### `INTENTIONALLY_UNFILLED_FIELDS` (22 个 FinancialMetrics 字段)

以下字段在 free backend 下永远返 `None`(Phase 0 audit 发现 persona 脚本不读它们,实现成本高、收益小,所以跳过):

```
enterprise_value, enterprise_value_to_ebitda_ratio, enterprise_value_to_revenue_ratio,
peg_ratio, return_on_assets, inventory_turnover, receivables_turnover,
days_sales_outstanding, operating_cycle, working_capital_turnover,
quick_ratio, cash_ratio, operating_cash_flow_ratio,
debt_to_assets, interest_coverage, earnings_per_share_growth,
free_cash_flow_growth, operating_income_growth, ebitda_growth,
payout_ratio, book_value_growth, free_cash_flow_yield
```

完整审计报告见 `docs/data_inventory.md` § 3.1。如果未来某个 persona 开始访问其中一个,在 `src/data_sources/aggregator.py` 的 `INTENTIONALLY_UNFILLED_FIELDS` frozenset 里把它删掉、`_build_financial_metrics` 加上计算逻辑即可。模块 import 时有 `RuntimeError` 安全网检查 schema 同步。

### `stanley-druckenmiller` 在 free backend 下信号可能更激进

free 直接抓 SEC EDGAR 的最新 XBRL 数据(包括上一财年财报刚出来的 fresh 数字),paid backend 因为 cache + 第三方刷新节奏可能晚几周。结果:Drucker 类 momentum 敏感的 persona 在新财报后立刻看到 ROE / margin 跳升,触发 bullish 比 paid 早。Phase 3 验证矩阵的 `stanley-druckenmiller / NVDA` PARTIAL case 就是这个机制。

如果你的策略要求两个 backend 信号一致再行动,把 Drucker 类 persona 的 confidence 阈值提高 10 pts 是简单缓冲。

### 小盘股 / 新上市公司数据稀疏 → 降级 neutral

SEC EDGAR 对上市不到 2 年的公司只有有限的历史报表;OpenInsider 对低交易量股票可能完全没收录。free backend 在这两种情况都会优雅降级到 `signal="neutral", confidence=0` 而不是崩溃。Phase 3 验证矩阵的 ZETA(2021 上市)上就有这种降级。

如果分析必须要某个新股,在 `aggregator.search_line_items` 直接看返回的字段是 `None` 的比例;比例 > 50% 时这个 ticker 不适合在 free backend 下做基本面分析。

### NVDA / 类似公司的 `total_debt` 可能仍有量级差异

NVDA 同时报告 umbrella `LongTermDebt` 和 sub-components(`LongTermDebtCurrent` + `LongTermDebtNoncurrent`),aggregator 的 `UMBRELLA_DECOMPOSITIONS` 已经处理掉这条 double-count(参见 `_aggregate_debt_components`)。但其他 umbrella 关系如果未来发现,需要加进 `UMBRELLA_DECOMPOSITIONS`。日志里出现 `"umbrella ... present, dropping sub-components"` info 行就是 dedup 在工作。

## 重新跑验证矩阵

任何时候改了 adapter 逻辑都建议跑一遍验证脚本:

```
SEC_EDGAR_USER_AGENT="Your Name your-email@example.com" \
    uv run python scripts/verify_free_backend.py
```

输出:
- stdout 实时进度(35 cell × 2 backend = 70 个 subprocess)
- `docs/verification_report.md` 完整报告(矩阵 + per-cell detail + 阈值判定)
- exit code 0 = 率视角阈值满足(≥ 80% PASS,≤ 3 FAIL)

冷启动约 10-20 分钟(需要 cold-fetch SEC + yfinance + openinsider);热缓存(`/workspace/.cache/cache.db` 已建立)约 3-5 分钟。

## 进一步阅读

- `PROJECT_SPEC.md` § "Closure Decision":Path B 选定的完整理由
- `docs/data_inventory.md`:Phase 0 字段审计,18 access vs 22 unfilled 详细列表
- `docs/verification_report.md`:Phase 3 验证矩阵原始报告 + PARTIAL case caveat
- `src/data_sources/`:6 个 adapter 模块,每个文件顶部 docstring 解释设计意图

## 发现 bug?

free backend 自身的 bug → 看 `tests/unit/test_aggregator.py`,加一个 reproducible 的失败用例,调试,修。

paid backend 不可用导致的 SKIP → 不是 free 端的事,确认 `FINANCIAL_DATASETS_API_KEY` 设了 + financialdatasets 对该 ticker 在你的 plan 内。
