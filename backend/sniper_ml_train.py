"""Train the sniper 'brain' (LightGBM win-probability model) from snapshot history.

Labeling = triple-barrier, aligned to the live strategy:
  At each historical decision point T we ask "if we bought here, would price reach
  the +scale_out barrier BEFORE the -stop barrier within the time-exit horizon?"
  label = 1 if the up-barrier is hit first, else 0. This makes the model predict
  exactly what the strategy monetizes (a profitable scale-out), not just "goes up".

Features are reconstructed as-of T from the 20-minute window ending at T via the
SAME function the live loop uses (sniper_features.compute_features_from_snaps), so
there is no train/serve skew.

Validation uses a TIME-BASED split (train on the earlier portion, validate on the
most recent) to avoid look-ahead leakage and to estimate real forward performance.

Run:  python sniper_ml_train.py
"""
import os
import sys
import json
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import asc
from database import SessionLocal
from models import SniperSnapshot
from sniper_features import compute_features_from_snaps
import sniper_ml
import sniper_config as cfg

# ---- Labeling / sampling params (mirror the strategy defaults) -------------
TP = 0.25                 # +scale_out barrier (fraction)
SL = -0.15                # -stop barrier (fraction)
HORIZON_MIN = 120         # time-exit horizon
FEATURE_WINDOW_MIN = 20   # history window for features (matches live)
SAMPLE_EVERY = 3          # decision point every N snapshots (reduce autocorrelation)
MIN_PRIOR_SNAPS = 3       # need >=3 snaps in window for valid features
MIN_FUTURE_MIN = 30       # if no barrier hit, require >=30 min of future to label 0


def _row_dict(r):
    return {c.name: getattr(r, c.name) for c in r.__table__.columns}


def _label(entry_price, future):
    """future = list of (minutes_ahead, price). Triple-barrier outcome or None."""
    if not entry_price or entry_price <= 0:
        return None
    last_min = 0.0
    for dt_min, price in future:
        if not price or price <= 0:
            continue
        last_min = dt_min
        r = (price - entry_price) / entry_price
        if r >= TP:
            return 1
        if r <= SL:
            return 0
    # No barrier touched within the data we have.
    if last_min >= MIN_FUTURE_MIN:
        return 0          # tracked long enough and never reached scale-out -> not a win
    return None           # insufficient forward data -> drop (avoid label noise)


def build_dataset():
    """Return (X rows, y labels, times) reconstructed from all snapshot history."""
    db = SessionLocal()
    try:
        addrs = [a for (a,) in db.query(SniperSnapshot.token_address).distinct().all()]
        print(f"[train] {len(addrs)} distinct tokens")
        X, y, ts = [], [], []
        win_w = timedelta(minutes=FEATURE_WINDOW_MIN)
        hor = timedelta(minutes=HORIZON_MIN)
        for n, addr in enumerate(addrs, 1):
            rows = db.query(SniperSnapshot).filter(
                SniperSnapshot.token_address == addr,
            ).order_by(asc(SniperSnapshot.snapshot_time)).all()
            if len(rows) < MIN_PRIOR_SNAPS + 5:
                continue
            snaps = [_row_dict(r) for r in rows]
            times = [s["snapshot_time"] for s in snaps]
            for i in range(MIN_PRIOR_SNAPS - 1, len(snaps), SAMPLE_EVERY):
                t = times[i]
                if t is None:
                    continue
                # Feature window: snaps in (t - 20min, t]
                window = [s for s, st in zip(snaps, times)
                          if st is not None and (t - win_w) <= st <= t]
                if len(window) < MIN_PRIOR_SNAPS:
                    continue
                feats = compute_features_from_snaps(window, as_of=t)
                if not feats:
                    continue
                entry_price = feats.get("price_usd") or snaps[i].get("price_usd")
                future = [((st - t).total_seconds() / 60.0, s.get("price_usd"))
                          for s, st in zip(snaps[i + 1:], times[i + 1:])
                          if st is not None and st <= t + hor]
                label = _label(entry_price, future)
                if label is None:
                    continue
                X.append(sniper_ml.vectorize(feats))
                y.append(label)
                ts.append(t)
            if n % 100 == 0:
                print(f"[train] processed {n}/{len(addrs)} tokens, {len(X)} samples so far")
        return X, y, ts
    finally:
        db.close()


def train():
    import numpy as np
    import lightgbm as lgb
    from sklearn.metrics import roc_auc_score, average_precision_score

    X, y, ts = build_dataset()
    if len(X) < 500:
        print(f"[train] only {len(X)} samples — too few to train a reliable model. Aborting.")
        return None
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=int)
    order = np.argsort(ts)              # chronological
    X, y = X[order], y[order]
    pos = int(y.sum())
    print(f"[train] samples={len(y)}  positives={pos} ({pos/len(y)*100:.1f}%)")

    # Time-based split: earliest 80% train, latest 20% validate (forward test).
    cut = int(len(y) * 0.8)
    Xtr, ytr, Xva, yva = X[:cut], y[:cut], X[cut:], y[cut:]
    spw = (len(ytr) - ytr.sum()) / max(ytr.sum(), 1)   # balance classes

    dtr = lgb.Dataset(Xtr, label=ytr, feature_name=sniper_ml.FEATURE_COLUMNS)
    dva = lgb.Dataset(Xva, label=yva, reference=dtr)
    params = {
        "objective": "binary", "metric": ["auc", "binary_logloss"],
        "learning_rate": 0.03, "num_leaves": 31, "max_depth": 6,
        "min_data_in_leaf": 50, "feature_fraction": 0.8,
        "bagging_fraction": 0.8, "bagging_freq": 1,
        "scale_pos_weight": spw, "verbose": -1,
    }
    booster = lgb.train(
        params, dtr, num_boost_round=600, valid_sets=[dtr, dva],
        valid_names=["train", "val"],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(0)],
    )

    pva = booster.predict(Xva)
    auc = roc_auc_score(yva, pva) if len(set(yva)) > 1 else float("nan")
    ap = average_precision_score(yva, pva) if len(set(yva)) > 1 else float("nan")
    base = yva.mean()
    print(f"[train] VAL  AUC={auc:.3f}  AvgPrecision={ap:.3f}  (base rate={base:.3f})")

    # Suggest a probability floor: the threshold whose precision is a clear lift
    # over the base win-rate while still admitting a reasonable share of trades.
    floor = _suggest_floor(yva, pva, base)
    print(f"[train] suggested prob floor ~ {floor:.2f} "
          f"(set conviction_floor to {round(floor*100)} in the UI)")

    # Feature importance (gain) — top 12.
    imp = sorted(zip(sniper_ml.FEATURE_COLUMNS, booster.feature_importance("gain")),
                 key=lambda kv: -kv[1])
    print("[train] top features (gain):")
    for name, g in imp[:12]:
        print(f"          {name:24s} {g:,.0f}")

    booster.save_model(sniper_ml.MODEL_PATH)
    meta = {
        "trained_at": datetime.utcnow().isoformat(),
        "n_samples": int(len(y)), "n_pos": pos,
        "val_auc": float(auc), "val_ap": float(ap), "base_rate": float(base),
        "suggested_prob_floor": float(floor),
        "tp": TP, "sl": SL, "horizon_min": HORIZON_MIN,
        "features": sniper_ml.FEATURE_COLUMNS,
        "top_features": [[n, int(g)] for n, g in imp[:20]],
    }
    with open(sniper_ml.META_PATH, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"[train] saved model -> {sniper_ml.MODEL_PATH}")
    sniper_ml.reload_model()
    return meta


def _suggest_floor(y, p, base):
    import numpy as np
    best_floor, best_lift = 0.5, 0.0
    for thr in np.arange(0.30, 0.91, 0.05):
        sel = p >= thr
        if sel.sum() < max(20, 0.03 * len(p)):   # need enough admitted trades
            continue
        prec = y[sel].mean()
        lift = prec - base
        if lift > best_lift:
            best_lift, best_floor = lift, float(thr)
    return best_floor


if __name__ == "__main__":
    train()
