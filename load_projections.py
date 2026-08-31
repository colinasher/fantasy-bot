"""
Load FantasyPros projection CSVs exported per position.
Those exports reuse the same header labels (ATT/YDS/TDS) for passing,
rushing, and receiving, so each file is mapped with an explicit column
list instead of trusting pandas' header row.
"""

from pathlib import Path
import re

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


# IDP rankings are treated as a name list you trust - no stat projections
# get scored, so PAR never applies to them. This is hardcoded to your
# actual export filename.
IDP_RANKINGS_FILE = "FantasyPros_Fantasy_Football_Projections_IDP.csv"


_HEADER_KEYWORDS = re.compile(r"\b(player|name|team|rank|pos)\b", re.I)


def _looks_like_header(line: str) -> bool:
    return bool(_HEADER_KEYWORDS.search(line))


def _infer_headerless_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    No header row at all - infer which column is which from the shape of
    its values: a mostly-numeric column is the rank, a column of short
    ALL-CAPS strings is the team, and the column with multi-word text
    (a space in it, like a full name) is the player name.
    """
    col_role: dict = {}
    for col in df.columns:
        sample = df[col].astype(str).str.strip()
        non_empty = sample[sample.ne("") & sample.ne("nan")]
        if non_empty.empty:
            continue
        numeric_frac = pd.to_numeric(non_empty, errors="coerce").notna().mean()
        avg_len = non_empty.str.len().mean()
        has_space_frac = non_empty.str.contains(" ").mean()
        short_upper_frac = non_empty.str.match(r"^[A-Z]{2,4}$").mean()

        if numeric_frac > 0.8 and "rank" not in col_role.values():
            col_role[col] = "rank"
        elif short_upper_frac > 0.6 and avg_len <= 4 and "team" not in col_role.values():
            col_role[col] = "team"
        elif has_space_frac > 0.5 and "name" not in col_role.values():
            col_role[col] = "name"

    if "name" not in col_role.values():
        # Nothing matched cleanly - fall back to the column with the
        # longest average string length, which is very likely the name.
        best_col, best_len = None, -1
        for col in df.columns:
            avg_len = df[col].astype(str).str.len().mean()
            if avg_len > best_len:
                best_col, best_len = col, avg_len
        if best_col is not None:
            col_role[best_col] = "name"

    return df.rename(columns=col_role)


def _read_idp_csv(path: Path) -> pd.DataFrame:
    """
    Handles three possible formats:
      1. A plain CSV with a real header on line 1 (e.g. 'name', or
         'rank,name,team').
      2. A FantasyPros-style export with a category row (TACKLES,,,MISC,,,)
         above the real header row (Player,Team,Solo,Ast,Sack,...).
      3. No header row at all - just raw rows like '1,T.J. Watt,PIT'. In
         this case column meaning is inferred from content (see
         _infer_headerless_columns) rather than assumed from a header.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        first_line = f.readline()
        second_line = f.readline()

    if _looks_like_header(first_line):
        return pd.read_csv(path)
    if _looks_like_header(second_line):
        return pd.read_csv(path, skiprows=1)
    # No header detected anywhere - read as raw data and infer columns.
    df = pd.read_csv(path, header=None)
    return _infer_headerless_columns(df)


def _find_column(columns, exact: list[str], contains: list[str]) -> str | None:
    """Exact match first, then first column containing any of `contains`."""
    for name in exact:
        if name in columns:
            return name
    for col in columns:
        for term in contains:
            if term in col:
                return col
    return None


def _load_idp_rankings(root: Path) -> pd.DataFrame | None:
    """
    Optional IDP list: needs at minimum a name-like column ('name',
    'player', or a compound header like 'player name'). Uses an explicit
    rank/RK column if present, else row order becomes the rank. 'team' is
    optional but helps drafted-player matching against the sheet. Any
    other columns (tiers, bye week, SOS, etc.) are intentionally ignored -
    IDP never gets scored or PAR'd, per design.
    Returns None (not an error) if the file isn't present yet.
    """
    path = root / IDP_RANKINGS_FILE
    if not path.exists():
        return None

    df = _read_idp_csv(path)
    df.columns = [str(c).strip().lower() for c in df.columns]

    name_col = _find_column(df.columns, ["name", "player"], ["name", "player"])
    if name_col is None:
        name_col = df.columns[0]
    df = df[df[name_col].notna()]  # drop FantasyPros' blank tier-separator rows
    df = df.rename(columns={name_col: "name"})
    df["name"] = df["name"].astype(str).str.replace("\xa0", "", regex=False).str.strip()
    df = df[df["name"].ne("") & df["name"].ne("nan")]

    team_col = _find_column(df.columns, ["team"], ["team"])
    if team_col and team_col != "team":
        df = df.rename(columns={team_col: "team"})
    if "team" not in df.columns:
        df["team"] = ""

    rank_col = _find_column(df.columns, ["rank", "rk"], ["rank"])
    if rank_col:
        df["idp_rank"] = pd.to_numeric(df[rank_col], errors="coerce")
    else:
        df["idp_rank"] = range(1, len(df) + 1)

    df["position"] = "IDP"
    return df[["name", "team", "position", "idp_rank"]].reset_index(drop=True)


def load_all_projections(data_dir: Path | None = None) -> pd.DataFrame:
    """
    QB/RB/WR/TE (raw stats, scored under league settings) + IDP (hand-rank
    only, no stats/PAR). This is what app.py should call.
    """
    root = data_dir or DATA_DIR
    offense = load_offensive_projections(root)
    idp = _load_idp_rankings(root)
    if idp is not None and len(idp):
        return pd.concat([offense, idp], ignore_index=True)
    return offense