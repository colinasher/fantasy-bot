"""
Fantasy Draft PAR Dashboard
Run with:  streamlit run app.py
"""

from datetime import timedelta

import streamlit as st

from draft_sheet import (
    SHEET_URL,
    extract_drafted_cells,
    fetch_sheet_csv,
    match_drafted_player_ids,
)
from load_projections import load_offensive_projections
from par_calc import LeagueConfig, compute_par
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

# ---------------- Sidebar: league settings ----------------
st.sidebar.header("League Settings")
teams = st.sidebar.number_input("Teams", value=10, min_value=2, max_value=20)
qb_slots = st.sidebar.number_input("QB slots/team", value=2, min_value=0)
rb_slots = st.sidebar.number_input("RB slots/team", value=2, min_value=0)
wr_slots = st.sidebar.number_input("WR slots/team", value=3, min_value=0)
te_slots = st.sidebar.number_input("TE slots/team", value=1, min_value=0)
flex_slots = st.sidebar.number_input("FLEX slots/team", value=1, min_value=0)
idp_slots = st.sidebar.number_input("IDP slots/team", value=3, min_value=0)

cfg = LeagueConfig(
    teams=teams,
    qb_slots=qb_slots,
    rb_slots=rb_slots,
    wr_slots=wr_slots,
    te_slots=te_slots,
    flex_slots=flex_slots,
    idp_slots=idp_slots,
)

st.sidebar.divider()
st.sidebar.markdown(f"[Open live draft sheet]({SHEET_URL})")
st.sidebar.caption(
    "Board polls the 2026 tab every 15 seconds and hides anyone "
    "already on a roster or in the pick grid."
)

# ---------------- Load projections (local CSVs) ----------------
@st.cache_data
def load_data():
    return load_offensive_projections()


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


@st.fragment(run_every=timedelta(seconds=15))
def render_board():
    try:
        csv_text = fetch_sheet_csv()
        drafted_cells = extract_drafted_cells(csv_text)
        drafted_ids, unmatched = match_drafted_player_ids(scored_df, drafted_cells)
    except RuntimeError as e:
        st.error(str(e))
        drafted_ids, unmatched, drafted_cells = set(), [], []

    pool = scored_df[~scored_df["player_id"].isin(drafted_ids)]
    pool, replacement_levels = compute_par(pool, cfg)
    active_positions = [p for p in POSITIONS if p in pool["position"].values]

    st.title("🏈 Draft Board — Points Above Replacement")

    with st.expander("Current replacement levels (recalculates as players are drafted)"):
        if active_positions:
            rep_cols = st.columns(len(active_positions))
            for i, pos in enumerate(active_positions):
                rep_cols[i].metric(pos, f"{replacement_levels.get(pos, 0):.1f} pts")

    st.caption(
        f"{len(drafted_cells)} names on the sheet • "
        f"{len(drafted_ids)} matched to projections • "
        f"{len(pool)} remaining • auto-refreshes every 15s"
    )
    if unmatched:
        with st.expander(f"{len(unmatched)} sheet names not in projections (IDP / mismatches)"):
            st.write(", ".join(unmatched))

    cols = st.columns(len(active_positions) or 1)
    for i, pos in enumerate(active_positions):
        color = COLORS[pos]
        with cols[i]:
            st.markdown(
                f"<div style='background-color:{color};padding:8px;border-radius:6px;"
                f"text-align:center;color:white;font-weight:bold;'>{pos}</div>",
                unsafe_allow_html=True,
            )
            pos_df = pool[pool["position"] == pos].sort_values("par", ascending=False)
            for _, row in pos_df.head(40).iterrows():
                st.markdown(
                    f"<div style='border-left:4px solid {color};padding:4px 8px;margin:3px 0;"
                    f"background-color:rgba(0,0,0,0.03);border-radius:3px;'>"
                    f"<b>{row['name']}</b><br>"
                    f"<span style='font-size:0.85em;color:gray;'>"
                    f"{row['fantasy_points']:.1f} pts • PAR {row['par']:.1f}</span></div>",
                    unsafe_allow_html=True,
                )


render_board()
