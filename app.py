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
# Page Configuration & Clean Styling
# ---------------------------------------------------------
st.set_page_config(
    page_title="Ric's Fantasy Football Command Center",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    /* Remove large top whitespace */
    .block-container {
        padding-top: 1.2rem !important;
        padding-bottom: 2rem !important;
        padding-left: 2.5rem !important;
        padding-right: 2.5rem !important;
    }
    header[data-testid="stHeader"] {
        height: 2rem !important;
        background: transparent !important;
    }
    h1 {
        margin-top: -0.8rem !important;
        padding-top: 0rem !important;
        font-size: 2rem !important;
    }

    /* Live Game & Status Cards */
    .matchup-card {
        border-radius: 8px;
        padding: 14px 18px;
        margin-bottom: 12px;
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

    /* T-Chart Roster Slot Styling */
    .roster-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 8px 12px;
        margin-bottom: 6px;
        background-color: #161B22;
        border: 1px solid #30363D;
        border-radius: 6px;
        min-height: 48px;
    }
    .pos-badge {
        font-weight: bold;
        font-size: 0.75rem;
        padding: 2px 6px;
        border-radius: 4px;
        background-color: #21262D;
        color: #58A6FF;
        border: 1px solid #30363D;
        margin-right: 8px;
    }
    .status-badge {
        font-size: 0.72rem;
        padding: 1px 6px;
        border-radius: 10px;
        font-weight: 600;
    }
    </style>
""",
    unsafe_allow_html=True,
)

# Persistent HTTP Session for fast connection reuse
@st.cache_resource
def get_http_session():
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=20)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

http = get_http_session()

# ---------------------------------------------------------
# Session State Initialization
# ---------------------------------------------------------
if "previous_scores" not in st.session_state:
    st.session_state.previous_scores = {}

if "live_feed" not in st.session_state:
    st.session_state.live_feed = []

if "score_history" not in st.session_state:
    st.session_state.score_history = defaultdict(list)


# ---------------------------------------------------------
# Configuration Loader
# ---------------------------------------------------------
@st.cache_data(ttl=60)
def load_config(config_path="config.yaml"):
    if not os.path.exists(config_path):
        return None
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


config = load_config()
if not config:
    st.error("config.yaml not found. Please place it in the root directory.")
    st.stop()


# ---------------------------------------------------------
# API Fetchers
# ---------------------------------------------------------
@st.cache_data(ttl=60)
def get_current_nfl_state():
    url = "https://api.sleeper.app/v1/state/nfl"
    try:
        resp = http.get(url, timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {"week": 1, "season_type": "regular", "season": "2026"}


@st.cache_data(ttl=86400)
def get_nfl_players():
    url = "https://api.sleeper.app/v1/players/nfl"
    try:
        resp = http.get(url, timeout=15)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {}


@st.cache_data(ttl=3600)
def get_user_id(username: str):
    url = f"https://api.sleeper.app/v1/user/{username.strip()}"
    try:
        resp = http.get(url, timeout=5)
        if resp.status_code == 200:
            return resp.json().get("user_id")
    except Exception:
        pass
    return None


@st.cache_data(ttl=600)
def get_roster_id(league_id: str, user_id: str):
    url = f"https://api.sleeper.app/v1/league/{league_id}/rosters"
    try:
        resp = http.get(url, timeout=5)
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


@st.cache_data(ttl=600)
def get_league_metadata(league_id: str):
    """Fetches custom team names and roster slot positions."""
    rosters_url = f"https://api.sleeper.app/v1/league/{league_id}/rosters"
    users_url = f"https://api.sleeper.app/v1/league/{league_id}/users"
    league_url = f"https://api.sleeper.app/v1/league/{league_id}"

    user_map = {}
    roster_map = {}
    roster_positions = []

    try:
        l_resp = http.get(league_url, timeout=5)
        if l_resp.status_code == 200:
            roster_positions = l_resp.json().get("roster_positions", [])

        u_resp = http.get(users_url, timeout=5)
        if u_resp.status_code == 200:
            for u in u_resp.json():
                uid = u.get("user_id")
                meta = u.get("metadata") or {}
                team_name = (
                    meta.get("team_name")
                    or u.get("display_name")
                    or u.get("username")
                )
                if uid and team_name:
                    user_map[uid] = team_name.strip()

        r_resp = http.get(rosters_url, timeout=5)
        if r_resp.status_code == 200:
            for r in r_resp.json():
                rid = r.get("roster_id")
                oid = r.get("owner_id")
                r_meta = r.get("metadata") or {}
                name = user_map.get(oid) or r_meta.get("team_name", f"Team {rid}")
                roster_map[rid] = name

        return roster_map, roster_positions
    except Exception:
        return {}, []


def get_league_matchups(league_id: str, week: int):
    """Zero-caching: strictly live points query on each poll."""
    url = f"https://api.sleeper.app/v1/league/{league_id}/matchups/{week}"
    try:
        resp = http.get(url, timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return []


def get_espn_nfl_scoreboard():
    """Zero-caching: strictly live ESPN scoreboard query on each poll."""
    url = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
    try:
        resp = http.get(url, timeout=5)
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

st.sidebar.title("Status and Controls")
st.sidebar.markdown(f"**NFL Season:** `{nfl_state.get('season', '')}` ({season_type})")
st.sidebar.markdown(f"**Detected Week:** `Week {api_detected_week}`")

current_week = st.sidebar.number_input(
    "Active Matchup Week", min_value=1, max_value=18, value=int(default_week)
)

refresh_interval = config.get("app", {}).get("refresh_interval_seconds", 15)
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
    st.warning("Please configure username and leagues in config.yaml.")
    st.stop()

all_players = get_nfl_players()
user_id = get_user_id(username)
if not user_id:
    st.error(f"Could not verify Sleeper user '{username}'.")
    st.stop()

espn_events = get_espn_nfl_scoreboard()

# Build map of NFL live game statuses
nfl_game_status = {}
for ev in espn_events:
    state = ev["status"]["type"]["state"]  # "pre", "in", "post"
    for comp in ev["competitions"][0]["competitors"]:
        abbr = normalize_team(comp["team"]["abbreviation"])
        nfl_game_status[abbr] = state

all_my_starters = []
league_summaries = []
current_time_str = datetime.datetime.now().strftime("%H:%M:%S")

for l_cfg in leagues_cfg:
    lid = str(l_cfg["id"]).strip()
    league_name = l_cfg.get("name", f"League {lid}")
    roster_id = get_roster_id(lid, user_id)

    if not roster_id:
        continue

    team_names, roster_positions = get_league_metadata(lid)
    my_team_name = team_names.get(roster_id, username)

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

    opp_roster_id = opp_matchup.get("roster_id") if opp_matchup else None
    opp_team_name = (
        team_names.get(opp_roster_id, f"Team {opp_roster_id}")
        if opp_roster_id
        else "No Opponent"
    )

    my_score = round(my_matchup.get("points", 0.0), 2)
    opp_score = round(opp_matchup.get("points", 0.0), 2) if opp_matchup else 0.0
    margin = round(my_score - opp_score, 2)

    # Record historical score point for line chart
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
                "opp_team_name": opp_team_name,
            }
        )

    league_summaries.append(
        {
            "league_id": lid,
            "league_name": league_name,
            "my_team_name": my_team_name,
            "opp_team_name": opp_team_name,
            "my_score": my_score,
            "opp_score": opp_score,
            "margin": margin,
            "my_matchup": my_matchup,
            "opp_matchup": opp_matchup,
            "roster_positions": roster_positions,
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
# Dynamic Top Matchup Cards
# ---------------------------------------------------------
st.title(f"Ric's Fantasy Football Command Center - Week {current_week}")

cols = st.columns(len(league_summaries) if league_summaries else 1)
for idx, summary in enumerate(league_summaries):
    margin = summary["margin"]
    is_winning = margin > 0
    is_tied = margin == 0

    if is_winning:
        status_text = "WINNING"
        accent_color = "#2EA043"  # Green
        badge_bg = "rgba(46, 160, 67, 0.18)"
        margin_sign = f"+{margin}"
    elif is_tied:
        status_text = "TIED"
        accent_color = "#D29922"  # Amber
        badge_bg = "rgba(210, 153, 34, 0.18)"
        margin_sign = "0.0"
    else:
        status_text = "LOSING"
        accent_color = "#F85149"  # Red
        badge_bg = "rgba(248, 81, 73, 0.18)"
        margin_sign = f"{margin}"

    with cols[idx]:
        st.markdown(
            f"""
            <div class="matchup-card" style="background-color: #161B22; border: 1px solid #30363D; border-left: 5px solid {accent_color};">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-weight: 600; font-size: 0.95rem; color: #8B949E;">{summary['league_name']}</span>
                    <span style="background-color: {badge_bg}; color: {accent_color}; font-weight: bold; font-size: 0.75rem; padding: 2px 8px; border-radius: 12px; border: 1px solid {accent_color};">
                        {status_text}
                    </span>
                </div>
                <div style="margin-top: 8px; display: flex; justify-content: space-between; align-items: baseline;">
                    <div>
                        <span style="font-size: 1.6rem; font-weight: bold; color: #F0F6FC;">{summary['my_score']}</span>
                        <span style="font-size: 0.85rem; color: #8B949E;">pts</span>
                    </div>
                    <div style="font-size: 0.95rem; font-weight: 600; color: {accent_color};">
                        {margin_sign} pts
                    </div>
                </div>
                <div style="margin-top: 6px; font-size: 0.82rem; color: #8B949E; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                    vs <strong style="color: #C9D1D9;">{summary['opp_team_name']}</strong> ({summary['opp_score']} pts)
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.divider()

# ---------------------------------------------------------
# Tabbed Navigation
# ---------------------------------------------------------
tab_live, tab_charts = st.tabs(["Live Dashboard", "Matchup T-Chart and Score History"])

# =========================================================
# TAB 1: LIVE DASHBOARD
# =========================================================
with tab_live:
    col_games, col_feed = st.columns([6, 5], gap="large")

    with col_games:
        st.subheader("What NFL Game to Watch")
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
                badge = "LIVE" if g["is_live"] else f"{g['status']}"
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
                            <strong>{g['my_players']}</strong> of your starters &nbsp;|&nbsp; 
                            <strong>{g['opp_players']}</strong> opponent starters
                        </div>
                    </div>
                """,
                    unsafe_allow_html=True,
                )

    with col_feed:
        st.subheader("Live Points Feed")
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
# TAB 2: T-CHART (FIRST) & POINTS OVER TIME (SECOND)
# =========================================================
with tab_charts:
    st.subheader("Matchup Starters and Score Progression")
    st.caption("Side-by-side roster T-Chart followed by live score curves")

    if not league_summaries:
        st.info("No active league matchups found.")
    else:
        league_tabs = st.tabs([s["league_name"] for s in league_summaries])

        def render_player_slot(slot_name, pid, points_map):
            """Helper function to render a styled player box for the T-Chart."""
            if not pid or pid == "0":
                return f"""
                <div class="roster-row" style="opacity: 0.5;">
                    <div><span class="pos-badge">{slot_name}</span> Empty</div>
                    <strong>0.00</strong>
                </div>
                """

            p_data = all_players.get(str(pid), {})
            p_name = p_data.get("full_name", f"Player {pid}")
            team = normalize_team(p_data.get("team", "FA"))
            pts = float(points_map.get(str(pid), 0.0))

            game_state = nfl_game_status.get(team, "pre")
            if game_state == "in":
                badge_html = '<span class="status-badge" style="background: rgba(248, 81, 73, 0.2); color: #F85149; border: 1px solid #F85149;">LIVE</span>'
            elif game_state == "post":
                badge_html = '<span class="status-badge" style="background: rgba(139, 148, 158, 0.2); color: #8B949E;">FINAL</span>'
            else:
                badge_html = '<span class="status-badge" style="background: rgba(56, 182, 255, 0.15); color: #38B6FF;">PRE</span>'

            return f"""
            <div class="roster-row">
                <div style="display: flex; align-items: center; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                    <span class="pos-badge">{slot_name}</span>
                    <span style="font-weight: 500; font-size: 0.92rem; color: #F0F6FC; margin-right: 6px;">{p_name}</span>
                    <span style="font-size: 0.78rem; color: #8B949E; margin-right: 6px;">{team}</span>
                    {badge_html}
                </div>
                <div style="font-weight: bold; font-size: 1rem; color: #F0F6FC; min-width: 45px; text-align: right;">
                    {pts:.2f}
                </div>
            </div>
            """

        for idx, summary in enumerate(league_summaries):
            lid = summary["league_id"]
            opp_name = summary["opp_team_name"]
            my_team_name = summary["my_team_name"]

            with league_tabs[idx]:
                league_history = st.session_state.score_history.get(lid, [])

                # Top Metrics
                m1, m2, m3 = st.columns(3)
                m1.metric(f"{my_team_name} (You)", f"{summary['my_score']} pts")
                m2.metric(f"{opp_name}", f"{summary['opp_score']} pts")
                m3.metric("Current Margin", f"{summary['margin']:+} pts")

                # 1. STARTERS BOX SCORE (T-CHART) - PLACED FIRST
                st.markdown("#### Starters Box Score (T-Chart)")

                my_matchup = summary["my_matchup"]
                opp_matchup = summary["opp_matchup"]

                my_starters_list = my_matchup.get("starters") or []
                opp_starters_list = (
                    opp_matchup.get("starters") if opp_matchup else []
                ) or []

                my_pts_map = my_matchup.get("players_points") or {}
                opp_pts_map = (
                    opp_matchup.get("players_points") if opp_matchup else {}
                ) or {}

                pos_slots = [
                    p for p in summary.get("roster_positions", []) if p != "BN"
                ]
                total_slots = max(
                    len(pos_slots),
                    len(my_starters_list),
                    len(opp_starters_list),
                )

                col_left, col_divider, col_right = st.columns([12, 1, 12])

                with col_left:
                    st.markdown(
                        f"""
                        <div style="border-bottom: 2px solid #38B6FF; padding-bottom: 6px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: baseline;">
                            <h4 style="margin: 0; color: #38B6FF;">{my_team_name} (You)</h4>
                            <span style="font-size: 1.1rem; font-weight: bold; color: #F0F6FC;">{summary['my_score']} pts</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                with col_right:
                    st.markdown(
                        f"""
                        <div style="border-bottom: 2px solid #F85149; padding-bottom: 6px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: baseline;">
                            <h4 style="margin: 0; color: #F85149;">{opp_name}</h4>
                            <span style="font-size: 1.1rem; font-weight: bold; color: #F0F6FC;">{summary['opp_score']} pts</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                with col_divider:
                    st.markdown(
                        """
                        <div style="height: 100%; border-left: 1px solid #30363D; margin: 0 auto; min-height: 400px;"></div>
                        """,
                        unsafe_allow_html=True,
                    )

                for slot_idx in range(total_slots):
                    slot_name = (
                        pos_slots[slot_idx]
                        if slot_idx < len(pos_slots)
                        else "FLEX"
                    )

                    my_pid = (
                        my_starters_list[slot_idx]
                        if slot_idx < len(my_starters_list)
                        else None
                    )
                    opp_pid = (
                        opp_starters_list[slot_idx]
                        if slot_idx < len(opp_starters_list)
                        else None
                    )

                    with col_left:
                        st.markdown(
                            render_player_slot(
                                slot_name, my_pid, my_pts_map
                            ),
                            unsafe_allow_html=True,
                        )

                    with col_right:
                        st.markdown(
                            render_player_slot(
                                slot_name, opp_pid, opp_pts_map
                            ),
                            unsafe_allow_html=True,
                        )

                st.divider()

                # 2. POINTS OVER TIME LINE CHART - PLACED SECOND
                st.markdown("#### Score Progression Over Time")
                if league_history:
                    df = pd.DataFrame(league_history)
                    fig = go.Figure()

                    fig.add_trace(
                        go.Scatter(
                            x=df["time"],
                            y=df["my_score"],
                            mode="lines+markers",
                            name=my_team_name,
                            line=dict(color="#38B6FF", width=3),
                            marker=dict(size=6),
                            hovertemplate=f"<b>{my_team_name}</b>: %{{y:.2f}} pts<br>Time: %{{x}}<extra></extra>",
                        )
                    )

                    fig.add_trace(
                        go.Scatter(
                            x=df["time"],
                            y=df["opp_score"],
                            mode="lines+markers",
                            name=opp_name,
                            line=dict(color="#F85149", width=2, dash="dash"),
                            marker=dict(size=6),
                            hovertemplate=f"<b>{opp_name}</b>: %{{y:.2f}} pts<br>Time: %{{x}}<extra></extra>",
                        )
                    )

                    fig.update_layout(
                        title=f"{summary['league_name']}: Cumulative Points",
                        template="plotly_dark",
                        height=360,
                        xaxis=dict(
                            title="Time",
                            showgrid=True,
                            gridcolor="rgba(255, 255, 255, 0.1)",
                        ),
                        yaxis=dict(
                            title="Fantasy Points",
                            side="right",
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
                        margin=dict(l=20, r=40, t=40, b=20),
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Collecting polling records to plot score lines...")