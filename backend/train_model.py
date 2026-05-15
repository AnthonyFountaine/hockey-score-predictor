"""
NHL Model Trainer
------------------
Reads data/training_data.csv and trains a logistic regression model
to predict the probability that a skater scores in a given game.

The learned feature importances are saved to data/model_weights.json
which nhl_stats.py reads to replace its hardcoded defaults.

Requires only numpy and scikit-learn — no GPU, no cloud service.
Training on a full season of data takes < 1 second.

Usage:
    pip install numpy scikit-learn
    python train_model.py
"""

import os
import csv
import json
import math

DATA_DIR     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
CSV_PATH     = os.path.join(DATA_DIR, "training_data.csv")
WEIGHTS_PATH = os.path.join(DATA_DIR, "model_weights.json")

# Minimum number of player-game rows before we trust the model
# enough to override the hardcoded defaults.
MIN_ROWS_TO_TRAIN = 200

# Feature columns in the CSV that we use as model inputs.
# These must match the signal names used in nhl_stats.py's rank_players().
FEATURE_COLS = [
    "gpg_bayesian",
    "goals_last5",
    "shots_per_game",
    "opp_ga_per_game",
    "home_binary",       # derived: 1 if HOME else 0
    "d_binary",          # derived: 1 if position == D else 0
]

TARGET_COL = "scored"


# ─────────────────────────────────────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────────────────────────────────────

def load_csv():
    """
    Load training_data.csv and return (X, y, n_rows).
    Skips rows with missing values in any feature or target column.
    Derives binary columns for home ice and position.
    """
    rows = []
    with open(CSV_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                gpg   = float(row["gpg_bayesian"])
                last5 = float(row["goals_last5"])
                shots = float(row["shots_per_game"])
                opp   = float(row["opp_ga_per_game"])
                home  = 1.0 if row["home_or_away"] == "HOME" else 0.0
                is_d  = 1.0 if str(row.get("position", "")).upper().startswith("D") else 0.0
                y     = int(row[TARGET_COL])
            except (ValueError, KeyError):
                continue   # skip malformed rows

            rows.append(([gpg, last5, shots, opp, home, is_d], y))

    if not rows:
        return [], [], 0

    X = [r[0] for r in rows]
    y = [r[1] for r in rows]
    return X, y, len(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Pure-Python min-max scaler  (avoids sklearn dependency for this step)
# ─────────────────────────────────────────────────────────────────────────────

def fit_scaler(X):
    """Return (mins, maxs) for each feature column."""
    n_feats = len(X[0])
    mins = [min(row[j] for row in X) for j in range(n_feats)]
    maxs = [max(row[j] for row in X) for j in range(n_feats)]
    return mins, maxs


def apply_scaler(X, mins, maxs):
    """Min-max scale X to [0, 1] using precomputed mins/maxs."""
    scaled = []
    for row in X:
        scaled_row = []
        for j, v in enumerate(row):
            rng = maxs[j] - mins[j]
            scaled_row.append((v - mins[j]) / rng if rng > 0 else 0.5)
        scaled.append(scaled_row)
    return scaled


# ─────────────────────────────────────────────────────────────────────────────
# Logistic regression — pure Python + numpy
# ─────────────────────────────────────────────────────────────────────────────

def sigmoid(z):
    """Numerically stable sigmoid."""
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    else:
        e = math.exp(z)
        return e / (1.0 + e)


def train_logistic_regression(X, y, lr=0.1, epochs=500, l2=0.01):
    """
    Gradient descent logistic regression with L2 regularisation.

    Returns (weights, bias) where weights has one entry per feature.

    L2 regularisation prevents overfitting when sample size is modest —
    it pulls weights toward zero unless a feature genuinely predicts scoring.

    lr     : learning rate
    epochs : number of full passes over the training set
    l2     : regularisation strength (higher = more shrinkage)
    """
    n     = len(X)
    n_f   = len(X[0])
    w     = [0.0] * n_f
    b     = 0.0

    for _ in range(epochs):
        dw = [0.0] * n_f
        db = 0.0

        for xi, yi in zip(X, y):
            z    = sum(w[j] * xi[j] for j in range(n_f)) + b
            pred = sigmoid(z)
            err  = pred - yi
            for j in range(n_f):
                dw[j] += err * xi[j]
            db += err

        # Update with L2 penalty on weights (not bias)
        for j in range(n_f):
            w[j] -= lr * (dw[j] / n + l2 * w[j])
        b -= lr * (db / n)

    return w, b


# ─────────────────────────────────────────────────────────────────────────────
# Convert model coefficients → ranking weights
# ─────────────────────────────────────────────────────────────────────────────

def coefficients_to_weights(w, feature_names):
    """
    The logistic regression produces one coefficient per feature.
    Positive coefficients mean the feature increases scoring probability.
    We clip negative coefficients to zero (a signal can't hurt you in ranking),
    then re-normalise the five scoring-signal weights to sum to 1.0.
    The d_binary coefficient becomes the d_multiplier separately.

    feature_names order must match FEATURE_COLS.
    """
    coef = dict(zip(feature_names, w))

    # Extract the position multiplier from the D dummy coefficient.
    # A negative D coefficient means D-men score less → we flip it to a multiplier.
    # clamp between 0.3 and 0.9 to stay reasonable.
    d_coef = coef.get("d_binary", 0.0)
    # The model learned how much *less* D-men score — translate to a 0-1 multiplier.
    # If d_coef is very negative, D-men are much less likely; if near zero, similar.
    d_mult = max(0.30, min(0.90, 1.0 + d_coef))   # d_coef is typically negative

    # Scoring signal weights — clip negatives to a small floor so no signal
    # is completely ignored (the model might have just seen little of it).
    signal_map = {
        "gpg_bayesian":    "w_gpg",
        "goals_last5":     "w_last5",
        "shots_per_game":  "w_shots",
        "opp_ga_per_game": "w_opp",
        "home_binary":     "w_home",
    }

    raw = {}
    for feat, key in signal_map.items():
        raw[key] = max(0.01, coef.get(feat, 0.0))   # floor at 0.01

    # Normalise to sum to 1.0
    total = sum(raw.values())
    normalised = {k: round(v / total, 4) for k, v in raw.items()}

    return {
        **normalised,
        "d_multiplier": round(d_mult, 4),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Evaluation
# ─────────────────────────────────────────────────────────────────────────────

def evaluate(X, y, w, b):
    """
    Compute accuracy, precision, recall, and log-loss on the training set.
    Log-loss is the most meaningful metric for a probability model.
    """
    tp = tn = fp = fn = 0
    log_loss_sum = 0.0
    eps = 1e-9

    for xi, yi in zip(X, y):
        z    = sum(w[j] * xi[j] for j in range(len(w))) + b
        prob = sigmoid(z)
        pred = 1 if prob >= 0.5 else 0

        log_loss_sum += -(yi * math.log(prob + eps) + (1 - yi) * math.log(1 - prob + eps))

        if pred == 1 and yi == 1: tp += 1
        elif pred == 0 and yi == 0: tn += 1
        elif pred == 1 and yi == 0: fp += 1
        else: fn += 1

    n         = len(y)
    accuracy  = (tp + tn) / n if n else 0
    precision = tp / (tp + fp) if (tp + fp) else 0
    recall    = tp / (tp + fn) if (tp + fn) else 0
    log_loss  = log_loss_sum / n if n else 0

    return {
        "accuracy":  round(accuracy,  4),
        "precision": round(precision, 4),
        "recall":    round(recall,    4),
        "log_loss":  round(log_loss,  4),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("\nNHL Model Trainer")
    print("=" * 50)

    if not os.path.exists(CSV_PATH):
        print(f"No training data found at {CSV_PATH}.")
        print("Run results_logger.py first to collect data.")
        return

    print(f"Loading {CSV_PATH} ...")
    X, y, n_rows = load_csv()

    print(f"Loaded {n_rows} player-game rows.")
    n_scored = sum(y)
    print(f"Scored: {n_scored} ({100*n_scored/n_rows:.1f}%)  "
          f"Didn't score: {n_rows - n_scored} ({100*(n_rows-n_scored)/n_rows:.1f}%)")

    if n_rows < MIN_ROWS_TO_TRAIN:
        print(f"\nNeed at least {MIN_ROWS_TO_TRAIN} rows to train reliably "
              f"(have {n_rows}). Keeping existing weights.")
        return

    # Scale features
    mins, maxs  = fit_scaler(X)
    X_scaled    = apply_scaler(X, mins, maxs)

    print(f"\nTraining logistic regression on {n_rows} rows ...")
    w, b = train_logistic_regression(X_scaled, y, lr=0.1, epochs=500, l2=0.01)

    # Evaluate
    metrics = evaluate(X_scaled, y, w, b)
    print(f"\nTraining metrics:")
    print(f"  Accuracy:  {metrics['accuracy']:.4f}")
    print(f"  Precision: {metrics['precision']:.4f}  (of predicted scorers, how many actually scored)")
    print(f"  Recall:    {metrics['recall']:.4f}   (of actual scorers, how many did we predict)")
    print(f"  Log-loss:  {metrics['log_loss']:.4f}  (lower is better; random baseline ≈ 0.69)")

    # Convert coefficients to ranking weights
    converted = coefficients_to_weights(w, FEATURE_COLS)

    print(f"\nLearned weights:")
    for k, v in converted.items():
        print(f"  {k:<20} {v:.4f}")

    # Build final weights dict
    weights = {
        **converted,
        "model_trained":  True,
        "training_games": n_rows,
        "metrics":        metrics,
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(WEIGHTS_PATH, "w", encoding="utf-8") as f:
        json.dump(weights, f, indent=2)

    print(f"\nWeights saved to {WEIGHTS_PATH}")
    print("nhl_stats.py will use these weights on the next run.")


if __name__ == "__main__":
    main()
