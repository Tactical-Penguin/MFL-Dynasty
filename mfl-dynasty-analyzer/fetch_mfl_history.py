from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from mfl_client import MFLAuthError, MFLClient


DATA_DIR = Path("data")


def parse_history_entry(entry: dict) -> dict:
    parsed = urlparse(entry["url"])
    path_parts = [part for part in parsed.path.split("/") if part]
    return {
        "year": int(entry["year"]),
        "host": f"{parsed.scheme}://{parsed.netloc}",
        "league_id": path_parts[-1],
    }


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch cached MFL playerScores history.")
    parser.add_argument("--start", type=int, default=None)
    parser.add_argument("--end", type=int, default=None)
    parser.add_argument("--login", action="store_true", help="Use MFL username/password cookie auth.")
    args = parser.parse_args()

    client = MFLClient()
    league = client.export("league", use_api_key=False)
    write_json(DATA_DIR / f"mfl_league_{client.config.year}.json", league)

    history = league.get("league", {}).get("history", {}).get("league", [])
    if isinstance(history, dict):
        history = [history]

    seasons = [parse_history_entry(entry) for entry in history]
    if args.start:
        seasons = [season for season in seasons if season["year"] >= args.start]
    if args.end:
        seasons = [season for season in seasons if season["year"] <= args.end]

    if args.login:
        client.login()

    for season in sorted(seasons, key=lambda item: item["year"]):
        output = DATA_DIR / f"mfl_player_scores_{season['year']}_ytd.json"
        try:
            data = client.export(
                "playerScores",
                year=season["year"],
                league_id=season["league_id"],
                host=season["host"],
                use_api_key=not args.login,
                W="YTD",
            )
        except MFLAuthError as exc:
            print(f"{season['year']}: skipped, auth required: {exc}")
            continue

        write_json(output, data)
        count = data.get("playerScores", {}).get("playerScore", [])
        if isinstance(count, dict):
            count = [count]
        print(f"{season['year']}: wrote {output} ({len(count)} scores)")


if __name__ == "__main__":
    main()
