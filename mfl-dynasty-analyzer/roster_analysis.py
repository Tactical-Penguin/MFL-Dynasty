from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path
from typing import Any

import pandas as pd

from fantasypros import (
    FANTASYPROS_CONTEXT_COLUMNS,
    load_fantasypros_context,
    market_value_from_rank,
    normalize_name,
    positions_match,
)
from mfl_scoring import scoring_context
from roster_positions import position_group


DATA_DIR = Path(__file__).resolve().parent / "data"
CORE_POSITIONS = ["QB", "RB", "WR", "TE", "PK", "DT", "DE", "LB", "CB", "S"]
KICKER_POSITIONS = {"PK", "K"}
STARTER_SLOTS = [
    ("QB", {"QB"}),
    ("RB", {"RB"}),
    ("WR", {"WR"}),
    ("DL 1", {"DL"}),
    ("DL 2", {"DL"}),
    ("LB 1", {"LB"}),
    ("LB 2", {"LB"}),
    ("DB 1", {"DB"}),
    ("DB 2", {"DB"}),
    ("FLEX 1", {"RB", "WR", "TE"}),
    ("FLEX 2", {"RB", "WR", "TE"}),
    ("FLEX 3", {"RB", "WR", "TE"}),
    ("SUPERFLEX", {"QB", "RB", "WR", "TE"}),
]

DYNASTY_TIER_OVERRIDES: dict[str, float] = {
    "13589": 100.0,  # Josh Allen
    "15281": 98.0,  # Ja'Marr Chase
    "15753": 94.0,  # Garrett Wilson
    "15751": 92.0,  # Drake London
    "16579": 91.0,  # Caleb Williams
    "14802": 90.0,  # Jonathan Taylor
    "16580": 87.0,  # Drake Maye
    "14835": 85.0,  # Tee Higgins
    "14147": 84.0,  # Nick Bosa
    "16223": 84.0,  # Will Anderson
    "16184": 83.0,  # Jayden Reed
    "16148": 82.0,  # Bryce Young
    "17112": 80.0,  # Abdul Carter
    "16653": 79.0,  # Jared Verse
    "16651": 78.0,  # Laiatu Latu
    "15253": 77.0,  # Travis Etienne
    "16187": 76.0,  # Josh Downs
    "17123": 75.0,  # Jihaad Campbell
    "17147": 74.0,  # Carson Schwesinger
    "16244": 74.0,  # Brian Branch
    "14167": 73.0,  # Josh Hines-Allen
    "14148": 72.0,  # Montez Sweat
    "15261": 71.0,  # Chuba Hubbard
    "14908": 70.0,  # Xavier McKinney
    "15418": 68.0,  # Camryn Bynum
    "9431": 67.0,   # Matthew Stafford
    "14322": 66.0,  # T.J. Edwards
    "13697": 64.0,  # Tremaine Edmunds
    "15351": 63.0,  # Jeremiah Owusu-Koramoah
    "14590": 62.0,  # Azeez Al-Shaair
    "17073": 61.0,  # Elic Ayomanor
    "16619": 60.0,  # Troy Franklin
    "16080": 59.0,  # Rashid Shaheed
}


POSITION_SCARCITY = {
    "QB": 18.0,
    "WR": 12.0,
    "RB": 10.0,
    "TE": 8.0,
    "DE": 13.0,
    "DT": 9.0,
    "LB": 11.0,
    "CB": 7.0,
    "S": 9.0,
    "PK": -8.0,
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def clean_franchise_name(name: object) -> str:
    text = unescape(str(name or ""))
    text = re.sub(r"<[^>]*>", "", text)
    return " ".join(text.split())


def league_franchises(
    league_path: Path = DATA_DIR / "mfl_league_2026.json",
    roster_path: Path = DATA_DIR / "mfl_rosters_2026.json",
) -> list[dict[str, str]]:
    rosters = load_json(roster_path)
    roster_franchises = as_list(rosters.get("rosters", {}).get("franchise", []))
    roster_ids = [str(item.get("id", "")) for item in roster_franchises if item.get("id")]

    league_franchises_by_id: dict[str, dict[str, Any]] = {}
    if league_path.exists():
        league = load_json(league_path)
        raw_franchises = as_list(league.get("league", {}).get("franchises", {}).get("franchise", []))
        league_franchises_by_id = {
            str(item["id"]): item
            for item in raw_franchises
            if isinstance(item, dict) and item.get("id")
        }

    franchise_ids = roster_ids or sorted(league_franchises_by_id)
    franchises = []
    for franchise_id in franchise_ids:
        details = league_franchises_by_id.get(franchise_id, {})
        name = clean_franchise_name(details.get("name", ""))
        label = f"{name} ({franchise_id})" if name else f"Franchise {franchise_id}"
        franchises.append(
            {
                "id": franchise_id,
                "name": name or f"Franchise {franchise_id}",
                "label": label,
                "icon": str(details.get("icon", "")),
                "logo": str(details.get("logo", "")),
            }
        )

    return franchises


def franchise_names_by_id(
    league_path: Path = DATA_DIR / "mfl_league_2026.json",
    roster_path: Path = DATA_DIR / "mfl_rosters_2026.json",
) -> dict[str, str]:
    return {franchise["id"]: franchise["name"] for franchise in league_franchises(league_path, roster_path)}


def load_player_map(path: Path = DATA_DIR / "mfl_players_2026.json") -> dict[str, dict[str, Any]]:
    data = load_json(path)
    return {player["id"]: player for player in data["players"]["player"]}


def roster_dataframe(
    franchise_id: str = "0002",
    roster_path: Path = DATA_DIR / "mfl_rosters_2026.json",
    players_path: Path = DATA_DIR / "mfl_players_2026.json",
) -> pd.DataFrame:
    rosters = load_json(roster_path)
    player_map = load_player_map(players_path)
    franchises = as_list(rosters["rosters"]["franchise"])
    team_names = franchise_names_by_id(roster_path=roster_path)

    if franchise_id.upper() == "ALL":
        selected_franchises = [item for item in franchises if item.get("id")]
    else:
        franchise = next((item for item in franchises if item.get("id") == franchise_id), None)
        selected_franchises = [franchise] if franchise is not None else []

    if not selected_franchises:
        available_ids = ", ".join(sorted(str(item.get("id")) for item in franchises if item.get("id")))
        raise ValueError(f"Franchise {franchise_id} was not found. Available franchise IDs: {available_ids}")

    rows = []
    for franchise in selected_franchises:
        current_franchise_id = str(franchise.get("id", ""))
        franchise_name = team_names.get(current_franchise_id, f"Franchise {current_franchise_id}")
        for roster_player in as_list(franchise.get("player", [])):
            player_id = str(roster_player["id"])
            player = player_map.get(player_id, {})
            position = player.get("position", "")
            rows.append(
                {
                    "roster_key": f"{current_franchise_id}:{player_id}",
                    "franchise_id": current_franchise_id,
                    "franchise_name": franchise_name,
                    "id": player_id,
                    "name": player.get("name", ""),
                    "position": position,
                    "position_group": position_group(position),
                    "nfl_team": player.get("team", ""),
                    "status": roster_player.get("status", ""),
                    "drafted": roster_player.get("drafted", ""),
                }
            )

    frame = pd.DataFrame(rows)
    frame["match_name"] = frame["name"].map(normalize_name)
    frame["active_roster"] = frame["status"].eq("ROSTER")
    frame["dynasty_value"] = frame.apply(score_player, axis=1)
    frame = add_fantasypros_context(frame)
    frame = add_scoring_context(frame)
    frame["protection_value"] = frame.apply(blended_protection_value, axis=1)
    frame["protect_rank"] = (
        frame.groupby("franchise_id")["protection_value"]
        .rank(ascending=False, method="first")
        .astype(int)
    )
    frame["recommended_34_all_owned"] = frame["protect_rank"].le(34)

    active = frame[frame["active_roster"]].copy()
    active_ranks = active.groupby("franchise_id")["protection_value"].rank(ascending=False, method="first")
    frame["recommended_34_active_only"] = False
    frame.loc[active.index, "recommended_34_active_only"] = active_ranks.le(34)
    return frame.sort_values(["franchise_name", "protection_value"], ascending=[True, False]).reset_index(drop=True)


def add_fantasypros_context(frame: pd.DataFrame) -> pd.DataFrame:
    fantasypros = load_fantasypros_context()
    if fantasypros.empty:
        for column in FANTASYPROS_CONTEXT_COLUMNS:
            if column != "match_name":
                frame[column] = pd.NA
        frame["fp_matched"] = False
        frame["fp_market_value"] = pd.NA
        frame["fp_primary_rank"] = pd.NA
        frame["fp_primary_source"] = pd.NA
        frame["fp_position_mismatch"] = False
        return frame

    merged = frame.merge(fantasypros, on="match_name", how="left")
    merged["fp_matched"] = merged["fp_player_name"].notna()
    merged["fp_primary_rank"] = merged.apply(primary_fantasypros_rank, axis=1)
    merged["fp_primary_source"] = merged.apply(primary_fantasypros_source, axis=1)
    merged["fp_market_value"] = merged["fp_primary_rank"].map(market_value_from_rank)
    merged["fp_position_mismatch"] = merged.apply(fantasypros_position_mismatch, axis=1)
    for column in FANTASYPROS_CONTEXT_COLUMNS:
        if column not in merged.columns:
            merged[column] = pd.NA
    return merged


def add_scoring_context(frame: pd.DataFrame) -> pd.DataFrame:
    scores = scoring_context()
    if scores.empty:
        return add_empty_scoring_columns(frame)

    merged = frame.merge(scores, left_on="id", right_on="player_id", how="left")
    return add_empty_scoring_columns(merged)


def add_empty_scoring_columns(frame: pd.DataFrame) -> pd.DataFrame:
    defaults = {
        "mfl_score_latest_year": pd.NA,
        "mfl_score_latest": pd.NA,
        "mfl_score_latest_percentile": pd.NA,
        "mfl_score_seasons": 0,
        "mfl_score_avg3": pd.NA,
        "mfl_score_value": pd.NA,
        "mfl_score_best_percentile": pd.NA,
        "mfl_score_trend": pd.NA,
    }
    for column, default in defaults.items():
        if column not in frame.columns:
            frame[column] = default
    return frame


def primary_fantasypros_rank(row: pd.Series) -> object:
    if row["position"] in {"DT", "DE", "LB", "CB", "S"}:
        return row.get("fp_idp_rank", pd.NA)
    if row["position"] in {"QB", "RB", "WR", "TE"}:
        return row.get("fp_superflex_rank", pd.NA)
    return row.get("fp_overall_rank", pd.NA)


def primary_fantasypros_source(row: pd.Series) -> str | None:
    if row["position"] in {"DT", "DE", "LB", "CB", "S"} and pd.notna(row.get("fp_idp_rank", pd.NA)):
        return "IDP"
    if row["position"] in {"QB", "RB", "WR", "TE"} and pd.notna(row.get("fp_superflex_rank", pd.NA)):
        return "Superflex"
    if pd.notna(row.get("fp_overall_rank", pd.NA)):
        return "Overall"
    return None


def fantasypros_position_mismatch(row: pd.Series) -> bool:
    if not row.get("fp_matched", False):
        return False

    if row["position"] in {"DT", "DE", "LB", "CB", "S"}:
        fp_position = row.get("fp_idp_pos", "")
    elif row["position"] in {"QB", "RB", "WR", "TE"}:
        fp_position = row.get("fp_superflex_pos", "")
    else:
        fp_position = row.get("fp_overall_pos", "")

    return not positions_match(row["position"], fp_position)


def blended_protection_value(row: pd.Series) -> float:
    heuristic = float(row["dynasty_value"])
    market = row.get("fp_market_value")
    production = row.get("mfl_score_value")

    if pd.isna(market) and pd.isna(production):
        return heuristic

    if pd.isna(production):
        market_value = float(market)
        value = (heuristic * 0.45) + (market_value * 0.55)

        # Avoid letting a suspicious external positional bucket dominate the model.
        if row.get("fp_position_mismatch", False):
            value = (heuristic * 0.75) + (market_value * 0.25)
        return value

    production_value = float(production)
    trend = row.get("mfl_score_trend")
    trend_adjustment = 0.0 if pd.isna(trend) else max(-4.0, min(4.0, float(trend) * 0.05))

    if pd.isna(market):
        value = (heuristic * 0.65) + (production_value * 0.35)
    else:
        market_value = float(market)
        if row.get("fp_position_mismatch", False):
            value = (heuristic * 0.45) + (market_value * 0.25) + (production_value * 0.30)
        else:
            value = (heuristic * 0.30) + (market_value * 0.45) + (production_value * 0.25)

    value += trend_adjustment
    return value


def score_player(row: pd.Series) -> float:
    player_id = str(row["id"])
    if player_id in DYNASTY_TIER_OVERRIDES:
        return DYNASTY_TIER_OVERRIDES[player_id]

    score = 35.0
    score += POSITION_SCARCITY.get(row["position"], 0.0)

    if row["status"] == "INJURED_RESERVE":
        score -= 3.0

    drafted = str(row.get("drafted", ""))
    if "2025" in drafted or drafted.startswith(("1.", "2.", "3.")):
        score += 8.0
    if "FCFS" in drafted or "Waiv" in drafted:
        score -= 2.0

    return score


def protection_summary(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    selected = frame[frame[column]]
    return (
        selected.groupby(["position_group"], dropna=False)
        .size()
        .reset_index(name="protected")
        .sort_values("position_group")
    )


def lineup_position(position: object) -> str:
    match = re.match(r"([A-Za-z]+)", str(position or ""))
    base = match.group(1).upper() if match else ""
    if base in {"DT", "DE"}:
        return "DL"
    if base in {"CB", "S"}:
        return "DB"
    return base


def chart_position(position: object) -> str:
    return lineup_position(position) or "UNK"


def starter_bucket(slot_name: str) -> str:
    if slot_name.startswith("DL"):
        return "DL"
    if slot_name.startswith("LB"):
        return "LB"
    if slot_name.startswith("DB"):
        return "DB"
    return slot_name


def primary_fantasypros_age(row: pd.Series) -> object:
    if row["position"] in {"DT", "DE", "LB", "CB", "S"}:
        return row.get("fp_idp_age", pd.NA)
    if row["position"] in {"QB", "RB", "WR", "TE"}:
        return row.get("fp_superflex_age", pd.NA)
    return row.get("fp_overall_age", pd.NA)


def median_series(values: pd.Series) -> float | pd.NA:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return pd.NA
    return float(numeric.median())


def choose_starters(team_frame: pd.DataFrame) -> tuple[list[dict[str, object]], float]:
    available = team_frame.copy()
    available["_power_value"] = pd.to_numeric(available["protection_value"], errors="coerce").fillna(0.0)
    available["_lineup_position"] = available["position"].map(lineup_position)
    available = available.sort_values("_power_value", ascending=False).to_dict("records")

    starters: list[dict[str, object]] = []
    starter_score = 0.0
    for slot_name, valid_positions in STARTER_SLOTS:
        for index, player in enumerate(available):
            if player["_lineup_position"] not in valid_positions:
                continue

            value = float(player["_power_value"])
            starters.append(
                {
                    "franchise_id": player["franchise_id"],
                    "franchise_name": player["franchise_name"],
                    "starter_slot": slot_name,
                    "starter_bucket": starter_bucket(slot_name),
                    "lineup_position": player["_lineup_position"],
                    "name": player["name"],
                    "position": player["position"],
                    "nfl_team": player["nfl_team"],
                    "score": value,
                    "fp_primary_source": player.get("fp_primary_source", pd.NA),
                    "fp_primary_rank": player.get("fp_primary_rank", pd.NA),
                }
            )
            starter_score += value
            del available[index]
            break

    return starters, starter_score


def league_power_rankings(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rankings = []
    starter_rows = []

    working = frame.copy()
    working["fp_primary_age"] = working.apply(primary_fantasypros_age, axis=1)
    working["protection_value"] = pd.to_numeric(working["protection_value"], errors="coerce").fillna(0.0)

    for (franchise_id, franchise_name), team_frame in working.groupby(["franchise_id", "franchise_name"], sort=False):
        starters, starter_score = choose_starters(team_frame)
        starter_rows.extend(starters)

        overall_score = float(team_frame["protection_value"].sum())
        bench_score = overall_score - starter_score
        rankings.append(
            {
                "franchise_id": franchise_id,
                "franchise_name": franchise_name,
                "starter_score": starter_score,
                "overall_score": overall_score,
                "bench_score": bench_score,
                "roster_size": int(len(team_frame)),
                "median_age": median_series(team_frame["fp_primary_age"]),
                "fp_matches": int(team_frame["fp_matched"].sum()) if "fp_matched" in team_frame else 0,
            }
        )

    rankings_frame = pd.DataFrame(rankings).sort_values(
        ["starter_score", "overall_score"],
        ascending=[False, False],
    )
    rankings_frame.insert(0, "power_rank", range(1, len(rankings_frame) + 1))

    starters_frame = pd.DataFrame(starter_rows)
    if starters_frame.empty:
        starter_breakdown = pd.DataFrame(columns=["franchise_name", "starter_bucket", "score"])
    else:
        slot_order = {slot_name: index for index, (slot_name, _) in enumerate(STARTER_SLOTS)}
        starters_frame = starters_frame.merge(
            rankings_frame[["franchise_name", "power_rank"]],
            on="franchise_name",
            how="left",
        )
        starters_frame["_slot_order"] = starters_frame["starter_slot"].map(slot_order)
        starters_frame = starters_frame.sort_values(["power_rank", "_slot_order"]).drop(columns=["_slot_order"])
        starter_breakdown = (
            starters_frame.groupby(["franchise_name", "starter_bucket"], as_index=False)["score"]
            .sum()
            .merge(rankings_frame[["franchise_name", "power_rank"]], on="franchise_name", how="left")
            .sort_values(["power_rank", "starter_bucket"])
        )

    return rankings_frame.reset_index(drop=True), starter_breakdown, starters_frame


def cutdown_projection(
    frame: pd.DataFrame,
    position_slots: int = 33,
    kicker_slots: int = 1,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    projected = frame.copy()
    projected["_cut_value"] = pd.to_numeric(projected["protection_value"], errors="coerce").fillna(0.0)
    projected["cutdown_protected"] = False
    projected["cutdown_status"] = "Projected Cut"

    for _, team_frame in projected.groupby("franchise_id", sort=False):
        kickers = team_frame[team_frame["position"].isin(KICKER_POSITIONS)]
        protected_kicker_keys = set(
            kickers.sort_values("_cut_value", ascending=False).head(kicker_slots)["roster_key"]
        )

        position_players = team_frame[~team_frame["position"].isin(KICKER_POSITIONS)]
        protected_position_keys = set(
            position_players.sort_values("_cut_value", ascending=False).head(position_slots)["roster_key"]
        )

        projected.loc[projected["roster_key"].isin(protected_kicker_keys), "cutdown_status"] = "Protected Kicker"
        projected.loc[projected["roster_key"].isin(protected_position_keys), "cutdown_status"] = "Protected Position"
        projected.loc[
            projected["roster_key"].isin(protected_kicker_keys | protected_position_keys),
            "cutdown_protected",
        ] = True

    summaries = []
    for (franchise_id, franchise_name), team_frame in projected.groupby(["franchise_id", "franchise_name"], sort=False):
        protected = team_frame[team_frame["cutdown_protected"]]
        cut = team_frame[~team_frame["cutdown_protected"]]
        total_value = float(team_frame["_cut_value"].sum())
        protected_value = float(protected["_cut_value"].sum())
        lost_value = float(cut["_cut_value"].sum())
        summaries.append(
            {
                "franchise_id": franchise_id,
                "franchise_name": franchise_name,
                "roster_size": int(len(team_frame)),
                "protected_players": int(len(protected)),
                "protected_positions": int(protected["cutdown_status"].eq("Protected Position").sum()),
                "protected_kickers": int(protected["cutdown_status"].eq("Protected Kicker").sum()),
                "projected_cuts": int(len(cut)),
                "pre_cut_value": total_value,
                "protected_value": protected_value,
                "lost_value": lost_value,
                "lost_value_pct": (lost_value / total_value * 100.0) if total_value else 0.0,
            }
        )

    summary = pd.DataFrame(summaries).sort_values("lost_value", ascending=False).reset_index(drop=True)
    return projected.drop(columns=["_cut_value"]), summary
