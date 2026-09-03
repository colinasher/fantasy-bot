"""
par_calc.py
Computes replacement level and Points Above Replacement (PAR) for each
position.

Replacement level = fantasy points of the first player at a position who
would NOT be a starter anywhere in the league, given:
  - dedicated starting slots per position
  - a shared FLEX pool (RB/WR/TE compete for FLEX_SLOTS spots)
  - IDP is a single generic pool (LB-heavy scoring already baked into points)

Replacement level is meant to be computed ONCE from the full initial
player pool (before any draft picks happen) and then held fixed for the
rest of the draft - see apply_fixed_par. Recomputing it from the
shrinking undrafted pool would make "replacement level" drift as players
get drafted (e.g. the "21st best QB" baseline would silently become the
21st best QB *remaining*, not the original 21st), which isn't what
replacement level is supposed to mean.
"""

import pandas as pd


class LeagueConfig:
    def __init__(
        self,
        teams=10,
        qb_slots=2,
        rb_slots=2,
        wr_slots=3,
        te_slots=1,
        flex_slots=1,
        idp_slots=3,
        flex_eligible=("RB", "WR", "TE"),
    ):
        self.teams = teams
        self.qb_slots = qb_slots
        self.rb_slots = rb_slots
        self.wr_slots = wr_slots
        self.te_slots = te_slots
        self.flex_slots = flex_slots
        self.idp_slots = idp_slots
        self.flex_eligible = set(flex_eligible)

    @property
    def qb_starters(self):
        return self.qb_slots * self.teams

    @property
    def rb_dedicated(self):
        return self.rb_slots * self.teams

    @property
    def wr_dedicated(self):
        return self.wr_slots * self.teams

    @property
    def te_dedicated(self):
        return self.te_slots * self.teams

    @property
    def flex_total(self):
        return self.flex_slots * self.teams

    @property
    def idp_starters(self):
        return self.idp_slots * self.teams


def _dedicated_cutoff(cfg: LeagueConfig, pos: str) -> int:
    return {
        "RB": cfg.rb_dedicated,
        "WR": cfg.wr_dedicated,
        "TE": cfg.te_dedicated,
    }[pos]


def compute_replacement_levels(pool: pd.DataFrame, cfg: LeagueConfig) -> dict:
    """
    pool: DataFrame of currently UNDRAFTED players with 'position' and
          'fantasy_points' columns.
    Returns: dict {position: replacement_points}
    """
    replacement = {}

    # --- QB: no flex competition ---
    qb = pool[pool["position"] == "QB"].sort_values("fantasy_points", ascending=False)
    replacement["QB"] = _nth_points(qb, cfg.qb_starters)

    # --- IDP: single generic pool ---
    idp = pool[pool["position"] == "IDP"].sort_values("fantasy_points", ascending=False)
    replacement["IDP"] = _nth_points(idp, cfg.idp_starters)

    # --- RB / WR / TE: shared flex pool ---
    flex_positions = [p for p in ("RB", "WR", "TE") if p in cfg.flex_eligible]
    starter_ids = set()

    leftover_by_pos = {}
    for pos in flex_positions:
        sub = pool[pool["position"] == pos].sort_values("fantasy_points", ascending=False)
        cutoff = _dedicated_cutoff(cfg, pos)
        dedicated_starters = sub.iloc[:cutoff]
        starter_ids.update(dedicated_starters.index)
        leftover_by_pos[pos] = sub.iloc[cutoff:]

    # Combine leftovers into one flex pool, ranked by points
    leftover_all = pd.concat(leftover_by_pos.values()).sort_values(
        "fantasy_points", ascending=False
    )
    flex_starters = leftover_all.iloc[: cfg.flex_total]
    starter_ids.update(flex_starters.index)

    # Replacement level per position = next-best player at that position
    # not included in starter_ids
    for pos in flex_positions:
        sub = pool[pool["position"] == pos].sort_values("fantasy_points", ascending=False)
        non_starters = sub[~sub.index.isin(starter_ids)]
        replacement[pos] = _nth_points(non_starters, 1)

    return replacement


def _nth_points(sorted_df: pd.DataFrame, n: int) -> float:
    """
    Points of the (n+1)-th ranked player (i.e. the first player OUTSIDE
    the top n = the replacement player), or the last available player's
    points if the pool is shallower than n (edge case late in draft).
    """
    if len(sorted_df) == 0:
        return 0.0
    if n < len(sorted_df):
        return float(sorted_df.iloc[n]["fantasy_points"])
    return float(sorted_df.iloc[-1]["fantasy_points"])


def compute_par(pool: pd.DataFrame, cfg: LeagueConfig) -> pd.DataFrame:
    """
    Adds 'replacement_points' and 'par' columns to the pool of undrafted
    players, recalculating replacement level from THIS pool. Kept for
    convenience/testing, but app.py should prefer apply_fixed_par so
    replacement level (and therefore PAR) stays anchored to the original
    full player pool rather than drifting as players get drafted.
    """
    pool = pool.copy()
    replacement_levels = compute_replacement_levels(pool, cfg)
    return apply_fixed_par(pool, replacement_levels), replacement_levels


def apply_fixed_par(pool: pd.DataFrame, fixed_replacement_levels: dict) -> pd.DataFrame:
    """
    Adds 'replacement_points' and 'par' columns using a FIXED replacement
    baseline (computed once, typically from the full initial pool before
    any picks are made) rather than recalculating it from `pool`. This
    keeps each remaining player's PAR anchored to the original "21st
    best QB" style baseline all draft long - only which players still
    appear changes, not the yardstick they're measured against.
    """
    pool = pool.copy()
    pool["replacement_points"] = pool["position"].map(fixed_replacement_levels)
    pool["par"] = (pool["fantasy_points"] - pool["replacement_points"]).round(2)
    return pool