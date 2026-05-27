"""China macro monthly indicators — PMI, PPI, credit, M2, GDP, property proxy."""

import pandas as pd
import yfinance as yf
import akshare as ak
import streamlit as st
from datetime import datetime


@st.cache_data(ttl=86400)
def get_china_macro() -> dict:
    result = {
        "fetched_at": datetime.now().strftime('%Y-%m-%d %H:%M HKT'),
        "error": False,
    }

    # === PMI ===
    # macro_china_non_man_pmi() is the reliable source (jin10.com-independent).
    # macro_china_pmi() uses jin10.com which intermittently fails — used as supplement only.
    try:
        df_non = ak.macro_china_non_man_pmi()
        # Sorted oldest-first; tail = newest; cols: 商品, 日期, 今值, 预测值, 前值
        latest_non = df_non.iloc[-1]
        prev_non   = df_non.iloc[-2]

        non_mfg_val  = float(str(latest_non.get('今值', 50)).replace(',', ''))
        non_mfg_prev = float(str(prev_non.get('今值', 50)).replace(',', ''))
        date_str     = str(latest_non.get('日期', ''))

        # Try manufacturing PMI — may fail if jin10.com is down
        mfg_val, mfg_prev_val = None, None
        try:
            df_mfg   = ak.macro_china_pmi()  # newest-first; col: 制造业-指数
            mfg_val      = float(str(df_mfg.iloc[0].get('制造业-指数', 50)).replace(',', ''))
            mfg_prev_val = float(str(df_mfg.iloc[1].get('制造业-指数', 50)).replace(',', ''))
        except Exception:
            pass  # non-mfg PMI still usable for composite signal

        # Use manufacturing PMI if available; fall back to non-manufacturing
        primary_val  = mfg_val      if mfg_val      is not None else non_mfg_val
        primary_prev = mfg_prev_val if mfg_prev_val is not None else non_mfg_prev

        result["pmi"] = {
            "manufacturing":        mfg_val,
            "manufacturing_prev":   mfg_prev_val,
            "manufacturing_change": round(mfg_val - mfg_prev_val, 1) if mfg_val and mfg_prev_val else None,
            "non_manufacturing":    non_mfg_val,
            "date":   date_str,
            "signal": "EXPANDING" if primary_val > 50 else "CONTRACTING",
            "trend":  "IMPROVING" if primary_val > primary_prev else "DETERIORATING",
            "source": "AKShare/NBS",
        }
    except Exception as e:
        result["pmi"] = {"error": True, "msg": str(e)}

    # === PPI ===
    try:
        df = ak.macro_china_ppi()
        # Sorted newest-first
        latest = df.iloc[0]
        prev   = df.iloc[1]

        ppi_val  = float(str(latest.get('当月同比增长', 0)).replace('%', '').replace(',', ''))
        ppi_prev = float(str(prev.get('当月同比增长', 0)).replace('%', '').replace(',', ''))

        result["ppi"] = {
            "yoy":      ppi_val,
            "prev_yoy": ppi_prev,
            "change":   round(ppi_val - ppi_prev, 1),
            "date":     str(latest.get('月份', '')),
            "signal":   "REFLATION" if ppi_val > 0 else "DEFLATION",
            "trend":    "IMPROVING" if ppi_val > ppi_prev else "DETERIORATING",
            "source":   "AKShare/NBS",
        }
    except Exception as e:
        result["ppi"] = {"error": True, "msg": str(e)}

    # === SOCIAL FINANCING (Credit Impulse) ===
    try:
        df = ak.macro_china_shrzgm()
        latest = df.iloc[-1]
        prev   = df.iloc[-2]

        sf_col   = '社会融资规模增量'
        loan_col = '其中-人民币贷款'

        sf_val   = float(str(latest.get(sf_col, 0)).replace(',', '')) \
                   if sf_col in df.columns else None
        sf_prev  = float(str(prev.get(sf_col, 0)).replace(',', '')) \
                   if sf_col in df.columns else None
        loan_val = float(str(latest.get(loan_col, 0)).replace(',', '')) \
                   if loan_col in df.columns else None

        if sf_val is not None and sf_prev is not None:
            trend     = "EXPANDING" if sf_val > sf_prev else "CONTRACTING"
            pct_change = (sf_val - sf_prev) / abs(sf_prev) * 100 if sf_prev != 0 else 0
        else:
            trend, pct_change = "UNKNOWN", 0

        result["credit"] = {
            "social_financing":      sf_val,
            "social_financing_prev": sf_prev,
            "rmb_loans":             loan_val,
            "trend":                 trend,
            "pct_change":            round(pct_change, 1),
            "date":                  str(latest.get('月份', '')),
            "signal":                "STIMULUS" if trend == "EXPANDING" else "TIGHTENING",
            "source":                "AKShare/PBOC",
            "unit":                  "亿元 RMB",
        }
    except Exception as e:
        result["credit"] = {"error": True, "msg": str(e)}

    # === M2 MONEY SUPPLY ===
    # macro_china_m2_yearly() uses jin10.com — may intermittently fail with SSL error.
    # Try yearly first; fall back to macro_china_non_man_pmi prev-value pattern if needed.
    try:
        df    = ak.macro_china_m2_yearly()
        m2_df = df[df['商品'].str.contains('M2', na=False)] if '商品' in df.columns else df

        if not m2_df.empty:
            valid  = m2_df[m2_df['今值'].notna()]
            latest = valid.iloc[-1]
            prev   = valid.iloc[-2]

            m2_val  = float(str(latest.get('今值', 0)).replace('%', '').replace(',', ''))
            m2_prev = float(str(prev.get('今值', 0)).replace('%', '').replace(',', ''))

            result["m2"] = {
                "yoy_growth": m2_val,
                "prev_yoy":   m2_prev,
                "change":     round(m2_val - m2_prev, 1),
                "date":       str(latest.get('日期', '')),
                "signal":     "LOOSE" if m2_val > 10 else "NEUTRAL" if m2_val > 7 else "TIGHT",
                "source":     "AKShare/PBOC",
            }
        else:
            result["m2"] = {"error": True, "msg": "M2 data not found"}
    except Exception:
        # Fallback: derive M2 proxy from social financing trend if available
        credit = result.get("credit", {})
        if not credit.get("error") and credit.get("pct_change") is not None:
            result["m2"] = {"error": True, "msg": "M2 source temporarily unavailable (jin10.com SSL)"}
        else:
            result["m2"] = {"error": True, "msg": "M2 source temporarily unavailable (jin10.com SSL)"}

    # === GDP (quarterly) ===
    try:
        df = ak.macro_china_gdp()
        # Sorted newest-first
        latest = df.iloc[0]
        prev   = df.iloc[1]

        gdp_col = [c for c in df.columns if '同比' in c and 'GDP' not in c.upper()
                   and '国内生产总值' in c]
        if not gdp_col:
            gdp_col = [c for c in df.columns if '同比' in c]

        if gdp_col:
            gdp_val  = float(str(latest[gdp_col[0]]).replace('%', '').replace(',', ''))
            gdp_prev = float(str(prev[gdp_col[0]]).replace('%', '').replace(',', ''))

            result["gdp"] = {
                "yoy":      gdp_val,
                "prev_yoy": gdp_prev,
                "change":   round(gdp_val - gdp_prev, 1),
                "quarter":  str(latest.get('季度', '')),
                "signal":   "STRONG" if gdp_val > 5 else "MODERATE" if gdp_val > 3 else "WEAK",
                "source":   "AKShare/NBS",
            }
        else:
            result["gdp"] = {"error": True, "msg": "GDP column not found"}
    except Exception as e:
        result["gdp"] = {"error": True, "msg": str(e)}

    # === PROPERTY PROXY ===
    try:
        proxies = {
            '2007.HK': 'Country Garden Services',
            '1109.HK': 'CR Land',
            '0960.HK': 'Longfor Group',
        }

        property_data = []
        for ticker, name in proxies.items():
            try:
                hist = yf.Ticker(ticker).history(period='3mo')
                if not hist.empty and len(hist) > 5:
                    chg_3m = (hist['Close'].iloc[-1] / hist['Close'].iloc[0] - 1) * 100
                    chg_1m = (hist['Close'].iloc[-1] / hist['Close'].iloc[-22] - 1) * 100 \
                             if len(hist) > 22 else None
                    property_data.append({
                        "ticker":    ticker,
                        "name":      name,
                        "change_3m": round(chg_3m, 1),
                        "change_1m": round(chg_1m, 1) if chg_1m is not None else None,
                    })
            except Exception:
                pass

        if property_data:
            avg_3m = sum(p['change_3m'] for p in property_data) / len(property_data)
            result["property"] = {
                "proxies":       property_data,
                "avg_3m_change": round(avg_3m, 1),
                "signal":        "RECOVERING" if avg_3m > 5 else "STABLE" if avg_3m > -5 else "DISTRESSED",
                "source":        "yfinance (HK-listed proxies)",
                "note":          "HK-listed property names as proxy",
            }
        else:
            result["property"] = {"error": True, "msg": "No property data"}
    except Exception as e:
        result["property"] = {"error": True, "msg": str(e)}

    # === COMPOSITE CHINA MACRO SIGNAL ===
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

    m2 = result.get("m2", {})
    if not m2.get("error"):
        if m2.get("signal") == "LOOSE":
            score += 1
            signals.append("M2 growth strong ✅")

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
