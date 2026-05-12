"""
NHL Roster + Scoring Stats
---------------------------
For every game on a given date, outputs per-player:
  - goals_total       : total goals scored this season
  - games_played      : games played this season
  - goals_per_game    : goals_total / games_played
  - home_or_away      : "HOME" or "AWAY"
  - opp_ga_per_game   : opponent team's avg goals allowed per game this season

Usage:
    pip install requests
    python nhl_stats.py                   # today
    python nhl_stats.py 2026-05-11        # specific date
    python nhl_stats.py 2026-05-11 --json
"""

import sys
import json
import time
import requests
from datetime import date

BASE   = "https://api-web.nhle.com/v1"
SEASON = "20252026"

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


# ─────────────────────────────────────────────────────────────────────────────
# HTTP helper
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
# Name resolver — handles both roster and boxscore name formats
# ─────────────────────────────────────────────────────────────────────────────

def resolve_name(p):
    """
    The NHL API uses inconsistent name structures:
      - Boxscore:  p["name"]["default"] = "Nathan MacKinnon"
      - Roster:    p["firstName"]["default"] + p["lastName"]["default"]
    This handles both.
    """
    name_obj = p.get("name", {})
    if isinstance(name_obj, dict) and name_obj.get("default"):
        return name_obj["default"]

    first = p.get("firstName", {})
    last  = p.get("lastName",  {})
    first = first.get("default", "") if isinstance(first, dict) else str(first)
    last  = last.get("default",  "") if isinstance(last,  dict) else str(last)
    return f"{first} {last}".strip()


# ─────────────────────────────────────────────────────────────────────────────
# Schedule
# ─────────────────────────────────────────────────────────────────────────────

def get_games_on_date(game_date):
    """Return list of game dicts for exactly game_date (YYYY-MM-DD)."""
    data = get(f"{BASE}/schedule/{game_date}")
    games = []
    for day in data.get("gameWeek", []):
        if day.get("date") == game_date:
            games.extend(day.get("games", []))
    return games


# ─────────────────────────────────────────────────────────────────────────────
# Rosters
# ─────────────────────────────────────────────────────────────────────────────

def get_roster_from_boxscore(game_id):
    """
    For a started/finished game, extract dressed players from the boxscore.
    playerByGameStats keys: awayTeam / homeTeam → forwards / defense / goalies
    Each player has: playerId, name{default}, sweaterNumber, position
    Returns {"away": [...], "home": [...]}, or None if no player data.
    """
    data         = get(f"{BASE}/gamecenter/{game_id}/boxscore")
    player_stats = data.get("playerByGameStats", {})

    if not player_stats:
        return None

    result = {}
    for side_key, label in [("awayTeam", "away"), ("homeTeam", "home")]:
        team_info = data.get(side_key, {})
        name_obj  = team_info.get("name", {})
        players   = []

        side_stats = player_stats.get(side_key, {})
        for group in ("forwards", "defense", "goalies"):
            for p in side_stats.get(group, []):
                players.append({
                    "player_id": p.get("playerId"),
                    "name":      resolve_name(p),
                    "jersey":    p.get("sweaterNumber", "?"),
                    "position":  p.get("position", "?"),
                })

        result[label] = {
            "team_name":   name_obj.get("default", "Unknown") if isinstance(name_obj, dict) else str(name_obj),
            "team_abbrev": team_info.get("abbrev", "???"),
            "players":     players,
        }

    return result


def get_roster_from_season(team_abbrev):
    """
    Fallback for games not yet started.
    /v1/roster/{abbrev}/current → forwards / defensemen / goalies
    Each player has: id (NOT playerId), firstName{default}, lastName{default},
                     sweaterNumber, positionCode
    """
    data    = get(f"{BASE}/roster/{team_abbrev}/current")
    players = []

    for group, pos_label in [("forwards", "F"), ("defensemen", "D"), ("goalies", "G")]:
        for p in data.get(group, []):
            players.append({
                "player_id": p.get("id"),          # <-- key is "id" here, not "playerId"
                "name":      resolve_name(p),
                "jersey":    p.get("sweaterNumber", "?"),
                "position":  p.get("positionCode", pos_label),
            })

    return players


# ─────────────────────────────────────────────────────────────────────────────
# Player season stats  (single API call per player)
# ─────────────────────────────────────────────────────────────────────────────

def get_player_stats(player_id):
    """
    Fetch /v1/player/{id}/game-log/{season}/2 once and derive all signals:
      - goals_total       total goals this season
      - games_played      games played this season
      - goals_per_game    goals_total / games_played
      - goals_last5       goals scored in the last 5 games  (recent form)
      - shots_per_game    average shots on goal per game this season

    The game log is ordered most-recent-first, so [:5] gives the last 5 games.
    Returns a dict; all values None on failure or empty log.
    """
    empty = {
        "goals_total":    None,
        "games_played":   None,
        "goals_per_game": None,
        "goals_last5":    None,
        "shots_per_game": None,
    }

    if not player_id:
        return empty

    try:
        data     = get(f"{BASE}/player/{player_id}/game-log/{SEASON}/2")
        game_log = data.get("gameLog", [])
    except Exception:
        return empty

    if not game_log:
        return {**empty, "goals_total": 0, "games_played": 0,
                "goals_per_game": 0.0, "goals_last5": 0, "shots_per_game": 0.0}

    played      = len(game_log)
    total_goals = sum(g.get("goals", 0)  for g in game_log)
    total_shots = sum(g.get("shots", 0)  for g in game_log)
    last5_goals = sum(g.get("goals", 0)  for g in game_log[:5])

    return {
        "goals_total":    total_goals,
        "games_played":   played,
        "goals_per_game": round(total_goals / played, 3),
        "goals_last5":    last5_goals,
        "shots_per_game": round(total_shots / played, 3),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Team goals-against per game
# ─────────────────────────────────────────────────────────────────────────────

def get_team_ga_per_game(team_abbrev):
    """
    /v1/club-stats/{abbrev}/{season}/2 returns {"skaters": [...], "goalies": [...]}
    We sum goalsAgainst and gamesStarted across all goalies to get the team total,
    then divide to get goals-against per game.
    Returns float or None.
    """
    try:
        data = get(f"{BASE}/club-stats/{team_abbrev}/{SEASON}/2")
    except Exception as exc:
        print(f"    Warning: team stats unavailable for {team_abbrev}: {exc}")
        return None

    goalies = data.get("goalies", [])
    if not goalies:
        print(f"    Warning: no goalie data found for {team_abbrev}. Keys: {list(data.keys())}")
        return None

    total_ga = 0
    total_gp = 0
    for g in goalies:
        total_ga += g.get("goalsAgainst", 0)
        # gamesStarted is the cleanest proxy for team games played
        # fall back to gamesPlayed if absent
        total_gp += g.get("gamesStarted", g.get("gamesPlayed", 0))

    if total_gp == 0:
        print(f"    Warning: goalie games played is 0 for {team_abbrev}")
        return None

    # Each game has exactly one starter, so summing gamesStarted across all
    # goalies gives the total team games played.
    team_games = sum(g.get("gamesStarted", 0) for g in goalies)
    return round(total_ga / team_games, 3) if team_games > 0 else None



# ─────────────────────────────────────────────────────────────────────────────
# Ranking
# ─────────────────────────────────────────────────────────────────────────────

# Weights — must sum to 1.0
# goals_per_game  : strongest long-term signal of scoring ability
# goals_last5     : recent form — hot streaks are real in hockey
# shots_per_game  : shots are the best predictor of future goals (Corsi theory)
# opp_ga_per_game : weak defence = easier to score against
# home_bonus      : home teams score ~5-8% more goals historically
W_GPG   = 0.35
W_LAST5 = 0.25
W_SHOTS = 0.20
W_OPP   = 0.15
W_HOME  = 0.05


def normalize(values):
    """
    Min-max normalize a list of floats to [0, 1].
    Returns 0.5 for all values if the range is zero (everyone the same).
    Missing (None) values are treated as 0 before normalizing.
    """
    cleaned = [v if v is not None else 0.0 for v in values]
    lo, hi  = min(cleaned), max(cleaned)
    if hi == lo:
        return [0.5] * len(cleaned)
    return [(v - lo) / (hi - lo) for v in cleaned]


def rank_players(all_skaters):
    """
    Given a flat list of skater dicts (no goalies), normalize each signal
    across the entire pool (all games, both teams) and compute a composite
    score for each player.

    Normalizing across the full pool rather than per-team means a player
    is ranked relative to everyone playing that night, which is exactly
    what you want for the Tim Hortons challenge.

    Adds 'score' and 'rank' keys to each player dict in-place.
    Returns the list sorted by score descending.
    """
    if not all_skaters:
        return all_skaters

    # Extract raw signal vectors
    gpg_vals   = [p.get("goals_per_game")  or 0.0 for p in all_skaters]
    last5_vals = [p.get("goals_last5")     or 0.0 for p in all_skaters]
    shots_vals = [p.get("shots_per_game")  or 0.0 for p in all_skaters]
    opp_vals   = [p.get("opp_ga_per_game") or 0.0 for p in all_skaters]
    home_vals  = [1.0 if p.get("home_or_away") == "HOME" else 0.0 for p in all_skaters]

    # Normalize each signal to [0, 1]
    gpg_n   = normalize(gpg_vals)
    last5_n = normalize(last5_vals)
    shots_n = normalize(shots_vals)
    opp_n   = normalize(opp_vals)
    home_n  = normalize(home_vals)   # already 0/1, normalize handles the scale

    # Position multiplier — scales the final score down for defencemen
    # so forwards are preferred even when a D-man's other signals are strong.
    # Reflects the real league-wide ratio of D vs F goals per game (~0.60).
    POSITION_MULTIPLIER = {"D": 0.60}

    # Compute weighted composite score
    for i, p in enumerate(all_skaters):
        pos        = str(p.get("position", ""))[:1].upper()
        pos_mult   = POSITION_MULTIPLIER.get(pos, 1.00)
        p["score"] = round(
            pos_mult * (
                W_GPG   * gpg_n[i]   +
                W_LAST5 * last5_n[i] +
                W_SHOTS * shots_n[i] +
                W_OPP   * opp_n[i]   +
                W_HOME  * home_n[i]
            ),
            4
        )

    all_skaters.sort(key=lambda p: p["score"], reverse=True)

    for rank, p in enumerate(all_skaters, start=1):
        p["rank"] = rank

    return all_skaters

# ─────────────────────────────────────────────────────────────────────────────
# Display
# ─────────────────────────────────────────────────────────────────────────────

def player_sort_key(p):
    pos   = str(p.get("position", ""))[:1].upper()
    order = {"G": 2, "D": 1}.get(pos, 0)
    j     = p.get("jersey", 99)
    return (order, int(j) if str(j).isdigit() else 99)


def print_team(label, team_name, team_abbrev, players, opp_abbrev, opp_ga_pg):
    ga_str = f"{opp_ga_pg:.3f}" if opp_ga_pg is not None else "N/A"
    print(f"\n  [{label}] {team_name} ({team_abbrev})")
    print(f"  Opponent: {opp_abbrev}  |  Opp avg GA/game: {ga_str}")
    print(f"  {'#':<5} {'Name':<26} {'Pos':<5} {'H/A':<5} "
          f"{'G':>4} {'GP':>4} {'G/GP':>6} {'L5G':>4} {'SOG/G':>6}")
    print("  " + "-" * 72)

    for p in sorted(players, key=player_sort_key):
        pos = str(p.get("position", ""))[:1].upper()
        if pos == "G":
            g_s = gp_s = gpg_s = l5_s = sog_s = "—"
        else:
            g_s   = str(p["goals_total"])         if p.get("goals_total")    is not None else "—"
            gp_s  = str(p["games_played"])         if p.get("games_played")   is not None else "—"
            gpg_s = f"{p['goals_per_game']:.3f}"  if p.get("goals_per_game") is not None else "—"
            l5_s  = str(p["goals_last5"])          if p.get("goals_last5")    is not None else "—"
            sog_s = f"{p['shots_per_game']:.2f}"  if p.get("shots_per_game") is not None else "—"

        print(
            f"  {str(p['jersey']):<5} {p['name']:<26} {p['position']:<5} "
            f"{p['home_or_away']:<5} {g_s:>4} {gp_s:>4} {gpg_s:>6} {l5_s:>4} {sog_s:>6}"
        )

    print(f"\n  {len(players)} players dressed")


def print_rankings(skaters):
    """Print the full cross-game ranked leaderboard."""
    print("\n" + "=" * 72)
    print("  OVERALL RANKING — all skaters playing tonight")
    print(f"  Weights: G/GP={W_GPG} | Last5={W_LAST5} | SOG/G={W_SHOTS} | "
          f"OppGA={W_OPP} | Home={W_HOME}")
    print("=" * 72)
    print(f"  {'RK':<4} {'Name':<26} {'Team':<5} {'Pos':<5} {'H/A':<5} "
          f"{'G/GP':>6} {'L5G':>4} {'SOG/G':>6} {'OppGA':>6} {'SCORE':>6}")
    print("  " + "-" * 80)

    for p in skaters:
        gpg_s  = f"{p['goals_per_game']:.3f}"  if p.get("goals_per_game") is not None else "—"
        l5_s   = str(p["goals_last5"])          if p.get("goals_last5")    is not None else "—"
        sog_s  = f"{p['shots_per_game']:.2f}"  if p.get("shots_per_game") is not None else "—"
        opp_s  = f"{p['opp_ga_per_game']:.3f}" if p.get("opp_ga_per_game")is not None else "—"
        score_s= f"{p['score']:.4f}"

        print(
            f"  {p['rank']:<4} {p['name']:<26} {p['team_abbrev']:<5} {p['position']:<5} "
            f"{p['home_or_away']:<5} {gpg_s:>6} {l5_s:>4} {sog_s:>6} {opp_s:>6} {score_s:>6}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    game_date = sys.argv[1] if len(sys.argv) > 1 else str(date.today())
    save_json = "--json" in sys.argv

    print(f"\nFetching NHL schedule for {game_date} ...")
    games = get_games_on_date(game_date)

    if not games:
        print("No games found for this date.")
        sys.exit(0)

    print(f"Found {len(games)} game(s). Fetching rosters and stats...\n")
    print("=" * 72)

    all_output  = {}
    all_skaters = []   # collect every skater across all games for cross-game ranking

    for game in games:
        game_id     = game["id"]
        game_state  = game.get("gameState", "UNKNOWN")
        start_utc   = game.get("startTimeUTC", "TBD")
        away_info   = game.get("awayTeam", {})
        home_info   = game.get("homeTeam", {})
        away_abbrev = away_info.get("abbrev", "???")
        home_abbrev = home_info.get("abbrev", "???")
        away_place  = away_info.get("placeName", {}).get("default", "Away")
        home_place  = home_info.get("placeName", {}).get("default", "Home")

        print(f"\nGAME {game_id}  —  {away_place} ({away_abbrev}) @ {home_place} ({home_abbrev})")
        print(f"  Start (UTC): {start_utc}  |  State: {game_state}")

        # ── Team GA/game ──────────────────────────────────────────────────────
        print("  Fetching team stats...")
        away_ga_pg = get_team_ga_per_game(away_abbrev)
        home_ga_pg = get_team_ga_per_game(home_abbrev)

        print("-" * 72)

        try:
            # ── Rosters ───────────────────────────────────────────────────────
            roster_data = get_roster_from_boxscore(game_id)

            if roster_data:
                away_team_name = roster_data["away"]["team_name"]
                home_team_name = roster_data["home"]["team_name"]
                away_players   = roster_data["away"]["players"]
                home_players   = roster_data["home"]["players"]
            else:
                # Game not started — use season rosters
                print("  Game not yet started — using season roster fallback.")
                away_team_name = away_place
                home_team_name = home_place
                away_players   = get_roster_from_season(away_abbrev)
                home_players   = get_roster_from_season(home_abbrev)

            # ── Enrich with player stats ──────────────────────────────────────
            print("  Fetching player stats (this may take a moment)...")

            def enrich(players, team_abbrev, home_or_away, opp_ga_pg):
                enriched = []
                for p in players:
                    pos       = str(p.get("position", ""))[:1].upper()
                    is_goalie = pos == "G"

                    if is_goalie:
                        stats = {
                            "goals_total":    None,
                            "games_played":   None,
                            "goals_per_game": None,
                            "goals_last5":    None,
                            "shots_per_game": None,
                        }
                    else:
                        stats = get_player_stats(p["player_id"])

                    enriched.append({
                        "player_id":      p["player_id"],
                        "name":           p["name"],
                        "jersey":         p["jersey"],
                        "position":       p["position"],
                        "team_abbrev":    team_abbrev,
                        "home_or_away":   home_or_away,
                        "opp_ga_per_game": opp_ga_pg,
                        **stats,
                    })
                return enriched

            # Away skaters face home defence → use home_ga_pg, and vice-versa
            away_enriched = enrich(away_players, away_abbrev, "AWAY", home_ga_pg)
            home_enriched = enrich(home_players, home_abbrev, "HOME", away_ga_pg)

            # ── Collect skaters for cross-game ranking ────────────────────────
            for p in away_enriched + home_enriched:
                if str(p.get("position", ""))[:1].upper() != "G":
                    all_skaters.append(p)

            # ── Print per-game rosters ────────────────────────────────────────
            print_team("AWAY", away_team_name, away_abbrev, away_enriched, home_abbrev, home_ga_pg)
            print_team("HOME", home_team_name, home_abbrev, home_enriched, away_abbrev, away_ga_pg)

            # ── Store ─────────────────────────────────────────────────────────
            all_output[str(game_id)] = {
                "game_state":  game_state,
                "away_abbrev": away_abbrev,
                "home_abbrev": home_abbrev,
                "away": {
                    "team_name":   away_team_name,
                    "team_abbrev": away_abbrev,
                    "ga_per_game": home_ga_pg,   # what away skaters face
                    "players":     away_enriched,
                },
                "home": {
                    "team_name":   home_team_name,
                    "team_abbrev": home_abbrev,
                    "ga_per_game": away_ga_pg,   # what home skaters face
                    "players":     home_enriched,
                },
            }

        except Exception as exc:
            print(f"  Error processing game {game_id}: {exc}")
            raise

        print()

    # ── Rank all skaters across every game tonight ────────────────────────────
    ranked = rank_players(all_skaters)
    print_rankings(ranked)

    print("=" * 72)
    print(f"\nDone. Processed {len(all_output)} game(s), ranked {len(ranked)} skaters.")

    # Always write data/rankings.json so the Next.js site can read it.
    import os
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
    os.makedirs(data_dir, exist_ok=True)
    rankings_path = os.path.join(data_dir, "rankings.json")

    payload = {
        "date":    game_date,
        "games":   all_output,
        "ranking": ranked,
    }

    with open(rankings_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    print(f"Rankings written to {rankings_path}")

    if save_json:
        out_file = f"stats_{game_date}.json"
        with open(out_file, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        print(f"Also saved to {out_file}")

    return payload


if __name__ == "__main__":
    main()
