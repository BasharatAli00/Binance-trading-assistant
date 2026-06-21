"""Rule-based conviction score 0-100 for the sniper (no ML in v1).

Pure function over a features dict (mirrors strategy.py / pivot_strategy.py
purity). An ML model can be added later as an additive signal.
"""
from sniper_macro import get_macro


def compute_conviction(features: dict) -> float:
    score = 0.0

    # 1. Volume acceleration (max 18)
    va = features.get("vol_acceleration_15m", 0)
    score += min(va * 18, 18)

    # 2. Buy pressure 10m (max 15)
    bp = features.get("buy_pressure_10m", 0)
    if bp >= 3:      score += 15
    elif bp >= 2:    score += 10
    elif bp >= 1.5:  score += 7
    elif bp >= 1:    score += 3

    # 3. Buy-ratio trend (max 10)
    bsr_15m = features.get("buy_sell_ratio_15m", 0.5)
    bsr_h1 = features.get("buyer_seller_ratio_h1", 0.5)
    if bsr_15m > bsr_h1:  score += 10
    elif bsr_15m > 0.6:   score += 5

    # 4. Boost count (max 7, cap spam)
    bc = features.get("boost_count", 0)
    if 0 < bc <= 500:
        score += min(bc / 100 * 7, 7)

    # 5. Liquidity health (max 15, minus rug penalty)
    liq = features.get("liquidity_usd", 0)
    lm_ratio = features.get("liq_to_mcap_ratio", 0)
    liq_drain = features.get("liq_quote_change_10m", 0)
    if liq >= 100_000:    score += 7
    elif liq >= 50_000:   score += 5
    elif liq >= 10_000:   score += 2
    if lm_ratio >= 0.1:   score += 5
    elif lm_ratio >= 0.05: score += 3
    if liq_drain < -10:   score -= 7

    # 6. Macro sentiment (max 10)
    fg = get_macro().get("fear_greed_index", 50)
    if fg >= 70:    score += 10
    elif fg >= 50:  score += 5
    elif fg <= 25:  score -= 5

    # 7. Momentum confirmation (max 10)
    pc_m5 = features.get("price_change_m5", 0)
    greens = features.get("consecutive_green_candles", 0)
    if pc_m5 >= 5:    score += 7
    elif pc_m5 >= 3:  score += 4
    if greens >= 3:   score += 3
    elif greens >= 2: score += 1

    # 8. Buyer dominance (max 10)
    if bsr_15m >= 0.7:    score += 10
    elif bsr_15m >= 0.6:  score += 6
    elif bsr_15m >= 0.55: score += 3

    # 9. Graduated (max 5)
    if features.get("is_graduated", 0):
        score += 5

    # 10. Has socials (max 5)
    if features.get("has_socials", 0):
        score += 5

    return round(min(max(score, 0), 100), 2)
