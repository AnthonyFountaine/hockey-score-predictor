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

---

## Setup — do this once

### Step 1 — Create the GitHub repo

1. Go to https://github.com/new
2. Name it `hockey-score-predictor`
3. Set it to **Private** (recommended) or Public
4. Do **not** add a README (you already have one)
5. Click **Create repository**

### Step 2 — Push this code

In your terminal, from inside this project folder:

```bash
git init
git add .
git commit -m "initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/hockey-score-predictor.git
git push -u origin main
```

Replace `YOUR_USERNAME` with your GitHub username.

### Step 3 — Deploy the backend to Render

1. Go to https://render.com and sign up (free)
2. Click **New → Web Service**
3. Connect your GitHub account and select the `hockey-score-predictor` repo
4. Fill in:
   - **Name**: `hockey-score-predictor-api`
   - **Root Directory**: `backend`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Plan**: Free
5. Under **Environment Variables**, add:
   - Key: `ANTHROPIC_API_KEY`  Value: your Anthropic API key (get one at https://console.anthropic.com)
6. Click **Create Web Service**
7. Wait ~2 minutes. Copy your Render URL — it will look like `https://hockey-score-predictor-api.onrender.com`

### Step 4 — Deploy the frontend to Vercel

1. Go to https://vercel.com and sign up (free)
2. Click **Add New → Project**
3. Import your `hockey-score-predictor` repo
4. Under **Framework Preset** choose **Next.js**
5. Set **Root Directory** to `frontend`
6. Under **Environment Variables**, add:
   - Key: `NEXT_PUBLIC_API_URL`  Value: your Render URL from Step 3 (no trailing slash)
7. Click **Deploy**
8. Your site will be live at `https://hockey-score-predictor.vercel.app` (or similar)

### Step 5 — Trigger the first rankings run

The GitHub Action runs automatically at 3 AM ET every day, but you can trigger it manually right now:

1. Go to your repo on GitHub
2. Click the **Actions** tab
3. Click **Daily NHL Rankings** in the left sidebar
4. Click **Run workflow → Run workflow**
5. Wait ~2–3 minutes for it to complete
6. Go back to your site and click **Load Rankings**

---

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
