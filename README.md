# Hockey Score Predictor

Daily NHL goal-scorer rankings for the Tim Hortons Hockey Challenge.

## How It Works

1. Every morning at 3 AM ET, GitHub Actions logs yesterday's results, retrains when enough data exists, and generates today's rankings.
2. The ranking script fetches today's NHL rosters and computes a composite scoring rank for every skater.
3. It writes the result to `data/rankings.json` and commits it to the repo.
4. The predictor improves from `data/training_data.csv`.
5. Manual Actions can import a whole completed season or retrain the model on demand.
6. The commit triggers the deployed frontend to rebuild.

## Project Structure

```text
hockey-score-predictor/
├── .github/workflows/
│   ├── daily.yml
│   ├── import-season-training-data.yml
│   └── retrain-model.yml
├── backend/
│   ├── import_season_training_data.py
│   ├── main.py
│   ├── nhl_features.py
│   ├── nhl_stats.py
│   ├── results_logger.py
│   ├── train_model.py
│   └── requirements.txt
├── data/
│   ├── rankings.json
│   ├── training_data.csv
│   ├── model_weights.json
│   └── logged_dates.json
└── frontend/
    └── src/app/
```

## Ranking Methodology

Each skater is scored using a normalized weighted composite of NHL API signals:

| Signal | Why it helps |
|---|---|
| Bayesian goals per game | Primary finishing signal with small-sample shrinkage |
| Goals and shots in the last 5 games | Recent form and shot volume |
| Shots per game and shooting percentage | Chance generation plus finishing rate |
| Points, assists, and power-play rates | Role, usage, and offensive environment |
| Average time on ice | Opportunity and coach trust |
| Opponent goals against and save percentage | Matchup difficulty |
| Home ice and position | Context learned from past outcomes |

Defencemen receive a learned position multiplier, defaulting to `0.60x` before enough data exists. All signals are min-max normalized across the full pool of skaters playing that night before weighting.

Historical imports use only player games before the target game date when building each training row, so the model avoids future-data leakage.

## Manual Data Workflows

Use **Actions -> Import Season Training Data** and enter a season string such as `20252026` to append every completed regular-season and playoff skater game from that season into `data/training_data.csv`.

Use **Actions -> Retrain Goal Scorer Model** to retrain `data/model_weights.json` from the latest training data without running the daily rankings job.
