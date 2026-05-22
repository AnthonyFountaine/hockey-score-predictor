"""
NHL Model Trainer
-----------------
Trains a regularized logistic regression on data/training_data.csv and writes
feature weights for the nightly scorer rankings.
"""

import csv
import json
import math
import os

from nhl_features import FEATURE_SPECS

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
CSV_PATH = os.path.join(DATA_DIR, "training_data.csv")
WEIGHTS_PATH = os.path.join(DATA_DIR, "model_weights.json")
MIN_ROWS_TO_TRAIN = 200
TARGET_COL = "scored"

FEATURE_COLS = [spec["csv"] for spec in FEATURE_SPECS] + ["d_binary"]
SPEC_BY_CSV = {spec["csv"]: spec for spec in FEATURE_SPECS}


def safe_float(value, default=0.0):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def load_csv():
    rows = []
    with open(CSV_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                y = int(row[TARGET_COL])
            except (ValueError, KeyError):
                continue

            features = []
            for col in FEATURE_COLS:
                if col == "home_binary":
                    features.append(1.0 if row.get("home_or_away") == "HOME" else 0.0)
                elif col == "d_binary":
                    features.append(1.0 if str(row.get("position", "")).upper().startswith("D") else 0.0)
                else:
                    features.append(safe_float(row.get(col)))
            rows.append((features, y))

    if not rows:
        return [], [], 0
    return [r[0] for r in rows], [r[1] for r in rows], len(rows)


def fit_scaler(X):
    n_feats = len(X[0])
    mins = [min(row[j] for row in X) for j in range(n_feats)]
    maxs = [max(row[j] for row in X) for j in range(n_feats)]
    return mins, maxs


def apply_scaler(X, mins, maxs):
    scaled = []
    for row in X:
        scaled_row = []
        for j, value in enumerate(row):
            rng = maxs[j] - mins[j]
            scaled_row.append((value - mins[j]) / rng if rng > 0 else 0.5)
        scaled.append(scaled_row)
    return scaled


def sigmoid(z):
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def train_logistic_regression(X, y, lr=0.1, epochs=800, l2=0.015):
    n = len(X)
    n_f = len(X[0])
    w = [0.0] * n_f
    b = 0.0

    for _ in range(epochs):
        dw = [0.0] * n_f
        db = 0.0
        for xi, yi in zip(X, y):
            pred = sigmoid(sum(w[j] * xi[j] for j in range(n_f)) + b)
            err = pred - yi
            for j in range(n_f):
                dw[j] += err * xi[j]
            db += err
        for j in range(n_f):
            w[j] -= lr * (dw[j] / n + l2 * w[j])
        b -= lr * (db / n)
    return w, b


def coefficients_to_weights(w):
    coef = dict(zip(FEATURE_COLS, w))
    d_coef = coef.get("d_binary", 0.0)
    d_mult = max(0.30, min(0.95, 1.0 + d_coef))

    raw = {}
    for spec in FEATURE_SPECS:
        c = coef.get(spec["csv"], 0.0) * spec["direction"]
        raw[spec["weight"]] = max(0.005, c)

    total = sum(raw.values())
    normalized = {key: round(value / total, 4) for key, value in raw.items()}
    return {
        **normalized,
        "d_multiplier": round(d_mult, 4),
        "coefficients": {name: round(value, 6) for name, value in coef.items()},
    }


def evaluate(X, y, w, b):
    tp = tn = fp = fn = 0
    log_loss_sum = 0.0
    eps = 1e-9

    for xi, yi in zip(X, y):
        prob = sigmoid(sum(w[j] * xi[j] for j in range(len(w))) + b)
        pred = 1 if prob >= 0.5 else 0
        log_loss_sum += -(yi * math.log(prob + eps) + (1 - yi) * math.log(1 - prob + eps))
        if pred == 1 and yi == 1:
            tp += 1
        elif pred == 0 and yi == 0:
            tn += 1
        elif pred == 1 and yi == 0:
            fp += 1
        else:
            fn += 1

    n = len(y)
    return {
        "accuracy": round((tp + tn) / n, 4) if n else 0,
        "precision": round(tp / (tp + fp), 4) if (tp + fp) else 0,
        "recall": round(tp / (tp + fn), 4) if (tp + fn) else 0,
        "log_loss": round(log_loss_sum / n, 4) if n else 0,
        "scored_rows": sum(y),
    }


def main():
    print("\nNHL Model Trainer")
    print("=" * 50)
    if not os.path.exists(CSV_PATH):
        print(f"No training data found at {CSV_PATH}.")
        return

    X, y, n_rows = load_csv()
    if not n_rows:
        print("No usable training rows found.")
        return

    n_scored = sum(y)
    print(f"Loaded {n_rows} player-game rows.")
    print(f"Scored: {n_scored} ({100 * n_scored / n_rows:.1f}%)")

    if n_rows < MIN_ROWS_TO_TRAIN:
        print(f"Need at least {MIN_ROWS_TO_TRAIN} rows to train reliably.")
        return

    mins, maxs = fit_scaler(X)
    X_scaled = apply_scaler(X, mins, maxs)

    print(f"\nTraining logistic regression on {n_rows} rows and {len(FEATURE_COLS)} features ...")
    w, b = train_logistic_regression(X_scaled, y)
    metrics = evaluate(X_scaled, y, w, b)
    converted = coefficients_to_weights(w)

    print("\nTraining metrics:")
    for key, value in metrics.items():
        print(f"  {key:<12} {value}")

    print("\nLearned ranking weights:")
    for spec in FEATURE_SPECS:
        print(f"  {spec['csv']:<28} {converted[spec['weight']]:.4f}")
    print(f"  {'d_multiplier':<28} {converted['d_multiplier']:.4f}")

    weights = {
        **converted,
        "model_trained": True,
        "training_games": n_rows,
        "feature_columns": FEATURE_COLS,
        "metrics": metrics,
        "scaler": {
            "mins": dict(zip(FEATURE_COLS, mins)),
            "maxs": dict(zip(FEATURE_COLS, maxs)),
        },
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(WEIGHTS_PATH, "w", encoding="utf-8") as f:
        json.dump(weights, f, indent=2)
    print(f"\nWeights saved to {WEIGHTS_PATH}")


if __name__ == "__main__":
    main()
