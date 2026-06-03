"""Portfolio Pulse — holdings vs benchmarks, alpha, theme tracking."""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import streamlit as st
import sys
sys.path.insert(0, '.')

BENCHMARK_MAP = {
    'HK':    {'ticker': '^HSI',  'name': 'HSI',  'secondary': '^HSCE'},
    'China': {'ticker': '^HSI',  'name': 'HSI',  'secondary': '^HSCE'},
    'US':    {'ticker': 'SPY',   'name': 'SPY',  'secondary': 'QQQ'},
    'Other': {'ticker': 'SPY',   'name': 'SPY',  'secondary': None},
    'SEA':   {'ticker': 'SPY',   'name': 'SPY',  'secondary': None},
}

THEME_MAP = {
    'AI Infrastructure': ['NVDA', 'AMD', 'AVGO', 'ARM', 'MRVL', 'CRDO', 'ALAB', 'SMCI'],
    'AI Software':       ['PLTR', 'APP', 'MSFT', 'GOOGL'],
    'AI Power':          ['CEG', 'VST', 'NRG', 'OKLO', 'SMR'],
    'Space':             ['RKLB', 'ASTS', 'PL', 'SPIR'],
    'HK/China Core':     ['2800.HK', '0388.HK', '0700.HK', '9988.HK', '3690.HK'],
    'Commodities':       ['GLD', 'IAU', 'SLV', 'GDX'],
    'Bonds/Income':      ['BND', 'AGG', 'TLT', 'HYG'],
}


@st.cache_data(ttl=900, show_spinner=False)
def get_portfolio_pulse() -> dict:
    """Load holdings from Google Sheets and compute performance vs benchmarks."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    result = {
        "fetched_at": datetime.now().strftime('%Y-%m-%d %H:%M HKT'),
        "error": False,
    }

    # ── LOAD HOLDINGS ──────────────────────────────────────────────
    try:
        from core.sheets import get_client, GSHEET_NAME
        client = get_client()
        sheet  = client.open(GSHEET_NAME)

        hm   = sheet.worksheet('Holdings_Master')
        rows = hm.get_all_records()

        ph      = sheet.worksheet('Portfolio_History')
        ph_rows = ph.get_all_records()

        holdings = [r for r in rows if r.get('ticker') and r.get('total_shares')]
        result["holdings_count"] = len(holdings)
        result["holdings"]       = holdings
        result["history"]        = ph_rows

    except Exception as e:
        result["error"]     = True
        result["error_msg"] = str(e)
        return result

    # ── FETCH CURRENT PRICES ───────────────────────────────────────
    tickers = [r['ticker'] for r in holdings]

    def fix_ticker(t):
        return t.replace('/', '-')

    def fetch_price(ticker):
        try:
            fixed = fix_ticker(ticker)
            t     = yf.Ticker(fixed)
            hist  = t.history(period='5d')
            if not hist.empty:
                price    = hist['Close'].iloc[-1]
                currency = getattr(t.fast_info, 'currency', 'USD')
                return ticker, {"price": round(float(price), 4), "currency": currency}
        except Exception:
            pass
        return ticker, None

    prices = {}
    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = {executor.submit(fetch_price, t): t for t in tickers}
        for future in as_completed(futures, timeout=60):
            try:
                ticker, data = future.result(timeout=5)
                if data:
                    prices[ticker] = data
            except Exception:
                pass

    result["prices"] = prices

    # ── FETCH BENCHMARK RETURNS ────────────────────────────────────
    benchmarks  = {}
    bench_tickers = ['^HSI', '^HSCE', 'SPY', 'QQQ', '^HSTECH']

    def fetch_bench(bt):
        try:
            hist = yf.Ticker(bt).history(period='252d')
            if hist.empty:
                return bt, None
            close = hist['Close']
            now   = float(close.iloc[-1])

            ret_1m = (now / float(close.iloc[-22]) - 1) * 100 if len(close) >= 22 else None
            ret_3m = (now / float(close.iloc[-63]) - 1) * 100 if len(close) >= 63 else None

            year_start = datetime(datetime.now().year, 1, 1)
            ytd_hist   = hist[hist.index >= str(year_start)]
            ret_ytd    = (now / float(ytd_hist['Close'].iloc[0]) - 1) * 100 \
                         if not ytd_hist.empty else None

            return bt, {
                "ret_1m":  round(ret_1m, 1)  if ret_1m  is not None else None,
                "ret_3m":  round(ret_3m, 1)  if ret_3m  is not None else None,
                "ret_ytd": round(ret_ytd, 1) if ret_ytd is not None else None,
                "current": round(now, 2),
            }
        except Exception:
            return bt, None

    with ThreadPoolExecutor(max_workers=5) as executor:
        bench_futures = {executor.submit(fetch_bench, bt): bt for bt in bench_tickers}
        for future in as_completed(bench_futures, timeout=45):
            try:
                bt, data = future.result(timeout=10)
                if data:
                    benchmarks[bt] = data
            except Exception:
                pass

    result["benchmarks"] = benchmarks

    # ── GET LIVE USDHKD ───────────────────────────────────────────
    usdhkd = 7.83
    try:
        fx = yf.Ticker('USDHKD=X').history(period='2d')
        if not fx.empty:
            usdhkd = float(fx['Close'].iloc[-1])
    except Exception:
        pass
    result["usdhkd"] = round(usdhkd, 4)

    # ── COMPUTE POSITION P&L + 3M RETURNS ─────────────────────────
    # Batch fetch 3M history for all tickers in parallel
    hist_cache = {}

    def fetch_hist(ticker):
        try:
            fixed = fix_ticker(ticker)
            hist  = yf.Ticker(fixed).history(period='100d')['Close']
            return ticker, hist
        except Exception:
            return ticker, None

    with ThreadPoolExecutor(max_workers=15) as executor:
        hist_futures = {executor.submit(fetch_hist, t): t for t in tickers}
        for future in as_completed(hist_futures, timeout=60):
            try:
                ticker, hist = future.result(timeout=5)
                if hist is not None:
                    hist_cache[ticker] = hist
            except Exception:
                pass

    positions = []
    for holding in holdings:
        ticker     = holding['ticker']
        name       = holding.get('name', ticker)
        region     = holding.get('region', 'US')
        sector     = holding.get('sector', 'Unknown')
        barbell    = holding.get('barbell_class', 'CORE')
        ccy        = holding.get('ccy', 'USD')
        shares     = float(holding.get('total_shares', 0) or 0)
        cost_local = float(holding.get('avg_cost_local', 0) or 0)
        cost_usd   = float(holding.get('avg_cost_usd', 0) or 0)

        price_data = prices.get(ticker, {})
        price      = price_data.get('price', 0)

        if not price or not shares:
            continue

        mv_local = price * shares
        mv_usd   = mv_local / usdhkd if ccy == 'HKD' else mv_local

        cost_basis_local = cost_local * shares
        cost_basis_usd   = (cost_usd * shares if cost_usd
                            else cost_basis_local / usdhkd if ccy == 'HKD'
                            else cost_basis_local)

        gl_usd = mv_usd - cost_basis_usd
        gl_pct = (price / cost_local - 1) * 100 if cost_local > 0 else 0

        bench        = BENCHMARK_MAP.get(region, BENCHMARK_MAP['US'])
        bench_ticker = bench['ticker']
        bench_name   = bench['name']
        bench_ret_3m = benchmarks.get(bench_ticker, {}).get('ret_3m')

        hist = hist_cache.get(ticker)
        if hist is not None and len(hist) >= 63:
            ret_3m = (float(hist.iloc[-1]) / float(hist.iloc[-63]) - 1) * 100
        else:
            ret_3m = None

        alpha = (ret_3m - bench_ret_3m) if (ret_3m is not None and bench_ret_3m is not None) else None

        theme = 'Other'
        for t_name, t_tickers in THEME_MAP.items():
            if ticker in t_tickers:
                theme = t_name
                break

        positions.append({
            "ticker":     ticker,
            "name":       name,
            "region":     region,
            "sector":     sector,
            "barbell":    barbell,
            "ccy":        ccy,
            "theme":      theme,
            "shares":     shares,
            "price":      round(price, 4),
            "mv_usd":     round(mv_usd, 0),
            "gl_usd":     round(gl_usd, 0),
            "gl_pct":     round(gl_pct, 1),
            "ret_3m":     round(ret_3m, 1)  if ret_3m  is not None else None,
            "bench_name": bench_name,
            "bench_3m":   bench_ret_3m,
            "alpha_3m":   round(alpha, 1)   if alpha   is not None else None,
        })

    positions.sort(key=lambda x: x['mv_usd'], reverse=True)
    result["positions"] = positions

    # ── SUMMARY STATS ──────────────────────────────────────────────
    total_mv   = sum(p['mv_usd'] for p in positions)
    total_gl   = sum(p['gl_usd'] for p in positions)
    total_cost = total_mv - total_gl
    gl_pct_overall = total_gl / total_cost * 100 if total_cost > 0 else 0

    by_region = {}
    for p in positions:
        r = p['region']
        if r not in by_region:
            by_region[r] = {'mv': 0, 'gl': 0, 'count': 0}
        by_region[r]['mv']    += p['mv_usd']
        by_region[r]['gl']    += p['gl_usd']
        by_region[r]['count'] += 1

    by_barbell = {}
    for p in positions:
        b = p['barbell']
        if b not in by_barbell:
            by_barbell[b] = {'mv': 0, 'count': 0}
        by_barbell[b]['mv']    += p['mv_usd']
        by_barbell[b]['count'] += 1

    with_alpha = [p for p in positions if p['alpha_3m'] is not None]
    winners = sorted(with_alpha, key=lambda x: x['alpha_3m'], reverse=True)[:5]
    losers  = sorted(with_alpha, key=lambda x: x['alpha_3m'])[:5]

    result["summary"] = {
        "total_mv_usd":   round(total_mv, 0),
        "total_gl_usd":   round(total_gl, 0),
        "gl_pct":         round(gl_pct_overall, 1),
        "position_count": len(positions),
        "by_region":      by_region,
        "by_barbell":     by_barbell,
        "top_winners":    winners,
        "top_losers":     losers,
        "usdhkd":         round(usdhkd, 4),
    }

    return result
