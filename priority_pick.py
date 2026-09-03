"""
priority_pick.py
Combines PAR with historical positional draft-pace to recommend a single
"priority pick" each turn: not just the highest-PAR player available, but
the position where waiting is riskiest given how fast that position
historically disappears before your next turn.

Logic:
  1. Read the authoritative pick order from the "Trades 2026" tab - this
     already reflects any traded picks, so no snake-order guessing is
     needed for anything it covers. Count how many picks have actually
     happened (from the live "2026" grid) to find where "now" is in that
     ordered list, then walk forward to find your next pick and every
     pick in between.
  2. If the Trades tab is unavailable entirely, fall back to a plain
     snake-order simulation (accurate only in the absence of trades).
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

from draft_sheet import parse_pick_order_tab, parse_round_cells, parse_round_picks
from draft_trends import POSITIONS, share_for_round

# IDP has no stat-based PAR (hand-rank only), so it never competes for
# the priority-pick recommendation - just QB/RB/WR/TE.
RANKED_POSITIONS = [p for p in POSITIONS if p != "IDP"]


# ---------------------------------------------------------------------------
# Primary: authoritative, trade-adjusted pick order (from the Trades tab)
# ---------------------------------------------------------------------------


def picks_until_my_turn_from_order(
    pick_order: list[tuple[int, str]],
    picks_completed: int,
    my_team_name: str,
    max_lookahead_picks: int = 80,
) -> list[int] | None:
    """
    Walks the authoritative pick order starting at the next undrafted
    pick. Returns the ROUND NUMBER of each pick before my team's next
    one - or None if my team was never found (the tab doesn't cover far
    enough ahead), so the caller can decide whether to fall back.
    """
    upcoming_rounds: list[int] = []
    idx = picks_completed
    steps = 0

    while idx < len(pick_order) and steps < max_lookahead_picks:
        rnd, team = pick_order[idx]
        if team == my_team_name:
            return upcoming_rounds
        upcoming_rounds.append(rnd)
        idx += 1
        steps += 1

    return None  # ran out of authoritative data before finding my team


# ---------------------------------------------------------------------------
# Fallback: plain snake simulation, used only if the Trades tab is
# unavailable or doesn't cover far enough ahead. Accurate only when no
# trades affect the picks it's simulating.
# ---------------------------------------------------------------------------


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
    next_round = max(round_cells.keys(), default=0) + 1
    return next_round, [False] * teams


def picks_until_my_turn_snake(
    round_cells: dict[int, list[str]],
    teams: int,
    my_team_index: int,
    max_lookahead_rounds: int = 6,
) -> list[int]:
    """Standard snake-order lookahead - does NOT account for traded picks."""
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
        flags = [False] * teams
    return upcoming_rounds


# ---------------------------------------------------------------------------
# Priority score computation (unchanged logic, just fed better input now)
# ---------------------------------------------------------------------------


def compute_priority_pick(pool_with_par, shares_by_round: dict, upcoming_rounds: list[int]):
    """
    pool_with_par: DataFrame with 'position', 'name', 'par' columns
                   (the current undrafted pool, already PAR-scored).
    shares_by_round: output of draft_trends.compute_round_position_shares
    upcoming_rounds: rounds of each pick before your next turn

    Returns None if the pool is empty, else a dict with the recommended
    position/player, the reasoning string, and the full per-position
    breakdown (so the UI can show runner-ups too).
    """
    K = len(upcoming_rounds)
    breakdown = {}

    for pos in RANKED_POSITIONS:
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
    trades_csv_text: str | None,
    shares_by_round: dict,
    teams: int,
    my_team_index: int | None,
    my_team_name: str | None,
):
    """
    Convenience wrapper: figures out how many picks stand between now and
    your next turn (trade-aware if the Trades tab is readable, else a
    plain snake-order estimate), and returns the priority pick
    recommendation - or None if we don't have enough info yet.
    """
    if my_team_index is None or my_team_name is None:
        return None

    round_picks = parse_round_picks(current_year_csv_text)
    picks_completed = sum(len(cells) for cells in round_picks.values())

    pick_order = parse_pick_order_tab(trades_csv_text) if trades_csv_text else []

    upcoming_rounds = None
    if pick_order:
        upcoming_rounds = picks_until_my_turn_from_order(
            pick_order, picks_completed, my_team_name
        )

    if upcoming_rounds is None:
        # Trades tab unavailable, empty, or didn't cover far enough ahead.
        round_cells = parse_round_cells(current_year_csv_text)
        upcoming_rounds = picks_until_my_turn_snake(round_cells, teams, my_team_index)

    return compute_priority_pick(scored_pool_with_par, shares_by_round, upcoming_rounds)