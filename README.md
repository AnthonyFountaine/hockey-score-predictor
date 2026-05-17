# Hockey Score Predictor

Daily NHL goal-scorer rankings for the Tim Hortons Hockey Challenge.
Upload screenshots of your three Tim Hortons lists and get AI-powered pick recommendations.

---

## How it works

1. **Every morning at 3 AM ET** a GitHub Actions job runs to update scoring data for yesterday and today
2. The script fetches today's NHL rosters and computes a composite scoring rank for every skater
3. It writes the result to `data/rankings.json` and commits it to the repo
4. The predictor improves itself everyday by training itself based on past scoring data
4. The commit triggers Vercel to rebuild the frontend in ~30 seconds
5. You open the site, upload your Tim Hortons screenshots, and get ranked picks instantly

---

## Project structure

```
hockey-score-predictor/
│
├── .github/
│   └── workflows/
│       └── daily.yml               # Runs all 3 scripts at 3 AM ET daily
│
├── backend/
│   ├── nhl_stats.py                # Fetches rosters + computes rankings
│   │                               #   - Playoff game log for L5G
│   │                               #   - Bayesian-adjusted G/GP
│   │                               #   - Reads model_weights.json if present
│   ├── results_logger.py           # Logs yesterday's actual goal scorers
│   │                               #   - Appends to training_data.csv
│   │                               #   - Runs BEFORE nhl_stats.py each morning
│   ├── train_model.py              # Trains logistic regression on training data
│   │                               #   - Writes model_weights.json
│   │                               #   - Skips if < 200 rows exist yet
│   ├── main.py                     # FastAPI server (name matching endpoint)
│   └── requirements.txt
│
├── data/
│   ├── rankings.json               # Written daily by nhl_stats.py
│   │                               #   - Read by frontend via GitHub raw URL
│   │                               #   - Read by backend /api/analyze endpoint
│   ├── training_data.csv           # Appended daily by results_logger.py
│   │                               #   - One row per skater per game
│   │                               #   - Used to train the model
│   ├── model_weights.json          # Written by train_model.py
│   │                               #   - Replaces hardcoded weights in nhl_stats.py
│   │                               #   - Created after 200+ training rows exist
│   └── logged_dates.json           # Tracks logged dates (prevents duplicates)
│
├── frontend/
│   ├── src/
│   │   └── app/
│   │       ├── layout.tsx          # Root layout + metadata
│   │       ├── page.tsx            # Main UI (rankings table + list input)
│   │       ├── page.module.css     # Component styles
│   │       └── globals.css         # Global dark theme variables
│   ├── package.json
│   ├── next.config.js
│   └── tsconfig.json
│
├── .gitignore
└── README.md
```

---

## Ranking methodology

Each skater is scored using a normalized weighted composite of 5 signals, these were the starting weights:

| Signal | Weight | Notes |
|---|---|---|
| Goals per game (season) | 35% | Primary scoring ability signal |
| Goals in last 5 games | 25% | Recent form / hot streaks |
| Shots on goal per game | 20% | Best predictor of future goals |
| Opponent GA per game | 15% | Weak defence = easier to score |
| Home ice | 5% | Home teams score ~5-8% more |

Defencemen receive a **0.60× position multiplier** since forwards score at roughly twice the rate.
All signals are min-max normalized across the full pool of skaters playing that night before weighting.

Weights are updated everyday based on past data
