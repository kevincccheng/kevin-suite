"""China macro monthly indicators — PMI, PPI, credit, GDP, property proxy."""

import threading
import pandas as pd
import yfinance as yf
import akshare as ak
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, wait as cf_wait
from datetime import datetime


def _timed(fn, timeout: int = 20):
    """Run fn() in a daemon thread; return result or None on timeout/error."""
    buf = [None]

    def _run():
        try:
            buf[0] = fn()
        except Exception:
            pass

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return buf[0]


def _get_lseg_china_meta() -> dict:
    """
    Fetch from LSEG what's available:
    - CNGDP=ECI: consensus estimate + actual + release date
    - CH*=ECI:   next scheduled release dates for PMI / PPI / CPI / GDP
    Returns {} if LSEG not connected.
    """
    try:
        from core.lseg_data import _open_desktop_session
        lib, ok = _open_desktop_session()
        if not ok or lib is None:
            return {}

        result = {}

        # GDP: CF_LAST = consensus estimate, GEN_VAL2 = actual value
        try:
            df = lib.get_data(
                universe=["CNGDP=ECI"],
                fields=["CF_LAST", "GEN_VAL2", "CF_DATE", "DSPLY_NAME"],
            )
            if df is not None and not df.empty:
                row = df.iloc[0]
                consensus = row.get("CF_LAST")
                actual    = row.get("GEN_VAL2")
                rel_date  = row.get("CF_DATE")
                if str(consensus) not in ("<NA>", "nan", "None"):
                    result["gdp_consensus"] = float(consensus)
                if str(actual) not in ("<NA>", "nan", "None"):
                    result["gdp_actual_lseg"] = float(actual)
                if str(rel_date) not in ("<NA>", "nan", "None", "NaT"):
                    result["gdp_release_date"] = str(pd.Timestamp(rel_date).date())
        except Exception:
            pass

        # Next release dates for PMI / PPI / CPI / GDP
        try:
            sched_rics = {
                "CHPMI=ECI":  "next_pmi_date",
                "CHPPIY=ECI": "next_ppi_date",
                "CHCPIY=ECI": "next_cpi_date",
                "CHGDPY=ECI": "next_gdp_date",
            }
            df2 = lib.get_data(
                universe=list(sched_rics.keys()),
                fields=["CF_DATE"],
            )
            if df2 is not None and not df2.empty:
                for _, row in df2.iterrows():
                    ric = str(row.get("Instrument", ""))
                    key = sched_rics.get(ric)
                    dt  = row.get("CF_DATE")
                    if key and str(dt) not in ("<NA>", "nan", "None", "NaT"):
                        result[key] = str(pd.Timestamp(dt).date())
        except Exception:
            pass

        return result
    except Exception:
        return {}


@st.cache_data(ttl=86400)
def get_china_macro() -> dict:
    result = {
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M HKT"),
        "error": False,
    }

    # ── Parallel AKShare fetches, each with a 22s thread timeout ──────────────
    # macro_china_pmi has BOTH manufacturing AND non-manufacturing PMI in one call.
    # macro_china_non_man_pmi is a separate NBS endpoint but times out frequently —
    # removed to avoid blocking the pool. macro_china_pmi (jin10) is the reliable path.
    # macro_china_m2_yearly (jin10) times out on every call — permanently removed.

    def _fetch_pmi():
        return _timed(ak.macro_china_pmi, timeout=22)        # mfg + non_mfg combined

    def _fetch_ppi():
        return _timed(ak.macro_china_ppi, timeout=22)

    def _fetch_credit():
        return _timed(ak.macro_china_shrzgm, timeout=22)

    def _fetch_gdp():
        return _timed(ak.macro_china_gdp, timeout=22)

    def _fetch_property():
        proxies = {
            "2007.HK": "Country Garden Services",
            "1109.HK": "CR Land",
            "0960.HK": "Longfor Group",
        }
        data = []
        for ticker, name in proxies.items():
            try:
                hist = yf.Ticker(ticker).history(period="3mo")
                if not hist.empty and len(hist) > 5:
                    chg_3m = (hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1) * 100
                    chg_1m = (hist["Close"].iloc[-1] / hist["Close"].iloc[-22] - 1) * 100 \
                             if len(hist) > 22 else None
                    data.append({
                        "ticker":    ticker,
                        "name":      name,
                        "change_3m": round(chg_3m, 1),
                        "change_1m": round(chg_1m, 1) if chg_1m is not None else None,
                    })
            except Exception:
                pass
        return data if data else None

    tasks = {
        "pmi":      _fetch_pmi,
        "ppi":      _fetch_ppi,
        "credit":   _fetch_credit,
        "gdp":      _fetch_gdp,
        "property": _fetch_property,
        "lseg":     _get_lseg_china_meta,
    }

    raw = {}
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fn): key for key, fn in tasks.items()}
        done, not_done = cf_wait(list(futures.keys()), timeout=28)
        for future in done:
            key = futures[future]
            try:
                raw[key] = future.result()
            except Exception:
                raw[key] = None
        for future in not_done:
            raw[futures[future]] = None

    lseg = raw.get("lseg") or {}

    # ── PMI ──────────────────────────────────────────────────────────────────
    # macro_china_pmi returns newest-first; cols: 月份, 制造业-指数, 制造业-同比增长,
    # 非制造业-指数, 非制造业-同比增长
    df_pmi = raw.get("pmi")
    try:
        if df_pmi is None or df_pmi.empty:
            raise ValueError("PMI data unavailable")

        row0 = df_pmi.iloc[0]   # latest
        row1 = df_pmi.iloc[1]   # previous

        mfg_val  = float(str(row0.get("制造业-指数",  50)).replace(",", ""))
        mfg_prev = float(str(row1.get("制造业-指数",  50)).replace(",", ""))
        nmfg_val = float(str(row0.get("非制造业-指数", 50)).replace(",", ""))
        date_str = str(row0.get("月份", ""))

        # Build last-6-months history for trend sparkline
        hist_rows = min(6, len(df_pmi))
        history = []
        for i in range(hist_rows - 1, -1, -1):   # oldest → newest
            r = df_pmi.iloc[i]
            try:
                history.append({
                    "date": str(r.get("月份", "")),
                    "mfg":  float(str(r.get("制造业-指数",  "")).replace(",", "") or 0),
                    "nmfg": float(str(r.get("非制造业-指数", "")).replace(",", "") or 0),
                })
            except Exception:
                pass

        result["pmi"] = {
            "manufacturing":      mfg_val,
            "manufacturing_prev": mfg_prev,
            "mfg_change":         round(mfg_val - mfg_prev, 1),
            "non_manufacturing":  nmfg_val,
            "date":   date_str,
            "signal": "EXPANDING"   if mfg_val > 50 else "CONTRACTING",
            "trend":  "IMPROVING"   if mfg_val > mfg_prev else "DETERIORATING",
            "history": history,
            "next_release": lseg.get("next_pmi_date", ""),
            "source": "AKShare/NBS via jin10",
        }
    except Exception as e:
        result["pmi"] = {"error": True, "msg": str(e)}

    # ── PPI ──────────────────────────────────────────────────────────────────
    # macro_china_ppi returns newest-first; cols: 月份, 当月, 当月同比增长, 累计
    df_ppi = raw.get("ppi")
    try:
        if df_ppi is None or df_ppi.empty:
            raise ValueError("PPI data unavailable")

        row0 = df_ppi.iloc[0]
        row1 = df_ppi.iloc[1]

        # Column may vary — try both common names
        yoy_col = "当月同比增长" if "当月同比增长" in df_ppi.columns else "当月"
        ppi_val  = float(str(row0.get(yoy_col, 0)).replace("%", "").replace(",", ""))
        ppi_prev = float(str(row1.get(yoy_col, 0)).replace("%", "").replace(",", ""))

        hist_rows = min(6, len(df_ppi))
        history = []
        for i in range(hist_rows - 1, -1, -1):
            r = df_ppi.iloc[i]
            try:
                history.append({
                    "date": str(r.get("月份", "")),
                    "yoy":  float(str(r.get(yoy_col, "")).replace("%", "").replace(",", "") or 0),
                })
            except Exception:
                pass

        result["ppi"] = {
            "yoy":      ppi_val,
            "prev_yoy": ppi_prev,
            "change":   round(ppi_val - ppi_prev, 1),
            "date":     str(row0.get("月份", "")),
            "signal":   "REFLATION" if ppi_val > 0 else "DEFLATION",
            "trend":    "IMPROVING" if ppi_val > ppi_prev else "DETERIORATING",
            "history":  history,
            "next_release": lseg.get("next_ppi_date", ""),
            "source":   "AKShare/NBS via jin10",
        }
    except Exception as e:
        result["ppi"] = {"error": True, "msg": str(e)}

    # ── CREDIT (Social Financing) ─────────────────────────────────────────────
    # macro_china_shrzgm sorted oldest-first; .iloc[-1] = latest
    df_credit = raw.get("credit")
    try:
        if df_credit is None or df_credit.empty:
            raise ValueError("Credit data unavailable")

        row_last = df_credit.iloc[-1]
        row_prev = df_credit.iloc[-2]
        sf_col   = "社会融资规模增量"
        loan_col = "其中-人民币贷款"

        sf_val   = float(str(row_last.get(sf_col,  0)).replace(",", "")) if sf_col  in df_credit.columns else None
        sf_prev  = float(str(row_prev.get(sf_col,  0)).replace(",", "")) if sf_col  in df_credit.columns else None
        loan_val = float(str(row_last.get(loan_col, 0)).replace(",", "")) if loan_col in df_credit.columns else None

        if sf_val is not None and sf_prev is not None and sf_prev != 0:
            trend      = "EXPANDING" if sf_val > sf_prev else "CONTRACTING"
            pct_change = (sf_val - sf_prev) / abs(sf_prev) * 100
        else:
            trend, pct_change = "UNKNOWN", 0.0

        result["credit"] = {
            "social_financing":      sf_val,
            "social_financing_prev": sf_prev,
            "rmb_loans":             loan_val,
            "trend":                 trend,
            "pct_change":            round(pct_change, 1),
            "date":                  str(row_last.get("月份", "")),
            "signal":                "STIMULUS" if trend == "EXPANDING" else "TIGHTENING",
            "source":                "AKShare/PBOC",
            "unit":                  "亿元 RMB",
        }
    except Exception as e:
        result["credit"] = {"error": True, "msg": str(e)}

    # ── GDP ───────────────────────────────────────────────────────────────────
    # macro_china_gdp sorted newest-first; cols: 季度, 国内生产总值-绝对值,
    # 国内生产总值-同比增长, 第一/二/三产业-*
    df_gdp = raw.get("gdp")
    try:
        if df_gdp is None or df_gdp.empty:
            raise ValueError("GDP data unavailable")

        # Prefer explicit column name, fall back to any 同比 column
        gdp_yoy_col = "国内生产总值-同比增长"
        if gdp_yoy_col not in df_gdp.columns:
            candidates = [c for c in df_gdp.columns if "同比" in c and "国内生产总值" in c]
            if not candidates:
                candidates = [c for c in df_gdp.columns if "同比" in c]
            gdp_yoy_col = candidates[0] if candidates else None

        if gdp_yoy_col is None:
            raise ValueError(f"GDP YoY column not found in {list(df_gdp.columns)}")

        row0 = df_gdp.iloc[0]
        row1 = df_gdp.iloc[1]
        gdp_val  = float(str(row0[gdp_yoy_col]).replace("%", "").replace(",", ""))
        gdp_prev = float(str(row1[gdp_yoy_col]).replace("%", "").replace(",", ""))

        hist_rows = min(5, len(df_gdp))
        history = []
        for i in range(hist_rows - 1, -1, -1):
            r = df_gdp.iloc[i]
            try:
                history.append({
                    "quarter": str(r.get("季度", "")),
                    "yoy":     float(str(r[gdp_yoy_col]).replace("%", "").replace(",", "") or 0),
                })
            except Exception:
                pass

        result["gdp"] = {
            "yoy":           gdp_val,
            "prev_yoy":      gdp_prev,
            "change":        round(gdp_val - gdp_prev, 1),
            "quarter":       str(row0.get("季度", "")),
            "signal":        "STRONG" if gdp_val > 5 else "MODERATE" if gdp_val > 3 else "WEAK",
            "trend":         "IMPROVING" if gdp_val > gdp_prev else "SLOWING",
            "history":       history,
            "consensus":     lseg.get("gdp_consensus"),      # LSEG consensus estimate
            "actual_lseg":   lseg.get("gdp_actual_lseg"),    # LSEG actual (cross-check)
            "release_date":  lseg.get("gdp_release_date", ""),
            "next_release":  lseg.get("next_gdp_date", ""),
            "source":        "AKShare/NBS",
        }
    except Exception as e:
        result["gdp"] = {"error": True, "msg": str(e)}

    # ── PROPERTY PROXY ────────────────────────────────────────────────────────
    prop_data = raw.get("property")
    try:
        if not prop_data:
            raise ValueError("No property data")
        avg_3m = sum(p["change_3m"] for p in prop_data) / len(prop_data)
        result["property"] = {
            "proxies":       prop_data,
            "avg_3m_change": round(avg_3m, 1),
            "signal":        "RECOVERING" if avg_3m > 5 else "STABLE" if avg_3m > -5 else "DISTRESSED",
            "source":        "yfinance (HK-listed proxies)",
            "note":          "HK-listed developers as proxy",
        }
    except Exception as e:
        result["property"] = {"error": True, "msg": str(e)}

    # ── LSEG NEXT RELEASE SCHEDULE ────────────────────────────────────────────
    result["lseg_schedule"] = {
        "next_pmi_date": lseg.get("next_pmi_date", ""),
        "next_ppi_date": lseg.get("next_ppi_date", ""),
        "next_cpi_date": lseg.get("next_cpi_date", ""),
        "next_gdp_date": lseg.get("next_gdp_date", ""),
    }

    # ── COMPOSITE SIGNAL ─────────────────────────────────────────────────────
    score   = 0
    signals = []

    pmi = result.get("pmi", {})
    if not pmi.get("error"):
        if pmi.get("signal") == "EXPANDING":
            score += 1
            signals.append("PMI expanding ✅")
        else:
            signals.append("PMI contracting ⚠️")
        if pmi.get("trend") == "IMPROVING":
            score += 0.5

    ppi = result.get("ppi", {})
    if not ppi.get("error"):
        if ppi.get("signal") == "REFLATION":
            score += 1
            signals.append("PPI reflating ✅")
        else:
            signals.append("PPI deflation ⚠️")

    credit = result.get("credit", {})
    if not credit.get("error"):
        if credit.get("signal") == "STIMULUS":
            score += 1.5
            signals.append("Credit expanding ✅")
        else:
            signals.append("Credit tightening ⚠️")

    gdp = result.get("gdp", {})
    if not gdp.get("error"):
        if gdp.get("signal") == "STRONG":
            score += 1
            signals.append("GDP ≥5% ✅")
        elif gdp.get("signal") == "MODERATE":
            score += 0.5
            signals.append("GDP moderate ⚠️")
        else:
            signals.append("GDP weak ⚠️")

    max_score = 5
    score     = min(round(score), max_score)
    overall   = "SUPPORTIVE" if score >= 4 else "NEUTRAL" if score >= 2 else "HEADWINDS"

    result["composite"] = {
        "score":    score,
        "max_score": max_score,
        "overall":  overall,
        "signals":  signals,
        "color":    "#166534" if overall == "SUPPORTIVE" else
                    "#854D0E" if overall == "NEUTRAL" else "#7F1D1D",
    }

    return result
