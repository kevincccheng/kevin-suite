"""
Composite signal engine — three-gate hierarchical scoring model.

Gate 1 (40%): Global Liquidity     range −4 to +4
Gate 2 (30%): HK Liquidity         range −3 to +3
Gate 3 (30%): China/HK Risk Appetite range −3 to +3

Final score = (g1/4*0.4 + g2/3*0.3 + g3/4*0.3) * 10  → −10 to +10

If Gate 1 < −2: force overall stance to WAIT regardless of other gates.
"""


def calculate_composite_signal(data: dict) -> dict:
    """
    data keys expected:
      sc_flows, hsi, cnh, vix, yield_curve, fed, dxy,
      hkma, hibor, usdhkd, usdcnh_200dma, hstech
    Returns full composite result dict.
    """
    sc      = data.get("sc_flows", {}) or {}
    hsi_d   = data.get("hsi", {}) or {}
    vix_d   = data.get("vix", {}) or {}
    yc_d    = data.get("yield_curve", {}) or {}
    fed_d   = data.get("fed", {}) or {}
    dxy_d   = data.get("dxy", {}) or {}
    hkma_d  = data.get("hkma", {}) or {}
    hibor_d = data.get("hibor", {}) or {}
    usdh_d  = data.get("usdhkd", {}) or {}
    cnh_200 = data.get("usdcnh_200dma", {}) or {}
    hst_d   = data.get("hstech", {}) or {}

    # ── GATE 1: Global Liquidity ──────────────────────────────────
    g1, g1f = 0, []

    # DXY
    if not dxy_d.get("error"):
        sig = dxy_d.get("signal", "")
        if sig == "WEAK":
            g1 += 1;  g1f.append("DXY weak — liquidity supportive (+1)")
        elif sig == "STRONG":
            g1 -= 1;  g1f.append("DXY strong — liquidity headwind (−1)")

    # Real 10yr yield (DFII10)
    ry = yc_d.get("real_yield_10yr") if not yc_d.get("error") else None
    if ry is not None:
        if ry < 1.5:
            g1 += 1;  g1f.append(f"Real 10yr yield {ry:.2f}% — benign (+1)")
        elif ry > 2.5:
            g1 -= 1;  g1f.append(f"Real 10yr yield {ry:.2f}% — restrictive (−1)")

    # VIX
    if not vix_d.get("error"):
        vsig = vix_d.get("signal", "")
        if vsig == "CALM":
            g1 += 1;  g1f.append(f"VIX calm {vix_d.get('vix', 0):.1f} (+1)")
        elif vsig == "FEAR":
            g1 -= 1;  g1f.append(f"VIX fear {vix_d.get('vix', 0):.1f} (−1)")
        elif vsig == "PANIC":
            g1 -= 2;  g1f.append(f"VIX panic {vix_d.get('vix', 0):.1f} (−2)")

    # Fed path
    if not fed_d.get("error") and not fed_d.get("probs_unavailable"):
        p_cut = (fed_d.get("prob_cut_25") or 0) + (fed_d.get("prob_cut_50") or 0)
        p_hike = fed_d.get("prob_hike") or 0
        if p_cut > 50:
            g1 += 1;  g1f.append(f"Fed cut probability {p_cut:.0f}% (+1)")
        elif p_hike > 20:
            g1 -= 1;  g1f.append(f"Fed hike risk {p_hike:.0f}% (−1)")

    g1 = max(-4, min(4, g1))
    gate1_forced_wait = g1 < -2

    # ── GATE 2: HK Liquidity ─────────────────────────────────────
    g2, g2f = 0, []

    if not hkma_d.get("error"):
        sig = hkma_d.get("signal", "")
        if sig == "EXPANDING":
            g2 += 1;  g2f.append("HKMA balance expanding (+1)")
        elif sig == "CONTRACTING":
            g2 -= 1;  g2f.append("HKMA balance contracting (−1)")

    if not hibor_d.get("error"):
        trend = hibor_d.get("trend", "")
        if trend == "FALLING":
            g2 += 1;  g2f.append("HIBOR falling — easing HK liquidity (+1)")
        elif trend == "RISING":
            g2 -= 1;  g2f.append("HIBOR rising — tightening HK liquidity (−1)")

    if not usdh_d.get("error"):
        sig = usdh_d.get("signal", "")
        if sig == "SAFE":
            g2 += 1;  g2f.append(f"USD/HKD {usdh_d.get('rate', 0):.4f} — peg safe (+1)")
        elif sig == "ALERT":
            g2 -= 1;  g2f.append(f"USD/HKD {usdh_d.get('rate', 0):.4f} — near weak-side band (−1)")

    g2 = max(-3, min(3, g2))

    # ── GATE 3: China/HK Risk Appetite ───────────────────────────
    g3, g3f = 0, []

    # Southbound flow
    sb_hkd = 0
    if not sc.get("error"):
        sb_hkd = (sc.get("southbound") or {}).get("net_flow_hkd") or 0
    if sb_hkd > 5_000_000_000:
        g3 += 1;  g3f.append(f"Strong southbound flow {sb_hkd/1e9:.1f}B HKD (+1)")
    elif sb_hkd < 0:
        g3 -= 1;  g3f.append(f"Southbound net selling {sb_hkd/1e9:.1f}B HKD (−1)")

    # CNH/USD vs 200DMA
    if not cnh_200.get("error"):
        sig = cnh_200.get("signal", "")
        if sig == "BELOW_200DMA":
            g3 += 1;  g3f.append("CNH below 200DMA — RMB stable/strengthening (+1)")
        elif sig == "ABOVE_200DMA":
            g3 -= 1;  g3f.append("CNH above 200DMA — RMB weakening pressure (−1)")

    # HSTECH vs HSI
    if not hst_d.get("error") and not hsi_d.get("error"):
        hst_chg = hst_d.get("change_pct", 0) or 0
        hsi_chg = (hsi_d.get("hsi") or {}).get("change_pct", 0) or 0
        if hst_chg > hsi_chg + 0.3:
            g3 += 1;  g3f.append(f"HSTECH outperforming HSI (+{hst_chg - hsi_chg:.1f}pp) (+1)")
        elif hst_chg < hsi_chg - 0.3:
            g3 -= 1;  g3f.append(f"HSTECH underperforming HSI ({hst_chg - hsi_chg:.1f}pp) (−1)")

    # HSI direction
    if not hsi_d.get("error"):
        hsi_chg = (hsi_d.get("hsi") or {}).get("change_pct", 0) or 0
        if hsi_chg > 0.5:
            g3 += 1;  g3f.append(f"HSI up {hsi_chg:.1f}% today (+1)")
        elif hsi_chg < -0.5:
            g3 -= 1;  g3f.append(f"HSI down {hsi_chg:.1f}% today (−1)")

    g3 = max(-3, min(3, g3))

    # ── Final score ───────────────────────────────────────────────
    combined = (g1 / 4 * 0.4 + g2 / 3 * 0.3 + g3 / 4 * 0.3) * 10
    combined = round(combined, 1)

    # ── Stances ───────────────────────────────────────────────────
    if gate1_forced_wait:
        hk_stance = us_stance = overall_stance = "WAIT"
        color = "red"
        action_line = ("Hold all positions — global liquidity hostile "
                       "(DXY strong, real yields elevated, VIX fear). "
                       "Do not deploy capital into risk assets.")
    elif combined >= 4:
        hk_stance = us_stance = overall_stance = "ACCUMULATE"
        color = "green"
        action_line = ("Accumulate across both HK/China and US portfolios. "
                       "Macro conditions broadly favourable.")
    elif combined >= 1:
        hk_stance = "ACCUMULATE"
        us_stance = "NEUTRAL"
        overall_stance = "ACCUMULATE"
        color = "green"
        action_line = ("Deploy into HK/China positions; hold US allocation steady. "
                       "Local flows supportive, global macro mixed.")
    elif combined >= -1:
        hk_stance = us_stance = overall_stance = "NEUTRAL"
        color = "yellow"
        action_line = ("Hold existing positions across both portfolios. "
                       "Mixed signals — no clear edge for new deployment.")
    elif combined >= -3:
        hk_stance = "WAIT"
        us_stance = "NEUTRAL"
        overall_stance = "WAIT"
        color = "red"
        action_line = ("Pause HK/China additions; maintain US. "
                       "Local liquidity tightening — wait for cleaner entry.")
    else:
        hk_stance = us_stance = overall_stance = "WAIT"
        color = "red"
        action_line = ("Defensive mode — reduce exposure across both portfolios. "
                       "Flows clearly risk-off; preserve capital.")

    return {
        "gate1_score":      g1,
        "gate2_score":      g2,
        "gate3_score":      g3,
        "combined_score":   combined,
        "gate1_forced_wait": gate1_forced_wait,
        "hk_stance":        hk_stance,
        "us_stance":        us_stance,
        "overall_stance":   overall_stance,
        "action_line":      action_line,
        "color":            color,
        "gate1_factors":    g1f,
        "gate2_factors":    g2f,
        "gate3_factors":    g3f,
    }


def _fmt_hkd(val: float) -> str:
    if abs(val) >= 1e9:
        return f"HKD {val/1e9:.1f}B"
    return f"HKD {val/1e6:.0f}M"
