"""US Macro flow data fetchers. All functions return fallback data on error."""

import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import yfinance as yf
import os


def get_fred_client():
    """Return a configured fredapi.Fred client, or None if no key available."""
    api_key = os.environ.get("FRED_API_KEY", "")
    if not api_key:
        try:
            import streamlit as st
            api_key = st.secrets.get("FRED_API_KEY", "")
        except Exception:
            pass
    if api_key:
        try:
            from fredapi import Fred
            return Fred(api_key=api_key)
        except Exception:
            pass
    return None


def get_fed_expectations() -> dict:
    """Fed funds rate and market-implied cut probabilities."""
    fallback = {
        "current_rate": 4.33,
        "next_meeting_date": "2026-06-12",
        "prob_hold": 55.0,
        "prob_cut_25": 35.0,
        "prob_cut_50": 5.0,
        "prob_hike": 5.0,
        "_is_mock": True,
    }
    # Try FRED for current rate
    current_rate = None
    fred = get_fred_client()
    if fred:
        try:
            dff = fred.get_series("DFF", observation_start="2024-01-01")
            if not dff.empty:
                current_rate = float(dff.iloc[-1])
        except Exception:
            pass

    if current_rate is None:
        try:
            url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFF"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                lines = [l for l in resp.text.strip().split("\n") if l and not l.startswith("DATE")]
                if lines:
                    current_rate = float(lines[-1].split(",")[1])
        except Exception:
            pass

    # Try CME FedWatch (scrape probabilities)
    probs = _scrape_cme_fedwatch()

    result = fallback.copy()
    if current_rate is not None:
        result["current_rate"] = current_rate
        result.pop("_is_mock", None)
    if probs:
        result.update(probs)
        result.pop("_is_mock", None)

    return result


def _scrape_cme_fedwatch() -> dict:
    """Attempt to scrape CME FedWatch probabilities."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/html",
        }
        # Try CME API endpoint for FedWatch data
        url = "https://www.cmegroup.com/CmeWS/mvc/VideoBoard/BONDS"
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            # Parse if structure matches
            if isinstance(data, list) and data:
                return {}
    except Exception:
        pass
    return {}


def get_yield_curve() -> dict:
    """US Treasury yield curve via yfinance and FRED."""
    fallback = {
        "yield_2yr": 4.23,
        "yield_10yr": 4.41,
        "yield_30yr": 4.65,
        "spread_10_2": 0.18,
        "inverted": False,
        "signal": "NORMAL",
        "_is_mock": True,
    }
    try:
        # yfinance treasury tickers
        tickers = yf.download(["^IRX", "^FVX", "^TNX", "^TYX"], period="5d", progress=False, auto_adjust=True)
        if tickers.empty:
            raise ValueError("No yfinance data")

        close = tickers["Close"]
        if isinstance(close, pd.Series):
            raise ValueError("Unexpected series format")

        def _last(col_substr):
            col = next((c for c in close.columns if col_substr in str(c).upper()), None)
            if col:
                vals = close[col].dropna()
                return float(vals.iloc[-1]) if not vals.empty else None
            return None

        # ^IRX = 13-week, ^FVX = 5yr, ^TNX = 10yr, ^TYX = 30yr
        # Use FRED for accurate 2yr; ^FVX as fallback (5yr, not ideal)
        y2 = None  # Will be filled by FRED below
        y10 = _last("TNX")
        y30 = _last("TYX")

        # Try FRED for more accurate yields
        fred = get_fred_client()
        if fred:
            try:
                s2 = fred.get_series("DGS2", observation_start="2024-01-01")
                s10 = fred.get_series("DGS10", observation_start="2024-01-01")
                s30 = fred.get_series("DGS30", observation_start="2024-01-01")
                y2 = float(s2.dropna().iloc[-1]) if not s2.dropna().empty else y2
                y10 = float(s10.dropna().iloc[-1]) if not s10.dropna().empty else y10
                y30 = float(s30.dropna().iloc[-1]) if not s30.dropna().empty else y30
            except Exception:
                pass
        else:
            # Try FRED without key
            for series_id, attr in [("DGS2", "y2"), ("DGS10", "y10"), ("DGS30", "y30")]:
                try:
                    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
                    r = requests.get(url, timeout=8)
                    if r.status_code == 200:
                        lines = [l for l in r.text.strip().split("\n") if l and not l.startswith("DATE")]
                        # Get last non-empty value
                        for line in reversed(lines):
                            parts = line.split(",")
                            if len(parts) == 2 and parts[1].strip() not in (".", ""):
                                val = float(parts[1])
                                if attr == "y2":
                                    y2 = val
                                elif attr == "y10":
                                    y10 = val
                                else:
                                    y30 = val
                                break
                except Exception:
                    pass

        if y2 is None or y10 is None:
            return fallback

        y30 = y30 or fallback["yield_30yr"]
        spread = y10 - y2
        inverted = spread < 0

        if spread > 0.5:
            signal = "NORMAL"
        elif spread > -0.1:
            signal = "FLAT"
        else:
            signal = "INVERTED"

        return {
            "yield_2yr": round(y2, 3),
            "yield_10yr": round(y10, 3),
            "yield_30yr": round(y30, 3),
            "spread_10_2": round(spread, 3),
            "inverted": inverted,
            "signal": signal,
        }
    except Exception:
        return fallback


def get_vix() -> dict:
    """VIX fear index via yfinance."""
    fallback = {
        "vix": 14.2,
        "change_pct": 0.0,
        "signal": "CALM",
        "_is_mock": True,
    }
    try:
        data = yf.download("^VIX", period="5d", progress=False, auto_adjust=True)
        if data.empty:
            return fallback
        close_raw = data["Close"]
        if isinstance(close_raw, pd.DataFrame):
            # single ticker download returns df with one col
            col = next(iter(close_raw.columns), None)
            close = close_raw[col].dropna() if col else pd.Series(dtype=float)
        else:
            close = close_raw.dropna()
        if len(close) < 2:
            return fallback

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
    except Exception:
        return fallback


def get_etf_flows() -> list:
    """Key ETF price/volume data as market sentiment proxy."""
    etf_meta = {
        "SPY": "S&P 500",
        "QQQ": "Nasdaq 100",
        "GLD": "Gold",
        "TLT": "Long Bonds",
        "FXI": "China Large Cap",
        "KWEB": "China Tech",
        "EEM": "Emerging Markets",
    }
    fallback = [
        {"ticker": t, "name": n, "price": 0.0, "change_pct_1d": 0.0,
         "change_pct_5d": 0.0, "volume_ratio": 1.0, "_is_mock": True}
        for t, n in etf_meta.items()
    ]
    try:
        tickers_list = list(etf_meta.keys())
        data = yf.download(
            tickers_list, period="30d", progress=False, auto_adjust=True
        )
        if data.empty:
            return fallback

        close = data["Close"]
        volume = data["Volume"]

        results = []
        for ticker in tickers_list:
            try:
                if ticker not in close.columns:
                    continue
                c = close[ticker].dropna()
                v = volume[ticker].dropna()

                if len(c) < 6:
                    results.append({
                        "ticker": ticker, "name": etf_meta[ticker],
                        "price": 0.0, "change_pct_1d": 0.0,
                        "change_pct_5d": 0.0, "volume_ratio": 1.0, "_is_mock": True
                    })
                    continue

                price = float(c.iloc[-1])
                change_1d = (float(c.iloc[-1]) - float(c.iloc[-2])) / float(c.iloc[-2]) * 100
                change_5d = (float(c.iloc[-1]) - float(c.iloc[-6])) / float(c.iloc[-6]) * 100

                vol_20d_avg = float(v.iloc[:-1].tail(20).mean()) if len(v) > 20 else float(v.mean())
                vol_today = float(v.iloc[-1])
                vol_ratio = vol_today / vol_20d_avg if vol_20d_avg > 0 else 1.0

                results.append({
                    "ticker": ticker,
                    "name": etf_meta[ticker],
                    "price": round(price, 2),
                    "change_pct_1d": round(change_1d, 2),
                    "change_pct_5d": round(change_5d, 2),
                    "volume_ratio": round(vol_ratio, 2),
                })
            except Exception:
                results.append({
                    "ticker": ticker, "name": etf_meta[ticker],
                    "price": 0.0, "change_pct_1d": 0.0,
                    "change_pct_5d": 0.0, "volume_ratio": 1.0, "_is_mock": True
                })

        return results if results else fallback

    except Exception:
        return fallback
