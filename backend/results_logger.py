"""
NHL Results Logger
-------------------
Runs at 3 AM ET (before nhl_stats.py) to record who actually scored
in yesterday's games. Appends one row per skater per game to
data/training_data.csv, which train_model.py uses to learn weights.

All games from the previous night are guaranteed to be final by 3 AM ET,
including late West Coast games that finish past midnight.

Usage:
    python results_logger.py               # logs yesterday automatically
    python results_logger.py 2026-05-13    # log a specific past date
"""

import os
import sys
import csv
import json
import time
import requests
from datetime import date, timedelta

BASE    = "https://api-web.nhle.com/v1"
SEASON  = "20252026"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":  "application/json",
    "Referer": "https://www.nhl.com/",
    "Origin":  "https://www.nhl.com",
}

DATA_DIR    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
CSV_PATH    = os.path.join(DATA_DIR, "training_data.csv")
LOGGED_PATH = os.path.join(DATA_DIR, "logged_dates.json")

CSV_FIELDS = [
    "date",
    "game_id",
    "player_id",
    "name",
    "team_abbrev",
    "position",
    "home_or_away",
    "opp_team_abbrev",
    "goals_reg_season",       # total regular season goals
    "games_played_reg",       # regular season GP
    "gpg_bayesian",           # Bayesian-adjusted G/GP
    "goals_last5",            # last 5 games (playoff if active, else reg)
    "shots_per_game",         # regular season SOG/G
    "opp_ga_per_game",        # opponent's GA/game
    "in_playoffs",            # 1 if player has playoff games, else 0
    "scored",                 # TARGET: 1 if scored >= 1 goal in this game, else 0
]


# ─────────────────────────────────────────────────────────────────────────────
# HTTP
# ─────────────────────────────────────────────────────────────────────────────

def get(url):
    for attempt in range(3):
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 429:
            time.sleep(2 ** attempt)
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()


# ─────────────────────────────────────────────────────────────────────────────
# Already-logged dates  (prevent duplicate rows on re-runs)
# ─────────────────────────────────────────────────────────────────────────────

def load_logged_dates():
    if not os.path.exists(LOGGED_PATH):
        return set()
    with open(LOGGED_PATH, encoding="utf-8") as f:
        return set(json.load(f))


def save_logged_dates(dates):
    with open(LOGGED_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(dates), f)


# ─────────────────────────────────────────────────────────────────────────────
# Schedule + boxscore
# ─────────────────────────────────────────────────────────────────────────────

def get_games_on_date(game_date):
    data  = get(f"{BASE}/schedule/{game_date}")
    games = []
    for day in data.get("gameWeek", []):
        if day.get("date") == game_date:
            games.extend(day.get("games", []))
    return games


def get_final_boxscore(game_id):
    """
    Return the boxscore dict for a completed game.
    Returns None if the game isn't in a final state.
    """
    data       = get(f"{BASE}/gamecenter/{game_id}/boxscore")
    game_state = data.get("gameState", "")

    # OFF = official final, FINAL = final, CRIT = critical (OT/SO) but still final
    if game_state not in ("OFF", "FINAL", "CRIT"):
        print(f"    Skipping game {game_id} — state is {game_state}, not final yet.")
        return None

    return data


# ─────────────────────────────────────────────────────────────────────────────
# Player stats (same logic as nhl_stats.py — kept local to avoid import coupling)
# ─────────────────────────────────────────────────────────────────────────────

LEAGUE_AVG_GPG = 0.15
SHRINK_K       = 20


def bayesian_gpg(goals, games_played):
    if not games_played:
        return LEAGUE_AVG_GPG
    return (goals + LEAGUE_AVG_GPG * SHRINK_K) / (games_played + SHRINK_K)


def get_player_stats(player_id):
    """Fetch reg season + playoff logs and compute all signals."""
    if not player_id:
        return None

    try:
        rs_log = get(f"{BASE}/player/{player_id}/game-log/{SEASON}/2").get("gameLog", [])
    except Exception:
        rs_log = []

    try:
        po_log = get(f"{BASE}/player/{player_id}/game-log/{SEASON}/3").get("gameLog", [])
    except Exception:
        po_log = []

    in_playoffs = len(po_log) > 0
    rs_goals    = sum(g.get("goals", 0) for g in rs_log)
    rs_shots    = sum(g.get("shots", 0) for g in rs_log)
    rs_played   = len(rs_log)
    last5_log   = po_log[:5] if in_playoffs else rs_log[:5]
    last5_goals = sum(g.get("goals", 0) for g in last5_log)

    return {
        "goals_reg_season": rs_goals,
        "games_played_reg": rs_played,
        "gpg_bayesian":     round(bayesian_gpg(rs_goals, rs_played), 4),
        "goals_last5":      last5_goals,
        "shots_per_game":   round(rs_shots / rs_played, 3) if rs_played else 0.0,
        "in_playoffs":      1 if in_playoffs else 0,
    }


def get_team_ga_per_game(team_abbrev):
    for game_type in (3, 2):
        try:
            data    = get(f"{BASE}/club-stats/{team_abbrev}/{SEASON}/{game_type}")
            goalies = data.get("goalies", [])
            if not goalies:
                continue
            total_ga = sum(g.get("goalsAgainst", 0) for g in goalies)
            team_gp  = sum(g.get("gamesStarted", 0) for g in goalies)
            if team_gp > 0:
                return round(total_ga / team_gp, 3)
        except Exception:
            continue
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Core logging logic
# ─────────────────────────────────────────────────────────────────────────────

def resolve_name(p):
    name_obj = p.get("name", {})
    if isinstance(name_obj, dict) and name_obj.get("default"):
        return name_obj["default"]
    first = p.get("firstName", {})
    last  = p.get("lastName",  {})
    first = first.get("default", "") if isinstance(first, dict) else str(first)
    last  = last.get("default",  "") if isinstance(last,  dict) else str(last)
    return f"{first} {last}".strip()


def log_date(game_date, writer):
    """
    Fetch all final games for game_date, pull each player's actual goals
    from the boxscore, fetch their pre-game signal stats, and write rows.

    Returns number of rows written.
    """
    games = get_games_on_date(game_date)
    if not games:
        print(f"  No games found for {game_date}.")
        return 0

    rows_written = 0

    for game in games:
        game_id     = game["id"]
        away_info   = game.get("awayTeam", {})
        home_info   = game.get("homeTeam", {})
        away_abbrev = away_info.get("abbrev", "???")
        home_abbrev = home_info.get("abbrev", "???")

        print(f"  Processing game {game_id}: {away_abbrev} @ {home_abbrev}")

        boxscore = get_final_boxscore(game_id)
        if boxscore is None:
            continue

        player_stats_map = boxscore.get("playerByGameStats", {})
        if not player_stats_map:
            print(f"    No player stats in boxscore for game {game_id} — skipping.")
            continue

        # Fetch team GA for each side
        away_ga_pg = get_team_ga_per_game(away_abbrev)
        home_ga_pg = get_team_ga_per_game(home_abbrev)

        for side_key, home_or_away, opp_abbrev, opp_ga_pg in [
            ("awayTeam", "AWAY", home_abbrev, home_ga_pg),
            ("homeTeam", "HOME", away_abbrev, away_ga_pg),
        ]:
            team_info  = boxscore.get(side_key, {})
            team_abrv  = team_info.get("abbrev", "???")
            side_stats = player_stats_map.get(side_key, {})

            for group in ("forwards", "defense"):   # exclude goalies
                for p in side_stats.get(group, []):
                    player_id    = p.get("playerId")
                    name         = resolve_name(p)
                    position     = p.get("position", "?")
                    goals_in_game = p.get("goals", 0)

                    # Fetch pre-game signals
                    stats = get_player_stats(player_id)
                    if stats is None:
                        continue

                    writer.writerow({
                        "date":            game_date,
                        "game_id":         game_id,
                        "player_id":       player_id,
                        "name":            name,
                        "team_abbrev":     team_abrv,
                        "position":        position,
                        "home_or_away":    home_or_away,
                        "opp_team_abbrev": opp_abbrev,
                        "opp_ga_per_game": opp_ga_pg if opp_ga_pg is not None else "",
                        "scored":          1 if goals_in_game >= 1 else 0,
                        **stats,
                    })
                    rows_written += 1

    return rows_written


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    # Default: log yesterday (all games guaranteed final by 3 AM ET)
    if len(sys.argv) > 1:
        game_date = sys.argv[1]
    else:
        game_date = str(date.today() - timedelta(days=1))

    os.makedirs(DATA_DIR, exist_ok=True)

    logged_dates = load_logged_dates()
    if game_date in logged_dates:
        print(f"Already logged {game_date} — skipping to avoid duplicates.")
        return

    print(f"\nLogging results for {game_date} ...")

    # Open CSV in append mode; write header only on first creation
    file_exists = os.path.exists(CSV_PATH)
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
            print("  Created training_data.csv with headers.")

        rows = log_date(game_date, writer)

    print(f"\nWrote {rows} rows for {game_date}.")

    logged_dates.add(game_date)
    save_logged_dates(logged_dates)
    print(f"Marked {game_date} as logged.")


if __name__ == "__main__":
    main()
