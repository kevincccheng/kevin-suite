"""Composite signal engine: combines HK and US data into a single actionable score."""


def calculate_hk_signal(hk_data: dict) -> dict:
    """Score HK/China conditions from -3 to +3. Error/missing inputs treated as neutral."""
    score = 0
    factors = []

    nb = hk_data.get("northbound") or {}
    sb = hk_data.get("southbound") or {}
    cnh = hk_data.get("cnh_cny") or {}
    hsi = hk_data.get("hsi") or {}

    # Treat errored sources as absent (neutral)
    if cnh.get("error"):
        cnh = {}
    if hsi.get("error"):
        hsi = {}

    nb_net = nb.get("net_flow_hkd", 0) or 0
    sb_net = sb.get("net_flow_hkd", 0) or 0
    spread_signal = cnh.get("signal") if cnh else None
    hsi_chg = (hsi.get("hsi") or {}).get("change_pct", 0) or 0

    # +1 if northbound is net buying
    if nb_net > 0:
        score += 1
        factors.append(f"Northbound net buying ({_fmt_hkd(nb_net)})")

    # +1 if northbound flow > 5B HKD (strong conviction)
    if nb_net > 5_000_000_000:
        score += 1
        factors.append("Strong northbound flow (>5B HKD)")

    # +1 if CNH/CNY spread stable (skip if data unavailable)
    if spread_signal == "STABLE":
        score += 1
        factors.append("CNH/CNY spread stable (<200 pips)")

    # -1 if southbound dominates northbound
    if sb_net > nb_net and sb_net > 0:
        score -= 1
        factors.append("Southbound > Northbound (HK selling)")

    # -1 if CNH/CNY stressed (skip if data unavailable)
    if spread_signal == "STRESS":
        score -= 1
        factors.append("CNH/CNY stress (>500 pips) — capital pressure")

    # -1 if HSI down >1% (skip if data unavailable)
    if hsi and hsi_chg < -1.0:
        score -= 1
        factors.append(f"HSI down {hsi_chg:.1f}% today")

    score = max(-3, min(3, score))
    return {"score": score, "label": _hk_label(score), "factors": factors}


def calculate_us_signal(us_data: dict) -> dict:
    """Score US macro conditions from -3 to +3. Error/missing inputs treated as neutral."""
    score = 0
    factors = []

    vix = us_data.get("vix") or {}
    yc = us_data.get("yield_curve") or {}
    etfs = us_data.get("etfs") or []

    # Treat errored sources as absent (neutral)
    if vix.get("error"):
        vix = {}
    if yc.get("error"):
        yc = {}

    vix_level = vix.get("vix") if vix else None
    inverted = yc.get("inverted") if yc else None

    spy_5d = next((e["change_pct_5d"] for e in etfs if e.get("ticker") == "SPY" and e.get("change_pct_5d") is not None), None)
    gld_vol = next((e["volume_ratio"] for e in etfs if e.get("ticker") == "GLD"), None)

    # +1 if VIX < 15 (calm) — skip if unavailable
    if vix_level is not None and vix_level < 15:
        score += 1
        factors.append(f"VIX calm ({vix_level:.1f})")

    # +1 if yield curve not inverted — skip if unavailable
    if inverted is not None and not inverted:
        score += 1
        factors.append(f"Yield curve not inverted (spread {yc.get('spread_10_2', 0):+.2f}%)")

    # +1 if SPY 5d return positive — skip if unavailable
    if spy_5d is not None and spy_5d > 0:
        score += 1
        factors.append(f"SPY +{spy_5d:.1f}% over 5 days")

    # -1 if VIX > 25 (fear) — skip if unavailable
    if vix_level is not None and vix_level > 25:
        score -= 1
        factors.append(f"VIX elevated ({vix_level:.1f}) — fear in market")

    # -1 if yield curve inverted — skip if unavailable
    if inverted:
        score -= 1
        factors.append(f"Yield curve inverted ({yc.get('spread_10_2', 0):+.2f}%)")

    # -1 if GLD volume ratio > 2 (flight to safety) — skip if unavailable
    if gld_vol is not None and gld_vol > 2.0:
        score -= 1
        factors.append(f"Gold volume {gld_vol:.1f}x normal — risk-off rush")

    score = max(-3, min(3, score))
    return {"score": score, "label": _us_label(score), "factors": factors}


def calculate_combined_signal(hk_score: int, us_score: int) -> dict:
    """Combine HK and US scores into overall risk stance."""
    combined = hk_score + us_score  # -6 to +6

    if combined >= 4:
        label = "RISK ON — HIGH CONVICTION"
        color = "green"
        action = "Add exposure. Flows strongly support risk assets."
    elif combined >= 2:
        label = "RISK ON"
        color = "green"
        action = "Lean long. Flows supportive of risk."
    elif combined >= -1:
        label = "NEUTRAL — WAIT"
        color = "yellow"
        action = "Hold positions. Mixed signals, no clear edge."
    elif combined >= -3:
        label = "RISK OFF"
        color = "red"
        action = "Reduce exposure. Flows turning negative."
    else:
        label = "RISK OFF — DEFENSIVE"
        color = "red"
        action = "Defensive mode. Flows clearly risk-off."

    return {
        "hk_score": hk_score,
        "us_score": us_score,
        "combined": combined,
        "label": label,
        "color": color,
        "action": action,
    }


def _fmt_hkd(val: float) -> str:
    if abs(val) >= 1e9:
        return f"HKD {val/1e9:.1f}B"
    return f"HKD {val/1e6:.0f}M"


def _hk_label(score: int) -> str:
    if score >= 2:   return "STRONG BUY"
    elif score == 1: return "BUY"
    elif score == 0: return "NEUTRAL"
    elif score == -1: return "CAUTION"
    else:            return "AVOID"


def _us_label(score: int) -> str:
    if score >= 2:   return "RISK ON"
    elif score == 1: return "CONSTRUCTIVE"
    elif score == 0: return "NEUTRAL"
    elif score == -1: return "CAUTIOUS"
    else:            return "RISK OFF"
