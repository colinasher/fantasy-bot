"""
Fantasy Draft PAR Dashboard
Run with: streamlit run app.py
"""

from datetime import timedelta

import pandas as pd
import streamlit as st

from bye_weeks import bye_week_for_team
from draft_sheet import (
    SHEET_URL,
    TEAM_COLUMNS,
    ROSTER_SLOTS,
    extract_drafted_cells,
    fetch_sheet_csv,
    get_team_names,
    match_drafted_player_ids,
    parse_roster_rows,
)
from draft_trends import compute_round_position_shares
from load_projections import load_all_projections
from par_calc import LeagueConfig, compute_par
from priority_pick import get_priority_pick
from scoring import score_players

st.set_page_config(page_title="Draft PAR Board", layout="wide")

POSITIONS = ["QB", "RB", "WR", "TE", "IDP"]
COLORS = {
    "QB": "#e63946",
    "RB": "#2a9d8f",
    "WR": "#457b9d",
    "TE": "#f4a261",
    "IDP": "#7b2cbf",
}

# ---------------- League settings (fixed - not changing mid-draft) ----------------
cfg = LeagueConfig(
    teams=10,
    qb_slots=2,
    rb_slots=2,
    wr_slots=3,
    te_slots=1,
    flex_slots=1,
    idp_slots=3,
)
teams = cfg.teams

# ---------------- Load projections (local CSVs) - moved up so the roster ----------------
# ---------------- section below can use scored_df right away ----------------


@st.cache_data
def load_data():
    return load_all_projections()


try:
    raw_df = load_data()
except FileNotFoundError as e:
    st.error(str(e))
    st.stop()

raw_df["position"] = raw_df["position"].str.upper().str.strip()
raw_df["position"] = raw_df["position"].replace(
    {"LB": "IDP", "DL": "IDP", "DB": "IDP", "DE": "IDP", "DT": "IDP", "CB": "IDP", "S": "IDP"}
)

scored_df = score_players(raw_df)

if "player_id" not in scored_df.columns:
    scored_df["player_id"] = (
        scored_df["name"].astype(str) + "_" + scored_df["position"].astype(str)
    )

# ---------------- Sidebar: team selector (needed for the roster below) ----------------


@st.cache_data(ttl=3600, show_spinner=False)
def cached_team_names():
    try:
        return get_team_names()
    except RuntimeError as e:
        st.sidebar.error(str(e))
        return []


team_names = cached_team_names()
if team_names:
    my_team = st.sidebar.selectbox("Your team", team_names)
    my_team_index = team_names.index(my_team)
else:
    my_team_index = None
    st.sidebar.warning("Couldn't read team names from the sheet header row.")


# ---------------- Sidebar: current roster (top of sidebar) ----------------
@st.fragment(run_every=timedelta(seconds=15))
def render_roster_sidebar():
    with st.sidebar:
        st.header("Current Roster")

        if my_team_index is None:
            st.caption("Select your team above to see your roster.")
            return

        try:
            csv_text = fetch_sheet_csv()
        except RuntimeError as e:
            st.caption(f"Couldn't read the sheet: {e}")
            return

        roster_by_slot = parse_roster_rows(csv_text)
        for slot in ROSTER_SLOTS:
            cell = ""
            if slot in roster_by_slot and my_team_index < len(roster_by_slot[slot]):
                cell = roster_by_slot[slot][my_team_index]

            if not cell:
                st.markdown(
                    "<div style='border-left:4px dashed #555;padding:4px 8px;"
                    "margin:3px 0;border-radius:3px;color:#888;'>"
                    f"<b>{slot}</b><br>"
                    "<span style='font-size:0.85em;'>Empty</span></div>",
                    unsafe_allow_html=True,
                )
                continue

            match_ids, _ = match_drafted_player_ids(scored_df, [cell])
            row = None
            if match_ids:
                pid = next(iter(match_ids))
                matched = scored_df[scored_df["player_id"] == pid]
                if len(matched):
                    row = matched.iloc[0]

            if row is None:
                st.markdown(
                    "<div style='border-left:4px solid #555;padding:4px 8px;"
                    "margin:3px 0;background-color:rgba(0,0,0,0.03);"
                    "border-radius:3px;'>"
                    f"<b>{slot}</b><br>"
                    f"<span style='font-size:0.85em;color:gray;'>{cell}</span></div>",
                    unsafe_allow_html=True,
                )
                continue

            color = COLORS.get(row["position"], "#555")
            if row["position"] == "IDP":
                rank_val = row.get("idp_rank")
                detail = f"Rank #{int(rank_val)}" if pd.notna(rank_val) else "Unranked"
            else:
                detail = f"{row['fantasy_points']:.1f} pts"

            bye = bye_week_for_team(row.get("team"))
            if bye is not None:
                detail += f" • Bye: {bye}"

            st.markdown(
                f"<div style='border-left:4px solid {color};padding:4px 8px;"
                f"margin:3px 0;background-color:rgba(0,0,0,0.03);"
                f"border-radius:3px;'>"
                f"<b>{slot}: {row['name']}</b><br>"
                f"<span style='font-size:0.85em;color:gray;'>{detail}</span></div>",
                unsafe_allow_html=True,
            )


render_roster_sidebar()

# ---------------- Sidebar: link + priority pick setup (below the roster) ----------------
st.sidebar.divider()
st.sidebar.markdown(f"[Open live draft sheet]({SHEET_URL})")
st.sidebar.caption(
    "Board polls the 2026 tab every 15 seconds and hides anyone "
    "already on a roster or in the pick grid."
)

st.sidebar.divider()
st.sidebar.subheader("Priority Pick")

load_trends = st.sidebar.button("Load historical draft trends")
if load_trends:
    st.session_state.pop("historical_shares", None)  # force recompute below

# ---------------- Historical draft trends (computed once, cached in session) ----------------
if "historical_shares" not in st.session_state:
    with st.spinner("Reading historical draft tabs (PLAYERS + past years)..."):
        try:
            st.session_state["historical_shares"] = compute_round_position_shares(scored_df)
        except RuntimeError as e:
            st.sidebar.error(f"Couldn't load historical trends: {e}")
            st.session_state["historical_shares"] = None

historical_shares = st.session_state.get("historical_shares")


@st.fragment(run_every=timedelta(seconds=15))
def render_board():
    try:
        csv_text = fetch_sheet_csv()
        drafted_cells = extract_drafted_cells(csv_text)
        drafted_ids, unmatched = match_drafted_player_ids(scored_df, drafted_cells)
    except RuntimeError as e:
        st.error(str(e))
        drafted_ids, unmatched, drafted_cells, csv_text = set(), [], [], ""

    pool = scored_df[~scored_df["player_id"].isin(drafted_ids)]
    pool, replacement_levels = compute_par(pool, cfg)

    active_positions = [p for p in POSITIONS if p in pool["position"].values]

    st.title("🏈 Draft Board — Points Above Replacement")

    # ---------------- Priority pick banner ----------------
    priority = None
    if historical_shares is not None and my_team_index is not None and csv_text:
        priority = get_priority_pick(
            pool, csv_text, historical_shares, teams, my_team_index
        )

    if priority:
        color = COLORS.get(priority["position"], "#333")
        st.markdown(
            f"<div style='background-color:{color}22;border:2px solid {color};"
            f"border-radius:10px;padding:14px 18px;margin-bottom:12px;'>"
            f"<div style='font-size:1.1em;font-weight:bold;color:{color};'>"
            f"⭐ Priority Pick: {priority['player']} ({priority['position']})</div>"
            f"<div style='margin-top:4px;'>{priority['reason']}</div>"
            f"<div style='margin-top:4px;font-size:0.85em;color:gray;'>"
            f"{priority['picks_until_next_turn']} picks until your next turn</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    elif my_team_index is None:
        st.info("Select your team in the sidebar to enable the priority pick recommendation.")
    elif historical_shares is None:
        st.info(
            "Historical draft trends aren't loaded yet — click "
            "'Load historical draft trends' in the sidebar."
        )

    with st.expander("Current replacement levels (recalculates as players are drafted)"):
        par_positions = [p for p in active_positions if p != "IDP"]
        if par_positions:
            rep_cols = st.columns(len(par_positions))
            for i, pos in enumerate(par_positions):
                rep_cols[i].metric(pos, f"{replacement_levels.get(pos, 0):.1f} pts")
        if "IDP" in active_positions:
            st.caption("IDP is hand-ranked, not PAR-scored - no replacement level shown.")

    st.caption(
        f"{len(drafted_cells)} names on the sheet • "
        f"{len(drafted_ids)} matched to projections • "
        f"{len(pool)} remaining • auto-refreshes every 15s"
    )

    if unmatched:
        with st.expander(f"{len(unmatched)} sheet names not in projections (IDP / mismatches)"):
            st.write(", ".join(unmatched))

    cols = st.columns(len(active_positions) or 1)

    priority_player = priority["player"] if priority else None
    priority_position = priority["position"] if priority else None

    for i, pos in enumerate(active_positions):
        color = COLORS[pos]
        with cols[i]:
            st.markdown(
                f"<div style='background-color:{color};padding:8px;border-radius:6px;"
                f"text-align:center;color:white;font-weight:bold;'>{pos}</div>",
                unsafe_allow_html=True,
            )
            if pos == "IDP":
                pos_df = pool[pool["position"] == pos].sort_values("idp_rank", ascending=True)
            else:
                pos_df = pool[pool["position"] == pos].sort_values("par", ascending=False)

            for _, row in pos_df.head(40).iterrows():
                is_priority = (
                    pos == priority_position and row["name"] == priority_player
                )
                border = f"4px solid {color}"
                extra_style = ""
                star = ""
                if is_priority:
                    border = "3px solid gold"
                    extra_style = "box-shadow:0 0 8px gold;"
                    star = "⭐ "

                if pos == "IDP":
                    rank_val = row.get("idp_rank")
                    detail = f"Rank #{int(rank_val)}" if pd.notna(rank_val) else "Unranked"
                else:
                    detail = f"{row['fantasy_points']:.1f} pts • PAR {row['par']:.1f}"

                bye = bye_week_for_team(row.get("team"))
                if bye is not None:
                    detail += f" • Bye: {bye}"

                st.markdown(
                    f"<div style='border-left:{border};padding:4px 8px;margin:3px 0;"
                    f"background-color:rgba(0,0,0,0.03);border-radius:3px;{extra_style}'>"
                    f"<b>{star}{row['name']}</b><br>"
                    f"<span style='font-size:0.85em;color:gray;'>{detail}</span></div>",
                    unsafe_allow_html=True,
                )


render_board()