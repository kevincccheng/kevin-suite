"""US Radar data fetching — all Module A signals for the US Capital Allocation Radar."""

import yfinance as yf
import pandas as pd
import requests
import os
from datetime import datetime


def get_spy_qqq_200dma() -> dict:
    try:
        result = {}
        for ticker in ['SPY', 'QQQ']:
            hist = yf.Ticker(ticker).history(period='250d')
            if hist.empty:
                continue
            close = hist['Close']
            ma200 = close.rolling(200).mean()
            current = close.iloc[-1]
            ma = ma200.iloc[-1]
            slope = ma200.diff().iloc[-5:].mean()
            pct_above = (current - ma) / ma * 100
            result[ticker] = {
                "price": round(current, 2),
                "ma200": round(ma, 2),
                "pct_above_200dma": round(pct_above, 2),
                "slope": round(slope, 4),
                "trend": "ABOVE" if current > ma else "BELOW",
                "slope_dir": "RISING" if slope > 0 else "FALLING"
            }
        result["source"] = "yfinance"
        result["fetched_at"] = datetime.now().strftime('%Y-%m-%d %H:%M HKT')
        return result
    except Exception:
        return {"error": True}


def get_market_breadth() -> dict:
    """RSP (equal weight) vs SPY (cap weight) ratio.
    Rising ratio = broad market participation, falling = narrow/concentrated."""
    try:
        rsp = yf.Ticker('RSP').history(period='30d')['Close']
        spy = yf.Ticker('SPY').history(period='30d')['Close']
        ratio_today = rsp.iloc[-1] / spy.iloc[-1]
        ratio_30d_ago = rsp.iloc[0] / spy.iloc[0]
        trend = "IMPROVING" if ratio_today > ratio_30d_ago else "DETERIORATING"
        pct_change = (ratio_today - ratio_30d_ago) / ratio_30d_ago * 100

        if trend == "IMPROVING" and pct_change > 1:
            signal = "BROAD"
        elif trend == "DETERIORATING" and pct_change < -2:
            signal = "NARROW"
        else:
            signal = "MIXED"

        return {
            "ratio": round(ratio_today, 4),
            "trend": trend,
            "pct_change_30d": round(pct_change, 2),
            "signal": signal,
            "source": "yfinance",
            "note": "RSP/SPY ratio — rising = broad market"
        }
    except Exception:
        return {"error": True}


def get_credit_spread() -> dict:
    """HYG (high yield) vs LQD (investment grade) as credit stress proxy."""
    try:
        hyg = yf.Ticker('HYG').history(period='30d')['Close']
        lqd = yf.Ticker('LQD').history(period='30d')['Close']
        ratio_today = hyg.iloc[-1] / lqd.iloc[-1]
        ratio_30d_ago = hyg.iloc[0] / lqd.iloc[0]
        trend = "TIGHTENING" if ratio_today > ratio_30d_ago else "WIDENING"

        if trend == "TIGHTENING":
            signal = "STABLE"
        elif ratio_today < ratio_30d_ago * 0.98:
            signal = "STRESS"
        else:
            signal = "WATCH"

        return {
            "hyg_lqd_ratio": round(ratio_today, 4),
            "trend": trend,
            "signal": signal,
            "hyg": round(hyg.iloc[-1], 2),
            "lqd": round(lqd.iloc[-1], 2),
            "source": "yfinance",
            "note": "HYG/LQD ratio proxy — falling = credit stress"
        }
    except Exception:
        return {"error": True}


def get_cboe_putcall() -> dict:
    """Fetch CBOE equity put/call ratio from daily statistics page."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(
            'https://www.cboe.com/us/options/market_statistics/daily/',
            headers=headers, timeout=10
        )
        if r.status_code != 200:
            raise Exception(f"HTTP {r.status_code}")

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, 'html.parser')

        tables = soup.find_all('table')
        putcall = None
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all('td')
                text = ' '.join(c.text.strip() for c in cells)
                if 'Equity' in text and putcall is None:
                    import re
                    nums = re.findall(r'\d+\.\d+', text)
                    if nums:
                        putcall = float(nums[-1])

        if putcall:
            signal = ("FEAR" if putcall > 1.0 else
                      "ELEVATED" if putcall > 0.8 else
                      "NEUTRAL" if putcall > 0.6 else "GREED")
            return {
                "equity_putcall": putcall,
                "signal": signal,
                "source": "CBOE",
                "note": ">1.0=fear, <0.6=greed"
            }
        else:
            raise Exception("Could not parse put/call ratio")
    except Exception as e:
        return {
            "equity_putcall": None,
            "signal": "UNAVAILABLE",
            "error_msg": str(e),
            "source": "CBOE",
            "note": "Parsing failed — check CBOE page structure"
        }


def get_us_regime_data() -> dict:
    """Master fetch function for all Module A signals."""
    from flow_core.us_macro import (
        get_vix, get_yield_curve, get_fed_expectations,
        get_dxy, get_etf_flows
    )

    return {
        "spy_qqq":     get_spy_qqq_200dma(),
        "breadth":     get_market_breadth(),
        "credit":      get_credit_spread(),
        "putcall":     get_cboe_putcall(),
        "vix":         get_vix(),
        "yield_curve": get_yield_curve(),
        "fed":         get_fed_expectations(),
        "dxy":         get_dxy(),
        "etfs":        get_etf_flows(),
        "fetched_at":  datetime.now().strftime('%Y-%m-%d %H:%M HKT')
    }
