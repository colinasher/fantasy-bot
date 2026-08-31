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

# First 10 data columns after the row label are the 10 teams.
# Everything to the right is pick-trade / extension metadata.
TEAM_COLUMNS = 10

PLAYER_CELL = re.compile(
    r"^[A-Za-z]\.\s+.+\([A-Za-z]{2,3}\)$"
)
SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"}


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
