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
import time

from nhl_features import FEATURE_SPECS

try:
    import numpy as np
except ImportError:
    np = None

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
CSV_PATH = os.path.join(DATA_DIR, "training_data.csv")
WEIGHTS_PATH = os.path.join(DATA_DIR, "model_weights.json")
MIN_ROWS_TO_TRAIN = int(os.environ.get("NHL_MIN_ROWS_TO_TRAIN", "200"))
TARGET_COL = "scored"
EPOCHS = int(os.environ.get("NHL_TRAIN_EPOCHS", "500"))
LEARNING_RATE = float(os.environ.get("NHL_TRAIN_LR", "0.12"))
L2 = float(os.environ.get("NHL_TRAIN_L2", "0.015"))
PROGRESS_EVERY = int(os.environ.get("NHL_TRAIN_PROGRESS_EVERY", "50"))
EARLY_STOP_DELTA = float(os.environ.get("NHL_TRAIN_EARLY_STOP_DELTA", "0.000001"))
EARLY_STOP_PATIENCE = int(os.environ.get("NHL_TRAIN_EARLY_STOP_PATIENCE", "5"))
DRY_RUN = os.environ.get("NHL_TRAIN_DRY_RUN", "").lower() in {"1", "true", "yes"}
BALANCE_CLASSES = os.environ.get("NHL_TRAIN_BALANCE_CLASSES", "1").lower() not in {"0", "false", "no"}

FEATURE_COLS = [spec["csv"] for spec in FEATURE_SPECS] + ["d_binary"]
SPEC_BY_CSV = {spec["csv"]: spec for spec in FEATURE_SPECS}


def log(message=""):
    print(message, flush=True)


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


def train_logistic_regression_python(X, y, lr=LEARNING_RATE, epochs=EPOCHS, l2=L2):
    n = len(X)
    n_f = len(X[0])
    w = [0.0] * n_f
    b = 0.0
    best_loss = float("inf")
    stale = 0
    sample_weights = make_sample_weights(y)

    for epoch in range(1, epochs + 1):
        dw = [0.0] * n_f
        db = 0.0
        loss_sum = 0.0
        eps = 1e-9
        weight_sum = sum(sample_weights)
        for xi, yi, sample_weight in zip(X, y, sample_weights):
            pred = sigmoid(sum(w[j] * xi[j] for j in range(n_f)) + b)
            err = (pred - yi) * sample_weight
            loss_sum += sample_weight * -(yi * math.log(pred + eps) + (1 - yi) * math.log(1 - pred + eps))
            for j in range(n_f):
                dw[j] += err * xi[j]
            db += err
        for j in range(n_f):
            w[j] -= lr * (dw[j] / weight_sum + l2 * w[j])
        b -= lr * (db / weight_sum)

        loss = loss_sum / weight_sum
        if epoch == 1 or epoch % PROGRESS_EVERY == 0 or epoch == epochs:
            log(f"  epoch {epoch:>4}/{epochs} log_loss={loss:.5f}")
        if best_loss - loss < EARLY_STOP_DELTA:
            stale += 1
        else:
            stale = 0
            best_loss = loss
        if epoch >= PROGRESS_EVERY and stale >= EARLY_STOP_PATIENCE:
            log(f"  early stop at epoch {epoch}; log_loss improvement flattened")
            break
    return w, b


def train_logistic_regression_numpy(X, y, lr=LEARNING_RATE, epochs=EPOCHS, l2=L2):
    X_arr = np.asarray(X, dtype=float)
    y_arr = np.asarray(y, dtype=float)
    sample_weights = np.asarray(make_sample_weights(y), dtype=float)
    weight_sum = float(sample_weights.sum())
    n, n_f = X_arr.shape
    w = np.zeros(n_f, dtype=float)
    b = 0.0
    best_loss = float("inf")
    stale = 0
    eps = 1e-9

    for epoch in range(1, epochs + 1):
        z = X_arr @ w + b
        pred = 1.0 / (1.0 + np.exp(-np.clip(z, -35, 35)))
        err = (pred - y_arr) * sample_weights
        dw = (X_arr.T @ err) / weight_sum + l2 * w
        db = float(err.sum() / weight_sum)
        w -= lr * dw
        b -= lr * db

        if epoch == 1 or epoch % PROGRESS_EVERY == 0 or epoch == epochs:
            per_row_loss = -(y_arr * np.log(pred + eps) + (1 - y_arr) * np.log(1 - pred + eps))
            loss = float((per_row_loss * sample_weights).sum() / weight_sum)
            log(f"  epoch {epoch:>4}/{epochs} log_loss={loss:.5f}")
            if best_loss - loss < EARLY_STOP_DELTA:
                stale += 1
            else:
                stale = 0
                best_loss = loss
            if epoch >= PROGRESS_EVERY and stale >= EARLY_STOP_PATIENCE:
                log(f"  early stop at epoch {epoch}; log_loss improvement flattened")
                break

    return w.tolist(), float(b)


def train_logistic_regression(X, y):
    if np is not None:
        return train_logistic_regression_numpy(X, y)
    log("  NumPy is not installed; using slower pure-Python trainer.")
    return train_logistic_regression_python(X, y)


def make_sample_weights(y):
    if not BALANCE_CLASSES:
        return [1.0] * len(y)
    positives = sum(y)
    negatives = len(y) - positives
    if not positives or not negatives:
        return [1.0] * len(y)
    pos_weight = len(y) / (2 * positives)
    neg_weight = len(y) / (2 * negatives)
    return [pos_weight if value else neg_weight for value in y]


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
    started = time.time()
    log("\nNHL Model Trainer")
    log("=" * 50)
    if not os.path.exists(CSV_PATH):
        log(f"No training data found at {CSV_PATH}.")
        return

    log(f"Loading {CSV_PATH} ...")
    X, y, n_rows = load_csv()
    if not n_rows:
        log("No usable training rows found.")
        return

    n_scored = sum(y)
    log(f"Loaded {n_rows} player-game rows.")
    log(f"Scored: {n_scored} ({100 * n_scored / n_rows:.1f}%)")
    log(f"Features: {', '.join(FEATURE_COLS)}")

    if n_rows < MIN_ROWS_TO_TRAIN:
        log(f"Need at least {MIN_ROWS_TO_TRAIN} rows to train reliably.")
        return

    log("\nScaling features ...")
    mins, maxs = fit_scaler(X)
    X_scaled = apply_scaler(X, mins, maxs)

    engine = "NumPy vectorized" if np is not None else "pure Python"
    log(f"\nTraining logistic regression on {n_rows} rows and {len(FEATURE_COLS)} features ...")
    log(f"Trainer: {engine}; epochs={EPOCHS}; lr={LEARNING_RATE}; l2={L2}; balanced_classes={BALANCE_CLASSES}")
    w, b = train_logistic_regression(X_scaled, y)
    log("Evaluating model ...")
    metrics = evaluate(X_scaled, y, w, b)
    converted = coefficients_to_weights(w)

    log("\nTraining metrics:")
    for key, value in metrics.items():
        log(f"  {key:<12} {value}")

    log("\nLearned ranking weights:")
    for spec in FEATURE_SPECS:
        log(f"  {spec['csv']:<28} {converted[spec['weight']]:.4f}")
    log(f"  {'d_multiplier':<28} {converted['d_multiplier']:.4f}")

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
    if DRY_RUN:
        log("\nDry run enabled; model_weights.json was not modified.")
    else:
        with open(WEIGHTS_PATH, "w", encoding="utf-8") as f:
            json.dump(weights, f, indent=2)
    elapsed = time.time() - started
    if not DRY_RUN:
        log(f"\nWeights saved to {WEIGHTS_PATH}")
    log(f"Done in {elapsed:.1f}s.")


if __name__ == "__main__":
    main()
