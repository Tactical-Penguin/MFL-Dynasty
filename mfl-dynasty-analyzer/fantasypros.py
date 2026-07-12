from __future__ import annotations

import os
import re
from pathlib import Path

import pandas as pd


DEFAULT_FILES = {
    "overall": "FantasyPros_2026_Dynasty_ALL_Rankings.csv",
    "superflex": "FantasyPros_2026_Dynasty_OP_Rankings.csv",
    "idp": "FantasyPros_2026_Dynasty_IDP_Rankings.csv",
}
FILE_PATTERNS = {
    "overall": ["*FantasyPros*Dynasty*ALL*Ranking*.csv", "*FantasyPros*Dynasty*Overall*Ranking*.csv"],
    "superflex": ["*FantasyPros*Dynasty*OP*Ranking*.csv", "*FantasyPros*Dynasty*Superflex*Ranking*.csv"],
    "idp": ["*FantasyPros*Dynasty*IDP*Ranking*.csv"],
}
FANTASYPROS_CONTEXT_COLUMNS = [
    "match_name",
    "fp_player_name",
    "fp_overall_rank",
    "fp_overall_tier",
    "fp_overall_team",
    "fp_overall_pos",
    "fp_overall_age",
    "fp_overall_avg",
    "fp_superflex_rank",
    "fp_superflex_tier",
    "fp_superflex_team",
    "fp_superflex_pos",
    "fp_superflex_age",
    "fp_superflex_avg",
    "fp_idp_rank",
    "fp_idp_tier",
    "fp_idp_team",
    "fp_idp_pos",
    "fp_idp_age",
    "fp_idp_avg",
]

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
POSITION_ALIASES = {
    "DL": {"DT", "DE"},
    "DB": {"CB", "S"},
    "EDGE": {"DE", "LB"},
}


def fantasypros_dir() -> Path:
    configured = os.getenv("FANTASYPROS_DIR")
    if configured:
        return Path(configured)
    return Path.home() / "Downloads"


def fantasypros_search_dirs(directory: Path | None = None) -> list[Path]:
    local_data_dir = Path(__file__).resolve().parent / "data"
    candidates = [directory] if directory is not None else [fantasypros_dir(), local_data_dir]
    search_dirs = []
    for candidate in candidates:
        if candidate is None:
            continue
        path = Path(candidate)
        if path not in search_dirs:
            search_dirs.append(path)
    return search_dirs


def find_rankings_file(kind: str, directory: Path | None = None) -> Path | None:
    for search_dir in fantasypros_search_dirs(directory):
        exact = search_dir / DEFAULT_FILES[kind]
        if exact.exists():
            return exact

        matches = []
        for pattern in FILE_PATTERNS[kind]:
            matches.extend(search_dir.glob(pattern))
        if matches:
            return max(matches, key=lambda path: path.stat().st_mtime)

    return None


def fantasypros_file_status(directory: Path | None = None) -> list[dict[str, str | bool]]:
    statuses = []
    for kind in DEFAULT_FILES:
        path = find_rankings_file(kind, directory)
        statuses.append(
            {
                "kind": kind,
                "expected": DEFAULT_FILES[kind],
                "path": str(path) if path else "",
                "loaded": path is not None,
            }
        )
    return statuses


def normalize_name(name: str) -> str:
    value = str(name or "").strip()
    if "," in value:
        last, first = value.split(",", 1)
        value = f"{first.strip()} {last.strip()}"

    value = value.lower()
    value = value.replace(".", " ")
    value = value.replace("'", "")
    value = value.replace("-", " ")
    value = re.sub(r"[^a-z0-9 ]+", " ", value)
    parts = [part for part in value.split() if part not in SUFFIXES]
    return " ".join(parts)


def base_position(position: str) -> str:
    match = re.match(r"([A-Za-z]+)", str(position or ""))
    return match.group(1).upper() if match else ""


def positions_match(mfl_position: str, fantasypros_position: str) -> bool:
    mfl = base_position(mfl_position)
    fp = base_position(fantasypros_position)
    if not mfl or not fp:
        return True
    if mfl == fp:
        return True
    return mfl in POSITION_ALIASES.get(fp, set()) or fp in POSITION_ALIASES.get(mfl, set())


def read_rankings(kind: str, directory: Path | None = None) -> pd.DataFrame:
    path = find_rankings_file(kind, directory)
    if path is None:
        return pd.DataFrame()

    frame = pd.read_csv(path)
    frame.columns = [column.strip().lower().replace(" ", "_").replace(".", "") for column in frame.columns]
    rename_map = {
        "rk": f"fp_{kind}_rank",
        "rank": f"fp_{kind}_rank",
        "ecr": f"fp_{kind}_rank",
        "tiers": f"fp_{kind}_tier",
        "tier": f"fp_{kind}_tier",
        "player_name": "fp_player_name",
        "player": "fp_player_name",
        "name": "fp_player_name",
        "team": f"fp_{kind}_team",
        "tm": f"fp_{kind}_team",
        "pos": f"fp_{kind}_pos",
        "position": f"fp_{kind}_pos",
        "age": f"fp_{kind}_age",
        "best": f"fp_{kind}_best",
        "worst": f"fp_{kind}_worst",
        "avg": f"fp_{kind}_avg",
        "average": f"fp_{kind}_avg",
        "stddev": f"fp_{kind}_stddev",
        "ecr_vs_adp": f"fp_{kind}_ecr_vs_adp",
    }
    frame = frame.rename(columns={column: rename_map[column] for column in frame.columns if column in rename_map})
    if "fp_player_name" not in frame.columns:
        return pd.DataFrame()

    frame["match_name"] = frame["fp_player_name"].map(normalize_name)
    keep = [
        "match_name",
        "fp_player_name",
        f"fp_{kind}_rank",
        f"fp_{kind}_tier",
        f"fp_{kind}_team",
        f"fp_{kind}_pos",
        f"fp_{kind}_age",
        f"fp_{kind}_avg",
    ]
    for column in keep:
        if column not in frame.columns:
            frame[column] = pd.NA
    return frame[keep].drop_duplicates("match_name", keep="first")


def load_fantasypros_context(directory: Path | None = None) -> pd.DataFrame:
    frames = []
    for kind in DEFAULT_FILES:
        frame = read_rankings(kind, directory)
        if not frame.empty:
            frames.append(frame)

    if not frames:
        return pd.DataFrame(columns=FANTASYPROS_CONTEXT_COLUMNS)

    merged = frames[0]
    for frame in frames[1:]:
        merged = merged.merge(frame, on="match_name", how="outer", suffixes=("", "_dup"))
        for column in list(merged.columns):
            if column.endswith("_dup"):
                base = column[:-4]
                if base in merged.columns:
                    merged[base] = merged[base].combine_first(merged[column])
                merged = merged.drop(columns=[column])

    for column in FANTASYPROS_CONTEXT_COLUMNS:
        if column not in merged.columns:
            merged[column] = pd.NA

    return merged[FANTASYPROS_CONTEXT_COLUMNS]


def market_value_from_rank(rank: object, max_rank: int = 350) -> float | None:
    if pd.isna(rank):
        return None
    try:
        numeric_rank = float(rank)
    except (TypeError, ValueError):
        return None
    return max(0.0, 100.0 - ((numeric_rank - 1.0) / max_rank * 100.0))
