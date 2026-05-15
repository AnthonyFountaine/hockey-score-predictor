"""
NHL Roster + Scoring Stats
---------------------------
Improvements over previous version:
  - Playoff game log (game type 3) used for L5G when playoffs are active
  - Bayesian-shrunk G/GP to prevent small-sample outliers
  - Loads model weights from data/model_weights.json if present,
    otherwise falls back to hardcoded defaults

Usage:
    pip install requests
    python nhl_stats.py                   # today
    python nhl_stats.py 2026-05-14        # specific date
    python nhl_stats.py 2026-05-14 --json
"""

import os
import sys
import json
import time
import math
import requests
from datetime import date

BASE    = "https://api-web.nhle.com/v1"
SEASON  = "20252026"

# League-average goals per game for a skater — used as the Bayesian prior.
# ~0.15 is a reasonable NHL-wide figure (roughly 6 goals / 40 skaters per game).
LEAGUE_AVG_GPG    = 0.15

# Shrinkage factor: how many "ghost games" of league-average performance
# to assume before trusting a player's real data.
# At k=20: a player with 20 GP is weighted 50% real / 50% prior.
# At k=20: a player with 1 GP is weighted ~5% real / ~95% prior.
SHRINK_K          = 20

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
# Model weights — loaded from file if available, else hardcoded defaults
# ─────────────────────────────────────────────────────────────────────────────

def load_weights():
    """
    Try to load trained weights from data/model_weights.json.
    Falls back to sensible hardcoded defaults if the file doesn't exist yet
    (i.e. before the first training run).
    """
    data_dir     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
    weights_path = os.path.join(data_dir, "model_weights.json")

    defaults = {
        "w_gpg":          0.35,
        "w_last5":        0.25,
        "w_shots":        0.20,
        "w_opp":          0.15,
        "w_home":         0.05,
        "d_multiplier":   0.60,
        "model_trained":  False,
        "training_games": 0,
    }

    if not os.path.exists(weights_path):
        return defaults

    try:
        with open(weights_path, encoding="utf-8") as f:
            saved = json.load(f)
        # Merge so any missing keys fall back to defaults
        return {**defaults, **saved}
    except Exception:
        return defaults


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
# Name resolver
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


# ─────────────────────────────────────────────────────────────────────────────
# Schedule
# ─────────────────────────────────────────────────────────────────────────────

def get_games_on_date(game_date):
    data  = get(f"{BASE}/schedule/{game_date}")
    games = []
    for day in data.get("gameWeek", []):
        if day.get("date") == game_date:
            games.extend(day.get("games", []))
    return games


# ─────────────────────────────────────────────────────────────────────────────
# Rosters
# ─────────────────────────────────────────────────────────────────────────────

def get_roster_from_boxscore(game_id):
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
    data    = get(f"{BASE}/roster/{team_abbrev}/current")
    players = []
    for group, pos_label in [("forwards", "F"), ("defensemen", "D"), ("goalies", "G")]:
        for p in data.get(group, []):
            players.append({
                "player_id": p.get("id"),
                "name":      resolve_name(p),
                "jersey":    p.get("sweaterNumber", "?"),
                "position":  p.get("positionCode", pos_label),
            })
    return players


# ─────────────────────────────────────────────────────────────────────────────
# Player stats  (regular season baseline + playoff recency)
# ─────────────────────────────────────────────────────────────────────────────

def bayesian_gpg(goals, games_played):
    """
    Bayesian shrinkage estimator for goals-per-game.
    Blends the player's actual rate toward the league average,
    weighted by sample size.

    Formula: (goals + LEAGUE_AVG_GPG * SHRINK_K) / (games_played + SHRINK_K)

    Effect:
      - 1 GP,  1 goal  → (1 + 0.15*20)/(1+20)  = 4/21  ≈ 0.19  (pulled way down)
      - 20 GP, 8 goals → (8 + 0.15*20)/(20+20) = 11/40 ≈ 0.275 (moderate trust)
      - 70 GP, 35 goals→ (35+0.15*20)/(70+20)  = 38/90 ≈ 0.422 (mostly trusted)
    """
    if games_played is None or games_played == 0:
        return LEAGUE_AVG_GPG
    return (goals + LEAGUE_AVG_GPG * SHRINK_K) / (games_played + SHRINK_K)


def get_player_stats(player_id):
    """
    Fetch both regular season (game type 2) and playoff (game type 3) game logs.

    Regular season log  → goals_total, games_played, shots_per_game,
                          and bayesian-adjusted goals_per_game
    Playoff log         → goals_last5 (last 5 playoff games if playoffs active,
                          else last 5 regular season games)

    Returns a unified dict with all signals.
    """
    empty = {
        "goals_total":     None,
        "games_played":    None,
        "goals_per_game":  None,
        "goals_last5":     None,
        "shots_per_game":  None,
        "in_playoffs":     False,
    }

    if not player_id:
        return empty

    # ── Regular season log ────────────────────────────────────────────────────
    try:
        rs_data = get(f"{BASE}/player/{player_id}/game-log/{SEASON}/2")
        rs_log  = rs_data.get("gameLog", [])
    except Exception:
        rs_log  = []

    # ── Playoff log ───────────────────────────────────────────────────────────
    try:
        po_data = get(f"{BASE}/player/{player_id}/game-log/{SEASON}/3")
        po_log  = po_data.get("gameLog", [])
    except Exception:
        po_log  = []

    in_playoffs = len(po_log) > 0

    # Baseline stats always come from the full regular season
    if rs_log:
        rs_goals  = sum(g.get("goals", 0) for g in rs_log)
        rs_shots  = sum(g.get("shots", 0) for g in rs_log)
        rs_played = len(rs_log)
    else:
        rs_goals  = 0
        rs_shots  = 0
        rs_played = 0

    gpg_adjusted = bayesian_gpg(rs_goals, rs_played)
    shots_pg     = round(rs_shots / rs_played, 3) if rs_played > 0 else 0.0

    # L5G: use playoff games if active, otherwise fall back to regular season
    if in_playoffs:
        last5_log = po_log[:5]   # API returns newest-first
    else:
        last5_log = rs_log[:5]

    last5_goals = sum(g.get("goals", 0) for g in last5_log)

    return {
        "goals_total":    rs_goals,
        "games_played":   rs_played,
        "goals_per_game": round(gpg_adjusted, 3),
        "goals_last5":    last5_goals,
        "shots_per_game": shots_pg,
        "in_playoffs":    in_playoffs,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Team goals-against per game
# ─────────────────────────────────────────────────────────────────────────────

def get_team_ga_per_game(team_abbrev):
    """
    Sum goalsAgainst across all goalies; divide by sum of gamesStarted.
    Tries playoff stats first (game type 3), falls back to regular season.
    """
    for game_type in (3, 2):
        try:
            data    = get(f"{BASE}/club-stats/{team_abbrev}/{SEASON}/{game_type}")
            goalies = data.get("goalies", [])
            if not goalies:
                continue
            total_ga = sum(g.get("goalsAgainst", 0)  for g in goalies)
            team_gp  = sum(g.get("gamesStarted", 0)  for g in goalies)
            if team_gp > 0:
                return round(total_ga / team_gp, 3)
        except Exception:
            continue

    print(f"    Warning: could not get GA stats for {team_abbrev}")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Ranking
# ─────────────────────────────────────────────────────────────────────────────

def normalize(values):
    cleaned = [v if v is not None else 0.0 for v in values]
    lo, hi  = min(cleaned), max(cleaned)
    if hi == lo:
        return [0.5] * len(cleaned)
    return [(v - lo) / (hi - lo) for v in cleaned]


def rank_players(all_skaters, weights):
    """
    Normalize each signal across the full pool of skaters playing tonight,
    then compute a weighted composite score using the provided weights dict.
    Defencemen are penalised by the d_multiplier.
    """
    if not all_skaters:
        return all_skaters

    w_gpg   = weights["w_gpg"]
    w_last5 = weights["w_last5"]
    w_shots = weights["w_shots"]
    w_opp   = weights["w_opp"]
    w_home  = weights["w_home"]
    d_mult  = weights["d_multiplier"]

    gpg_n   = normalize([p.get("goals_per_game")  or 0.0 for p in all_skaters])
    last5_n = normalize([p.get("goals_last5")     or 0.0 for p in all_skaters])
    shots_n = normalize([p.get("shots_per_game")  or 0.0 for p in all_skaters])
    opp_n   = normalize([p.get("opp_ga_per_game") or 0.0 for p in all_skaters])
    home_n  = normalize([1.0 if p.get("home_or_away") == "HOME" else 0.0 for p in all_skaters])

    for i, p in enumerate(all_skaters):
        pos      = str(p.get("position", ""))[:1].upper()
        pos_mult = d_mult if pos == "D" else 1.0
        p["score"] = round(
            pos_mult * (
                w_gpg   * gpg_n[i]   +
                w_last5 * last5_n[i] +
                w_shots * shots_n[i] +
                w_opp   * opp_n[i]   +
                w_home  * home_n[i]
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
          f"{'G':>4} {'GP':>4} {'G/GP(adj)':>10} {'L5G':>4} {'SOG/G':>6} {'PO':>3}")
    print("  " + "-" * 76)

    for p in sorted(players, key=player_sort_key):
        pos = str(p.get("position", ""))[:1].upper()
        if pos == "G":
            g_s = gp_s = gpg_s = l5_s = sog_s = po_s = "—"
        else:
            g_s   = str(p["goals_total"])         if p.get("goals_total")    is not None else "—"
            gp_s  = str(p["games_played"])         if p.get("games_played")   is not None else "—"
            gpg_s = f"{p['goals_per_game']:.3f}"  if p.get("goals_per_game") is not None else "—"
            l5_s  = str(p["goals_last5"])          if p.get("goals_last5")    is not None else "—"
            sog_s = f"{p['shots_per_game']:.2f}"  if p.get("shots_per_game") is not None else "—"
            po_s  = "✓" if p.get("in_playoffs")   else ""

        print(
            f"  {str(p['jersey']):<5} {p['name']:<26} {p['position']:<5} "
            f"{p['home_or_away']:<5} {g_s:>4} {gp_s:>4} {gpg_s:>10} "
            f"{l5_s:>4} {sog_s:>6} {po_s:>3}"
        )

    print(f"\n  {len(players)} players dressed")


def print_rankings(skaters, weights):
    print("\n" + "=" * 72)
    print("  OVERALL RANKING — all skaters playing tonight")
    trained = weights.get("model_trained", False)
    n_games = weights.get("training_games", 0)
    if trained:
        print(f"  Weights: ML-trained on {n_games} player-game observations")
    else:
        print(f"  Weights: defaults (no training data yet)")
    print("=" * 72)
    print(f"  {'RK':<4} {'Name':<26} {'Team':<5} {'Pos':<5} {'H/A':<5} "
          f"{'G/GP(adj)':>10} {'L5G':>4} {'SOG/G':>6} {'OppGA':>6} {'PO':>3} {'SCORE':>6}")
    print("  " + "-" * 88)

    for p in skaters:
        gpg_s  = f"{p['goals_per_game']:.3f}"  if p.get("goals_per_game") is not None else "—"
        l5_s   = str(p["goals_last5"])          if p.get("goals_last5")    is not None else "—"
        sog_s  = f"{p['shots_per_game']:.2f}"  if p.get("shots_per_game") is not None else "—"
        opp_s  = f"{p['opp_ga_per_game']:.3f}" if p.get("opp_ga_per_game")is not None else "—"
        po_s   = "✓" if p.get("in_playoffs")   else ""
        score_s= f"{p['score']:.4f}"

        print(
            f"  {p['rank']:<4} {p['name']:<26} {p['team_abbrev']:<5} {p['position']:<5} "
            f"{p['home_or_away']:<5} {gpg_s:>10} {l5_s:>4} {sog_s:>6} "
            f"{opp_s:>6} {po_s:>3} {score_s:>6}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    game_date = sys.argv[1] if len(sys.argv) > 1 else str(date.today())
    save_json = "--json" in sys.argv

    weights = load_weights()
    print(f"\nWeights source: {'ML model' if weights['model_trained'] else 'defaults'}")

    print(f"\nFetching NHL schedule for {game_date} ...")
    games = get_games_on_date(game_date)

    if not games:
        print("No games found for this date.")
        sys.exit(0)

    print(f"Found {len(games)} game(s). Fetching rosters and stats...\n")
    print("=" * 72)

    all_output  = {}
    all_skaters = []

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

        print("  Fetching team stats...")
        away_ga_pg = get_team_ga_per_game(away_abbrev)
        home_ga_pg = get_team_ga_per_game(home_abbrev)

        print("-" * 72)

        try:
            roster_data = get_roster_from_boxscore(game_id)

            if roster_data:
                away_team_name = roster_data["away"]["team_name"]
                home_team_name = roster_data["home"]["team_name"]
                away_players   = roster_data["away"]["players"]
                home_players   = roster_data["home"]["players"]
            else:
                print("  Game not yet started — using season roster fallback.")
                away_team_name = away_place
                home_team_name = home_place
                away_players   = get_roster_from_season(away_abbrev)
                home_players   = get_roster_from_season(home_abbrev)

            print("  Fetching player stats (this may take a moment)...")

            def enrich(players, team_abbrev, home_or_away, opp_ga_pg):
                enriched = []
                for p in players:
                    pos       = str(p.get("position", ""))[:1].upper()
                    is_goalie = pos == "G"
                    stats = (
                        {"goals_total": None, "games_played": None,
                         "goals_per_game": None, "goals_last5": None,
                         "shots_per_game": None, "in_playoffs": False}
                        if is_goalie else get_player_stats(p["player_id"])
                    )
                    enriched.append({
                        "player_id":       p["player_id"],
                        "name":            p["name"],
                        "jersey":          p["jersey"],
                        "position":        p["position"],
                        "team_abbrev":     team_abbrev,
                        "home_or_away":    home_or_away,
                        "opp_ga_per_game": opp_ga_pg,
                        **stats,
                    })
                return enriched

            away_enriched = enrich(away_players, away_abbrev, "AWAY", home_ga_pg)
            home_enriched = enrich(home_players, home_abbrev, "HOME", away_ga_pg)

            for p in away_enriched + home_enriched:
                if str(p.get("position", ""))[:1].upper() != "G":
                    all_skaters.append(p)

            print_team("AWAY", away_team_name, away_abbrev, away_enriched, home_abbrev, home_ga_pg)
            print_team("HOME", home_team_name, home_abbrev, home_enriched, away_abbrev, away_ga_pg)

            all_output[str(game_id)] = {
                "game_state":  game_state,
                "away_abbrev": away_abbrev,
                "home_abbrev": home_abbrev,
                "away": {"team_name": away_team_name, "team_abbrev": away_abbrev,
                         "ga_per_game": home_ga_pg, "players": away_enriched},
                "home": {"team_name": home_team_name, "team_abbrev": home_abbrev,
                         "ga_per_game": away_ga_pg, "players": home_enriched},
            }

        except Exception as exc:
            print(f"  Error processing game {game_id}: {exc}")
            raise

        print()

    ranked = rank_players(all_skaters, weights)
    print_rankings(ranked, weights)

    print("=" * 72)
    print(f"\nDone. Processed {len(all_output)} game(s), ranked {len(ranked)} skaters.")

    data_dir      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
    os.makedirs(data_dir, exist_ok=True)
    rankings_path = os.path.join(data_dir, "rankings.json")

    payload = {
        "date":         game_date,
        "games":        all_output,
        "ranking":      ranked,
        "model_trained": weights["model_trained"],
        "training_games": weights["training_games"],
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
