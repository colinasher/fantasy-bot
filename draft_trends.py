"""
draft_trends.py
Historical position-by-round draft-rate analysis, pooled across past
season tabs in the league's Google Sheet (the same data your
_hist_draft.py explored). Used to estimate how many players at a given
position are likely to be drafted before your next turn - see
priority_pick.py.
"""

from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict

from draft_sheet import fetch_sheet_csv, match_drafted_player_ids, parse_round_picks

IDP_LABELS = {"LB", "DL", "DB", "DE", "DT", "CB", "S", "IDP"}
POSITIONS = ["QB", "RB", "WR", "TE", "IDP"]

# Same years _hist_draft.py used. Adjust if you add more historical tabs.
DEFAULT_HISTORICAL_YEARS = ["2025", "2023", "2021", "2020", "2019"]


def _infer_positions_from_players_tab(csv_text: str) -> dict[str, str]:
    """PLAYERS tab: 'J. Gibbs (DET)', 'RB', ... -> lookup by cell text (with/without team)."""
    mapping: dict[str, str] = {}
    for row in csv.reader(io.StringIO(csv_text)):
        if len(row) < 2:
            continue
        name, pos = row[0].strip(), row[1].strip().upper()
        if not name or not pos:
            continue
        mapping[name.casefold()] = pos
        if "(" in name:
            mapping[name.split("(")[0].strip().casefold()] = pos
    return mapping


def _classify_cell(cell: str, players_map: dict[str, str], scored_df) -> str:
    cf = cell.casefold()
    if cf in players_map:
        pos = players_map[cf]
        return "IDP" if pos in IDP_LABELS else pos
    name_part = cell.split("(")[0].strip().casefold()
    if name_part in players_map:
        pos = players_map[name_part]
        return "IDP" if pos in IDP_LABELS else pos
    ids, _ = match_drafted_player_ids(scored_df, [cell])
    if ids:
        pid = next(iter(ids))
        row = scored_df[scored_df["player_id"] == pid]
        if len(row):
            return str(row.iloc[0]["position"])
    return "IDP"  # unmatched historical names skew IDP / retired players


def compute_round_position_shares(
    scored_df,
    years: list[str] | None = None,
    max_round: int = 20,
) -> dict[int, dict[str, float] | None]:
    """
    Returns {round: {position: share_of_picks (0-1)}} pooled across the
    given historical year tabs. `None` for a round with no historical
    data at all (caller should fall back - see share_for_round).
    """
    years = years or DEFAULT_HISTORICAL_YEARS
    players_map = _infer_positions_from_players_tab(fetch_sheet_csv("PLAYERS"))

    round_counts: dict[int, Counter] = defaultdict(Counter)
    for year in years:
        try:
            text = fetch_sheet_csv(year)
        except RuntimeError:
            continue
        picks = parse_round_picks(text)
        for rnd, cells in picks.items():
            pos_list = [_classify_cell(c, players_map, scored_df) for c in cells]
            round_counts[rnd].update(pos_list)

    shares: dict[int, dict[str, float] | None] = {}
    for rnd in range(1, max_round + 1):
        c = round_counts.get(rnd, Counter())
        n = sum(c.values())
        shares[rnd] = None if n == 0 else {p: c.get(p, 0) / n for p in POSITIONS}
    return shares


def share_for_round(shares: dict[int, dict[str, float] | None], rnd: int) -> dict[str, float]:
    """
    Look up a round's historical position shares. Falls back to the
    nearest round (earlier first, then later) with real data, and
    finally to an even split if the sheet had no usable history at all.
    """
    if shares.get(rnd) is not None:
        return shares[rnd]
    for r in range(rnd - 1, 0, -1):
        if shares.get(r) is not None:
            return shares[r]
    for r in range(rnd + 1, max(shares.keys(), default=rnd) + 1):
        if shares.get(r) is not None:
            return shares[r]
    return {p: 1 / len(POSITIONS) for p in POSITIONS}