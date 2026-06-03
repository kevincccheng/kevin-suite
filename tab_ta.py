"""Tab 12 — Technical Analysis Engine."""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def render_ta():
    st.header("📈 Technical Analysis Engine")
    st.caption("Enter any ticker, index, or commodity")

    # ── INPUT ROW ────────────────────────────────────────────────
    col_in, col_btn = st.columns([3, 1])
    with col_in:
        ticker_input = st.text_input(
            "Ticker",
            placeholder="NVDA, 0700.HK, ^HSI, GC=F",
            key="ta_ticker_input",
        )
    with col_btn:
        st.write("")
        st.write("")
        analyse_btn = st.button("📊 Analyse", key="ta_analyse_btn", type="primary")

    # Quick-access buttons
    st.caption("Quick access:")
    qcols = st.columns(7)
    quick = [
        ("S&P 500", "^GSPC"), ("Nasdaq", "^NDX"), ("Dow", "^DJI"),
        ("HSI", "^HSI"), ("HSTECH", "^HSTECH"), ("Gold", "GC=F"), ("Oil", "CL=F"),
    ]
    for i, (label, qticker) in enumerate(quick):
        with qcols[i]:
            if st.button(label, key=f"quick_{qticker}"):
                st.session_state["ta_selected"] = qticker

    # Determine active ticker
    if analyse_btn and ticker_input.strip():
        st.session_state["ta_selected"] = ticker_input.strip()

    active_ticker = st.session_state.get("ta_selected", "").strip()

    if not active_ticker:
        st.info("Enter a ticker above or click a quick-access button to begin.")
        return

    # ── ANALYSIS ─────────────────────────────────────────────────
    from ta_engine.analysis import get_ta_analysis

    with st.spinner(f"Analysing {active_ticker}..."):
        ta = get_ta_analysis(active_ticker)

    if ta.get("error"):
        st.error(f"❌ {ta.get('error_msg', 'Unknown error')}")
        return

    comp = ta["composite"]
    ind  = ta["indicators"]
    hist = ta["hist"]

    name     = ta.get("company_name", active_ticker)
    price    = ta.get("current_price", 0)
    change   = ta.get("price_change_pct", 0)
    is_index = ta.get("is_index", False)

    # ── COMPANY HEADER ────────────────────────────────────────────
    st.markdown(f"## {name} ({ta['ticker_clean']})")
    pcol1, pcol2, pcol3 = st.columns(3)
    with pcol1:
        st.metric("Price", f"{price:,.4f}", delta=f"{change:+.2f}%")
    with pcol2:
        st.metric("52W High", f"{ind['sr']['wk52_high']:,.4f}")
    with pcol3:
        st.metric("52W Low", f"{ind['sr']['wk52_low']:,.4f}")

    st.divider()

    # ── DIFFUSION INDEX BANNER ────────────────────────────────────
    score   = comp["normalised"]
    verdict = comp["verdict"]
    color   = comp["color"]
    raw     = comp["raw_total"]
    max_s   = comp["max_possible"]
    n_ind   = len([s for s in comp["scores"] if s is not None])

    st.markdown(
        f'<div style="background:{color};padding:20px;border-radius:8px;margin:10px 0">'
        f'<h2 style="color:white;margin:0">'
        f'TA Diffusion Index: {score:.0f}/100 — {verdict}'
        f'</h2>'
        f'<p style="color:white;margin:5px 0 0 0">'
        f'Raw score: {raw}/{max_s} across {n_ind} indicators'
        f'</p>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.progress(int(score))
    st.divider()

    # ── SCORECARD TABLE ───────────────────────────────────────────
    st.subheader("📋 Indicator Breakdown")

    rows = [
        ("📊 Trend (MAs)",       ind["trend"]["score"],  ind["trend"]["note"]),
        ("💫 Momentum (RSI)",    ind["rsi"]["score"],    ind["rsi"]["note"]),
        ("📈 MACD",              ind["macd"]["score"],   ind["macd"]["note"]),
        ("🎯 Bollinger Bands",   ind["bb"]["score"],     ind["bb"]["note"]),
        ("📦 Volume & OBV",      ind["volume"]["score"], ind["volume"]["note"]),
        ("🏔️ Support/Resistance", ind["sr"]["score"],    ind["sr"]["note"]),
        ("⚡ Relative Strength", ind["rs"]["score"],     ind["rs"]["note"]),
    ]

    def _score_str(s):
        if s is None:
            return "N/A (index)"
        return f"+{s}" if s > 0 else str(s)

    def _signal(s_str):
        if "+" in s_str and s_str != "+0":
            return "🟢"
        if "-" in s_str:
            return "🔴"
        return "🟡"

    score_rows = []
    for indicator, s, note in rows:
        s_str = _score_str(s)
        score_rows.append({
            "Signal":    _signal(s_str),
            "Indicator": indicator,
            "Score":     s_str,
            "Reading":   note,
        })

    st.dataframe(
        pd.DataFrame(score_rows),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        f"📅 Data: yfinance | ⏰ 15-min delay | "
        f"🔄 Fetched: {ta['fetched_at']}"
    )
    st.divider()

    # ── CHARTS ────────────────────────────────────────────────────
    st.subheader("📊 Charts")

    n_rows       = 3 if is_index else 4
    row_heights  = ([0.5, 0.2, 0.15, 0.15] if not is_index
                    else [0.6, 0.2, 0.2])
    subplot_titles = (
        ["Price + MAs + Bollinger Bands", "Volume & OBV", "RSI (14)", "MACD (12,26,9)"]
        if not is_index else
        ["Price + MAs + Bollinger Bands", "RSI (14)", "MACD (12,26,9)"]
    )

    fig = make_subplots(
        rows=n_rows, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=row_heights,
        subplot_titles=subplot_titles,
    )

    dates = hist.index

    # Row 1 — Candlestick + MAs + Bollinger
    fig.add_trace(go.Candlestick(
        x=dates,
        open=hist["Open"], high=hist["High"],
        low=hist["Low"],   close=hist["Close"],
        name="Price", showlegend=False,
    ), row=1, col=1)

    ma20_s  = ind["trend"]["ma20_series"]
    ma50_s  = ind["trend"]["ma50_series"]
    ma200_s = ind["trend"]["ma200_series"]

    for ma_label, ma_data, ma_color in [
        ("MA20",  ma20_s,  "#3b82f6"),
        ("MA50",  ma50_s,  "#f59e0b"),
        ("MA200", ma200_s, "#ef4444"),
    ]:
        fig.add_trace(go.Scatter(
            x=dates[-len(ma_data):], y=ma_data,
            name=ma_label,
            line=dict(color=ma_color, width=1),
        ), row=1, col=1)

    bb_up  = ind["bb"]["upper_series"]
    bb_lo  = ind["bb"]["lower_series"]
    bb_mid = ind["bb"]["middle_series"]
    bb_dates = dates[-len(bb_up):]

    fig.add_trace(go.Scatter(
        x=bb_dates, y=bb_up,
        name="BB Upper",
        line=dict(color="gray", width=1, dash="dash"),
        showlegend=False,
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=bb_dates, y=bb_lo,
        name="BB Lower",
        line=dict(color="gray", width=1, dash="dash"),
        fill="tonexty",
        fillcolor="rgba(128,128,128,0.1)",
        showlegend=False,
    ), row=1, col=1)

    fig.add_hline(
        y=ind["sr"]["wk52_high"],
        line_dash="dot", line_color="green",
        annotation_text="52W High",
        row=1, col=1,
    )
    fig.add_hline(
        y=ind["sr"]["wk52_low"],
        line_dash="dot", line_color="red",
        annotation_text="52W Low",
        row=1, col=1,
    )

    # Row 2 — Volume & OBV (stocks/ETFs only)
    rsi_row  = 3 if not is_index else 2
    macd_row = 4 if not is_index else 3

    if not is_index:
        vol_data = ind["volume"]
        fig.add_trace(go.Bar(
            x=dates,
            y=hist["Volume"],
            name="Volume",
            marker_color="rgba(100,149,237,0.5)",
            showlegend=False,
        ), row=2, col=1)

        obv_s = vol_data.get("obv_series")
        if obv_s:
            fig.add_trace(go.Scatter(
                x=dates[-len(obv_s):], y=obv_s,
                name="OBV",
                line=dict(color="#8b5cf6", width=1),
                yaxis="y5",
            ), row=2, col=1)

    # RSI row
    rsi_s = ind["rsi"]["rsi_series"]
    fig.add_trace(go.Scatter(
        x=dates[-len(rsi_s):], y=rsi_s,
        name="RSI",
        line=dict(color="#06b6d4", width=1.5),
        showlegend=False,
    ), row=rsi_row, col=1)

    for y_level, lcolor in [(70, "red"), (30, "green"), (50, "gray")]:
        fig.add_hline(
            y=y_level,
            line_dash="dash" if y_level != 50 else "dot",
            line_color=lcolor,
            opacity=0.5 if y_level != 50 else 0.3,
            row=rsi_row, col=1,
        )

    # MACD row
    macd_s   = ind["macd"]["macd_series"]
    signal_s = ind["macd"]["signal_series"]
    hist_s   = ind["macd"]["histogram_series"]
    macd_dates = dates[-len(macd_s):]

    fig.add_trace(go.Scatter(
        x=macd_dates, y=macd_s,
        name="MACD",
        line=dict(color="#3b82f6", width=1.5),
        showlegend=False,
    ), row=macd_row, col=1)
    fig.add_trace(go.Scatter(
        x=macd_dates, y=signal_s,
        name="Signal",
        line=dict(color="#f59e0b", width=1),
        showlegend=False,
    ), row=macd_row, col=1)
    fig.add_trace(go.Bar(
        x=macd_dates, y=hist_s,
        name="MACD Hist",
        marker_color=["#22c55e" if v >= 0 else "#ef4444" for v in hist_s],
        showlegend=False,
    ), row=macd_row, col=1)

    # Layout
    fig.update_layout(
        height=800 if not is_index else 650,
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        paper_bgcolor="#0e1117",
        plot_bgcolor="#0e1117",
        font=dict(color="white", size=11),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=50, r=50, t=60, b=50),
    )

    fig.update_yaxes(title_text="Price", row=1, col=1)
    if not is_index:
        fig.update_yaxes(title_text="Volume", row=2, col=1)
    fig.update_yaxes(title_text="RSI", row=rsi_row, col=1)
    fig.update_yaxes(title_text="MACD", row=macd_row, col=1)

    st.plotly_chart(fig, use_container_width=True)
    st.divider()

    # ── EXPORT (placeholder — no PDF exporter in scope) ──────────
    st.caption("💡 Use the Export tab to download a portfolio-level PDF.")
