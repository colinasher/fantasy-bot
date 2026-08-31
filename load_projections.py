"""
Load FantasyPros projection CSVs exported per position.

Those exports reuse the same header labels (ATT/YDS/TDS) for passing,
rushing, and receiving, so each file is mapped with an explicit column
list instead of trusting pandas' header row.
"""

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent

# skiprows=1 drops the original header so `names` is the real schema.
POSITION_FILES = {
    "QB": (
        "FantasyPros_Fantasy_Football_Projections_QB.csv",
        [
            "name", "team",
            "pass_att", "pass_cmp", "pass_yds", "pass_td", "pass_int",
            "rush_att", "rush_yds", "rush_td",
            "fl", "fpts",
        ],
    ),
    "RB": (
        "FantasyPros_Fantasy_Football_Projections_RB.csv",
        [
            "name", "team",
            "rush_att", "rush_yds", "rush_td",
            "rec", "rec_yds", "rec_td",
            "fl", "fpts",
        ],
    ),
    "WR": (
        "FantasyPros_Fantasy_Football_Projections_WR.csv",
        [
            "name", "team",
            "rec", "rec_yds", "rec_td",
            "rush_att", "rush_yds", "rush_td",
            "fl", "fpts",
        ],
    ),
    "TE": (
        "FantasyPros_Fantasy_Football_Projections_TE.csv",
        [
            "name", "team",
            "rec", "rec_yds", "rec_td",
            "fl", "fpts",
        ],
    ),
}


def _clean_players(df: pd.DataFrame, position: str) -> pd.DataFrame:
    df = df.copy()
    df["name"] = df["name"].astype(str).str.replace("\xa0", "", regex=False).str.strip()
    df = df[df["name"].ne("") & df["name"].ne("nan")]
    df["position"] = position
    df = df.drop(columns=["fpts"], errors="ignore")
    return df


def load_offensive_projections(data_dir: Path | None = None) -> pd.DataFrame:
    """Return one DataFrame of QB/RB/WR/TE projections in scoring.py's schema."""
    root = data_dir or DATA_DIR
    frames = []
    missing = []
    for position, (filename, names) in POSITION_FILES.items():
        path = root / filename
        if not path.exists():
            missing.append(filename)
            continue
        df = pd.read_csv(path, skiprows=1, names=names)
        frames.append(_clean_players(df, position))

    if missing and not frames:
        raise FileNotFoundError(
            "No projection CSVs found. Expected files like: " + ", ".join(missing)
        )
    if missing:
        raise FileNotFoundError("Missing projection CSVs: " + ", ".join(missing))

    return pd.concat(frames, ignore_index=True)
