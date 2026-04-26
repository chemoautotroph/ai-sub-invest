# Data Inventory — Phase 0

ai-sub-invest 对 financialdatasets.ai 的全部依赖,以及免费源(SEC EDGAR / yfinance / OpenInsider)的覆盖度评估。

## 0. 仓库扫描范围

- `src/tools/api.py` — 7 个 public 函数封装 financialdatasets API
- `src/data/models.py` — 7 个返回值 Pydantic model + 5 个 `*Response` 包装
- `.claude/skills/*/scripts/{analyze.py,calculate.py,aggregate.py}` — 21 个 skill,实际有 20 个脚本(`portfolio-manager` 不调 api),其中 18 个 `analyze.py` + `risk-manager/calculate.py` + `portfolio-manager/aggregate.py`
- `.claude/skills/financial-data/scripts/*.py` — 6 个数据获取脚本(直接透传 api.py)

## 1. api.py 函数清单

| # | 函数 | 签名 | 返回 model | 调用的 financialdatasets endpoint |
|---|---|---|---|---|
| 1 | `get_prices` | `(ticker, start_date, end_date, api_key=None) -> list[Price]` | `Price` | `GET /prices/?ticker=&interval=day&interval_multiplier=1&start_date=&end_date=` |
| 2 | `get_financial_metrics` | `(ticker, end_date, period="ttm", limit=10, api_key=None) -> list[FinancialMetrics]` | `FinancialMetrics`(40+ 字段) | `GET /financial-metrics/?ticker=&report_period_lte=&limit=&period=` |
| 3 | `search_line_items` | `(ticker, line_items, end_date, period="ttm", limit=10, api_key=None) -> list[LineItem]` | `LineItem`(`extra="allow"` 动态字段) | `POST /financials/search/line-items` body=`{tickers, line_items, end_date, period, limit}` |
| 4 | `get_insider_trades` | `(ticker, end_date, start_date=None, limit=1000, api_key=None) -> list[InsiderTrade]` | `InsiderTrade` | `GET /insider-trades/?ticker=&filing_date_lte=&filing_date_gte=&limit=`(分页) |
| 5 | `get_company_news` | `(ticker, end_date, start_date=None, limit=1000, api_key=None) -> list[CompanyNews]` | `CompanyNews` | `GET /news/?ticker=&end_date=&start_date=&limit=`(分页) |
| 6 | `get_market_cap` | `(ticker, end_date, api_key=None) -> float \| None` | `float` | `end_date == today` 时打 `/company/facts/?ticker=`,否则复用 `get_financial_metrics().market_cap` |
| 7 | `get_price_data` / `prices_to_df` | 包装 `get_prices` 返回 `pd.DataFrame` | `pd.DataFrame` | (无新调用) |

> **注**: `LineItem` 模型只声明了 `ticker / report_period / period / currency`,其余字段由 `extra="allow"` 动态接收。免费源实现需要按调用方传入的 `line_items` 名字列表逐一返回 — 名字必须和当前 persona 用的一致。

## 2. Persona 对 api.py 的调用矩阵

| Persona / Script | get_prices | get_market_cap | get_financial_metrics | search_line_items | get_insider_trades | get_company_news |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| warren-buffett | | ✓ | ✓ ttm/10 | ✓ ttm/10 | | |
| ben-graham | | ✓ | ✓ annual/10 | ✓ annual/10 | | |
| charlie-munger | | ✓ | ✓ ttm/10 | ✓ ttm/10 | | |
| bill-ackman | | ✓ | ✓ ttm/10 | ✓ ttm/10 | | |
| aswath-damodaran | | ✓ | ✓ ttm/10 | ✓ ttm/10 | | |
| cathie-wood | | ✓ | ✓ ttm/10 | ✓ ttm/10 | | |
| phil-fisher | | ✓ | ✓ ttm/10 | ✓ ttm/10 | | |
| mohnish-pabrai | | ✓ | ✓ ttm/10 | ✓ ttm/10 | | |
| peter-lynch | | ✓ | ✓ ttm/10 | (import 但**未调用**)¹ | | |
| rakesh-jhunjhunwala | | ✓ | ✓ ttm/10 | (import 但**未调用**)¹ | | |
| michael-burry | | ✓ | ✓ ttm/10 | ✓ ttm/10 | ✓² | |
| valuation | | ✓ | ✓ ttm/10 | ✓ ttm/10 | | |
| fundamentals | | | ✓ ttm/10 | | | |
| growth-analyst | | | ✓ ttm/10 | | | |
| stanley-druckenmiller | ✓ (180d) | ✓ | ✓ ttm/10 | | | |
| sentiment | | | ✓ ttm/5 | | ✓² | |
| news-sentiment | | | | | | ✓³ |
| technicals | ✓ | | | | | |
| risk-manager | ✓ | | | | | |
| portfolio-manager | (无 api 调用,只聚合 signals) | | | | | |
| financial-data/* | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

**已知 bug(原代码)**:
1. **peter-lynch / rakesh-jhunjhunwala** `import search_line_items` 但 `__main__` 没调用,反而向 `analyze_financial_health` 传了 `[]`。无影响,但说明这两家其实**只需 metrics**。
2. **michael-burry/scripts/analyze.py:74** 调用 `get_insider_trades(ticker, end_date, 20)` —— 第三个位置参数是 `start_date: str | None`,不是 `limit`。`20` 会被当成 `filing_date_gte=20` 去查 SEC,基本一定返回空。**新实现要把 limit 当 limit**,顺手修。同理 `news-sentiment/scripts/analyze.py:36` 把 `limit` 传到 `start_date` 位置。
3. **michael-burry / sentiment** 都访问 `trade.transaction_type` 和 `trade.value` —— `InsiderTrade` 模型里**没有这两个字段**(实际字段是 `transaction_shares / transaction_value / transaction_price_per_share`)。原代码用 `getattr(trade, 'transaction_type', '')` 做了 silent 兜底,所以 insider 信号一直全是 0,从来没 work。**OpenInsider 抓回来的交易代码(P/S/M/...)正好可以补这个洞**,但要在 `InsiderTrade` 里加 `transaction_type: str | None`(扩展字段,不破坏既有 schema)。
- ttm = trailing twelve months;annual = 年报;limit 是 period 数量(取最近 10 期或 5 期)。
- "180d" 指 druckenmiller 把 end_date 往前推 180 天作为 start_date。

## 3. 字段实际使用清单(从 grep 真实访问统计)

### 3.1 `FinancialMetrics` — 实际访问的字段(按使用频次降序)

| 字段 | 使用次数 | 主要用途 | SEC EDGAR + yfinance 覆盖 |
|---|:-:|---|:-:|
| `return_on_equity` | 46 | 质量/护城河/管理层(几乎所有 fundamentals persona 都用) | ✅ NetIncomeLoss / StockholdersEquity |
| `debt_to_equity` | 37 | 财务健康/反向清单 | ✅ (LongTermDebt+ShortTermDebt) / StockholdersEquity |
| `earnings_growth` | 32 | PEG / 增长趋势 | ✅ 期间净利润同比 |
| `operating_margin` | 31 | 护城河/盈利能力/利润率稳定性 | ✅ OperatingIncomeLoss / Revenues |
| `price_to_earnings_ratio` | 29 | 估值/PEG | ✅ market_cap / NetIncomeLoss(yfinance 给 P/E,或自算) |
| `revenue_growth` | 23 | 增长/加速度 | ✅ Revenues 同比 |
| `free_cash_flow_per_share` | 20 | FCF 转化/护城河 | ✅ (OCF − Capex) / shares |
| `earnings_per_share` | 20 | Graham number / 增长 / FCF 转化 | ✅ EarningsPerShareDiluted (XBRL 直接给) |
| `current_ratio` | 19 | 流动性/财务健康 | ✅ AssetsCurrent / LiabilitiesCurrent |
| `gross_margin` | 15 | 护城河/创新/竞争位 | ✅ GrossProfit / Revenues |
| `price_to_sales_ratio` | 10 | 估值/逆向 | ✅ market_cap / Revenues |
| `price_to_book_ratio` | 9 | 深度价值/相对估值 | ✅ market_cap / StockholdersEquity |
| `net_margin` | 9 | 盈利能力/卖点 | ✅ NetIncomeLoss / Revenues |
| `return_on_invested_capital` | 4 | Munger 偏好 | ✅ NOPAT / InvestedCapital(NOPAT = OperatingIncome × (1−tax_rate);InvestedCapital = StockholdersEquity + LongTermDebt) |
| `free_cash_flow_yield` | 4 | 估值 | ✅ FCF / market_cap |
| `asset_turnover` | 2 | 资产效率(Fisher) | ✅ Revenues / Assets |
| `book_value_per_share` | 1 | Graham number | ✅ StockholdersEquity / shares |
| `book_value_growth` | 1 | 复利质量 | ✅ StockholdersEquity 同比 |
| `market_cap` | (经 get_market_cap) | 多处 | ✅ yfinance `Ticker.info['marketCap']`,end_date≠today 时也可用 close × shares |

**`FinancialMetrics` 模型里声明但实际从未被任何 persona 访问的字段**(可以直接 `None` 填充):
`enterprise_value, enterprise_value_to_ebitda_ratio, enterprise_value_to_revenue_ratio, peg_ratio, return_on_assets, inventory_turnover, receivables_turnover, days_sales_outstanding, operating_cycle, working_capital_turnover, quick_ratio, cash_ratio, operating_cash_flow_ratio, debt_to_assets, interest_coverage, earnings_per_share_growth, free_cash_flow_growth, operating_income_growth, ebitda_growth, payout_ratio, currency, ticker, report_period, period`

> 但 `ticker / report_period / period / currency` 是必填字段,免费源实现必须填(Pydantic validation)。

### 3.2 `LineItem` — 实际访问的字段名(动态字段)

| 字段名 | 使用次数 | 谁用 | SEC EDGAR XBRL 概念 |
|---|:-:|---|---|
| `earnings_per_share` | 15 | ben-graham, charlie-munger, bill-ackman, michael-burry | ✅ `EarningsPerShareDiluted` / `EarningsPerShareBasic` |
| `issuance_or_purchase_of_equity_shares` | 11 | warren-buffett, charlie-munger, bill-ackman, mohnish-pabrai | ✅ `StockRepurchasedAndRetiredDuringPeriodValue` − `StockIssuedDuringPeriodValueNewIssues`(注意符号) |
| `dividends_and_other_cash_distributions` | 10 | warren-buffett, ben-graham, charlie-munger, bill-ackman, mohnish-pabrai | ✅ `PaymentsOfDividends`(返回负值,与原 API 约定一致) |
| `outstanding_shares` | 8 | warren-buffett, ben-graham, charlie-munger, phil-fisher, mohnish-pabrai, aswath-damodaran | ✅ `CommonStockSharesOutstanding` 或 `EntityCommonStockSharesOutstanding`(dei) |
| `net_income` | 7 | warren-buffett, ben-graham, charlie-munger, aswath-damodaran, cathie-wood, valuation, bill-ackman, phil-fisher | ✅ `NetIncomeLoss` |
| `total_liabilities` | 6 | ben-graham, michael-burry, mohnish-pabrai | ✅ `Liabilities` |
| `capital_expenditure` | 6 | warren-buffett, aswath-damodaran, valuation, phil-fisher, cathie-wood | ✅ `PaymentsToAcquirePropertyPlantAndEquipment`(SEC 报正值,转负与原 API 约定一致) |
| `current_assets` | 4 | ben-graham, michael-burry | ✅ `AssetsCurrent` |
| `total_assets` | 3 | ben-graham, mohnish-pabrai, michael-burry | ✅ `Assets` |
| `shareholders_equity` | 2 | warren-buffett, charlie-munger, michael-burry | ✅ `StockholdersEquity` |
| `revenue` | 2 | cathie-wood, phil-fisher | ✅ `Revenues` 或 `RevenueFromContractWithCustomerExcludingAssessedTax`(新准则) |
| `free_cash_flow` | 2 | aswath-damodaran, valuation | ✅ 计算:`NetCashProvidedByUsedInOperatingActivities` + `PaymentsToAcquirePropertyPlantAndEquipment`(后者负向) |
| `depreciation_and_amortization` | 2 | warren-buffett, aswath-damodaran, valuation | ✅ `DepreciationDepletionAndAmortization` 或 `DepreciationAndAmortization` |
| `current_liabilities` | 1 | ben-graham | ✅ `LiabilitiesCurrent` |
| `book_value_per_share` | 1 | ben-graham | ✅ 计算:`StockholdersEquity` / `outstanding_shares` |
| `gross_profit` | 0 (warren-buffett 在 LINE_ITEMS 里申明但未访问) | — | ✅ `GrossProfit` |

### 3.3 `Price` 模型 — 全字段必须

`open / close / high / low / volume / time` —— ✅ yfinance `Ticker.history(auto_adjust=True)` 全覆盖。

### 3.4 `InsiderTrade` 模型字段

| 字段 | 真实访问? | OpenInsider 覆盖 |
|---|---|:-:|
| `ticker / filing_date` | 是(必填) | ✅ |
| `name / title / is_board_director / issuer` | 输出但很少读 | ✅ |
| `transaction_date / transaction_shares / transaction_price_per_share / transaction_value` | 部分(burry/sentiment 真实代码用错了字段名,但 model 本身没坏) | ✅ |
| `shares_owned_before_transaction / shares_owned_after_transaction` | 几乎不读 | ⚠️ OpenInsider 给 `Δown` % 而不是 before/after,需要 None |
| `security_title` | 不读 | ⚠️ OpenInsider 不直接给,可填 "Common Stock" |
| **`transaction_type`(扩展)** | michael-burry / sentiment 用 `getattr` 兜底访问 | ✅ OpenInsider 的 trans-code(P/S/M/A/G)能映射 |

### 3.5 `CompanyNews` 模型字段

| 字段 | 真实访问 | yfinance 覆盖 |
|---|---|:-:|
| `title` | ✅ news-sentiment 唯一访问的字段 | ✅ `Ticker.news[i]['content']['title']` |
| `ticker / author / source / date / url / sentiment` | model 必填(除 sentiment) | 部分 ✅(yfinance 给 publisher/link/providerPublishTime;date 可格式化;sentiment 永远 None) |

### 3.6 `CompanyFacts` 模型(只在 `get_market_cap` 当天分支用)

只读 `.market_cap`,其他字段未访问。yfinance `Ticker.info['marketCap']` 直接覆盖。当天/历史两条分支可统一改成只查 yfinance。

## 4. 覆盖度小结(按 endpoint)

| Endpoint | 覆盖度 | 说明 |
|---|:-:|---|
| `get_prices` | **100%** | yfinance 完全替代 |
| `get_market_cap` | **100%** | yfinance `Ticker.info['marketCap']`(当天)+ close × shares(历史) |
| `get_financial_metrics`(实际用到的 18/40 字段)| **100%** | 全部可由 SEC EDGAR XBRL 原始概念 + 价格 + 简单除法计算得到 |
| `search_line_items`(实际用到的 16 个字段)| **100%** | 全部 1:1 对应 us-gaap concept 或一步加减 |
| `get_insider_trades` | **~95%** | OpenInsider 全字段够用,`security_title` 用常量、`shares_owned_before/after` 留 `None`;另外修两处原代码 bug |
| `get_company_news` | **70%(头条够用)** | yfinance 给 title/publisher/link/timestamp,够 news-sentiment 跑(只读 title);深度 sentiment 字段必须留 `None`(spec 已说不实现 derived metrics) |
| **总体加权** | **≥ 95%** | 远高于 60% 阈值 |

实际未被访问的 `FinancialMetrics` 字段约占 model 的 50%,这部分免费源实现里全部填 `None` 就行(Pydantic 接受,persona 也已经处理 `None`)。

## 5. 进入 Phase 1 前的待确认事项

请确认以下决定后再开 Phase 1:

1. **Insider trade 修 bug 还是保持兼容?**(我倾向修 — 在 `InsiderTrade` 里加 `transaction_type: str | None`,把 OpenInsider 的 P/S/M 填进去;burry / sentiment 的 `getattr` 一直返回空字符串,所以这两家的 insider 信号目前是死的)
2. **CompanyNews `sentiment` 字段** 永远 `None` 还是用 keyword 简单打分填?(spec 说"分析师 estimates 跳过",news sentiment 本身没禁,但 yfinance 不给。我倾向只填 title+date+source+url,sentiment 留 `None`,让 news-sentiment 自己用 keyword 打分 — 它本来就这么做)
3. **`FinancialMetrics` 未访问字段** 默认全 `None`,Pydantic 通过 — 这是省力做法。同意?
4. **`LineItem` 字段命名** 严格按调用方的字符串(如 `dividends_and_other_cash_distributions`)返回,符号约定与原 API 保持(dividends/capex 为负)。同意?
5. **`get_market_cap` 历史分支** 直接 `close_on(end_date) × shares_on(end_date)`,不再走 `get_financial_metrics`,避免循环依赖。同意?

## 6. 阻塞性问题

无。覆盖度 ≥ 95%,远超 60% 阈值。**建议进 Phase 1**。
