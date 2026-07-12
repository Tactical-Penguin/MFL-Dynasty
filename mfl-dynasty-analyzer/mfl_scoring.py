from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from roster_positions import position_group


DATA_DIR = Path("data")
SCORES_PATTERN = "mfl_player_scores_*_ytd.json"


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def season_from_path(path: Path) -> int | None:
    match = re.search(r"mfl_player_scores_(\d{4})_ytd", path.name)
    return int(match.group(1)) if match else None


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_player_positions(players_path: Path = DATA_DIR / "mfl_players_2026.json") -> pd.DataFrame:
    if not players_path.exists():
        return pd.DataFrame(columns=["player_id", "mfl_position", "position_group"])

    data = load_json(players_path)
    rows = []
    for player in as_list(data.get("players", {}).get("player")):
        position = player.get("position", "")
        rows.append(
            {
                "player_id": str(player.get("id", "")),
                "mfl_position": position,
                "position_group": position_group(position),
            }
        )
    return pd.DataFrame(rows).drop_duplicates("player_id")


def load_cached_player_scores(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    rows = []
    for path in sorted(data_dir.glob(SCORES_PATTERN)):
        season = season_from_path(path)
        if season is None:
            continue

        data = load_json(path)
        if "error" in data:
            continue

        score_root = data.get("playerScores", {})
        for item in as_list(score_root.get("playerScore")):
            player_id = str(item.get("id", "")).strip()
            if not player_id:
                continue

            score = pd.to_numeric(item.get("score"), errors="coerce")
            if pd.isna(score):
                continue

            rows.append(
                {
                    "player_id": player_id,
                    "season": season,
                    "score": float(score),
                }
            )

    if not rows:
        return pd.DataFrame(columns=["player_id", "season", "score"])

    return pd.DataFrame(rows)


def scoring_context(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    scores = load_cached_player_scores(data_dir)
    if scores.empty:
        return empty_scoring_context()

    positions = load_player_positions(data_dir / "mfl_players_2026.json")
    scores = scores.merge(positions, on="player_id", how="left")
    scores["position_group"] = scores["position_group"].fillna("UNK")
    scores = scores[scores["score"].notna()].copy()
    scores = scores[scores["score"] > 0].copy()
    if scores.empty:
        return empty_scoring_context()

    scores["season_position_percentile"] = scores.groupby(["season", "position_group"])["score"].rank(
        pct=True,
        method="average",
    ) * 100.0

    latest_season = int(scores["season"].max())
    latest = (
        scores.sort_values(["player_id", "season"])
        .groupby("player_id")
        .tail(1)[["player_id", "season", "score", "season_position_percentile"]]
        .rename(
            columns={
                "season": "mfl_score_latest_year",
                "score": "mfl_score_latest",
                "season_position_percentile": "mfl_score_latest_percentile",
            }
        )
    )

    recent = scores[scores["season"] >= latest_season - 2].copy()
    recent_agg = (
        recent.groupby("player_id")
        .agg(
            mfl_score_seasons=("season", "nunique"),
            mfl_score_avg3=("score", "mean"),
            mfl_score_value=("season_position_percentile", "mean"),
            mfl_score_best_percentile=("season_position_percentile", "max"),
        )
        .reset_index()
    )

    trend = scores.sort_values(["player_id", "season"]).copy()
    trend["previous_percentile"] = trend.groupby("player_id")["season_position_percentile"].shift(1)
    trend = (
        trend.groupby("player_id")
        .tail(1)[["player_id", "season_position_percentile", "previous_percentile"]]
        .copy()
    )
    trend["mfl_score_trend"] = trend["season_position_percentile"] - trend["previous_percentile"]
    trend = trend[["player_id", "mfl_score_trend"]]

    context = latest.merge(recent_agg, on="player_id", how="left").merge(trend, on="player_id", how="left")
    context["mfl_score_seasons"] = context["mfl_score_seasons"].fillna(0).astype(int)
    return context


def empty_scoring_context() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "player_id",
            "mfl_score_latest_year",
            "mfl_score_latest",
            "mfl_score_latest_percentile",
            "mfl_score_seasons",
            "mfl_score_avg3",
            "mfl_score_value",
            "mfl_score_best_percentile",
            "mfl_score_trend",
        ]
    )
