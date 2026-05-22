"""
Import Season Training Data
---------------------------
Optimized full-season importer.

The importer makes the minimum practical NHL API calls:
  - one schedule request per team to discover completed games
  - one boxscore request per completed game

Player and opponent pre-game features are then computed locally with rolling
season state. This avoids calling per-player game logs for every player-game.
"""

import csv
import os
import re
import sys
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed

from nhl_features import BASE, HEADERS, LEAGUE_AVG_GPG, SHRINK_K, bayesian_gpg, parse_toi_minutes, resolve_name
from results_logger import CSV_FIELDS, CSV_PATH, DATA_DIR, load_existing_keys, migrate_csv_header

TEAM_ABBREVS = [
    "ANA", "BOS", "BUF", "CAR", "CBJ", "CGY", "CHI", "COL",
    "DAL", "DET", "EDM", "FLA", "LAK", "MIN", "MTL", "NJD",
    "NSH", "NYI", "NYR", "OTT", "PHI", "PIT", "SEA", "SJS",
    "STL", "TBL", "TOR", "UTA", "VAN", "VGK", "WPG", "WSH",
]

FINAL_STATES = {"OFF", "FINAL", "CRIT"}
GAME_TYPES = {2, 3}
MAX_WORKERS = int(os.environ.get("NHL_IMPORT_WORKERS", "12"))
MAX_GAMES = int(os.environ.get("NHL_IMPORT_MAX_GAMES", "0"))
DRY_RUN = os.environ.get("NHL_IMPORT_DRY_RUN", "").lower() in {"1", "true", "yes"}


def log(message=""):
    print(message, flush=True)


def validate_season(value):
    if not re.fullmatch(r"\d{8}", value or ""):
        raise ValueError('Season must look like "20252026".')
    if int(value[:4]) + 1 != int(value[4:]):
        raise ValueError("Season end year must be one year after the start year.")
    return value


def request_json(session, url, timeout=(4, 20)):
    last_exc = None
    for attempt in range(3):
        try:
            response = session.get(url, timeout=timeout)
            if response.status_code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_exc = exc
            time.sleep(0.5 * (attempt + 1))
    raise last_exc


def session_factory():
    import requests

    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def fetch_team_schedule(team, season):
    session = session_factory()
    data = request_json(session, f"{BASE}/club-schedule-season/{team}/{season}")
    return team, data.get("games", [])


def discover_completed_games(season):
    log(f"Discovering completed games for {season} from {len(TEAM_ABBREVS)} team schedules...")
    games_by_id = {}

    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(TEAM_ABBREVS))) as pool:
        futures = {pool.submit(fetch_team_schedule, team, season): team for team in TEAM_ABBREVS}
        for future in as_completed(futures):
            team = futures[future]
            try:
                _, games = future.result()
            except Exception as exc:
                log(f"  Schedule failed for {team}: {exc}")
                continue

            added = 0
            for game in games:
                game_id = str(game.get("id", ""))
                if not game_id:
                    continue
                if str(game.get("season")) != str(season):
                    continue
                if game.get("gameType") not in GAME_TYPES:
                    continue
                if game.get("gameState") not in FINAL_STATES:
                    continue
                games_by_id[game_id] = game
                added += 1
            log(f"  {team}: {added} completed schedule entries read")

    games = sorted(
        games_by_id.values(),
        key=lambda game: (game.get("gameDate", ""), game.get("startTimeUTC", ""), int(game.get("id", 0))),
    )
    log(f"Discovered {len(games)} unique completed regular-season/playoff games.")
    if MAX_GAMES > 0:
        log(f"Limiting import to first {MAX_GAMES} games because NHL_IMPORT_MAX_GAMES is set.")
        games = games[:MAX_GAMES]
    return games


def fetch_boxscore(game):
    session = session_factory()
    game_id = str(game["id"])
    data = request_json(session, f"{BASE}/gamecenter/{game_id}/boxscore")
    return game_id, data


def fetch_boxscores(games):
    log(f"Fetching {len(games)} boxscores with {MAX_WORKERS} workers...")
    boxscores = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_boxscore, game): str(game["id"]) for game in games}
        for done, future in enumerate(as_completed(futures), start=1):
            game_id = futures[future]
            try:
                fetched_id, boxscore = future.result()
                boxscores[fetched_id] = boxscore
            except Exception as exc:
                log(f"  Boxscore failed for {game_id}: {exc}")
            if done == 1 or done % 25 == 0 or done == len(games):
                log(f"  Boxscores fetched: {done}/{len(games)}")
    return boxscores


def new_player_state():
    return {
        "rs_games": 0,
        "rs_goals": 0,
        "rs_assists": 0,
        "rs_points": 0,
        "rs_shots": 0,
        "rs_pp_goals": 0,
        "rs_pp_points": 0,
        "rs_toi": 0.0,
        "rs_last5": deque(maxlen=5),
        "po_games": 0,
        "po_last5": deque(maxlen=5),
    }


def new_team_state():
    return {"games": 0, "goals_against": 0, "saves": 0}


def player_features(state):
    games = state["rs_games"]
    goals = state["rs_goals"]
    shots = state["rs_shots"]
    last5 = state["po_last5"] if state["po_games"] else state["rs_last5"]
    last5_count = len(last5)

    return {
        "goals_reg_season": goals,
        "games_played_reg": games,
        "gpg_bayesian": round(bayesian_gpg(goals, games), 4),
        "assists_reg_season": state["rs_assists"],
        "points_reg_season": state["rs_points"],
        "assists_per_game": round(state["rs_assists"] / games, 4) if games else 0.0,
        "points_per_game": round(state["rs_points"] / games, 4) if games else 0.0,
        "shots_per_game": round(shots / games, 4) if games else 0.0,
        "shooting_pct": round(goals / shots, 4) if shots else 0.0,
        "power_play_goals": state["rs_pp_goals"],
        "power_play_points": state["rs_pp_points"],
        "power_play_goals_per_game": round(state["rs_pp_goals"] / games, 4) if games else 0.0,
        "power_play_points_per_game": round(state["rs_pp_points"] / games, 4) if games else 0.0,
        "avg_toi_minutes": round(state["rs_toi"] / games, 3) if games else 0.0,
        "goals_last5": sum(game["goals"] for game in last5),
        "last5_shots_per_game": round(sum(game["shots"] for game in last5) / last5_count, 4) if last5_count else 0.0,
        "last5_points": sum(game["points"] for game in last5),
        "last5_toi_minutes": round(sum(game["toi"] for game in last5) / last5_count, 3) if last5_count else 0.0,
        "in_playoffs": 1 if state["po_games"] else 0,
    }


def team_defense_features(state):
    games = state["games"]
    goals_against = state["goals_against"]
    shots_against = state["saves"] + goals_against
    return {
        "ga_per_game": round(goals_against / games, 4) if games else "",
        "save_pct": round(state["saves"] / shots_against, 4) if shots_against else "",
    }


def stat_value(player, *keys, default=0):
    for key in keys:
        value = player.get(key)
        if value not in (None, ""):
            return value
    return default


def skater_game_line(player):
    goals = int(stat_value(player, "goals"))
    assists = int(stat_value(player, "assists"))
    points = int(stat_value(player, "points", default=goals + assists))
    shots = int(stat_value(player, "shots", "sog"))
    pp_goals = int(stat_value(player, "powerPlayGoals"))
    pp_points = int(stat_value(player, "powerPlayPoints"))
    toi = parse_toi_minutes(player.get("toi"))
    return {
        "goals": goals,
        "assists": assists,
        "points": points,
        "shots": shots,
        "pp_goals": pp_goals,
        "pp_points": pp_points,
        "toi": toi,
    }


def update_player_state(state, line, game_type):
    if game_type == 2:
        state["rs_games"] += 1
        state["rs_goals"] += line["goals"]
        state["rs_assists"] += line["assists"]
        state["rs_points"] += line["points"]
        state["rs_shots"] += line["shots"]
        state["rs_pp_goals"] += line["pp_goals"]
        state["rs_pp_points"] += line["pp_points"]
        state["rs_toi"] += line["toi"]
        state["rs_last5"].appendleft(line)
    elif game_type == 3:
        state["po_games"] += 1
        state["po_last5"].appendleft(line)


def side_goalie_saves(side_stats):
    return sum(int(stat_value(goalie, "saves")) for goalie in side_stats.get("goalies", []))


def update_team_states(game, player_stats_map, team_states):
    away = game.get("awayTeam", {})
    home = game.get("homeTeam", {})
    away_abbrev = away.get("abbrev")
    home_abbrev = home.get("abbrev")
    away_score = int(away.get("score", 0))
    home_score = int(home.get("score", 0))
    away_stats = player_stats_map.get("awayTeam", {})
    home_stats = player_stats_map.get("homeTeam", {})

    if away_abbrev:
        team_states[away_abbrev]["games"] += 1
        team_states[away_abbrev]["goals_against"] += home_score
        team_states[away_abbrev]["saves"] += side_goalie_saves(away_stats)
    if home_abbrev:
        team_states[home_abbrev]["games"] += 1
        team_states[home_abbrev]["goals_against"] += away_score
        team_states[home_abbrev]["saves"] += side_goalie_saves(home_stats)


def write_training_rows(games, boxscores, writer, existing_keys, season):
    player_states = defaultdict(new_player_state)
    team_states = defaultdict(new_team_state)
    rows_written = 0
    games_processed = 0

    for game in games:
        game_id = str(game["id"])
        boxscore = boxscores.get(game_id)
        if not boxscore:
            continue

        player_stats_map = boxscore.get("playerByGameStats", {})
        if not player_stats_map:
            continue

        game_type = int(game.get("gameType", 2))
        game_date = game.get("gameDate", "")
        away_abbrev = game.get("awayTeam", {}).get("abbrev", "???")
        home_abbrev = game.get("homeTeam", {}).get("abbrev", "???")
        away_defense = team_defense_features(team_states[away_abbrev])
        home_defense = team_defense_features(team_states[home_abbrev])
        game_rows = 0

        for side_key, home_or_away, team_abbrev, opp_abbrev, opp_defense in [
            ("awayTeam", "AWAY", away_abbrev, home_abbrev, home_defense),
            ("homeTeam", "HOME", home_abbrev, away_abbrev, away_defense),
        ]:
            side_stats = player_stats_map.get(side_key, {})
            for group in ("forwards", "defense"):
                for player in side_stats.get(group, []):
                    player_id = str(player.get("playerId"))
                    if not player_id or player_id == "None":
                        continue
                    line = skater_game_line(player)
                    state = player_states[player_id]
                    key = (game_id, player_id)

                    if key not in existing_keys:
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
                            "opp_ga_per_game": opp_defense["ga_per_game"],
                            "opp_save_pct": opp_defense["save_pct"],
                            "scored": 1 if line["goals"] >= 1 else 0,
                            **player_features(state),
                        }
                        writer.writerow(row)
                        existing_keys.add(key)
                        rows_written += 1
                        game_rows += 1

                    update_player_state(state, line, game_type)

        update_team_states(game, player_stats_map, team_states)
        games_processed += 1
        if games_processed == 1 or games_processed % 25 == 0 or games_processed == len(games):
            log(f"  Processed {games_processed}/{len(games)} games through {game_date}; wrote {rows_written} rows")
        elif game_rows:
            log(f"  {game_date} {away_abbrev}@{home_abbrev}: +{game_rows} rows")

    return rows_written


def main():
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python backend/import_season_training_data.py "20252026"')
    season = validate_season(sys.argv[1])

    started = time.time()
    os.makedirs(DATA_DIR, exist_ok=True)
    if not DRY_RUN:
        migrate_csv_header()
    existing_keys = load_existing_keys()

    games = discover_completed_games(season)
    if not games:
        log(f"No completed regular-season/playoff games found for {season}.")
        return

    boxscores = fetch_boxscores(games)
    output_path = os.devnull if DRY_RUN else CSV_PATH
    file_exists = os.path.exists(CSV_PATH)
    if DRY_RUN:
        log("Dry run enabled; training_data.csv will not be modified.")
    with open(output_path, "a", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=CSV_FIELDS)
        if not file_exists and not DRY_RUN:
            writer.writeheader()
        total_rows = write_training_rows(games, boxscores, writer, existing_keys, season)

    elapsed = time.time() - started
    log(f"\nImported {total_rows} new player-game rows for {season} in {elapsed:.1f}s.")


if __name__ == "__main__":
    main()
