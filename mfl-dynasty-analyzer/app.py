from __future__ import annotations

import importlib

import pandas as pd
import plotly.express as px
import streamlit as st

import fantasypros
import roster_analysis

fantasypros = importlib.reload(fantasypros)
roster_analysis = importlib.reload(roster_analysis)

fantasypros_file_status = fantasypros.fantasypros_file_status
fantasypros_search_dirs = fantasypros.fantasypros_search_dirs
cutdown_projection = roster_analysis.cutdown_projection
league_franchises = roster_analysis.league_franchises
league_power_rankings = roster_analysis.league_power_rankings
protection_summary = roster_analysis.protection_summary
roster_dataframe = roster_analysis.roster_dataframe


POWER_SLOT_COLORS = {
    "QB": "#2563eb",
    "RB": "#dc2626",
    "WR": "#ea580c",
    "FLEX 1": "#14b8a6",
    "FLEX 2": "#0d9488",
    "FLEX 3": "#0f766e",
    "SUPERFLEX": "#f59e0b",
    "DL": "#7c3aed",
    "LB": "#16a34a",
    "DB": "#db2777",
}
POWER_SLOT_ORDER = ["QB", "RB", "WR", "FLEX 1", "FLEX 2", "FLEX 3", "SUPERFLEX", "DL", "LB", "DB"]


st.set_page_config(page_title="MFL Dynasty Analyzer", layout="wide")


@st.cache_data
def load_franchise_options() -> list[dict[str, str]]:
    return league_franchises()


@st.cache_data
def load_roster_frame(franchise_id: str) -> pd.DataFrame:
    return roster_dataframe(franchise_id=franchise_id)


st.title("MFL Dynasty Analyzer")

with st.sidebar:
    st.header("Team")
    franchises = load_franchise_options()
    if franchises:
        team_options = [{"id": "ALL", "name": "All teams", "label": "All teams"}] + franchises
        selected_franchise = st.selectbox(
            "League team",
            team_options,
            index=0,
            format_func=lambda franchise: franchise["label"],
        )
        franchise_id = selected_franchise["id"]
        selected_team_name = selected_franchise["name"]
        if franchise_id != "ALL":
            st.caption(f"Franchise {franchise_id}")
    else:
        franchise_id = st.text_input("Franchise ID", value="0002")
        selected_team_name = f"Franchise {franchise_id}"

    st.header("League Shape")
    protect_count = st.number_input("Protection slots", min_value=1, max_value=60, value=34)
    pool_mode = st.radio(
        "Expansion pool",
        ["All owned players", "Active roster only"],
        help="Use all owned players if IR players can be selected in the expansion draft.",
    )

st.caption(selected_team_name)

frame = load_roster_frame(franchise_id=franchise_id)
ranked = frame.sort_values("protection_value", ascending=False).copy()
selected_all_teams = franchise_id == "ALL"

if pool_mode == "Active roster only":
    eligible = ranked[ranked["active_roster"]].copy()
else:
    eligible = ranked.copy()

if selected_all_teams and "franchise_id" in eligible:
    protected_keys = set(
        eligible.sort_values(["franchise_id", "protection_value"], ascending=[True, False])
        .groupby("franchise_id", sort=False)
        .head(int(protect_count))["roster_key"]
    )
else:
    protected_keys = set(eligible.head(int(protect_count))["roster_key"])
ranked["protected"] = ranked["roster_key"].isin(protected_keys)

protected = ranked[ranked["protected"]]
exposed = ranked[~ranked["protected"]]

top_line = st.columns(5 if selected_all_teams else 4)
metric_index = 0
if selected_all_teams:
    top_line[metric_index].metric("Teams", ranked["franchise_id"].nunique())
    metric_index += 1
top_line[metric_index].metric("Owned Players", len(ranked))
top_line[metric_index + 1].metric("Protected", len(protected))
top_line[metric_index + 2].metric("Exposed", len(exposed))
top_line[metric_index + 3].metric("Active Roster", int(ranked["active_roster"].sum()))

team_columns = ["franchise_name"] if selected_all_teams else []
team_column_config = {"franchise_name": "Team"} if selected_all_teams else {}

league_frame = ranked if selected_all_teams else load_roster_frame(franchise_id="ALL")
power_frame = league_frame[league_frame["active_roster"]].copy() if pool_mode == "Active roster only" else league_frame.copy()
power_rankings, starter_breakdown, starter_detail = league_power_rankings(power_frame)
cutdown_frame, cutdown_summary = cutdown_projection(power_frame)
post_cut_frame = cutdown_frame[cutdown_frame["cutdown_protected"]].copy()
post_cut_rankings, post_cut_breakdown, post_cut_starter_detail = league_power_rankings(post_cut_frame)

tabs = st.tabs(
    [
        "Protection Board",
        "Position Mix",
        "FantasyPros Context",
        "MFL Scoring",
        "Exposed Players",
        "Raw Roster",
        "Power Rankings",
        "Cutdown Projection",
    ]
)

with tabs[0]:
    st.subheader("Recommended Protection Board")
    board = ranked[
        [
            "protected",
            "protect_rank",
            *team_columns,
            "name",
            "position",
            "position_group",
            "nfl_team",
            "status",
            "fp_primary_source",
            "fp_primary_rank",
            "fp_position_mismatch",
            "mfl_score_value",
            "mfl_score_latest",
            "protection_value",
            "dynasty_value",
            "drafted",
        ]
    ].copy()
    board["protection_value"] = board["protection_value"].round(1)
    board["dynasty_value"] = board["dynasty_value"].round(1)
    board["mfl_score_value"] = pd.to_numeric(board["mfl_score_value"], errors="coerce").round(1)
    board["mfl_score_latest"] = pd.to_numeric(board["mfl_score_latest"], errors="coerce").round(1)
    st.dataframe(
        board,
        hide_index=True,
        use_container_width=True,
        column_config={
            **team_column_config,
            "protected": st.column_config.CheckboxColumn("Protect"),
            "protect_rank": "Rank",
            "nfl_team": "NFL",
            "fp_primary_source": "FP Source",
            "fp_primary_rank": "FP Rank",
            "fp_position_mismatch": st.column_config.CheckboxColumn("FP Pos Mismatch"),
            "mfl_score_value": "MFL Prod Value",
            "mfl_score_latest": "Latest Pts",
            "protection_value": "Protect Value",
            "dynasty_value": "Base Value",
        },
    )

with tabs[1]:
    st.subheader("Protected Position Mix")
    summary = protection_summary(ranked, "protected")
    chart = px.bar(
        summary,
        x="position_group",
        y="protected",
        color="position_group",
        text="protected",
    )
    chart.update_layout(showlegend=False, xaxis_title="", yaxis_title="Players")
    st.plotly_chart(chart, use_container_width=True)

    st.dataframe(summary, hide_index=True, use_container_width=True)

with tabs[2]:
    st.subheader("FantasyPros Context")
    fantasypros_files = fantasypros_file_status()
    loaded_fantasypros_files = [status for status in fantasypros_files if status["loaded"]]
    missing_fantasypros_files = [status for status in fantasypros_files if not status["loaded"]]
    if not loaded_fantasypros_files:
        search_dirs = ", ".join(str(path) for path in fantasypros_search_dirs())
        expected_files = ", ".join(str(status["expected"]) for status in fantasypros_files)
        st.warning(f"No FantasyPros CSVs loaded. Looking in: {search_dirs}. Expected: {expected_files}.")
    elif missing_fantasypros_files:
        missing_files = ", ".join(str(status["expected"]) for status in missing_fantasypros_files)
        st.info(f"FantasyPros loaded partially. Missing: {missing_files}.")

    context_columns = [
        *team_columns,
        "name",
        "position",
        "nfl_team",
        "fp_matched",
        "fp_player_name",
        "fp_primary_source",
        "fp_primary_rank",
        "fp_market_value",
        "fp_overall_rank",
        "fp_overall_tier",
        "fp_superflex_pos",
        "fp_superflex_rank",
        "fp_superflex_tier",
        "fp_idp_pos",
        "fp_idp_rank",
        "fp_idp_tier",
        "fp_overall_pos",
        "fp_overall_age",
        "fp_overall_avg",
        "fp_superflex_age",
        "fp_superflex_avg",
        "fp_idp_age",
        "fp_idp_avg",
        "fp_position_mismatch",
    ]
    available_columns = [column for column in context_columns if column in ranked.columns]
    context = ranked[available_columns].copy()
    numeric_columns = [
        "fp_primary_rank",
        "fp_market_value",
        "fp_overall_rank",
        "fp_overall_tier",
        "fp_superflex_rank",
        "fp_superflex_tier",
        "fp_idp_rank",
        "fp_idp_tier",
        "fp_overall_age",
        "fp_overall_avg",
        "fp_superflex_age",
        "fp_superflex_avg",
        "fp_idp_age",
        "fp_idp_avg",
    ]
    for column in numeric_columns:
        if column in context:
            context[column] = pd.to_numeric(context[column], errors="coerce").round(1)
    if "fp_matched" in context and not bool(context["fp_matched"].any()) and loaded_fantasypros_files:
        st.warning("FantasyPros CSVs loaded, but no roster players matched. Check that the downloaded files include player names.")

    st.dataframe(
        context,
        hide_index=True,
        use_container_width="stretch",
        column_config={
            **team_column_config,
            "fp_matched": st.column_config.CheckboxColumn("Matched"),
            "fp_player_name": "FP Name",
            "fp_primary_source": "Source",
            "fp_primary_rank": "Primary Rank",
            "fp_market_value": "Market Value",
            "fp_overall_rank": "Overall Rank",
            "fp_overall_tier": "Overall Tier",
            "fp_superflex_pos": "SF Pos",
            "fp_superflex_rank": "SF Rank",
            "fp_superflex_tier": "SF Tier",
            "fp_idp_pos": "IDP Pos",
            "fp_idp_rank": "IDP Rank",
            "fp_idp_tier": "IDP Tier",
            "fp_overall_pos": "Overall Pos",
            "fp_overall_age": "Overall Age",
            "fp_overall_avg": "Overall Avg",
            "fp_superflex_age": "SF Age",
            "fp_superflex_avg": "SF Avg",
            "fp_idp_age": "IDP Age",
            "fp_idp_avg": "IDP Avg",
            "fp_position_mismatch": st.column_config.CheckboxColumn("Mismatch"),
        },
    )

with tabs[3]:
    st.subheader("MFL Scoring History")
    scoring_columns = [
        *team_columns,
        "name",
        "position",
        "nfl_team",
        "mfl_score_seasons",
        "mfl_score_latest_year",
        "mfl_score_latest",
        "mfl_score_avg3",
        "mfl_score_latest_percentile",
        "mfl_score_value",
        "mfl_score_trend",
    ]
    scoring = ranked[scoring_columns].copy()
    numeric_columns = [
        "mfl_score_latest",
        "mfl_score_avg3",
        "mfl_score_latest_percentile",
        "mfl_score_value",
        "mfl_score_trend",
    ]
    for column in numeric_columns:
        scoring[column] = pd.to_numeric(scoring[column], errors="coerce").round(1)

    scoring_matches = int(pd.to_numeric(scoring["mfl_score_seasons"], errors="coerce").fillna(0).gt(0).sum())
    st.metric("Players With Cached MFL Scoring", scoring_matches)
    st.dataframe(
        scoring,
        hide_index=True,
        use_container_width=True,
        column_config={
            **team_column_config,
            "mfl_score_seasons": "Seasons",
            "mfl_score_latest_year": "Latest Year",
            "mfl_score_latest": "Latest Pts",
            "mfl_score_avg3": "Avg Pts",
            "mfl_score_latest_percentile": "Latest Pos %",
            "mfl_score_value": "Production Value",
            "mfl_score_trend": "Trend",
        },
    )

with tabs[4]:
    st.subheader("Expansion Draft Exposure")
    exposed_view = exposed[
        [
            *team_columns,
            "name",
            "position",
            "position_group",
            "nfl_team",
            "status",
            "protection_value",
            "dynasty_value",
            "fp_primary_source",
            "fp_primary_rank",
            "mfl_score_value",
            "drafted",
        ]
    ].copy()
    exposed_view["protection_value"] = exposed_view["protection_value"].round(1)
    exposed_view["dynasty_value"] = exposed_view["dynasty_value"].round(1)
    exposed_view["mfl_score_value"] = pd.to_numeric(exposed_view["mfl_score_value"], errors="coerce").round(1)
    st.dataframe(exposed_view, hide_index=True, use_container_width=True)

with tabs[5]:
    st.subheader("Raw Roster")
    st.dataframe(ranked, hide_index=True, use_container_width=True)

with tabs[6]:
    st.subheader("League Power Rankings")
    if starter_breakdown.empty:
        st.info("No starter scores available.")
    else:
        team_order = power_rankings["franchise_name"].tolist()
        chart_data = starter_breakdown.copy()
        chart_data["score"] = pd.to_numeric(chart_data["score"], errors="coerce").round(1)
        power_chart = px.bar(
            chart_data,
            x="franchise_name",
            y="score",
            color="starter_bucket",
            category_orders={
                "franchise_name": team_order,
                "starter_bucket": POWER_SLOT_ORDER,
            },
            color_discrete_map=POWER_SLOT_COLORS,
            text="score",
        )
        power_chart.update_layout(
            barmode="stack",
            height=560,
            legend_title_text="Starter Slot",
            xaxis_title="",
            yaxis_title="Starter Score",
            margin={"l": 20, "r": 20, "t": 20, "b": 100},
        )
        power_chart.update_xaxes(tickangle=-30)
        power_chart.update_traces(
            texttemplate="%{y:.0f}",
            textposition="inside",
            textfont_size=10,
            hovertemplate="%{x}<br>%{fullData.name}: %{y:.1f}<extra></extra>",
        )
        st.plotly_chart(power_chart, use_container_width=True)

    leaderboard = power_rankings[
        [
            "power_rank",
            "franchise_name",
            "starter_score",
            "overall_score",
            "bench_score",
            "roster_size",
            "median_age",
            "fp_matches",
        ]
    ].copy()
    for column in ["starter_score", "overall_score", "bench_score", "median_age"]:
        leaderboard[column] = pd.to_numeric(leaderboard[column], errors="coerce").round(1)

    st.dataframe(
        leaderboard,
        hide_index=True,
        use_container_width=True,
        column_config={
            "power_rank": "Rank",
            "franchise_name": "Team",
            "starter_score": "Starter Score",
            "overall_score": "Overall Score",
            "bench_score": "Bench Score",
            "roster_size": "Roster",
            "median_age": "Median Age",
            "fp_matches": "FP Matches",
        },
    )

    st.subheader("Starter Lineups")
    starter_view = starter_detail[
        [
            "franchise_name",
            "starter_slot",
            "lineup_position",
            "position",
            "name",
            "nfl_team",
            "score",
            "fp_primary_source",
            "fp_primary_rank",
        ]
    ].copy()
    starter_view["score"] = pd.to_numeric(starter_view["score"], errors="coerce").round(1)
    starter_view["fp_primary_rank"] = pd.to_numeric(starter_view["fp_primary_rank"], errors="coerce").round(1)
    st.dataframe(
        starter_view,
        hide_index=True,
        use_container_width=True,
        column_config={
            "franchise_name": "Team",
            "starter_slot": "Slot",
            "lineup_position": "Lineup Pos",
            "position": "MFL Pos",
            "name": "Player",
            "nfl_team": "NFL",
            "score": "Score",
            "fp_primary_source": "FP Source",
            "fp_primary_rank": "FP Rank",
        },
    )

with tabs[7]:
    st.subheader("Cutdown Projection")

    pre_power = power_rankings[
        ["franchise_id", "power_rank", "starter_score", "overall_score"]
    ].rename(
        columns={
            "power_rank": "pre_power_rank",
            "starter_score": "pre_starter_score",
            "overall_score": "pre_overall_score",
        }
    )
    post_power = post_cut_rankings[
        ["franchise_id", "power_rank", "starter_score", "overall_score"]
    ].rename(
        columns={
            "power_rank": "post_power_rank",
            "starter_score": "post_starter_score",
            "overall_score": "post_overall_score",
        }
    )
    cutdown_view = (
        cutdown_summary.merge(pre_power, on="franchise_id", how="left")
        .merge(post_power, on="franchise_id", how="left")
        .sort_values(["post_power_rank", "lost_value"], ascending=[True, False])
    )
    cutdown_view["starter_score_lost"] = cutdown_view["pre_starter_score"] - cutdown_view["post_starter_score"]
    cutdown_view["overall_score_lost"] = cutdown_view["pre_overall_score"] - cutdown_view["post_overall_score"]

    lost_chart_data = cutdown_view.sort_values("lost_value", ascending=False).copy()
    lost_chart_data["lost_value"] = pd.to_numeric(lost_chart_data["lost_value"], errors="coerce").round(1)
    lost_chart = px.bar(
        lost_chart_data,
        x="franchise_name",
        y="lost_value",
        text="lost_value",
        color="lost_value",
        color_continuous_scale="Reds",
    )
    lost_chart.update_layout(
        height=420,
        showlegend=False,
        coloraxis_showscale=False,
        xaxis_title="",
        yaxis_title="Projected Value Lost",
        margin={"l": 20, "r": 20, "t": 20, "b": 90},
    )
    lost_chart.update_xaxes(tickangle=-30)
    lost_chart.update_traces(texttemplate="%{y:.0f}", textposition="outside")
    st.plotly_chart(lost_chart, use_container_width=True)

    summary_columns = [
        "post_power_rank",
        "pre_power_rank",
        "franchise_name",
        "roster_size",
        "protected_players",
        "protected_positions",
        "protected_kickers",
        "projected_cuts",
        "pre_starter_score",
        "post_starter_score",
        "starter_score_lost",
        "pre_overall_score",
        "post_overall_score",
        "overall_score_lost",
        "lost_value",
        "lost_value_pct",
    ]
    summary_table = cutdown_view[summary_columns].copy()
    for column in [
        "pre_starter_score",
        "post_starter_score",
        "starter_score_lost",
        "pre_overall_score",
        "post_overall_score",
        "overall_score_lost",
        "lost_value",
        "lost_value_pct",
    ]:
        summary_table[column] = pd.to_numeric(summary_table[column], errors="coerce").round(1)

    st.dataframe(
        summary_table,
        hide_index=True,
        use_container_width=True,
        column_config={
            "post_power_rank": "Post Rank",
            "pre_power_rank": "Pre Rank",
            "franchise_name": "Team",
            "roster_size": "Before",
            "protected_players": "Protected",
            "protected_positions": "Pos Protected",
            "protected_kickers": "K Protected",
            "projected_cuts": "Cuts",
            "pre_starter_score": "Pre Starter",
            "post_starter_score": "Post Starter",
            "starter_score_lost": "Starter Lost",
            "pre_overall_score": "Pre Overall",
            "post_overall_score": "Post Overall",
            "overall_score_lost": "Overall Lost",
            "lost_value": "Cut Value",
            "lost_value_pct": "Cut %",
        },
    )

    st.subheader("Post-Cut Power Rankings")
    if post_cut_breakdown.empty:
        st.info("No post-cut starter scores available.")
    else:
        post_team_order = post_cut_rankings["franchise_name"].tolist()
        post_chart_data = post_cut_breakdown.copy()
        post_chart_data["score"] = pd.to_numeric(post_chart_data["score"], errors="coerce").round(1)
        post_chart = px.bar(
            post_chart_data,
            x="franchise_name",
            y="score",
            color="starter_bucket",
            category_orders={
                "franchise_name": post_team_order,
                "starter_bucket": POWER_SLOT_ORDER,
            },
            color_discrete_map=POWER_SLOT_COLORS,
            text="score",
        )
        post_chart.update_layout(
            barmode="stack",
            height=520,
            legend_title_text="Starter Slot",
            xaxis_title="",
            yaxis_title="Post-Cut Starter Score",
            margin={"l": 20, "r": 20, "t": 20, "b": 90},
        )
        post_chart.update_xaxes(tickangle=-30)
        post_chart.update_traces(
            texttemplate="%{y:.0f}",
            textposition="inside",
            textfont_size=10,
            hovertemplate="%{x}<br>%{fullData.name}: %{y:.1f}<extra></extra>",
        )
        st.plotly_chart(post_chart, use_container_width=True)

    st.subheader("Projected Player Pool")
    player_pool = cutdown_frame[~cutdown_frame["cutdown_protected"]].sort_values(
        "protection_value",
        ascending=False,
    )
    pool_view = player_pool[
        [
            "franchise_name",
            "name",
            "position",
            "position_group",
            "nfl_team",
            "status",
            "protection_value",
            "dynasty_value",
            "fp_primary_source",
            "fp_primary_rank",
            "mfl_score_value",
            "drafted",
        ]
    ].copy()
    for column in ["protection_value", "dynasty_value", "fp_primary_rank", "mfl_score_value"]:
        pool_view[column] = pd.to_numeric(pool_view[column], errors="coerce").round(1)

    st.dataframe(
        pool_view,
        hide_index=True,
        use_container_width=True,
        column_config={
            "franchise_name": "Former Team",
            "name": "Player",
            "nfl_team": "NFL",
            "protection_value": "Projected Value",
            "dynasty_value": "Base Value",
            "fp_primary_source": "FP Source",
            "fp_primary_rank": "FP Rank",
            "mfl_score_value": "MFL Prod Value",
        },
    )

st.caption(
    "Current values are a first-pass dynasty heuristic. Next step: blend MFL scoring history, "
    "FantasyPros projections/rankings, and manually locked protection decisions."
)
