"""
Read live draft results from the league Google Sheet.

Picks and roster slots use FantasyPros-style abbreviations, e.g.
"J. Chase (CIN)", "A. St. Brown (DET)", "P. Mahomes II (KC)".
"""

from __future__ import annotations

import csv
import io
import re
import urllib.error
import urllib.parse
import urllib.request

SHEET_ID = "1RrqFIRwu8W11rWkOyNWUM4k0u5Dzc0qNe6eS1k6EV_0"
SHEET_NAME = "2026"
SHEET_URL = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
    f"#gid=290495943"
)
TRADES_SHEET_NAME = "Trades 2026"

# First 10 data columns after the row label are the 10 teams.
# Everything to the right is pick-trade / extension metadata.
TEAM_COLUMNS = 10

PLAYER_CELL = re.compile(
    r"^[A-Za-z]\.\s+.+\([A-Za-z]{2,3}\)$"
)

SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"}

# Matches row labels like "Round 1", "Round 12" in the pick-grid tabs.
ROUND_RE = re.compile(r"^Round\s+(\d+)$", re.I)


def fetch_sheet_csv(sheet_name: str = SHEET_NAME) -> str:
    url = (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq"
        f"?tqx=out:csv&sheet={urllib.parse.quote(sheet_name)}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"Could not read Google Sheet tab '{sheet_name}' "
            f"(HTTP {e.code}). Is the sheet still shared as viewable?"
        ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error reading Google Sheet: {e}") from e


def extract_drafted_cells(csv_text: str) -> list[str]:
    """Return unique drafted player strings from pick grid + roster slots."""
    reader = csv.reader(io.StringIO(csv_text))
    found: list[str] = []
    seen: set[str] = set()
    for row in reader:
        cells = row[1 : 1 + TEAM_COLUMNS]
        for cell in cells:
            text = (cell or "").strip()
            if not text or not PLAYER_CELL.match(text):
                continue
            key = text.casefold()
            if key not in seen:
                seen.add(key)
                found.append(text)
    return found


def _strip_suffixes(parts: list[str]) -> list[str]:
    while parts and parts[-1].casefold().rstrip(".") in {s.rstrip(".") for s in SUFFIXES}:
        parts = parts[:-1]
    return parts


def _abbrev_forms(name: str) -> set[str]:
    """'Ja'Marr Chase' -> {'J. Chase'}; 'A.J. Brown' -> {'A.J. Brown', 'A. Brown'}."""
    parts = [p for p in (name or "").split() if p]
    if len(parts) < 2 or not parts[0]:
        return set()
    initial = parts[0][0].upper()
    rest = parts[1:]
    forms = {
        f"{initial}. {' '.join(rest)}",
        f"{initial}. {' '.join(_strip_suffixes(list(rest)))}",
    }
    # "A.J. Brown" is already first-token + last; also keep the dotted first name.
    if "." in parts[0]:
        forms.add(f"{parts[0]} {' '.join(rest)}")
        forms.add(f"{parts[0]} {' '.join(_strip_suffixes(list(rest)))}")
    return {f.casefold() for f in forms if f.strip()}


def board_keys_for_player(name: str, team: str) -> set[str]:
    """
    Keys a projection player might appear as on the draft board.
    "Ja'Marr Chase" / CIN -> "J. Chase (CIN)"
    "Aaron Jones Sr." / MIN -> "A. Jones Sr. (MIN)" and "A. Jones (MIN)"
    """
    team = (team or "").strip().upper()
    forms = _abbrev_forms(name)
    if not forms:
        return set()
    keys = set(forms)
    if team:
        keys |= {f"{form} ({team.casefold()})" for form in forms}
    return keys


def _parse_cell(cell: str) -> tuple[str, str] | None:
    text = (cell or "").strip()
    if not PLAYER_CELL.match(text):
        return None
    body, team = text.rsplit("(", 1)
    return body.strip(), team.rstrip(")").strip()


def match_drafted_player_ids(scored_df, cells: list[str]) -> tuple[set[str], list[str]]:
    """
    Map drafted board cells onto scored_df player_id values.
    Returns (matched_ids, unmatched_board_names).
    """
    exact: dict[str, str] = {}
    by_abbrev: dict[str, list[str]] = {}

    for _, row in scored_df.iterrows():
        pid = row["player_id"]
        keys = board_keys_for_player(str(row["name"]), str(row.get("team", "")))
        abbrevs = _abbrev_forms(str(row["name"]))
        for key in keys:
            if "(" in key:
                exact.setdefault(key, pid)
        for abbr in abbrevs:
            by_abbrev.setdefault(abbr, []).append(pid)

    matched_ids: set[str] = set()
    unmatched: list[str] = []

    for cell in cells:
        parsed = _parse_cell(cell)
        if not parsed:
            unmatched.append(cell)
            continue
        name_part, team = parsed
        name_cf = name_part.casefold()
        stripped = " ".join(_strip_suffixes(name_part.split())).casefold()
        candidates = [
            f"{name_cf} ({team.casefold()})",
            f"{stripped} ({team.casefold()})",
            name_cf,
            stripped,
        ]
        pid = None
        for cand in candidates:
            if cand in exact:
                pid = exact[cand]
                break
        if pid is None:
            for cand in (name_cf, stripped):
                ids = by_abbrev.get(cand, [])
                unique = list(dict.fromkeys(ids))
                if len(unique) == 1:
                    pid = unique[0]
                    break
        if pid is None:
            unmatched.append(cell)
        else:
            matched_ids.add(pid)

    return matched_ids, unmatched


# ---------------------------------------------------------------------------
# New: round-grid parsing, used by both draft_trends.py (historical tabs)
# and priority_pick.py (live current-round detection on the "2026" tab).
# ---------------------------------------------------------------------------

def parse_round_picks(csv_text: str) -> dict[int, list[str]]:
    """Round number -> ordered list of FILLED pick-grid cells (left to right)."""
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


def parse_round_cells(csv_text: str) -> dict[int, list[str]]:
    """
    Round number -> raw cells for all TEAM_COLUMNS, in column order,
    preserving empty strings for not-yet-made picks. Needed to know
    exactly which team-column slots are still open in an in-progress
    round (parse_round_picks only returns the filled ones, losing
    position information).
    """
    by_round: dict[int, list[str]] = {}
    for row in csv.reader(io.StringIO(csv_text)):
        if not row:
            continue
        m = ROUND_RE.match((row[0] or "").strip())
        if not m:
            continue
        rnd = int(m.group(1))
        cells = [(c or "").strip() for c in row[1 : 1 + TEAM_COLUMNS]]
        by_round[rnd] = cells
    return by_round


def get_team_names(sheet_name: str = SHEET_NAME) -> list[str]:
    """
    First row of the tab = the 10 team-column headers, in column order.
    Used to let the user pick 'which column is my team' for the priority
    pick's snake-order lookahead.
    """
    csv_text = fetch_sheet_csv(sheet_name)
    reader = csv.reader(io.StringIO(csv_text))
    header = next(reader, [])
    names = [(c or "").strip() for c in header[1 : 1 + TEAM_COLUMNS]]
    return names

# ---------------------------------------------------------------------------
# Roster section: the sheet has a labeled row per slot (QB1, QB2, ..., BN8)
# below the pick grid, one column per team - same TEAM_COLUMNS layout.
# ---------------------------------------------------------------------------

ROSTER_SLOTS = [
    "QB1", "QB2",
    "RB1", "RB2",
    "WR1", "WR2", "WR3",
    "TE1",
    "FLEX",
    "IDP1", "IDP2", "IDP3",
    "BN1", "BN2", "BN3", "BN4", "BN5", "BN6", "BN7", "BN8",
]


def parse_roster_rows(csv_text: str) -> dict[str, list[str]]:
    """
    Slot label ('QB1', 'FLEX', 'BN3', ...) -> raw cells for all
    TEAM_COLUMNS, in column order. Only the first matching row per label
    is kept (in case a label string appears more than once anywhere else
    in the sheet).
    """
    wanted = {s.upper() for s in ROSTER_SLOTS}
    by_slot: dict[str, list[str]] = {}
    for row in csv.reader(io.StringIO(csv_text)):
        if not row:
            continue
        label = (row[0] or "").strip().upper()
        if label in wanted and label not in by_slot:
            cells = [(c or "").strip() for c in row[1 : 1 + TEAM_COLUMNS]]
            by_slot[label] = cells
    return by_slot

# ---------------------------------------------------------------------------
# Trades tab: a "Pick" / "Team" table (columns B, C) that already reflects
# any traded picks - this is the authoritative, trade-adjusted draft order,
# so it's read directly instead of trying to simulate snake order + trades.
# ---------------------------------------------------------------------------

TRADES_SHEET_NAME = "Trades 2026"

PICK_LABEL_RE = re.compile(r"^(\d+)\.(\d+)$")


def parse_pick_order_tab(csv_text: str) -> list[tuple[int, str]]:
    """
    Returns [(round, team_name), ...] in true overall pick order (index 0
    = pick 1). Reads whichever rows are actually present - no round limit
    assumed, since the tab may not be filled out beyond the picks made
    (or planned) so far.
    """
    entries: dict[tuple[int, int], str] = {}
    for row in csv.reader(io.StringIO(csv_text)):
        if len(row) < 3:
            continue
        label = (row[1] or "").strip()
        team = (row[2] or "").strip()
        m = PICK_LABEL_RE.match(label)
        if m and team:
            rnd, pos = int(m.group(1)), int(m.group(2))
            entries[(rnd, pos)] = team

    ordered_keys = sorted(entries.keys())
    return [(rnd, entries[(rnd, pos)]) for rnd, pos in ordered_keys]