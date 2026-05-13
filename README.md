# Hockey Score Predictor

Daily NHL goal-scorer rankings for the Tim Hortons Hockey Challenge.
Upload screenshots of your three Tim Hortons lists and get AI-powered pick recommendations.

---

## How it works

1. **Every morning at 3 AM ET** a GitHub Actions job runs `backend/nhl_stats.py`
2. The script fetches today's NHL rosters and computes a composite scoring rank for every skater
3. It writes the result to `data/rankings.json` and commits it to the repo
4. The commit triggers Vercel to rebuild the frontend in ~30 seconds
5. You open the site, upload your Tim Hortons screenshots, and get ranked picks instantly

## Project structure

```
hockey-score-predictor/
├── .github/
│   └── workflows/
│       └── daily.yml           # runs nhl_stats.py every morning at 3 AM ET
├── backend/
│   ├── nhl_stats.py            # NHL data fetcher + ranking engine
│   ├── main.py                 # FastAPI server (image upload + Claude OCR)
│   └── requirements.txt
├── data/
│   └── rankings.json           # written by nhl_stats.py, read by the site
├── frontend/
│   ├── src/app/
│   │   ├── layout.tsx
│   │   ├── page.tsx            # main UI
│   │   ├── page.module.css
│   │   └── globals.css
│   ├── package.json
│   ├── next.config.js
│   └── tsconfig.json
└── .gitignore
```

---

## Ranking methodology

Each skater is scored using a normalized weighted composite of 5 signals:

| Signal | Weight | Notes |
|---|---|---|
| Goals per game (season) | 35% | Primary scoring ability signal |
| Goals in last 5 games | 25% | Recent form / hot streaks |
| Shots on goal per game | 20% | Best predictor of future goals |
| Opponent GA per game | 15% | Weak defence = easier to score |
| Home ice | 5% | Home teams score ~5-8% more |

Defencemen receive a **0.60× position multiplier** since forwards score at roughly twice the rate.
All signals are min-max normalized across the full pool of skaters playing that night before weighting.

---

## Updating the season

When a new NHL season starts, update the `SEASON` constant at the top of `backend/nhl_stats.py`:

```python
SEASON = "20262027"   # change this each October
```

Commit and push — the next morning's job will use the new season.
