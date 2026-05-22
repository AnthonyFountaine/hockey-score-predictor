"""
NHL Results Logger
------------------
Appends one training row per skater per completed game.
"""

import csv
import json
import os
import sys
from datetime import date, timedelta

from nhl_features import (
    BASE,
    CSV_SIGNAL_FIELDS,
    SEASON,
    get,
    get_player_stats,
    get_team_defense_stats,
    resolve_name,
)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
CSV_PATH = os.path.join(DATA_DIR, "training_data.csv")
LOGGED_PATH = os.path.join(DATA_DIR, "logged_dates.json")

CSV_FIELDS = [
    "date",
    "season",
    "game_id",
    "player_id",
    "name",
    "team_abbrev",
    "position",
    "home_or_away",
    "opp_team_abbrev",
    *CSV_SIGNAL_FIELDS,
    "scored",
]


def get_games_on_date(game_date):
    data = get(f"{BASE}/schedule/{game_date}")
    games = []
    for day in data.get("gameWeek", []):
        if day.get("date") == game_date:
            games.extend(day.get("games", []))
    return games


def get_final_boxscore(game_id):
    data = get(f"{BASE}/gamecenter/{game_id}/boxscore")
    game_state = data.get("gameState", "")
    if game_state not in ("OFF", "FINAL", "CRIT"):
        print(f"    Skipping game {game_id} - state is {game_state}, not final.")
        return None
    return data


def load_logged_dates():
    if not os.path.exists(LOGGED_PATH):
        return set()
    with open(LOGGED_PATH, encoding="utf-8") as f:
        return set(json.load(f))


def save_logged_dates(dates):
    with open(LOGGED_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(dates), f)


def normalize_row(row):
    return {field: row.get(field, "") for field in CSV_FIELDS}


def migrate_csv_header():
    if not os.path.exists(CSV_PATH):
        return
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames == CSV_FIELDS:
            return
        rows = [normalize_row(row) for row in reader]
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print("  Migrated training_data.csv to the expanded feature schema.")


def load_existing_keys():
    if not os.path.exists(CSV_PATH):
        return set()
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {
            (str(row.get("game_id", "")), str(row.get("player_id", "")))
            for row in reader
            if row.get("game_id") and row.get("player_id")
        }


def csv_stats(stats, opp_defense):
    return {
        "goals_reg_season": stats["goals_total"],
        "games_played_reg": stats["games_played"],
        "gpg_bayesian": stats["goals_per_game"],
        "assists_reg_season": stats["assists_total"],
        "points_reg_season": stats["points_total"],
        "assists_per_game": stats["assists_per_game"],
        "points_per_game": stats["points_per_game"],
        "shots_per_game": stats["shots_per_game"],
        "shooting_pct": stats["shooting_pct"],
        "power_play_goals": stats["power_play_goals"],
        "power_play_points": stats["power_play_points"],
        "power_play_goals_per_game": stats["power_play_goals_per_game"],
        "power_play_points_per_game": stats["power_play_points_per_game"],
        "avg_toi_minutes": stats["avg_toi_minutes"],
        "goals_last5": stats["goals_last5"],
        "last5_shots_per_game": stats["last5_shots_per_game"],
        "last5_points": stats["last5_points"],
        "last5_toi_minutes": stats["last5_toi_minutes"],
        "opp_ga_per_game": opp_defense.get("ga_per_game") if opp_defense.get("ga_per_game") is not None else "",
        "opp_save_pct": opp_defense.get("save_pct") if opp_defense.get("save_pct") is not None else "",
        "in_playoffs": 1 if stats["in_playoffs"] else 0,
    }


def log_date(game_date, writer, season=SEASON, existing_keys=None):
    games = get_games_on_date(game_date)
    if not games:
        print(f"  No games found for {game_date}.")
        return 0

    existing_keys = existing_keys if existing_keys is not None else set()
    rows_written = 0

    for game in games:
        game_id = str(game["id"])
        if str(game.get("season")) != str(season):
            continue
        if game.get("gameType") not in (2, 3):
            continue

        away_info = game.get("awayTeam", {})
        home_info = game.get("homeTeam", {})
        away_abbrev = away_info.get("abbrev", "???")
        home_abbrev = home_info.get("abbrev", "???")
        print(f"  Processing game {game_id}: {away_abbrev} @ {home_abbrev}")

        boxscore = get_final_boxscore(game_id)
        if boxscore is None:
            continue

        player_stats_map = boxscore.get("playerByGameStats", {})
        if not player_stats_map:
            continue

        away_defense = get_team_defense_stats(away_abbrev, season=season, before_date=game_date)
        home_defense = get_team_defense_stats(home_abbrev, season=season, before_date=game_date)

        for side_key, home_or_away, opp_abbrev, opp_defense in [
            ("awayTeam", "AWAY", home_abbrev, home_defense),
            ("homeTeam", "HOME", away_abbrev, away_defense),
        ]:
            team_info = boxscore.get(side_key, {})
            team_abbrev = team_info.get("abbrev", "???")
            side_stats = player_stats_map.get(side_key, {})

            for group in ("forwards", "defense"):
                for player in side_stats.get(group, []):
                    player_id = str(player.get("playerId"))
                    key = (game_id, player_id)
                    if key in existing_keys:
                        continue

                    stats = get_player_stats(player_id, season=season, before_date=game_date)
                    row = {
                        "date": game_date,
                        "season": season,
                        "game_id": game_id,
                        "player_id": player_id,
                        "name": resolve_name(player),
                        "team_abbrev": team_abbrev,
                        "position": player.get("position", "?"),
                        "home_or_away": home_or_away,
                        "opp_team_abbrev": opp_abbrev,
                        "scored": 1 if player.get("goals", 0) >= 1 else 0,
                        **csv_stats(stats, opp_defense),
                    }
                    writer.writerow(row)
                    existing_keys.add(key)
                    rows_written += 1

    return rows_written


def main():
    game_date = sys.argv[1] if len(sys.argv) > 1 else str(date.today() - timedelta(days=1))
    season = sys.argv[2] if len(sys.argv) > 2 else SEASON

    os.makedirs(DATA_DIR, exist_ok=True)
    migrate_csv_header()

    logged_dates = load_logged_dates()
    if game_date in logged_dates:
        print(f"Already logged {game_date} - skipping to avoid duplicates.")
        return

    print(f"\nLogging results for {game_date} (season {season}) ...")
    existing_keys = load_existing_keys()
    file_exists = os.path.exists(CSV_PATH)
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        rows = log_date(game_date, writer, season=season, existing_keys=existing_keys)

    print(f"\nWrote {rows} rows for {game_date}.")
    logged_dates.add(game_date)
    save_logged_dates(logged_dates)


if __name__ == "__main__":
    main()
