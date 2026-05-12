"""
Hockey Score Predictor — FastAPI Backend
-----------------------------------------
Endpoints:
  GET  /api/rankings          Return today's pre-computed rankings JSON
  POST /api/analyze           Accept three lists of player names as plain text,
                              match them against today's rankings, return
                              ranked picks per list

Run locally:
  pip install fastapi uvicorn
  uvicorn main:app --reload --port 8000

Deploy: Render.com → New Web Service → connect repo → root dir = backend
        Start command: uvicorn main:app --host 0.0.0.0 --port $PORT
"""

import json
import pathlib
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Hockey Score Predictor API")

# Allow the Next.js frontend (localhost dev + Vercel prod) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Path to the JSON written by nhl_stats.py
DATA_PATH = pathlib.Path(__file__).parent.parent / "data" / "rankings.json"


# ─────────────────────────────────────────────────────────────────────────────
# Request / response models
# ─────────────────────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    list1: List[str] = []
    list2: List[str] = []
    list3: List[str] = []


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_rankings() -> dict:
    if not DATA_PATH.exists():
        raise HTTPException(status_code=503, detail="Rankings not yet generated for today.")
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def match_names_to_rankings(names: List[str], all_ranked: List[dict]) -> List[dict]:
    """
    Fuzzy-match a list of player name strings against the full ranked list.
    Returns matched players in ranked order (best score first).

    Strategy: lowercase substring match in both directions so that
    "MacKinnon" matches "Nathan MacKinnon" and vice-versa.
    """
    if not names:
        return []

    matched     = []
    names_lower = [n.lower().strip() for n in names if n.strip()]

    for player in all_ranked:  # already sorted by score descending
        player_lower = player["name"].lower()
        for nl in names_lower:
            if nl and (nl in player_lower or player_lower in nl):
                matched.append(player)
                break  # don't double-add the same player

    return matched


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/rankings")
def get_rankings():
    """Return today's full rankings JSON as-is."""
    return load_rankings()


@app.post("/api/analyze")
def analyze(body: AnalyzeRequest):
    """
    Accept three lists of player names, match each against today's rankings,
    and return ranked picks with a highlighted top pick per list.
    """
    data       = load_rankings()
    all_ranked = data.get("ranking", [])

    results = {}
    for list_num, names in [(1, body.list1), (2, body.list2), (3, body.list3)]:
        matched = match_names_to_rankings(names, all_ranked)
        results[f"list{list_num}"] = {
            "ranked_picks": matched,
            "top_pick":     matched[0] if matched else None,
        }

    return {
        "date":    data.get("date"),
        "results": results,
    }


@app.get("/health")
def health():
    return {"status": "ok"}
