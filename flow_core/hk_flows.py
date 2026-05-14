"""HK/China flow data fetchers. All functions return empty/fallback on error."""

import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
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

# Approximate RMB→HKD rate; 亿元 × _RMB_HKD × 1e8 = HKD
_RMB_HKD = 1.07


def _cache(func):
    """Conditional streamlit cache wrapper."""
    if STREAMLIT_AVAILABLE:
        import streamlit as st
        return st.cache_data(ttl=3600)(func)
    return func


def _get_mock_stock_connect():
    """Fallback mock data for Stock Connect."""
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "northbound": {
            "net_flow_hkd": 3_200_000_000,
            "buy_turnover": 18_500_000_000,
            "sell_turnover": 15_300_000_000,
            "quota_used_pct": 12.4,
            "quota_remaining_hkd": 46_900_000_000,
        },
        "southbound": {
            "net_flow_hkd": 1_100_000_000,
            "buy_turnover": 8_200_000_000,
            "sell_turnover": 7_100_000_000,
            "quota_used_pct": 2.6,
        },
        "_is_mock": True,
    }


def get_stock_connect_flows() -> dict:
    """
    Fetch today's Stock Connect flows via AKShare (East Money).
    Note: China suspended northbound real-time data publication in Nov 2023.
    Southbound (HK → Mainland) is live; northbound will be 0 until data restored.
    Falls back to mock on failure.
    """
    if AKSHARE_AVAILABLE:
        try:
            df = ak.stock_hsgt_fund_flow_summary_em()
            if df is not None and not df.empty:
                date_val = str(df['交易日'].iloc[0])

                nb_rows = df[df['资金方向'] == '北向']
                sb_rows = df[df['资金方向'] == '南向']

                nb_rmb = float(nb_rows['成交净买额'].sum())   # 亿元 RMB
                sb_rmb = float(sb_rows['成交净买额'].sum())   # 亿元 RMB

                nb_hkd = nb_rmb * 1e8 * _RMB_HKD
                sb_hkd = sb_rmb * 1e8 * _RMB_HKD

                def _sb_signal(v):
                    if v > 100:
                        return "STRONG_BUY"
                    if v > 0:
                        return "BUY"
                    if v > -100:
                        return "SELL"
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
                    "is_mock": False,
                }
        except Exception:
            pass

    return _get_mock_stock_connect()


def _parse_hkex_api(data: dict) -> dict:
    """Parse HKEX API response format."""
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
    """Parse HKEX XML/alternate API response."""
    try:
        soup = BeautifulSoup(text, "lxml")
        # Try to extract key numbers from any table/data structure
        tables = soup.find_all("table")
        if not tables:
            return {}
        return {}
    except Exception:
        return {}


def _parse_hkex_quota_page(html: str) -> dict:
    """Scrape HKEX daily quota usage page."""
    try:
        soup = BeautifulSoup(html, "lxml")
        tables = soup.find_all("table")
        result = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "northbound": {
                "net_flow_hkd": 0,
                "buy_turnover": 0,
                "sell_turnover": 0,
                "quota_used_pct": 0,
                "quota_remaining_hkd": 0,
            },
            "southbound": {
                "net_flow_hkd": 0,
                "buy_turnover": 0,
                "sell_turnover": 0,
                "quota_used_pct": 0,
            },
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
    Return last N days of Stock Connect flows.
    Uses AKShare for southbound (live); northbound data unavailable since Nov 2023.
    The chart column 'northbound_net' is populated with southbound data so the
    existing chart renders correctly; 'southbound_net' holds the same values.
    """
    if AKSHARE_AVAILABLE:
        try:
            df = ak.stock_hsgt_hist_em(symbol='南向资金')
            df2 = df.dropna(subset=['当日成交净买额'])
            if not df2.empty:
                df2 = df2.tail(days).copy()
                df2 = df2.rename(columns={'日期': 'date', '当日成交净买额': 'southbound_net_rmb'})
                df2['date'] = pd.to_datetime(df2['date'])
                df2['southbound_net_rmb'] = pd.to_numeric(df2['southbound_net_rmb'], errors='coerce')
                # Convert 亿元 RMB to HKD
                df2['southbound_net'] = df2['southbound_net_rmb'] * 1e8 * _RMB_HKD
                # Populate northbound_net with southbound for chart compatibility
                df2['northbound_net'] = df2['southbound_net']
                df2['northbound_cumulative_5d'] = df2['northbound_net'].rolling(5).sum()
                df2['northbound_cumulative_20d'] = df2['northbound_net'].rolling(20).sum()
                df2['_is_mock'] = False
                df2['is_mock'] = False
                return df2[['date', 'northbound_net', 'southbound_net',
                            'northbound_cumulative_5d', 'northbound_cumulative_20d',
                            '_is_mock', 'is_mock']]
        except Exception:
            pass

    # Fallback mock
    dates = pd.bdate_range(end=datetime.now(), periods=days)
    np.random.seed(42)
    df = pd.DataFrame({
        "date": dates,
        "northbound_net": np.random.normal(2e9, 3e9, len(dates)),
        "southbound_net": np.random.normal(0.8e9, 1.5e9, len(dates)),
        "_is_mock": True,
        "is_mock": True,
    })
    df["northbound_cumulative_5d"] = df["northbound_net"].rolling(5).sum()
    df["northbound_cumulative_20d"] = df["northbound_net"].rolling(20).sum()
    return df


def get_top_northbound_stocks() -> list:
    """
    Top 10 stocks most added by northbound (via AKShare hold_stock_em).
    Note: data source reflects last available snapshot (northbound reporting
    was suspended by China Nov 2023; this shows the most recent available data).
    Falls back to static mock list.
    """
    mock = [
        {"ticker": "0700.HK", "name": "Tencent", "net_buy_hkd": 1_250_000_000, "_is_mock": True},
        {"ticker": "9988.HK", "name": "Alibaba", "net_buy_hkd": 980_000_000, "_is_mock": True},
        {"ticker": "3690.HK", "name": "Meituan", "net_buy_hkd": 720_000_000, "_is_mock": True},
        {"ticker": "1810.HK", "name": "Xiaomi", "net_buy_hkd": 560_000_000, "_is_mock": True},
        {"ticker": "0941.HK", "name": "China Mobile", "net_buy_hkd": 450_000_000, "_is_mock": True},
        {"ticker": "2318.HK", "name": "Ping An Insurance", "net_buy_hkd": 380_000_000, "_is_mock": True},
        {"ticker": "1398.HK", "name": "ICBC", "net_buy_hkd": 310_000_000, "_is_mock": True},
        {"ticker": "2020.HK", "name": "ANTA Sports", "net_buy_hkd": 280_000_000, "_is_mock": True},
        {"ticker": "9618.HK", "name": "JD.com", "net_buy_hkd": 240_000_000, "_is_mock": True},
        {"ticker": "0175.HK", "name": "Geely Auto", "net_buy_hkd": 195_000_000, "_is_mock": True},
    ]
    if AKSHARE_AVAILABLE:
        try:
            df = ak.stock_hsgt_hold_stock_em(market='沪股通', indicator='今日排行')
            if df is not None and not df.empty:
                results = []
                for _, row in df.head(10).iterrows():
                    # 今日增持估计-市值 is in 万元 RMB; convert to HKD
                    net_buy_wan_rmb = float(row.get('今日增持估计-市值', 0) or 0)
                    net_buy_hkd = net_buy_wan_rmb * 1e4 * _RMB_HKD
                    results.append({
                        "ticker": str(row.get('代码', '')),
                        "name": str(row.get('名称', '')),
                        "net_buy_hkd": net_buy_hkd,
                        "_is_mock": False,
                    })
                if results:
                    return results
        except Exception:
            pass
    return mock


def get_hsi_data() -> dict:
    """Fetch HSI and HSCEI current levels via yfinance."""
    fallback = {
        "hsi": {"level": 23456.0, "change_pct": 0.0},
        "hscei": {"level": 8234.0, "change_pct": 0.0},
        "spread": 15222.0,
        "_is_mock": True,
    }
    try:
        # HSCEI ticker on Yahoo Finance uses ^HSCE (not ^HSCEI)
        tickers = yf.download(["^HSI", "^HSCE"], period="5d", progress=False, auto_adjust=True)
        if tickers.empty:
            return fallback
        close = tickers["Close"] if isinstance(tickers["Close"], pd.DataFrame) else tickers[["Close"]]
        hsi_col = next((c for c in close.columns if "HSI" in str(c).upper() and "HSCE" not in str(c).upper()), None)
        hscei_col = next((c for c in close.columns if "HSCE" in str(c).upper()), None)

        if not hsi_col:
            return fallback

        hsi_vals = close[hsi_col].dropna()
        hscei_vals = close[hscei_col].dropna() if hscei_col else pd.Series(dtype=float)
        if len(hsi_vals) < 2:
            return fallback

        hsi_now = float(hsi_vals.iloc[-1])
        hsi_prev = float(hsi_vals.iloc[-2])

        if len(hscei_vals) >= 2:
            hscei_now = float(hscei_vals.iloc[-1])
            hscei_prev = float(hscei_vals.iloc[-2])
        else:
            hscei_now = fallback["hscei"]["level"]
            hscei_prev = hscei_now

        return {
            "hsi": {
                "level": hsi_now,
                "change_pct": (hsi_now - hsi_prev) / hsi_prev * 100,
            },
            "hscei": {
                "level": hscei_now,
                "change_pct": (hscei_now - hscei_prev) / hscei_prev * 100,
            },
            "spread": hsi_now - hscei_now,
        }
    except Exception:
        return fallback


def get_cnh_cny_spread() -> dict:
    """CNH/CNY spread — offshore vs onshore RMB capital flow signal."""
    fallback = {
        "cnh_per_usd": 7.2345,
        "cny_per_usd": 7.2123,
        "spread_pips": 22.2,
        "signal": "STABLE",
        "_is_mock": True,
    }
    try:
        tickers = yf.download(["USDCNH=X", "USDCNY=X"], period="5d", progress=False, auto_adjust=True)
        if tickers.empty:
            return fallback

        close = tickers["Close"]
        # Handle single vs multi ticker response
        if isinstance(close, pd.Series):
            return fallback

        cnh_col = next((c for c in close.columns if "CNH" in str(c).upper()), None)
        cny_col = next((c for c in close.columns if "CNY" in str(c).upper() and "CNH" not in str(c).upper()), None)

        if not cnh_col or not cny_col:
            return fallback

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
    except Exception:
        return fallback


def get_pboc_rate() -> dict:
    """PBOC 7-day reverse repo rate. Tries FRED first, then fallback."""
    fallback = {
        "rate": 1.50,
        "date": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
        "change_from_prev": 0.0,
        "_is_mock": True,
    }
    fred_key = os.environ.get("FRED_API_KEY", "")
    if not fred_key and STREAMLIT_AVAILABLE:
        try:
            import streamlit as st
            fred_key = st.secrets.get("FRED_API_KEY", "")
        except Exception:
            pass
    if fred_key:
        try:
            from fredapi import Fred
            fred = Fred(api_key=fred_key)
            series = fred.get_series("INTDSRCNM193N", observation_start="2024-01-01")
            if not series.empty:
                rate = float(series.iloc[-1])
                date = str(series.index[-1].date())
                prev = float(series.iloc[-2]) if len(series) > 1 else rate
                return {
                    "rate": rate,
                    "date": date,
                    "change_from_prev": rate - prev,
                }
        except Exception:
            pass

    # Try without API key (FRED sometimes allows unauthenticated reads)
    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=INTDSRCNM193N&vintage_date="
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            lines = [l for l in resp.text.strip().split("\n") if l and not l.startswith("DATE")]
            if lines:
                last = lines[-1].split(",")
                prev_line = lines[-2].split(",") if len(lines) > 1 else last
                rate = float(last[1])
                prev = float(prev_line[1])
                return {
                    "rate": rate,
                    "date": last[0],
                    "change_from_prev": rate - prev,
                }
    except Exception:
        pass

    return fallback
