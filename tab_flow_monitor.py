"""Flow Monitor tab — Phase 2: HK/China focus with compact Global Context panel."""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

from flow_core.hk_flows import (
    get_stock_connect_flows,
    get_stock_connect_history,
    get_hsi_data,
    get_cnh_cny_spread,
    get_pboc_rate,
    get_hkma_balance,
    get_hibor,
    get_usdhkd,
    get_hstech,
    get_usdcnh_200dma,
    get_southbound_conviction,
)
from flow_core.us_macro import (
    get_fed_expectations,
    get_yield_curve,
    get_vix,
    get_dxy,
)
from flow_core.composite import calculate_composite_signal
from flow_core.signal_logger import log_daily_signal, get_signal_history
from flow_core.ai_briefing import generate_briefing
from core.lseg_data import lseg_desktop_available

_HK_BRIEFING_PROMPT = (
    "You are a concise macro analyst briefing a Hong Kong-based "
    "private investor on HK/China market conditions only. "
    "Focus exclusively on: southbound flows, HK liquidity "
    "(HKMA, HIBOR), HKD peg status, HSI/HSTECH momentum, "
    "and how global signals (DXY, VIX, real yields) specifically "
    "impact HK/China equities. "
    "The investor deploys HKD 100K/month into HK/China equities. "
    "End with one clear HK/China DCA recommendation only."
)


@st.cache_data(ttl=1800)
def _fetch_flow_data():
    from concurrent.futures import ThreadPoolExecutor, wait as cf_wait
    from flow_core.china_macro import get_china_macro

    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M HKT")

    # All 16 signals are independent — run in parallel.
    # china_macro has its own 24hr internal cache; including it here runs it
    # concurrently with flow signals instead of blocking the render path.
    tasks = {
        "sc_flows":              get_stock_connect_flows,
        "hsi":                   get_hsi_data,
        "cnh":                   get_cnh_cny_spread,
        "pboc":                  get_pboc_rate,
        "nb_history":            lambda: get_stock_connect_history(30),
        "hkma":                  get_hkma_balance,
        "hibor":                 get_hibor,
        "usdhkd":                get_usdhkd,
        "hstech":                get_hstech,
        "usdcnh_200dma":         get_usdcnh_200dma,
        "southbound_conviction": get_southbound_conviction,
        "fed":                   get_fed_expectations,
        "yield_curve":           get_yield_curve,
        "vix":                   get_vix,
        "dxy":                   get_dxy,
        "china_macro":           get_china_macro,
    }

    results = {"fetched_at": fetched_at}
    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = {executor.submit(fn): key for key, fn in tasks.items()}
        # 60s global wall-clock cap — any signal still running after 60s is skipped
        done, not_done = cf_wait(list(futures.keys()), timeout=60)
        for future in done:
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as e:
                results[key] = {"error": True, "msg": str(e)}
        for future in not_done:
            key = futures[future]
            results[key] = {"error": True, "msg": "timeout"}
    return results


# ── Helpers ──────────────────────────────────────────────────────


def _fmt_hkd(val: float, decimals: int = 1) -> str:
    if val is None:
        return "N/A"
    if abs(val) >= 1e9:
        return f"HKD {val/1e9:.{decimals}f}B"
    if abs(val) >= 1e6:
        return f"HKD {val/1e6:.0f}M"
    return f"HKD {val:,.0f}"


def _signal_emoji(sig: str) -> str:
    m = {"STABLE": "✅", "MILD_PRESSURE": "⚠️", "STRESS": "🚨",
         "CALM": "✅", "ELEVATED": "⚠️", "FEAR": "🚨", "PANIC": "💀",
         "NORMAL": "✅", "FLAT": "⚠️", "INVERTED": "🚨",
         "EXPANDING": "📈", "CONTRACTING": "📉",
         "RISING": "📈", "FALLING": "📉",
         "SAFE": "✅", "WATCH": "⚠️", "ALERT": "🚨",
         "STRONG": "💪", "WEAK": "🕊️", "NEUTRAL": "➡️",
         "ABOVE_200DMA": "⬆️", "BELOW_200DMA": "⬇️"}
    return m.get(sig, "")


def _has_error(data) -> bool:
    if isinstance(data, dict):
        return bool(data.get("error"))
    if isinstance(data, list):
        return len(data) == 0
    if isinstance(data, pd.DataFrame):
        return data.empty
    return False


def _src(data) -> str:
    if isinstance(data, dict) and not data.get("error"):
        return data.get("source", "")
    return ""


def _live_badge(data, label: str = "") -> str:
    if _has_error(data):
        return f"🟡 Unavailable{' — ' + label if label else ''}"
    src = _src(data)
    tag = src or label
    return f"🔵 Live{' via ' + tag if tag else ''}"


def _stance_color(stance: str) -> tuple:
    return {
        "ACCUMULATE": ("#1a472a", "#4ade80"),
        "NEUTRAL":    ("#3a3014", "#fbbf24"),
        "WAIT":       ("#5c0000", "#f87171"),
    }.get(stance, ("#1e2530", "#9ca3af"))


def _make_nb_chart(df: pd.DataFrame) -> go.Figure:
    colors = ["#4ade80" if v >= 0 else "#f87171" for v in df["northbound_net"]]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["date"], y=df["northbound_net"] / 1e9,
        marker_color=colors, name="Daily Flow",
        hovertemplate="%{x}<br>%{y:.2f}B HKD<extra></extra>",
    ))
    if "northbound_cumulative_5d" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["northbound_cumulative_5d"] / 1e9,
            mode="lines", line=dict(color="#60a5fa", width=2, dash="dot"),
            name="5d Cumulative",
        ))
    if "northbound_cumulative_20d" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["northbound_cumulative_20d"] / 1e9,
            mode="lines", line=dict(color="#f59e0b", width=2),
            name="20d Cumulative",
        ))
    fig.add_hline(y=0, line_width=1, line_color="white", opacity=0.3)
    fig.update_layout(
        title="Southbound Flow (HKD Billion)",
        template="plotly_dark", height=280,
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", y=1.1, x=0),
        hovermode="x unified",
    )
    return fig


def _stance_badge_html(label: str, stance: str) -> str:
    bg, tc = _stance_color(stance)
    emoji = {"ACCUMULATE": "🟢", "NEUTRAL": "🟡", "WAIT": "🔴"}.get(stance, "⚫")
    return (
        f'<div style="background:{bg};border:1px solid {tc};border-radius:10px;'
        f'padding:12px 16px;text-align:center">'
        f'<div style="color:#9ca3af;font-size:11px;text-transform:uppercase;letter-spacing:1px">{label}</div>'
        f'<div style="color:{tc};font-size:1.5rem;font-weight:700;margin-top:4px">{emoji} {stance}</div>'
        f'</div>'
    )


def render_global_context(d: dict):
    """Compact 4-metric panel showing US signals that affect HK/China flows."""
    st.subheader("🌍 Global Context — Impact on HK")
    st.caption("Key US signals affecting HKD peg and HK/China flows")

    col1, col2, col3, col4 = st.columns(4)

    dxy = d.get("dxy", {})
    with col1:
        if not dxy.get("error"):
            signal = dxy.get("signal", "N/A")
            price = dxy.get("price", 0)
            st.metric("DXY Dollar", f"{price:.1f}",
                      delta=f"{dxy.get('change_pct', 0):+.2f}%")
            st.caption(f"Signal: {signal}")
        else:
            st.metric("DXY Dollar", "N/A")

    vix = d.get("vix", {})
    with col2:
        if not vix.get("error"):
            st.metric("VIX", f"{vix.get('vix', 0):.1f}",
                      delta=f"{vix.get('change_pct', 0):+.1f}")
            st.caption(vix.get("signal", ""))
        else:
            st.metric("VIX", "N/A")

    yc = d.get("yield_curve", {})
    with col3:
        real = yc.get("real_yield_10yr", None)
        if real is not None:
            st.metric("US Real Yield", f"{real:.2f}%")
            signal = ("RESTRICTIVE" if real > 2.0 else
                      "NEUTRAL" if real > 1.0 else "EASY")
            st.caption(signal)
        else:
            st.metric("US Real Yield", "N/A")

    fed = d.get("fed", {})
    with col4:
        if not fed.get("error"):
            hold = fed.get("prob_hold", 0)
            cut = fed.get("prob_cut_25", 0)
            st.metric("Fed Rate", f"{fed.get('current_rate', 0):.2f}%")
            st.caption(f"Hold {hold:.0f}% / Cut {cut:.0f}%")
        else:
            st.metric("Fed Rate", "N/A")

    st.caption(
        f"📡 Data: yfinance + FRED | "
        f"🔄 Updated: {datetime.now().strftime('%H:%M HKT')} | "
        f"Full US analysis in 🇺🇸 US Radar tab"
    )


# ── Main render ───────────────────────────────────────────────────


def render_china_macro(china_data: dict):
    comp    = china_data.get("composite", {})
    overall = comp.get("overall", "UNKNOWN")
    color   = comp.get("color", "#374151")
    score   = comp.get("score", 0)
    max_s   = comp.get("max_score", 5)
    signals = comp.get("signals", [])
    sched   = china_data.get("lseg_schedule", {})

    with st.expander(
        f"🇨🇳 China Macro Context — {overall} ({score}/{max_s}) | Monthly data | Click to expand",
        expanded=False,
    ):
        st.markdown(
            f'<div style="background:{color};padding:10px;border-radius:6px;margin-bottom:10px">'
            f'<span style="color:white;font-weight:bold">'
            f'China Macro: {overall} — {score}/{max_s}'
            f'</span></div>',
            unsafe_allow_html=True,
        )

        for s in signals:
            st.write(f"• {s}")

        # Next release schedule from LSEG
        sched_parts = []
        if sched.get("next_pmi_date"):
            sched_parts.append(f"PMI: {sched['next_pmi_date']}")
        if sched.get("next_ppi_date"):
            sched_parts.append(f"PPI: {sched['next_ppi_date']}")
        if sched.get("next_cpi_date"):
            sched_parts.append(f"CPI: {sched['next_cpi_date']}")
        if sched.get("next_gdp_date"):
            sched_parts.append(f"GDP: {sched['next_gdp_date']}")
        if sched_parts:
            st.caption("📅 Next releases (LSEG): " + " | ".join(sched_parts))

        st.divider()

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.markdown("**📊 PMI**")
            pmi = china_data.get("pmi", {})
            if not pmi.get("error"):
                mfg     = pmi.get("manufacturing", 0) or 0
                non_mfg = pmi.get("non_manufacturing")
                chg     = pmi.get("mfg_change", 0) or 0
                signal  = pmi.get("signal", "")
                trend   = pmi.get("trend", "")
                icon       = "✅" if signal == "EXPANDING" else "⚠️"
                trend_icon = "▲" if trend == "IMPROVING" else "▼"
                st.metric("Manufacturing PMI", f"{mfg:.1f}", delta=f"{chg:+.1f} MoM")
                st.write(f"{icon} {signal} {trend_icon}")
                if non_mfg:
                    nmfg_icon = "✅" if non_mfg > 50 else "⚠️"
                    st.write(f"Non-mfg PMI: {nmfg_icon} {non_mfg:.1f}")
                # Mini history table
                hist = pmi.get("history", [])
                if hist:
                    rows = [{"Period": h["date"], "Mfg": f"{h['mfg']:.1f}", "Non-mfg": f"{h['nmfg']:.1f}"} for h in hist[-4:]]
                    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
                st.caption(
                    f"50 = expansion threshold | "
                    f"Data: {pmi.get('date', '')} | "
                    + (f"Next: {sched.get('next_pmi_date', '')}" if sched.get("next_pmi_date") else "")
                )
            else:
                st.info(f"PMI unavailable — East Money API ({pmi.get('msg','')[:60]})")
                st.caption("Typically resolves after 18:00 HKT on trading days")

        with col2:
            st.markdown("**💰 Credit (Social Financing)**")
            credit = china_data.get("credit", {})
            if not credit.get("error"):
                sf      = credit.get("social_financing", 0)
                sf_prev = credit.get("social_financing_prev", 0)
                loans   = credit.get("rmb_loans", 0)
                signal  = credit.get("signal", "")
                pct_chg = credit.get("pct_change", 0)
                icon    = "✅" if signal == "STIMULUS" else "⚠️"
                sf_fmt  = (f"{sf/10000:.2f}T RMB" if sf and sf > 10000
                           else f"{sf:.0f}亿" if sf else "N/A")
                sf_prev_fmt = (f"{sf_prev/10000:.2f}T" if sf_prev and sf_prev > 10000
                               else f"{sf_prev:.0f}亿" if sf_prev else "N/A")
                st.metric("Social Financing", sf_fmt, delta=f"{pct_chg:+.1f}% vs prev")
                st.write(f"{icon} {signal}")
                if loans:
                    loans_fmt = f"{loans/10000:.2f}T RMB" if loans > 10000 else f"{loans:.0f}亿"
                    st.write(f"RMB Loans: {loans_fmt}")
                st.write(f"Prev month: {sf_prev_fmt}")
                st.caption(
                    f"Data: {credit.get('date', '')} | "
                    f"Source: {credit.get('source', '')}"
                )
            else:
                st.info(f"Credit data unavailable")

        with col3:
            st.markdown("**🏭 PPI & GDP**")
            ppi = china_data.get("ppi", {})
            if not ppi.get("error"):
                ppi_val   = ppi.get("yoy", 0) or 0
                ppi_sig   = ppi.get("signal", "")
                ppi_trend = ppi.get("trend", "")
                ppi_chg   = ppi.get("change", 0) or 0
                icon       = "✅" if ppi_sig == "REFLATION" else "⚠️"
                trend_icon = "▲" if ppi_trend == "IMPROVING" else "▼"
                st.metric("PPI YoY", f"{ppi_val:+.1f}%", delta=f"{ppi_chg:+.1f}pp MoM")
                st.write(f"{icon} {ppi_sig} {trend_icon}")
                hist_ppi = ppi.get("history", [])
                if hist_ppi:
                    rows = [{"Period": h["date"], "PPI YoY%": f"{h['yoy']:+.1f}"} for h in hist_ppi[-4:]]
                    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
                st.caption(
                    f">0 = reflation / pricing power | "
                    f"Data: {ppi.get('date', '')} | "
                    + (f"Next: {sched.get('next_ppi_date', '')}" if sched.get("next_ppi_date") else "")
                )
            else:
                st.info(f"PPI unavailable ({ppi.get('msg','')[:60]})")

            st.divider()

            gdp = china_data.get("gdp", {})
            if not gdp.get("error"):
                gdp_val    = gdp.get("yoy", 0) or 0
                gdp_sig    = gdp.get("signal", "")
                gdp_chg    = gdp.get("change", 0) or 0
                consensus  = gdp.get("consensus")
                icon_g     = "✅" if gdp_sig == "STRONG" else "➡️" if gdp_sig == "MODERATE" else "⚠️"
                st.metric(f"GDP YoY {gdp.get('quarter','')}", f"{gdp_val:.1f}%",
                          delta=f"{gdp_chg:+.1f}pp vs prev")
                st.write(f"{icon_g} {gdp_sig}")
                if consensus is not None:
                    beat = gdp_val - consensus
                    beat_str = f"{'Beat' if beat >= 0 else 'Miss'} by {abs(beat):.2f}pp"
                    st.write(f"Consensus: {consensus:.2f}% | {beat_str}")
                hist_gdp = gdp.get("history", [])
                if hist_gdp:
                    rows = [{"Quarter": h["quarter"], "GDP YoY%": f"{h['yoy']:.1f}"} for h in hist_gdp[-4:]]
                    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
                st.caption(
                    f"Source: {gdp.get('source','AKShare')} | "
                    + (f"Next: {sched.get('next_gdp_date','')}" if sched.get("next_gdp_date") else "")
                    + (" | LSEG consensus" if consensus is not None else "")
                )
            else:
                st.info(f"GDP unavailable ({gdp.get('msg','')[:60]})")

        with col4:
            st.markdown("**🏘️ Property Sector**")
            prop = china_data.get("property", {})
            if not prop.get("error"):
                avg_3m   = prop.get("avg_3m_change", 0) or 0
                prop_sig = prop.get("signal", "")
                proxies  = prop.get("proxies", [])
                icon     = ("✅" if prop_sig == "RECOVERING"
                            else "➡️" if prop_sig == "STABLE" else "⚠️")
                st.metric("HK-Listed Developers (3M avg)", f"{avg_3m:+.1f}%")
                st.write(f"{icon} **{prop_sig}**")
                for p in proxies[:3]:
                    chg_3m = p.get("change_3m", 0) or 0
                    chg_1m = p.get("change_1m")
                    c3_icon = "📈" if chg_3m > 0 else "📉"
                    c1_str  = f" | 1M: {chg_1m:+.1f}%" if chg_1m is not None else ""
                    st.write(f"{c3_icon} {p['name']}: 3M {chg_3m:+.1f}%{c1_str}")
                st.caption("HK-listed developers as sector proxy | Source: yfinance")
            else:
                st.info("Property data unavailable")

        st.caption(
            f"📅 Monthly data — updates when NBS/PBOC publishes | "
            f"🔄 Cached 24hrs | Last fetched: {fetched} | "
            f"⚠️ CPI excluded — AKShare source unreliable"
        )


def render_flow_monitor():
    """Render the HK/China Flow Monitor dashboard (Phase 2)."""

    st.markdown("""
    <style>
        .fm-main-header { font-size: 2rem; font-weight: 700; margin-bottom: 0; }
        .fm-sub-header  { color: #888; font-size: 1rem; margin-top: 0; }
        .fm-section-title {
            font-size: 1rem; font-weight: 600; color: #9ca3af;
            text-transform: uppercase; letter-spacing: 1px;
            margin: 1rem 0 0.4rem 0; border-bottom: 1px solid #2d3748;
            padding-bottom: 0.3rem;
        }
        .fm-factor-item { font-size: 0.85rem; color: #d1d5db; margin: 0.2rem 0; }
        .fm-action-line {
            font-size: 1.05rem; font-weight: 600; color: #e5e7eb;
            background: #1e2530; border-radius: 8px; padding: 12px 16px;
            margin: 8px 0; border-left: 4px solid #60a5fa;
        }
    </style>
    """, unsafe_allow_html=True)

    # ── Header ────────────────────────────────────────────────────
    col_title, col_btn = st.columns([5, 1])
    with col_title:
        st.markdown('<p class="fm-main-header">🌊 Flow Monitor</p>', unsafe_allow_html=True)
        st.markdown('<p class="fm-sub-header">HK/China Flows & Liquidity Intelligence — Phase 2</p>',
                    unsafe_allow_html=True)
    with col_btn:
        st.write(""); st.write("")
        if st.button("🔄 Refresh", key="fm_refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S HKT')}")

    # ── Data source indicator ─────────────────────────────────────
    _lseg_on = lseg_desktop_available()
    if _lseg_on:
        st.caption("📡 **LSEG connected** — using Refinitiv Workspace as primary data source")
    else:
        st.caption("📡 yfinance / FRED / AKShare mode — LSEG Workspace not detected")

    # ── Fetch all data ────────────────────────────────────────────
    with st.spinner("Fetching live data..."):
        d = _fetch_flow_data()

    fetched_at = d.get("fetched_at", datetime.now().strftime("%Y-%m-%d %H:%M HKT"))

    sc      = d["sc_flows"]
    hsi     = d["hsi"]
    cnh     = d["cnh"]
    pboc    = d["pboc"]
    nb_hist = d["nb_history"]
    hkma    = d["hkma"]
    hibor   = d["hibor"]
    usdhkd  = d["usdhkd"]
    hstech  = d["hstech"]
    cnh_200 = d["usdcnh_200dma"]
    fed     = d["fed"]
    yc      = d["yield_curve"]
    vix     = d["vix"]
    dxy     = d["dxy"]

    _sb          = d["southbound_conviction"]
    sb_table1    = _sb.get("table1", pd.DataFrame())
    sb_table2    = _sb.get("table2", pd.DataFrame())
    sb_conv_full = _sb.get("full", pd.DataFrame())
    sb_date      = _sb.get("data_date", "Unknown")
    sb_fetched   = _sb.get("fetched_at", fetched_at)
    sb_schedule  = _sb.get("update_schedule", "Updates after ~18:00 HKT each trading day")

    def _ts(badge: str, schedule: str) -> str:
        return f"{badge} | ⏰ {schedule} | 🔄 Fetched: {fetched_at}"

    # ── Composite signal ──────────────────────────────────────────
    composite = calculate_composite_signal(d)
    log_daily_signal(composite, d)

    # ── DECISION PANEL ────────────────────────────────────────────
    st.divider()
    dc1, dc2, dc3 = st.columns(3)
    with dc1:
        st.markdown(_stance_badge_html("HK / China", composite["hk_stance"]),
                    unsafe_allow_html=True)
    with dc2:
        st.markdown(_stance_badge_html("US Allocation", composite["us_stance"]),
                    unsafe_allow_html=True)
    with dc3:
        st.markdown(_stance_badge_html("Overall Regime", composite["overall_stance"]),
                    unsafe_allow_html=True)

    st.markdown(
        f'<div class="fm-action-line">📋 {composite["action_line"]}</div>',
        unsafe_allow_html=True,
    )

    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("Gate 1 — Global Liq.", f"{composite['gate1_score']:+d} / 4",
               delta="⚠️ FORCED WAIT" if composite["gate1_forced_wait"] else None,
               delta_color="inverse" if composite["gate1_forced_wait"] else "off")
    sc2.metric("Gate 2 — HK Liq.", f"{composite['gate2_score']:+d} / 3")
    sc3.metric("Gate 3 — Risk App.", f"{composite['gate3_score']:+d} / 3")
    sc4.metric("Combined Score", f"{composite['combined_score']:+.1f} / 10")

    with st.expander("📋 Gate factor breakdown", expanded=False):
        ex1, ex2, ex3 = st.columns(3)
        with ex1:
            st.markdown("**Gate 1 — Global Liquidity**")
            for f in composite["gate1_factors"] or ["No factors (neutral)"]:
                st.markdown(f'<div class="fm-factor-item">• {f}</div>', unsafe_allow_html=True)
        with ex2:
            st.markdown("**Gate 2 — HK Liquidity**")
            for f in composite["gate2_factors"] or ["No factors (neutral)"]:
                st.markdown(f'<div class="fm-factor-item">• {f}</div>', unsafe_allow_html=True)
        with ex3:
            st.markdown("**Gate 3 — Risk Appetite**")
            for f in composite["gate3_factors"] or ["No factors (neutral)"]:
                st.markdown(f'<div class="fm-factor-item">• {f}</div>', unsafe_allow_html=True)

    # ── AI MORNING BRIEFING ───────────────────────────────────────
    st.divider()
    st.subheader("🤖 Morning Briefing")

    _sb_rmb  = (sc.get("southbound") or {}).get("net_flow_rmb_bn") if not _has_error(sc) else None
    _hst_chg = hstech.get("change_pct") if not _has_error(hstech) else None
    _hsi_chg = (hsi.get("hsi") or {}).get("change_pct") if not _has_error(hsi) else None
    _vs_hsi  = (f"{_hst_chg - _hsi_chg:+.1f}pp vs HSI"
                if _hst_chg is not None and _hsi_chg is not None else "N/A")

    _signal_data = {
        "gate1_score":     composite["gate1_score"],
        "gate2_score":     composite["gate2_score"],
        "gate3_score":     composite["gate3_score"],
        "combined_score":  f"{composite['combined_score']:+.1f}",
        "hk_stance":       composite["hk_stance"],
        "us_stance":       composite["us_stance"],
        "overall_stance":  composite["overall_stance"],
        "action_line":     composite["action_line"],
        "hsi_change":      f"{_hsi_chg:+.2f}" if _hsi_chg is not None else "N/A",
        "southbound_hkd":  f"{_sb_rmb:+.1f}" if _sb_rmb is not None else "N/A",
        "vix":             f"{vix.get('vix', 0):.1f}" if not _has_error(vix) else "N/A",
        "dxy":             (f"{dxy.get('price', 0):.1f} ({dxy.get('signal', '')})"
                            if not _has_error(dxy) else "N/A"),
        "yield_10y":       f"{yc.get('yield_10yr', 0):.3f}" if not _has_error(yc) else "N/A",
        "real_yield":      (f"{yc.get('real_yield_10yr', 0):.2f}"
                            if not _has_error(yc) and yc.get("real_yield_10yr") is not None else "N/A"),
        "yield_spread":    f"{yc.get('spread_10_2', 0):+.3f}" if not _has_error(yc) else "N/A",
        "usdcnh":          f"{cnh.get('cnh_per_usd', 0):.4f}" if not _has_error(cnh) else "N/A",
        "usdcnh_signal":   cnh_200.get("signal", "N/A") if not _has_error(cnh_200) else "N/A",
        "hkma_trend":      hkma.get("trend", "N/A") if not _has_error(hkma) else "N/A",
        "hibor_overnight": f"{hibor.get('overnight', 0):.3f}" if not _has_error(hibor) else "N/A",
        "hibor_1month":    f"{hibor.get('one_month', 0):.3f}" if not _has_error(hibor) else "N/A",
        "hibor_trend":     hibor.get("trend", "N/A") if not _has_error(hibor) else "N/A",
        "usdhkd":          f"{usdhkd.get('rate', 0):.4f}" if not _has_error(usdhkd) else "N/A",
        "usdhkd_signal":   usdhkd.get("signal", "N/A") if not _has_error(usdhkd) else "N/A",
        "fed_rate":        f"{fed.get('current_rate', 0):.2f}" if not _has_error(fed) else "N/A",
        "fed_next_meeting": fed.get("next_meeting_date", "N/A") if not _has_error(fed) else "N/A",
        "fed_hold_prob":   (f"{fed.get('prob_hold', 0):.0f}"
                            if not _has_error(fed) and not fed.get("probs_unavailable") else "N/A"),
        "fed_cut25_prob":  (f"{fed.get('prob_cut_25', 0):.0f}"
                            if not _has_error(fed) and not fed.get("probs_unavailable") else "N/A"),
        "hstech_change":   f"{_hst_chg:+.2f}" if _hst_chg is not None else "N/A",
        "hstech_vs_hsi":   _vs_hsi,
        "top_institutional_stocks": (
            ", ".join(sb_table1["name"].head(3).tolist())
            if not sb_table1.empty else "none"
        ),
        "top_intensity_stocks": (
            ", ".join(sb_table2["name"].head(3).tolist())
            if not sb_table2.empty else "none"
        ),
        "southbound_data_date": sb_date,
    }

    def _briefing_stale() -> bool:
        ts = st.session_state.get("briefing_timestamp")
        if ts is None:
            return True
        if ts.date() < datetime.now().date():
            return True
        return (datetime.now() - ts).total_seconds() > 4 * 3600

    br_col, btn_col = st.columns([5, 1])
    with btn_col:
        st.write("")
        _force_refresh = st.button("🔄 Refresh", key="briefing_refresh",
                                   use_container_width=True)

    if _force_refresh or _briefing_stale():
        with st.spinner("Generating briefing…"):
            _text = generate_briefing(_signal_data,
                                      system_prompt_override=_HK_BRIEFING_PROMPT)
        if _text:
            st.session_state["briefing_text"]      = _text
            st.session_state["briefing_timestamp"] = datetime.now()

    _cached_text = st.session_state.get("briefing_text", "")
    _cached_ts   = st.session_state.get("briefing_timestamp")

    with br_col:
        if not _cached_text:
            st.info("Add ANTHROPIC_API_KEY to .env to enable the AI morning briefing.")
        else:
            st.markdown(
                f'<div style="background:#1e2530;border-radius:8px;padding:14px 18px;'
                f'border-left:4px solid #60a5fa;font-size:0.97rem;color:#e5e7eb;'
                f'line-height:1.6">{_cached_text}</div>',
                unsafe_allow_html=True,
            )
            if _cached_ts:
                st.caption(f"Generated: {_cached_ts.strftime('%Y-%m-%d %H:%M')} · "
                           "refreshes daily or every 4 hours")

    st.divider()

    # ════════════════════════════════════════════════════════════
    # HK/CHINA FLOWS & LIQUIDITY
    # ════════════════════════════════════════════════════════════
    st.markdown('<div class="fm-section-title">📊 HK/China Flows & Liquidity</div>',
                unsafe_allow_html=True)

    # Stock Connect
    st.markdown("**Stock Connect Today**")
    st.caption(_ts(_live_badge(sc, "AKShare"), "Updates after ~18:00 HKT each trading day (East Money post-close processing)"))
    if _has_error(sc):
        st.info("Unavailable — AKShare did not return Stock Connect data")
    else:
        nb = sc.get("northbound", {})
        sb = sc.get("southbound", {})
        sb_net = sb.get("net_flow_hkd", 0) or 0
        cm1, cm2 = st.columns(2)
        with cm1:
            st.metric("Northbound", "N/A (suspended)",
                      delta=nb.get("note", "Suspended Nov 2023"), delta_color="off")
        with cm2:
            sb_rmb = sb.get("net_flow_rmb_bn")
            sb_label = f"Net: {sb_rmb:+.1f}亿 RMB" if sb_rmb is not None else f"Net: {_fmt_hkd(sb_net)}"
            st.metric("Southbound (HK→Mainland)",
                      _fmt_hkd(abs(sb_net)) if sb_net else "—",
                      delta=f"{sb_label}  {sb.get('signal', '')}",
                      delta_color="normal" if sb_net >= 0 else "inverse")

    st.divider()

    # Southbound chart
    st.markdown("**Southbound Flow — Last 30 Days**")
    if nb_hist.empty:
        st.info("Unavailable — AKShare did not return flow history")
    else:
        st.caption(
            f"🔵 Live southbound via AKShare (northbound suspended Nov 2023) | "
            f"⚠️ HKEX publishes with 1 business day lag — today's flows appear tomorrow morning | "
            f"📅 Data as of: {sb_date} | ⏰ Updates after ~08:00 HKT next business day"
        )
        fig = _make_nb_chart(nb_hist)
        fig.update_layout(title="Southbound Flow — HK Connect to Mainland (亿元 RMB × 1.07 ≈ HKD)")
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── Southbound Conviction (two Z-score tables) ───────────
    _sb_avail = not _sb.get("error", True)

    def _accel_s(a) -> str:
        if a is None or not pd.notna(a): return "N/A"
        arrow = " ▲" if float(a) > 1.2 else (" ▼" if float(a) < 0.8 else "")
        return f"{float(a):.1f}x{arrow}"

    st.subheader(f"🎯 Southbound Conviction — True Buying as of {sb_date}")

    if _sb_avail:
        st.caption(
            f"📅 Data as of: {sb_date} "
            f"(HKEX publishes with 1 business day lag — "
            f"today's flows appear tomorrow morning) | "
            f"⏰ Updates after ~08:00 HKT next business day | "
            f"🔄 Last fetched: {sb_fetched}"
        )
        st.caption("⚡ First daily load fetches market caps — subsequent loads are instant from cache")
    else:
        st.caption(
            f"🔄 Last fetch attempt: {sb_fetched} — API unavailable | "
            f"⏰ {sb_schedule}"
        )

    # ── Ticker lookup ─────────────────────────────────────────
    st.markdown("**🔍 Look Up Any Stock**")
    _lk1, _lk2 = st.columns([3, 1])
    with _lk1:
        _sb_raw = st.text_input(
            "HK ticker", key="sb_lookup_ticker",
            placeholder="e.g. 0700, 9988, 2318",
            label_visibility="collapsed",
        )
    with _lk2:
        st.button("Check Flow", key="sb_lookup_btn", use_container_width=True)

    if _sb_raw.strip():
        _cc = _sb_raw.strip().upper().replace(".HK", "").strip()
        try:
            _cp = str(int(_cc)).zfill(5)
        except ValueError:
            _cp = _cc.zfill(5)
        _lt = _cp + ".HK"
        if not sb_conv_full.empty and "ticker" in sb_conv_full.columns:
            _m = sb_conv_full[sb_conv_full["ticker"] == _lt]
            if not _m.empty:
                _r = _m.iloc[0]
                _nb  = _r["net_buy_hkd"] / 1e6
                _sth = _r.get("sb_hold_pct")
                _fi  = _r.get("flow_intensity_pct")
                _sc1 = _r.get("score_t1")
                _sts = _r.get("stars", "—")
                st.success(
                    f"📊 **{_r['name']} ({_cp}.HK)** — as of {_r.get('data_date', sb_date)}  \n"
                    f"True Net Buy: **{_nb:+,.1f}M HKD** | "
                    f"Flow Intensity: **{f'{_fi:.2f}% of mkt cap' if _fi is not None and pd.notna(_fi) else 'N/A'}** | "
                    f"5D Accel: **{_accel_s(_r.get('acceleration'))}** | "
                    f"SB Hold: **{f'{_sth:.1f}%' if _sth is not None and pd.notna(_sth) else 'N/A'}** | "
                    f"Score T1: **{f'{_sc1:.2f}' if _sc1 is not None and pd.notna(_sc1) else 'N/A'}** | "
                    f"**{_sts}**"
                )
            else:
                st.warning(
                    f"⚠️ {_lt} not found in southbound data — "
                    "either not Stock Connect eligible or no flow on data date"
                )
        else:
            st.info("Full dataset unavailable for lookup.")

    st.divider()

    # ── Table 1: Institutional Flow ───────────────────────────
    st.subheader("🏦 Table 1 — Institutional Flow (Absolute Size)")
    st.caption("Ranks by absolute southbound buying. Shows where serious money is flowing in size. Best for validating large-cap holdings.")

    if sb_table1.empty:
        from flow_core.signal_logger import get_signal_history as _get_hist
        _hist = _get_hist(days=7)
        if not _hist.empty and "date" in _hist.columns:
            _last_dt = _hist["date"].max()
            _last_msg = f"Last successful data: {_last_dt.strftime('%Y-%m-%d') if hasattr(_last_dt, 'strftime') else str(_last_dt)}"
        else:
            _last_msg = "No recent data in history"
        st.warning(
            f"⚠️ East Money (AKShare) API temporarily unavailable — connection dropped. "
            f"{_last_msg}. "
            f"Will retry automatically on next refresh (~30 min). "
            f"East Money processes end-of-day data 16:00–18:00 HKT — check back after 18:00 HKT."
        )
    else:
        _t1_rows = []
        for _, _r in sb_table1.iterrows():
            _code = _r["ticker"].replace(".HK", "")
            _sth  = _r.get("sb_hold_pct")
            _pchg = _r["price_change_1d"]
            _t1_rows.append({
                "Stock":           f"{_r['name']} ({_code}.HK)",
                "Net Buy (HKD M)": round(_r["net_buy_hkd"] / 1e6, 0),
                "SB Hold%":        f"{_sth:.1f}%" if _sth is not None and pd.notna(_sth) else "N/A",
                "5D Accel":        _accel_s(_r.get("acceleration")),
                "Price 1D%":       f"{_pchg:+.2f}%" if pd.notna(_pchg) else "N/A",
                "Score":           f"{_r['score_t1']:.2f}",
                "★":               _r.get("stars", "—"),
            })
        _t1_df = pd.DataFrame(_t1_rows)
        st.dataframe(
            _t1_df, use_container_width=True, hide_index=True,
            column_config={
                "Stock":           st.column_config.TextColumn("Stock", width="medium"),
                "Net Buy (HKD M)": st.column_config.NumberColumn("Net Buy (HKD M)", format="%+,.0f"),
                "SB Hold%":        st.column_config.TextColumn("SB Hold%", width="small"),
                "5D Accel":        st.column_config.TextColumn("5D Accel", width="small"),
                "Price 1D%":       st.column_config.TextColumn("Price 1D%", width="small"),
                "Score":           st.column_config.TextColumn("Score", width="small"),
                "★":               st.column_config.TextColumn("★", width="small"),
            },
        )

    st.divider()

    # ── Table 2: Flow Intensity ───────────────────────────────
    st.subheader("🔭 Table 2 — Flow Intensity (vs Market Cap)")
    st.caption("Ranks by buying intensity relative to firm size. Surfaces early rotation in small/mid caps before headlines. Min HKD 30M absolute flow. Best for spotting emerging themes.")

    if sb_table2.empty:
        st.info(
            "📊 Flow intensity table unavailable — "
            "market cap data could not be computed. "
            "This recovers automatically when AKShare data loads."
        )
    else:
        _t2_rows = []
        for _, _r in sb_table2.iterrows():
            _code = _r["ticker"].replace(".HK", "")
            _pchg = _r["price_change_1d"]
            _mc   = _r.get("market_cap_hkd")
            _t2_rows.append({
                "Stock":           f"{_r['name']} ({_code}.HK)",
                "Flow/Mkt Cap%":   f"{_r['flow_intensity_pct']:.2f}%",
                "Net Buy (HKD M)": round(_r["net_buy_hkd"] / 1e6, 0),
                "Mkt Cap (HKD B)": f"{_mc/1e9:.1f}B" if _mc and pd.notna(_mc) else "N/A",
                "5D Accel":        _accel_s(_r.get("acceleration")),
                "Price 1D%":       f"{_pchg:+.2f}%" if pd.notna(_pchg) else "N/A",
                "Score":           f"{_r['score_t2']:.2f}",
                "★":               _r.get("stars", "—"),
            })
        _t2_df = pd.DataFrame(_t2_rows)
        st.dataframe(
            _t2_df, use_container_width=True, hide_index=True,
            column_config={
                "Stock":           st.column_config.TextColumn("Stock", width="medium"),
                "Flow/Mkt Cap%":   st.column_config.TextColumn("Flow/Mkt Cap%", width="medium"),
                "Net Buy (HKD M)": st.column_config.NumberColumn("Net Buy (HKD M)", format="%+,.0f"),
                "Mkt Cap (HKD B)": st.column_config.TextColumn("Mkt Cap (HKD B)", width="small"),
                "5D Accel":        st.column_config.TextColumn("5D Accel", width="small"),
                "Price 1D%":       st.column_config.TextColumn("Price 1D%", width="small"),
                "Score":           st.column_config.TextColumn("Score", width="small"),
                "★":               st.column_config.TextColumn("★", width="small"),
            },
        )

    st.caption(
        "True Net Buy = share count change × price (excludes price appreciation on existing holdings). "
        f"Mkt cap estimated from AKShare holding value ÷ SB ownership %. Min HKD 30M filter applied. "
        f"★ = percentile within table universe. Source: AKShare/HKEX, as of {sb_date}."
    )

    st.divider()

    # HSI / HSCEI
    st.markdown("**HSI / HSCEI**")
    st.caption(_ts(_live_badge(hsi, "yfinance"), "15-min delay during market hours"))
    if _has_error(hsi):
        st.info("Unavailable — yfinance did not return HSI data")
    else:
        hm1, hm2 = st.columns(2)
        hsi_d   = hsi.get("hsi", {})
        hscei_d = hsi.get("hscei", {})
        with hm1:
            st.metric("HSI", f"{hsi_d.get('level', 0):,.0f}",
                      delta=f"{hsi_d.get('change_pct', 0):+.2f}%",
                      delta_color="normal" if (hsi_d.get("change_pct") or 0) >= 0 else "inverse")
        with hm2:
            st.metric("HSCEI", f"{hscei_d.get('level', 0):,.0f}",
                      delta=f"{hscei_d.get('change_pct', 0):+.2f}%",
                      delta_color="normal" if (hscei_d.get("change_pct") or 0) >= 0 else "inverse")
        spread = hsi.get("spread", 0) or 0
        st.caption(f"HSI-HSCEI Spread: {spread:,.0f}"
                   + (" ⚠️ Diverging" if abs(spread) > 20000 else ""))

    st.divider()

    # HSTECH
    st.markdown("**Hang Seng Tech Index**")
    st.caption(_ts(_live_badge(hstech, _src(hstech) or "yfinance"), "15-min delay during market hours"))
    if _has_error(hstech):
        st.info("Unavailable — HSTECH data could not be fetched")
    else:
        hst_chg = hstech.get("change_pct", 0) or 0
        hsi_chg = (hsi.get("hsi") or {}).get("change_pct", 0) or 0 if not _has_error(hsi) else 0
        vs_hsi  = hst_chg - hsi_chg
        vs_label = f"vs HSI: {vs_hsi:+.2f}pp"
        st.metric("HSTECH", f"{hstech.get('price', 0):,.0f}",
                  delta=f"{hst_chg:+.2f}%  ({vs_label})",
                  delta_color="normal" if hst_chg >= 0 else "inverse")

    st.divider()

    # CNH/CNY spread
    st.markdown("**CNH/CNY Spread**")
    st.caption(_ts(_live_badge(cnh, "yfinance"), "15-min delay during market hours"))
    if _has_error(cnh):
        st.info("Unavailable — yfinance did not return CNH/CNY data")
    else:
        cnh_val     = cnh.get("cnh_per_usd", 0) or 0
        cny_val     = cnh.get("cny_per_usd", 0) or 0
        spread_pips = cnh.get("spread_pips", 0) or 0
        cnh_signal  = cnh.get("signal", "STABLE")
        cm1, cm2, cm3 = st.columns(3)
        with cm1:
            st.metric("CNH/USD", f"{cnh_val:.4f}")
        with cm2:
            st.metric("CNY/USD", f"{cny_val:.4f}")
        with cm3:
            st.metric("Spread", f"{spread_pips:.0f} pips",
                      delta=f"{_signal_emoji(cnh_signal)} {cnh_signal}")
        color_map = {"STABLE": "🟢", "MILD_PRESSURE": "🟡", "STRESS": "🔴"}
        st.markdown(f"{color_map.get(cnh_signal, '⚪')} CNH signal: **{cnh_signal}**")

    st.divider()

    # USD/CNH vs 200DMA
    st.markdown("**USD/CNH vs 200-Day MA**")
    st.caption(_ts(_live_badge(cnh_200, _src(cnh_200) or "yfinance"), "15-min delay during market hours"))
    if _has_error(cnh_200):
        st.info("Unavailable — USD/CNH history could not be fetched")
    else:
        sig200 = cnh_200.get("signal", "")
        color200 = {"BELOW_200DMA": "🟢", "ABOVE_200DMA": "🔴"}.get(sig200, "⚪")
        c200a, c200b = st.columns(2)
        with c200a:
            st.metric("Current", f"{cnh_200.get('current', 0):.4f}")
        with c200b:
            st.metric("200DMA", f"{cnh_200.get('ma200', 0):.4f}")
        st.markdown(f"{color200} Signal: **{sig200}** {_signal_emoji(sig200)}")
        st.caption("Below 200DMA = RMB stable/strengthening; Above = weakening pressure")

    st.divider()

    # HKMA Aggregate Balance
    st.markdown("**HKMA Aggregate Balance**")
    st.caption(_ts(_live_badge(hkma, _src(hkma) or "HKMA API"), "Updates daily ~19:00 HKT each business day"))
    if _has_error(hkma):
        st.info("Unavailable — HKMA balance data could not be fetched")
    else:
        bal_bn  = (hkma.get("balance") or 0) / 1e9 if (hkma.get("balance") or 0) > 1e6 else hkma.get("balance") or 0
        trend   = hkma.get("trend", "STABLE")
        t_color = {"EXPANDING": "🟢", "STABLE": "🟡", "CONTRACTING": "🔴"}.get(trend, "⚪")
        st.metric("Aggregate Balance",
                  f"HKD {bal_bn:.1f}B" if bal_bn > 1 else f"HKD {hkma.get('balance', 0):,.0f}",
                  delta=f"{_signal_emoji(trend)} {trend}")
        st.markdown(f"{t_color} Trend: **{trend}**")

    st.divider()

    # HIBOR
    st.markdown("**HIBOR Rates**")
    st.caption(_ts(_live_badge(hibor, _src(hibor) or "HKMA API"), "Updates daily ~19:00 HKT each business day"))
    if _has_error(hibor):
        st.info("Unavailable — HIBOR data could not be fetched")
    else:
        hb1, hb2 = st.columns(2)
        trend_h = hibor.get("trend", "STABLE")
        t_color_h = {"FALLING": "🟢", "STABLE": "🟡", "RISING": "🔴"}.get(trend_h, "⚪")
        with hb1:
            st.metric("Overnight", f"{hibor.get('overnight', 0):.3f}%")
        with hb2:
            st.metric("1-Month", f"{hibor.get('one_month', 0):.3f}%",
                      delta=f"{_signal_emoji(trend_h)} {trend_h}")
        st.markdown(f"{t_color_h} HIBOR trend: **{trend_h}**")

    st.divider()

    # USD/HKD
    st.markdown("**USD/HKD Peg Monitor**")
    st.caption(_ts(_live_badge(usdhkd, _src(usdhkd) or "yfinance"), "15-min delay during market hours"))
    if _has_error(usdhkd):
        st.info("Unavailable — USD/HKD data could not be fetched")
    else:
        peg_sig   = usdhkd.get("signal", "SAFE")
        peg_color = {"SAFE": "🟢", "WATCH": "🟡", "ALERT": "🔴"}.get(peg_sig, "⚪")
        st.metric("USD/HKD", f"{usdhkd.get('rate', 0):.4f}",
                  delta=f"{usdhkd.get('distance_pips', 0):.0f} pips from 7.85  {peg_sig}",
                  delta_color="normal" if peg_sig == "SAFE" else "inverse")
        st.markdown(f"{peg_color} Peg signal: **{peg_sig}**")
        st.caption("HKMA defends 7.75–7.85 band. ALERT = <50 pips from weak side.")

    st.divider()

    # PBOC rate
    st.markdown("**PBOC Policy Rate**")
    st.caption(_ts(_live_badge(pboc, "FRED"), "Updates daily ~05:00 HKT (prior US ET day)"))
    if _has_error(pboc):
        st.info(f"Unavailable — FRED INTDSRCNM193N (checked {pboc.get('date', '—')})")
    else:
        pboc_rate = pboc.get("rate", 0) or 0
        pboc_chg  = pboc.get("change_from_prev", 0) or 0
        st.metric("7-Day Reverse Repo Rate", f"{pboc_rate:.2f}%",
                  delta=f"{pboc_chg:+.2f}% vs prev" if pboc_chg else "Unchanged")
        if pboc.get("date"):
            st.caption(f"As of: {pboc['date']}")

    # ── GLOBAL CONTEXT PANEL ──────────────────────────────────
    st.divider()
    render_global_context(d)

    # ── SIGNAL HISTORY ────────────────────────────────────────
    st.divider()
    st.markdown('<div class="fm-section-title">📈 Signal History (Real Data)</div>',
                unsafe_allow_html=True)

    hist_df = get_signal_history(days=90)

    if len(hist_df) < 2:
        st.info(
            "Signal history is building — check back tomorrow. "
            "First entry logged today."
        )
    else:
        fig_hist = go.Figure()

        bar_colors = [
            "#4ade80" if (v or 0) >= 0 else "#f87171"
            for v in hist_df["combined_score"].fillna(0)
        ]
        fig_hist.add_trace(go.Bar(
            x=hist_df["date"],
            y=hist_df["combined_score"],
            marker_color=bar_colors,
            name="Composite Score",
            opacity=0.8,
            hovertemplate="%{x|%Y-%m-%d}<br>Score: %{y:+.1f}<extra></extra>",
        ))

        hsi_mask = hist_df["hsi_change"].notna()
        if hsi_mask.any():
            fig_hist.add_trace(go.Scatter(
                x=hist_df.loc[hsi_mask, "date"],
                y=hist_df.loc[hsi_mask, "hsi_change"],
                mode="lines+markers",
                line=dict(color="#60a5fa", width=2),
                marker=dict(size=4),
                name="HSI Daily Return %",
                yaxis="y2",
                hovertemplate="%{x|%Y-%m-%d}<br>HSI: %{y:+.2f}%<extra></extra>",
            ))

        fig_hist.update_layout(
            title="30-Day Composite Score vs HSI Daily Return",
            template="plotly_dark",
            height=320,
            margin=dict(l=10, r=10, t=40, b=10),
            yaxis=dict(title="Composite Score (−10 to +10)", zeroline=True,
                       zerolinecolor="white", zerolinewidth=1),
            yaxis2=dict(title="HSI Return %", overlaying="y", side="right",
                        showgrid=False),
            legend=dict(orientation="h", y=1.05),
            hovermode="x unified",
        )
        st.plotly_chart(fig_hist, use_container_width=True)

        first_date = hist_df["date"].min().strftime("%Y-%m-%d")
        st.caption(f"Source: local SQLite — real data only, logging started {first_date}")

        st.markdown("**Last 7 Days**")
        last7 = hist_df.tail(7).sort_values("date", ascending=False).copy()

        def _trunc(s, n=70):
            s = str(s) if pd.notna(s) else "—"
            return s[:n] + "…" if len(s) > n else s

        summary = pd.DataFrame({
            "Date":        last7["date"].dt.strftime("%Y-%m-%d"),
            "Score":       last7["combined_score"].apply(
                               lambda v: f"{v:+.1f}" if pd.notna(v) else "—"),
            "HK Stance":   last7["hk_stance"].fillna("—"),
            "US Stance":   last7["us_stance"].fillna("—"),
            "Action Line": last7["action_line"].apply(_trunc),
        })
        st.dataframe(summary, use_container_width=True, hide_index=True)

    # ── China Macro Monthly Block ──────────────────────────────
    china_data = d.get("china_macro")
    if china_data and not china_data.get("error"):
        render_china_macro(china_data)

    # ── Footer ────────────────────────────────────────────────
    st.divider()
    st.caption(
        "Flow Monitor Phase 2 | Data: LSEG / yfinance / FRED / AKShare / HKMA API | "
        "Not investment advice. "
        f"Rendered: {datetime.now().strftime('%Y-%m-%d %H:%M')} HKT"
    )
