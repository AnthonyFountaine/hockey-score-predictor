"""
NHL Roster + Goal Scorer Rankings
---------------------------------
Fetches today's NHL games, enriches every dressed skater with scoring signals,
and writes data/rankings.json for the frontend.
"""

import json
import os
import sys
from datetime import date

from nhl_features import (
    BASE,
    FEATURE_SPECS,
    SEASON,
    get,
    get_player_stats,
    get_team_defense_stats,
    normalize,
    resolve_name,
)


def data_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")


def load_weights():
    weights_path = os.path.join(data_dir(), "model_weights.json")
    defaults = {
        **{spec["weight"]: spec["default"] for spec in FEATURE_SPECS},
        "d_multiplier": 0.60,
        "model_trained": False,
        "training_games": 0,
    }
    if not os.path.exists(weights_path):
        return defaults
    try:
        with open(weights_path, encoding="utf-8") as f:
            saved = json.load(f)
        return {**defaults, **saved}
    except Exception:
        return defaults


def get_games_on_date(game_date):
    data = get(f"{BASE}/schedule/{game_date}")
    games = []
    for day in data.get("gameWeek", []):
        if day.get("date") == game_date:
            games.extend(day.get("games", []))
    return games


def get_roster_from_boxscore(game_id):
    data = get(f"{BASE}/gamecenter/{game_id}/boxscore")
    player_stats = data.get("playerByGameStats", {})
    if not player_stats:
        return None

    result = {}
    for side_key, label in [("awayTeam", "away"), ("homeTeam", "home")]:
        team_info = data.get(side_key, {})
        name_obj = team_info.get("name", {})
        side_stats = player_stats.get(side_key, {})
        players = []
        for group in ("forwards", "defense", "goalies"):
            for p in side_stats.get(group, []):
                players.append({
                    "player_id": p.get("playerId"),
                    "name": resolve_name(p),
                    "jersey": p.get("sweaterNumber", "?"),
                    "position": p.get("position", "?"),
                })
        result[label] = {
            "team_name": name_obj.get("default", "Unknown") if isinstance(name_obj, dict) else str(name_obj),
            "team_abbrev": team_info.get("abbrev", "???"),
            "players": players,
        }
    return result


def get_roster_from_season(team_abbrev):
    data = get(f"{BASE}/roster/{team_abbrev}/current")
    players = []
    for group, pos_label in [("forwards", "F"), ("defensemen", "D"), ("goalies", "G")]:
        for p in data.get(group, []):
            players.append({
                "player_id": p.get("id"),
                "name": resolve_name(p),
                "jersey": p.get("sweaterNumber", "?"),
                "position": p.get("positionCode", pos_label),
            })
    return players


def rank_players(all_skaters, weights):
    if not all_skaters:
        return all_skaters

    normalized = {}
    for spec in FEATURE_SPECS:
        values = []
        for player in all_skaters:
            if spec["csv"] == "home_binary":
                values.append(1.0 if player.get("home_or_away") == "HOME" else 0.0)
            else:
                values.append(player.get(spec["player"]) or 0.0)
        scaled = normalize(values)
        if spec["direction"] < 0:
            scaled = [1.0 - value for value in scaled]
        normalized[spec["weight"]] = scaled

    for idx, player in enumerate(all_skaters):
        pos = str(player.get("position", ""))[:1].upper()
        pos_mult = weights.get("d_multiplier", 0.60) if pos == "D" else 1.0
        score = 0.0
        influence = {}
        for spec in FEATURE_SPECS:
            weight = weights.get(spec["weight"], spec["default"])
            contribution = weight * normalized[spec["weight"]][idx]
            influence[spec["weight"]] = round(contribution, 5)
            score += contribution
        player["score"] = round(pos_mult * score, 4)
        player["model_contributions"] = influence

    all_skaters.sort(key=lambda p: p["score"], reverse=True)
    for rank, player in enumerate(all_skaters, start=1):
        player["rank"] = rank
    return all_skaters


def player_sort_key(p):
    pos = str(p.get("position", ""))[:1].upper()
    order = {"G": 2, "D": 1}.get(pos, 0)
    jersey = p.get("jersey", 99)
    return (order, int(jersey) if str(jersey).isdigit() else 99)


def print_team(label, team_name, team_abbrev, players, opp_abbrev, opp_defense):
    ga = opp_defense.get("ga_per_game")
    sv = opp_defense.get("save_pct")
    ga_str = f"{ga:.3f}" if ga is not None else "N/A"
    sv_str = f"{sv:.3f}" if sv is not None else "N/A"
    print(f"\n  [{label}] {team_name} ({team_abbrev})")
    print(f"  Opponent: {opp_abbrev} | Opp GA/game: {ga_str} | Opp SV%: {sv_str}")
    print(f"  {'#':<5} {'Name':<26} {'Pos':<5} {'H/A':<5} {'G':>4} {'GP':>4} "
          f"{'G/GP':>7} {'SOG/G':>7} {'SH%':>6} {'PPG/G':>7} {'TOI':>6}")
    print("  " + "-" * 92)

    for p in sorted(players, key=player_sort_key):
        pos = str(p.get("position", ""))[:1].upper()
        if pos == "G":
            vals = ["-"] * 7
        else:
            vals = [
                str(p.get("goals_total", "-")),
                str(p.get("games_played", "-")),
                f"{p.get('goals_per_game', 0):.3f}",
                f"{p.get('shots_per_game', 0):.2f}",
                f"{p.get('shooting_pct', 0):.3f}",
                f"{p.get('power_play_goals_per_game', 0):.3f}",
                f"{p.get('avg_toi_minutes', 0):.1f}",
            ]
        print(f"  {str(p['jersey']):<5} {p['name']:<26} {p['position']:<5} "
              f"{p['home_or_away']:<5} {vals[0]:>4} {vals[1]:>4} {vals[2]:>7} "
              f"{vals[3]:>7} {vals[4]:>6} {vals[5]:>7} {vals[6]:>6}")


def print_rankings(skaters, weights):
    print("\n" + "=" * 92)
    print("  OVERALL RANKING - all skaters playing tonight")
    if weights.get("model_trained", False):
        print(f"  Weights: ML-trained on {weights.get('training_games', 0)} player-game rows")
    else:
        print("  Weights: defaults")
    print("=" * 92)
    print(f"  {'RK':<4} {'Name':<26} {'Team':<5} {'Pos':<5} {'Score':>7} "
          f"{'G/GP':>7} {'SOG/G':>7} {'SH%':>6} {'PPG/G':>7} {'TOI':>6} {'OppGA':>7}")
    print("  " + "-" * 92)
    for p in skaters:
        print(f"  {p['rank']:<4} {p['name']:<26} {p['team_abbrev']:<5} {p['position']:<5} "
              f"{p['score']:>7.4f} {p.get('goals_per_game', 0):>7.3f} "
              f"{p.get('shots_per_game', 0):>7.2f} {p.get('shooting_pct', 0):>6.3f} "
              f"{p.get('power_play_goals_per_game', 0):>7.3f} "
              f"{p.get('avg_toi_minutes', 0):>6.1f} {p.get('opp_ga_per_game') or 0:>7.3f}")


def main():
    game_date = sys.argv[1] if len(sys.argv) > 1 else str(date.today())
    save_json = "--json" in sys.argv
    weights = load_weights()

    print(f"\nFetching NHL schedule for {game_date} (season {SEASON}) ...")
    games = get_games_on_date(game_date)
    if not games:
        print("No games found for this date.")
        payload = {"date": game_date, "games": {}, "ranking": [], "message": "No NHL games scheduled today."}
        write_rankings(payload)
        return payload

    all_output = {}
    all_skaters = []

    for game in games:
        game_id = game["id"]
        game_state = game.get("gameState", "UNKNOWN")
        away_info = game.get("awayTeam", {})
        home_info = game.get("homeTeam", {})
        away_abbrev = away_info.get("abbrev", "???")
        home_abbrev = home_info.get("abbrev", "???")
        away_place = away_info.get("placeName", {}).get("default", "Away")
        home_place = home_info.get("placeName", {}).get("default", "Home")
        print(f"\nGAME {game_id}: {away_place} ({away_abbrev}) @ {home_place} ({home_abbrev})")

        away_defense = get_team_defense_stats(away_abbrev)
        home_defense = get_team_defense_stats(home_abbrev)

        roster_data = get_roster_from_boxscore(game_id)
        if roster_data:
            away_team_name = roster_data["away"]["team_name"]
            home_team_name = roster_data["home"]["team_name"]
            away_players = roster_data["away"]["players"]
            home_players = roster_data["home"]["players"]
        else:
            print("  Game not yet started - using season roster fallback.")
            away_team_name = away_place
            home_team_name = home_place
            away_players = get_roster_from_season(away_abbrev)
            home_players = get_roster_from_season(home_abbrev)

        def enrich(players, team_abbrev, home_or_away, opp_defense):
            enriched = []
            for player in players:
                pos = str(player.get("position", ""))[:1].upper()
                if pos == "G":
                    stats = {}
                else:
                    stats = get_player_stats(player["player_id"])
                enriched.append({
                    "player_id": player["player_id"],
                    "name": player["name"],
                    "jersey": player["jersey"],
                    "position": player["position"],
                    "team_abbrev": team_abbrev,
                    "home_or_away": home_or_away,
                    "opp_ga_per_game": opp_defense.get("ga_per_game"),
                    "opp_save_pct": opp_defense.get("save_pct"),
                    **stats,
                })
            return enriched

        away_enriched = enrich(away_players, away_abbrev, "AWAY", home_defense)
        home_enriched = enrich(home_players, home_abbrev, "HOME", away_defense)

        for player in away_enriched + home_enriched:
            if str(player.get("position", ""))[:1].upper() != "G":
                all_skaters.append(player)

        print_team("AWAY", away_team_name, away_abbrev, away_enriched, home_abbrev, home_defense)
        print_team("HOME", home_team_name, home_abbrev, home_enriched, away_abbrev, away_defense)

        all_output[str(game_id)] = {
            "game_state": game_state,
            "away_abbrev": away_abbrev,
            "home_abbrev": home_abbrev,
            "away": {
                "team_name": away_team_name,
                "team_abbrev": away_abbrev,
                "opp_defense": home_defense,
                "players": away_enriched,
            },
            "home": {
                "team_name": home_team_name,
                "team_abbrev": home_abbrev,
                "opp_defense": away_defense,
                "players": home_enriched,
            },
        }

    ranked = rank_players(all_skaters, weights)
    print_rankings(ranked, weights)
    payload = {
        "date": game_date,
        "season": SEASON,
        "games": all_output,
        "ranking": ranked,
        "model_trained": weights.get("model_trained", False),
        "training_games": weights.get("training_games", 0),
        "feature_weights": {spec["csv"]: weights.get(spec["weight"], spec["default"]) for spec in FEATURE_SPECS},
    }
    write_rankings(payload)

    if save_json:
        out_file = f"stats_{game_date}.json"
        with open(out_file, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
    return payload


def write_rankings(payload):
    os.makedirs(data_dir(), exist_ok=True)
    rankings_path = os.path.join(data_dir(), "rankings.json")
    with open(rankings_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    print(f"\nRankings written to {rankings_path}")


if __name__ == "__main__":
    main()
