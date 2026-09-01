"""
bye_weeks.py
Static 2026 bye-week lookup by team, keyed off the abbreviations used in
FantasyPros exports (and common alternate abbreviations other sources use).
"""

from __future__ import annotations

# Canonical team abbreviation -> bye week.
BYE_WEEK_BY_TEAM = {
    "CAR": 5, "KC": 5,
    "CIN": 6, "DET": 6, "MIA": 6, "MIN": 6,
    "BUF": 7, "JAX": 7, "LAC": 7, "WAS": 7,
    "HOU": 8, "NO": 8, "NYG": 8, "SF": 8,
    "PIT": 9, "TEN": 9,
    "CHI": 10, "DEN": 10, "PHI": 10, "TB": 10,
    "ATL": 11, "CLE": 11, "GB": 11, "LAR": 11, "NE": 11, "SEA": 11,
    "BAL": 13, "IND": 13, "LV": 13, "NYJ": 13,
    "ARI": 14, "DAL": 14,
}

# Alternate abbreviations some sources/sheets use, mapped to the
# canonical key above. Intentionally does NOT include ambiguous ones
# like a bare "LA" (could be Rams or Chargers) - better to show nothing
# than guess wrong.
TEAM_ALIASES = {
    "JAC": "JAX",
    "WSH": "WAS",
    "GNB": "GB",
    "KAN": "KC",
    "NWE": "NE",
    "NOR": "NO",
    "SFO": "SF",
    "TAM": "TB",
    "LVR": "LV",
    "OAK": "LV",   # legacy Raiders abbreviation, just in case
}


def bye_week_for_team(team: str | None) -> int | None:
    """Return the 2026 bye week for a team abbreviation, or None if unknown."""
    if not team:
        return None
    key = str(team).strip().upper()
    if not key:
        return None
    key = TEAM_ALIASES.get(key, key)
    return BYE_WEEK_BY_TEAM.get(key)