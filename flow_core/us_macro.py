"""US Macro flow data fetchers. Returns error dict/empty on failure — never fake data."""

import requests
import pandas as pd
from datetime import datetime
import yfinance as yf
import os


def _get_fred_key() -> str:
    key = os.environ.get("FRED_API_KEY", "")
    if not key:
        try:
            import streamlit as st
            key = st.secrets.get("FRED_API_KEY", "")
        except Exception:
            pass
    return key


def _fred_csv_last(series_id: str):
    """Fetch last non-missing value from FRED CSV without API key. Returns float or None."""
    try:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            lines = [l for l in r.text.strip().split("\n") if l and not l.startswith("DATE")]
            for line in reversed(lines):
                parts = line.split(",")
                if len(parts) == 2 and parts[1].strip() not in (".", ""):
                    return float(parts[1])
    except Exception:
        pass
    return None


def get_fred_client():
    """Return a configured fredapi.Fred client, or None if no key available."""
    api_key = _get_fred_key()
    if api_key:
        try:
            from fredapi import Fred
            return Fred(api_key=api_key)
        except Exception:
            pass
    return None


def get_fed_expectations() -> dict:
    """Fed funds rate. Returns {"error": True} if FRED unavailable."""
    current_rate = None
    fred = get_fred_client()
    if fred:
        try:
            dff = fred.get_series("DFF", observation_start="2024-01-01")
            if not dff.empty:
                current_rate = float(dff.dropna().iloc[-1])
        except Exception:
            pass

    if current_rate is None:
        current_rate = _fred_csv_last("DFF")

    if current_rate is None:
        return {"error": True, "error_msg": "FRED DFF unavailable"}

    result = {"current_rate": current_rate}
    probs = _scrape_cme_fedwatch()
    if probs:
        result.update(probs)
    return result


def _scrape_cme_fedwatch() -> dict:
    """Attempt CME FedWatch probability scrape. Returns {} on failure."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/html",
        }
        url = "https://www.cmegroup.com/CmeWS/mvc/VideoBoard/BONDS"
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and data:
                return {}
    except Exception:
        pass
    return {}


def get_yield_curve() -> dict:
    """
    US Treasury yields from FRED: DGS2, DGS5, DGS10, DGS30, DFII10 (real yield).
    Returns {"error": True} if core yields unavailable — never simulated.
    """
    series_map = {
        "yield_2yr":      "DGS2",
        "yield_5yr":      "DGS5",
        "yield_10yr":     "DGS10",
        "yield_30yr":     "DGS30",
        "real_yield_10yr": "DFII10",
    }
    fetched = {}
    fred = get_fred_client()

    for field, sid in series_map.items():
        val = None
        if fred:
            try:
                s = fred.get_series(sid, observation_start="2024-01-01").dropna()
                if not s.empty:
                    val = float(s.iloc[-1])
            except Exception:
                pass
        if val is None:
            val = _fred_csv_last(sid)
        fetched[field] = val

    y2 = fetched.get("yield_2yr")
    y10 = fetched.get("yield_10yr")

    if y2 is None or y10 is None:
        return {"error": True, "error_msg": "FRED Treasury yields unavailable", **fetched}

    y30 = fetched.get("yield_30yr")
    spread = y10 - y2
    inverted = spread < 0

    if spread > 0.5:
        signal = "NORMAL"
    elif spread > -0.1:
        signal = "FLAT"
    else:
        signal = "INVERTED"

    return {
        "yield_2yr":       round(y2, 3),
        "yield_5yr":       round(fetched["yield_5yr"], 3) if fetched.get("yield_5yr") is not None else None,
        "yield_10yr":      round(y10, 3),
        "yield_30yr":      round(y30, 3) if y30 is not None else None,
        "real_yield_10yr": round(fetched["real_yield_10yr"], 3) if fetched.get("real_yield_10yr") is not None else None,
        "spread_10_2":     round(spread, 3),
        "inverted":        inverted,
        "signal":          signal,
    }


def get_vix() -> dict:
    """VIX fear index via yfinance. Returns {"error": True} on failure."""
    try:
        data = yf.download("^VIX", period="5d", progress=False, auto_adjust=True)
        if data.empty:
            return {"error": True, "error_msg": "yfinance VIX unavailable"}
        close_raw = data["Close"]
        if isinstance(close_raw, pd.DataFrame):
            col = next(iter(close_raw.columns), None)
            close = close_raw[col].dropna() if col else pd.Series(dtype=float)
        else:
            close = close_raw.dropna()
        if len(close) < 2:
            return {"error": True, "error_msg": "Insufficient VIX data"}

        vix_now = float(close.iloc[-1].item() if hasattr(close.iloc[-1], "item") else close.iloc[-1])
        vix_prev = float(close.iloc[-2].item() if hasattr(close.iloc[-2], "item") else close.iloc[-2])
        change_pct = (vix_now - vix_prev) / vix_prev * 100

        if vix_now < 15:
            signal = "CALM"
        elif vix_now < 20:
            signal = "ELEVATED"
        elif vix_now < 30:
            signal = "FEAR"
        else:
            signal = "PANIC"

        return {
            "vix": round(vix_now, 2),
            "change_pct": round(change_pct, 2),
            "signal": signal,
        }
    except Exception as e:
        return {"error": True, "error_msg": str(e)}


def get_etf_flows() -> list:
    """
    Key ETF price/volume data via yfinance.
    Uses period='10d' for reliable close prices and 5d change calculation.
    Returns [] on failure — never fake prices.
    """
    etf_meta = {
        "SPY":  "S&P 500",
        "QQQ":  "Nasdaq 100",
        "GLD":  "Gold",
        "TLT":  "Long Bonds",
        "FXI":  "China Large Cap",
        "KWEB": "China Tech",
        "EEM":  "Emerging Markets",
    }
    tickers_list = list(etf_meta.keys())

    try:
        data = yf.download(tickers_list, period="10d", progress=False, auto_adjust=True)
        if data.empty:
            return []

        close = data["Close"]
        volume = data["Volume"]

        # Flatten MultiIndex if present (yfinance sometimes returns (field, ticker) tuples)
        if isinstance(close.columns, pd.MultiIndex):
            close = close.droplevel(0, axis=1)
            volume = volume.droplevel(0, axis=1)

        results = []
        for ticker in tickers_list:
            if ticker not in close.columns:
                continue
            try:
                c = close[ticker].dropna()
                v = volume[ticker].dropna()

                if len(c) < 2:
                    continue

                price = float(c.iloc[-1])
                if price == 0.0:
                    continue

                change_1d = (float(c.iloc[-1]) - float(c.iloc[-2])) / float(c.iloc[-2]) * 100

                if len(c) >= 6:
                    change_5d = (float(c.iloc[-1]) - float(c.iloc[-6])) / float(c.iloc[-6]) * 100
                else:
                    change_5d = None

                vol_20d_avg = float(v.iloc[:-1].tail(20).mean()) if len(v) > 1 else float(v.mean())
                vol_today = float(v.iloc[-1])
                vol_ratio = vol_today / vol_20d_avg if vol_20d_avg > 0 else 1.0

                results.append({
                    "ticker":        ticker,
                    "name":          etf_meta[ticker],
                    "price":         round(price, 2),
                    "change_pct_1d": round(change_1d, 2),
                    "change_pct_5d": round(change_5d, 2) if change_5d is not None else None,
                    "volume_ratio":  round(vol_ratio, 2),
                })
            except Exception:
                continue

        return results

    except Exception:
        return []
