"""One-off: compile historical position-by-round draft rates."""
from __future__ import annotations

import csv
import io
import re
from collections import Counter, defaultdict

from draft_sheet import PLAYER_CELL, TEAM_COLUMNS, fetch_sheet_csv, match_drafted_player_ids
from load_projections import load_offensive_projections
from scoring import score_players

ROUND_RE = re.compile(r"^Round\s+(\d+)$", re.I)


def infer_positions_from_players_tab(csv_text: str) -> dict[str, str]:
    """PLAYERS tab: 'J. Gibbs (DET)', 'RB', ..."""
    mapping = {}
    for row in csv.reader(io.StringIO(csv_text)):
        if len(row) < 2:
            continue
        name, pos = row[0].strip(), row[1].strip().upper()
        if name and pos:
            mapping[name.casefold()] = pos
            # also without team
            if "(" in name:
                mapping[name.split("(")[0].strip().casefold()] = pos
    return mapping


def parse_round_picks(csv_text: str) -> dict[int, list[str]]:
    by_round: dict[int, list[str]] = {}
    for row in csv.reader(io.StringIO(csv_text)):
        if not row:
            continue
        m = ROUND_RE.match((row[0] or "").strip())
        if not m:
            continue
        rnd = int(m.group(1))
        picks = []
        for cell in row[1 : 1 + TEAM_COLUMNS]:
            text = (cell or "").strip()
            if PLAYER_CELL.match(text):
                picks.append(text)
        by_round[rnd] = picks
    return by_round


def classify(cell: str, players_map: dict[str, str], scored) -> str:
    cf = cell.casefold()
    if cf in players_map:
        pos = players_map[cf]
        return "IDP" if pos in {"LB", "DL", "DB", "DE", "DT", "CB", "S", "IDP"} else pos
    name_part = cell.split("(")[0].strip().casefold()
    if name_part in players_map:
        pos = players_map[name_part]
        return "IDP" if pos in {"LB", "DL", "DB", "DE", "DT", "CB", "S", "IDP"} else pos
    ids, unmatched = match_drafted_player_ids(scored, [cell])
    if ids:
        pid = next(iter(ids))
        row = scored[scored["player_id"] == pid]
        if len(row):
            return str(row.iloc[0]["position"])
    return "IDP"  # unmatched historical names are mostly IDP / retired


def main() -> None:
    raw = load_offensive_projections()
    raw["player_id"] = raw["name"].astype(str) + "_" + raw["position"].astype(str)
    scored = score_players(raw)
    players_map = infer_positions_from_players_tab(fetch_sheet_csv("PLAYERS"))

    years = ["2025", "2023", "2021", "2020", "2019"]
    round_pos = defaultdict(Counter)
    year_round = {}

    for year in years:
        try:
            text = fetch_sheet_csv(year)
        except RuntimeError as e:
            print(year, e)
            continue
        picks = parse_round_picks(text)
        year_round[year] = {}
        for rnd, cells in sorted(picks.items()):
            pos_list = [classify(c, players_map, scored) for c in cells]
            year_round[year][rnd] = Counter(pos_list)
            round_pos[rnd].update(pos_list)
            print(f"{year} R{rnd:02d} n={len(cells)} {dict(Counter(pos_list))}")

    print("\n=== AVERAGE SHARE BY ROUND (pooled) ===")
    positions = ["QB", "RB", "WR", "TE", "IDP"]
    print("rnd", *[f"{p:>6}" for p in positions], "n")
    for rnd in range(1, 21):
        c = round_pos[rnd]
        n = sum(c.values()) or 1
        shares = [f"{100*c[p]/n:5.1f}%" for p in positions]
        print(f"{rnd:3d}", *shares, f"{sum(c.values()):3d}")

    print("\n=== FIRST ROUND WITH >=1 QB (by year) ===")
    for year, rounds in year_round.items():
        first = min((r for r, c in rounds.items() if c.get("QB", 0) > 0), default=None)
        print(year, "first QB round", first, "QB by round", {r: c.get("QB", 0) for r, c in rounds.items() if c.get("QB")})


if __name__ == "__main__":
    main()
