"""AI Morning Briefing — calls Claude API to synthesise macro signals into a paragraph."""

import os
import requests


_SYSTEM_PROMPT = (
    "You are a concise macro analyst briefing a Hong Kong-based private investor "
    "who runs a dual portfolio: HKD 100K/month DCA into HK/China equities and "
    "USD 8K/month into US equities. "
    "Your job is to synthesise the current macro signals into one plain-English "
    "paragraph of 3-4 sentences maximum. "
    "Be direct and actionable. No disclaimers. No generic advice. "
    "End with one clear deployment recommendation for this month's DCA."
)

_NO_KEY_MSG = ""  # empty string signals caller to show info widget instead


def _build_prompt(d: dict) -> str:
    def v(key, fmt=None):
        val = d.get(key)
        if val is None or val == "N/A":
            return "N/A"
        return fmt.format(val) if fmt else str(val)

    etf_lines = ""
    for e in (d.get("etf_summary") or [])[:3]:
        etf_lines += f"\n     {e['ticker']}: {e['change_1d']:+.1f}% 1d"

    return f"""Current macro signals as of today:
- Overall stance: {v('overall_stance')} (score: {v('combined_score')}/10)
- Gate 1 Global Liquidity: {v('gate1_score')}/4 — \
DXY {v('dxy')}, VIX {v('vix')}, Real yield {v('real_yield')}%
- Gate 2 HK Liquidity: {v('gate2_score')}/3 — \
HKMA balance {v('hkma_trend')}, HIBOR {v('hibor_trend')}, \
USD/HKD {v('usdhkd')} ({v('usdhkd_signal')})
- Gate 3 Risk Appetite: {v('gate3_score')}/3 — \
Southbound {v('southbound_hkd')}亿 RMB, CNH {v('usdcnh_signal')}, \
HSTECH {v('hstech_vs_hsi')}
- HSI: {v('hsi_change')}%, VIX: {v('vix')}, \
US 10Y: {v('yield_10y')}%, Real yield: {v('real_yield')}%
- Fed: {v('fed_hold_prob')}% hold / {v('fed_cut25_prob')}% cut-25 \
at {v('fed_next_meeting')}
- Top ETF movers:{etf_lines if etf_lines else ' N/A'}
Write the briefing paragraph now."""


def generate_briefing(signal_data: dict) -> str:
    """
    Call the Anthropic API and return a 3-4 sentence macro briefing.

    Returns:
      - Empty string if ANTHROPIC_API_KEY is missing (caller shows info widget)
      - Briefing text on success
      - "Briefing temporarily unavailable." on API error
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return _NO_KEY_MSG

    prompt = _build_prompt(signal_data)

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":          api_key,
                "anthropic-version":  "2023-06-01",
                "content-type":       "application/json",
            },
            json={
                "model":      "claude-sonnet-4-6",
                "max_tokens": 300,
                "system":     _SYSTEM_PROMPT,
                "messages":   [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()["content"][0]["text"].strip()
        return "Briefing temporarily unavailable."
    except Exception:
        return "Briefing temporarily unavailable."
