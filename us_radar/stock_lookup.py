"""US stock signal lookup — yfinance + LSEG + SEC EDGAR."""

import sys
import os
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# RIC map for common tickers (NASDAQ .O, NYSE .N)
_RIC_MAP = {
    "NVDA": "NVDA.O", "TSLA": "TSLA.O", "AAPL": "AAPL.O",
    "MSFT": "MSFT.O", "GOOGL": "GOOGL.O", "AMZN": "AMZN.O",
    "META": "META.O", "AVGO": "AVGO.O", "AMD": "AMD.O",
    "PLTR": "PLTR.N", "APP": "APP.O", "RKLB": "RKLB.O",
    "ASTS": "ASTS.O", "OKLO": "OKLO.N", "SMR": "SMR.N",
    "NRG": "NRG.N", "VST": "VST.N", "CEG": "CEG.N",
    "CRDO": "CRDO.O", "ALAB": "ALAB.O", "ARM": "ARM.O",
    "MRVL": "MRVL.O", "HIMS": "HIMS.N", "HOOD": "HOOD.O",
    "SMCI": "SMCI.O", "PL": "PL.N", "SPIR": "SPIR.O",
    "ACHR": "ACHR.N", "JOBY": "JOBY.N", "RXRX": "RXRX.O",
    "VOO": "VOO.A", "QQQ": "QQQ.O", "SPY": "SPY.N",
}


def _safe_float(val) -> "float | None":
    if val is None:
        return None
    s = str(val)
    if s in ("<NA>", "nan", "None", ""):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def get_stock_signals(ticker: str) -> dict:
    ticker = ticker.upper().strip()
    result = {
        "ticker":  ticker,
        "as_of":   datetime.now().strftime('%Y-%m-%d %H:%M HKT'),
        "error":   False,
    }

    # === SIGNAL 1: Price, trend, range (yfinance) ===
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period='252d')
        if hist.empty:
            result["error"] = True
            result["error_msg"] = f"{ticker} not found on yfinance"
            return result

        info = t.info
        close  = hist['Close']
        volume = hist['Volume']
        high   = hist['High']
        low    = hist['Low']

        current  = float(close.iloc[-1])
        ma50     = float(close.rolling(50).mean().iloc[-1])
        ma200    = float(close.rolling(200).mean().iloc[-1])

        week_52_high   = float(close.max())
        week_52_low    = float(close.min())
        range_width    = week_52_high - week_52_low
        range_position = (current - week_52_low) / range_width * 100 if range_width > 0 else 50

        pct_vs_200 = (current - ma200) / ma200 * 100
        pct_vs_50  = (current - ma50)  / ma50  * 100

        today_high  = float(high.iloc[-1])
        today_low   = float(low.iloc[-1])
        today_range = today_high - today_low
        delivery    = (current - today_low) / today_range * 100 if today_range > 0 else 50

        result["price"] = {
            "current":            round(current, 2),
            "ma50":               round(ma50, 2),
            "ma200":              round(ma200, 2),
            "pct_vs_200dma":      round(pct_vs_200, 1),
            "pct_vs_50dma":       round(pct_vs_50, 1),
            "week_52_high":       round(week_52_high, 2),
            "week_52_low":        round(week_52_low, 2),
            "range_position_pct": round(range_position, 1),
            "price_delivery_pct": round(delivery, 1),
            "company_name":       info.get("longName", ticker),
            "sector":             info.get("sector", "Unknown"),
            "market_cap":         info.get("marketCap", None),
            "source":             "yfinance",
        }

        # === SIGNAL 2: Volume & accumulation ===
        vol_20d_avg = float(volume.iloc[-21:-1].mean())
        vol_today   = float(volume.iloc[-1])
        vol_ratio   = vol_today / vol_20d_avg if vol_20d_avg > 0 else 1.0

        recent_vol  = volume.iloc[-20:]
        persistence = int((recent_vol > vol_20d_avg * 1.5).sum())

        recent_close      = close.iloc[-20:]
        recent_close_prev = close.iloc[-21:-1]
        accum_days = sum(
            1 for i in range(len(recent_vol))
            if recent_vol.iloc[i] > vol_20d_avg * 1.2
            and i > 0
            and recent_close.iloc[i] > recent_close_prev.iloc[i]
        )

        result["volume"] = {
            "today":                   int(vol_today),
            "avg_20d":                 int(vol_20d_avg),
            "ratio":                   round(vol_ratio, 2),
            "persistence_20d":         persistence,
            "accumulation_days_20d":   accum_days,
            "signal": ("STRONG"   if vol_ratio > 2.0 else
                       "ELEVATED" if vol_ratio > 1.5 else
                       "NORMAL"   if vol_ratio > 0.8 else "LOW"),
            "source": "yfinance",
        }

        # === SIGNAL 3: Short interest proxy ===
        short_pct   = info.get("shortPercentOfFloat", None)
        short_ratio = info.get("shortRatio", None)
        sp_pct = round(short_pct * 100, 1) if short_pct is not None else None
        result["short_interest"] = {
            "pct_of_float":  sp_pct,
            "days_to_cover": round(float(short_ratio), 1) if short_ratio is not None else None,
            "signal": ("HIGH_SHORT" if short_pct and short_pct > 0.15 else
                       "MODERATE"   if short_pct and short_pct > 0.05 else "LOW"),
            "source": "yfinance",
            "note": "Point-in-time from yfinance — FINRA publishes bi-monthly updates",
        }

    except Exception as e:
        result["price"]          = {"error": True, "msg": str(e)}
        result["volume"]         = {"error": True}
        result["short_interest"] = {"error": True}

    # === SIGNAL 4: LSEG estimate revisions ===
    try:
        from core.lseg_data import lseg_desktop_available, _open_desktop_session
        if lseg_desktop_available():
            lib, ok = _open_desktop_session()
            if ok:
                ric = _RIC_MAP.get(ticker, f"{ticker}.O")
                df = lib.get_data(
                    universe=[ric],
                    fields=[
                        'TR.EPSMeanEstimate',
                        'TR.RevenueMeanEstimate',
                        'TR.PriceTargetMean',
                        'TR.PriceTargetHigh',
                        'TR.PriceTargetLow',
                    ]
                )
                if df is not None and not df.empty:
                    row = df.iloc[0]
                    eps   = _safe_float(row.get('Earnings Per Share - Mean Estimate'))
                    rev   = _safe_float(row.get('Revenue - Mean Estimate'))
                    pt    = _safe_float(row.get('Price Target - Mean'))
                    pt_hi = _safe_float(row.get('Price Target - High'))
                    pt_lo = _safe_float(row.get('Price Target - Low'))

                    current_price = result.get("price", {}).get("current", 0)
                    upside = ((pt - current_price) / current_price * 100
                              if pt and current_price else None)

                    if pt and current_price and current_price > 0:
                        up = (float(pt) - current_price) / current_price * 100
                        if up > 20:
                            derived_consensus = "Strong Buy"
                        elif up > 10:
                            derived_consensus = "Buy"
                        elif up > -5:
                            derived_consensus = "Hold"
                        else:
                            derived_consensus = "Sell"
                    else:
                        derived_consensus = "N/A"

                    result["lseg"] = {
                        "eps_estimate":      eps,
                        "revenue_estimate":  rev,
                        "derived_consensus": derived_consensus,
                        "price_target_mean": round(pt, 2)    if pt    else None,
                        "price_target_high": round(pt_hi, 2) if pt_hi else None,
                        "price_target_low":  round(pt_lo, 2) if pt_lo else None,
                        "upside_to_target":  round(upside, 1) if upside is not None else None,
                        "source":            "LSEG",
                    }
                else:
                    result["lseg"] = {"error": True, "msg": f"No LSEG data for {ric}"}
        else:
            result["lseg"] = {"error": True, "msg": "LSEG not connected"}
    except Exception as e:
        result["lseg"] = {"error": True, "msg": str(e)}

    # === SIGNAL 5: SEC 13F (EDGAR free) ===
    try:
        headers = {
            'User-Agent': 'kevin.cc.cheng@gmail.com',
            'Accept':     'application/json',
        }
        url = (f"https://efts.sec.gov/LATEST/search-index?"
               f"q=%22{ticker}%22&forms=13F-HR")
        r = requests.get(url, headers=headers, timeout=8)
        result["sec_13f"] = {
            "available": r.status_code == 200,
            "url":       url,
            "source":    "SEC EDGAR (free)",
            "note":      "13F data accessible via SEC EDGAR" if r.status_code == 200 else "Unavailable",
        }
    except Exception:
        result["sec_13f"] = {"available": False}

    # === COMPOSITE ACCUMULATION SCORE ===
    score     = 0
    max_score = 10
    reasons   = []

    price_data = result.get("price", {})
    vol_data   = result.get("volume", {})
    short_data = result.get("short_interest", {})
    lseg_data  = result.get("lseg", {})

    # === PRICE TREND (0-4 points) ===
    pct200   = price_data.get("pct_vs_200dma", 0) or 0
    pct50    = price_data.get("pct_vs_50dma", 0) or 0
    delivery = price_data.get("price_delivery_pct", 50) or 50

    if pct200 > 10:
        score += 2
        reasons.append(f"Strong uptrend: +{pct200:.1f}% above 200DMA ✅")
    elif pct200 > 0:
        score += 1
        reasons.append(f"Above 200DMA: +{pct200:.1f}% ✅")
    elif pct200 < -10:
        score -= 1
        reasons.append(f"Well below 200DMA: {pct200:.1f}% ❌")

    if pct50 > 5:
        score += 1
        reasons.append(f"Above 50DMA: +{pct50:.1f}% ✅")

    if delivery > 65:
        score += 1
        reasons.append(f"Strong close: top {100-delivery:.0f}% of range ✅")

    # === VOLUME (0-3 points) ===
    vol_ratio   = vol_data.get("ratio", 1) or 1
    persistence = vol_data.get("persistence_20d", 0) or 0

    if vol_ratio > 2.0:
        score += 2
        reasons.append(f"Very high volume: {vol_ratio:.1f}x avg 🔺")
    elif vol_ratio > 1.5:
        score += 1
        reasons.append(f"Elevated volume: {vol_ratio:.1f}x avg ✅")

    if persistence >= 5:
        score += 1
        reasons.append(f"Volume persistence: {persistence}/20 days ✅")

    # === SHORT INTEREST (0-1 point) ===
    short_pct_val = short_data.get("pct_of_float", 0) or 0
    if 5 < short_pct_val < 20 and vol_ratio > 1.3:
        score += 1
        reasons.append(
            f"Short squeeze setup: {short_pct_val:.1f}% short "
            f"+ elevated volume ✅"
        )

    # === LSEG SIGNALS (0-2 points) ===
    if not lseg_data.get("error"):
        upside_v = lseg_data.get("upside_to_target", 0) or 0
        derived  = lseg_data.get("derived_consensus", "N/A")

        if derived in ["Strong Buy", "Buy"]:
            score += 1
            reasons.append(f"Analyst target implies Buy ✅")

        if upside_v > 20:
            score += 1
            reasons.append(f"Analyst upside: {upside_v:+.1f}% ✅")
        elif upside_v > 10:
            score += 0.5
            reasons.append(f"Analyst upside: {upside_v:+.1f}%")

    score = max(0, min(round(score), max_score))

    stars = ("★★★★★" if score >= 9 else
             "★★★★☆" if score >= 7 else
             "★★★☆☆" if score >= 5 else
             "★★☆☆☆" if score >= 3 else "★☆☆☆☆")

    result["composite"] = {
        "score":     score,
        "max_score": max_score,
        "stars":     stars,
        "signal":    ("STRONG ACCUMULATION" if score >= 8 else
                      "ACCUMULATING"        if score >= 6 else
                      "MIXED"               if score >= 4 else
                      "WEAK"                if score >= 2 else "AVOID"),
        "reasons":   reasons,
    }

    return result
