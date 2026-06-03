"""Technical Analysis Engine — 7-indicator diffusion index."""

import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime


# ── Ticker normalisation ──────────────────────────────────────────

_ALIAS_MAP = {
    "HSI":     "^HSI",
    "SP500":   "^GSPC",
    "S&P500":  "^GSPC",
    "S&P":     "^GSPC",
    "NASDAQ":  "^NDX",
    "NDX":     "^NDX",
    "DOW":     "^DJI",
    "DJIA":    "^DJI",
    "HSCEI":   "^HSCE",
    "HSTECH":  "^HSTECH",
    "GOLD":    "GC=F",
    "OIL":     "CL=F",
    "SILVER":  "SI=F",
}

_INDEX_SET = {
    "^HSI", "^GSPC", "^NDX", "^DJI", "^HSCE", "^HSTECH",
    "000001.SS", "399001.SZ",
}

_COMMODITY_SET = {"GC=F", "CL=F", "SI=F"}


def _normalise_ticker(raw: str) -> str:
    t = raw.strip().upper()
    if t in _ALIAS_MAP:
        return _ALIAS_MAP[t]
    # Pure digits → HK ticker (e.g. "700" → "0700.HK")
    if t.isdigit():
        return t.zfill(4) + ".HK"
    return t


def _is_index(ticker: str) -> bool:
    return ticker.startswith("^") or ticker in _INDEX_SET

def _is_commodity(ticker: str) -> bool:
    return ticker in _COMMODITY_SET


def _safe_float(val) -> "float | None":
    try:
        v = float(val)
        return None if (np.isnan(v) or np.isinf(v)) else v
    except Exception:
        return None


# ── Indicator calculations ────────────────────────────────────────

def _compute_trend(close: pd.Series) -> dict:
    n = len(close)
    ma20  = close.rolling(min(20, n)).mean()
    ma50  = close.rolling(min(50, n)).mean()
    ma200 = close.rolling(min(200, n)).mean()

    cur  = float(close.iloc[-1])
    m20  = _safe_float(ma20.iloc[-1])
    m50  = _safe_float(ma50.iloc[-1])
    m200 = _safe_float(ma200.iloc[-1])

    above = sum(1 for m in [m20, m50, m200] if m and cur > m)

    if above == 3 and m20 and m50 and m200 and m20 > m50 > m200:
        score, note = +2, "Bull aligned — price above all MAs, MA20 > MA50 > MA200"
    elif above == 3:
        score, note = +1, "Price above all 3 MAs"
    elif above == 2:
        score, note = 0, "Price above 2 of 3 MAs — mixed"
    elif above == 1:
        score, note = -1, "Price below most MAs — bearish"
    else:
        score, note = -2, "Bear aligned — price below all MAs"

    vs_ma20_pct  = (cur / m20  - 1) * 100 if m20  else None
    vs_ma200_pct = (cur / m200 - 1) * 100 if m200 else None

    return {
        "score":            score,
        "note":             note,
        "ma20":             m20,
        "ma50":             m50,
        "ma200":            m200,
        "current_vs_ma20_pct":  round(vs_ma20_pct, 1)  if vs_ma20_pct  is not None else None,
        "current_vs_ma200_pct": round(vs_ma200_pct, 1) if vs_ma200_pct is not None else None,
        "ma20_series":  list(ma20.dropna().values),
        "ma50_series":  list(ma50.dropna().values),
        "ma200_series": list(ma200.dropna().values),
    }


def _compute_rsi(close: pd.Series) -> dict:
    period = min(14, len(close) - 1)
    delta  = close.diff()
    gain   = delta.clip(lower=0).rolling(period).mean()
    loss   = (-delta.clip(upper=0)).rolling(period).mean()
    rs     = gain / loss.replace(0, np.nan)
    rsi    = 100 - (100 / (1 + rs))

    rsi_cur = _safe_float(rsi.iloc[-1]) or 50.0

    if 40 <= rsi_cur <= 70:
        score, note = +2, f"RSI {rsi_cur:.1f} — healthy momentum zone"
    elif 30 <= rsi_cur < 40:
        score, note = +1, f"RSI {rsi_cur:.1f} — near oversold, recovery watch"
    elif 70 < rsi_cur <= 80:
        score, note = 0,  f"RSI {rsi_cur:.1f} — overbought, watch for pullback"
    elif rsi_cur > 80:
        score, note = -1, f"RSI {rsi_cur:.1f} — extreme overbought"
    else:
        score, note = -2, f"RSI {rsi_cur:.1f} — oversold breakdown"

    rsi_series = list(rsi.dropna().values[-60:])
    return {
        "score":      score,
        "note":       note,
        "rsi_current": round(rsi_cur, 1),
        "rsi_series":  rsi_series,
    }


def _compute_macd(close: pd.Series) -> dict:
    ema12      = close.ewm(span=12, adjust=False).mean()
    ema26      = close.ewm(span=26, adjust=False).mean()
    macd_line  = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram  = macd_line - signal_line

    macd_cur   = _safe_float(macd_line.iloc[-1]) or 0
    signal_cur = _safe_float(signal_line.iloc[-1]) or 0
    hist_cur   = _safe_float(histogram.iloc[-1]) or 0
    hist_prev  = _safe_float(histogram.iloc[-2]) or 0

    above_signal   = macd_cur > signal_cur
    hist_expanding = abs(hist_cur) > abs(hist_prev)

    if above_signal and hist_expanding and hist_cur > 0:
        score, note = +2, "MACD above signal, histogram expanding positive"
    elif above_signal and hist_cur > 0:
        score, note = +1, "MACD above signal, positive histogram"
    elif above_signal and hist_cur < 0:
        score, note = 0,  "MACD above signal but histogram turning negative"
    elif not above_signal and hist_cur < 0 and not hist_expanding:
        score, note = -1, "MACD below signal, histogram contracting"
    else:
        score, note = -2, "MACD below signal, histogram expanding negative"

    tail = 60
    return {
        "score":           score,
        "note":            note,
        "macd_series":     list(macd_line.values[-tail:]),
        "signal_series":   list(signal_line.values[-tail:]),
        "histogram_series": list(histogram.values[-tail:]),
    }


def _compute_bb(close: pd.Series) -> dict:
    n       = min(20, len(close))
    bb_mid  = close.rolling(n).mean()
    bb_std  = close.rolling(n).std()
    bb_up   = bb_mid + 2 * bb_std
    bb_lo   = bb_mid - 2 * bb_std
    bb_width = (bb_up - bb_lo) / bb_mid.replace(0, np.nan)

    cur    = float(close.iloc[-1])
    up_cur = _safe_float(bb_up.iloc[-1]) or cur
    lo_cur = _safe_float(bb_lo.iloc[-1]) or cur
    band   = up_cur - lo_cur

    pct_b = (cur - lo_cur) / band if band > 0 else 0.5
    width_cur = _safe_float(bb_width.iloc[-1]) or 0
    width_avg = _safe_float(bb_width.rolling(20).mean().iloc[-1]) or width_cur
    expanding = width_cur > width_avg

    if 0.5 <= pct_b <= 0.8 and expanding:
        score, note = +2, f"%B {pct_b:.2f} — upper half, bands expanding (bullish)"
    elif pct_b > 0.5:
        score, note = +1, f"%B {pct_b:.2f} — price in upper half of band"
    elif 0.3 <= pct_b <= 0.5:
        score, note = 0,  f"%B {pct_b:.2f} — mid-band, neutral"
    elif pct_b < 0.3 and not expanding:
        score, note = -1, f"%B {pct_b:.2f} — lower half, bands contracting"
    else:
        score, note = -2, f"%B {pct_b:.2f} — near lower band, bands expanding (breakdown)"

    tail = 60
    return {
        "score":        score,
        "note":         note,
        "pct_b":        round(pct_b, 3),
        "upper_series": list(bb_up.values[-tail:]),
        "middle_series": list(bb_mid.values[-tail:]),
        "lower_series": list(bb_lo.values[-tail:]),
    }


def _compute_volume(close: pd.Series, volume: pd.Series, is_index: bool) -> dict:
    if is_index or volume is None or volume.sum() == 0:
        return {"score": None, "note": "N/A — price index has no meaningful volume", "obv_series": None, "vol_ratio": None, "obv_rising": None}

    n          = min(20, len(volume))
    vol_avg20  = volume.rolling(n).mean()
    vol_ratio  = float(volume.iloc[-1]) / float(vol_avg20.iloc[-1]) if float(vol_avg20.iloc[-1]) > 0 else 1.0

    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    obv       = (volume * direction).cumsum()
    obv_ma20  = obv.rolling(n).mean()

    obv_rising = bool(float(obv.iloc[-1]) > float(obv_ma20.iloc[-1]))
    price_up   = float(close.iloc[-1]) > float(close.iloc[-2])

    if price_up and vol_ratio > 1.5 and obv_rising:
        score, note = +2, f"Vol ratio {vol_ratio:.1f}x, OBV rising — strong accumulation"
    elif price_up and obv_rising:
        score, note = +1, f"OBV rising with price — healthy accumulation"
    elif not price_up and not obv_rising:
        score, note = -1, f"OBV falling with price — distribution"
    elif not price_up and vol_ratio > 1.5:
        score, note = -2, f"Vol ratio {vol_ratio:.1f}x on down day — heavy distribution"
    else:
        score, note = 0, f"Vol ratio {vol_ratio:.1f}x — neutral"

    obv_series = list(obv.values[-60:])
    return {
        "score":      score,
        "note":       note,
        "vol_ratio":  round(vol_ratio, 2),
        "obv_series": obv_series,
        "obv_rising": obv_rising,
    }


def _compute_sr(close: pd.Series) -> dict:
    n         = min(60, len(close) - 1)
    cur       = float(close.iloc[-1])
    wk52_high = float(close.max())
    wk52_low  = float(close.min())

    span = wk52_high - wk52_low
    range_pct        = (cur - wk52_low) / span * 100 if span > 0 else 50.0
    pct_from_52w_high = (cur / wk52_high - 1) * 100
    pct_from_52w_low  = (cur / wk52_low  - 1) * 100

    if pct_from_52w_high > -3:
        score, note = +2, f"Near 52W high ({pct_from_52w_high:+.1f}%) — strong uptrend"
    elif range_pct > 70:
        score, note = +1, f"{range_pct:.0f}% of 52W range — upper territory"
    elif range_pct > 40:
        score, note = 0,  f"{range_pct:.0f}% of 52W range — mid-range"
    elif range_pct > 20:
        score, note = -1, f"{range_pct:.0f}% of 52W range — lower territory"
    else:
        score, note = -2, f"Near 52W low ({pct_from_52w_low:+.1f}% above) — downtrend"

    return {
        "score":             score,
        "note":              note,
        "wk52_high":         round(wk52_high, 4),
        "wk52_low":          round(wk52_low, 4),
        "range_pct":         round(range_pct, 1),
        "pct_from_52w_high": round(pct_from_52w_high, 1),
        "pct_from_52w_low":  round(pct_from_52w_low, 1),
    }


def _compute_rs(close: pd.Series, ticker: str) -> dict:
    # HK stocks/ETFs → benchmark vs HSI
    if ticker.endswith(".HK"):
        bench = "^HSI"
    # SPY or S&P 500 → benchmark vs Nasdaq
    elif ticker in {"SPY", "^GSPC"}:
        bench = "^NDX"
    # All other indices and commodities → benchmark vs SPY
    else:
        bench = "SPY"

    try:
        bench_hist  = yf.Ticker(bench).history(period="100d")["Close"]
        min_periods = min(63, len(close), len(bench_hist))

        stock_ret_3m = (float(close.iloc[-1]) / float(close.iloc[-min_periods]) - 1) * 100
        bench_ret_3m = (float(bench_hist.iloc[-1]) / float(bench_hist.iloc[-min_periods]) - 1) * 100
        rs_3m        = stock_ret_3m - bench_ret_3m
    except Exception:
        bench = "N/A"
        stock_ret_3m = bench_ret_3m = rs_3m = 0.0

    if rs_3m > 10:
        score, note = +2, f"RS vs {bench}: {rs_3m:+.1f}% — strong outperformance"
    elif rs_3m > 0:
        score, note = +1, f"RS vs {bench}: {rs_3m:+.1f}% — mild outperformance"
    elif rs_3m > -10:
        score, note = -1, f"RS vs {bench}: {rs_3m:+.1f}% — mild underperformance"
    else:
        score, note = -2, f"RS vs {bench}: {rs_3m:+.1f}% — significant underperformance"

    return {
        "score":        score,
        "note":         note,
        "rs_3m":        round(rs_3m, 1),
        "stock_ret_3m": round(stock_ret_3m, 1),
        "bench_ret_3m": round(bench_ret_3m, 1),
        "bench_ticker": bench,
    }


# ── Main entry point ──────────────────────────────────────────────

@st.cache_data(ttl=900, show_spinner=False)
def get_ta_analysis(ticker_raw: str) -> dict:
    ticker    = _normalise_ticker(ticker_raw)
    index     = _is_index(ticker)
    commodity = _is_commodity(ticker)

    try:
        t    = yf.Ticker(ticker)
        hist = t.history(period="252d")
        if hist.empty:
            return {"error": True, "error_msg": f"No data returned for {ticker}. Check ticker."}
    except Exception as e:
        return {"error": True, "error_msg": str(e)}

    close  = hist["Close"].dropna()
    volume = hist["Volume"]

    if len(close) < 5:
        return {"error": True, "error_msg": f"Insufficient history for {ticker} ({len(close)} days)."}

    # Company info
    try:
        info         = t.info
        company_name = info.get("shortName") or info.get("longName") or ticker
        sector       = info.get("sector", "")
    except Exception:
        info         = {}
        company_name = ticker
        sector       = ""

    cur_price = float(close.iloc[-1])
    prev_price = float(close.iloc[-2]) if len(close) >= 2 else cur_price
    price_change_pct = (cur_price / prev_price - 1) * 100 if prev_price > 0 else 0.0

    # Compute all indicators
    ind_trend  = _compute_trend(close)
    ind_rsi    = _compute_rsi(close)
    ind_macd   = _compute_macd(close)
    ind_bb     = _compute_bb(close)
    ind_vol    = _compute_volume(close, volume, index and not commodity)
    ind_sr     = _compute_sr(close)
    ind_rs     = _compute_rs(close, ticker)

    indicators = {
        "trend":  ind_trend,
        "rsi":    ind_rsi,
        "macd":   ind_macd,
        "bb":     ind_bb,
        "volume": ind_vol,
        "sr":     ind_sr,
        "rs":     ind_rs,
    }

    # Composite diffusion index
    all_scores   = [ind["score"] for ind in indicators.values()]
    valid_scores = [s for s in all_scores if s is not None]
    raw_total    = sum(valid_scores)
    max_possible = len(valid_scores) * 2
    min_possible = len(valid_scores) * -2
    denom        = max_possible - min_possible
    normalised   = (raw_total - min_possible) / denom * 100 if denom > 0 else 50.0

    if normalised >= 75:
        verdict = "STRONG BUY"
    elif normalised >= 60:
        verdict = "BUY"
    elif normalised >= 45:
        verdict = "NEUTRAL"
    elif normalised >= 30:
        verdict = "SELL"
    else:
        verdict = "STRONG SELL"

    verdict_color = {
        "STRONG BUY":  "#166534",
        "BUY":         "#15803d",
        "NEUTRAL":     "#854D0E",
        "SELL":        "#b91c1c",
        "STRONG SELL": "#7F1D1D",
    }[verdict]

    return {
        "error":            False,
        "ticker_clean":     ticker,
        "ticker_raw":       ticker_raw,
        "company_name":     company_name,
        "sector":           sector,
        "current_price":    round(cur_price, 4),
        "price_change_pct": round(price_change_pct, 2),
        "is_index":         index and not commodity,
        "is_commodity":     commodity,
        "hist":             hist,
        "indicators":       indicators,
        "composite": {
            "normalised":    round(normalised, 1),
            "raw_total":     raw_total,
            "max_possible":  max_possible,
            "min_possible":  min_possible,
            "scores":        all_scores,
            "verdict":       verdict,
            "color":         verdict_color,
        },
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M HKT"),
    }
