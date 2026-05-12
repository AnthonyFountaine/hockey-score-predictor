"""
Hockey Score Predictor — FastAPI Backend
-----------------------------------------
Endpoints:
  GET  /api/rankings          Return today's pre-computed rankings JSON
  POST /api/analyze           Accept screenshots for all 3 lists, OCR them
                              with Claude vision, match names against today's
                              rankings, return ranked picks per list

Run locally:
  pip install fastapi uvicorn python-multipart anthropic
  uvicorn main:app --reload --port 8000

Deploy: Render.com → New Web Service → connect repo → root dir = backend
        Start command: uvicorn main:app --host 0.0.0.0 --port $PORT
"""

import os
import json
import base64
import pathlib
from typing import List

import anthropic
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Hockey Score Predictor API")

# Allow the Next.js frontend (localhost dev + Vercel prod) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten to your Vercel domain in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# Path to the JSON written by nhl_stats.py
DATA_PATH = pathlib.Path(__file__).parent.parent / "data" / "rankings.json"

anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_rankings() -> dict:
    if not DATA_PATH.exists():
        raise HTTPException(status_code=503, detail="Rankings not yet generated for today.")
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def images_to_content_blocks(files: List[UploadFile]) -> list:
    """Convert uploaded image files into Anthropic vision content blocks."""
    blocks = []
    for f in files:
        raw      = f.file.read()
        b64      = base64.standard_b64encode(raw).decode()
        media    = f.content_type or "image/jpeg"
        blocks.append({
            "type":   "image",
            "source": {"type": "base64", "media_type": media, "data": b64},
        })
    return blocks


def extract_names_from_images(image_blocks: list, list_number: int) -> List[str]:
    """
    Send screenshot(s) for one Tim Hortons list to Claude vision.
    Returns a list of player name strings exactly as they appear in the screenshots.
    Multiple screenshots are sent in one call so Claude sees the full list.
    """
    if not image_blocks:
        return []

    prompt_blocks = image_blocks + [{
        "type": "text",
        "text": (
            f"These are screenshot(s) from the Tim Hortons NHL game app showing "
            f"List {list_number} of players. "
            "Extract every player name visible across all screenshots. "
            "Return ONLY a JSON array of strings, one name per element, "
            "exactly as written — no extra text, no markdown fences. "
            "Example: [\"Nathan MacKinnon\", \"Auston Matthews\"]"
        ),
    }]

    response = anthropic_client.messages.create(
        model      = "claude-opus-4-5",
        max_tokens = 512,
        messages   = [{"role": "user", "content": prompt_blocks}],
    )

    raw_text = response.content[0].text.strip()

    # Strip markdown fences if Claude added them despite instructions
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]

    try:
        names = json.loads(raw_text)
        return [str(n).strip() for n in names if n]
    except json.JSONDecodeError:
        # Fallback: split by newline
        return [line.strip("•- ").strip() for line in raw_text.splitlines() if line.strip()]


def match_names_to_rankings(names: List[str], all_ranked: List[dict]) -> List[dict]:
    """
    Fuzzy-match extracted names against the ranked player list.
    Returns only the matched players, in their ranked order,
    with their full stats attached.

    Matching strategy: lowercase substring match in both directions
    (handles abbreviations, missing accents, etc.)
    """
    matched = []
    names_lower = [n.lower() for n in names]

    for player in all_ranked:   # already sorted by score desc
        player_lower = player["name"].lower()
        for nl in names_lower:
            if nl in player_lower or player_lower in nl:
                matched.append(player)
                break   # don't double-add

    return matched


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/rankings")
def get_rankings():
    """Return today's full rankings JSON as-is."""
    return load_rankings()


@app.post("/api/analyze")
async def analyze(
    list1: List[UploadFile] = File(default=[]),
    list2: List[UploadFile] = File(default=[]),
    list3: List[UploadFile] = File(default=[]),
):
    """
    Accept 1-N screenshots per list, OCR them with Claude vision,
    match each player name against today's rankings, and return
    ranked picks for each list.
    """
    data       = load_rankings()
    all_ranked = data.get("ranking", [])

    results = {}
    for list_num, files in [(1, list1), (2, list2), (3, list3)]:
        if not files:
            results[f"list{list_num}"] = []
            continue

        image_blocks   = images_to_content_blocks(files)
        names          = extract_names_from_images(image_blocks, list_num)
        matched        = match_names_to_rankings(names, all_ranked)

        results[f"list{list_num}"] = {
            "extracted_names": names,
            "ranked_picks":    matched,
            "top_pick":        matched[0] if matched else None,
        }

    return {
        "date":    data.get("date"),
        "results": results,
    }


@app.get("/health")
def health():
    return {"status": "ok"}
