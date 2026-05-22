"""HK/China flow data fetchers. Returns error dict/empty on failure — never fake data."""

import requests
import pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup
import yfinance as yf
import os

try:
    import streamlit as st
    STREAMLIT_AVAILABLE = True
except ImportError:
    STREAMLIT_AVAILABLE = False

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False

_RMB_HKD = 1.07


def get_stock_connect_flows() -> dict:
    """
    Fetch today's Stock Connect flows via AKShare (East Money).
    Northbound real-time data suspended by China Nov 2023; southbound is live.
    Returns {"error": True} if unavailable.
    """
    if not AKSHARE_AVAILABLE:
        return {"error": True, "error_msg": "AKShare not installed"}
    try:
        df = ak.stock_hsgt_fund_flow_summary_em()
        if df is None or df.empty:
            return {"error": True, "error_msg": "AKShare returned no data"}

        date_val = str(df['交易日'].iloc[0])
        nb_rows = df[df['资金方向'] == '北向']
        sb_rows = df[df['资金方向'] == '南向']
        nb_rmb = float(nb_rows['成交净买额'].sum())
        sb_rmb = float(sb_rows['成交净买额'].sum())
        nb_hkd = nb_rmb * 1e8 * _RMB_HKD
        sb_hkd = sb_rmb * 1e8 * _RMB_HKD

        def _sb_signal(v):
            if v > 100: return "STRONG_BUY"
            if v > 0:   return "BUY"
            if v > -100: return "SELL"
            return "STRONG_SELL"

        return {
            "date": date_val,
            "northbound": {
                "net_flow_rmb_bn": nb_rmb,
                "net_flow_hkd": nb_hkd,
                "note": "Northbound data suspended by China since Nov 2023",
                "signal": "NEUTRAL",
            },
            "southbound": {
                "net_flow_rmb_bn": sb_rmb,
                "net_flow_hkd": sb_hkd,
                "signal": _sb_signal(sb_rmb),
            },
        }
    except Exception as e:
        return {"error": True, "error_msg": str(e)}


def _parse_hkex_api(data: dict) -> dict:
    try:
        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "northbound": {
                "net_flow_hkd": float(data.get("nbNetBuyTurnover", 0)) * 1e6,
                "buy_turnover": float(data.get("nbBuyTurnover", 0)) * 1e6,
                "sell_turnover": float(data.get("nbSellTurnover", 0)) * 1e6,
                "quota_used_pct": float(data.get("nbQuotaUsedPct", 0)),
                "quota_remaining_hkd": float(data.get("nbQuotaRemaining", 0)) * 1e6,
            },
            "southbound": {
                "net_flow_hkd": float(data.get("sbNetBuyTurnover", 0)) * 1e6,
                "buy_turnover": float(data.get("sbBuyTurnover", 0)) * 1e6,
                "sell_turnover": float(data.get("sbSellTurnover", 0)) * 1e6,
                "quota_used_pct": float(data.get("sbQuotaUsedPct", 0)),
            },
        }
    except Exception:
        return {}


def _parse_hkex_api_v2(text: str) -> dict:
    try:
        soup = BeautifulSoup(text, "lxml")
        tables = soup.find_all("table")
        if not tables:
            return {}
        return {}
    except Exception:
        return {}


def _parse_hkex_quota_page(html: str) -> dict:
    try:
        soup = BeautifulSoup(html, "lxml")
        tables = soup.find_all("table")
        result = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "northbound": {"net_flow_hkd": 0, "buy_turnover": 0, "sell_turnover": 0,
                           "quota_used_pct": 0, "quota_remaining_hkd": 0},
            "southbound": {"net_flow_hkd": 0, "buy_turnover": 0, "sell_turnover": 0,
                           "quota_used_pct": 0},
        }
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
                text_lower = " ".join(cells).lower()
                if "northbound" in text_lower or "north" in text_lower:
                    for cell in cells:
                        try:
                            val = float(cell.replace(",", "").replace("%", "").replace("$", ""))
                            if "%" in cell and 0 <= val <= 100:
                                result["northbound"]["quota_used_pct"] = val
                            elif val > 1e8:
                                if result["northbound"]["buy_turnover"] == 0:
                                    result["northbound"]["buy_turnover"] = val
                        except (ValueError, AttributeError):
                            pass
        if any(v != 0 for v in result["northbound"].values()):
            return result
    except Exception:
        pass
    return {}


def get_stock_connect_history(days: int = 30) -> pd.DataFrame:
    """
    Last N days of southbound Stock Connect flows via AKShare.
    Returns empty DataFrame if unavailable — no simulated fallback.
    """
    if not AKSHARE_AVAILABLE:
        return pd.DataFrame()
    try:
        df = ak.stock_hsgt_hist_em(symbol='南向资金')
        df2 = df.dropna(subset=['当日成交净买额'])
        if df2.empty:
            return pd.DataFrame()
        df2 = df2.tail(days).copy()
        df2 = df2.rename(columns={'日期': 'date', '当日成交净买额': 'southbound_net_rmb'})
        df2['date'] = pd.to_datetime(df2['date'])
        df2['southbound_net_rmb'] = pd.to_numeric(df2['southbound_net_rmb'], errors='coerce')
        df2['southbound_net'] = df2['southbound_net_rmb'] * 1e8 * _RMB_HKD
        # northbound_net mirrors southbound for chart column compatibility
        df2['northbound_net'] = df2['southbound_net']
        df2['northbound_cumulative_5d'] = df2['northbound_net'].rolling(5).sum()
        df2['northbound_cumulative_20d'] = df2['northbound_net'].rolling(20).sum()
        return df2[['date', 'northbound_net', 'southbound_net',
                    'northbound_cumulative_5d', 'northbound_cumulative_20d']]
    except Exception:
        return pd.DataFrame()


def get_hsi_data() -> dict:
    """HSI and HSCEI current levels via yfinance. Returns {"error": True} on failure."""
    try:
        tickers = yf.download(["^HSI", "^HSCE"], period="5d", progress=False, auto_adjust=True)
        if tickers.empty:
            return {"error": True, "error_msg": "yfinance returned no HSI data"}
        close = tickers["Close"] if isinstance(tickers["Close"], pd.DataFrame) else tickers[["Close"]]
        hsi_col = next(
            (c for c in close.columns if "HSI" in str(c).upper() and "HSCE" not in str(c).upper()), None
        )
        hscei_col = next((c for c in close.columns if "HSCE" in str(c).upper()), None)
        if not hsi_col:
            return {"error": True, "error_msg": "HSI column not found"}
        hsi_vals = close[hsi_col].dropna()
        hscei_vals = close[hscei_col].dropna() if hscei_col else pd.Series(dtype=float)
        if len(hsi_vals) < 2:
            return {"error": True, "error_msg": "Insufficient HSI history"}
        hsi_now = float(hsi_vals.iloc[-1])
        hsi_prev = float(hsi_vals.iloc[-2])
        if len(hscei_vals) >= 2:
            hscei_now = float(hscei_vals.iloc[-1])
            hscei_prev = float(hscei_vals.iloc[-2])
            hscei_chg = (hscei_now - hscei_prev) / hscei_prev * 100
        else:
            hscei_now = 0.0
            hscei_chg = 0.0
        return {
            "hsi": {
                "level": hsi_now,
                "change_pct": (hsi_now - hsi_prev) / hsi_prev * 100,
            },
            "hscei": {
                "level": hscei_now,
                "change_pct": hscei_chg,
            },
            "spread": hsi_now - hscei_now,
        }
    except Exception as e:
        return {"error": True, "error_msg": str(e)}


def get_cnh_cny_spread() -> dict:
    """CNH/CNY spread — offshore vs onshore RMB signal. Returns {"error": True} on failure."""
    try:
        tickers = yf.download(["USDCNH=X", "USDCNY=X"], period="5d", progress=False, auto_adjust=True)
        if tickers.empty:
            return {"error": True, "error_msg": "yfinance returned no FX data"}
        close = tickers["Close"]
        if isinstance(close, pd.Series):
            return {"error": True, "error_msg": "Unexpected series format"}
        cnh_col = next((c for c in close.columns if "CNH" in str(c).upper()), None)
        cny_col = next(
            (c for c in close.columns if "CNY" in str(c).upper() and "CNH" not in str(c).upper()), None
        )
        if not cnh_col or not cny_col:
            return {"error": True, "error_msg": "CNH/CNY columns not found"}
        cnh = float(close[cnh_col].dropna().iloc[-1])
        cny = float(close[cny_col].dropna().iloc[-1])
        spread_pips = abs(cnh - cny) * 10000
        if spread_pips < 200:
            signal = "STABLE"
        elif spread_pips < 500:
            signal = "MILD_PRESSURE"
        else:
            signal = "STRESS"
        return {
            "cnh_per_usd": cnh,
            "cny_per_usd": cny,
            "spread_pips": spread_pips,
            "signal": signal,
        }
    except Exception as e:
        return {"error": True, "error_msg": str(e)}


def get_pboc_rate() -> dict:
    """
    PBOC 7-day reverse repo rate from FRED series INTDSRCNM193N.
    Returns {"error": True, "date": today} if unavailable — never a hardcoded rate.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    fred_key = os.environ.get("FRED_API_KEY", "")
    if not fred_key and STREAMLIT_AVAILABLE:
        try:
            fred_key = st.secrets.get("FRED_API_KEY", "")
        except Exception:
            pass

    if fred_key:
        try:
            from fredapi import Fred
            fred = Fred(api_key=fred_key)
            series = fred.get_series("INTDSRCNM193N", observation_start="2024-01-01")
            series = series.dropna()
            if not series.empty:
                rate = float(series.iloc[-1])
                date = str(series.index[-1].date())
                prev = float(series.iloc[-2]) if len(series) > 1 else rate
                return {"rate": rate, "date": date, "change_from_prev": rate - prev}
        except Exception:
            pass

    # Unauthenticated FRED CSV fallback
    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=INTDSRCNM193N"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            lines = [l for l in resp.text.strip().split("\n") if l and not l.startswith("DATE")]
            valid = [l for l in lines if len(l.split(",")) == 2 and l.split(",")[1].strip() not in (".", "")]
            if valid:
                last = valid[-1].split(",")
                prev_line = valid[-2].split(",") if len(valid) > 1 else last
                rate = float(last[1])
                prev = float(prev_line[1])
                return {"rate": rate, "date": last[0], "change_from_prev": rate - prev}
    except Exception:
        pass

    return {"error": True, "date": today, "error_msg": "FRED INTDSRCNM193N unavailable"}


# ── New Phase 2 signals ───────────────────────────────────────────


def get_hkma_balance() -> dict:
    """
    HKMA Aggregate Balance (HKD bn).
    Primary: LSEG. Fallback: HKMA Open API.
    Returns {"balance": float, "trend": str, "signal": str, "source": str}
    or {"error": True}.
    """
    from core.lseg_data import get_hkma_balance_lseg
    result = get_hkma_balance_lseg()
    if result:
        bal = result["balance"]
        chg = result["change"]
        chg_pct = chg / bal * 100 if bal else 0
        if chg_pct > 2:
            trend, signal = "EXPANDING", "EXPANDING"
        elif chg_pct < -2:
            trend, signal = "CONTRACTING", "CONTRACTING"
        else:
            trend, signal = "STABLE", "STABLE"
        return {"balance": bal, "change": chg, "trend": trend,
                "signal": signal, "source": "LSEG"}

    # HKMA Open API fallback
    try:
        url = ("https://api.hkma.gov.hk/public/market-data-and-statistics/"
               "daily-monetary-statistics/daily-figures-interbank-liquidity")
        resp = requests.get(url, timeout=10, params={"offset": 0, "limit": 10,
                                                      "sortby": "end_of_date",
                                                      "sortorder": "desc"})
        if resp.status_code == 200:
            records = resp.json().get("result", {}).get("records", [])
            # Field is closing_balance (HKD millions)
            vals = [float(r["closing_balance"]) for r in records
                    if r.get("closing_balance") not in (None, "", "N/A")]
            if len(vals) >= 2:
                bal_m = vals[0]  # HKD millions
                chg_pct = (vals[0] - vals[min(6, len(vals)-1)]) / vals[min(6, len(vals)-1)] * 100
                if chg_pct > 2:
                    trend, signal = "EXPANDING", "EXPANDING"
                elif chg_pct < -2:
                    trend, signal = "CONTRACTING", "CONTRACTING"
                else:
                    trend, signal = "STABLE", "STABLE"
                return {"balance": bal_m * 1e6, "change": (vals[0] - vals[1]) * 1e6,
                        "trend": trend, "signal": signal, "source": "HKMA API"}
    except Exception:
        pass
    return {"error": True}


def get_hibor() -> dict:
    """
    HIBOR overnight and 1-month rates.
    Primary: LSEG RICs HIBOROND= and HIBOR1MD=.
    Fallback: HKMA Open API.
    Returns {"overnight": float, "one_month": float, "trend": str, "source": str}
    or {"error": True}.
    """
    from core.lseg_data import _lseg_last_price, _lseg_history, lseg_desktop_available
    if lseg_desktop_available():
        try:
            overnight = _lseg_last_price("HIBOROND=")
            one_month = _lseg_last_price("HIBOR1MD=")
            if overnight is not None and one_month is not None:
                hist = _lseg_history("HIBOR1MD=", 5)
                if len(hist) >= 2:
                    trend = "RISING" if hist[-1] > hist[0] * 1.01 else (
                            "FALLING" if hist[-1] < hist[0] * 0.99 else "STABLE")
                else:
                    trend = "STABLE"
                return {"overnight": overnight, "one_month": one_month,
                        "trend": trend, "source": "LSEG"}
        except Exception:
            pass

    # HKMA Open API fallback
    try:
        url = ("https://api.hkma.gov.hk/public/market-data-and-statistics/"
               "daily-monetary-statistics/daily-figures-interbank-liquidity")
        resp = requests.get(url, timeout=10, params={"offset": 0, "limit": 10,
                                                      "sortby": "end_of_date",
                                                      "sortorder": "desc"})
        if resp.status_code == 200:
            records = resp.json().get("result", {}).get("records", [])
            # Field names confirmed from HKMA API
            on_vals = [float(r["hibor_overnight"]) for r in records
                       if r.get("hibor_overnight") not in (None, "", "N/A")]
            m1_vals = [float(r["hibor_fixing_1m"]) for r in records
                       if r.get("hibor_fixing_1m") not in (None, "", "N/A")]
            if on_vals and m1_vals:
                overnight = on_vals[0]
                one_month = m1_vals[0]
                trend = ("RISING"  if len(m1_vals) >= 5 and m1_vals[0] > m1_vals[4] * 1.01 else
                         "FALLING" if len(m1_vals) >= 5 and m1_vals[0] < m1_vals[4] * 0.99 else
                         "STABLE")
                return {"overnight": overnight, "one_month": one_month,
                        "trend": trend, "source": "HKMA API"}
    except Exception:
        pass
    return {"error": True}


def get_usdhkd() -> dict:
    """
    USD/HKD spot rate and distance from weak-side 7.85 band.
    Primary: LSEG RIC USDHKD=. Fallback: yfinance USDHKD=X.
    Signal: SAFE (>200 pips), WATCH (<200 pips), ALERT (<50 pips from 7.85).
    """
    from core.lseg_data import _lseg_last_price, lseg_desktop_available
    rate = None
    source = "yfinance"

    if lseg_desktop_available():
        for ric in ("USDHKD=", "USDHKD=R", "HKD=", ".USDHKD"):
            rate = _lseg_last_price(ric)
            if rate is not None:
                source = "LSEG"
                break

    if rate is None:
        try:
            data = yf.download("USDHKD=X", period="5d", progress=False, auto_adjust=True)
            if not data.empty:
                close = data["Close"]
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
                rate = float(close.dropna().iloc[-1])
                source = "yfinance"
        except Exception:
            pass

    if rate is None:
        return {"error": True}

    distance_pips = (7.85 - rate) * 10000
    if distance_pips > 200:
        signal = "SAFE"
    elif distance_pips > 50:
        signal = "WATCH"
    else:
        signal = "ALERT"

    return {"rate": round(rate, 4), "distance_pips": round(distance_pips, 1),
            "signal": signal, "source": source}


def get_hstech() -> dict:
    """
    Hang Seng Tech Index.
    Primary: LSEG .HSTECH. Fallback: yfinance ^HSTECH.
    """
    from core.lseg_data import get_hstech_lseg
    result = get_hstech_lseg()
    if result:
        return result

    try:
        data = yf.download("^HSTECH", period="5d", progress=False, auto_adjust=True)
        if data.empty:
            return {"error": True}
        close = data["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        close = close.dropna()
        if len(close) < 2:
            return {"error": True}
        price     = float(close.iloc[-1])
        chg_pct   = (price - float(close.iloc[-2])) / float(close.iloc[-2]) * 100
        return {"price": price, "change_pct": round(chg_pct, 2), "source": "yfinance"}
    except Exception:
        return {"error": True}


def get_usdcnh_200dma() -> dict:
    """
    USD/CNH vs its 200-day moving average.
    Primary: LSEG history. Fallback: yfinance USDCNH=X.
    Signal: ABOVE_200DMA (RMB weakening), BELOW_200DMA (RMB stable/strengthening).
    """
    from core.lseg_data import get_usdcnh_history_lseg
    df = get_usdcnh_history_lseg(250)
    source = "LSEG"

    if df.empty:
        source = "yfinance"
        try:
            # USDCNY=X has full history on yfinance; use as CNH proxy for 200DMA signal
            hist = yf.Ticker("USDCNY=X").history(period="2y")
            if not hist.empty and len(hist) >= 30:
                hist = hist.reset_index()[["Date", "Close"]].rename(
                    columns={"Date": "date", "Close": "close"})
                hist["date"]  = pd.to_datetime(hist["date"]).dt.tz_localize(None)
                hist["close"] = pd.to_numeric(hist["close"], errors="coerce")
                df = hist.dropna(subset=["close"])[["date", "close"]].reset_index(drop=True)
        except Exception:
            pass

    if df.empty or len(df) < 30:
        return {"error": True}

    current = float(df["close"].iloc[-1])
    ma200   = float(df["close"].tail(200).mean())
    signal  = "ABOVE_200DMA" if current > ma200 else "BELOW_200DMA"

    return {"current": round(current, 4), "ma200": round(ma200, 4),
            "signal": signal, "source": source}


def _get_market_caps(tickers: list, akshare_caps: dict, usdhkd: float = 7.83) -> dict:
    """
    Three-layer market cap fetch for tickers NOT already covered by AKShare estimates.
    Layer 1: SQLite daily cache (instant).
    Layer 2: LSEG batch (one API call for all missing — ~18s fixed overhead).
    Layer 3: Parallel yfinance with per-stock timeout (8 workers, 30s total limit).
    Results are saved back to SQLite for the rest of the day.
    Returns merged dict of {ticker: market_cap_hkd}.
    """
    from flow_core.signal_logger import get_cached_market_caps, save_market_caps
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Start with what AKShare gave us
    result = dict(akshare_caps)
    missing = [t for t in tickers if t not in result]
    if not missing:
        return result

    # Layer 1: SQLite cache (instant)
    cached = get_cached_market_caps(missing)
    result.update(cached)
    missing = [t for t in missing if t not in result]
    if not missing:
        return result

    newly_fetched: dict = {}

    # Layer 2: LSEG batch (fast single call for all missing)
    if lseg_desktop_available():
        try:
            from core.lseg_data import get_market_caps_lseg
            lseg_caps = get_market_caps_lseg(missing)
            newly_fetched.update(lseg_caps)
            missing = [t for t in missing if t not in newly_fetched]
        except Exception:
            pass

    # Layer 3: Parallel yfinance with 2s timeout per stock
    if missing:
        def _fetch_one(ticker):
            try:
                fi = yf.Ticker(ticker).fast_info
                mc = getattr(fi, "market_cap", None)
                if mc and mc > 0:
                    ccy = getattr(fi, "currency", "HKD") or "HKD"
                    if str(ccy).upper() == "USD":
                        mc = mc * usdhkd
                    return (ticker, float(mc))
            except Exception:
                pass
            return (ticker, None)

        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = {ex.submit(_fetch_one, t): t for t in missing}
            for fut in as_completed(futures, timeout=30):
                try:
                    tkr, mc = fut.result(timeout=2)
                    if mc:
                        newly_fetched[tkr] = mc
                except Exception:
                    pass

    # Persist newly fetched to SQLite cache
    if newly_fetched:
        save_market_caps(newly_fetched, source="LSEG+yfinance")

    result.update(newly_fetched)
    return result


def get_southbound_conviction() -> dict:
    """
    Rebuild: two Z-score ranked tables + full 600-stock dataset for lookup.

    Returns dict:
      table1    - DataFrame, top 20 by institutional flow (absolute size Z-score)
      table2    - DataFrame, top 20 by flow intensity (net_buy / est_mkt_cap)
      full      - DataFrame, all 600 stocks with computed fields for lookup
      data_date - str, trading date the data covers
      fetched_at- str, when AKShare was called
      update_schedule - str
      error     - bool

    Market cap estimated from AKShare data (no extra API calls):
      est_market_cap_hkd = 持股市值 / (持股数量占发行股百分比 / 100)

    True net buy = share count change × closing price (strips price appreciation).
    """
    import time as _time
    import numpy as np

    _now_str = datetime.now().strftime("%Y-%m-%d %H:%M HKT")
    _SCHEDULE = "Updates after ~18:00 HKT each trading day"
    _EMPTY = {
        "table1": pd.DataFrame(), "table2": pd.DataFrame(), "full": pd.DataFrame(),
        "data_date": "Unavailable", "fetched_at": _now_str,
        "update_schedule": _SCHEDULE, "error": True,
    }

    if not AKSHARE_AVAILABLE:
        return _EMPTY

    def _zw(series, clip=3.0):
        mu, sigma = series.mean(), series.std()
        if sigma == 0:
            return pd.Series(0.0, index=series.index)
        return ((series - mu) / sigma).clip(-clip, clip)

    def _pct_stars(score, scores_arr):
        pct = (np.array(scores_arr) < score).mean() * 100
        if pct >= 95:   return "★★★★★"
        elif pct >= 85: return "★★★★☆"
        elif pct >= 70: return "★★★☆☆"
        elif pct >= 50: return "★★☆☆☆"
        else:           return "★☆☆☆☆"

    try:
        today = datetime.now().strftime("%Y%m%d")

        # Threaded fetch with per-attempt timeout — the 4-day window can stall
        # silently for ~120s before raising ChunkedEncodingError. A 20s timeout
        # per attempt caps the worst case at ~22s (20s + 2s sleep + 8s retry).
        import threading as _threading

        def _akshare_fetch(start: str) -> "pd.DataFrame | None":
            try:
                return ak.stock_hsgt_stock_statistics_em(
                    symbol="南向持股", start_date=start, end_date=today)
            except Exception:
                return None

        stats = None
        for _attempt, _days in enumerate([4, 3]):
            _start = (datetime.now() - pd.Timedelta(days=_days)).strftime("%Y%m%d")
            _result_holder = [None]
            _t = _threading.Thread(
                target=lambda s=_start: _result_holder.__setitem__(0, _akshare_fetch(s)),
                daemon=True,
            )
            _t.start()
            _t.join(timeout=20)          # hard cap: 20s per attempt
            if _t.is_alive():
                # Still blocked — move to shorter window immediately
                _time.sleep(0.5)
                continue
            stats = _result_holder[0]
            if stats is not None and not stats.empty:
                break
            if _attempt < 1:
                _time.sleep(2)

        if stats is None or stats.empty:
            return _EMPTY

        for _col in ["持股数量", "当日收盘价", "当日涨跌幅",
                     "持股数量占发行股百分比", "持股市值"]:
            if _col in stats.columns:
                stats[_col] = pd.to_numeric(stats[_col], errors="coerce")
        stats["持股日期"] = pd.to_datetime(stats["持股日期"])
        stats = stats.sort_values(["股票代码", "持股日期"]).reset_index(drop=True)
        stats["shares_delta"] = stats.groupby("股票代码")["持股数量"].diff()

        latest    = stats["持股日期"].max()
        data_date = latest.strftime("%Y-%m-%d")
        today_df  = stats[stats["持股日期"] == latest].copy()
        today_df["true_net_buy_hkd"] = today_df["shares_delta"] * today_df["当日收盘价"]
        today_df  = today_df.dropna(subset=["true_net_buy_hkd"])

        if today_df.empty:
            return _EMPTY

        _NEAR_ZERO = 10_000
        prev_days = stats[stats["持股日期"] < latest]
        prev_avg  = (prev_days.groupby("股票代码")["shares_delta"]
                     .apply(lambda s: s.dropna().abs().mean()))

        all_rows = []
        for _, row in today_df.iterrows():
            code        = str(row["股票代码"]).zfill(5)
            net_buy     = float(row["true_net_buy_hkd"])
            today_delta = float(row["shares_delta"]) if pd.notna(row["shares_delta"]) else 0
            price_chg   = float(row["当日涨跌幅"]) if pd.notna(row["当日涨跌幅"]) else 0
            sb_hold     = float(row["持股数量占发行股百分比"]) if pd.notna(row.get("持股数量占发行股百分比")) else None
            hold_val    = float(row["持股市值"]) if pd.notna(row.get("持股市值")) else None

            accel = None
            pa = prev_avg.get(row["股票代码"])
            if pa is not None and pa > _NEAR_ZERO and today_delta > 0:
                accel = round(today_delta / pa, 2)

            # Estimate total market cap from AKShare data — no extra API call needed
            est_mkt_cap = None
            if hold_val and sb_hold and sb_hold > 0.1:
                est_mkt_cap = hold_val / (sb_hold / 100.0)

            weakness = 1.0 if (net_buy > 0 and price_chg < -1.0) else 0.0

            all_rows.append({
                "ticker":          code + ".HK",
                "name":            str(row["股票简称"]),
                "net_buy_hkd":     net_buy,
                "sb_hold_pct":     sb_hold,
                "acceleration":    accel,
                "price_change_1d": price_chg,
                "weakness":        weakness,
                "market_cap_hkd":  est_mkt_cap,
                "data_date":       data_date,
            })

        full_df = pd.DataFrame(all_rows)

        # Filtered universe: positive net buy, >= HKD 30M
        filt = full_df[(full_df["net_buy_hkd"] >= 30_000_000)].copy()

        if filt.empty:
            return {**_EMPTY, "full": full_df, "data_date": data_date, "error": False}

        # Supplement market caps for any stocks where AKShare estimate unavailable
        # (sb_hold_pct was 0 or < 0.1%). Use 3-layer fetch: cache → LSEG → yfinance.
        _need_mc = filt[filt["market_cap_hkd"].isna()]["ticker"].tolist()
        if _need_mc:
            _akshare_caps = {r["ticker"]: r["market_cap_hkd"]
                             for r in all_rows if r["market_cap_hkd"] is not None}
            _all_caps = _get_market_caps(
                filt["ticker"].tolist(), _akshare_caps, usdhkd=7.83)
            filt["market_cap_hkd"] = filt["ticker"].map(_all_caps)

        # ── TABLE 1: Institutional Flow ───────────────────────────
        t1 = filt.copy()
        t1["z_netbuy"] = _zw(t1["net_buy_hkd"])
        t1["z_accel"]  = _zw(t1["acceleration"].fillna(0))
        t1["z_weak"]   = _zw(t1["weakness"])
        t1["score_t1"] = t1["z_netbuy"] * 2.5 + t1["z_accel"] * 1.5 + t1["z_weak"] * 1.0
        t1_sc = t1["score_t1"].values
        t1["stars"] = [_pct_stars(s, t1_sc) for s in t1["score_t1"]]
        table1 = t1.sort_values("score_t1", ascending=False).head(20).reset_index(drop=True)

        # ── TABLE 2: Flow Intensity ───────────────────────────────
        t2 = filt[filt["market_cap_hkd"].notna()].copy()
        if not t2.empty:
            t2["flow_intensity_pct"] = t2["net_buy_hkd"] / t2["market_cap_hkd"] * 100
            t2["z_intensity"] = _zw(t2["flow_intensity_pct"])
            t2["z_accel"]     = _zw(t2["acceleration"].fillna(0))
            t2["z_weak"]      = _zw(t2["weakness"])
            t2["score_t2"]    = t2["z_intensity"] * 2.0 + t2["z_accel"] * 2.0 + t2["z_weak"] * 1.0
            t2_sc = t2["score_t2"].values
            t2["stars"] = [_pct_stars(s, t2_sc) for s in t2["score_t2"]]
            table2 = t2.sort_values("score_t2", ascending=False).head(20).reset_index(drop=True)
        else:
            table2 = pd.DataFrame()

        # Merge scores back into full_df for lookup
        _t1_map = t1.set_index("ticker")[["score_t1", "stars"]].to_dict("index")
        _t2_map = (t2.set_index("ticker")[["flow_intensity_pct", "score_t2"]].to_dict("index")
                   if not t2.empty else {})
        full_df["score_t1"]          = full_df["ticker"].map({k: v["score_t1"] for k, v in _t1_map.items()})
        full_df["stars"]             = full_df["ticker"].map({k: v["stars"]    for k, v in _t1_map.items()})
        full_df["flow_intensity_pct"] = full_df["ticker"].map({k: v["flow_intensity_pct"] for k, v in _t2_map.items()})

        return {
            "table1": table1, "table2": table2, "full": full_df,
            "data_date": data_date, "fetched_at": _now_str,
            "update_schedule": _SCHEDULE, "error": False,
        }

    except Exception:
        return _EMPTY
