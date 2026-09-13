import datetime
import os
from collections import defaultdict
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import yaml

# ---------------------------------------------------------
# Page Configuration & Styling
# ---------------------------------------------------------
st.set_page_config(
    page_title="Sleeper Live Command Center",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded",
)



st.markdown(
    """
    <style>
    /* 1. Remove the large default padding at the top of the app */
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 2rem !important;
        padding-left: 3rem !important;
        padding-right: 3rem !important;
    }

    /* 2. Collapse the top Streamlit header bar height */
    header[data-testid="stHeader"] {
        height: 2rem !important;
        background: transparent !important;
    }

    /* 3. Pull the main title up closer to the top edge */
    h1 {
        margin-top: -1rem !important;
        padding-top: 0rem !important;
    }

    /* Existing component styles */
    .metric-card {
        background-color: #1E222D;
        border-radius: 8px;
        padding: 12px 16px;
        border-left: 4px solid #38B6FF;
        margin-bottom: 10px;
    }
    .game-card {
        background-color: #161B22;
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 8px;
        border: 1px solid #30363D;
    }
    .feed-item {
        padding: 8px 12px;
        border-radius: 6px;
        margin-bottom: 6px;
        background-color: #0E1117;
        border-left: 3px solid #238636;
        font-size: 0.92rem;
    }
    .feed-item-negative {
        padding: 8px 12px;
        border-radius: 6px;
        margin-bottom: 6px;
        background-color: #0E1117;
        border-left: 3px solid #DA3633;
        font-size: 0.92rem;
    }
    </style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------
# Session State Initialization
# ---------------------------------------------------------
if "previous_scores" not in st.session_state:
    st.session_state.previous_scores = {}

if "live_feed" not in st.session_state:
    st.session_state.live_feed = []

# Tracks point progression: { league_id: [ {"time": str, "my_score": float, "opp_score": float, "margin": float} ] }
if "score_history" not in st.session_state:
    st.session_state.score_history = defaultdict(list)


# ---------------------------------------------------------
# Configuration Loader
# ---------------------------------------------------------
@st.cache_data(ttl=300)
def load_config(config_path="config.yaml"):
    if not os.path.exists(config_path):
        return None
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


config = load_config()
if not config:
    st.error("⚠️ `config.yaml` not found. Please place it in the root directory.")
    st.stop()


# ---------------------------------------------------------
# API Fetchers
# ---------------------------------------------------------
@st.cache_data(ttl=300)
def get_current_nfl_state():
    url = "https://api.sleeper.app/v1/state/nfl"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {"week": 1, "season_type": "regular", "season": "2026"}


@st.cache_data(ttl=86400)
def get_nfl_players():
    url = "https://api.sleeper.app/v1/players/nfl"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {}


@st.cache_data(ttl=3600)
def get_user_id(username: str):
    url = f"https://api.sleeper.app/v1/user/{username.strip()}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("user_id")
    except Exception:
        pass
    return None


@st.cache_data(ttl=3600)
def get_roster_id(league_id: str, user_id: str):
    url = f"https://api.sleeper.app/v1/league/{league_id}/rosters"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            rosters = resp.json()
            for r in rosters:
                if r.get("owner_id") == user_id or user_id in (
                    r.get("co_owners") or []
                ):
                    return r.get("roster_id")
    except Exception:
        pass
    return None


def get_league_matchups(league_id: str, week: int):
    url = f"https://api.sleeper.app/v1/league/{league_id}/matchups/{week}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return []


def get_espn_nfl_scoreboard():
    url = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("events", [])
    except Exception:
        pass
    return []


TEAM_REMAP = {"JAX": "JAC", "WSH": "WAS"}


def normalize_team(abbr):
    if not abbr:
        return ""
    return TEAM_REMAP.get(abbr.upper(), abbr.upper())


# ---------------------------------------------------------
# Sidebar Controls
# ---------------------------------------------------------
nfl_state = get_current_nfl_state()
api_detected_week = max(1, nfl_state.get("week", 1))
season_type = nfl_state.get("season_type", "regular").upper()

configured_override = config.get("app", {}).get("manual_week_override")
default_week = (
    configured_override
    if (
        configured_override and not config.get("app", {}).get("auto_detect_week")
    )
    else api_detected_week
)

st.sidebar.title("🏈 Status & Controls")
st.sidebar.markdown(
    f"**NFL Season:** `{nfl_state.get('season', '')}` ({season_type})"
)
st.sidebar.markdown(f"**Detected Week:** `Week {api_detected_week}`")

current_week = st.sidebar.number_input(
    "Active Matchup Week", min_value=1, max_value=18, value=int(default_week)
)

refresh_interval = config.get("app", {}).get("refresh_interval_seconds", 20)
enable_polling = st.sidebar.checkbox("Enable Live Polling", value=True)

if enable_polling:
    st_autorefresh(interval=refresh_interval * 1000, key="sleeper_poll")

if st.sidebar.button("Clear Point History & Feeds"):
    st.session_state.live_feed = []
    st.session_state.previous_scores = {}
    st.session_state.score_history = defaultdict(list)
    st.rerun()

# ---------------------------------------------------------
# Data Pipeline
# ---------------------------------------------------------
username = config.get("sleeper", {}).get("username")
leagues_cfg = config.get("sleeper", {}).get("leagues", [])

if not username or not leagues_cfg:
    st.warning("Please configure `username` and leagues in `config.yaml`.")
    st.stop()

all_players = get_nfl_players()
user_id = get_user_id(username)
if not user_id:
    st.error(f"Could not verify Sleeper user '{username}'.")
    st.stop()

all_my_starters = []
league_summaries = []
current_time_str = datetime.datetime.now().strftime("%H:%M:%S")

for l_cfg in leagues_cfg:
    lid = str(l_cfg["id"]).strip()
    league_name = l_cfg.get("name", f"League {lid}")
    roster_id = get_roster_id(lid, user_id)

    if not roster_id:
        continue

    matchups = get_league_matchups(lid, current_week)
    if not matchups:
        continue

    my_matchup = next((m for m in matchups if m["roster_id"] == roster_id), None)
    if not my_matchup:
        continue

    matchup_id = my_matchup.get("matchup_id")
    opp_matchup = next(
        (
            m
            for m in matchups
            if m.get("matchup_id") == matchup_id and m["roster_id"] != roster_id
        ),
        None,
    )

    my_score = round(my_matchup.get("points", 0.0), 2)
    opp_score = round(opp_matchup.get("points", 0.0), 2) if opp_matchup else 0.0
    margin = round(my_score - opp_score, 2)

    # Record historical score point for line chart (only on change or first entry)
    history = st.session_state.score_history[lid]
    if (
        not history
        or history[-1]["my_score"] != my_score
        or history[-1]["opp_score"] != opp_score
    ):
        history.append(
            {
                "time": current_time_str,
                "my_score": my_score,
                "opp_score": opp_score,
                "margin": margin,
                "league_name": league_name,
            }
        )

    league_summaries.append(
        {
            "league_id": lid,
            "league_name": league_name,
            "my_score": my_score,
            "opp_score": opp_score,
            "margin": margin,
        }
    )

    # Active starters and scoring delta tracking
    my_starters = [
        pid for pid in (my_matchup.get("starters") or []) if pid and pid != "0"
    ]
    for pid in my_starters:
        all_my_starters.append(
            {"player_id": pid, "league": league_name, "is_opponent": False}
        )

        current_pts = float(my_matchup.get("players_points", {}).get(pid, 0.0))
        score_key = f"{lid}_{pid}"

        if score_key in st.session_state.previous_scores:
            delta = round(
                current_pts - st.session_state.previous_scores[score_key], 2
            )
            if abs(delta) >= 0.1:
                p_meta = all_players.get(pid, {})
                name = p_meta.get("full_name", f"Player {pid}")
                team = p_meta.get("team", "FA")
                st.session_state.live_feed.insert(
                    0,
                    {
                        "time": current_time_str,
                        "player": f"{name} ({team})",
                        "delta": delta,
                        "total": current_pts,
                        "league": league_name,
                    },
                )
        st.session_state.previous_scores[score_key] = current_pts

    if opp_matchup:
        opp_starters = [
            pid
            for pid in (opp_matchup.get("starters") or [])
            if pid and pid != "0"
        ]
        for pid in opp_starters:
            all_my_starters.append(
                {"player_id": pid, "league": league_name, "is_opponent": True}
            )

# ---------------------------------------------------------
# Top Summary Metrics
# ---------------------------------------------------------
st.title(f"🏈 Sleeper Command Center — Week {current_week}")

cols = st.columns(len(league_summaries) if league_summaries else 1)
for idx, summary in enumerate(league_summaries):
    with cols[idx]:
        delta_color = "normal" if summary["margin"] >= 0 else "inverse"
        st.metric(
            label=summary["league_name"],
            value=f"{summary['my_score']} pts",
            delta=f"{summary['margin']:+} vs Opp ({summary['opp_score']} pts)",
            delta_color=delta_color,
        )

st.divider()

# ---------------------------------------------------------
# Tabbed Navigation
# ---------------------------------------------------------
tab_live, tab_charts = st.tabs(["🔴 Live Dashboard", "📈 Matchup Points Over Time"])

# =========================================================
# TAB 1: LIVE DASHBOARD
# =========================================================
with tab_live:
    col_games, col_feed = st.columns([6, 5], gap="large")

    with col_games:
        st.subheader("📺 What NFL Game to Watch")
        st.caption("Ranked by active fantasy starters across your matchups")

        espn_events = get_espn_nfl_scoreboard()
        my_team_counts = defaultdict(int)
        opp_team_counts = defaultdict(int)

        for item in all_my_starters:
            pid = item["player_id"]
            team_abbr = normalize_team(all_players.get(pid, {}).get("team"))
            if team_abbr:
                if item["is_opponent"]:
                    opp_team_counts[team_abbr] += 1
                else:
                    my_team_counts[team_abbr] += 1

        ranked_games = []
        for ev in espn_events:
            status_state = ev["status"]["type"]["state"]
            clock_detail = ev["status"]["type"].get(
                "shortDetail", ev["status"]["type"].get("detail", "")
            )
            competitors = ev["competitions"][0]["competitors"]
            home = competitors[0]
            away = competitors[1]

            home_abbr = normalize_team(home["team"]["abbreviation"])
            away_abbr = normalize_team(away["team"]["abbreviation"])

            my_players_here = (
                my_team_counts[home_abbr] + my_team_counts[away_abbr]
            )
            opp_players_here = (
                opp_team_counts[home_abbr] + opp_team_counts[away_abbr]
            )

            state_weight = (
                2
                if status_state == "in"
                else (1 if status_state == "pre" else 0)
            )

            ranked_games.append(
                {
                    "matchup": f"{away_abbr} {away.get('score', '')} @ {home_abbr} {home.get('score', '')}",
                    "status": clock_detail,
                    "is_live": status_state == "in",
                    "state_weight": state_weight,
                    "my_players": my_players_here,
                    "opp_players": opp_players_here,
                    "total_players": my_players_here + opp_players_here,
                }
            )

        ranked_games.sort(
            key=lambda x: (
                x["state_weight"],
                x["my_players"],
                x["total_players"],
            ),
            reverse=True,
        )

        if not ranked_games:
            st.write("No active NFL games on the scoreboard.")
        else:
            for idx, g in enumerate(ranked_games):
                badge = "🔴 LIVE" if g["is_live"] else f"⏱ {g['status']}"
                priority_color = (
                    "#38B6FF" if g["my_players"] > 0 else "#8B949E"
                )

                st.markdown(
                    f"""
                    <div class="game-card" style="border-left: 5px solid {priority_color};">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <strong style="font-size: 1.1rem;">#{idx+1} {g['matchup']}</strong>
                            <span style="font-size: 0.85rem; font-weight: bold;">{badge}</span>
                        </div>
                        <div style="margin-top: 6px; font-size: 0.9rem; color: #C9D1D9;">
                            ⭐ <strong>{g['my_players']}</strong> of your starters &nbsp;|&nbsp; 
                            ⚠️ <strong>{g['opp_players']}</strong> opponent starters
                        </div>
                    </div>
                """,
                    unsafe_allow_html=True,
                )

    with col_feed:
        st.subheader("⚡ Live Points Feed")
        st.caption("Point deltas detected across your active rosters")

        if not st.session_state.live_feed:
            st.markdown(
                """
                <div style="padding: 24px; text-align: center; color: #8B949E; border: 1px dashed #30363D; border-radius: 8px;">
                    Watching for scoring events... Points updates will stream in as games progress.
                </div>
            """,
                unsafe_allow_html=True,
            )
        else:
            for item in st.session_state.live_feed[:15]:
                is_pos = item["delta"] >= 0
                card_class = "feed-item" if is_pos else "feed-item-negative"
                delta_str = f"+{item['delta']}" if is_pos else f"{item['delta']}"

                st.markdown(
                    f"""
                    <div class="{card_class}">
                        <div style="display: flex; justify-content: space-between;">
                            <strong>{item['player']}</strong>
                            <span style="font-weight: bold; color: {'#3FB950' if is_pos else '#F85149'};">{delta_str} pts</span>
                        </div>
                        <div style="font-size: 0.8rem; color: #8B949E; margin-top: 2px;">
                            {item['league']} &bull; Total: {item['total']} pts &bull; <em>{item['time']}</em>
                        </div>
                    </div>
                """,
                    unsafe_allow_html=True,
                )

# =========================================================
# TAB 2: POINTS OVER TIME LINE CHARTS
# =========================================================
with tab_charts:
    st.subheader("📈 Matchup Scoring Progression Over Time")
    st.caption(
        "Live cumulative score curves for both teams (Y-axis positioned on the right)"
    )

    if not league_summaries:
        st.info("No active league matchups found.")
    else:
        league_tabs = st.tabs([s["league_name"] for s in league_summaries])

        for idx, summary in enumerate(league_summaries):
            lid = summary["league_id"]
            with league_tabs[idx]:
                league_history = st.session_state.score_history.get(lid, [])

                if not league_history:
                    st.info("Collecting polling records to plot score lines...")
                    continue

                df = pd.DataFrame(league_history)

                # Metric highlight row
                m1, m2, m3 = st.columns(3)
                m1.metric("Your Current Score", f"{summary['my_score']} pts")
                m2.metric("Opponent Score", f"{summary['opp_score']} pts")
                m3.metric("Current Margin", f"{summary['margin']:+} pts")

                # Build line chart for both teams
                fig = go.Figure()

                # User's Team Score Line
                fig.add_trace(
                    go.Scatter(
                        x=df["time"],
                        y=df["my_score"],
                        mode="lines+markers",
                        name="My Team",
                        line=dict(color="#38B6FF", width=3),
                        marker=dict(size=6),
                        hovertemplate="<b>My Team</b>: %{y:.2f} pts<br>Time: %{x}<extra></extra>",
                    )
                )

                # Opponent's Team Score Line
                fig.add_trace(
                    go.Scatter(
                        x=df["time"],
                        y=df["opp_score"],
                        mode="lines+markers",
                        name="Opponent",
                        line=dict(color="#F85149", width=2, dash="dash"),
                        marker=dict(size=6),
                        hovertemplate="<b>Opponent</b>: %{y:.2f} pts<br>Time: %{x}<extra></extra>",
                    )
                )

                # Layout: points on the right Y-axis, time along the X-axis
                fig.update_layout(
                    title=f"{summary['league_name']} — Live Score Progression",
                    template="plotly_dark",
                    height=420,
                    xaxis=dict(
                        title="Time",
                        showgrid=True,
                        gridcolor="rgba(255, 255, 255, 0.1)",
                    ),
                    yaxis=dict(
                        title="Fantasy Points",
                        side="right",  # Points on the right side
                        showgrid=True,
                        gridcolor="rgba(255, 255, 255, 0.1)",
                    ),
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="right",
                        x=1,
                    ),
                    margin=dict(l=20, r=40, t=50, b=30),
                )

                st.plotly_chart(fig, use_container_width=True)