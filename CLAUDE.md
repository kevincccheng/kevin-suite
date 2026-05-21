# kevin-suite — Claude Code Context

## Standing Instructions (Always Apply)

- After completing ANY task, always run:
    git add -A
    git commit -m "[describe what was done]"
    git push origin master
- Never finish a task without pushing to GitHub.
- This applies to every change, no matter how small.
- If push fails, report the error — do not silently skip it.

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

### Flow Monitor modules (`flow_core/`) — Phase 2
- `flow_core/hk_flows.py` — All HK/China signals; LSEG primary, AKShare/yfinance/HKMA API fallback
- `flow_core/us_macro.py` — All US macro signals; LSEG primary, yfinance/FRED fallback
- `flow_core/composite.py` — Three-gate hierarchical scoring engine (Phase 2); see Flow Monitor section below
- `flow_core/signal_logger.py` — SQLite logger; writes to `data/flow_signals.db` on every refresh
- `flow_core/ai_briefing.py` — AI Morning Briefing; calls `claude-sonnet-4-6` via Anthropic API; 4hr session-state cache
- `tab_flow_monitor.py` — Render function `render_flow_monitor()` called by tab 9 in app.py

### Broker CSV parsers (`parsers/`)
- `parsers/schwab.py`, `ibkr.py`, `futu.py`, `moomoo.py`

### Config
- `config.py` — all position data, broker list, compliance rules, TICKER_MAP

## Data sources
| Source | Used by | Priority |
|--------|---------|----------|
| **LSEG/Refinitiv Workspace** | `core/lseg_data.py`, `flow_core/` | Primary for Flow Monitor + Stock Analyzer (local desktop only) |
| yfinance | `core/prices.py`, `flow_core/` | Fallback for Flow Monitor; primary for portfolio prices |
| FRED API | `flow_core/us_macro.py`, `flow_core/hk_flows.py` | Yield curve, Fed rate, PBOC rate (API key optional — CSV fallback) |
| AKShare (East Money) | `flow_core/hk_flows.py` | Stock Connect southbound flows (northbound suspended Nov 2023) |
| HKMA Open API | `flow_core/hk_flows.py` | HKMA Aggregate Balance, HIBOR rates (no key needed) |
| Google Sheets | `core/sheets.py` | Persistent store for holdings, trades, snapshots |
| CME ZQ Futures | `flow_core/us_macro.py` | Fed meeting probabilities (day-weighted from 30-day futures) |

## Data Architecture

### Fetch priority (Flow Monitor)
Every signal in `flow_core/` follows a strict priority chain — no exceptions:

```
LSEG/Refinitiv Workspace (localhost:9000)
  ↓ if unavailable
yfinance / FRED / AKShare / HKMA Open API
  ↓ if unavailable
{"error": True}  →  display "Unavailable" — never show fake data
```

`lseg_desktop_available()` (cached 60s) gates all LSEG calls. Fallback runs silently; the display badge shows which source was used.

### Signal persistence (Flow Monitor)
- **SQLite DB**: `data/flow_signals.db` — created automatically on first refresh
- **Table**: `daily_signals`, `date TEXT PRIMARY KEY` (one row per calendar day)
- **Write**: `log_daily_signal(composite, raw)` in `flow_core/signal_logger.py` — called on every tab refresh via `INSERT OR REPLACE`; silent on errors, never crashes the app
- **Read**: `get_signal_history(days=90)` — returns DataFrame for charting (Phase 3)
- The `data/` directory is in `.gitignore`; the DB is local-only

### Portfolio data flow
```
config.py INITIAL_POSITIONS  →  seed_sheet.py  →  Google Sheets Holdings_Master
                                                          ↓
                              Trades (via Trade Entry tab) → _apply_trade_delta()
                                                          ↓
                              app.py load_data()  →  read_holdings() (cached 5 min)
```

## Environment variables (`.env` — never committed)
| Variable | Purpose |
|----------|---------|
| `EDP_API_KEY` | Enables LSEG mode (`USE_LSEG = bool(os.getenv("EDP_API_KEY"))`) |
| `FRED_API_KEY` | FRED API auth for yield curve and PBOC data (optional — CSV fallback exists) |
| `ANTHROPIC_API_KEY` | Claude API for Flow Monitor AI Morning Briefing — without it the briefing section shows `st.info()` |

## Streamlit secrets (`.streamlit/secrets.toml` — never committed)
| Secret | Purpose |
|--------|---------|
| `gcp_service_account` | Google Sheets service account JSON |

## Flow Monitor — Phase 2 (`flow_core/`)

### Data fetch priority rule
Every signal in `flow_core/` follows: **LSEG first → fallback silently**. Each function calls `lseg_desktop_available()` internally (or delegates to a `get_*_lseg()` helper in `core/lseg_data.py`). If LSEG is unavailable, the fallback source runs without any user-visible error — the display just shows the fallback source badge. Never return fake data; unavailable means `{"error": True}`.

### All signals and their sources

**HK/China signals (`flow_core/hk_flows.py`)**

| Signal | Function | LSEG primary | Fallback |
|--------|----------|-------------|---------|
| Stock Connect flows | `get_stock_connect_flows()` | — | AKShare `stock_hsgt_fund_flow_summary_em()` |
| Southbound history (30d) | `get_stock_connect_history()` | — | AKShare `stock_hsgt_hist_em('南向资金')` |
| HSI / HSCEI | `get_hsi_data()` | — | yfinance `^HSI`, `^HSCE` |
| CNH/CNY spread | `get_cnh_cny_spread()` | — | yfinance `USDCNH=X`, `USDCNY=X` |
| PBOC 7-day rate | `get_pboc_rate()` | — | FRED `INTDSRCNM193N` → CSV fallback |
| **HKMA Aggregate Balance** | `get_hkma_balance()` | `get_hkma_balance_lseg()` (`HKHKMAAB=ECI`) | HKMA Open API → `closing_balance` field |
| **HIBOR (ON + 1M)** | `get_hibor()` | `HIBOROND=`, `HIBOR1MD=` | HKMA Open API → `hibor_overnight`, `hibor_fixing_1m` |
| **USD/HKD peg monitor** | `get_usdhkd()` | `USDHKD=` (tries 4 RICs) | yfinance `USDHKD=X` |
| **HSTECH Index** | `get_hstech()` | `get_hstech_lseg()` (`.HSTECH`) | yfinance `^HSTECH` |
| **USD/CNH vs 200DMA** | `get_usdcnh_200dma()` | `get_usdcnh_history_lseg()` (`CNY=` proxy) | yfinance `USDCNY=X` (250-day Ticker().history()) |
| **Southbound Conviction** | `get_southbound_conviction()` | — | AKShare `stock_hsgt_stock_statistics_em(南向持股)` |

**`get_southbound_conviction()` — detail**

Returns a **tuple `(top10_df, full_df)`**, not a single DataFrame:
- `top10_df` — top 10 net buyers sorted by `conviction_score` desc, then `net_buy_hkd` desc
- `full_df` — all 600 southbound-eligible stocks with metrics; used for the ticker lookup panel

Callers in `tab_flow_monitor.py` unpack with: `sb_conv, sb_conv_full = d["southbound_conviction"]`

**Why share count change, not market value change**: `持股市值变化-1日` (1-day holding value change) includes price appreciation on existing holdings — e.g. Tencent up 2.4% on 490B of existing holdings creates an 11.7B "change" with no new shares bought. The correct metric is:
```
net_buy_hkd = (持股数量_today - 持股数量_yesterday) × 当日收盘价
```
This isolates actual new shares added/removed by southbound investors.

**5D Acceleration**: `today_delta / prev_4day_avg_delta` — both computed from `持股数量` daily diffs across the 7-day fetch window. **Uncapped** (shows real numbers like 13.8x). Only shows "N/A" when prior average is near zero (< 10,000 shares, i.e. no meaningful prior activity).

**Conviction score (1–5)**:

| Component | Points |
|-----------|--------|
| True net buy > 1,000M HKD | +2.0 |
| True net buy 500–1,000M | +1.5 |
| True net buy 200–500M | +1.0 |
| True net buy < 200M | +0.5 |
| Acceleration > 4× | +1.5 |
| Acceleration 2–4× | +1.0 |
| Acceleration 1.5–2× | +0.5 |
| SB hold % > 30% | +1.0 |
| SB hold % 15–30% | +0.5 |
| Buying into weakness (net buy > 0 AND price < −1%) | +0.5 bonus |

Rounded to nearest 0.5, capped at 5.0. Displayed as `★★★★☆` style stars.

**AKShare fetch window and retry logic**: Primary attempt uses **4 calendar days** (~2,400 rows, 3 API pages). If that raises `ChunkedEncodingError` / `ProtocolError: Response ended prematurely`, retries once with **3 calendar days** after a 2s sleep. Do NOT increase the primary window above 4 days — East Money's `datacenter-web.eastmoney.com` drops the TCP connection mid-stream on large paginated fetches (~5+ pages), causing the request to stall for ~120s before failing. The 4-day window completes in ~9s; the old 7-day window took 148s on failure.

**US Macro signals (`flow_core/us_macro.py`)**

| Signal | Function | LSEG primary | Fallback |
|--------|----------|-------------|---------|
| Fed rate + FOMC probs | `get_fed_expectations()` | — | FRED `DFF` + CME ZQ futures via yfinance |
| Yield curve (2/5/10/30yr + real) | `get_yield_curve()` | — | FRED `DGS2/5/10/30`, `DFII10` → CSV fallback |
| VIX | `get_vix()` | — | yfinance `^VIX` |
| **DXY Dollar Index** | `get_dxy()` | `get_dxy_lseg()` (`.DXY` or `DXY=`) | yfinance `DX-Y.NYB` |
| **ETFs** (SPY/QQQ/GLD/TLT/FXI/KWEB/EEM) | `get_etf_flows()` | `get_etf_flows_lseg()` (`.N`/`.O` RICs) | yfinance 10-day download |

**`core/lseg_data.py` helpers added in Phase 2**
- `_lseg_last_price(ric)` — single price lookup, returns `float | None`
- `_lseg_history(ric, count, interval)` — list of N closing prices, oldest first
- `get_hkma_balance_lseg()`, `get_dxy_lseg()`, `get_hstech_lseg()`, `get_usdcnh_history_lseg()`, `get_etf_flows_lseg()`

### HKMA Open API field names (confirmed)
The HKMA API endpoint `daily-figures-interbank-liquidity` uses these field names:
- Aggregate balance → `closing_balance` (HKD millions; multiply by 1e6 for HKD)
- HIBOR overnight → `hibor_overnight`
- HIBOR 1-month → `hibor_fixing_1m` (NOT `hibor_1month`)

### Composite scoring — three-gate model (`flow_core/composite.py`)

**Entry point**: `calculate_composite_signal(data: dict) -> dict`

The `data` dict must contain keys: `sc_flows`, `hsi`, `cnh`, `vix`, `yield_curve`, `fed`, `dxy`, `hkma`, `hibor`, `usdhkd`, `usdcnh_200dma`, `hstech`. Missing/errored keys are treated as neutral (not as negative signals).

**Gate 1 — Global Liquidity (weight 40%, range −4 to +4)**

| Input | GREEN (+1) | RED (−1) | Special |
|-------|-----------|---------|---------|
| DXY signal | WEAK | STRONG | — |
| Real 10yr yield (DFII10) | < 1.5% | > 2.5% | — |
| VIX | CALM | FEAR | PANIC = −2 |
| Fed path | Cut prob > 50% | Hike prob > 20% | — |

**Force WAIT**: if Gate 1 score < −2, the overall stance is forced to WAIT regardless of Gates 2 and 3. "Global liquidity is hostile — do not deploy capital."

**Gate 2 — HK Liquidity (weight 30%, range −3 to +3)**

| Input | GREEN (+1) | RED (−1) |
|-------|-----------|---------|
| HKMA Aggregate Balance | EXPANDING | CONTRACTING |
| HIBOR trend | FALLING | RISING |
| USD/HKD | SAFE (>200 pips from 7.85) | ALERT (<50 pips) |

**Gate 3 — China/HK Risk Appetite (weight 30%, range −3 to +3)**

| Input | GREEN (+1) | RED (−1) |
|-------|-----------|---------|
| Southbound flow | > 5B HKD | Net negative |
| USD/CNH vs 200DMA | BELOW (RMB stable) | ABOVE (RMB weakening) |
| HSTECH vs HSI | HSTECH outperforming (+0.3pp) | HSTECH underperforming |
| HSI direction | Up > 0.5% | Down > 0.5% |

Northbound flows **removed from scoring** (suspended by China Nov 2023).

**Final score formula**:
```
combined = (gate1/4 * 0.4 + gate2/3 * 0.3 + gate3/4 * 0.3) * 10
```
Range: −10 to +10, rounded to 1 decimal.

**Stance mapping**:

| Score | HK/China | US | Overall |
|-------|----------|----|---------|
| Gate 1 forced | WAIT | WAIT | WAIT |
| ≥ +4 | ACCUMULATE | ACCUMULATE | ACCUMULATE |
| ≥ +1 | ACCUMULATE | NEUTRAL | ACCUMULATE |
| ≥ −1 | NEUTRAL | NEUTRAL | NEUTRAL |
| ≥ −3 | WAIT | NEUTRAL | WAIT |
| < −3 | WAIT | WAIT | WAIT |

**Return dict keys**: `gate1_score`, `gate2_score`, `gate3_score`, `combined_score`, `gate1_forced_wait`, `hk_stance`, `us_stance`, `overall_stance`, `action_line`, `color`, `gate1_factors`, `gate2_factors`, `gate3_factors`.

### SQLite signal logger (`flow_core/signal_logger.py`)
- **DB path**: `data/flow_signals.db` (created automatically, gitignored)
- **Table**: `daily_signals` with `date TEXT PRIMARY KEY`
- **`log_daily_signal(composite, raw)`** — called on every tab refresh; `INSERT OR REPLACE` by date; silent on errors, never crashes the app
- **`get_signal_history(days=90)`** — returns DataFrame sorted by date ascending; used by Phase 3a chart and Phase 3b signal_data assembly

### AI Morning Briefing (`flow_core/ai_briefing.py`)
- **`generate_briefing(signal_data: dict) -> str`** — calls the Anthropic API and returns a 3–4 sentence macro paragraph ending with a specific DCA deployment recommendation
- **Model**: `claude-sonnet-4-6`, `max_tokens=300`
- **API key**: reads `ANTHROPIC_API_KEY` from environment (loaded via `.env`). Returns empty string `""` if key is absent — the caller (`tab_flow_monitor.py`) then shows `st.info()` instead of crashing
- **Caching**: `st.session_state["briefing_text"]` + `"briefing_timestamp"` — regenerates only when: (a) first load of a new day, (b) >4 hours since last call, or (c) user clicks "🔄 Refresh". Never calls API on every page rerun.
- **System prompt context**: HK-based investor, HKD 100K/month DCA into HK/China + USD 8K/month into US equities; direct and actionable, no disclaimers
- **signal_data dict** assembled in `tab_flow_monitor.py` from all live fetched values — covers all 3 gate inputs plus HSI, VIX, DXY, yields, HIBOR, USD/HKD, southbound flow, HSTECH vs HSI, top 3 ETF movers

### Flow Monitor tab display (`tab_flow_monitor.py`)
The `_fetch_flow_data()` function is cached `@st.cache_data(ttl=900)` and fetches all 15 signals in one call. `render_flow_monitor()` structure:

1. **Header** + LSEG connection indicator (`lseg_desktop_available()`)
2. **Decision Panel** — three stance badges (HK, US, Overall) + bold action line + gate scores
3. **Gate factor breakdown** (collapsible expander)
4. **🤖 Morning Briefing** — AI paragraph in styled container + "🔄 Refresh" button + last-updated caption. Shows `st.info()` if no API key.
5. **Two-column layout**:
   - Left: Stock Connect → Southbound chart → **🎯 Conviction Table + Ticker Lookup** → HSI/HSCEI → HSTECH → CNH/CNY spread → CNH 200DMA → HKMA Balance → HIBOR → USD/HKD → PBOC rate
   - Right: DXY → Fed expectations → Yield curve (inc. real yield) → VIX → ETF Monitor
6. **📈 Signal History** — dual-axis chart (composite score bars + HSI % line) from SQLite; shows info message until ≥2 days of data; last-7-days summary table below chart
7. **Footer** with data credits

**Southbound Conviction Table** (inside left column, after the southbound chart):
- **🔍 Ticker Lookup** panel above the table: text input + "Check Flow" button. Searches `full_df` (600 stocks) by ticker code. Input cleaned to 5-digit zero-padded format (`700` → `00700.HK`). Shows `st.success()` card with all metrics if found, `st.warning()` if not in southbound data.
- **Top 10 table**: Stock (name + code) | True Net Buy (HKD M) | SB Hold % | 5D Accel | Price 1D% | Score (★★★★☆)
- Sorted by `conviction_score` descending, tiebroken by `net_buy_hkd`
- Caption explains methodology and data date

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

### Add a new signal to Flow Monitor
1. Add fetch function to `flow_core/hk_flows.py` or `flow_core/us_macro.py` (LSEG primary → fallback pattern)
2. If LSEG-specific fetch needed, add helper to `core/lseg_data.py`
3. Add to `_fetch_flow_data()` dict in `tab_flow_monitor.py`
4. Pass to `calculate_composite_signal(data)` in `flow_core/composite.py` if it affects scoring
5. Add display tile in `render_flow_monitor()`
6. Add column to `daily_signals` table in `flow_core/signal_logger.py` if you want it logged

### Adjust composite gate weights or thresholds
Edit `flow_core/composite.py` → `calculate_composite_signal()`. The three gate blocks are clearly labelled. The final formula `(g1/4*0.4 + g2/3*0.3 + g3/4*0.3) * 10` must always sum coefficients to 1.0.

## Secrets (never commit)
- `.env` — API keys (EDP_API_KEY, FRED_API_KEY)
- `service_account.json` — Google service account key
- `.streamlit/secrets.toml` — Streamlit secrets (GCP + app password)
- `streamlit_secrets_copy.txt` — local backup of secrets.toml
- All covered by `.gitignore`
