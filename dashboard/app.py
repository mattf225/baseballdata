"""
B.L.A.S.T. Monitoring Dashboard
---------------------------------
Run with:
    streamlit run dashboard/app.py

Requires:
    - SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env
    - migrate_add_outcome.sql applied to Supabase
    - backfill_outcomes.py run to populate actual_outcome column
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="B.L.A.S.T. Dashboard",
    page_icon="⚾",
    layout="wide",
    initial_sidebar_state="collapsed",
)

TEAL    = "#00D4AA"
GREEN   = "#00FF87"
RED     = "#FF4757"
AMBER   = "#FFA502"
BLUE    = "#1E90FF"
BG      = "#0D1117"
CARD_BG = "#161B22"
BORDER  = "#30363D"
TEXT    = "#E6EDF3"
MUTED   = "#8B949E"

PLOTLY_TEMPLATE = "plotly_dark"

st.markdown("""<style>
    .stTabs [data-baseweb="tab-panel"] { padding-bottom: 8rem; }
</style>""", unsafe_allow_html=True)

MARKET_LABELS = {
    # Game lines
    "h2h":                    "Moneyline",
    "spreads":                "Run Line",
    "totals":                 "Total Runs",
    # Batter props
    "batter_home_runs":       "Home Run",
    "batter_hits":            "Hit",
    "batter_total_bases":     "Total Bases",
    "batter_total_bases_1.5": "Total Bases 1.5",
    "batter_strikeouts":      "Batter K",
    # Pitcher props
    "pitcher_strikeouts":     "Pitcher K",
    "pitcher_outs":           "Pitcher Outs",
    "pitcher_hits_allowed":   "Hits Allowed",
    "pitcher_walks_allowed":  "Walks Allowed",
}

st.markdown(f"""
<style>
    /* Global */
    html, body, [class*="css"] {{
        background-color: {BG};
        color: {TEXT};
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .stApp {{ background-color: {BG}; }}
    .block-container {{ padding: 1.5rem 2rem; max-width: 1400px; }}

    /* Header */
    .blast-header {{
        display: flex;
        align-items: baseline;
        gap: 12px;
        margin-bottom: 0.25rem;
    }}
    .blast-title {{
        font-size: 1.75rem;
        font-weight: 700;
        color: {TEAL};
        letter-spacing: 0.05em;
    }}
    .blast-sub {{
        font-size: 0.85rem;
        color: {MUTED};
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }}

    /* KPI Cards */
    .kpi-card {{
        background: {CARD_BG};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 1.1rem 1.25rem;
        text-align: center;
    }}
    .kpi-label {{
        font-size: 0.72rem;
        color: {MUTED};
        text-transform: uppercase;
        letter-spacing: 0.1em;
        margin-bottom: 0.4rem;
    }}
    .kpi-value {{
        font-size: 2rem;
        font-weight: 700;
        line-height: 1;
    }}
    .kpi-delta {{
        font-size: 0.78rem;
        margin-top: 0.3rem;
        color: {MUTED};
    }}

    /* Outcome badges */
    .badge-hit     {{ color: {GREEN}; font-weight: 600; }}
    .badge-miss    {{ color: {RED};   font-weight: 600; }}
    .badge-pending {{ color: {AMBER}; font-weight: 600; }}

    /* Table */
    .stDataFrame {{ background: {CARD_BG}; border-radius: 8px; }}

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {{
        background: {CARD_BG};
        border-radius: 6px;
        padding: 4px;
        gap: 4px;
        border: 1px solid {BORDER};
    }}
    .stTabs [data-baseweb="tab"] {{
        color: {MUTED};
        border-radius: 4px;
        padding: 6px 18px;
        font-size: 0.85rem;
    }}
    .stTabs [aria-selected="true"] {{
        background: {TEAL} !important;
        color: {BG} !important;
        font-weight: 600;
    }}

    /* Divider */
    hr {{ border-color: {BORDER}; margin: 1rem 0; }}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------
@st.cache_resource
def get_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        st.error("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")
        st.stop()
    return create_client(url, key)


@st.cache_data(ttl=300)
def load_alerts() -> pd.DataFrame:
    """Loads all rows from mlb_alert_log, returns as DataFrame."""
    supabase = get_supabase()
    response = (
        supabase.table("mlb_alert_log")
        .select("*")
        .order("sent_at", desc=True)
        .execute()
    )
    if not response.data:
        return pd.DataFrame()

    df = pd.DataFrame(response.data)
    df["sent_at"] = pd.to_datetime(df["sent_at"], utc=True)
    df["game_date"] = df["sent_at"].dt.date
    df["market_label"] = df["market"].map(MARKET_LABELS).fillna(df["market"])

    # Re-derive implied probability from stored odds for calibration chart
    def parse_implied(odds_str):
        try:
            odds = int(odds_str.replace("+", ""))
            raw = 100 / (odds + 100) if odds > 0 else abs(odds) / (abs(odds) + 100)
            return raw / 1.05  # strip vig (matches ev_calculator logic)
        except Exception:
            return None

    df["implied_prob"] = df["odds_formatted"].apply(parse_implied)
    df["model_prob"]   = df.apply(
        lambda r: (r["implied_prob"] + r["calculated_edge_percentage"])
        if r["implied_prob"] is not None else None,
        axis=1,
    )

    return df


def kpi(label: str, value: str, color: str = TEXT, delta: str = ""):
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value" style="color:{color};">{value}</div>
        {"<div class='kpi-delta'>" + delta + "</div>" if delta else ""}
    </div>
    """, unsafe_allow_html=True)


def outcome_badge(val):
    if val is True:
        return "✓ Hit"
    if val is False:
        return "✗ Miss"
    return "⏳ Pending"


def outcome_color(val):
    if val is True:
        return GREEN
    if val is False:
        return RED
    return AMBER


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown("""
<div class="blast-header">
    <span class="blast-title">⚾ B.L.A.S.T.</span>
    <span class="blast-sub">Baseball Live Analytics & Scouting Technology — Monitoring Dashboard</span>
</div>
""", unsafe_allow_html=True)

@st.cache_data(ttl=120)
def load_odds(sportsbook: str = "All", market: str = "All", player: str = "") -> pd.DataFrame:
    """Loads recent rows from mlb_odds_log for the Odds Explorer tab."""
    supabase = get_supabase()
    response = (
        supabase.table("mlb_odds_log")
        .select("*")
        .order("fetched_at", desc=True)
        .limit(5000)
        .execute()
    )
    if not response.data:
        return pd.DataFrame()

    df = pd.DataFrame(response.data)
    df["fetched_at"] = pd.to_datetime(df["fetched_at"], utc=True)
    df["market_label"] = df["market"].map(MARKET_LABELS).fillna(df["market"])

    if sportsbook != "All":
        df = df[df["sportsbook"] == sportsbook]
    if market != "All":
        df = df[df["market_label"] == market]
    if player.strip():
        df = df[df["player_name"].str.contains(player.strip(), case=False, na=False)]

    return df


@st.cache_data(ttl=300)
def load_odds_books() -> list:
    """Returns distinct sportsbook keys from mlb_odds_log."""
    supabase = get_supabase()
    response = (
        supabase.table("mlb_odds_log")
        .select("sportsbook")
        .limit(2000)
        .execute()
    )
    if not response.data:
        return []
    return sorted({row["sportsbook"] for row in response.data if row.get("sportsbook")})


@st.cache_data(ttl=60)
def load_line_movements(sportsbook: str = "All", market: str = "All", player: str = "", min_shift: float = 0.01) -> pd.DataFrame:
    """Loads recent line movements from mlb_line_movements."""
    supabase = get_supabase()
    try:
        q = (
            supabase.table("mlb_line_movements")
            .select("player_name, market, sportsbook, game_date, old_odds, new_odds, old_implied_prob, new_implied_prob, prob_shift, old_point, new_point, detected_at")
            .order("detected_at", desc=True)
            .limit(2000)
        )
        response = q.execute()
        if not response.data:
            return pd.DataFrame()
        df = pd.DataFrame(response.data)
        df["detected_at"] = pd.to_datetime(df["detected_at"], utc=True)
        df["prob_shift"] = df["prob_shift"].astype(float)
        df["market_label"] = df["market"].map(MARKET_LABELS).fillna(df["market"])
        if sportsbook != "All":
            df = df[df["sportsbook"] == sportsbook]
        if market != "All":
            df = df[df["market_label"] == market]
        if player:
            df = df[df["player_name"].str.contains(player, case=False, na=False)]
        df = df[df["prob_shift"].abs() >= min_shift]
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_pitcher_gamelogs(player_name: str = "") -> pd.DataFrame:
    """Loads pitcher gamelogs from Supabase. Optionally filter by player name."""
    supabase = get_supabase()
    try:
        q = (
            supabase.table("pitcher_gamelogs")
            .select("pitcher_name, game_date, SO, HA, Outs, K_pct, opp_team, opp_k_pct")
            .order("game_date", desc=True)
        )
        if player_name.strip():
            name = player_name.strip().lower()
            parts = name.split()
            if len(parts) == 2:
                # Support both "first last" and "last, first" formats
                flipped = f"{parts[1]}, {parts[0]}"
                q = q.or_(f"pitcher_name.ilike.%{name}%,pitcher_name.ilike.%{flipped}%")
            else:
                q = q.ilike("pitcher_name", f"%{name}%")
        q = q.limit(50)
        response = q.execute()
        if not response.data:
            return pd.DataFrame()
        return pd.DataFrame(response.data)
    except Exception:
        return pd.DataFrame()


df_raw = load_alerts()

last_refresh = datetime.now(timezone.utc).strftime("%b %d %Y, %H:%M UTC")
alert_count = len(df_raw) if not df_raw.empty else 0
st.markdown(f'<p style="color:{MUTED}; font-size:0.78rem; margin-bottom:1rem;">Data refreshed: {last_refresh} &nbsp;·&nbsp; {alert_count:,} total alerts</p>', unsafe_allow_html=True)

tab_overview, tab_history, tab_accuracy, tab_pnl, tab_daily, tab_odds, tab_movements = st.tabs([
    "📊 Overview", "📋 Alert History", "🎯 Model Accuracy", "💰 P&L & Retraining", "📅 Daily EV Summary", "📈 Odds Explorer", "📉 Line Movements"
])


# ===========================================================================
# TAB 1 — OVERVIEW
# ===========================================================================
with tab_overview:
    if df_raw.empty:
        st.warning("No alert data yet. Run `python3 run_mlb_pipeline.py` to generate +EV alerts, or check the **Odds Explorer** tab to browse live sportsbook odds.")
    else:
        resolved = df_raw[df_raw["actual_outcome"].notna()]
        hits      = resolved[resolved["actual_outcome"] == True]
        misses    = resolved[resolved["actual_outcome"] == False]
        pending   = df_raw[df_raw["actual_outcome"].isna()]

        win_rate  = len(hits) / len(resolved) * 100 if len(resolved) > 0 else 0
        avg_edge  = df_raw["calculated_edge_percentage"].mean() * 100
        n_markets = df_raw["market"].nunique()

        st.markdown("#### Key Metrics")
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1: kpi("Total Alerts", f"{len(df_raw):,}", TEAL)
        with c2: kpi("Win Rate", f"{win_rate:.1f}%", GREEN if win_rate >= 50 else RED,
                     f"{len(hits)} hits / {len(resolved)} resolved")
        with c3: kpi("Avg Edge", f"+{avg_edge:.1f}%", TEAL)
        with c4: kpi("Pending", f"{len(pending):,}", AMBER, "outcomes not yet resolved")
        with c5: kpi("Markets", f"{n_markets}", BLUE)

        st.markdown("<hr>", unsafe_allow_html=True)

        col_left, col_right = st.columns([2, 1])

        with col_left:
            st.markdown("#### Alert Volume Over Time")
            daily_counts = (
                df_raw.groupby("game_date").size().reset_index(name="alerts")
            )
            daily_counts["game_date"] = pd.to_datetime(daily_counts["game_date"])
            fig_vol = px.bar(
                daily_counts, x="game_date", y="alerts",
                template=PLOTLY_TEMPLATE,
                color_discrete_sequence=[TEAL],
            )
            fig_vol.update_layout(
                plot_bgcolor=CARD_BG, paper_bgcolor=CARD_BG,
                margin=dict(l=0, r=0, t=10, b=0),
                xaxis_title="", yaxis_title="Alerts",
                height=240,
            )
            st.plotly_chart(fig_vol, use_container_width=True)

        with col_right:
            st.markdown("#### Market Mix")
            market_counts = df_raw["market_label"].value_counts().reset_index()
            market_counts.columns = ["market", "count"]
            fig_pie = px.pie(
                market_counts, names="market", values="count",
                template=PLOTLY_TEMPLATE,
                color_discrete_sequence=px.colors.sequential.Teal,
                hole=0.45,
            )
            fig_pie.update_layout(
                plot_bgcolor=CARD_BG, paper_bgcolor=CARD_BG,
                margin=dict(l=0, r=0, t=10, b=0),
                showlegend=True,
                legend=dict(font=dict(size=11), bgcolor=CARD_BG),
                height=240,
            )
            fig_pie.update_traces(textinfo="percent")
            st.plotly_chart(fig_pie, use_container_width=True)

        st.markdown("#### Recent Alerts (Last 10)")
        recent = df_raw.head(10)[["player_name", "market_label", "sportsbook", "odds_formatted",
                                   "calculated_edge_percentage", "sent_at", "actual_outcome"]].copy()
        recent["edge"]    = recent["calculated_edge_percentage"].apply(lambda x: f"+{x*100:.1f}%")
        recent["outcome"] = recent["actual_outcome"].apply(outcome_badge)
        recent["sent_at"] = recent["sent_at"].dt.strftime("%b %d, %H:%M")
        recent = recent.drop(columns=["calculated_edge_percentage", "actual_outcome"])
        recent = recent[["player_name", "market_label", "sportsbook", "odds_formatted", "edge", "sent_at", "outcome"]]
        recent.columns    = ["Player", "Market", "Book", "Odds", "Edge", "Sent At", "Outcome"]
        st.dataframe(recent, use_container_width=True, hide_index=True)


# ===========================================================================
# TAB 2 — ALERT HISTORY
# ===========================================================================
with tab_history:
    if df_raw.empty:
        st.info("No alert data yet. Check the **Odds Explorer** tab to browse live sportsbook odds.")
    else:
        st.markdown("#### Filter Alerts")

        col_f1, col_f2, col_f3, col_f4 = st.columns(4)

        with col_f1:
            all_markets = ["All"] + sorted(df_raw["market_label"].unique().tolist())
            sel_market  = st.selectbox("Market", all_markets, key="hist_market")

        with col_f2:
            all_books = ["All"] + sorted(df_raw["sportsbook"].dropna().unique().tolist())
            sel_book  = st.selectbox("Sportsbook", all_books, key="hist_book")

        with col_f3:
            outcome_opts = {"All": None, "✓ Hit": True, "✗ Miss": False, "⏳ Pending": "pending"}
            sel_outcome  = st.selectbox("Outcome", list(outcome_opts.keys()), key="hist_outcome")

        with col_f4:
            date_min = df_raw["game_date"].min()
            date_max = df_raw["game_date"].max()
            sel_dates = st.date_input("Date Range", value=(date_min, date_max),
                                      min_value=date_min, max_value=date_max, key="hist_dates")

        filtered = df_raw.copy()
        if sel_market != "All":
            filtered = filtered[filtered["market_label"] == sel_market]
        if sel_book != "All":
            filtered = filtered[filtered["sportsbook"] == sel_book]
        if sel_outcome != "All":
            ov = outcome_opts[sel_outcome]
            if ov == "pending":
                filtered = filtered[filtered["actual_outcome"].isna()]
            else:
                filtered = filtered[filtered["actual_outcome"] == ov]
        if isinstance(sel_dates, tuple) and len(sel_dates) == 2:
            filtered = filtered[
                (filtered["game_date"] >= sel_dates[0]) &
                (filtered["game_date"] <= sel_dates[1])
            ]

        st.markdown(f'<p style="color:{MUTED}; font-size:0.8rem;">{len(filtered):,} results</p>',
                    unsafe_allow_html=True)

        hist_cols = [
            "player_name", "market_label", "sportsbook", "odds_formatted",
            "calculated_edge_percentage", "model_prob", "implied_prob",
            "game_date", "actual_outcome"
        ]
        has_point = "point" in filtered.columns
        if has_point:
            hist_cols.insert(3, "point")

        display = filtered[hist_cols].copy()

        if has_point:
            display["Line"] = display["point"].apply(lambda x: str(x) if pd.notna(x) else "—")
        display["Edge"]         = display["calculated_edge_percentage"].apply(lambda x: f"+{x*100:.1f}%")
        display["Model Prob"]   = display["model_prob"].apply(lambda x: f"{x*100:.1f}%" if pd.notna(x) else "—")
        display["Implied Prob"] = display["implied_prob"].apply(lambda x: f"{x*100:.1f}%" if pd.notna(x) else "—")
        display["Outcome"]      = display["actual_outcome"].apply(outcome_badge)
        display["Date"]         = display["game_date"].astype(str)

        display = display.rename(columns={
            "player_name": "Player", "market_label": "Market",
            "sportsbook": "Sportsbook", "odds_formatted": "Odds",
        })
        final_hist_cols = ["Player", "Market"]
        if has_point:
            final_hist_cols += ["Line"]
        final_hist_cols += ["Sportsbook", "Odds", "Edge", "Model Prob", "Implied Prob", "Date", "Outcome"]
        display = display[final_hist_cols]

        st.dataframe(display, use_container_width=True, hide_index=True, height=520)

        csv = filtered.to_csv(index=False).encode("utf-8")
        st.download_button("⬇ Export CSV", csv, "blast_alerts.csv", "text/csv")


# ===========================================================================
# TAB 3 — MODEL ACCURACY
# ===========================================================================
with tab_accuracy:
    if df_raw.empty:
        st.info("No alert data yet.")
    else:
        resolved_all = df_raw[df_raw["actual_outcome"].notna()].copy()

        if resolved_all.empty:
            st.info("Run `python3 dashboard/backfill_outcomes.py` to populate actual outcomes.")
        else:
            # Filters
            acc_col1, acc_col2 = st.columns(2)
            with acc_col1:
                book_opts = ["All"] + sorted(resolved_all["sportsbook"].dropna().unique().tolist())
                sel_acc_book = st.selectbox("Sportsbook", book_opts, key="acc_book")
            with acc_col2:
                market_opts = ["All"] + sorted(resolved_all["market_label"].dropna().unique().tolist())
                sel_acc_market = st.selectbox("Market", market_opts, key="acc_market")

            resolved = resolved_all.copy()
            if sel_acc_book != "All":
                resolved = resolved[resolved["sportsbook"] == sel_acc_book]
            if sel_acc_market != "All":
                resolved = resolved[resolved["market_label"] == sel_acc_market]

            if resolved.empty:
                st.info("No resolved alerts match the selected filters.")
            else:
                resolved["hit"] = resolved["actual_outcome"].astype(int)

                overall_wr  = resolved["hit"].mean() * 100
                by_market   = resolved.groupby("market_label")["hit"].agg(["mean", "count"]).reset_index()
                by_market.columns = ["Market", "Win Rate", "Alerts"]
                by_market["Win Rate %"] = (by_market["Win Rate"] * 100).round(1)
                best_market = by_market.loc[by_market["Win Rate"].idxmax(), "Market"] if len(by_market) else "—"

                avg_edge_hits   = resolved[resolved["hit"] == 1]["calculated_edge_percentage"].mean() * 100
                avg_edge_misses = resolved[resolved["hit"] == 0]["calculated_edge_percentage"].mean() * 100

                c1, c2, c3, c4 = st.columns(4)
                with c1: kpi("Overall Win Rate", f"{overall_wr:.1f}%", GREEN if overall_wr >= 50 else RED)
                with c2: kpi("Best Market", best_market, TEAL)
                with c3: kpi("Avg Edge (Hits)",   f"+{avg_edge_hits:.1f}%",   GREEN)
                with c4: kpi("Avg Edge (Misses)", f"+{avg_edge_misses:.1f}%", RED)

                st.markdown("<hr>", unsafe_allow_html=True)

                # Alerts table
                st.markdown(
                    f'<p style="color:{MUTED}; font-size:0.8rem;">{len(resolved):,} alerts</p>',
                    unsafe_allow_html=True,
                )
                disp_acc = resolved[[
                    "player_name", "market_label", "point", "sportsbook",
                    "odds_formatted", "calculated_edge_percentage",
                    "model_prob", "implied_prob", "sent_at", "actual_outcome"
                ]].copy()
                disp_acc["Edge"] = disp_acc["calculated_edge_percentage"].apply(
                    lambda x: f"+{x*100:.1f}%" if pd.notna(x) else "—"
                )
                disp_acc["Model Prob"] = disp_acc["model_prob"].apply(
                    lambda x: f"{x*100:.1f}%" if pd.notna(x) else "—"
                )
                disp_acc["Implied Prob"] = disp_acc["implied_prob"].apply(
                    lambda x: f"{x*100:.1f}%" if pd.notna(x) else "—"
                )
                disp_acc["Line"] = disp_acc["point"].apply(
                    lambda x: str(x) if pd.notna(x) else "—"
                )
                disp_acc["Outcome"] = disp_acc["actual_outcome"].apply(
                    lambda x: "✅ Hit" if x is True else ("❌ Miss" if x is False else "⏳ Pending")
                )
                disp_acc["Date"] = pd.to_datetime(disp_acc["sent_at"]).dt.strftime("%Y-%m-%d")
                disp_acc = disp_acc.rename(columns={
                    "player_name": "Player",
                    "market_label": "Market",
                    "sportsbook": "Sportsbook",
                    "odds_formatted": "Odds",
                })
                disp_acc = disp_acc[["Player", "Market", "Line", "Sportsbook", "Odds", "Edge", "Model Prob", "Implied Prob", "Date", "Outcome"]]
                st.dataframe(disp_acc, use_container_width=True, hide_index=True, height=280)

                st.markdown("<hr>", unsafe_allow_html=True)

                col_l, col_r = st.columns(2)

                with col_l:
                    st.markdown("#### Win Rate by Market")
                    by_market_sorted = by_market.sort_values("Win Rate %", ascending=True)
                    colors = [GREEN if wr >= 50 else RED for wr in by_market_sorted["Win Rate %"]]
                    fig_market = go.Figure(go.Bar(
                        x=by_market_sorted["Win Rate %"],
                        y=by_market_sorted["Market"],
                        orientation="h",
                        marker_color=colors,
                        text=by_market_sorted.apply(lambda r: f"{r['Win Rate %']}% ({int(r['Alerts'])})", axis=1),
                        textposition="outside",
                    ))
                    fig_market.add_vline(x=50, line_dash="dot", line_color=MUTED, annotation_text="50%")
                    fig_market.update_layout(
                        template=PLOTLY_TEMPLATE,
                        plot_bgcolor=CARD_BG, paper_bgcolor=CARD_BG,
                        margin=dict(l=0, r=60, t=10, b=0),
                        xaxis=dict(range=[0, 110], title="Win Rate %"),
                        yaxis_title="",
                        height=320,
                    )
                    st.plotly_chart(fig_market, use_container_width=True)

                with col_r:
                    st.markdown("#### Win Rate Over Time (Weekly)")
                    resolved["week"] = pd.to_datetime(resolved["game_date"]).dt.to_period("W").dt.start_time
                    weekly = resolved.groupby("week")["hit"].agg(["mean", "count"]).reset_index()
                    weekly.columns = ["Week", "Win Rate", "Alerts"]
                    weekly["Win Rate %"] = (weekly["Win Rate"] * 100).round(1)

                    fig_time = go.Figure()
                    fig_time.add_trace(go.Scatter(
                        x=weekly["Week"], y=weekly["Win Rate %"],
                        mode="lines+markers",
                        line=dict(color=TEAL, width=2),
                        marker=dict(size=6, color=TEAL),
                        name="Win Rate",
                        hovertemplate="%{y:.1f}% (%{customdata} alerts)<extra></extra>",
                        customdata=weekly["Alerts"],
                    ))
                    fig_time.add_hline(y=50, line_dash="dot", line_color=MUTED)
                    fig_time.update_layout(
                        template=PLOTLY_TEMPLATE,
                        plot_bgcolor=CARD_BG, paper_bgcolor=CARD_BG,
                        margin=dict(l=0, r=0, t=10, b=0),
                        yaxis=dict(range=[0, 105], title="Win Rate %"),
                        xaxis_title="",
                        height=320,
                        showlegend=False,
                    )
                    st.plotly_chart(fig_time, use_container_width=True)

                col_l2, col_r2 = st.columns(2)

                with col_l2:
                    st.markdown("#### Edge Distribution: Hits vs Misses")
                    fig_edge = go.Figure()
                    fig_edge.add_trace(go.Histogram(
                        x=resolved[resolved["hit"] == 1]["calculated_edge_percentage"] * 100,
                        name="Hit", marker_color=GREEN, opacity=0.75, nbinsx=20,
                    ))
                    fig_edge.add_trace(go.Histogram(
                        x=resolved[resolved["hit"] == 0]["calculated_edge_percentage"] * 100,
                        name="Miss", marker_color=RED, opacity=0.75, nbinsx=20,
                    ))
                    fig_edge.update_layout(
                        barmode="overlay",
                        template=PLOTLY_TEMPLATE,
                        plot_bgcolor=CARD_BG, paper_bgcolor=CARD_BG,
                        margin=dict(l=0, r=0, t=10, b=0),
                        xaxis_title="Edge %", yaxis_title="Count",
                        height=280,
                        legend=dict(bgcolor=CARD_BG),
                    )
                    st.plotly_chart(fig_edge, use_container_width=True)

                with col_r2:
                    st.markdown("#### Model Calibration")
                    cal_df = resolved.dropna(subset=["model_prob"]).copy()
                    if not cal_df.empty:
                        cal_df["prob_bucket"] = pd.cut(cal_df["model_prob"], bins=10)
                        cal = cal_df.groupby("prob_bucket", observed=False).agg(
                            mean_pred=("model_prob", "mean"),
                            actual_rate=("hit", "mean"),
                            count=("hit", "count"),
                        ).dropna().reset_index()

                        fig_cal = go.Figure()
                        fig_cal.add_trace(go.Scatter(
                            x=[0, 1], y=[0, 1],
                            mode="lines", line=dict(color=MUTED, dash="dot"), name="Perfect"
                        ))
                        fig_cal.add_trace(go.Scatter(
                            x=cal["mean_pred"], y=cal["actual_rate"],
                            mode="lines+markers",
                            marker=dict(size=cal["count"].clip(4, 18), color=TEAL, sizemode="area"),
                            line=dict(color=TEAL),
                            name="Model",
                            hovertemplate="Predicted: %{x:.1%}<br>Actual: %{y:.1%}<extra></extra>",
                        ))
                        fig_cal.update_layout(
                            template=PLOTLY_TEMPLATE,
                            plot_bgcolor=CARD_BG, paper_bgcolor=CARD_BG,
                            margin=dict(l=0, r=0, t=10, b=0),
                            xaxis=dict(range=[0, 1], title="Model Probability", tickformat=".0%"),
                            yaxis=dict(range=[0, 1], title="Actual Hit Rate", tickformat=".0%"),
                            height=280,
                            legend=dict(bgcolor=CARD_BG),
                        )
                        st.plotly_chart(fig_cal, use_container_width=True)
                    else:
                        st.info("Not enough data for calibration chart.")


# ===========================================================================
# TAB 4 — P&L & RETRAINING
# ===========================================================================
with tab_pnl:
    if df_raw.empty:
        st.info("No alert data yet.")
    else:
        resolved = df_raw[df_raw["actual_outcome"].notna()].copy()

        if resolved.empty:
            st.info("Run `python3 dashboard/backfill_outcomes.py` to populate actual outcomes, then revisit this tab.")
        else:
            resolved["hit"] = resolved["actual_outcome"].astype(int)

            # --- P&L calculation (flat $100 bet per alert) ---
            def calc_payout(odds_str, hit):
                """Returns net profit/loss for a $100 flat bet."""
                try:
                    odds = int(str(odds_str).replace("+", ""))
                    if hit:
                        return odds * 100 / 100 if odds > 0 else 100 / abs(odds) * 100
                    return -100.0
                except Exception:
                    return 0.0

            resolved["pnl"] = resolved.apply(
                lambda r: calc_payout(r["odds_formatted"], r["hit"]), axis=1
            )

            total_pnl     = resolved["pnl"].sum()
            total_wagered = len(resolved) * 100
            roi           = (total_pnl / total_wagered * 100) if total_wagered > 0 else 0
            avg_win       = resolved[resolved["hit"] == 1]["pnl"].mean() if resolved["hit"].sum() > 0 else 0
            avg_loss      = resolved[resolved["hit"] == 0]["pnl"].mean() if (resolved["hit"] == 0).sum() > 0 else 0
            win_rate      = resolved["hit"].mean() * 100

            # KPI row
            st.markdown("#### Profit & Loss (Flat $100 Bets)")
            c1, c2, c3, c4, c5 = st.columns(5)
            pnl_color = GREEN if total_pnl >= 0 else RED
            with c1: kpi("Total P&L", f"${total_pnl:+,.0f}", pnl_color)
            with c2: kpi("ROI", f"{roi:+.1f}%", GREEN if roi >= 0 else RED,
                         f"${total_wagered:,.0f} wagered")
            with c3: kpi("Win Rate", f"{win_rate:.1f}%", GREEN if win_rate >= 50 else RED,
                         f"{resolved['hit'].sum()}/{len(resolved)} resolved")
            with c4: kpi("Avg Win", f"${avg_win:+,.0f}", GREEN)
            with c5: kpi("Avg Loss", f"${avg_loss:,.0f}", RED)

            st.markdown("<hr>", unsafe_allow_html=True)

            # --- Cumulative P&L chart ---
            col_l, col_r = st.columns(2)

            with col_l:
                st.markdown("#### Cumulative P&L Over Time")
                pnl_daily = (
                    resolved.groupby("game_date")["pnl"].sum()
                    .sort_index()
                    .cumsum()
                    .reset_index()
                )
                pnl_daily.columns = ["Date", "Cumulative P&L"]
                pnl_daily["Date"] = pd.to_datetime(pnl_daily["Date"])
                fig_pnl = go.Figure()
                fig_pnl.add_trace(go.Scatter(
                    x=pnl_daily["Date"], y=pnl_daily["Cumulative P&L"],
                    mode="lines",
                    fill="tozeroy",
                    line=dict(color=TEAL, width=2),
                    fillcolor="rgba(0, 212, 170, 0.15)",
                ))
                fig_pnl.add_hline(y=0, line_dash="dot", line_color=MUTED)
                fig_pnl.update_layout(
                    template=PLOTLY_TEMPLATE,
                    plot_bgcolor=CARD_BG, paper_bgcolor=CARD_BG,
                    margin=dict(l=0, r=0, t=10, b=0),
                    yaxis_title="Cumulative P&L ($)", xaxis_title="",
                    height=300,
                )
                st.plotly_chart(fig_pnl, use_container_width=True)

            with col_r:
                st.markdown("#### ROI by Edge Bucket")
                resolved["edge_bucket"] = pd.cut(
                    resolved["calculated_edge_percentage"] * 100,
                    bins=[0, 5, 10, 15, 20, 30, 100],
                    labels=["0-5%", "5-10%", "10-15%", "15-20%", "20-30%", "30%+"],
                )
                edge_roi = resolved.groupby("edge_bucket", observed=False).agg(
                    bets=("pnl", "count"),
                    total_pnl=("pnl", "sum"),
                    win_rate=("hit", "mean"),
                ).reset_index()
                edge_roi["roi"] = (edge_roi["total_pnl"] / (edge_roi["bets"] * 100) * 100).round(1)
                colors = [GREEN if r >= 0 else RED for r in edge_roi["roi"]]
                fig_roi = go.Figure(go.Bar(
                    x=edge_roi["edge_bucket"].astype(str),
                    y=edge_roi["roi"],
                    marker_color=colors,
                    text=edge_roi.apply(lambda r: f"{r['roi']:+.1f}% ({int(r['bets'])})", axis=1),
                    textposition="outside",
                ))
                fig_roi.add_hline(y=0, line_dash="dot", line_color=MUTED)
                fig_roi.update_layout(
                    template=PLOTLY_TEMPLATE,
                    plot_bgcolor=CARD_BG, paper_bgcolor=CARD_BG,
                    margin=dict(l=0, r=0, t=10, b=0),
                    xaxis_title="Model Edge", yaxis_title="ROI %",
                    height=300,
                )
                st.plotly_chart(fig_roi, use_container_width=True)

            st.markdown("<hr>", unsafe_allow_html=True)

            # --- P&L by Market and by Sportsbook ---
            col_m, col_s = st.columns(2)

            with col_m:
                st.markdown("#### P&L by Market")
                by_market = resolved.groupby("market_label").agg(
                    bets=("pnl", "count"),
                    total_pnl=("pnl", "sum"),
                    win_rate=("hit", "mean"),
                ).reset_index()
                by_market["roi"] = (by_market["total_pnl"] / (by_market["bets"] * 100) * 100).round(1)
                by_market = by_market.sort_values("total_pnl", ascending=True)
                colors = [GREEN if p >= 0 else RED for p in by_market["total_pnl"]]
                fig_mkt = go.Figure(go.Bar(
                    x=by_market["total_pnl"],
                    y=by_market["market_label"],
                    orientation="h",
                    marker_color=colors,
                    text=by_market.apply(
                        lambda r: f"${r['total_pnl']:+,.0f} ({r['win_rate']*100:.0f}% WR, {int(r['bets'])} bets)", axis=1
                    ),
                    textposition="outside",
                ))
                fig_mkt.add_vline(x=0, line_dash="dot", line_color=MUTED)
                fig_mkt.update_layout(
                    template=PLOTLY_TEMPLATE,
                    plot_bgcolor=CARD_BG, paper_bgcolor=CARD_BG,
                    margin=dict(l=0, r=80, t=10, b=0),
                    xaxis_title="Total P&L ($)", yaxis_title="",
                    height=300,
                )
                st.plotly_chart(fig_mkt, use_container_width=True)

            with col_s:
                st.markdown("#### P&L by Sportsbook")
                by_book = resolved.groupby("sportsbook").agg(
                    bets=("pnl", "count"),
                    total_pnl=("pnl", "sum"),
                    win_rate=("hit", "mean"),
                ).reset_index()
                by_book["roi"] = (by_book["total_pnl"] / (by_book["bets"] * 100) * 100).round(1)
                by_book = by_book.sort_values("total_pnl", ascending=True)
                colors = [GREEN if p >= 0 else RED for p in by_book["total_pnl"]]
                fig_book = go.Figure(go.Bar(
                    x=by_book["total_pnl"],
                    y=by_book["sportsbook"],
                    orientation="h",
                    marker_color=colors,
                    text=by_book.apply(
                        lambda r: f"${r['total_pnl']:+,.0f} (ROI: {r['roi']:+.1f}%, {int(r['bets'])} bets)", axis=1
                    ),
                    textposition="outside",
                ))
                fig_book.add_vline(x=0, line_dash="dot", line_color=MUTED)
                fig_book.update_layout(
                    template=PLOTLY_TEMPLATE,
                    plot_bgcolor=CARD_BG, paper_bgcolor=CARD_BG,
                    margin=dict(l=0, r=80, t=10, b=0),
                    xaxis_title="Total P&L ($)", yaxis_title="",
                    height=300,
                )
                st.plotly_chart(fig_book, use_container_width=True)

            st.markdown("<hr>", unsafe_allow_html=True)

            # --- Biggest Misses (worst losses by edge) ---
            st.markdown("#### Biggest Misses (Model Overconfidence)")
            st.markdown(
                f'<p style="color:{MUTED}; font-size:0.82rem;">'
                f'Alerts where the model predicted a high edge but the bet lost. '
                f'These are the most valuable cases for retraining — the model was most wrong here.</p>',
                unsafe_allow_html=True,
            )
            misses = resolved[resolved["hit"] == 0].sort_values(
                "calculated_edge_percentage", ascending=False
            ).head(20).copy()
            if not misses.empty:
                miss_display = misses[[
                    "player_name", "market_label", "sportsbook", "odds_formatted",
                    "calculated_edge_percentage", "model_prob", "implied_prob", "game_date"
                ]].copy()
                miss_display["Edge"]       = miss_display["calculated_edge_percentage"].apply(lambda x: f"+{x*100:.1f}%")
                miss_display["Model Prob"] = miss_display["model_prob"].apply(lambda x: f"{x*100:.1f}%" if pd.notna(x) else "-")
                miss_display["Implied"]    = miss_display["implied_prob"].apply(lambda x: f"{x*100:.1f}%" if pd.notna(x) else "-")
                miss_display["Date"]       = miss_display["game_date"].astype(str)
                miss_display = miss_display.rename(columns={
                    "player_name": "Player", "market_label": "Market",
                    "sportsbook": "Book", "odds_formatted": "Odds",
                })
                miss_display = miss_display[["Player", "Market", "Book", "Odds", "Edge", "Model Prob", "Implied", "Date"]]
                st.dataframe(miss_display, use_container_width=True, hide_index=True)
            else:
                st.success("No misses yet!")

            st.markdown("<hr>", unsafe_allow_html=True)

            # --- Export for retraining ---
            st.markdown("#### Export Resolved Alerts for Retraining")
            st.markdown(
                f'<p style="color:{MUTED}; font-size:0.82rem;">'
                f'Download all resolved alerts as CSV. Includes player name, market, odds, '
                f'model probability, implied probability, edge, and actual outcome (1=hit, 0=miss). '
                f'Use this to analyze model weaknesses and retrain.</p>',
                unsafe_allow_html=True,
            )
            export = resolved[[
                "player_name", "market", "sportsbook", "odds_formatted",
                "calculated_edge_percentage", "model_prob", "implied_prob",
                "game_date", "actual_outcome"
            ]].copy()
            export.columns = [
                "player_name", "market", "sportsbook", "odds",
                "edge", "model_prob", "implied_prob",
                "game_date", "outcome"
            ]
            export["outcome"] = export["outcome"].astype(int)

            c1, c2, _ = st.columns([1, 1, 2])
            with c1:
                csv_retrain = export.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "Download Resolved Alerts CSV",
                    csv_retrain, "blast_resolved_alerts.csv", "text/csv",
                )
            with c2:
                st.markdown(
                    f'<p style="color:{MUTED}; font-size:0.82rem; margin-top:0.5rem;">'
                    f'{len(export):,} resolved alerts available</p>',
                    unsafe_allow_html=True,
                )


# ===========================================================================
# TAB 5 — DAILY EV SUMMARY
# ===========================================================================
with tab_daily:
    if df_raw.empty:
        st.info("No alert data yet.")
    else:
        daily = (
            df_raw.groupby("game_date")
            .agg(
                alerts=("id", "count"),
                avg_edge=("calculated_edge_percentage", "mean"),
                hits=("actual_outcome", lambda x: (x == True).sum()),
                resolved=("actual_outcome", lambda x: x.notna().sum()),
            )
            .reset_index()
        )
        daily["game_date"] = pd.to_datetime(daily["game_date"])
        daily["win_rate"]  = daily.apply(
            lambda r: r["hits"] / r["resolved"] if r["resolved"] > 0 else None, axis=1
        )
        daily["avg_edge_pct"] = daily["avg_edge"] * 100

        best_day  = daily.loc[daily["alerts"].idxmax()]
        most_edge = daily.dropna(subset=["win_rate"]).loc[daily.dropna(subset=["win_rate"])["win_rate"].idxmax()] \
                    if daily["win_rate"].notna().any() else None

        c1, c2, c3 = st.columns(3)
        with c1: kpi("Peak Day Alerts", str(int(best_day["alerts"])),
                     TEAL, str(best_day["game_date"].date()))
        with c2: kpi("Avg Alerts/Day", f"{daily['alerts'].mean():.1f}", TEAL)
        with c3:
            if most_edge is not None:
                kpi("Best Win-Rate Day", f"{most_edge['win_rate']*100:.0f}%",
                    GREEN, str(most_edge["game_date"].date()))
            else:
                kpi("Best Win-Rate Day", "—", MUTED, "pending outcomes")

        st.markdown("<hr>", unsafe_allow_html=True)

        st.markdown("#### Daily Alert Count & Avg Edge")
        fig_daily = go.Figure()
        fig_daily.add_trace(go.Bar(
            x=daily["game_date"], y=daily["alerts"],
            name="Alerts", marker_color=TEAL, opacity=0.8,
            yaxis="y",
        ))
        fig_daily.add_trace(go.Scatter(
            x=daily["game_date"], y=daily["avg_edge_pct"],
            name="Avg Edge %", line=dict(color=AMBER, width=2),
            mode="lines+markers", marker=dict(size=5),
            yaxis="y2",
        ))
        fig_daily.update_layout(
            template=PLOTLY_TEMPLATE,
            plot_bgcolor=CARD_BG, paper_bgcolor=CARD_BG,
            margin=dict(l=0, r=0, t=10, b=0),
            height=280,
            xaxis_title="",
            yaxis=dict(title="Alerts", side="left"),
            yaxis2=dict(title="Avg Edge %", side="right", overlaying="y"),
            legend=dict(bgcolor=CARD_BG, orientation="h", y=1.05),
        )
        st.plotly_chart(fig_daily, use_container_width=True)

        st.markdown("#### Market Mix Over Time")
        market_daily = (
            df_raw.groupby(["game_date", "market_label"])
            .size()
            .reset_index(name="count")
        )
        market_daily["game_date"] = pd.to_datetime(market_daily["game_date"])
        fig_stack = px.bar(
            market_daily, x="game_date", y="count", color="market_label",
            template=PLOTLY_TEMPLATE,
            color_discrete_sequence=px.colors.qualitative.Set3,
            barmode="stack",
            labels={"market_label": "Market", "count": "Alerts", "game_date": ""},
        )
        fig_stack.update_layout(
            plot_bgcolor=CARD_BG, paper_bgcolor=CARD_BG,
            margin=dict(l=0, r=0, t=10, b=0),
            height=260,
            legend=dict(bgcolor=CARD_BG, font=dict(size=11)),
        )
        st.plotly_chart(fig_stack, use_container_width=True)

        col_b, col_w = st.columns(2)

        with col_b:
            st.markdown("#### Best Days by Win Rate")
            top = (
                daily.dropna(subset=["win_rate"])
                .sort_values("win_rate", ascending=False)
                .head(10)
            )
            top_display = top[["game_date", "alerts", "hits", "resolved", "win_rate", "avg_edge_pct"]].copy()
            top_display["Date"]     = top_display["game_date"].dt.strftime("%b %d")
            top_display["Win Rate"] = top_display["win_rate"].apply(lambda x: f"{x*100:.0f}%")
            top_display["Avg Edge"] = top_display["avg_edge_pct"].apply(lambda x: f"+{x:.1f}%")
            top_display = top_display[["Date", "alerts", "hits", "resolved", "Win Rate", "Avg Edge"]]
            top_display.columns = ["Date", "Alerts", "Hits", "Resolved", "Win Rate", "Avg Edge"]
            st.dataframe(top_display, use_container_width=True, hide_index=True)

        with col_w:
            st.markdown("#### Worst Days by Win Rate")
            bot = (
                daily.dropna(subset=["win_rate"])
                .sort_values("win_rate", ascending=True)
                .head(10)
            )
            bot_display = bot[["game_date", "alerts", "hits", "resolved", "win_rate", "avg_edge_pct"]].copy()
            bot_display["Date"]     = bot_display["game_date"].dt.strftime("%b %d")
            bot_display["Win Rate"] = bot_display["win_rate"].apply(lambda x: f"{x*100:.0f}%")
            bot_display["Avg Edge"] = bot_display["avg_edge_pct"].apply(lambda x: f"+{x:.1f}%")
            bot_display = bot_display[["Date", "alerts", "hits", "resolved", "Win Rate", "Avg Edge"]]
            bot_display.columns = ["Date", "Alerts", "Hits", "Resolved", "Win Rate", "Avg Edge"]
            st.dataframe(bot_display, use_container_width=True, hide_index=True)


# ===========================================================================
# TAB 5 — ODDS EXPLORER
# ===========================================================================
with tab_odds:
    st.markdown("#### Live Odds Explorer")
    st.markdown(
        f'<p style="color:{MUTED}; font-size:0.82rem;">Browse raw sportsbook odds archived by the pipeline. '
        f'Populated each time <code>run_mlb_pipeline.py</code> runs. '
        f'Shows the last 5,000 rows (most recent first).</p>',
        unsafe_allow_html=True,
    )

    col_o1, col_o2, col_o3, col_o4 = st.columns(4)
    with col_o1:
        available_books = load_odds_books()
        sel_odds_book = st.selectbox("Sportsbook", ["All"] + available_books, key="odds_book")
    with col_o2:
        type_opts = ["All", "Game Lines", "Player Props"]
        sel_odds_type = st.selectbox("Type", type_opts, key="odds_type")
    with col_o3:
        odds_market_opts = ["All"] + list(MARKET_LABELS.values())
        sel_odds_market = st.selectbox("Market", odds_market_opts, key="odds_market")
    with col_o4:
        sel_odds_player = st.text_input("Team / Player (partial match)", key="odds_player")

    GAME_LINE_KEYS = {"h2h", "spreads", "totals"}

    def _fmt_odds(val):
        if pd.isna(val): return "—"
        return f"+{int(val)}" if val > 0 else str(int(val))

    def _fmt_rl(pt, odds):
        if pd.isna(pt) or pd.isna(odds): return "—"
        pt_str = f"+{pt:.1f}" if pt > 0 else f"{pt:.1f}"
        return f"{pt_str} ({_fmt_odds(odds)})"

    def _fmt_total(label, pt, odds):
        if pd.isna(pt) or pd.isna(odds): return "—"
        return f"{label} {pt:.1f} ({_fmt_odds(odds)})"

    def build_game_lines_table(df):
        """Pivot long-format odds into sportsbook two-row-per-game layout."""
        gl = df[df["market"].isin(GAME_LINE_KEYS)].copy()
        if gl.empty:
            return pd.DataFrame()

        rows = []
        group_cols = ["event_id", "sportsbook", "game_date"]
        # Use home/away if available, else fall back to first/second team seen
        for (eid, book, gdate), grp in gl.groupby(group_cols):
            home = grp["home_team"].dropna().iloc[0] if "home_team" in grp and grp["home_team"].notna().any() else None
            away = grp["away_team"].dropna().iloc[0] if "away_team" in grp and grp["away_team"].notna().any() else None

            # If home/away unknown, infer from h2h outcome names
            if not home or not away:
                teams = grp[grp["market"] == "h2h"]["player_name"].unique().tolist()
                away = teams[0] if len(teams) > 0 else "Away"
                home = teams[1] if len(teams) > 1 else "Home"

            commence = grp["commence_time"].dropna().iloc[0] if "commence_time" in grp and grp["commence_time"].notna().any() else None
            time_str = pd.to_datetime(commence, utc=True).strftime("%-m/%-d/%y %-I:%M %p") if commence else str(gdate)

            h2h  = grp[grp["market"] == "h2h"]
            spr  = grp[grp["market"] == "spreads"]
            tot  = grp[grp["market"] == "totals"]

            def team_val(sub, team, col="odds_american"):
                r = sub[sub["player_name"] == team]
                return r[col].values[0] if not r.empty else float("nan")

            def team_pt(sub, team):
                r = sub[sub["player_name"] == team]
                return r["point"].values[0] if not r.empty and "point" in r.columns else float("nan")

            def label_val(sub, label, col="odds_american"):
                r = sub[sub["player_name"] == label]
                return r[col].values[0] if not r.empty else float("nan")

            def label_pt(sub, label):
                r = sub[sub["player_name"] == label]
                return r["point"].values[0] if not r.empty and "point" in r.columns else float("nan")

            # Away row
            rows.append({
                "Game":     time_str,
                "Book":     book,
                "Team":     away,
                "Run Line": _fmt_rl(team_pt(spr, away), team_val(spr, away)),
                "Moneyline": _fmt_odds(team_val(h2h, away)),
                "Total":    _fmt_total("O", label_pt(tot, "Over"), label_val(tot, "Over")),
                "_sort":    str(gdate) + eid + book + "0",
            })
            # Home row
            rows.append({
                "Game":     "",  # blank — same game block
                "Book":     book,
                "Team":     home,
                "Run Line": _fmt_rl(team_pt(spr, home), team_val(spr, home)),
                "Moneyline": _fmt_odds(team_val(h2h, home)),
                "Total":    _fmt_total("U", label_pt(tot, "Under"), label_val(tot, "Under")),
                "_sort":    str(gdate) + eid + book + "1",
            })

        result = pd.DataFrame(rows).sort_values("_sort").drop(columns=["_sort"])
        return result

    df_odds = load_odds(sel_odds_book, sel_odds_market, sel_odds_player)

    # Apply type filter
    if not df_odds.empty and sel_odds_type != "All":
        if sel_odds_type == "Game Lines":
            df_odds = df_odds[df_odds["market"].isin(GAME_LINE_KEYS)]
        else:
            df_odds = df_odds[~df_odds["market"].isin(GAME_LINE_KEYS)]

    if df_odds.empty:
        st.info(
            "No odds data found. The pipeline archives odds to `mlb_odds_log` each run.\n\n"
            "**To populate this table:**\n"
            "```bash\n"
            "ALLOW_SPRING_TRAINING=true python3 run_mlb_pipeline.py\n"
            "```\n"
            "Then refresh this page."
        )
    elif sel_odds_type == "Game Lines":
        # Sportsbook-style pivot view
        gl_table = build_game_lines_table(df_odds)
        if gl_table.empty:
            st.info("No game line data found for the selected filters.")
        else:
            st.markdown(
                f'<p style="color:{MUTED}; font-size:0.8rem;">'
                f'{gl_table["Team"].notna().sum() // 2} games · {df_odds["sportsbook"].nunique()} book(s)</p>',
                unsafe_allow_html=True,
            )
            st.dataframe(gl_table, use_container_width=True, hide_index=True, height=560)
            csv_odds = df_odds.to_csv(index=False).encode("utf-8")
            st.download_button("⬇ Export CSV (raw)", csv_odds, "blast_game_lines.csv", "text/csv")
    else:
        # Raw row view for props / all
        st.markdown(
            f'<p style="color:{MUTED}; font-size:0.8rem;">{len(df_odds):,} rows</p>',
            unsafe_allow_html=True,
        )

        # Build base columns
        cols_to_select = [
            "player_name", "market_label", "market", "sportsbook",
            "odds_american", "implied_prob", "game_date", "fetched_at"
        ]
        has_point = "point" in df_odds.columns
        if has_point:
            cols_to_select.insert(4, "point")
        has_model = "model_prob" in df_odds.columns and "edge" in df_odds.columns
        if has_model:
            cols_to_select += ["model_prob", "edge"]

        display_odds = df_odds[cols_to_select].copy()
        if has_point:
            display_odds["Line"] = display_odds["point"].apply(
                lambda x: str(x) if pd.notna(x) else "—"
            )
        # Build matchup column: show opposing pitcher if available, else team matchup
        has_opp = "opposing_pitcher" in df_odds.columns
        has_teams = "home_team" in df_odds.columns and "away_team" in df_odds.columns
        has_matchup = has_opp or has_teams
        if has_matchup:
            def _build_matchup(row):
                opp = row.get("opposing_pitcher")
                if pd.notna(opp) and opp and opp != "TBD":
                    return f"vs {opp}"
                home = row.get("home_team")
                away = row.get("away_team")
                if pd.notna(home) and pd.notna(away):
                    return f"{away} @ {home}"
                return "—"

            display_odds["Matchup"] = df_odds.apply(_build_matchup, axis=1)

        display_odds["Type"] = display_odds["market"].apply(
            lambda m: "Game Line" if m in GAME_LINE_KEYS else "Player Prop"
        )
        display_odds["Implied Prob"] = display_odds["implied_prob"].apply(
            lambda x: f"{x*100:.1f}%" if pd.notna(x) else "—"
        )
        display_odds["Odds"] = display_odds["odds_american"].apply(_fmt_odds)
        display_odds["Fetched"] = display_odds["fetched_at"].dt.strftime("%b %d, %H:%M UTC")

        if has_model:
            display_odds["Model Prob"] = display_odds["model_prob"].apply(
                lambda x: f"{x*100:.1f}%" if pd.notna(x) else "—"
            )
            # Keep numeric edge for proper sorting, format as percentage string
            display_odds["Edge"] = display_odds["edge"].apply(
                lambda x: round(x * 100, 1) if pd.notna(x) else None
            )
            display_odds = display_odds.sort_values("Edge", ascending=False, na_position="last")
            display_odds["Edge"] = display_odds["Edge"].apply(
                lambda x: f"+{x:.1f}%" if pd.notna(x) and x > 0 else (f"{x:.1f}%" if pd.notna(x) else "—")
            )

        display_odds = display_odds.rename(columns={
            "player_name": "Team / Player",
            "market_label": "Market",
            "sportsbook": "Book",
            "game_date": "Game Date",
        })

        final_cols = ["Team / Player", "Market"]
        if has_point:
            final_cols += ["Line"]
        if has_matchup:
            final_cols += ["Matchup"]
        final_cols += ["Type", "Book", "Odds", "Implied Prob"]
        if has_model:
            final_cols += ["Model Prob", "Edge"]
        final_cols += ["Game Date", "Fetched"]
        display_odds = display_odds[final_cols]

        st.dataframe(display_odds, use_container_width=True, hide_index=True, height=560)
        csv_odds = df_odds.to_csv(index=False).encode("utf-8")
        st.download_button("⬇ Export CSV", csv_odds, "blast_odds.csv", "text/csv", key="odds_csv")

    # --- Player Insights Section ---
    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown("#### Player Insights")
    st.markdown(
        f'<p style="color:{MUTED}; font-size:0.82rem;">'
        f'Search for a pitcher to see their last 5 games and matchup history. '
        f'Data comes from pitcher gamelogs stored by the pipeline.</p>',
        unsafe_allow_html=True,
    )

    col_pi1, col_pi2 = st.columns([2, 2])
    with col_pi1:
        insight_player = st.text_input("Pitcher Name", key="insight_player", placeholder="e.g. Logan Webb")
    with col_pi2:
        insight_opp = st.text_input("Filter by Opponent (optional)", key="insight_opp", placeholder="e.g. NYY")

    if insight_player.strip():
        gl = load_pitcher_gamelogs(insight_player)

        if gl.empty:
            st.info(f"No game log data found for '{insight_player}'. Pitcher gamelogs are populated each pipeline run.")
        else:
            # Apply opponent filter if provided
            gl_matchup = gl.copy()
            if insight_opp.strip() and "opp_team" in gl.columns:
                gl_matchup = gl[gl["opp_team"].str.contains(insight_opp.strip(), case=False, na=False)]

            col_g1, col_g2 = st.columns(2)

            with col_g1:
                st.markdown("##### Last 5 Games")
                recent_5 = gl.head(5).copy()
                if not recent_5.empty:
                    display_gl = recent_5.rename(columns={
                        "pitcher_name": "Pitcher",
                        "game_date": "Date",
                        "SO": "K",
                        "HA": "Hits Allowed",
                        "Outs": "Outs",
                        "K_pct": "K%",
                        "opp_team": "Opponent",
                    })
                    if "K%" in display_gl.columns:
                        display_gl["K%"] = display_gl["K%"].apply(
                            lambda x: f"{float(x)*100:.1f}%" if pd.notna(x) else "—"
                        )
                    show_cols = [c for c in ["Pitcher", "Date", "Opponent", "K", "Hits Allowed", "Outs", "K%"] if c in display_gl.columns]
                    st.dataframe(display_gl[show_cols], use_container_width=True, hide_index=True)

                    # Summary stats
                    avg_k = recent_5["SO"].mean() if "SO" in recent_5.columns else 0
                    avg_outs = recent_5["Outs"].mean() if "Outs" in recent_5.columns else 0
                    avg_ha = recent_5["HA"].mean() if "HA" in recent_5.columns else 0
                    st.markdown(
                        f'<p style="color:{MUTED}; font-size:0.82rem;">'
                        f'5-game averages: <b style="color:{TEAL}">{avg_k:.1f} K</b> · '
                        f'<b style="color:{TEAL}">{avg_outs:.1f} Outs</b> · '
                        f'<b style="color:{TEAL}">{avg_ha:.1f} HA</b></p>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.info("No recent games found.")

            with col_g2:
                if insight_opp.strip():
                    st.markdown(f"##### Matchups vs {insight_opp.strip().upper()}")
                else:
                    st.markdown("##### Matchup History")
                    st.markdown(
                        f'<p style="color:{MUTED}; font-size:0.82rem;">'
                        f'Enter an opponent abbreviation above to filter.</p>',
                        unsafe_allow_html=True,
                    )

                if not gl_matchup.empty:
                    matchup_display = gl_matchup.head(5).rename(columns={
                        "pitcher_name": "Pitcher",
                        "game_date": "Date",
                        "SO": "K",
                        "HA": "Hits Allowed",
                        "Outs": "Outs",
                        "K_pct": "K%",
                        "opp_team": "Opponent",
                    }).copy()
                    if "K%" in matchup_display.columns:
                        matchup_display["K%"] = matchup_display["K%"].apply(
                            lambda x: f"{float(x)*100:.1f}%" if pd.notna(x) else "—"
                        )
                    show_cols = [c for c in ["Pitcher", "Date", "Opponent", "K", "Hits Allowed", "Outs", "K%"] if c in matchup_display.columns]
                    st.dataframe(matchup_display[show_cols], use_container_width=True, hide_index=True)

                    if insight_opp.strip() and len(gl_matchup) > 0:
                        avg_k = gl_matchup["SO"].mean() if "SO" in gl_matchup.columns else 0
                        avg_outs = gl_matchup["Outs"].mean() if "Outs" in gl_matchup.columns else 0
                        avg_ha = gl_matchup["HA"].mean() if "HA" in gl_matchup.columns else 0
                        st.markdown(
                            f'<p style="color:{MUTED}; font-size:0.82rem;">'
                            f'vs {insight_opp.strip().upper()} averages ({len(gl_matchup)} starts): '
                            f'<b style="color:{TEAL}">{avg_k:.1f} K</b> · '
                            f'<b style="color:{TEAL}">{avg_outs:.1f} Outs</b> · '
                            f'<b style="color:{TEAL}">{avg_ha:.1f} HA</b></p>',
                            unsafe_allow_html=True,
                        )
                elif insight_opp.strip():
                    st.info(f"No matchups found vs '{insight_opp}'.")

# ===========================================================================
# TAB 6 — LINE MOVEMENTS
# ===========================================================================
with tab_movements:
    st.markdown("#### Line Movements")
    st.markdown(
        f'<p style="color:{MUTED}; font-size:0.82rem;">'
        f'Tracks when Bovada or Kalshi odds shift by ≥1% implied probability between pipeline runs. '
        f'Negative shift = book raised the implied probability (line got harder to beat).</p>',
        unsafe_allow_html=True,
    )

    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    with col_m1:
        mv_books = ["All", "bovada", "kalshi"]
        sel_mv_book = st.selectbox("Sportsbook", mv_books, key="mv_book")
    with col_m2:
        mv_market_opts = ["All"] + [v for v in MARKET_LABELS.values() if "Moneyline" not in v and "Run Line" not in v and "Total Runs" not in v]
        sel_mv_market = st.selectbox("Market", mv_market_opts, key="mv_market")
    with col_m3:
        sel_mv_player = st.text_input("Player (partial match)", key="mv_player")
    with col_m4:
        sel_mv_min = st.slider("Min prob shift (%)", min_value=1, max_value=20, value=1, key="mv_min")

    df_mv = load_line_movements(sel_mv_book, sel_mv_market, sel_mv_player, sel_mv_min / 100)

    if df_mv.empty:
        st.info(
            "No line movements detected yet. Movements are logged each time `run_mlb_pipeline.py` runs "
            "and finds odds that changed since the previous run.\n\n"
            "**First-time setup:** run `migrate_add_line_movements.sql` in your Supabase SQL Editor."
        )
    else:
        def _fmt_odds(val):
            if pd.isna(val): return "—"
            return f"+{int(val)}" if val > 0 else str(int(val))

        def _fmt_shift(val):
            if pd.isna(val): return "—"
            pct = float(val) * 100
            sign = "▲" if pct > 0 else "▼"
            color = RED if pct > 0 else GREEN
            return f"{sign} {abs(pct):.1f}%"

        st.markdown(
            f'<p style="color:{MUTED}; font-size:0.8rem;">{len(df_mv):,} movements</p>',
            unsafe_allow_html=True,
        )

        display_mv = df_mv.copy()
        def _fmt_point(val):
            if pd.isna(val) or val is None: return "—"
            v = float(val)
            return str(int(v)) if v == int(v) else str(v)

        display_mv["Old Line"]  = display_mv["old_point"].apply(_fmt_point)
        display_mv["New Line"]  = display_mv["new_point"].apply(_fmt_point)
        display_mv["Old Odds"]  = display_mv["old_odds"].apply(_fmt_odds)
        display_mv["New Odds"]  = display_mv["new_odds"].apply(_fmt_odds)
        display_mv["Old Prob"]  = display_mv["old_implied_prob"].apply(lambda x: f"{float(x)*100:.1f}%" if pd.notna(x) else "—")
        display_mv["New Prob"]  = display_mv["new_implied_prob"].apply(lambda x: f"{float(x)*100:.1f}%" if pd.notna(x) else "—")
        display_mv["Shift"]     = display_mv["prob_shift"].apply(_fmt_shift)
        display_mv["Detected"]  = display_mv["detected_at"].dt.strftime("%b %d, %H:%M UTC")
        display_mv = display_mv.rename(columns={
            "player_name":  "Player",
            "market_label": "Market",
            "sportsbook":   "Book",
            "game_date":    "Game Date",
        })
        display_mv = display_mv[["Player", "Market", "Book", "Game Date", "Old Line", "Old Odds", "New Line", "New Odds", "Old Prob", "New Prob", "Shift", "Detected"]]
        st.dataframe(display_mv, use_container_width=True, hide_index=True, height=560)

        # Prob shift distribution chart
        fig_mv = px.histogram(
            df_mv, x=df_mv["prob_shift"] * 100,
            nbins=40,
            labels={"x": "Probability Shift (%)"},
            title="Distribution of Line Movements",
            template=PLOTLY_TEMPLATE,
            color_discrete_sequence=[TEAL],
        )
        fig_mv.update_layout(
            paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
            font_color=TEXT, showlegend=False,
            margin=dict(t=40, b=20, l=0, r=0),
            height=300,
        )
        st.plotly_chart(fig_mv, use_container_width=True)

        csv_mv = df_mv.to_csv(index=False).encode("utf-8")
        st.download_button("⬇ Export CSV", csv_mv, "blast_line_movements.csv", "text/csv")
