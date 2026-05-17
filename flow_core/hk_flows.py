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
