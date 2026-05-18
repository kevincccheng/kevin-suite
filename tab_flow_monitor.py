"""Flow Monitor tab — Phase 2: hierarchical scoring, LSEG primary, full signal suite."""

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
)
from flow_core.us_macro import (
    get_fed_expectations,
    get_yield_curve,
    get_vix,
    get_etf_flows,
    get_dxy,
)
from flow_core.composite import calculate_composite_signal
from flow_core.signal_logger import log_daily_signal, get_signal_history
from flow_core.ai_briefing import generate_briefing
from core.lseg_data import lseg_desktop_available


@st.cache_data(ttl=900)
def _fetch_flow_data():
    return {
        "sc_flows":      get_stock_connect_flows(),
        "hsi":           get_hsi_data(),
        "cnh":           get_cnh_cny_spread(),
        "pboc":          get_pboc_rate(),
        "nb_history":    get_stock_connect_history(30),
        "hkma":          get_hkma_balance(),
        "hibor":         get_hibor(),
        "usdhkd":        get_usdhkd(),
        "hstech":        get_hstech(),
        "usdcnh_200dma": get_usdcnh_200dma(),
        "fed":           get_fed_expectations(),
        "yield_curve":   get_yield_curve(),
        "vix":           get_vix(),
        "dxy":           get_dxy(),
        "etfs":          get_etf_flows(),
    }


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
    """Return (bg, text_color) for a stance badge."""
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


def _make_etf_chart(etfs: list) -> go.Figure:
    if not etfs:
        return go.Figure()
    df = pd.DataFrame(etfs)
    if "change_pct_1d" not in df.columns:
        return go.Figure()
    df = df.dropna(subset=["change_pct_1d"])
    colors = ["#4ade80" if v > 0 else "#f87171" for v in df["change_pct_1d"]]
    fig = go.Figure(go.Bar(
        x=df["ticker"], y=df["change_pct_1d"],
        marker_color=colors,
        text=[f"{v:+.1f}%" for v in df["change_pct_1d"]],
        textposition="outside",
        hovertemplate="%{x}<br>1d: %{y:.2f}%<extra></extra>",
    ))
    fig.add_hline(y=0, line_width=1, line_color="white", opacity=0.3)
    fig.update_layout(
        title="ETF 1-Day Performance",
        template="plotly_dark", height=260,
        margin=dict(l=10, r=10, t=40, b=10),
        yaxis_title="Change %",
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


# ── Main render ───────────────────────────────────────────────────


def render_flow_monitor():
    """Render the full Flow Monitor dashboard (Phase 2) inside the kevin-suite tab."""

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
        st.markdown('<p class="fm-sub-header">HK/China + US Macro Intelligence — Phase 2</p>',
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

    sc       = d["sc_flows"]
    hsi      = d["hsi"]
    cnh      = d["cnh"]
    pboc     = d["pboc"]
    nb_hist  = d["nb_history"]
    hkma     = d["hkma"]
    hibor    = d["hibor"]
    usdhkd   = d["usdhkd"]
    hstech   = d["hstech"]
    cnh_200  = d["usdcnh_200dma"]
    fed      = d["fed"]
    yc       = d["yield_curve"]
    vix      = d["vix"]
    dxy      = d["dxy"]
    etfs     = d["etfs"]

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

    # Score row
    cs = composite["combined_score"]
    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("Gate 1 — Global Liq.", f"{composite['gate1_score']:+d} / 4",
               delta="⚠️ FORCED WAIT" if composite["gate1_forced_wait"] else None,
               delta_color="inverse" if composite["gate1_forced_wait"] else "off")
    sc2.metric("Gate 2 — HK Liq.", f"{composite['gate2_score']:+d} / 3")
    sc3.metric("Gate 3 — Risk App.", f"{composite['gate3_score']:+d} / 3")
    sc4.metric("Combined Score", f"{cs:+.1f} / 10")

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

    # Assemble signal_data from all fetched values
    _sb_rmb = (sc.get("southbound") or {}).get("net_flow_rmb_bn") if not _has_error(sc) else None
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
        "fed_next_meeting":fed.get("next_meeting_date", "N/A") if not _has_error(fed) else "N/A",
        "fed_hold_prob":   (f"{fed.get('prob_hold', 0):.0f}"
                            if not _has_error(fed) and not fed.get("probs_unavailable") else "N/A"),
        "fed_cut25_prob":  (f"{fed.get('prob_cut_25', 0):.0f}"
                            if not _has_error(fed) and not fed.get("probs_unavailable") else "N/A"),
        "hstech_change":   f"{_hst_chg:+.2f}" if _hst_chg is not None else "N/A",
        "hstech_vs_hsi":   _vs_hsi,
        "etf_summary":     [{"ticker": e["ticker"], "change_1d": e["change_pct_1d"]}
                             for e in (etfs or [])[:3]],
    }

    # Cache logic: regenerate if new day, >4h old, or forced refresh
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
            _text = generate_briefing(_signal_data)
        if _text:  # non-empty = success or "unavailable" message
            st.session_state["briefing_text"]      = _text
            st.session_state["briefing_timestamp"] = datetime.now()
        # empty string means no API key — don't cache, show info instead

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

    # ── TWO-COLUMN LAYOUT ─────────────────────────────────────────
    left, right = st.columns(2, gap="large")

    # ════════════════════════════════════════════════════════════
    # LEFT: HK/CHINA
    # ════════════════════════════════════════════════════════════
    with left:
        st.markdown('<div class="fm-section-title">📊 HK/China Flows & Liquidity</div>',
                    unsafe_allow_html=True)

        # Stock Connect
        st.markdown("**Stock Connect Today**")
        st.caption(_live_badge(sc, "AKShare"))
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
            st.caption("🔵 Live southbound via AKShare (northbound suspended Nov 2023)")
            fig = _make_nb_chart(nb_hist)
            fig.update_layout(title="Southbound Flow — HK Connect to Mainland (亿元 RMB × 1.07 ≈ HKD)")
            st.plotly_chart(fig, use_container_width=True)

        st.divider()

        # HSI / HSCEI
        st.markdown("**HSI / HSCEI**")
        st.caption(_live_badge(hsi, "yfinance"))
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
        st.caption(_live_badge(hstech, _src(hstech) or "yfinance"))
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
        st.caption(_live_badge(cnh, "yfinance"))
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
        st.caption(_live_badge(cnh_200, _src(cnh_200) or "yfinance"))
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
        st.caption(_live_badge(hkma, _src(hkma) or "HKMA API"))
        if _has_error(hkma):
            st.info("Unavailable — HKMA balance data could not be fetched")
        else:
            bal_bn  = (hkma.get("balance") or 0) / 1e9 if (hkma.get("balance") or 0) > 1e6 else hkma.get("balance") or 0
            chg_bn  = (hkma.get("change") or 0)
            trend   = hkma.get("trend", "STABLE")
            t_color = {"EXPANDING": "🟢", "STABLE": "🟡", "CONTRACTING": "🔴"}.get(trend, "⚪")
            st.metric("Aggregate Balance",
                      f"HKD {bal_bn:.1f}B" if bal_bn > 1 else f"HKD {hkma.get('balance', 0):,.0f}",
                      delta=f"{_signal_emoji(trend)} {trend}")
            st.markdown(f"{t_color} Trend: **{trend}**")

        st.divider()

        # HIBOR
        st.markdown("**HIBOR Rates**")
        st.caption(_live_badge(hibor, _src(hibor) or "HKMA API"))
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
        st.caption(_live_badge(usdhkd, _src(usdhkd) or "yfinance"))
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
        st.caption(_live_badge(pboc, "FRED"))
        if _has_error(pboc):
            st.info(f"Unavailable — FRED INTDSRCNM193N (checked {pboc.get('date', '—')})")
        else:
            pboc_rate = pboc.get("rate", 0) or 0
            pboc_chg  = pboc.get("change_from_prev", 0) or 0
            st.metric("7-Day Reverse Repo Rate", f"{pboc_rate:.2f}%",
                      delta=f"{pboc_chg:+.2f}% vs prev" if pboc_chg else "Unchanged")
            if pboc.get("date"):
                st.caption(f"As of: {pboc['date']}")

    # ════════════════════════════════════════════════════════════
    # RIGHT: US MACRO
    # ════════════════════════════════════════════════════════════
    with right:
        st.markdown('<div class="fm-section-title">🇺🇸 US Macro</div>', unsafe_allow_html=True)

        # DXY
        st.markdown("**DXY Dollar Index**")
        st.caption(_live_badge(dxy, _src(dxy) or "yfinance"))
        if _has_error(dxy):
            st.info("Unavailable — DXY data could not be fetched")
        else:
            dxy_sig   = dxy.get("signal", "NEUTRAL")
            dxy_color = {"WEAK": "🟢", "NEUTRAL": "🟡", "STRONG": "🔴"}.get(dxy_sig, "⚪")
            st.metric("DXY", f"{dxy.get('price', 0):.2f}",
                      delta=f"{dxy.get('change_pct', 0):+.2f}%  {dxy_sig}",
                      delta_color="inverse" if dxy_sig == "STRONG" else
                                  "normal" if dxy_sig == "WEAK" else "off")
            st.markdown(f"{dxy_color} DXY: **{dxy_sig}** — "
                        + ("Weak USD = liquidity supportive" if dxy_sig == "WEAK"
                           else "Strong USD = liquidity headwind" if dxy_sig == "STRONG"
                           else "Neutral USD conditions"))

        st.divider()

        # Fed Expectations
        st.markdown("**Fed Expectations**")
        st.caption(_live_badge(fed, "FRED + CME ZQ futures"))
        if _has_error(fed):
            st.info("Unavailable — FRED DFF did not return data")
        else:
            fm1, fm2 = st.columns(2)
            with fm1:
                st.metric("Current Fed Rate", f"{fed.get('current_rate', 0):.2f}%")
            with fm2:
                st.metric("Next FOMC", fed.get("next_meeting_date", "—"))
            if fed.get("probs_unavailable"):
                st.info("Meeting probabilities unavailable — CME ZQ futures unavailable")
            else:
                prob_cols = st.columns(4)
                for col, (lbl, key) in zip(prob_cols, [
                    ("Hold", "prob_hold"), ("Cut 25bp", "prob_cut_25"),
                    ("Cut 50bp", "prob_cut_50"), ("Hike", "prob_hike"),
                ]):
                    with col:
                        val = fed.get(key)
                        col.metric(lbl, f"{val:.0f}%" if val is not None else "—")
                if fed.get("futures_ticker"):
                    st.caption(
                        f"Implied from {fed['futures_ticker']} @ {fed.get('futures_price', '—')} "
                        f"→ post-meeting rate ~{fed.get('implied_post_rate', '—')}%"
                    )

        st.divider()

        # Yield Curve + Real Yield
        st.markdown("**US Treasury Yield Curve**")
        st.caption(_live_badge(yc, "FRED"))
        if _has_error(yc):
            st.info("Unavailable — FRED Treasury yields did not return data")
        else:
            yc_signal = yc.get("signal", "NORMAL")
            ym1, ym2, ym3, ym4 = st.columns(4)
            with ym1:
                st.metric("2yr",  f"{yc.get('yield_2yr',  0):.3f}%")
            with ym2:
                st.metric("10yr", f"{yc.get('yield_10yr', 0):.3f}%")
            with ym3:
                st.metric("30yr", f"{yc.get('yield_30yr', 0):.3f}%"
                          if yc.get("yield_30yr") else "—")
            with ym4:
                ry = yc.get("real_yield_10yr")
                ry_color = "🔴" if (ry or 0) > 2.5 else ("🟡" if (ry or 0) > 1.5 else "🟢")
                st.metric("Real 10yr", f"{ry:.2f}%" if ry else "—",
                          help="TIPS real yield (DFII10). >2.5% = restrictive for risk assets.")
            spread_10_2 = yc.get("spread_10_2", 0) or 0
            color_yc = {"NORMAL": "🟢", "FLAT": "🟡", "INVERTED": "🔴"}.get(yc_signal, "⚪")
            st.markdown(
                f"{color_yc} 10yr-2yr: **{spread_10_2:+.3f}%** → **{yc_signal}**"
                + (f"  |  Real 10yr: {ry_color} **{ry:.2f}%**" if ry else "")
            )

        st.divider()

        # VIX
        st.markdown("**VIX Fear Index**")
        st.caption(_live_badge(vix, "yfinance"))
        if _has_error(vix):
            st.info("Unavailable — yfinance VIX unavailable")
        else:
            vix_level = vix.get("vix", 0) or 0
            vix_chg   = vix.get("change_pct", 0) or 0
            vix_sig   = vix.get("signal", "CALM")
            vix_color = {"CALM": "🟢", "ELEVATED": "🟡", "FEAR": "🟠", "PANIC": "🔴"}.get(vix_sig, "⚪")
            st.metric(f"VIX   {vix_color} {vix_sig}", f"{vix_level:.2f}",
                      delta=f"{vix_chg:+.1f}%", delta_color="inverse")

        st.divider()

        # ETF Monitor
        st.markdown("**Key ETF Monitor**")
        etf_src = "LSEG" if (etfs and etfs[0].get("source") == "LSEG") else "yfinance"
        st.caption(f"🔵 Live via {etf_src}" if etfs else "🟡 Unavailable")
        if not etfs:
            st.info("Unavailable — ETF data could not be fetched")
        else:
            df_etf = pd.DataFrame(etfs)
            display_cols = ["ticker", "name", "price", "change_pct_1d", "change_pct_5d", "volume_ratio"]
            df_display = df_etf[[c for c in display_cols if c in df_etf.columns]].copy()
            df_display.columns = [c.replace("_", " ").title() for c in df_display.columns]

            def _color_pct(val):
                if isinstance(val, float):
                    return "color: #4ade80" if val > 0 else ("color: #f87171" if val < 0 else "")
                return ""

            styled = df_display.style.map(
                _color_pct, subset=[c for c in df_display.columns if "Pct" in c or "Change" in c]
            )
            st.dataframe(styled, use_container_width=True, hide_index=True)
            st.plotly_chart(_make_etf_chart(etfs), use_container_width=True)

            gld  = next((e for e in etfs if e["ticker"] == "GLD"), {})
            tlt  = next((e for e in etfs if e["ticker"] == "TLT"), {})
            fxi  = next((e for e in etfs if e["ticker"] == "FXI"), {})
            kweb = next((e for e in etfs if e["ticker"] == "KWEB"), {})
            for note in [
                f"⚠️ GLD volume {gld.get('volume_ratio', 1):.1f}x normal — risk-off demand"
                    if (gld.get("volume_ratio") or 1) > 1.5 else None,
                f"🟢 FXI +{fxi.get('change_pct_5d', 0):.1f}% over 5d — China ETF buying"
                    if (fxi.get("change_pct_5d") or 0) > 3 else None,
                f"🔴 KWEB {kweb.get('change_pct_5d', 0):.1f}% over 5d — China tech selling"
                    if (kweb.get("change_pct_5d") or 0) < -5 else None,
                f"🔴 TLT +{tlt.get('change_pct_5d', 0):.1f}% — flight to bonds"
                    if (tlt.get("change_pct_5d") or 0) > 2 else None,
            ]:
                if note:
                    st.caption(note)

    # ── SIGNAL HISTORY ───────────────────────────────────────────
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
        # Dual-axis chart: composite score bars + HSI line
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
        st.caption(
            f"Source: local SQLite — real data only, logging started {first_date}"
        )

        # Last 7 days summary table
        st.markdown("**Last 7 Days**")
        last7 = hist_df.tail(7).sort_values("date", ascending=False).copy()

        def _trunc(s, n=70):
            s = str(s) if pd.notna(s) else "—"
            return s[:n] + "…" if len(s) > n else s

        summary = pd.DataFrame({
            "Date":       last7["date"].dt.strftime("%Y-%m-%d"),
            "Score":      last7["combined_score"].apply(
                              lambda v: f"{v:+.1f}" if pd.notna(v) else "—"),
            "HK Stance":  last7["hk_stance"].fillna("—"),
            "US Stance":  last7["us_stance"].fillna("—"),
            "Action Line": last7["action_line"].apply(_trunc),
        })
        st.dataframe(summary, use_container_width=True, hide_index=True)

    # ── Footer ────────────────────────────────────────────────────
    st.divider()
    st.caption(
        "Flow Monitor Phase 2 | Data: LSEG / yfinance / FRED / AKShare / HKMA API | "
        "Not investment advice. "
        f"Rendered: {datetime.now().strftime('%Y-%m-%d %H:%M')} HKT"
    )
