"""Flow Monitor tab — renders the full HK/China + US Macro dashboard."""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

from flow_core.hk_flows import (
    get_stock_connect_flows,
    get_stock_connect_history,
    get_top_northbound_stocks,
    get_hsi_data,
    get_cnh_cny_spread,
    get_pboc_rate,
)
from flow_core.us_macro import (
    get_fed_expectations,
    get_yield_curve,
    get_vix,
    get_etf_flows,
)
from flow_core.composite import (
    calculate_hk_signal,
    calculate_us_signal,
    calculate_combined_signal,
)


@st.cache_data(ttl=900)
def _fetch_flow_data():
    sc_flows = get_stock_connect_flows()
    hsi = get_hsi_data()
    cnh = get_cnh_cny_spread()
    pboc = get_pboc_rate()
    nb_history = get_stock_connect_history(30)
    top_stocks = get_top_northbound_stocks()
    fed = get_fed_expectations()
    yc = get_yield_curve()
    vix = get_vix()
    etfs = get_etf_flows()
    return {
        "sc_flows": sc_flows, "hsi": hsi, "cnh": cnh, "pboc": pboc,
        "nb_history": nb_history, "top_stocks": top_stocks,
        "fed": fed, "yc": yc, "vix": vix, "etfs": etfs,
    }


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
         "NORMAL": "✅", "FLAT": "⚠️", "INVERTED": "🚨"}
    return m.get(sig, "")


def _is_mock(data) -> bool:
    if isinstance(data, dict):
        return data.get("_is_mock", False) or data.get("is_mock", False)
    if isinstance(data, pd.DataFrame):
        mock_col = next((c for c in ("_is_mock", "is_mock") if c in data.columns), None)
        return bool(mock_col and data[mock_col].any())
    if isinstance(data, list) and data:
        return data[0].get("_is_mock", False) or data[0].get("is_mock", False)
    return False


def _mock_badge(data) -> str:
    return " **(mock)**" if _is_mock(data) else ""


def _live_badge(data, source: str = "") -> str:
    suffix = f" via {source}" if source else ""
    if _is_mock(data):
        return f"🟡 Simulated data{suffix}"
    return f"🔵 Live{suffix}"


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
        title="Northbound Flow (HKD Billion)",
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


def render_flow_monitor():
    """Render the full Flow Monitor dashboard inside the Apex 2035 tab."""

    # Inject CSS scoped to this tab's content
    st.markdown("""
    <style>
        .fm-main-header { font-size: 2rem; font-weight: 700; margin-bottom: 0; }
        .fm-sub-header { color: #888; font-size: 1rem; margin-top: 0; }
        .fm-signal-banner {
            padding: 1rem 1.5rem; border-radius: 10px;
            font-size: 1.4rem; font-weight: 700;
            margin: 0.5rem 0 1rem 0; letter-spacing: 0.5px;
        }
        .fm-green-banner { background: #1a3a2a; color: #4ade80; border: 1px solid #4ade80; }
        .fm-yellow-banner { background: #3a3014; color: #fbbf24; border: 1px solid #fbbf24; }
        .fm-red-banner { background: #3a1a1a; color: #f87171; border: 1px solid #f87171; }
        .fm-section-title {
            font-size: 1rem; font-weight: 600; color: #9ca3af;
            text-transform: uppercase; letter-spacing: 1px;
            margin: 1rem 0 0.4rem 0; border-bottom: 1px solid #2d3748;
            padding-bottom: 0.3rem;
        }
        .fm-factor-item { font-size: 0.85rem; color: #d1d5db; margin: 0.2rem 0; }
    </style>
    """, unsafe_allow_html=True)

    # Header
    col_title, col_btn = st.columns([5, 1])
    with col_title:
        st.markdown('<p class="fm-main-header">🌊 Flow Monitor</p>', unsafe_allow_html=True)
        st.markdown('<p class="fm-sub-header">HK/China + US Macro Intelligence</p>', unsafe_allow_html=True)
    with col_btn:
        st.write("")
        st.write("")
        if st.button("🔄 Refresh", key="fm_refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S HKT')}")

    with st.spinner("Fetching live data..."):
        d = _fetch_flow_data()

    sc = d["sc_flows"]
    hsi = d["hsi"]
    cnh = d["cnh"]
    pboc = d["pboc"]
    nb_hist = d["nb_history"]
    top_stocks = d["top_stocks"]
    fed = d["fed"]
    yc = d["yc"]
    vix = d["vix"]
    etfs = d["etfs"]

    # Composite signal
    hk_input = {
        "northbound": sc.get("northbound", {}),
        "southbound": sc.get("southbound", {}),
        "cnh_cny": cnh,
        "hsi": hsi,
    }
    us_input = {"vix": vix, "yield_curve": yc, "etfs": etfs}
    hk_sig = calculate_hk_signal(hk_input)
    us_sig = calculate_us_signal(us_input)
    combined = calculate_combined_signal(hk_sig["score"], us_sig["score"])

    color_class = {
        "green": "fm-green-banner",
        "yellow": "fm-yellow-banner",
        "red": "fm-red-banner",
    }[combined["color"]]
    banner_emoji = {"green": "🟢", "yellow": "🟡", "red": "🔴"}[combined["color"]]
    st.markdown(
        f'<div class="fm-signal-banner {color_class}">'
        f'{banner_emoji} {combined["label"]}</div>',
        unsafe_allow_html=True,
    )

    s1, s2, s3, s4 = st.columns(4)
    with s1:
        st.metric("HK/China Score", f"{hk_sig['score']:+d} / 3", delta=hk_sig["label"])
    with s2:
        st.metric("US Macro Score", f"{us_sig['score']:+d} / 3", delta=us_sig["label"])
    with s3:
        st.metric("Combined Score", f"{combined['combined']:+d} / 6")
    with s4:
        action = combined["action"]
        st.metric("Suggested Stance", action[:35] + "…" if len(action) > 35 else action)

    with st.expander("📋 Signal factors driving today's score", expanded=False):
        fc1, fc2 = st.columns(2)
        with fc1:
            st.markdown("**HK/China factors:**")
            for f in hk_sig["factors"] or ["No factors"]:
                st.markdown(f'<div class="fm-factor-item">• {f}</div>', unsafe_allow_html=True)
        with fc2:
            st.markdown("**US Macro factors:**")
            for f in us_sig["factors"] or ["No factors"]:
                st.markdown(f'<div class="fm-factor-item">• {f}</div>', unsafe_allow_html=True)

    st.divider()

    left, right = st.columns(2, gap="large")

    # ── LEFT: HK/CHINA FLOWS ──────────────────────────────────────
    with left:
        st.markdown('<div class="fm-section-title">📊 HK/China Flows</div>', unsafe_allow_html=True)

        nb = sc.get("northbound", {})
        sb = sc.get("southbound", {})

        st.markdown("**Stock Connect Today**")
        st.caption(_live_badge(sc, "AKShare"))

        nb_net = nb.get("net_flow_hkd", 0) or 0
        sb_net = sb.get("net_flow_hkd", 0) or 0
        quota_pct = nb.get("quota_used_pct", 0) or 0

        cm1, cm2 = st.columns(2)
        with cm1:
            nb_rmb = nb.get("net_flow_rmb_bn")
            nb_label = (
                f"Net: {nb_rmb:+.1f}亿 RMB" if nb_rmb is not None
                else f"Net: {_fmt_hkd(nb_net)}"
            )
            st.metric(
                "Northbound (Mainland → HK)",
                "N/A (suspended)",
                delta=nb.get("note", nb_label),
                delta_color="off",
            )
        with cm2:
            sb_rmb = sb.get("net_flow_rmb_bn")
            sb_label = (
                f"Net: {sb_rmb:+.1f}亿 RMB" if sb_rmb is not None
                else f"Net: {_fmt_hkd(sb_net)}"
            )
            sb_signal = sb.get("signal", "")
            st.metric(
                "Southbound (HK → Mainland)",
                _fmt_hkd(abs(sb_net)) if sb_net else "—",
                delta=f"{sb_label}  {sb_signal}",
                delta_color="normal" if sb_net >= 0 else "inverse",
            )

        if quota_pct:
            st.markdown(f"**Quota used:** {quota_pct:.1f}%")
            st.progress(min(quota_pct / 100, 1.0))
        if nb.get("quota_remaining_hkd"):
            st.caption(f"Remaining: {_fmt_hkd(nb['quota_remaining_hkd'])}")

        st.divider()

        hist_live = not _is_mock(nb_hist)
        chart_label = "Southbound Flow — Last 30 Days" if hist_live else "Northbound Flow — Last 30 Days (Simulated)"
        st.markdown(f"**{chart_label}**")
        if hist_live:
            st.caption("🔵 Live southbound data via AKShare (northbound suspended by China Nov 2023)")
        else:
            st.caption("🟡 Simulated — AKShare unavailable")
        if not nb_hist.empty:
            fig = _make_nb_chart(nb_hist)
            if hist_live:
                fig.update_layout(title="Southbound Flow — HK Connect to Mainland (亿元 RMB × 1.07 ≈ HKD)")
            st.plotly_chart(fig, use_container_width=True)

        st.divider()

        st.markdown("**Top Northbound Stocks (last available)**")
        st.caption(_live_badge(top_stocks, "AKShare"))
        if top_stocks:
            df_top = pd.DataFrame(top_stocks[:10])
            buy_col = next((c for c in ("net_buy_hkd", "net_buy") if c in df_top.columns), None)
            if buy_col:
                df_top["Net Buy"] = df_top[buy_col].apply(
                    lambda v: _fmt_hkd(v) if buy_col == "net_buy_hkd" else f"~{_fmt_hkd(v)}"
                )
                df_top = df_top.rename(columns={"ticker": "Ticker", "name": "Name"})
                show_cols = [c for c in ["Ticker", "Name", "Net Buy"] if c in df_top.columns]
                st.dataframe(df_top[show_cols], use_container_width=True, hide_index=True)

        st.divider()

        mock_hsi = _mock_badge(hsi)
        st.markdown(f"**HSI / HSCEI**{mock_hsi}")
        hm1, hm2 = st.columns(2)
        hsi_d = hsi.get("hsi", {})
        hscei_d = hsi.get("hscei", {})
        with hm1:
            st.metric(
                "HSI", f"{hsi_d.get('level', 0):,.0f}",
                delta=f"{hsi_d.get('change_pct', 0):+.2f}%",
                delta_color="normal" if (hsi_d.get("change_pct", 0) or 0) >= 0 else "inverse",
            )
        with hm2:
            st.metric(
                "HSCEI", f"{hscei_d.get('level', 0):,.0f}",
                delta=f"{hscei_d.get('change_pct', 0):+.2f}%",
                delta_color="normal" if (hscei_d.get("change_pct", 0) or 0) >= 0 else "inverse",
            )
        spread = hsi.get("spread", 0) or 0
        spread_flag = " ⚠️ Diverging" if abs(spread) > 20000 else ""
        st.caption(f"HSI-HSCEI Spread: {spread:,.0f}{spread_flag}")

        st.divider()

        mock_cnh = _mock_badge(cnh)
        st.markdown(f"**CNH/CNY Spread**{mock_cnh}")
        cnh_val = cnh.get("cnh_per_usd", 0) or 0
        cny_val = cnh.get("cny_per_usd", 0) or 0
        spread_pips = cnh.get("spread_pips", 0) or 0
        cnh_signal = cnh.get("signal", "STABLE")
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

        mock_pboc = _mock_badge(pboc)
        st.markdown(f"**PBOC Policy Rate**{mock_pboc}")
        pboc_rate = pboc.get("rate", 0) or 0
        pboc_chg = pboc.get("change_from_prev", 0) or 0
        pboc_date = pboc.get("date", "")
        st.metric(
            "7-Day Reverse Repo Rate", f"{pboc_rate:.2f}%",
            delta=f"{pboc_chg:+.2f}% vs prev" if pboc_chg != 0 else "Unchanged",
        )
        if pboc_date:
            st.caption(f"As of: {pboc_date}")

    # ── RIGHT: US MACRO ───────────────────────────────────────────
    with right:
        st.markdown('<div class="fm-section-title">🇺🇸 US Macro</div>', unsafe_allow_html=True)

        st.markdown("**Fed Expectations**")
        st.caption(_live_badge(fed, "FRED" if not _is_mock(fed) else ""))
        fed_rate = fed.get("current_rate", 0) or 0
        fm1, fm2 = st.columns(2)
        with fm1:
            st.metric("Current Fed Rate", f"{fed_rate:.2f}%")
        with fm2:
            st.metric("Next Meeting", fed.get("next_meeting_date", "TBD"))

        prob_cols = st.columns(4)
        labels_keys = [("Hold", "prob_hold"), ("Cut 25bp", "prob_cut_25"),
                       ("Cut 50bp", "prob_cut_50"), ("Hike", "prob_hike")]
        for col, (lbl, key) in zip(prob_cols, labels_keys):
            with col:
                val = fed.get(key, 0) or 0
                st.metric(lbl, f"{val:.0f}%")

        st.divider()

        st.markdown("**US Treasury Yield Curve**")
        st.caption(_live_badge(yc, "FRED" if not _is_mock(yc) else ""))
        yc_signal = yc.get("signal", "NORMAL")
        ym1, ym2, ym3 = st.columns(3)
        with ym1:
            st.metric("2yr", f"{yc.get('yield_2yr', 0):.3f}%")
        with ym2:
            st.metric("10yr", f"{yc.get('yield_10yr', 0):.3f}%")
        with ym3:
            st.metric("30yr", f"{yc.get('yield_30yr', 0):.3f}%")
        spread_10_2 = yc.get("spread_10_2", 0) or 0
        color_yc = {"NORMAL": "🟢", "FLAT": "🟡", "INVERTED": "🔴"}.get(yc_signal, "⚪")
        st.markdown(
            f"{color_yc} 10yr-2yr spread: **{spread_10_2:+.3f}%** → **{yc_signal}** {_signal_emoji(yc_signal)}"
        )

        st.divider()

        mock_vix = _mock_badge(vix)
        st.markdown(f"**VIX Fear Index**{mock_vix}")
        vix_level = vix.get("vix", 0) or 0
        vix_chg = vix.get("change_pct", 0) or 0
        vix_sig = vix.get("signal", "CALM")
        vix_color = {"CALM": "🟢", "ELEVATED": "🟡", "FEAR": "🟠", "PANIC": "🔴"}.get(vix_sig, "⚪")
        st.metric(
            f"VIX   {vix_color} {vix_sig}", f"{vix_level:.2f}",
            delta=f"{vix_chg:+.1f}%", delta_color="inverse",
        )

        st.divider()

        mock_etf = _mock_badge(etfs)
        st.markdown(f"**Key ETF Monitor**{mock_etf}")

        if etfs:
            df_etf = pd.DataFrame(etfs)
            display_cols = ["ticker", "name", "price", "change_pct_1d", "change_pct_5d", "volume_ratio"]
            df_display = df_etf[[c for c in display_cols if c in df_etf.columns]].copy()
            df_display.columns = [c.replace("_", " ").title() for c in df_display.columns]

            def color_pct(val):
                if isinstance(val, float):
                    if val > 0:
                        return "color: #4ade80"
                    elif val < 0:
                        return "color: #f87171"
                return ""

            styled = df_display.style.map(
                color_pct, subset=[c for c in df_display.columns if "Pct" in c or "Change" in c]
            )
            st.dataframe(styled, use_container_width=True, hide_index=True)
            st.plotly_chart(_make_etf_chart(etfs), use_container_width=True)

            gld = next((e for e in etfs if e["ticker"] == "GLD"), {})
            tlt = next((e for e in etfs if e["ticker"] == "TLT"), {})
            fxi = next((e for e in etfs if e["ticker"] == "FXI"), {})
            kweb = next((e for e in etfs if e["ticker"] == "KWEB"), {})

            signal_notes = []
            if (gld.get("volume_ratio") or 1) > 1.5:
                signal_notes.append(f"⚠️ GLD volume {gld.get('volume_ratio', 1):.1f}x normal — risk-off demand")
            if (fxi.get("change_pct_5d") or 0) > 3:
                signal_notes.append(f"🟢 FXI +{fxi.get('change_pct_5d', 0):.1f}% over 5d — China ETF buying")
            if (kweb.get("change_pct_5d") or 0) < -5:
                signal_notes.append(f"🔴 KWEB {kweb.get('change_pct_5d', 0):.1f}% over 5d — China tech selling")
            if (tlt.get("change_pct_5d") or 0) > 2:
                signal_notes.append(f"🔴 TLT +{tlt.get('change_pct_5d', 0):.1f}% — flight to bonds")
            for note in signal_notes:
                st.caption(note)

    # ── BOTTOM: SIGNAL HISTORY ────────────────────────────────────
    st.divider()
    st.markdown('<div class="fm-section-title">📈 Signal History (Simulated)</div>', unsafe_allow_html=True)

    if not nb_hist.empty:
        hist_df = nb_hist.copy()
        np.random.seed(99)
        nb_z = (hist_df["northbound_net"] - hist_df["northbound_net"].mean()) / (hist_df["northbound_net"].std() + 1)
        hist_df["composite_score"] = (nb_z * 2).clip(-5, 5).round(1)
        hist_df["hsi_return_pct"] = np.random.normal(0, 1.2, len(hist_df))

        fig_hist = go.Figure()
        fig_hist.add_trace(go.Bar(
            x=hist_df["date"], y=hist_df["composite_score"],
            marker_color=["#4ade80" if v >= 0 else "#f87171" for v in hist_df["composite_score"]],
            name="Composite Score", opacity=0.7,
        ))
        fig_hist.add_trace(go.Scatter(
            x=hist_df["date"], y=hist_df["hsi_return_pct"],
            mode="lines", line=dict(color="#60a5fa", width=2),
            name="HSI Daily Return %", yaxis="y2",
        ))
        fig_hist.update_layout(
            template="plotly_dark", height=300,
            margin=dict(l=10, r=10, t=30, b=10),
            yaxis=dict(title="Composite Score"),
            yaxis2=dict(title="HSI Return %", overlaying="y", side="right"),
            legend=dict(orientation="h", y=1.05),
            hovermode="x unified",
            title="30-Day Signal vs HSI Performance",
        )
        st.plotly_chart(fig_hist, use_container_width=True)

    st.divider()
    st.caption(
        "Flow Monitor | Data: HKEX, yfinance, FRED | "
        "Built for macro intelligence, not investment advice. "
        f"Rendered: {datetime.now().strftime('%Y-%m-%d %H:%M')} HKT"
    )
