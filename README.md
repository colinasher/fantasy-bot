# Draft PAR Dashboard

A live draft-day tool: ranks available players by **Points Above Replacement
(PAR)** in 5 color-coded columns (QB / RB / WR / TE / IDP), and recalculates
replacement levels automatically as players get drafted.

## Setup

```bash
pip install -r requirements.txt
streamlit run app.py
```

This opens a browser tab (usually `http://localhost:8501`) — keep it open on
a laptop/tablet during the draft.

## Using it during the draft

- Left sidebar: confirm league settings (defaults match your league: 10
  teams, 2 QB / 2 RB / 3 WR / 1 TE / 1 FLEX / 3 IDP).
- Projections load from the FantasyPros CSV exports in this folder
  (`FantasyPros_Fantasy_Football_Projections_{QB,RB,WR,TE}.csv`). Raw
  stats are re-scored with this league's settings (FPTS in the files is
  ignored). Drop in an IDP CSV later if you want that column populated.
- The board reads the live [2026 draft sheet](https://docs.google.com/spreadsheets/d/1RrqFIRwu8W11rWkOyNWUM4k0u5Dzc0qNe6eS1k6EV_0/edit#gid=290495943)
  every 15 seconds. Anyone already in the pick grid or a roster slot
  (`J. Chase (CIN)` format) is removed from the available pool and PAR
  recalculates automatically.

## CSV format

One row per player. Required columns: `name`, `position`.
Position should be `QB`, `RB`, `WR`, `TE`, or an IDP-type label
(`IDP`, `LB`, `DL`, `DB`, `DE`, `DT`, `CB`, `S` — all get treated as
generic IDP, matching your league's rules).

Stat columns (include whichever apply to the player; missing = 0):

| Column | Used for | League scoring |
|---|---|---|
| `pass_yds` | QB | 0.04/yd |
| `pass_td` | QB | 4/TD |
| `rush_yds` | RB/QB/WR | 0.1/yd |
| `rush_td` | RB/QB/WR | 6/TD |
| `rec` | RB/WR/TE | 0.5/rec |
| `rec_yds` | RB/WR/TE | 0.1/yd |
| `rec_td` | RB/WR/TE | 6/TD |
| `tackles_solo` | IDP | 1/tackle |
| `tackles_ast` | IDP | 1/tackle |
| `sacks` | IDP | 3/sack (fractional ok, e.g. 0.5) |
| `tfl` | IDP | 0.5/TFL (fractional ok) |
| `int` | IDP | 4/INT |
| `fum_rec` | IDP | 1/fumble recovery |
| `forced_fum` | IDP | 2/forced fumble |
| `def_td` | IDP | 6/TD |

**Important:** use raw projected stat lines, not pre-scored fantasy points
from another site's scoring system — the whole point of this tool is
applying *your* league's exact scoring, especially for IDP where your
league's weighting (heavier on LBs) differs a lot from generic defaults.

## How PAR is calculated

See `par_calc.py` for the full logic. Summary:

- **QB**: replacement level = the 21st-best QB (2 starters × 10 teams + 1),
  since QB doesn't compete for FLEX in your league.
- **RB / WR / TE**: these three positions share your 10 FLEX spots. The
  tool ranks all RB/WR/TE, assigns dedicated starter slots first (20 RB,
  30 WR, 10 TE), then lets the 10 FLEX spots go to whichever leftover
  players (any of the three positions) have the most points — exactly
  like a real draft would naturally allocate value. Replacement level per
  position is set at the first player of that position who didn't make
  the cut.
- **IDP**: single generic pool, replacement level = the 31st-best IDP
  (3 starters × 10 teams + 1), scored under your LB-favoring settings.

## Next steps / ideas

- If you want this synced across multiple people's screens during the
  draft (rather than one laptop), that would need a small hosted backend —
  let your dashboard builder (me!) know if you want that next.
