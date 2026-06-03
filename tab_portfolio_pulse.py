"""Tab 11 — Portfolio Pulse: holdings vs benchmarks, alpha, southbound check."""

import streamlit as st
import pandas as pd
from portfolio_pulse.analysis import get_portfolio_pulse


def render_portfolio_pulse():
    st.header("💼 Portfolio Pulse")
    st.caption(
        "Your actual holdings vs benchmarks. "
        "Performance, alpha, and theme tracking."
    )

    with st.spinner("Loading portfolio data..."):
        data = get_portfolio_pulse()

    if data.get("error"):
        st.error(
            f"❌ Could not load portfolio: "
            f"{data.get('error_msg', 'Unknown error')}"
        )
        return

    summary    = data.get("summary", {})
    positions  = data.get("positions", [])
    benchmarks = data.get("benchmarks", {})
    usdhkd     = data.get("usdhkd", 7.83)

    # ── SECTION 1: PORTFOLIO SUMMARY ─────────────────────────────
    st.divider()
    st.subheader("📊 Portfolio Overview")

    col1, col2, col3, col4, col5 = st.columns(5)

    total_mv = summary.get("total_mv_usd", 0)
    total_gl = summary.get("total_gl_usd", 0)
    gl_pct   = summary.get("gl_pct", 0)
    count    = summary.get("position_count", 0)

    with col1:
        st.metric("Total Portfolio", f"${total_mv/1e6:.3f}M")
    with col2:
        st.metric(
            "Unrealised G/L",
            f"${total_gl:+,.0f}",
            delta=f"{gl_pct:+.1f}%",
        )
    with col3:
        st.metric("Positions", count)
    with col4:
        hsi = benchmarks.get('^HSI', {})
        hsi_3m = hsi.get('ret_3m')
        st.metric(
            "HSI 3M",
            f"{hsi_3m:+.1f}%" if hsi_3m is not None else "N/A",
        )
    with col5:
        spy = benchmarks.get('SPY', {})
        spy_3m = spy.get('ret_3m')
        st.metric(
            "SPY 3M",
            f"{spy_3m:+.1f}%" if spy_3m is not None else "N/A",
        )

    st.caption(
        f"📅 Prices: ~15min delay | "
        f"🔄 Fetched: {data['fetched_at']} | "
        f"FX: USD/HKD = {usdhkd:.4f}"
    )

    st.divider()

    # ── SECTION 2: REGION BREAKDOWN ──────────────────────────────
    st.subheader("🌍 By Region")
    by_region = summary.get("by_region", {})

    if by_region:
        reg_cols = st.columns(len(by_region))
        for i, (region, rdata) in enumerate(by_region.items()):
            mv   = rdata['mv']
            gl   = rdata['gl']
            cnt  = rdata['count']
            pct  = mv / total_mv * 100 if total_mv > 0 else 0
            gl_p = gl / (mv - gl) * 100 if (mv - gl) > 0 else 0

            bench_data = {
                'HK':    benchmarks.get('^HSI', {}),
                'China': benchmarks.get('^HSI', {}),
                'US':    benchmarks.get('SPY', {}),
            }.get(region, {})

            with reg_cols[i]:
                icon = ("🇭🇰" if region in ['HK', 'China']
                        else "🇺🇸" if region == 'US'
                        else "🌏")
                st.markdown(f"**{icon} {region}**")
                st.write(f"${mv/1e6:.2f}M ({pct:.0f}%)")
                st.write(f"G/L: {gl_p:+.1f}%")
                st.write(f"{cnt} positions")
                b3m = bench_data.get('ret_3m')
                if b3m is not None:
                    st.caption(f"Benchmark 3M: {b3m:+.1f}%")

    st.divider()

    # ── SECTION 3: WINNERS vs LOSERS ─────────────────────────────
    st.subheader("🏆 Alpha vs Benchmark (3M)")
    st.caption(
        "Alpha = your stock's 3M return minus its benchmark's 3M return"
    )

    col_w, col_l = st.columns(2)

    with col_w:
        st.markdown("**📈 Top Outperformers**")
        for p in summary.get("top_winners", []):
            alpha = p.get('alpha_3m', 0) or 0
            ret   = p.get('ret_3m', 0) or 0
            bench = p.get('bench_3m', 0) or 0
            st.markdown(f"**{p['ticker']}** {p['name'][:20]}")
            st.write(
                f"Alpha: **{alpha:+.1f}%** "
                f"({ret:+.1f}% vs {p['bench_name']} {bench:+.1f}%)"
            )
            st.caption(f"{p['region']} | {p['sector'][:25]}")
            st.divider()

    with col_l:
        st.markdown("**📉 Top Underperformers**")
        for p in summary.get("top_losers", []):
            alpha = p.get('alpha_3m', 0) or 0
            ret   = p.get('ret_3m', 0) or 0
            bench = p.get('bench_3m', 0) or 0
            st.markdown(f"**{p['ticker']}** {p['name'][:20]}")
            st.write(
                f"Alpha: **{alpha:+.1f}%** "
                f"({ret:+.1f}% vs {p['bench_name']} {bench:+.1f}%)"
            )
            st.caption(f"{p['region']} | {p['sector'][:25]}")
            st.divider()

    st.divider()

    # ── SECTION 4: FULL HOLDINGS TABLE ───────────────────────────
    st.subheader("📋 Full Holdings")

    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        region_filter = st.multiselect(
            "Region",
            options=sorted(set(p['region'] for p in positions)),
            default=[],
            key="pp_region_filter",
        )
    with fc2:
        barbell_filter = st.multiselect(
            "Barbell Class",
            options=sorted(set(p['barbell'] for p in positions)),
            default=[],
            key="pp_barbell_filter",
        )
    with fc3:
        sort_by = st.selectbox(
            "Sort by",
            options=["Market Value", "G/L %", "Alpha 3M", "3M Return"],
            key="pp_sort",
        )

    filtered = positions
    if region_filter:
        filtered = [p for p in filtered if p['region'] in region_filter]
    if barbell_filter:
        filtered = [p for p in filtered if p['barbell'] in barbell_filter]

    sort_map = {
        "Market Value": ("mv_usd",   True),
        "G/L %":        ("gl_pct",   True),
        "Alpha 3M":     ("alpha_3m", True),
        "3M Return":    ("ret_3m",   True),
    }
    sort_key, sort_desc = sort_map.get(sort_by, ("mv_usd", True))
    filtered.sort(key=lambda x: x.get(sort_key) or -999, reverse=sort_desc)

    if filtered:
        df = pd.DataFrame(filtered)
        display = df[[
            'ticker', 'name', 'region', 'barbell',
            'mv_usd', 'gl_pct', 'ret_3m',
            'bench_name', 'bench_3m', 'alpha_3m',
        ]].copy()

        display['mv_usd']   = display['mv_usd'].apply(lambda x: f"${x:,.0f}")
        display['gl_pct']   = display['gl_pct'].apply(lambda x: f"{x:+.1f}%")
        display['ret_3m']   = display['ret_3m'].apply(
            lambda x: f"{x:+.1f}%" if x is not None else "N/A")
        display['bench_3m'] = display['bench_3m'].apply(
            lambda x: f"{x:+.1f}%" if x is not None else "N/A")
        display['alpha_3m'] = display['alpha_3m'].apply(
            lambda x: f"{x:+.1f}%" if x is not None else "N/A")

        display.columns = [
            'Ticker', 'Name', 'Region', 'Class',
            'Mkt Value', 'G/L%', '3M Ret',
            'Benchmark', 'Bench 3M', 'Alpha',
        ]
        st.dataframe(display, use_container_width=True, hide_index=True)
        st.caption(f"Showing {len(filtered)} of {len(positions)} positions")
    else:
        st.info("No positions match the filter")

    st.divider()

    # ── SECTION 5: SOUTHBOUND CHECK FOR HK HOLDINGS ──────────────
    hk_positions = [p for p in positions if p['region'] in ['HK', 'China']]

    if hk_positions:
        st.subheader("🌊 Southbound Flow on Your HK Holdings")
        st.caption(
            "Check if mainland money is buying or selling your specific HK positions"
        )

        try:
            from flow_core.hk_flows import get_southbound_conviction
            sb      = get_southbound_conviction()
            full_df = sb.get("full", pd.DataFrame())
            sb_date = sb.get("data_date", "Unknown")

            if not full_df.empty:
                matches = []
                for p in hk_positions:
                    code  = p['ticker'].replace('.HK', '').lstrip('0')
                    match = full_df[
                        full_df['股票代码'].astype(str).str.lstrip('0') == code
                    ]
                    if not match.empty:
                        row = match.iloc[0]
                        matches.append({
                            "ticker":  p['ticker'],
                            "name":    p['name'],
                            "net_buy": row.get('net_buy_hkd', None),
                            "sb_hold": row.get('sb_hold_pct', None),
                            "accel":   row.get('flow_5d_accel', None),
                        })

                if matches:
                    st.caption(f"📅 Southbound data as of: {sb_date} (T+1 lag)")
                    match_df = pd.DataFrame(matches)
                    match_df['net_buy'] = match_df['net_buy'].apply(
                        lambda x: (f"+{x/1e6:.0f}M HKD" if x and x > 0
                                   else f"{x/1e6:.0f}M HKD" if x else "N/A"))
                    match_df['sb_hold'] = match_df['sb_hold'].apply(
                        lambda x: f"{x:.1f}%" if x else "N/A")
                    match_df['accel'] = match_df['accel'].apply(
                        lambda x: f"{x:.1f}x" if x else "N/A")
                    match_df.columns = ['Ticker', 'Name', 'Net Buy', 'SB Hold%', '5D Accel']
                    st.dataframe(match_df, use_container_width=True, hide_index=True)
                else:
                    st.info(
                        "None of your HK holdings found in southbound data "
                        "(may not be Stock Connect eligible)"
                    )
            else:
                st.info("Southbound data unavailable — check Flow Monitor tab")
        except Exception as e:
            st.info(f"Southbound check unavailable: {e}")
