"""
scoring.py
Converts raw per-player stat projections into fantasy points using the
league's custom scoring settings.

Expected raw stat columns (any can be missing/0):
    pass_yds, pass_td,
    rush_yds, rush_td,
    rec, rec_yds, rec_td,
    tackles_solo, tackles_ast, sacks, tfl, int, fum_rec, forced_fum, def_td
"""

import pandas as pd

# ---- League scoring settings ----
SCORING = {
    # Passing
    "pass_yds": 0.04,
    "pass_td": 4,
    # Rushing
    "rush_yds": 0.1,
    "rush_td": 6,
    # Receiving
    "rec_yds": 0.1,
    "rec": 0.5,
    "rec_td": 6,
    # IDP
    "tackles_solo": 1.0,
    "tackles_ast": 1.0,
    "sacks": 3.0,      # fractional sacks (e.g. 0.5) scale naturally
    "tfl": 0.5,        # fractional TFL (half-sack-TFL) scale naturally
    "int": 4.0,
    "fum_rec": 1.0,
    "forced_fum": 2.0,
    "def_td": 6.0,
}

# All stat columns we know how to score
STAT_COLUMNS = list(SCORING.keys())


def ensure_stat_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Make sure every scoring-relevant column exists, filling missing with 0."""
    df = df.copy()
    for col in STAT_COLUMNS:
        if col not in df.columns:
            df[col] = 0.0
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return df


def score_players(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add a 'fantasy_points' column to df based on SCORING weights.
    Expects a 'position' column (QB/RB/WR/TE/IDP or specific IDP subtypes
    like LB/DL/DB which all get treated as IDP).
    """
    df = ensure_stat_columns(df)

    points = pd.Series(0.0, index=df.index)
    for col, weight in SCORING.items():
        points += df[col] * weight

    df["fantasy_points"] = points.round(2)
    return df
