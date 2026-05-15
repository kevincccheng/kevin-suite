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
- `core/engine.py` — P&L calc; `brokers_list` column carries full broker detail
- `core/prices.py` — yfinance prices; FX uses USDHKD=X (~7.83) as divisor; timestamps in HKT
- `core/sheets.py` — Google Sheets via gspread; reads `st.secrets["gcp_service_account"]`
- `core/exports.py` — PDF generation via ReportLab
- `core/lseg_data.py` — LSEG/Refinitiv Workspace integration (local desktop only)

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

## Known gotchas

### Trade entry → Master Ledger flow (`core/sheets.py`)
`append_trades` writes to `Trades_Ledger`, then calls `recalculate_holding(ticker)` which re-derives total shares and avg cost from all trades and calls `upsert_holding` to update `Holdings_Master`.

**Critical ordering**: `read_trades.clear()` must be called **before** the `recalculate_holding` loop, not after. If the cache is cleared after, `recalculate_holding` reads stale pre-write data, finds no trades for the ticker, and silently returns without updating `Holdings_Master`. This was fixed 2026-05-15.

**New positions**: `recalculate_holding` looks up name/sector via `yf.Ticker(ticker).info` and infers region from ticker suffix (`.HK` → HK, else US) when writing a position that doesn't already exist in `Holdings_Master`. `barbell_class` defaults to `"CORE"`. This was fixed 2026-05-15.

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
