"""US Capital Allocation Radar — Module A regime scoring."""

from datetime import datetime


def calculate_regime(data: dict, monthly_allocation: int = 8000) -> dict:
    score = 0
    max_score = 8
    factors = []

    # Factor 1: SPY vs 200DMA
    spy_qqq = data.get("spy_qqq", {})
    spy = spy_qqq.get("SPY", {})
    if not spy_qqq.get("error"):
        spy_above = spy.get("pct_above_200dma", 0)
        spy_slope = spy.get("slope_dir", "")
        if spy_above > 5 and spy_slope == "RISING":
            score += 2
            factors.append("SPY well above rising 200DMA ✅")
        elif spy_above > 0:
            score += 1
            factors.append("SPY above 200DMA ✅")
        elif spy_above < -5:
            score -= 2
            factors.append("SPY well below 200DMA ⚠️")
        else:
            score -= 1
            factors.append("SPY below 200DMA ⚠️")

    # Factor 2: VIX
    vix_data = data.get("vix", {})
    if not vix_data.get("error"):
        vix = vix_data.get("vix", 20)
        if vix < 15:
            score += 2
            factors.append(f"VIX {vix:.1f} — calm ✅")
        elif vix < 20:
            score += 1
            factors.append(f"VIX {vix:.1f} — elevated but OK")
        elif vix < 30:
            score -= 1
            factors.append(f"VIX {vix:.1f} — elevated ⚠️")
        else:
            score -= 2
            factors.append(f"VIX {vix:.1f} — fear ❌")

    # Factor 3: Credit spreads
    credit = data.get("credit", {})
    if not credit.get("error"):
        signal = credit.get("signal", "")
        if signal == "STABLE":
            score += 1
            factors.append("Credit spreads stable ✅")
        elif signal == "STRESS":
            score -= 2
            factors.append("Credit spreads widening ❌")
        else:
            factors.append("Credit spreads mixed")

    # Factor 4: Market breadth
    breadth = data.get("breadth", {})
    if not breadth.get("error"):
        signal = breadth.get("signal", "")
        if signal == "BROAD":
            score += 1
            factors.append("Market breadth broad ✅")
        elif signal == "NARROW":
            score -= 1
            factors.append("Market breadth narrow ⚠️")

    # Factor 5: Put/call sentiment
    putcall = data.get("putcall", {})
    pc = putcall.get("equity_putcall")
    if pc:
        if pc < 0.6:
            score -= 1
            factors.append(f"Put/call {pc:.2f} — greed ⚠️")
        elif pc > 1.2:
            factors.append(f"Put/call {pc:.2f} — extreme fear")
        elif 0.7 <= pc <= 0.9:
            score += 1
            factors.append(f"Put/call {pc:.2f} — neutral ✅")

    # Factor 6: Real yield
    yc = data.get("yield_curve", {})
    real = yc.get("real_yield_10yr")
    if real is not None:
        if real < 1.0:
            score += 1
            factors.append(f"Real yield {real:.2f}% — easy ✅")
        elif real > 2.5:
            score -= 1
            factors.append(f"Real yield {real:.2f}% — restrictive ⚠️")
        else:
            factors.append(f"Real yield {real:.2f}% — neutral")

    # Panic override: VIX > 35 + put/call > 1.2 + credit NOT in stress = capitulation opportunity
    panic_override = False
    vix_val = vix_data.get("vix", 0) if not vix_data.get("error") else 0
    credit_ok = credit.get("signal", "") != "STRESS"
    pc_fear = pc and pc > 1.2

    if vix_val > 35 and pc_fear and credit_ok:
        panic_override = True
        factors.append("🟣 PANIC OVERRIDE — capitulation signal")

    # Determine regime with percentage-based DCA amounts
    if panic_override:
        regime = "PANIC"
        color = "#6B21A8"
        deploy_pct = 150
        deploy_amt = int(monthly_allocation * 1.5)
        reserve_amt = deploy_amt - monthly_allocation
        dca_action = (
            f"🟣 DEPLOY 150% — Deploy "
            f"USD {deploy_amt:,.0f} "
            f"(use USD {monthly_allocation:,.0f} allocation "
            f"+ USD {reserve_amt:,.0f} reserves). "
            f"Capitulation signal — rare opportunity. Layer 1 only."
        )
        layer3_active = False
    elif score >= 6:
        regime = "GREEN"
        color = "#166534"
        deploy_pct = 100
        deploy_amt = monthly_allocation
        dca_action = (
            f"🟢 DEPLOY FULL — Deploy "
            f"{deploy_pct}% (USD {deploy_amt:,.0f}) "
            f"into VOO/QQQ on schedule. "
            f"All systems constructive. Layer 1/2/3 alerts active."
        )
        layer3_active = True
    elif score >= 3:
        regime = "YELLOW"
        color = "#854D0E"
        deploy_pct = 50
        deploy_amt = int(monthly_allocation * 0.5)
        hold_amt = monthly_allocation - deploy_amt
        dca_action = (
            f"🟡 DEPLOY HALF — Deploy "
            f"{deploy_pct}% (USD {deploy_amt:,.0f}) now, "
            f"hold {100 - deploy_pct}% (USD {hold_amt:,.0f}) "
            f"for better entry or pullback confirmation. "
            f"Layer 3 paused."
        )
        layer3_active = False
    elif score >= 0:
        regime = "YELLOW"
        color = "#854D0E"
        deploy_pct = 25
        deploy_amt = int(monthly_allocation * 0.25)
        hold_amt = monthly_allocation - deploy_amt
        dca_action = (
            f"🟡 DEPLOY QUARTER — Deploy "
            f"{deploy_pct}% (USD {deploy_amt:,.0f}) as token, "
            f"hold {100 - deploy_pct}% (USD {hold_amt:,.0f}). "
            f"Wait for clearer signal. Layer 3 paused."
        )
        layer3_active = False
    else:
        regime = "RED"
        color = "#7F1D1D"
        deploy_pct = 0
        deploy_amt = 0
        dca_action = (
            f"🔴 HOLD — Deploy 0%. "
            f"Preserve full USD {monthly_allocation:,.0f}. "
            f"Wait for regime improvement. Layer 3 OFF."
        )
        layer3_active = False

    return {
        "regime":            regime,
        "score":             score,
        "max_score":         max_score,
        "color":             color,
        "dca_action":        dca_action,
        "deploy_pct":        deploy_pct,
        "deploy_amt":        deploy_amt,
        "monthly_allocation": monthly_allocation,
        "factors":           factors,
        "layer3_active":     layer3_active,
        "panic_override":    panic_override,
        "calculated_at":     datetime.now().strftime('%Y-%m-%d %H:%M HKT')
    }
