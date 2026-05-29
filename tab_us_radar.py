"""US Capital Allocation Radar tab — Module A regime gatekeeper."""

import os
import streamlit as st
import pandas as pd
from datetime import datetime

from us_radar.data import get_us_regime_data
from us_radar.scoring import calculate_regime
from us_radar.compounders import get_watchlist_signals
from flow_core.ai_briefing import generate_briefing

_US_BRIEFING_PROMPT = (
    "You are a concise macro analyst briefing a "
    "Hong Kong-based private investor on US market "
    "conditions. The investor deploys a fixed monthly "
    "amount into VOO/QQQ via DCA and maintains a satellite "
    "portfolio of AI/robotics/space/energy thematic "
    "names. Focus on: whether the current regime "
    "supports deploying the monthly DCA, and which "
    "thematic themes (AI infrastructure, AI power, "
    "physical AI/robotics, space ecosystem) are most "
    "favoured by current conditions. "
    "Be direct and actionable. No disclaimers. "
    "3-4 sentences maximum. End with one clear "
    "US DCA deployment recommendation."
)


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_us_data():
    return get_us_regime_data()


def render_us_radar():
    st.header("US Capital Allocation Radar")
    st.caption(
        "Answers: Should I deploy my monthly US DCA? "
        "Which US themes show early accumulation?"
    )

    # === DCA SETTINGS ===
    with st.expander("⚙️ DCA Settings", expanded=False):
        monthly_allocation = st.number_input(
            "Monthly US allocation (USD)",
            min_value=1000,
            max_value=100000,
            value=st.session_state.get("us_monthly_allocation", 8000),
            step=500,
            key="us_monthly_allocation_input",
            help="Your total monthly US DCA budget",
        )
        st.session_state["us_monthly_allocation"] = monthly_allocation

    monthly_allocation = st.session_state.get("us_monthly_allocation", 8000)

    with st.spinner("Loading US market data..."):
        data = _fetch_us_data()

    regime = calculate_regime(data, monthly_allocation=monthly_allocation)

    # === SECTION 1: REGIME GATEKEEPER ===
    st.divider()

    regime_color = regime["color"]
    regime_name  = regime["regime"]
    score        = regime["score"]

    st.markdown(
        f'<div style="background-color:{regime_color};'
        f'padding:20px;border-radius:8px;margin-bottom:10px">'
        f'<h2 style="color:white;margin:0">'
        f'{regime_name} — Score: {score}/{regime["max_score"]}'
        f'</h2></div>',
        unsafe_allow_html=True
    )

    st.markdown(f"**{regime['dca_action']}**")

    with st.expander("📋 Regime factors"):
        for f in regime["factors"]:
            st.write(f"• {f}")

    st.caption(
        f"🔄 Calculated: {regime['calculated_at']} | "
        f"Data: yfinance + FRED + CBOE"
    )

    st.divider()

    # === SECTION 2: KEY METRICS ===
    st.subheader("📊 Key Regime Metrics")

    col1, col2 = st.columns(2)

    with col1:
        spy_qqq = data.get("spy_qqq", {})
        st.markdown("**SPY/QQQ vs 200DMA**")
        if not spy_qqq.get("error"):
            for t in ['SPY', 'QQQ']:
                td    = spy_qqq.get(t, {})
                pct   = td.get('pct_above_200dma', 0)
                trend = td.get('trend', '')
                slope = td.get('slope_dir', '')
                icon  = "✅" if trend == "ABOVE" else "❌"
                st.write(f"{icon} **{t}**: {pct:+.1f}% vs 200DMA ({slope} slope)")
        st.caption(f"📅 {spy_qqq.get('fetched_at', 'N/A')} | ⏰ 15-min delay")

        st.markdown("**Market Breadth (RSP/SPY)**")
        breadth = data.get("breadth", {})
        if not breadth.get("error"):
            signal = breadth.get("signal", "")
            trend  = breadth.get("trend", "")
            pct30  = breadth.get("pct_change_30d", 0)
            icon   = "✅" if signal == "BROAD" else ("⚠️" if signal == "NARROW" else "➡️")
            st.write(
                f"{icon} **{signal}** — RSP/SPY trend "
                f"{trend} ({pct30:+.1f}% vs 30d ago)"
            )
            st.caption(breadth.get("note", ""))

        st.markdown("**Credit Spreads (HYG/LQD)**")
        credit = data.get("credit", {})
        if not credit.get("error"):
            signal = credit.get("signal", "")
            trend  = credit.get("trend", "")
            icon   = "✅" if signal == "STABLE" else ("❌" if signal == "STRESS" else "⚠️")
            st.write(f"{icon} **{signal}** — {trend}")
            st.caption(credit.get("note", ""))

    with col2:
        vix_data = data.get("vix", {})
        st.markdown("**VIX Fear Index**")
        if not vix_data.get("error"):
            vix_val = vix_data.get("vix", 0)
            signal  = vix_data.get("signal", "")
            change  = vix_data.get("change_pct", 0)
            st.metric("VIX", f"{vix_val:.2f}", delta=f"{change:+.2f}")
            st.caption(signal)

        st.markdown("**CBOE Put/Call Ratio**")
        pc_data = data.get("putcall", {})
        pc = pc_data.get("equity_putcall")
        if pc:
            signal = pc_data.get("signal", "")
            icon   = "😱" if signal == "FEAR" else ("😤" if signal == "GREED" else "😐")
            st.write(f"{icon} Equity P/C: **{pc:.2f}** — {signal}")
        else:
            st.info("Put/call unavailable today")
        st.caption(pc_data.get("note", ""))

        yc = data.get("yield_curve", {})
        st.markdown("**Yield Curve**")
        if not yc.get("error"):
            y2     = yc.get("yield_2yr", 0) or 0
            y10    = yc.get("yield_10yr", 0) or 0
            real   = yc.get("real_yield_10yr")
            spread = y10 - y2
            icon   = "✅" if spread > 0.3 else ("⚠️" if spread > -0.1 else "❌")
            real_str = f" | Real: {real:.2f}%" if real is not None else ""
            st.write(f"2yr: {y2:.2f}% | 10yr: {y10:.2f}%{real_str}")
            st.write(f"{icon} Spread: {spread:+.2f}%")

        fed = data.get("fed", {})
        st.markdown("**Fed Expectations**")
        if not fed.get("error"):
            rate    = fed.get("current_rate", 0)
            hold    = fed.get("prob_hold", 0)
            cut     = fed.get("prob_cut_25", 0)
            meeting = fed.get("next_meeting_date", "")
            st.write(f"Rate: {rate:.2f}% | Next: {meeting}")
            st.write(f"Hold {hold:.0f}% / Cut {cut:.0f}%")

    st.divider()

    # === SECTION 3: ETF MONITOR ===
    st.subheader("📈 Key ETF Monitor")
    etfs = data.get("etfs", [])
    if etfs:
        df = pd.DataFrame(etfs)
        display_cols = ["ticker", "name", "price",
                        "change_pct_1d", "change_pct_5d", "volume_ratio"]
        available = [c for c in display_cols if c in df.columns]
        st.dataframe(df[available], use_container_width=True, hide_index=True)
    else:
        st.info("ETF data unavailable")

    etf_src = "LSEG" if (etfs and etfs[0].get("source") == "LSEG") else "yfinance"
    st.caption(
        f"📅 Data as of last market close | "
        f"⏰ 15-min delay during market hours | "
        f"📡 Source: {etf_src}"
    )

    st.divider()

    # === SECTION 4: STOCK SIGNAL LOOKUP ===
    st.subheader("🔍 US Stock Signal Lookup")
    st.caption(
        "Look up accumulation signals for any US stock. "
        "Uses yfinance + LSEG (if connected) + SEC EDGAR."
    )

    col_input, col_btn = st.columns([3, 1])
    with col_input:
        lookup_ticker = st.text_input(
            "Enter US ticker",
            placeholder="e.g. TSLA, NVDA, PLTR, RKLB",
            key="us_stock_lookup_ticker",
            label_visibility="collapsed",
        ).upper().strip()
    with col_btn:
        lookup_btn = st.button("🔍 Analyse", key="us_stock_lookup_btn")

    if lookup_btn and lookup_ticker:
        from us_radar.stock_lookup import get_stock_signals
        with st.spinner(f"Fetching signals for {lookup_ticker}..."):
            signals = get_stock_signals(lookup_ticker)

        if signals.get("error"):
            st.error(f"❌ {signals.get('error_msg', 'Ticker not found')}")
        else:
            price = signals.get("price", {})
            vol   = signals.get("volume", {})
            short = signals.get("short_interest", {})
            lseg  = signals.get("lseg", {})
            comp  = signals.get("composite", {})

            name   = price.get("company_name", lookup_ticker)
            sector = price.get("sector", "")
            st.markdown(f"### 📊 {name} ({lookup_ticker})")
            st.caption(f"Sector: {sector} | As of: {signals['as_of']}")

            # Composite score banner
            c_score  = comp.get("score", 0)
            stars    = comp.get("stars", "")
            sig_name = comp.get("signal", "")
            max_s    = comp.get("max_score", 10)
            banner_color = ("#166534" if c_score >= 8 else
                            "#854D0E" if c_score >= 5 else
                            "#7F1D1D")
            st.markdown(
                f'<div style="background:{banner_color};'
                f'padding:12px;border-radius:6px;margin:8px 0">'
                f'<span style="color:white;font-size:18px">'
                f'{stars} {sig_name} — Score: {c_score}/{max_s}'
                f'</span></div>',
                unsafe_allow_html=True
            )

            c1, c2, c3, c4 = st.columns(4)

            with c1:
                st.markdown("**📈 Price & Trend**")
                current   = price.get("current", 0)
                pct200    = price.get("pct_vs_200dma", 0)
                pct50     = price.get("pct_vs_50dma", 0)
                range_pos = price.get("range_position_pct", 0)
                delivery  = price.get("price_delivery_pct", 0)
                icon200   = "✅" if pct200 > 0 else "❌"
                st.write(f"Price: **${current:,.2f}**")
                st.write(f"{icon200} vs 200DMA: {pct200:+.1f}%")
                st.write(f"vs 50DMA: {pct50:+.1f}%")
                st.write(f"52W range: {range_pos:.0f}%ile")
                st.write(f"Price delivery: {delivery:.0f}%")

            with c2:
                st.markdown("**📊 Volume**")
                ratio      = vol.get("ratio", 1)
                persist    = vol.get("persistence_20d", 0)
                accum      = vol.get("accumulation_days_20d", 0)
                vol_signal = vol.get("signal", "")
                icon_vol   = "🔺" if ratio > 1.5 else "➡️"
                st.write(f"{icon_vol} Today: **{ratio:.2f}x** avg")
                st.write(f"Signal: {vol_signal}")
                st.write(f"Persist (20d): {persist}/20 days")
                st.write(f"Accum days: {accum}/20 days")

            with c3:
                st.markdown("**📉 Short Interest**")
                short_pct  = short.get("pct_of_float")
                dtc        = short.get("days_to_cover")
                short_sig  = short.get("signal", "")
                if short_pct is not None:
                    icon_s = "🔴" if short_pct > 15 else ("🟡" if short_pct > 5 else "🟢")
                    st.write(f"{icon_s} Float short: **{short_pct:.1f}%**")
                    if dtc:
                        st.write(f"Days to cover: {dtc:.1f}")
                    st.write(f"Signal: {short_sig}")
                    st.caption(short.get("note", ""))
                else:
                    st.write("Short data unavailable")

            with c4:
                st.markdown("**🎯 LSEG Analyst**")
                if not lseg.get("error"):
                    consensus = lseg.get("derived_consensus", "N/A")
                    pt        = lseg.get("price_target_mean")
                    pt_high   = lseg.get("price_target_high")
                    pt_low    = lseg.get("price_target_low")
                    upside    = lseg.get("upside_to_target")
                    icon_c    = ("🟢" if consensus in ["Strong Buy", "Buy"]
                                 else "🟡" if consensus == "Hold" else "🔴")
                    st.write(f"{icon_c} **{consensus}**")
                    if pt:
                        st.write(f"Target: ${pt:.2f}")
                        if pt_high and pt_low:
                            st.write(f"Range: ${pt_low:.2f}–${pt_high:.2f}")
                    if upside is not None:
                        icon_u = "✅" if upside > 10 else ("⚠️" if upside < 0 else "➡️")
                        st.write(f"{icon_u} Upside: {upside:+.1f}%")
                    st.caption("Source: LSEG Workspace")
                else:
                    st.write("LSEG data unavailable")
                    st.caption(lseg.get("msg", ""))

            # Score breakdown
            with st.expander("📋 Score breakdown"):
                reasons = comp.get("reasons", [])
                if reasons:
                    for r in reasons:
                        st.write(f"• {r}")
                else:
                    st.write("No breakdown available")

            # Regime compatibility
            st.markdown("**⚡ Regime Compatibility**")
            current_regime = regime.get("regime", "UNKNOWN")
            score_val      = comp.get("score", 0)

            if current_regime == "GREEN" and score_val >= 6:
                st.success(
                    f"✅ ACTIVE in {current_regime} regime — "
                    f"Strong signals + favourable macro. Consider for new capital."
                )
            elif current_regime == "YELLOW" and score_val >= 7:
                st.warning(
                    f"⚠️ WATCH in {current_regime} regime — "
                    f"Strong stock signals but mixed macro. Build watchlist position only."
                )
            elif current_regime == "RED":
                st.error(
                    f"🔴 PAUSED in {current_regime} regime — "
                    f"Do not deploy new capital regardless of stock signals. "
                    f"Wait for macro improvement."
                )
            else:
                st.info(
                    f"📋 MONITOR — Score {score_val}/{max_s} "
                    f"in {current_regime} regime. Research further before acting."
                )

            # SEC 13F link
            sec = signals.get("sec_13f", {})
            if sec.get("available"):
                st.caption(
                    f"📋 View institutional 13F filings: "
                    f"[SEC EDGAR]({sec.get('url', '')})"
                )

    st.divider()

    # === SECTION 5: THEMATIC WATCHLIST RADAR ===
    st.subheader("📊 Thematic Watchlist Radar")
    st.caption(
        "Daily Z-score ranking of 24 thematic names. "
        "Layer 1 = Core compounders (trend-weighted) | "
        "Layer 2 = Growth | Layer 3 = Moonshots (momentum-weighted)."
    )

    with st.spinner("Loading watchlist signals..."):
        df_all = get_watchlist_signals("all")

    if not df_all.empty:
        if regime.get("regime") not in ("GREEN", "PANIC"):
            st.warning(
                f"⚠️ {regime.get('regime')} REGIME — "
                "Layer 3 paused. Layer 2 only on high-conviction signals. "
                "Focus on Layer 1 core compounders."
            )

        def _render_watchlist_table(df_sub: pd.DataFrame):
            if df_sub.empty:
                st.info("No data for this layer.")
                return

            disp = df_sub[[
                "rank", "ticker", "name", "theme", "layer",
                "price", "pct_vs_200", "vol_ratio", "rs_vs_qqq", "upside", "stars",
            ]].copy()
            disp.columns = [
                "Rank", "Ticker", "Name", "Theme", "Layer",
                "Price", "vs 200DMA%", "Vol Ratio", "RS vs QQQ%", "LSEG Upside%", "★",
            ]

            for col in ["Price"]:
                disp[col] = disp[col].apply(
                    lambda x: f"${x:,.2f}" if x is not None and pd.notna(x) else "—"
                )
            for col in ["vs 200DMA%", "RS vs QQQ%", "LSEG Upside%"]:
                disp[col] = disp[col].apply(
                    lambda x: f"{x:+.1f}%" if x is not None and pd.notna(x) else "—"
                )
            for col in ["Vol Ratio"]:
                disp[col] = disp[col].apply(
                    lambda x: f"{x:.2f}x" if x is not None and pd.notna(x) else "—"
                )

            st.dataframe(disp, use_container_width=True, hide_index=True)

            top3 = df_sub.head(3)
            if not top3.empty:
                st.markdown("**🔔 Top signals today:**")
                a1, a2, a3 = st.columns(3)
                for col_w, (_, row) in zip([a1, a2, a3], top3.iterrows()):
                    upside_v = row.get("upside")
                    upside_s = (f" · {upside_v:+.1f}% LSEG upside"
                                if upside_v is not None and pd.notna(upside_v) else "")
                    with col_w:
                        st.metric(
                            f"#{int(row['rank'])} {row['ticker']} (L{row['layer']})",
                            row["stars"],
                            f"{row['pct_vs_200']:+.1f}% vs 200DMA{upside_s}",
                        )

        tab_all, tab_l1, tab_l2, tab_l3 = st.tabs(
            ["All (24)", "Layer 1 — Core", "Layer 2 — Growth", "Layer 3 — Moonshots"]
        )
        with tab_all:
            _render_watchlist_table(df_all)
        with tab_l1:
            _render_watchlist_table(df_all[df_all["layer"] == 1].copy())
        with tab_l2:
            _render_watchlist_table(df_all[df_all["layer"] == 2].copy())
        with tab_l3:
            _render_watchlist_table(df_all[df_all["layer"] == 3].copy())

        fetched_wl = df_all["fetched_at"].iloc[0] if "fetched_at" in df_all.columns else "N/A"
        lseg_count = int(df_all["lseg_ok"].sum()) if "lseg_ok" in df_all.columns else 0
        st.caption(
            f"🔄 Fetched: {fetched_wl} | ⏰ Cache: 1hr | "
            f"📡 yfinance + LSEG ({lseg_count}/24 with price targets)"
        )
    else:
        df_all = pd.DataFrame()
        st.warning("Watchlist data unavailable — will retry on next refresh.")

    st.divider()

    # === SECTION 6: AI BRIEFING ===
    st.subheader("🤖 US Market Briefing")

    briefing_key = "us_briefing_text"
    ts_key       = "us_briefing_timestamp"

    now     = datetime.now()
    last_ts = st.session_state.get(ts_key)
    need_refresh = (
        not last_ts or
        (now - last_ts).total_seconds() > 14400 or
        now.date() > last_ts.date()
    )

    col_b1, col_b2 = st.columns([4, 1])
    with col_b2:
        if st.button("🔄 Refresh", key="us_briefing_refresh"):
            need_refresh = True

    if need_refresh:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            yc_for_brief = data.get("yield_curve", {})
            top3_names  = df_all["name"].head(3).tolist()  if not df_all.empty else []
            top3_themes = df_all["theme"].head(3).tolist() if not df_all.empty else []

            signal_data = {
                "regime":               regime["regime"],
                "score":                regime["score"],
                "dca_action":           regime["dca_action"],
                "deploy_pct":           regime.get("deploy_pct", 0),
                "spy_pct_above_200dma": (data.get("spy_qqq", {})
                                         .get("SPY", {}).get("pct_above_200dma", "N/A")),
                "qqq_pct_above_200dma": (data.get("spy_qqq", {})
                                         .get("QQQ", {}).get("pct_above_200dma", "N/A")),
                "vix":                  data.get("vix", {}).get("vix", "N/A"),
                "credit_signal":        data.get("credit", {}).get("signal", "N/A"),
                "breadth_signal":       data.get("breadth", {}).get("signal", "N/A"),
                "putcall":              data.get("putcall", {}).get("equity_putcall", "N/A"),
                "real_yield":           yc_for_brief.get("real_yield_10yr", "N/A"),
                "fed_rate":             data.get("fed", {}).get("current_rate", "N/A"),
                "layer3_active":        regime["layer3_active"],
                "overall_stance":       regime["regime"],
                "combined_score":       regime["score"],
                "top_watchlist_names":  top3_names,
                "top_watchlist_themes": top3_themes,
            }

            with col_b1:
                with st.spinner("Generating US briefing..."):
                    briefing = generate_briefing(
                        signal_data,
                        system_prompt_override=_US_BRIEFING_PROMPT
                    )
                    st.session_state[briefing_key] = briefing
                    st.session_state[ts_key] = now
        else:
            st.session_state[briefing_key] = ""

    briefing_text = st.session_state.get(briefing_key, "")
    with col_b1:
        if briefing_text:
            st.markdown(
                f'<div style="background-color:#f0f9ff;'
                f'padding:15px;border-radius:8px;'
                f'border-left:4px solid #0ea5e9">'
                f'{briefing_text}</div>',
                unsafe_allow_html=True
            )
            last_ts = st.session_state.get(ts_key)
            if last_ts:
                st.caption(
                    f"Generated: {last_ts.strftime('%H:%M HKT')} | "
                    f"Refreshes every 4 hours or on demand"
                )
        elif not os.environ.get("ANTHROPIC_API_KEY"):
            st.info("Add ANTHROPIC_API_KEY to .env to enable US briefing")

    st.divider()

    # === SECTION 7: LAYER 3 STATUS ===
    if regime["layer3_active"]:
        st.success(
            "🟢 GREEN REGIME — Layer 3 Moonshot radar ACTIVE. "
            "Thematic accumulation signals will appear here in Phase 2."
        )
    else:
        st.warning(
            f"⚠️ {regime['regime']} REGIME — Layer 3 Moonshot radar PAUSED. "
            f"No new capital to speculative names. "
            + ("Panic override — deploy to Layer 1 only."
               if regime["panic_override"] else "")
        )

    st.caption(
        "Layer 2/3 thematic stock radar coming in Phase 2. "
        "This tab currently shows Module A (regime gatekeeper) + stock lookup."
    )
