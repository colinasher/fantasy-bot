"""
priority_pick.py
Combines PAR with historical positional draft-pace to recommend a single
"priority pick" each turn: not just the highest-PAR player available, but
the position where waiting is riskiest given how fast that position
historically disappears before your next turn.

Logic:
  1. Figure out the current round and which team-columns still need to
     pick this round (from the live sheet's "Round N" grid).
  2. Simulate the snake order forward from there to find exactly how many
     picks happen - and in which rounds - before your team picks again.
  3. For each position, sum the historical round-shares over those
     upcoming picks -> "expected # of this position drafted before your
     next turn".
  4. drop_off = PAR(best available now) - PAR(the player you'd likely
     still get after that many are gone). This is the real cost of
     waiting, in PAR terms.
  5. priority_score = PAR(best available now) + drop_off. Highest score
     wins - a position only jumps ahead of raw PAR when waiting is
     genuinely expensive.
"""

from __future__ import annotations

from draft_sheet import parse_round_cells
from draft_trends import POSITIONS, share_for_round


def snake_order(round_num: int, teams: int) -> list[int]:
    """0-indexed team-column pick order for this round (standard snake)."""
    order = list(range(teams))
    if round_num % 2 == 0:
        order = list(reversed(order))
    return order


def find_current_round(round_cells: dict[int, list[str]], teams: int) -> tuple[int, list[bool]]:
    """
    Returns (round_in_progress, filled_flags) - the first round in the
    sheet that isn't completely filled yet. filled_flags[i] = whether
    team-column i already has a pick in that round.
    """
    for rnd in sorted(round_cells.keys()):
        cells = round_cells[rnd]
        filled = [bool(c) for c in cells[:teams]]
        if not all(filled):
            return rnd, filled
    # Every round present in the sheet is full - draft is ahead of what
    # we parsed (or hasn't started, in which case round_cells is empty).
    next_round = max(round_cells.keys(), default=0) + 1
    return next_round, [False] * teams


def picks_until_my_turn(
    round_cells: dict[int, list[str]],
    teams: int,
    my_team_index: int,
    max_lookahead_rounds: int = 6,
) -> list[int]:
    """
    Returns the ROUND NUMBER of each pick that happens strictly before
    my team's next pick, in chronological snake order. Length of the
    list = number of picks until my turn.
    """
    current_round, filled = find_current_round(round_cells, teams)
    upcoming_rounds: list[int] = []

    rnd = current_round
    flags = filled
    while rnd < current_round + max_lookahead_rounds:
        order = snake_order(rnd, teams)
        for team_idx in order:
            already_filled = flags[team_idx] if rnd == current_round else False
            if already_filled:
                continue
            if team_idx == my_team_index:
                return upcoming_rounds
            upcoming_rounds.append(rnd)
        rnd += 1
        flags = [False] * teams  # future rounds: nothing filled yet
    return upcoming_rounds


def compute_priority_pick(pool_with_par, shares_by_round: dict, upcoming_rounds: list[int]):
    """
    pool_with_par: DataFrame with 'position', 'name', 'par' columns
                   (the current undrafted pool, already PAR-scored).
    shares_by_round: output of draft_trends.compute_round_position_shares
    upcoming_rounds: output of picks_until_my_turn

    Returns None if the pool is empty, else a dict with the recommended
    position/player, the reasoning string, and the full per-position
    breakdown (so the UI can show runner-ups too).
    """
    K = len(upcoming_rounds)
    breakdown = {}

    for pos in POSITIONS:
        pos_pool = (
            pool_with_par[pool_with_par["position"] == pos]
            .sort_values("par", ascending=False)
            .reset_index(drop=True)
        )
        if len(pos_pool) == 0:
            continue

        expected_drafted = sum(
            share_for_round(shares_by_round, r).get(pos, 0.0) for r in upcoming_rounds
        )
        likely_index = min(round(expected_drafted), len(pos_pool) - 1)

        best_now = pos_pool.iloc[0]
        likely_later = pos_pool.iloc[likely_index]

        drop_off = round(float(best_now["par"] - likely_later["par"]), 2)
        priority_score = round(float(best_now["par"]) + drop_off, 2)

        breakdown[pos] = {
            "player": best_now["name"],
            "par": round(float(best_now["par"]), 2),
            "expected_drafted_before_next_turn": round(expected_drafted, 1),
            "drop_off": drop_off,
            "priority_score": priority_score,
        }

    if not breakdown:
        return None

    top_pos = max(breakdown, key=lambda p: breakdown[p]["priority_score"])
    rec = breakdown[top_pos]

    if rec["drop_off"] > 0.5:
        reason = (
            f"Best available {top_pos} has {rec['par']:.1f} PAR. Historically, "
            f"~{rec['expected_drafted_before_next_turn']:.1f} {top_pos}s get drafted "
            f"in the {K} pick{'s' if K != 1 else ''} before your next turn — waiting "
            f"would likely cost you about {rec['drop_off']:.1f} PAR at this position, "
            f"more than any other spot's risk."
        )
    else:
        reason = (
            f"Best available {top_pos} has {rec['par']:.1f} PAR, the highest on the "
            f"board right now, and this position isn't at much risk of a run before "
            f"your next turn ({rec['expected_drafted_before_next_turn']:.1f} expected)."
        )

    return {
        "position": top_pos,
        "player": rec["player"],
        "par": rec["par"],
        "priority_score": rec["priority_score"],
        "picks_until_next_turn": K,
        "reason": reason,
        "breakdown": breakdown,
    }


def get_priority_pick(
    scored_pool_with_par,
    current_year_csv_text: str,
    shares_by_round: dict,
    teams: int,
    my_team_index: int | None,
):
    """
    Convenience wrapper: parses the live '2026' tab csv already fetched
    by app.py (no extra network call), runs the snake-order lookahead,
    and returns the priority pick recommendation - or None if we don't
    have enough info (e.g. no team selected yet).
    """
    if my_team_index is None:
        return None
    round_cells = parse_round_cells(current_year_csv_text)
    upcoming_rounds = picks_until_my_turn(round_cells, teams, my_team_index)
    return compute_priority_pick(scored_pool_with_par, shares_by_round, upcoming_rounds)