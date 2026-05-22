"""
Import Season Training Data
---------------------------
Usage:
    python backend/import_season_training_data.py 20252026
"""

import csv
import os
import re
import sys

from nhl_features import BASE, get
from results_logger import CSV_FIELDS, CSV_PATH, DATA_DIR, load_existing_keys, log_date, migrate_csv_header

TEAM_ABBREVS = [
    "ANA", "BOS", "BUF", "CAR", "CBJ", "CGY", "CHI", "COL",
    "DAL", "DET", "EDM", "FLA", "LAK", "MIN", "MTL", "NJD",
    "NSH", "NYI", "NYR", "OTT", "PHI", "PIT", "SEA", "SJS",
    "STL", "TBL", "TOR", "UTA", "VAN", "VGK", "WPG", "WSH",
]


def validate_season(value):
    if not re.fullmatch(r"\d{8}", value or ""):
        raise ValueError('Season must look like "20252026".')
    if int(value[:4]) + 1 != int(value[4:]):
        raise ValueError("Season end year must be one year after the start year.")
    return value


def discover_game_dates(season):
    dates = set()
    for team in TEAM_ABBREVS:
        try:
            schedule = get(f"{BASE}/club-schedule-season/{team}/{season}").get("games", [])
        except Exception as exc:
            print(f"Could not read schedule for {team}: {exc}")
            continue
        for game in schedule:
            if str(game.get("season")) != str(season):
                continue
            if game.get("gameType") not in (2, 3):
                continue
            if game.get("gameState") not in ("OFF", "FINAL"):
                continue
            if game.get("gameDate"):
                dates.add(game["gameDate"])
    return sorted(dates)


def main():
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python backend/import_season_training_data.py "20252026"')
    season = validate_season(sys.argv[1])

    os.makedirs(DATA_DIR, exist_ok=True)
    migrate_csv_header()
    existing_keys = load_existing_keys()
    dates = discover_game_dates(season)

    if not dates:
        print(f"No completed regular-season/playoff games found for {season}.")
        return

    print(f"Importing {len(dates)} game dates for season {season}.")
    file_exists = os.path.exists(CSV_PATH)
    total_rows = 0
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        for game_date in dates:
            print(f"\n{game_date}")
            total_rows += log_date(game_date, writer, season=season, existing_keys=existing_keys)

    print(f"\nImported {total_rows} new player-game rows for {season}.")


if __name__ == "__main__":
    main()
