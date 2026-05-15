# kevin-suite — Claude Code Context

## What this is
Unified Streamlit dashboard combining the Apex 2035 portfolio tracker and the Flow Monitor macro dashboard.
Tracks ~71 positions across 8 brokers, plus live HK/China and US macro signals.

- GitHub: github.com/kevincccheng/kevin-suite
- Source projects: `apex2035` (portfolio) + `flow-monitor` (macro)

## Key facts
- All position data lives in **config.py** → `INITIAL_POSITIONS`
- After ANY edit to config.py, re-seed the Google Sheet (see command below)
- Google Sheet ID: 1M7zNVjhI0b5NmQDNHvOso_nHML1SlBVR7lWj0zPzApg
- Service account: apex2035-sheets@apex2035.iam.gserviceaccount.com

## Running locally
```bat
dev.bat
```
Runs: `streamlit run app.py --server.runOnSave true --server.port 8502`

## Re-seed command (run after editing config.py)
```bash
cd C:/Users/kevin/projects/kevin-suite
PYTHONIOENCODING=utf-8 python seed_sheet.py --creds service_account.json --sheet-id 1M7zNVjhI0b5NmQDNHvOso_nHML1SlBVR7lWj0zPzApg
```

## Architecture

### App entry point
- `app.py` — Streamlit UI, **9 tabs**

### Tabs
| # | Tab | Source |
|---|-----|--------|
| 1 | 📊 Master Ledger | apex2035 |
| 2 | 🏦 Broker Recon | apex2035 |
| 3 | 🎯 Analytics | apex2035 |
| 4 | ⚠️ Alerts | apex2035 |
| 5 | ✏️ Trade Entry | apex2035 |
| 6 | 📄 Export | apex2035 |
| 7 | 📈 Stock Analyzer | apex2035 |
| 8 | 🎯 Conviction Tracker | apex2035 |
| 9 | 🌊 Flow Monitor | flow-monitor |

### Portfolio modules (`core/`)
- `core/engine.py` — P&L calc, 10-pillar stock analysis, DCF fair value; see Stock Analyzer section below
- `core/prices.py` — yfinance prices; FX uses USDHKD=X (~7.83) as divisor; timestamps in HKT
- `core/sheets.py` — Google Sheets via gspread; reads `st.secrets["gcp_service_account"]`
- `core/exports.py` — PDF generation via ReportLab
- `core/lseg_data.py` — LSEG/Refinitiv Workspace integration (local desktop only; desktop session via localhost:9000, no credentials needed)

### Flow Monitor modules (`flow_core/`)
- `flow_core/hk_flows.py` — Stock Connect flows, HSI/HSCEI, CNH/CNY, PBOC rate via AKShare + yfinance
- `flow_core/us_macro.py` — Fed expectations, yield curve, VIX, ETF flows via FRED + yfinance
- `flow_core/composite.py` — Scoring engine: combines HK and US signals into −6 to +6 risk stance
- `tab_flow_monitor.py` — Render function `render_flow_monitor()` called by tab 9 in app.py

### Broker CSV parsers (`parsers/`)
- `parsers/schwab.py`, `ibkr.py`, `futu.py`, `moomoo.py`

### Config
- `config.py` — all position data, broker list, compliance rules, TICKER_MAP

## Data sources
| Source | Used by | Purpose |
|--------|---------|---------|
| yfinance | `core/prices.py`, `flow_core/` | Live prices, FX, HSI, ETFs, VIX |
| FRED API | `flow_core/us_macro.py` | Treasury yields, Fed rate, PBOC rate |
| AKShare | `flow_core/hk_flows.py` | Stock Connect flows, top holdings |
| Google Sheets | `core/sheets.py` | Persistent store for holdings, trades, snapshots |
| LSEG/Refinitiv | `core/lseg_data.py` | Fundamentals for Stock Analyzer (local only) |

## Environment variables (`.env` — never committed)
| Variable | Purpose |
|----------|---------|
| `EDP_API_KEY` | Enables LSEG mode (`USE_LSEG = bool(os.getenv("EDP_API_KEY"))`) |
| `FRED_API_KEY` | FRED API auth for yield curve and PBOC data |

## Streamlit secrets (`.streamlit/secrets.toml` — never committed)
| Secret | Purpose |
|--------|---------|
| `gcp_service_account` | Google Sheets service account JSON |

## Stock Analyzer — `core/engine.py` `calculate_pillars()`

### 10-Pillar framework

| # | Pillar | GREEN threshold | Source |
|---|--------|----------------|--------|
| 1 | **Fwd P/E vs Sector Median** | Fwd P/E < sector median | yfinance `forwardPE` |
| 2 | ROIC | > 15% | yfinance financials |
| 3 | Revenue Growth 3yr CAGR | > 10% | yfinance income_stmt |
| 4 | Net Income Growth 3yr CAGR | > 10% | yfinance income_stmt |
| 5 | Shares Outstanding 5yr | Shrinking (< −0.5%) | yfinance income_stmt |
| 6 | Net Debt / EBITDA | < 2× | yfinance balance_sheet |
| 7 | FCF Growth 3yr CAGR | > 10% | yfinance cash_flow |
| 8 | Price / FCF | < 20× | yfinance |
| 9 | Gross Margin Trend 3yr | Expanding > +2pp | yfinance income_stmt |
| 10 | **PEG Ratio** | < 1.0 | yfinance `forwardPE` + `earningsGrowth` |

**Pillar 1 detail**: compares `info["forwardPE"]` to a hardcoded sector median dict in `_sector_fwd_pe_medians`. YELLOW if within 20% above median; RED if >20% above. Sector name comes from `info["sector"]`. If sector not in the dict, rates NA. LSEG supplement fills NA using `TR.EPSMean`-derived P/E and the same sector median dict.

**Pillar 10 detail**: PEG = `forwardPE / (earningsGrowth × 100)`. Falls back to 3yr NI CAGR from Pillar 4 if `earningsGrowth` is absent. Negative growth → RED. GREEN < 1.0, YELLOW 1.0–1.5, RED > 1.5.

**`data_source` field**: every pillar dict carries `"data_source": "yfinance" | "LSEG" | "N/A"`. Set at creation for pillars 1 and 10; backfilled by a loop for pillars 2–9; overwritten to `"LSEG"` by the LSEG supplement block.

**`dcf_inputs` in return dict**: `calculate_pillars` returns a `dcf_inputs` key with pre-computed numeric values used to populate DCF slider defaults and the benchmark panel:
- `revenue_cagr_3yr`, `ni_cagr_3yr`, `fcf_cagr_3yr` (%, from pillars 3/4/7)
- `gross_margin_latest` (%, from pillar 9)
- `trailing_pe`, `fwd_pe`, `peg` (from pillars 1/10 and `info["trailingPE"]`)
- `profit_margins_pct` (from `info["profitMargins"]` × 100)
- `fcf_margin_pct` (FCF / Revenue × 100, most recent year)

### LSEG auto-detection (`app.py`, tab 7)
There is **no LSEG button**. On every Analyze click, `lseg_desktop_available()` is called silently. If Refinitiv Workspace is running, `calculate_pillars(ticker, True)` is called automatically and the data source indicator shows "LSEG + yfinance". If not, `calculate_pillars(ticker, False)` runs. The spinner message reflects which mode is active.

### DCF Fair Value Estimator (`app.py`, tab 7)
- **DCF Benchmark Panel** (`st.expander`) shows 7 rows of actual historical data from `dcf_inputs` above the sliders — Revenue CAGR, FCF CAGR, NI CAGR, Gross Margin, Trailing P/E, Forward P/E, PEG.
- **Slider defaults are dynamic**: revenue growth defaults to min(actual 3yr CAGR, 30%); profit margin to actual `profitMargins`; FCF margin to actual FCF/Revenue; terminal P/E to min(trailing P/E × 0.6, 35). Required return stays at 10%.
- A `st.warning` box above the sliders reminds that DCF is assumption-sensitive.

### Verdict banner colours (score-based, not verdict-based)
- Score 8–10 → dark green `#1a472a` / text `#4ade80`
- Score 5–7  → dark amber `#7d4e00` / text `#fbbf24`
- Score 0–4  → dark red `#5c0000`   / text `#f87171`

### Sector median Forward P/E lookup (hardcoded in `engine.py`)
```python
_sector_fwd_pe_medians = {
    "Technology": 28.0, "Semiconductors": 36.0, "Communication Services": 18.0,
    "Consumer Discretionary": 22.0, "Consumer Staples": 19.0, "Health Care": 17.0,
    "Financials": 13.0, "Industrials": 20.0, "Energy": 12.0, "Materials": 15.0,
    "Real Estate": 35.0, "Utilities": 15.0,
}
```
To update medians, edit this dict at the top of the `calculate_pillars` function body.

## Known gotchas

### Trade entry → Master Ledger flow (`core/sheets.py`)
`append_trades` writes to `Trades_Ledger`, then calls `_apply_trade_delta(trade)` for each trade to update `Holdings_Master`.

**Delta-based, not replay-based**: `_apply_trade_delta` reads the *current* `Holdings_Master` row as the baseline and applies the trade on top (BUY: weighted-average new cost; SELL: subtract shares, cost unchanged). It does **not** replay the full `Trades_Ledger` from scratch — doing so would ignore the config.py-seeded initial position and overwrite it with just the traded quantity. This was the original bug (fixed 2026-05-15).

**New positions**: when the ticker doesn't exist in `Holdings_Master`, `_apply_trade_delta` looks up name/sector via `yf.Ticker(ticker).info`, infers region from ticker suffix (`.HK` → HK, else US), and defaults `barbell_class` to `"CORE"`.

### Trade Entry tab ticker field (`app.py`, tab 5)
The stock name lookup widget sits **outside** the `st.form` block intentionally — Streamlit forms batch all widget changes and only rerun on submit, so a ticker input inside the form cannot trigger live name lookups. The outer `st.text_input(key="te_ticker")` drives the lookup; the inner form field is pre-populated from `st.session_state["te_ticker"]`. On successful submit, `st.session_state["_reset_te_ticker"] = True` is set and `st.rerun()` is called. On the next run, before the widget renders, `st.session_state.pop("te_ticker", None)` is executed — this is the only safe way to reset a keyed widget (Streamlit raises `StreamlitAPIException` if you set a widget's key directly after it has been instantiated in the same run).

### No password gate
The app is local-only. The `check_password()` gate was removed 2026-05-15. Do not re-add it.

## Common tasks

### Add a new stock position
Edit `config.py` → add to `INITIAL_POSITIONS` → re-seed → push to GitHub

### Add a short call option
```python
{
    "ticker": "TICKER-C{STRIKE}-{MON}{YY}",  # e.g. AAPL-C200-JUN26
    "name": "Short Call TICKER ${STRIKE} {Mon}-{YEAR}",
    "region": "US", "sector": "Options — Short Call", "barbell_class": "TACTICAL",
    "ccy": "USD",
    "brokers": [{"broker": "IBKR", "shares": -100, "avg_cost_local": PREMIUM_PER_SHARE}],
}
```
Then add to TICKER_MAP: `"TICKER-C{STRIKE}-{MON}{YY}": "TICKER{YY}{MM}{DD}C{STRIKE_8DIGITS}"`

### Remove an expired option
Delete the position from `INITIAL_POSITIONS` and its TICKER_MAP entry → re-seed → push

### Fix cost basis
Edit `avg_cost_local` in the relevant broker dict in `INITIAL_POSITIONS` → re-seed

### Modify Flow Monitor display
Edit `tab_flow_monitor.py` → change `render_flow_monitor()`. Import paths must use `flow_core.*` not `core.*`.

### Add a new data source to Flow Monitor
Add fetch logic in `flow_core/hk_flows.py` or `flow_core/us_macro.py` → update scoring in `flow_core/composite.py` → update display in `tab_flow_monitor.py`

## Secrets (never commit)
- `.env` — API keys (EDP_API_KEY, FRED_API_KEY)
- `service_account.json` — Google service account key
- `.streamlit/secrets.toml` — Streamlit secrets (GCP + app password)
- `streamlit_secrets_copy.txt` — local backup of secrets.toml
- All covered by `.gitignore`
