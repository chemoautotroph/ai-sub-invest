# ConsensusAI

investment analysis that aggregates signals from 21 analyst personas to generate consensus-based trading recommendations.

## Overview

ConsensusAI uses Claude Code Skills to simulate multiple investment analysts, each with their own philosophy and methodology. The system aggregates their signals to produce consensus recommendations.

### Analyst Personas (12)

| Analyst | Style |
|---------|-------|
| Warren Buffett | Value investing, intrinsic value, competitive moats |
| Charlie Munger | Mental models, quality-focused, multidisciplinary |
| Ben Graham | Deep value, Graham Number, margin of safety |
| Peter Lynch | GARP, PEG ratios, 10-baggers |
| Phil Fisher | Scuttlebutt method, 15-point checklist, R&D focus |
| Michael Burry | Contrarian deep value, distressed, short positions |
| Mohnish Pabrai | Dhandho framework, asymmetric payoffs |
| Bill Ackman | Activist investing, turnarounds, governance |
| Cathie Wood | Disruptive innovation, AI, high-growth |
| Stanley Druckenmiller | Macro-driven, sector rotation, trend-following |
| Rakesh Jhunjhunwala | Emerging markets, macro-aware growth |
| Aswath Damodaran | Rigorous DCF, valuation models, WACC |

### Analysis Skills (9)

| Skill | Function |
|-------|----------|
| Fundamentals | Financial statements, ratios, profitability |
| Technicals | Chart patterns, indicators, momentum |
| Valuation | Multi-model DCF, comparables, asset-based |
| Sentiment | Insider trades, institutional ownership |
| News Sentiment | News flow, media coverage, event-driven |
| Growth Analyst | Revenue acceleration, margin expansion |
| Risk Manager | Position sizing, portfolio constraints |
| Portfolio Manager | Aggregate signals, final trading decisions |
| Financial Data | Fetch metrics, prices, news, insider trades |

## Installation

```bash
# Clone repository
git clone https://github.com/ancs21/ai-sub-invest.git
cd ai-sub-invest

# Install dependencies (requires Python 3.11+)
uv sync

# Set up environment
cp .env.example .env
# Edit .env: set FINANCIAL_DATASETS_API_KEY (paid backend) OR
#            set USE_FREE_BACKEND=1 + SEC_EDGAR_USER_AGENT="Name email" (free backend)

# Optional: Install SDK for programmatic access
uv add claude-agent-sdk
```

## Run in Dev Container (sandboxed Claude Code)

The repo ships with an Anthropic-style Claude Code sandbox under `.devcontainer/`.
The container runs Claude with `--dangerously-skip-permissions` behind an iptables
whitelist (Anthropic API, GitHub, npm, SEC EDGAR, OpenInsider, Yahoo Finance).

Prereqs: Docker Engine running on the host, plus the devcontainer CLI:

```bash
npm install -g @devcontainers/cli
```

One-shot launch (build + exec Claude inside):

```bash
./start_docker.sh
```

Equivalent manual commands:

```bash
# Build image + start container (reads .devcontainer/devcontainer.json)
devcontainer up --workspace-folder .

# Drop into a shell
devcontainer exec --workspace-folder . zsh

# Or launch Claude Code directly
devcontainer exec --workspace-folder . claude --dangerously-skip-permissions

# Force a rebuild after changing the Dockerfile or firewall script
devcontainer up --workspace-folder . --remove-existing-container
```

What gets mounted into the container:

| Host path | Container path | Purpose |
|---|---|---|
| project root | `/workspace` | code (delegated bind) |
| `~/.claude` | `/home/node/.claude` | Claude config + memory persistence |
| `~/.ssh` (ro) | `/home/node/.ssh` | git push / SSH keys |
| `~/.gitconfig` (ro) | `/home/node/.gitconfig` | git identity |

The `postStartCommand` runs `.devcontainer/init-firewall.sh` to install the
iptables whitelist — that's why `--cap-add=NET_ADMIN` and `NET_RAW` are set in
`devcontainer.json`. If you add a new data source domain, whitelist it there
and rebuild.

## Free Backend (no paid API required)

This fork adds a free-data path so you can run the full persona suite without a
`financialdatasets.ai` subscription. Set in `.env`:

```bash
USE_FREE_BACKEND=1
SEC_EDGAR_USER_AGENT="Your Name your-email@example.com"
```

All six `src/tools/api.py` data calls then route through `src/data_sources/aggregator`,
which assembles the same Pydantic shapes from:

- **SEC EDGAR XBRL** — companyfacts + submissions (fundamentals, line items)
- **yfinance** — OHLCV, market cap, basic info
- **OpenInsider** — insider trades (HTML scraper)

Persona scripts work unchanged. See [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md)
for the full enable/disable flow, env var requirements, firewall whitelist, and
known limitations (e.g. SEC EDGAR rate limits, ticker coverage gaps). The
verification matrix (5 tickers × 7 personas A/B paid-vs-free) lives in
[`docs/verification_report.md`](docs/verification_report.md).

## Usage

### Via Claude Code Chat

Simply ask Claude to analyze stocks:

```
Analyze AAPL like Warren Buffett
```
```
Run all analysts on TSLA and give me a trading decision
```
```
What's the valuation for MSFT?
```

#### Example Prompts

| Task | Prompt |
|------|--------|
| Single analyst | `Analyze NVDA using Charlie Munger's approach` |
| Multiple analysts | `Run Buffett, Graham, and Lynch on META` |
| Full analysis | `Aggregate all signals for AMZN` |
| Specific focus | `What's the DCF valuation for GOOGL?` |
| Comparison | `Compare AAPL and MSFT using fundamentals` |
| Technical | `Show me the technical analysis for SPY` |
| Sentiment | `What's the insider sentiment on TSLA?` |

### Via SDK

```bash
# Single ticker
uv run python src/sdk_main.py AAPL 2025-12-06

# Multiple tickers
uv run python src/sdk_main.py AAPL,MSFT,NVDA 2025-12-06

# With custom portfolio cash
uv run python src/sdk_main.py AAPL,GOOGL 2025-12-06 --cash 50000

# Specific analysts only
uv run python src/sdk_main.py NVDA 2025-12-06 --analysts warren-buffett,cathie-wood,technicals

# Verbose output (see intermediate steps)
uv run python src/sdk_main.py TSLA 2025-12-06 -v

# Save results to file
uv run python src/sdk_main.py AAPL,MSFT 2025-12-06 -o results.json

# Full example with all options
uv run python src/sdk_main.py AAPL,MSFT,GOOGL 2025-12-06 \
  --start-date 2025-06-01 \
  --cash 100000 \
  --analysts warren-buffett,ben-graham,technicals,valuation \
  --verbose \
  --output analysis.json
```

#### SDK Options

| Flag | Description | Default |
|------|-------------|---------|
| `tickers` | Comma-separated tickers | Required |
| `end_date` | Analysis date (YYYY-MM-DD) | Required |
| `--start-date` | Historical data start | 6 months before end |
| `--cash` | Initial portfolio cash | 100,000 |
| `--analysts` | Specific analysts to use | Core 6 analysts |
| `--verbose, -v` | Show intermediate output | False |
| `--output, -o` | Save JSON to file | stdout |

### Run Individual Skills

```bash
# Warren Buffett analysis
uv run python .claude/skills/warren-buffett/scripts/analyze.py AAPL 2025-12-06

# Technical analysis (requires date range)
uv run python .claude/skills/technicals/scripts/analyze.py AAPL 2024-06-01 2025-12-06

# Risk calculation
uv run python .claude/skills/risk-manager/scripts/calculate.py AAPL 2025-12-06 100000

# Aggregate signals
uv run python .claude/skills/portfolio-manager/scripts/aggregate.py '{
  "warren_buffett": {"signal": "bullish", "confidence": 85},
  "ben_graham": {"signal": "neutral", "confidence": 52}
}'
```

## Output Format

All analysts return JSON with:

```json
{
  "ticker": "AAPL",
  "signal": "bullish",
  "confidence": 85,
  "score": 18,
  "max_score": 22,
  "reasoning": "...",
  "market_cap": 3500000000000
}
```

Portfolio manager aggregation returns:

```json
{
  "action": "buy",
  "confidence": 75,
  "reasoning": "Bullish consensus (5/8 analysts) with 75% avg confidence",
  "consensus_details": {
    "bullish_count": 5,
    "bearish_count": 1,
    "neutral_count": 2,
    "weighted_score": 0.45
  }
}
```

## Project Structure

```
consensusai/
├── .claude/
│   └── skills/                # 21 analyst skills
│       ├── warren-buffett/
│       ├── ben-graham/
│       ├── portfolio-manager/
│       └── ...
├── .devcontainer/             # Claude Code sandbox (Dockerfile + firewall)
├── docs/
│   ├── USER_GUIDE.md          # free-backend enable/disable, env vars
│   ├── data_inventory.md      # paid-vs-free field-level audit (Phase 0)
│   └── verification_report.md # 5 tickers × 7 personas A/B parity
├── scripts/
│   ├── fetch_*_fixtures.py    # snapshot real API responses for tests
│   └── verify_free_backend.py # parity harness (paid vs free)
├── src/
│   ├── data/
│   │   ├── cache.py           # in-memory cache (paid backend)
│   │   └── models.py          # Pydantic models
│   ├── data_sources/          # free backend (added in this fork)
│   │   ├── cache.py           # SQLite cache with TTL (PROJECT_SPEC pinned)
│   │   ├── sec_edgar.py       # XBRL companyfacts / submissions adapter
│   │   ├── yfinance_adapter.py
│   │   ├── openinsider.py     # HTML scraper
│   │   ├── computed.py        # 8 pure ratio functions
│   │   └── aggregator.py      # mirrors src/tools/api.py shape
│   ├── tools/
│   │   └── api.py             # data API (routes to free backend via env)
│   ├── utils/
│   │   └── api_key.py
│   └── sdk_main.py            # SDK entry point
├── tests/                     # unit + parity tests
├── start_docker.sh            # one-shot: devcontainer up + exec claude
├── pyproject.toml
└── README.md
```

## Disclaimer

This project is for **educational and research purposes only**.

- Not intended for real trading or investment
- No investment advice or guarantees provided
- Consult a financial advisor for investment decisions
- Past performance does not indicate future results

## Inspiration

Inspired by [ai-hedge-fund](https://github.com/virattt/ai-hedge-fund).

## License

MIT License
