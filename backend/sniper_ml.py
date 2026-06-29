"""ML 'brain' for the sniper — LightGBM win-probability model.

This is the inference side (load + predict). Training lives in sniper_ml_train.py.
The model predicts P(token reaches the +scale_out barrier before the -stop barrier
within the time-exit horizon) from the same feature vector the live loop computes,
so train/serve parity is guaranteed via the shared FEATURE_COLUMNS ordering.

Graceful degradation: if no model file exists (or it fails to load), predict_prob
returns None and the loop falls back to the rule-based conviction score.
"""
import os
import json
import threading

# Single source of truth for the feature vector fed to the model. Order matters —
# it must match exactly between training and inference. Only numeric features from
# sniper_features.compute_features_from_snaps are included (no symbol/address/dex).
FEATURE_COLUMNS = [
    "price_change_m5", "volume_m5", "buys_m5", "sells_m5",
    "price_change_3m", "price_change_10m", "price_change_15m",
    "price_volatility_15m", "price_trend_15m", "price_vs_session_high",
    "consecutive_green_candles", "volume_sum_15m", "buys_sum_15m", "sells_sum_15m",
    "buy_sell_ratio_15m", "vol_acceleration_15m", "vol_to_liquidity_15m",
    "avg_trade_size_15m", "volume_trend_15m",
    "price_change_h1", "volume_h1", "buys_h1", "sells_h1", "buyer_seller_ratio_h1",
    "price_change_h6", "price_change_h24", "volume_h6", "volume_h24",
    "momentum_accel", "buy_pressure_10m",
    "token_age_hours", "liquidity_usd", "market_cap", "liq_to_mcap_ratio",
    "pool_count", "has_socials", "boost_count", "fdv", "fdv_mcap_ratio",
    "liq_quote_change_10m", "prev_buys_m5", "prev_sells_m5", "is_graduated",
    "buyer_seller_ratio_h24",
]

_HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(_HERE, "sniper_model.txt")        # LightGBM native booster
META_PATH = os.path.join(_HERE, "sniper_model_meta.json")   # features, metrics, threshold

_lock = threading.Lock()
_booster = None
_meta = None
_loaded = False


def vectorize(features: dict) -> list:
    """Project a features dict onto FEATURE_COLUMNS (missing -> 0.0, bools -> 0/1)."""
    row = []
    for col in FEATURE_COLUMNS:
        v = features.get(col, 0.0)
        if isinstance(v, bool):
            v = 1.0 if v else 0.0
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = 0.0
        if v != v or v in (float("inf"), float("-inf")):  # NaN / inf guard
            v = 0.0
        row.append(v)
    return row


def _load():
    global _booster, _meta, _loaded
    with _lock:
        _loaded = True
        if not os.path.exists(MODEL_PATH):
            _booster = None
            return
        try:
            import lightgbm as lgb
            _booster = lgb.Booster(model_file=MODEL_PATH)
            if os.path.exists(META_PATH):
                with open(META_PATH) as f:
                    _meta = json.load(f)
            print(f"[sniper.ml] model loaded ({MODEL_PATH})"
                  + (f" auc={_meta.get('val_auc'):.3f}" if _meta and _meta.get('val_auc') else ""))
        except Exception as e:
            print(f"[sniper.ml] model load failed: {e}")
            _booster = None


def reload_model():
    """Force a re-read from disk (call after retraining)."""
    global _loaded
    _loaded = False
    _load()
    return is_ready()


def is_ready() -> bool:
    if not _loaded:
        _load()
    return _booster is not None


def model_info() -> dict:
    if not _loaded:
        _load()
    info = {"ready": _booster is not None, "model_path": MODEL_PATH,
            "n_features": len(FEATURE_COLUMNS)}
    if _meta:
        info.update({k: _meta.get(k) for k in
                     ("trained_at", "n_samples", "n_pos", "val_auc", "val_ap",
                      "suggested_prob_floor", "tp", "sl", "horizon_min")})
    return info


def predict_prob(features: dict):
    """Return win probability in [0,1], or None if no model is available."""
    if not _loaded:
        _load()
    if _booster is None or not features:
        return None
    try:
        row = vectorize(features)
        p = _booster.predict([row])[0]
        return float(max(0.0, min(1.0, p)))
    except Exception as e:
        print(f"[sniper.ml] predict error: {e}")
        return None
