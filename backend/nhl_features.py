import math
import os
import time
from datetime import datetime

BASE = "https://api-web.nhle.com/v1"
SEASON = os.environ.get("NHL_SEASON", "20252026")

LEAGUE_AVG_GPG = 0.15
SHRINK_K = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.nhl.com/",
    "Origin": "https://www.nhl.com",
}


FEATURE_SPECS = [
    {"csv": "gpg_bayesian", "player": "goals_per_game", "weight": "w_gpg", "default": 0.20, "direction": 1},
    {"csv": "goals_last5", "player": "goals_last5", "weight": "w_last5", "default": 0.13, "direction": 1},
    {"csv": "shots_per_game", "player": "shots_per_game", "weight": "w_shots", "default": 0.15, "direction": 1},
    {"csv": "shooting_pct", "player": "shooting_pct", "weight": "w_shooting_pct", "default": 0.07, "direction": 1},
    {"csv": "points_per_game", "player": "points_per_game", "weight": "w_points_per_game", "default": 0.08, "direction": 1},
    {"csv": "power_play_goals_per_game", "player": "power_play_goals_per_game", "weight": "w_pp_goals", "default": 0.07, "direction": 1},
    {"csv": "power_play_points_per_game", "player": "power_play_points_per_game", "weight": "w_pp_points", "default": 0.04, "direction": 1},
    {"csv": "avg_toi_minutes", "player": "avg_toi_minutes", "weight": "w_avg_toi", "default": 0.08, "direction": 1},
    {"csv": "last5_shots_per_game", "player": "last5_shots_per_game", "weight": "w_last5_shots", "default": 0.06, "direction": 1},
    {"csv": "last5_points", "player": "last5_points", "weight": "w_last5_points", "default": 0.04, "direction": 1},
    {"csv": "opp_ga_per_game", "player": "opp_ga_per_game", "weight": "w_opp_ga", "default": 0.05, "direction": 1},
    {"csv": "opp_save_pct", "player": "opp_save_pct", "weight": "w_opp_save_pct", "default": 0.02, "direction": -1},
    {"csv": "home_binary", "player": "home_binary", "weight": "w_home", "default": 0.01, "direction": 1},
]

CSV_SIGNAL_FIELDS = [
    "goals_reg_season",
    "games_played_reg",
    "gpg_bayesian",
    "assists_reg_season",
    "points_reg_season",
    "assists_per_game",
    "points_per_game",
    "shots_per_game",
    "shooting_pct",
    "power_play_goals",
    "power_play_points",
    "power_play_goals_per_game",
    "power_play_points_per_game",
    "avg_toi_minutes",
    "goals_last5",
    "last5_shots_per_game",
    "last5_points",
    "last5_toi_minutes",
    "opp_ga_per_game",
    "opp_save_pct",
    "in_playoffs",
]


def get(url):
    import requests

    for attempt in range(3):
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 429:
            time.sleep(2 ** attempt)
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()


def resolve_name(p):
    name_obj = p.get("name", {})
    if isinstance(name_obj, dict) and name_obj.get("default"):
        return name_obj["default"]
    first = p.get("firstName", {})
    last = p.get("lastName", {})
    first = first.get("default", "") if isinstance(first, dict) else str(first)
    last = last.get("default", "") if isinstance(last, dict) else str(last)
    return f"{first} {last}".strip()


def bayesian_gpg(goals, games_played):
    if not games_played:
        return LEAGUE_AVG_GPG
    return (goals + LEAGUE_AVG_GPG * SHRINK_K) / (games_played + SHRINK_K)


def parse_toi_minutes(value):
    if not value or not isinstance(value, str) or ":" not in value:
        return 0.0
    minutes, seconds = value.split(":", 1)
    try:
        return int(minutes) + int(seconds) / 60.0
    except ValueError:
        return 0.0


def filter_log_before(log, before_date):
    if not before_date:
        return log
    return [g for g in log if g.get("gameDate") and g.get("gameDate") < before_date]


def get_player_game_log(player_id, season, game_type):
    try:
        return get(f"{BASE}/player/{player_id}/game-log/{season}/{game_type}").get("gameLog", [])
    except Exception:
        return []


def get_player_stats(player_id, season=SEASON, before_date=None):
    empty = {
        "goals_total": 0,
        "games_played": 0,
        "goals_per_game": LEAGUE_AVG_GPG,
        "assists_total": 0,
        "points_total": 0,
        "assists_per_game": 0.0,
        "points_per_game": 0.0,
        "shots_per_game": 0.0,
        "shooting_pct": 0.0,
        "power_play_goals": 0,
        "power_play_points": 0,
        "power_play_goals_per_game": 0.0,
        "power_play_points_per_game": 0.0,
        "avg_toi_minutes": 0.0,
        "goals_last5": 0,
        "last5_shots_per_game": 0.0,
        "last5_points": 0,
        "last5_toi_minutes": 0.0,
        "in_playoffs": False,
    }
    if not player_id:
        return empty

    rs_log = filter_log_before(get_player_game_log(player_id, season, 2), before_date)
    po_log = filter_log_before(get_player_game_log(player_id, season, 3), before_date)
    active_log = po_log if po_log else rs_log
    last5_log = active_log[:5]

    games_played = len(rs_log)
    goals = sum(g.get("goals", 0) for g in rs_log)
    assists = sum(g.get("assists", 0) for g in rs_log)
    points = sum(g.get("points", 0) for g in rs_log)
    shots = sum(g.get("shots", 0) for g in rs_log)
    pp_goals = sum(g.get("powerPlayGoals", 0) for g in rs_log)
    pp_points = sum(g.get("powerPlayPoints", 0) for g in rs_log)
    toi_total = sum(parse_toi_minutes(g.get("toi")) for g in rs_log)

    last5_count = len(last5_log)
    last5_shots = sum(g.get("shots", 0) for g in last5_log)
    last5_points = sum(g.get("points", 0) for g in last5_log)
    last5_toi = sum(parse_toi_minutes(g.get("toi")) for g in last5_log)

    if not games_played:
        return {**empty, "in_playoffs": bool(po_log)}

    return {
        "goals_total": goals,
        "games_played": games_played,
        "goals_per_game": round(bayesian_gpg(goals, games_played), 4),
        "assists_total": assists,
        "points_total": points,
        "assists_per_game": round(assists / games_played, 4),
        "points_per_game": round(points / games_played, 4),
        "shots_per_game": round(shots / games_played, 4),
        "shooting_pct": round(goals / shots, 4) if shots else 0.0,
        "power_play_goals": pp_goals,
        "power_play_points": pp_points,
        "power_play_goals_per_game": round(pp_goals / games_played, 4),
        "power_play_points_per_game": round(pp_points / games_played, 4),
        "avg_toi_minutes": round(toi_total / games_played, 3),
        "goals_last5": sum(g.get("goals", 0) for g in last5_log),
        "last5_shots_per_game": round(last5_shots / last5_count, 4) if last5_count else 0.0,
        "last5_points": last5_points,
        "last5_toi_minutes": round(last5_toi / last5_count, 3) if last5_count else 0.0,
        "in_playoffs": bool(po_log),
    }


def get_team_defense_stats(team_abbrev, season=SEASON, before_date=None):
    if before_date:
        return get_team_defense_from_schedule(team_abbrev, season, before_date)

    for game_type in (3, 2):
        try:
            data = get(f"{BASE}/club-stats/{team_abbrev}/{season}/{game_type}")
            goalies = data.get("goalies", [])
            if not goalies:
                continue
            total_ga = sum(g.get("goalsAgainst", 0) for g in goalies)
            starts = sum(g.get("gamesStarted", 0) for g in goalies)
            saves = sum(g.get("saves", 0) for g in goalies)
            shots_against = saves + total_ga
            if starts > 0:
                return {
                    "ga_per_game": round(total_ga / starts, 4),
                    "save_pct": round(saves / shots_against, 4) if shots_against else None,
                }
        except Exception:
            continue
    return {"ga_per_game": None, "save_pct": None}


def get_team_defense_from_schedule(team_abbrev, season, before_date):
    games = []
    try:
        games = get(f"{BASE}/club-schedule-season/{team_abbrev}/{season}").get("games", [])
    except Exception:
        return {"ga_per_game": None, "save_pct": None}

    goals_against = 0
    games_played = 0
    for game in games:
        if game.get("gameDate") >= before_date:
            continue
        if game.get("gameType") not in (2, 3):
            continue
        if game.get("gameState") not in ("OFF", "FINAL"):
            continue
        away = game.get("awayTeam", {})
        home = game.get("homeTeam", {})
        away_abbrev = away.get("abbrev")
        home_abbrev = home.get("abbrev")
        if team_abbrev == away_abbrev and away.get("score") is not None and home.get("score") is not None:
            goals_against += int(home.get("score", 0))
            games_played += 1
        elif team_abbrev == home_abbrev and away.get("score") is not None and home.get("score") is not None:
            goals_against += int(away.get("score", 0))
            games_played += 1

    return {
        "ga_per_game": round(goals_against / games_played, 4) if games_played else None,
        "save_pct": None,
    }


def normalize(values):
    cleaned = [v if v is not None else 0.0 for v in values]
    lo, hi = min(cleaned), max(cleaned)
    if hi == lo:
        return [0.5] * len(cleaned)
    return [(v - lo) / (hi - lo) for v in cleaned]


def season_start_date(season):
    start_year = int(str(season)[:4])
    return datetime(start_year, 9, 1).date()


def season_end_date(season):
    end_year = int(str(season)[4:])
    return datetime(end_year, 7, 15).date()
