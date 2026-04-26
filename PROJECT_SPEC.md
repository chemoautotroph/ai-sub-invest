# 项目:ai-sub-invest 数据层免费化重构

## 任务总览

把 ai-sub-invest 现在依赖的 financialdatasets.ai 付费 API 替换为免费数据源组合(SEC EDGAR + yfinance + OpenInsider),通过 env variable 路由,让原代码 0 改动可切换。

**最高优先级原则:每一行解析代码必须有对应的测试覆盖,无测试不写代码,无测试不算完成**。SEC EDGAR XBRL 数据形态非常脏,无 TDD 必出 silent bug。

## 工作环境

- 工作目录:`/workspace`(已经是 ai-sub-invest 的 git 仓库)
- 包管理:`uv`(已安装,用 `uv add` 加依赖,`uv run pytest` 跑测试)
- Python:3.11(uv 管理)
- 网络:容器在防火墙白名单内,已开通的域名包括 `pypi.org`、`files.pythonhosted.org`、`api.financialdatasets.ai`、`query1.finance.yahoo.com`、`query2.finance.yahoo.com`、`finance.yahoo.com`。**SEC EDGAR (`www.sec.gov`、`data.sec.gov`) 和 OpenInsider (`openinsider.com`) 还没开通**——遇到连接失败就停下来告诉用户加白名单,不要尝试绕过。

## 工程标准(必须遵守)

1. **TDD 严格执行**:每个函数,先写 pytest 测试用例(标记 `@pytest.mark.unit` 或 `@pytest.mark.integration`),让测试 fail,再写实现让测试 pass。提交时给出 `uv run pytest tests/ -v` 的完整通过截图。
2. **单元测试用 mock**(`pytest-mock` 或 `responses` 库),不调真实 API;**集成测试用真实调用**但受限于一个小 fixture(2-3 个 ticker × 1-2 个时间点)。两类测试分开 marker,CI 默认只跑 unit,集成测试要 `pytest -m integration` 显式触发。
3. **Type hints 全覆盖**,`mypy --strict` 通过(允许在 SEC XBRL 解析的地方用 `Any` 但要有注释说明为什么)。
4. **覆盖率目标**:解析层和计算层 ≥ 90% line coverage;adapter 调用层 ≥ 75%。用 `pytest-cov` 检查,提交报告。
5. **不允许 silent failure**。所有 except 块要么记日志(用 `logging`,不用 print)要么 raise。**禁止** `except Exception: pass`。
6. **数据契约**:每个 public 函数返回的数据结构用 Pydantic model 定义。Schema 漂移会被 Pydantic 立刻 catch 住,这是 financialdatasets API 替换的最重要保险。
7. **commit 粒度**:每个 phase 至少一次 commit,每个 adapter 完成至少一次 commit,commit message 格式 `[phase-N] <module>: <action>`。

## Phase 0:Inventory(✅ 2026-04-26 完成,GO 决策)

**目标**:精确知道 ai-sub-invest 实际依赖 financialdatasets 的哪些函数和字段。

**步骤**:
1. 读 `/workspace/src/tools/api.py`,列出所有调用 financialdatasets API 的 public 函数。
2. 读 `/workspace/.claude/skills/*/scripts/{analyze.py,calculate.py,aggregate.py}`,统计每个 persona 用了哪些 API 函数和返回对象的哪些字段。
3. 产出 `/workspace/docs/data_inventory.md`(已完成,覆盖度 ≥ 95%)。

### Phase 0 决议(以下 5 条是 Phase 1 的硬约束)

1. **修 insider trade 链路 bug**(三处都改):
   - `src/data/models.py`:`InsiderTrade` 加 `transaction_type: str | None = None` 和 `value: float | None = None` 两个字段。
   - `.claude/skills/michael-burry/scripts/analyze.py:74`:`get_insider_trades(ticker, end_date, 20)` 改成 `get_insider_trades(ticker, end_date, limit=20)`(原代码把 20 错传到 `start_date`)。
   - `.claude/skills/news-sentiment/scripts/analyze.py:36`:`get_company_news(ticker, end_date, limit)` 改成 `get_company_news(ticker, end_date, limit=limit)`。
   - **Phase 2 A/B 兼容性测试**:在 `tests/integration/test_persona_compatibility.py` 给 `michael-burry` 和 `sentiment` 两个 persona 加 `@pytest.mark.expected_divergence` —— 因为 USE_FREE_BACKEND=1 修了 bug 后 insider 信号会真实生效,与原代码(信号一直为 0)的差异是**预期**而非回归。

2. **CompanyNews.sentiment 永远填 None**:免费源不实现自动 sentiment 标签。`news-sentiment` persona 自己用关键词打分(它本来就这么做)。yfinance 给的 title/publisher/link/timestamp 够用。

3. **`FinancialMetrics` 22 个未访问字段**:在 `src/data_sources/aggregator.py` 顶部用一个常量列出来,Pydantic 接受 None,持续填 None:
   ```python
   INTENTIONALLY_UNFILLED_FIELDS = (
       "enterprise_value", "enterprise_value_to_ebitda_ratio",
       "enterprise_value_to_revenue_ratio", "peg_ratio", "return_on_assets",
       "inventory_turnover", "receivables_turnover", "days_sales_outstanding",
       "operating_cycle", "working_capital_turnover", "quick_ratio",
       "cash_ratio", "operating_cash_flow_ratio", "debt_to_assets",
       "interest_coverage", "earnings_per_share_growth",
       "free_cash_flow_growth", "operating_income_growth", "ebitda_growth",
       "payout_ratio", "book_value_growth", "free_cash_flow_yield",
   )
   ```
   后续要补哪个字段,从这个清单里删掉、补上实现即可。

4. **LineItem 符号约定**:`PaymentsToAcquirePropertyPlantAndEquipment` 在 SEC XBRL 是**正数**,但 financialdatasets 原 API 返回 `capital_expenditure` 是**负数**,persona 代码也按负数取 `abs()`。免费源实现必须保持原约定:`capital_expenditure < 0` / `dividends_and_other_cash_distributions < 0`。`tests/unit/test_sec_edgar.py` 必须有以下两个专门测试:
   - `test_capex_sign_convention`:从 fixture 的 SEC `PaymentsToAcquirePropertyPlantAndEquipment`(正数)出发,验证 LineItem 返回的 `capital_expenditure` 为负。
   - `test_dividends_sign_convention`:同理验证 `dividends_and_other_cash_distributions` 为负。

5. **`get_market_cap` 历史分支**:简单版,`auto_adjusted_close(end_date) × current_shares_outstanding`。文档化 ±10% 精度限制(因为 split-adjusted close × 当下股数 ≠ 当时真实 market cap;小盘股或大量回购公司误差更大)。**stretch goal** 留到 Phase 4:如果验证矩阵显示某 persona 因这个误差炸了,再做精确版(用每期 10-Q/10-K 的 `EntityCommonStockSharesOutstanding` 配对 split-adjusted close)。

### Cache TTL 表(Phase 1.1 cache.py 必须实现并测试)

| Source | Endpoint | TTL | 理由 |
|---|---|---|---|
| `aggregator` | `financial_metrics` | **7d** | 季度财报数据,跨季度才需要刷新;短期内反复查同 ticker 不应每次重算 |
| `aggregator` | `prices` | **1d** | 日线 OHLCV,T+1 刷新即可 |
| `sec_edgar` | `cik_mapping` | **30d** | 公司 CIK 几乎不变,新上市公司才会动 |
| `yfinance` | `basic_info` | **30d** | sector/industry/country/shares_outstanding 长期稳定 |
| `aggregator` | `company_news` | **1h** | 新闻 hot,需要快速感知;不要无限新但要至少 1h 防抖 |
| `sec_edgar` | `company_facts` | **1d** | XBRL 财报 JSON,SEC 不会一天多次重发 |
| `aggregator` | `insider_trades` | **4h** | Form 4 当天就交,4h 兼顾 freshness 和 API 配额 |

**实现要求**:这 7 个 TTL 在 `src/data_sources/cache.py` 里以 `CacheTTL` 类常量暴露,`tests/unit/test_cache.py` 必须 parametrize 这张表,验证每个 (source, endpoint) 组合的 set/get/expire 行为。

## Phase 1:数据源 adapters(每个 adapter 独立写完独立测完才进下一个)

### 目录结构
```
src/data_sources/
├── init.py
├── base.py              # 抽象基类、共享异常、共享 retry 逻辑
├── cache.py             # SQLite 缓存层
├── sec_edgar.py         # SEC EDGAR companyfacts、submissions、filings
├── yfinance_adapter.py  # OHLCV、market cap、basic info
├── openinsider.py       # OpenInsider RSS parser
├── computed.py          # 从原始报表算 ROE/ROIC/FCF margin 等
└── aggregator.py        # 对外暴露的统一接口,签名跟原 api.py 对齐
tests/
├── unit/
│   ├── test_cache.py
│   ├── test_sec_edgar.py
│   ├── test_yfinance_adapter.py
│   ├── test_openinsider.py
│   ├── test_computed.py
│   └── fixtures/        # 真实 API 响应的 JSON dump,给 mock 用
└── integration/
├── test_sec_edgar_live.py
├── test_yfinance_live.py
└── test_openinsider_live.py
```
### 1.1 cache.py(必须最先写)

SQLite 缓存,schema:

```sql
CREATE TABLE cache (
  source TEXT NOT NULL,
  endpoint TEXT NOT NULL,
  key TEXT NOT NULL,
  fetched_at TIMESTAMP NOT NULL,
  ttl_seconds INTEGER NOT NULL,
  payload BLOB NOT NULL,
  PRIMARY KEY (source, endpoint, key)
);
```

**必测的 case**:
- TTL 内 hit 返回缓存
- TTL 过期返回 None
- 同一 key 不同 source 互不干扰
- 并发写入(用 threading)不丢数据
- payload 大小 > 1MB 不报错(SEC 一份 companyfacts 经常 5-10MB)
- **每个 TTL 表里的 (source, endpoint) 组合**(共 7 个,见 Phase 0 决议中的 TTL 表)都要有 parametrize 测试:set → 立即 get hit → 推进到 TTL 边界外 → get 返回 None。`CacheTTL` 类常量值与 spec 表格完全一致。

### 1.2 sec_edgar.py(最难,占 50% 工作量)

**必填 User-Agent**:从 env var `SEC_EDGAR_USER_AGENT` 读,格式 "Name email@x.com"。**没设这个就直接抛异常,不要用 fallback**——SEC 会因为缺 UA 给你返回 403,debug 起来浪费时间。

**实现的函数**:
- `get_cik_for_ticker(ticker: str) -> str`:从 `https://www.sec.gov/files/company_tickers.json` 查 CIK。结果缓存 30 天。
- `get_company_facts(cik: str) -> CompanyFacts`:`https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json`。返回的 Pydantic model 要把 `us-gaap` 和 `dei` 两个 taxonomy 都解析进来。
- `get_concept_series(cik: str, concept: str, unit: str = "USD") -> list[ConceptDataPoint]`:取出某个 XBRL concept(如 `NetIncomeLoss`)的时间序列,**自动处理 restated filings 取最新版**。
- `get_filings_index(cik: str, form: str = "10-K") -> list[FilingMeta]`:从 `https://data.sec.gov/submissions/CIK{cik:010d}.json` 拿 filing 列表。
- `get_8k_items(cik: str, since: date) -> list[EightKItem]`:8-K filings 解析成 (date, items, primary_doc_url) 列表,给新闻/事件用。

**XBRL parsing 必测的 edge cases**(没这些测试不算完成):
1. 同一 concept 多个 unit(USD vs USD/shares):函数要按 unit 参数过滤,不要 silently 选第一个
2. 同一 fiscal period 多次 filing(10-K + amend):取 `filed` 最新的那一份
3. fiscal year ≠ calendar year(NVDA 财年 1 月底结束):返回的 timestamp 用 `end` 字段不是 `filed`
4. 缺失中间季度(有些公司不报 Q3):返回的列表跳过缺失,**不要补 0**
5. 单位换算(`USD/shares` 表示 per-share 数据,不要乘股数)
6. 修订(restatement):新 fiscal period 出现时旧的同 period 数据被覆盖,需要 dedup by (`end`, `fp`, `fy`),保留 `filed` 最新的

**测试 fixture**:从真实 SEC 拉 NVDA、AAPL、BRK.A 三家的 companyfacts JSON,存到 `tests/unit/fixtures/sec/`,unit test 全部 mock 这些文件。BRK.A 选进来是因为它的 fiscal year 跟其他不同,且报表科目分类特殊。

### 1.3 yfinance_adapter.py

包装 yfinance 让它行为可预测:

- `get_prices(ticker: str, start: date, end: date) -> pd.DataFrame`:OHLCV,自动处理 split/dividend adjustment(用 `auto_adjust=True`)
- `get_market_cap(ticker: str) -> float | None`:从 `Ticker.info['marketCap']` 拿,**返回前验证是 float 且 > 0,否则返回 None**(yfinance 偶尔返回 string 或 None)
- `get_basic_info(ticker: str) -> BasicInfo`:sector、industry、shares_outstanding、country

**必测的 edge cases**:
1. 不存在的 ticker(如 "FAKE123"):返回空 DataFrame,不抛异常
2. ticker 在请求时间段内还没上市(如 NVDA 在 1990 年):返回空 DataFrame
3. yfinance 返回的 columns 大小写飘忽(`Close` vs `close`):统一小写
4. 时区:索引必须是 tz-aware UTC
5. 中间日 NaN(休市/数据缺失):forward fill 还是抛异常?**抛异常** + 在 log 里说明哪些日期缺失

### 1.4 openinsider.py

从 `http://openinsider.com/screener?s={ticker}` 抓 HTML,parse 表格。BeautifulSoup + 严格 schema 验证。

**必测**:
1. 没有任何 insider trade 的 ticker(罕见但存在):返回空列表
2. 表格 HTML 结构改变(测试用 fixture 模拟):抛 `OpenInsiderSchemaError` 而不是返回错数据
3. 解析金额 "$1,234,567.89" → float
4. 解析交易代码(P=Purchase, S=Sale, M=Option exercise 等)

### 1.5 computed.py

纯计算,无 IO,容易测。每个指标一个函数,公式写在 docstring 里。

最小集合(覆盖 ai-sub-invest persona 的需要):
- `roe(net_income, stockholders_equity) -> float`
- `roic(nopat, invested_capital) -> float`,NOPAT = EBIT × (1 - tax_rate)
- `fcf(operating_cash_flow, capex) -> float`,capex 注意符号(SEC 报负数)
- `fcf_margin(fcf, revenue) -> float`
- `debt_to_equity(total_debt, stockholders_equity) -> float`
- `current_ratio(current_assets, current_liabilities) -> float`
- `gross_margin(gross_profit, revenue) -> float`
- `operating_margin(operating_income, revenue) -> float`

**每个函数必测**:
- 正常输入
- 分母为 0:返回 None 或 NaN(明确选择,文档化)
- 负值(亏损公司的 ROE):允许返回负数,不要 abs
- 输入有 NaN:propagate(返回 NaN),不要默认 0

### 1.6 aggregator.py(对外接口)

签名**完全 mirror** ai-sub-invest 原本 `src/tools/api.py` 的 public 函数。返回 Pydantic model 用同名同字段(从 `src/data/models.py` import,**不要新建**)。

每个函数内部:cache check → 数据源调用 → schema validation → 写 cache → 返回。

## Phase 2:集成 ai-sub-invest

**做法**:env variable 路由,**不改原 api.py 大部分代码**:

```python
# src/tools/api.py 顶部
import os
_USE_FREE = os.getenv("USE_FREE_BACKEND", "0") == "1"

def get_financial_metrics(ticker, end_date, period="ttm", limit=10):
    if _USE_FREE:
        from src.data_sources.aggregator import get_financial_metrics as _impl
        return _impl(ticker, end_date, period, limit)
    # ... 原代码不动
```

`.env.example` 加上: 
```
USE_FREE_BACKEND=1
SEC_EDGAR_USER_AGENT=Your Name your-email@example.com
```
**集成测试**(必写):
- `tests/integration/test_persona_compatibility.py`:对 NVDA、MSFT、AVGO 三个 ticker,在 `USE_FREE_BACKEND=0` 和 `USE_FREE_BACKEND=1` 两种模式下分别运行 warren-buffett 和 fundamentals 两个 persona script,对比输出 JSON。允许 signal 和 confidence 有 ±15% 差异,但**核心字段必须存在且非 None**。这个测试做 A/B 对比的 ground truth。

## Phase 3:验证矩阵

写 `scripts/verify_free_backend.py`,跑下面这张表,生成 `docs/verification_report.md`:

| Persona | NVDA | MSFT | AVGO | INTU | ZETA |
|---|---|---|---|---|---|
| warren-buffett | ? | ? | ? | ? | ? |
| ben-graham | ? | ? | ? | ? | ? |
| charlie-munger | ? | ? | ? | ? | ? |
| druckenmiller | ? | ? | ? | ? | ? |
| fundamentals | ? | ? | ? | ? | ? |
| valuation | ? | ? | ? | ? | ? |
| technicals | ? | ? | ? | ? | ? |

每格填 `PASS` / `PARTIAL`(部分字段缺失但 signal 合理)/ `FAIL`(报错或信号明显错)。

**交付标准**:`PASS` ≥ 28 格(80%),`FAIL` ≤ 3 格。否则不算交付,定位失败原因再补 adapter。

## 已知缺口(不要试图实现,直接跳过)

这几类数据免费源没有干净版本,如果 persona 要,在对应函数返回空 list 或 None 并 log warning:

1. **分析师 estimates、forward EPS、价格目标**:返回空 list
2. **ETF 持仓拆分**:跳过
3. **Earnings call transcripts**:跳过
4. **机构持仓变动(13F 解析)**:Phase 1 不做。

## Stretch Goals(Phase 4,只在验证矩阵失败时考虑)

不阻塞 Phase 1-3 主线交付。完成验证矩阵后,根据 PASS/FAIL 分布再决定是否做:

1. **精确历史 market_cap**:配对每期 10-Q/10-K 的 `EntityCommonStockSharesOutstanding` 与 split-adjusted close,替换简单版的 `close × current_shares` —— 仅在小盘股/大量回购公司的 persona 出现 PARTIAL/FAIL 时做。
2. **13F 机构持仓变动解析**:`sec_edgar.py` 加 `get_13f_filings` —— 仅在 sentiment / portfolio-manager persona 需要时做。
3. **`FinancialMetrics` 部分未填字段补齐**:从 `INTENTIONALLY_UNFILLED_FIELDS` 清单里挑被实际访问的字段(目前为 0,后续 persona 演进可能用到)按需补。每补一个就从清单里删掉。
4. **News sentiment 自动标注**:接入 LLM 给 `CompanyNews.sentiment` 打 positive/negative/neutral —— 仅在 news-sentiment persona 的 keyword 打分明显劣化于原 API 的 sentiment 字段时做。

## Checkpoint 流程(必须遵守)

每完成下面任一节点,**停下来打印 status,等用户确认再继续**:
- ✅ Phase 0 完成(inventory 给用户看)
- ✅ cache.py + 测试通过
- ✅ sec_edgar.py + 测试通过(这是最大风险点,要单独确认)
- ✅ yfinance_adapter.py + 测试通过
- ✅ openinsider.py + 测试通过
- ✅ computed.py + 测试通过
- ✅ aggregator.py + 集成测试通过
- ✅ 验证矩阵跑完

不要一口气做完不通报,**用户的 Claude Code quota 也消耗不起一次性几个小时的 session**。

## 不要做的事

- 不要试图实现付费 API 才有的 derived metrics(比如 financialdatasets 自家算的"financial health score")。这些是黑盒,模仿不了,跳过。
- 不要写"自适应 fallback 链"(SEC 失败 → yfinance → 第三个 → ...)。直接报错,简单可调试。
- 不要重构 ai-sub-invest 原有代码。只在 `src/tools/api.py` 加路由分支,其他文件不动。
- 不要装 pandas、numpy 之外的"data science 全家桶"(scipy/sklearn 等)——徒增 image size,这个项目用不上。

## 开始

现在从 Phase 0 开始。读 `src/tools/api.py` 和 `.claude/skills/*/scripts/analyze.py`,产出 `docs/data_inventory.md`,然后停下来等用户 review。
