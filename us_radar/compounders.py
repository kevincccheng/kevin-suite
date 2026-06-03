"""Layer 1/2/3 Compounders — thematic watchlist Z-score daily ranking."""

import yfinance as yf
import pandas as pd
import streamlit as st
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed


# ── Watchlist definitions ────────────────────────────────────────────────────

LAYER1 = {
    "NVDA": {"ric": "NVDA.O", "name": "NVIDIA",               "theme": "AI infrastructure"},
    "AVGO": {"ric": "AVGO.O", "name": "Broadcom",             "theme": "AI infrastructure"},
    "AMD":  {"ric": "AMD.O",  "name": "AMD",                  "theme": "AI infrastructure"},
    "ARM":  {"ric": "ARM.O",  "name": "Arm Holdings",         "theme": "AI infrastructure"},
    "MRVL": {"ric": "MRVL.O", "name": "Marvell Technology",   "theme": "AI infrastructure"},
    "PLTR": {"ric": "PLTR.N", "name": "Palantir",             "theme": "AI software"},
    "APP":  {"ric": "APP.O",  "name": "AppLovin",             "theme": "AI software"},
    "CEG":  {"ric": "CEG.N",  "name": "Constellation Energy", "theme": "AI power"},
    "VST":  {"ric": "VST.N",  "name": "Vistra",               "theme": "AI power"},
}

LAYER2 = {
    "CRDO": {"ric": "CRDO.O", "name": "Credo Technology",     "theme": "AI infrastructure"},
    "ALAB": {"ric": "ALAB.O", "name": "Astera Labs",          "theme": "AI infrastructure"},
    "SMCI": {"ric": "SMCI.O", "name": "Super Micro",          "theme": "AI infrastructure"},
    "RKLB": {"ric": "RKLB.O", "name": "Rocket Lab",           "theme": "space"},
    "ASTS": {"ric": "ASTS.O", "name": "AST SpaceMobile",      "theme": "space"},
    "NRG":  {"ric": "NRG.N",  "name": "NRG Energy",           "theme": "AI power"},
    "HIMS": {"ric": "HIMS.N", "name": "Hims & Hers Health",   "theme": "healthtech"},
    "HOOD": {"ric": "HOOD.O", "name": "Robinhood Markets",    "theme": "fintech"},
}

LAYER3 = {
    "OKLO": {"ric": "OKLO.N", "name": "Oklo",                 "theme": "nuclear"},
    "SMR":  {"ric": "SMR.N",  "name": "NuScale Power",        "theme": "nuclear"},
    "ACHR": {"ric": "ACHR.N", "name": "Archer Aviation",      "theme": "physical AI"},
    "JOBY": {"ric": "JOBY.N", "name": "Joby Aviation",        "theme": "physical AI"},
    "PL":   {"ric": "PL.N",   "name": "Planet Labs",          "theme": "space"},
    "SPIR": {"ric": "SPIR.O", "name": "Spire Global",         "theme": "space"},
    "RXRX": {"ric": "RXRX.O", "name": "Recursion Pharma",     "theme": "AI biotech"},
}

ALL_WATCHLIST = {**LAYER1, **LAYER2, **LAYER3}


# ── Helpers ──────────────────────────────────────────────────────────────────

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


def _safe_zscore(series: pd.Series) -> pd.Series:
    """Z-score winsorised at ±3; returns 0 for zero-variance series."""
    std = series.std()
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=series.index)
    z = (series - series.mean()) / std
    return z.clip(-3, 3)


def _get_qqq_return(period_days: int = 63) -> float:
    """QQQ return over last period_days trading days for RS calculation."""
    try:
        hist = yf.Ticker("QQQ").history(period=f"{period_days + 10}d")
        if len(hist) < period_days:
            return 0.0
        close = hist["Close"]
        return (close.iloc[-1] - close.iloc[-period_days]) / close.iloc[-period_days] * 100
    except Exception:
        return 0.0


def _get_yf_signals(tickers: list) -> dict:
    """Parallel yfinance fetch — price/volume/RS signals for every ticker."""
    qqq_ret = _get_qqq_return(63)

    def _fetch_one(ticker):
        try:
            hist = yf.Ticker(ticker).history(period="270d")
            if len(hist) < 22:
                return ticker, None
            close  = hist["Close"]
            volume = hist["Volume"]

            current    = float(close.iloc[-1])
            ma200      = float(close.rolling(200).mean().iloc[-1])
            ma50       = float(close.rolling(50).mean().iloc[-1])
            pct_vs_200 = (current - ma200) / ma200 * 100 if ma200 > 0 else 0.0
            pct_vs_50  = (current - ma50)  / ma50  * 100 if ma50  > 0 else 0.0

            vol_20d_avg  = float(volume.iloc[-21:-1].mean())
            vol_today    = float(volume.iloc[-1])
            vol_ratio    = vol_today / vol_20d_avg if vol_20d_avg > 0 else 1.0
            persistence  = int((volume.iloc[-21:] > vol_20d_avg).sum())

            ret_1m = ((close.iloc[-1] - close.iloc[-22]) / close.iloc[-22] * 100
                      if len(close) >= 22 else 0.0)

            if len(close) >= 64:
                ret_63d   = (close.iloc[-1] - close.iloc[-64]) / close.iloc[-64] * 100
                rs_vs_qqq = ret_63d - qqq_ret
            else:
                rs_vs_qqq = 0.0

            return ticker, {
                "price":           round(current, 2),
                "pct_vs_200":      round(pct_vs_200, 1),
                "pct_vs_50":       round(pct_vs_50, 1),
                "vol_ratio":       round(vol_ratio, 2),
                "persistence_20d": persistence,
                "ret_1m":          round(ret_1m, 1),
                "rs_vs_qqq":       round(rs_vs_qqq, 1),
            }
        except Exception:
            return ticker, None

    results = {}
    with ThreadPoolExecutor(max_workers=12) as executor:
        futs = {executor.submit(_fetch_one, t): t for t in tickers}
        for fut in as_completed(futs, timeout=35):
            try:
                ticker, data = fut.result()
                results[ticker] = data
            except Exception:
                pass
    return results


def _get_lseg_estimates(rics: list) -> dict:
    """Batch LSEG price-target + estimate fetch for all RICs in one call."""
    try:
        from core.lseg_data import lseg_desktop_available, _open_desktop_session
        if not lseg_desktop_available():
            return {}
        lib, ok = _open_desktop_session()
        if not ok:
            return {}
        df = lib.get_data(
            universe=rics,
            fields=[
                "TR.EPSMeanEstimate",
                "TR.RevenueMeanEstimate",
                "TR.PriceTargetMean",
                "TR.PriceTargetHigh",
                "TR.PriceTargetLow",
            ],
        )
        if df is None or df.empty:
            return {}
        result = {}
        for _, yfrow in df.iterrows():
            ric    = str(yfrow.get("Instrument") or "")
            ticker = ric.replace(".O", "").replace(".N", "").replace(".A", "")
            result[ticker] = {
                "price_target_mean": _safe_float(yfrow.get("Price Target - Mean")),
                "price_target_high": _safe_float(yfrow.get("Price Target - High")),
                "price_target_low":  _safe_float(yfrow.get("Price Target - Low")),
                "eps_estimate":      _safe_float(yfrow.get("Earnings Per Share - Mean Estimate")),
                "revenue_estimate":  _safe_float(yfrow.get("Revenue - Mean Estimate")),
            }
        return result
    except Exception:
        return {}


# ── Main entry point ─────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def get_watchlist_signals(layer: str = "all") -> pd.DataFrame:
    """Fetch and Z-score rank all watchlist signals. Sorted by conviction score."""
    if layer == "layer1":
        universe = LAYER1
    elif layer == "layer2":
        universe = LAYER2
    elif layer == "layer3":
        universe = LAYER3
    else:
        universe = ALL_WATCHLIST

    tickers = list(universe.keys())
    rics    = [universe[t]["ric"] for t in tickers]

    yf_signals   = _get_yf_signals(tickers)
    lseg_signals = _get_lseg_estimates(rics)

    rows = []
    for ticker in tickers:
        meta     = universe[ticker]
        yf_row   = yf_signals.get(ticker) or {}
        lseg_row = lseg_signals.get(ticker, {})

        price  = yf_row.get("price")
        pt     = lseg_row.get("price_target_mean")
        upside = ((pt - price) / price * 100) if (pt and price and price > 0) else None

        layer_num = 1 if ticker in LAYER1 else (2 if ticker in LAYER2 else 3)

        rows.append({
            "ticker":            ticker,
            "name":              meta["name"],
            "theme":             meta["theme"],
            "layer":             layer_num,
            "ric":               meta["ric"],
            "price":             price,
            "pct_vs_200":        yf_row.get("pct_vs_200", 0.0),
            "pct_vs_50":         yf_row.get("pct_vs_50", 0.0),
            "vol_ratio":         yf_row.get("vol_ratio", 1.0),
            "persistence_20d":   yf_row.get("persistence_20d", 0),
            "ret_1m":            yf_row.get("ret_1m", 0.0),
            "rs_vs_qqq":         yf_row.get("rs_vs_qqq", 0.0),
            "upside":            round(upside, 1) if upside is not None else None,
            "price_target_mean": pt,
            "eps_estimate":      lseg_row.get("eps_estimate"),
            "lseg_ok":           bool(lseg_row and pt is not None),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Fill NaN before Z-scoring
    for col in ["pct_vs_200", "vol_ratio", "persistence_20d", "ret_1m", "rs_vs_qqq"]:
        df[col] = df[col].fillna(0.0)
    upside_filled = pd.to_numeric(df["upside"], errors="coerce").fillna(0.0)

    z_pct200  = _safe_zscore(df["pct_vs_200"])
    z_rs      = _safe_zscore(df["rs_vs_qqq"])
    z_vol     = _safe_zscore(df["vol_ratio"])
    z_persist = _safe_zscore(df["persistence_20d"].astype(float))
    z_ret1m   = _safe_zscore(df["ret_1m"])
    z_upside  = _safe_zscore(upside_filled)

    is_l1 = df["layer"] == 1
    score = pd.Series(0.0, index=df.index)

    # Layer 1 — trend-focused
    score[is_l1] = (
        z_pct200[is_l1]  * 2.0 +
        z_rs[is_l1]      * 1.5 +
        z_upside[is_l1]  * 1.5 +
        z_vol[is_l1]     * 0.5 +
        z_persist[is_l1] * 0.5
    )
    # Layer 2/3 — momentum-focused (z_pct200 weight raised 1.0 → 1.5)
    score[~is_l1] = (
        z_vol[~is_l1]     * 2.0 +
        z_persist[~is_l1] * 2.0 +
        z_ret1m[~is_l1]   * 1.0 +
        z_pct200[~is_l1]  * 1.5 +
        z_upside[~is_l1]  * 0.5
    )

    # TREND GATE: hard cap on broken-downtrend stocks regardless of volume signals
    pct200_s = df["pct_vs_200"].fillna(0.0)
    score[pct200_s < -20] = score[pct200_s < -20].clip(upper=-1.5)   # severe: bottom 15%
    score[(pct200_s >= -20) & (pct200_s < -10)] = (
        score[(pct200_s >= -20) & (pct200_s < -10)].clip(upper=-0.5) # moderate: bottom 30%
    )
    score[(pct200_s >= -10) & (pct200_s < -5)] -= 0.5                # mild: slight penalty

    df["score"] = score.round(2)
    df = df.sort_values("score", ascending=False).reset_index(drop=True)

    # Stars — percentile within the full table universe
    pct_rank = df["score"].rank(pct=True)

    def _stars(p: float) -> str:
        if p >= 0.90: return "★★★★★"
        if p >= 0.75: return "★★★★☆"
        if p >= 0.50: return "★★★☆☆"
        if p >= 0.25: return "★★☆☆☆"
        return "★☆☆☆☆"

    df["stars"]      = pct_rank.map(_stars)
    df.insert(0, "rank", range(1, len(df) + 1))
    df["fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M HKT")

    return df
