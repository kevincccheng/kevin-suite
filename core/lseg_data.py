# core/lseg_data.py — LSEG Desktop Session integration (local only)
# Requires Refinitiv Workspace to be running on this PC (localhost:9000).
# On Streamlit Cloud or without Workspace: all functions return {} / False safely.
# DO NOT add LSEG credentials here — desktop session only, no platform/RDP.

import streamlit as st


def _import_lseg_lib():
    """Return the first available LSEG/Refinitiv data module, or None."""
    for lib_name in ("lseg.data", "refinitiv.data"):
        try:
            import importlib
            return importlib.import_module(lib_name)
        except Exception:
            pass
    return None


@st.cache_resource(ttl=60)
def _open_desktop_session():
    """
    Try to open a desktop session via Workspace proxy (localhost:9000).
    Returns (module, True) if connected, (None, False) otherwise.
    Cached 60 s so the sidebar check doesn't hit the network every rerun.
    """
    lib = _import_lseg_lib()
    if lib is None:
        return None, False
    try:
        lib.open_session()          # Desktop session — no credentials needed
        sess = lib.session.get_default()
        if "Opened" in str(getattr(sess, "open_state", "")):
            return lib, True
    except Exception:
        pass
    return None, False


def lseg_desktop_available() -> bool:
    """True only when Refinitiv Workspace is running and the session is open."""
    _, ok = _open_desktop_session()
    return ok


# Backward-compat aliases used elsewhere in the app
def lseg_available() -> bool:
    return lseg_desktop_available()


def lseg_connected() -> bool:
    return lseg_desktop_available()


def refresh_lseg():
    """Force re-check of Workspace connection on next call."""
    _open_desktop_session.clear()


# ── Data fetching (only called when lseg_desktop_available() is True) ──────

def get_fundamentals_lseg(ticker: str) -> dict:
    """
    Fetch snapshot fundamentals from LSEG EDP via Workspace desktop session.
    Returns dict with keys: ebit, revenue, net_income, fcf, gross_profit,
    gross_margin, total_debt, cash, shares, ev_ebitda, eps_mean, price, pe_ratio
    Returns {} on any failure.
    """
    try:
        lib, ok = _open_desktop_session()
        if not ok or lib is None:
            return {}

        fields = [
            "TR.EBITActValue",
            "TR.TotalRevenue",
            "TR.NetIncome",
            "TR.FreeCashFlow",
            "TR.GrossProfit",
            "TR.GrossMargin",
            "TR.TotalDebt",
            "TR.CashAndSTInvestments",
            "TR.SharesOutstanding",
            "TR.EVToEBITDA",
            "TR.EPSMean",
            "TR.PriceClose",
        ]
        data = lib.get_data(universe=[ticker], fields=fields)
        if data is None or data.empty:
            return {}

        col_keys = [c for c in data.columns if c != "Instrument"]
        row = data.iloc[0]
        field_map = {
            "TR.EBITActValue":         "ebit",
            "TR.TotalRevenue":         "revenue",
            "TR.NetIncome":            "net_income",
            "TR.FreeCashFlow":         "fcf",
            "TR.GrossProfit":          "gross_profit",
            "TR.GrossMargin":          "gross_margin",
            "TR.TotalDebt":            "total_debt",
            "TR.CashAndSTInvestments": "cash",
            "TR.SharesOutstanding":    "shares",
            "TR.EVToEBITDA":           "ev_ebitda",
            "TR.EPSMean":              "eps_mean",
            "TR.PriceClose":           "price",
        }
        result = {}
        for i, field_code in enumerate(fields):
            if i >= len(col_keys):
                break
            key_name = field_map.get(field_code)
            if not key_name:
                continue
            v = row.get(col_keys[i])
            if v is not None and str(v) not in ("nan", "None", "<NA>", ""):
                try:
                    result[key_name] = float(v)
                except Exception:
                    pass

        if "price" in result and "eps_mean" in result and result["eps_mean"] > 0:
            result["pe_ratio"] = result["price"] / result["eps_mean"]

        return result
    except Exception:
        return {}


def get_historical_pe_lseg(ticker: str, years: int = 5) -> list:
    """
    Compute annual P/E from LSEG historical EPS + annual close prices.
    Returns list of floats (oldest→newest); [] on failure.
    """
    try:
        lib, ok = _open_desktop_session()
        if not ok or lib is None:
            return []

        eps_data = lib.get_data(
            universe=[ticker],
            fields=["TR.EPSActValue"],
            parameters={"SDate": f"-{years}Y", "EDate": "0D", "Frq": "FY"},
        )
        if eps_data is None or eps_data.empty:
            return []

        eps_col = [c for c in eps_data.columns if c != "Instrument"][0]
        eps_vals = [
            float(v) for v in eps_data[eps_col]
            if v is not None and str(v) not in ("nan", "None", "<NA>", "") and float(v) > 0
        ]
        if not eps_vals:
            return []

        price_data = lib.get_history(ticker, fields=["TRDPRC_1"], interval="1Y", count=years)
        if price_data is None or price_data.empty:
            return []

        price_col = price_data.columns[0]
        price_vals = [
            float(v) for v in price_data[price_col]
            if v is not None and str(v) not in ("nan", "None", "<NA>", "") and float(v) > 0
        ]
        if not price_vals:
            return []

        return [p / e for p, e in zip(price_vals, eps_vals) if e > 0 and 0 < p / e < 1000]
    except Exception:
        return []


def get_price_lseg(ticker: str) -> dict:
    """Real-time price from LSEG Workspace. Returns {} on failure."""
    try:
        lib, ok = _open_desktop_session()
        if not ok or lib is None:
            return {}

        data = lib.get_data(universe=[ticker], fields=["TR.PriceClose", "CF_CURRENCY"])
        if data is None or data.empty:
            return {}

        cols  = [c for c in data.columns if c != "Instrument"]
        row   = data.iloc[0]
        price = row.get(cols[0]) if cols else None
        ccy   = row.get(cols[1]) if len(cols) > 1 else None
        try:
            import pandas as _pd
            price_ok = price is not None and _pd.notna(price)
            ccy_ok   = ccy   is not None and _pd.notna(ccy)
        except Exception:
            price_ok = price is not None and str(price) not in ("nan", "None", "<NA>")
            ccy_ok   = ccy   is not None and str(ccy)   not in ("nan", "None", "<NA>")
        return {
            "price":    float(price) if price_ok else None,
            "currency": str(ccy)     if ccy_ok   else "HKD" if ".HK" in ticker else "USD",
            "source":   "lseg",
        }
    except Exception:
        return {}


def _lseg_last_price(ric: str) -> "float | None":
    """Get the latest close price for a RIC. Returns None on any failure."""
    try:
        lib, ok = _open_desktop_session()
        if not ok or lib is None:
            return None
        data = lib.get_data(universe=[ric], fields=["TR.PriceClose"])
        if data is None or data.empty:
            return None
        cols = [c for c in data.columns if c != "Instrument"]
        v = data.iloc[0].get(cols[0]) if cols else None
        return float(v) if v is not None and str(v) not in ("nan", "None", "<NA>") else None
    except Exception:
        return None


def _lseg_history(ric: str, count: int, interval: str = "1D") -> "list[float]":
    """Return list of last `count` closing prices for a RIC (oldest first). [] on failure."""
    try:
        lib, ok = _open_desktop_session()
        if not ok or lib is None:
            return []
        hist = lib.get_history(ric, fields=["TRDPRC_1"], interval=interval, count=count)
        if hist is None or hist.empty:
            return []
        col = hist.columns[0]
        vals = [float(v) for v in hist[col] if v is not None and str(v) not in ("nan", "None", "<NA>")]
        return vals
    except Exception:
        return []


def get_hkma_balance_lseg() -> dict:
    """Fetch HKMA Aggregate Balance via LSEG. Returns {} on failure."""
    try:
        lib, ok = _open_desktop_session()
        if not ok or lib is None:
            return {}
        for ric in ("HKHKMAAB=ECI", "HKMAAB=ECI", "HKMAAB="):
            price = _lseg_last_price(ric)
            if price is not None:
                hist = _lseg_history(ric, 8)
                change = (price - hist[-2]) if len(hist) >= 2 else 0.0
                return {"balance": price, "change": change, "source": "LSEG"}
        return {}
    except Exception:
        return {}


def get_dxy_lseg() -> dict:
    """Fetch DXY Dollar Index via LSEG. Returns {} on failure."""
    try:
        for ric in (".DXY", "DXY="):
            price = _lseg_last_price(ric)
            if price is not None:
                hist = _lseg_history(ric, 2)
                change_pct = (price - hist[0]) / hist[0] * 100 if len(hist) >= 2 and hist[0] else 0.0
                return {"price": price, "change_pct": round(change_pct, 2), "source": "LSEG"}
        return {}
    except Exception:
        return {}


def get_hstech_lseg() -> dict:
    """Fetch Hang Seng Tech Index via LSEG. Returns {} on failure."""
    try:
        price = _lseg_last_price(".HSTECH")
        if price is None:
            return {}
        hist = _lseg_history(".HSTECH", 2)
        change_pct = (price - hist[0]) / hist[0] * 100 if len(hist) >= 2 and hist[0] else 0.0
        return {"price": price, "change_pct": round(change_pct, 2), "source": "LSEG"}
    except Exception:
        return {}


def get_usdcnh_history_lseg(days: int = 250) -> "pd.DataFrame":
    """Fetch USD/CNH (or CNY proxy) daily close history via LSEG. Returns empty DataFrame on failure."""
    try:
        import pandas as pd
        lib, ok = _open_desktop_session()
        if not ok or lib is None:
            return pd.DataFrame()
        # Try CNH first, fall back to onshore CNY (close proxy for signal purposes)
        for ric in ("USDCNH=", "CNY=", "USDCNY="):
            try:
                hist = lib.get_history(ric, fields=["TRDPRC_1"], interval="1D", count=days)
                if hist is not None and not hist.empty and len(hist) >= 30:
                    df = hist.reset_index()
                    df.columns = ["date", "close"]
                    df["date"]  = pd.to_datetime(df["date"])
                    df["close"] = pd.to_numeric(df["close"], errors="coerce")
                    clean = df.dropna(subset=["close"])[["date", "close"]].reset_index(drop=True)
                    if len(clean) >= 30:
                        return clean
            except Exception:
                continue
        return pd.DataFrame()
    except Exception:
        import pandas as pd
        return pd.DataFrame()


def get_etf_flows_lseg(tickers: list) -> list:
    """Fetch ETF price/1d/5d change via LSEG. Returns [] on failure."""
    _ric_map = {
        "SPY": "SPY.N",  "QQQ": "QQQ.O", "GLD": "GLD.N",
        "TLT": "TLT.N",  "FXI": "FXI.N", "KWEB": "KWEB.O", "EEM": "EEM.N",
    }
    _name_map = {
        "SPY": "S&P 500", "QQQ": "Nasdaq 100", "GLD": "Gold",
        "TLT": "Long Bonds", "FXI": "China Large Cap",
        "KWEB": "China Tech", "EEM": "Emerging Markets",
    }
    try:
        lib, ok = _open_desktop_session()
        if not ok or lib is None:
            return []
        results = []
        for tkr in tickers:
            ric = _ric_map.get(tkr)
            if not ric:
                continue
            price = _lseg_last_price(ric)
            if price is None:
                continue
            hist = _lseg_history(ric, 7)
            change_1d = (price - hist[-2]) / hist[-2] * 100 if len(hist) >= 2 and hist[-2] else 0.0
            change_5d = (price - hist[0]) / hist[0] * 100 if len(hist) >= 6 and hist[0] else None
            results.append({
                "ticker":        tkr,
                "name":          _name_map.get(tkr, tkr),
                "price":         round(price, 2),
                "change_pct_1d": round(change_1d, 2),
                "change_pct_5d": round(change_5d, 2) if change_5d is not None else None,
                "volume_ratio":  1.0,
                "source":        "LSEG",
            })
        return results
    except Exception:
        return []


def get_market_caps_lseg(tickers: list) -> dict:
    """
    Batch-fetch market caps for a list of RIC tickers via LSEG.
    Returns {ticker: market_cap_hkd}. HK stocks are in HKD natively;
    USD-denominated stocks are converted using a fallback rate of 7.83.
    Returns {} on any failure.

    Note from diagnostics: LSEG returns the column as 'Company Market Cap'
    (not 'TR.CompanyMarketCap') and CF_CURRENCY is <NA> for HK stocks
    (which trade in HKD by default).
    """
    try:
        lib, ok = _open_desktop_session()
        if not ok or lib is None:
            return {}
        df = lib.get_data(
            universe=tickers,
            fields=["TR.CompanyMarketCap", "CF_CURRENCY"],
        )
        if df is None or df.empty:
            return {}

        # Column may come back as 'Company Market Cap' or 'TR.CompanyMarketCap'
        mc_col = next(
            (c for c in df.columns
             if "market cap" in c.lower() or "companymarketcap" in c.lower().replace(".", "")),
            None,
        )
        ccy_col = next(
            (c for c in df.columns if "currency" in c.lower()), None
        )
        if mc_col is None:
            return {}

        usdhkd = 7.83
        result = {}
        for _, row in df.iterrows():
            ric = row.get("Instrument") or (row.name if hasattr(row, "name") else None)
            if not ric:
                continue
            mc = row.get(mc_col)
            if mc is None or str(mc) in ("nan", "None", "<NA>", ""):
                continue
            try:
                mc = float(mc)
            except (ValueError, TypeError):
                continue
            if mc <= 0:
                continue

            ccy = str(row.get(ccy_col, "")) if ccy_col else ""
            if ccy.upper() == "USD":
                mc = mc * usdhkd
            # HK stocks: CF_CURRENCY is NA → already in HKD
            result[ric] = mc

        return result
    except Exception:
        return {}
