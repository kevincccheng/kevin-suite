"""SQLite-based daily signal logger for Flow Monitor."""

import sqlite3
from pathlib import Path
from datetime import datetime
import pandas as pd

DB_DIR  = Path(__file__).parent.parent / "data"
DB_PATH = DB_DIR / "flow_signals.db"

_CREATE = """
CREATE TABLE IF NOT EXISTS daily_signals (
    date            TEXT PRIMARY KEY,
    gate1_score     REAL,
    gate2_score     REAL,
    gate3_score     REAL,
    combined_score  REAL,
    hk_stance       TEXT,
    us_stance       TEXT,
    overall_stance  TEXT,
    action_line     TEXT,
    hsi_price       REAL,
    hsi_change      REAL,
    southbound_hkd  REAL,
    vix             REAL,
    dxy             REAL,
    yield_10y       REAL,
    usdcnh          REAL,
    hkma_balance    REAL,
    source_lseg     INTEGER,
    created_at      TEXT
)
"""


def _conn():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH))
    c.execute(_CREATE)
    c.commit()
    return c


def log_daily_signal(composite: dict, raw: dict):
    """Insert or replace today's signal row. Silent on any error."""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        hsi   = raw.get("hsi", {}) or {}
        sc    = raw.get("sc_flows", {}) or {}
        vix   = raw.get("vix", {}) or {}
        yc    = raw.get("yield_curve", {}) or {}
        dxy   = raw.get("dxy", {}) or {}
        cnh   = raw.get("usdcnh_200dma", {}) or {}
        hkma  = raw.get("hkma", {}) or {}

        sb_hkd = (sc.get("southbound") or {}).get("net_flow_hkd") if not sc.get("error") else None
        src_lseg = 1 if any(
            (raw.get(k) or {}).get("source") == "LSEG"
            for k in ("dxy", "hkma", "hibor", "usdhkd", "hstech", "usdcnh_200dma")
        ) else 0

        row = (
            today,
            composite.get("gate1_score"),
            composite.get("gate2_score"),
            composite.get("gate3_score"),
            composite.get("combined_score"),
            composite.get("hk_stance"),
            composite.get("us_stance"),
            composite.get("overall_stance"),
            composite.get("action_line"),
            (hsi.get("hsi") or {}).get("level")     if not hsi.get("error") else None,
            (hsi.get("hsi") or {}).get("change_pct") if not hsi.get("error") else None,
            sb_hkd,
            vix.get("vix")        if not vix.get("error") else None,
            dxy.get("price")      if not dxy.get("error") else None,
            yc.get("yield_10yr")  if not yc.get("error") else None,
            cnh.get("current")    if not cnh.get("error") else None,
            hkma.get("balance")   if not hkma.get("error") else None,
            src_lseg,
            datetime.now().isoformat(),
        )
        c = _conn()
        c.execute("INSERT OR REPLACE INTO daily_signals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
        c.commit()
        c.close()
    except Exception:
        pass


def get_signal_history(days: int = 90) -> pd.DataFrame:
    """Return last N days of signals as DataFrame. Empty DataFrame on any error."""
    try:
        if not DB_PATH.exists():
            return pd.DataFrame()
        c = _conn()
        df = pd.read_sql_query(
            f"SELECT * FROM daily_signals ORDER BY date DESC LIMIT {days}", c
        )
        c.close()
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)
    except Exception:
        return pd.DataFrame()
