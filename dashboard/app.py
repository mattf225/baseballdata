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

MARKET_LABELS = {
    "batter_home_runs":       "Home Run",
    "batter_hits":            "Hit",
    "batter_total_bases_1.5": "Total Bases 1.5",
    "batter_strikeouts":      "Batter K",
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

df_raw = load_alerts()

if df_raw.empty:
    st.warning("No alert data found in Supabase. Run the pipeline first to generate alerts.")
    st.stop()

last_refresh = datetime.now(timezone.utc).strftime("%b %d %Y, %H:%M UTC")
st.markdown(f'<p style="color:{MUTED}; font-size:0.78rem; margin-bottom:1rem;">Data refreshed: {last_refresh} &nbsp;·&nbsp; {len(df_raw):,} total alerts</p>', unsafe_allow_html=True)

tab_overview, tab_history, tab_accuracy, tab_daily = st.tabs([
    "📊 Overview", "📋 Alert History", "🎯 Model Accuracy", "📅 Daily EV Summary"
])


# ===========================================================================
# TAB 1 — OVERVIEW
# ===========================================================================
with tab_overview:
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
    recent.columns    = ["Player", "Market", "Book", "Odds", "Edge", "Sent At", "Outcome"]
    st.dataframe(recent, use_container_width=True, hide_index=True)


# ===========================================================================
# TAB 2 — ALERT HISTORY
# ===========================================================================
with tab_history:
    st.markdown("#### Filter Alerts")

    col_f1, col_f2, col_f3, col_f4 = st.columns(4)

    with col_f1:
        all_markets = ["All"] + sorted(df_raw["market_label"].unique().tolist())
        sel_market  = st.selectbox("Market", all_markets)

    with col_f2:
        all_books = ["All"] + sorted(df_raw["sportsbook"].dropna().unique().tolist())
        sel_book  = st.selectbox("Sportsbook", all_books)

    with col_f3:
        outcome_opts = {"All": None, "✓ Hit": True, "✗ Miss": False, "⏳ Pending": "pending"}
        sel_outcome  = st.selectbox("Outcome", list(outcome_opts.keys()))

    with col_f4:
        date_min = df_raw["game_date"].min()
        date_max = df_raw["game_date"].max()
        sel_dates = st.date_input("Date Range", value=(date_min, date_max),
                                  min_value=date_min, max_value=date_max)

    # Apply filters
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

    display = filtered[[
        "player_name", "market_label", "sportsbook", "odds_formatted",
        "calculated_edge_percentage", "model_prob", "implied_prob",
        "game_date", "actual_outcome"
    ]].copy()

    display["Edge"]          = display["calculated_edge_percentage"].apply(lambda x: f"+{x*100:.1f}%")
    display["Model Prob"]    = display["model_prob"].apply(lambda x: f"{x*100:.1f}%" if pd.notna(x) else "—")
    display["Implied Prob"]  = display["implied_prob"].apply(lambda x: f"{x*100:.1f}%" if pd.notna(x) else "—")
    display["Outcome"]       = display["actual_outcome"].apply(outcome_badge)
    display["Date"]          = display["game_date"].astype(str)

    display = display.rename(columns={
        "player_name": "Player", "market_label": "Market",
        "sportsbook": "Sportsbook", "odds_formatted": "Odds",
    })
    display = display[["Player", "Market", "Sportsbook", "Odds", "Edge",
                        "Model Prob", "Implied Prob", "Date", "Outcome"]]

    st.dataframe(display, use_container_width=True, hide_index=True, height=520)

    csv = filtered.to_csv(index=False).encode("utf-8")
    st.download_button("⬇ Export CSV", csv, "blast_alerts.csv", "text/csv")


# ===========================================================================
# TAB 3 — MODEL ACCURACY
# ===========================================================================
with tab_accuracy:
    resolved = df_raw[df_raw["actual_outcome"].notna()].copy()

    if resolved.empty:
        st.info("Run `python dashboard/backfill_outcomes.py` to populate actual outcomes.")
        st.stop()

    resolved["hit"] = resolved["actual_outcome"].astype(int)

    # ── KPIs ─────────────────────────────────────────────────────────────────
    overall_wr  = resolved["hit"].mean() * 100
    by_market   = resolved.groupby("market_label")["hit"].agg(["mean", "count"]).reset_index()
    by_market.columns = ["Market", "Win Rate", "Alerts"]
    by_market["Win Rate %"] = (by_market["Win Rate"] * 100).round(1)
    best_market  = by_market.loc[by_market["Win Rate"].idxmax(), "Market"] if len(by_market) else "—"

    avg_edge_hits   = resolved[resolved["hit"] == 1]["calculated_edge_percentage"].mean() * 100
    avg_edge_misses = resolved[resolved["hit"] == 0]["calculated_edge_percentage"].mean() * 100

    c1, c2, c3, c4 = st.columns(4)
    with c1: kpi("Overall Win Rate", f"{overall_wr:.1f}%", GREEN if overall_wr >= 50 else RED)
    with c2: kpi("Best Market", best_market, TEAL)
    with c3: kpi("Avg Edge (Hits)",   f"+{avg_edge_hits:.1f}%",   GREEN)
    with c4: kpi("Avg Edge (Misses)", f"+{avg_edge_misses:.1f}%", RED)

    st.markdown("<hr>", unsafe_allow_html=True)

    col_l, col_r = st.columns(2)

    # ── Win Rate by Market ────────────────────────────────────────────────────
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

    # ── Accuracy Over Time ────────────────────────────────────────────────────
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

    # ── Edge Distribution ─────────────────────────────────────────────────────
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

    # ── Calibration Chart ─────────────────────────────────────────────────────
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
# TAB 4 — DAILY EV SUMMARY
# ===========================================================================
with tab_daily:
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

    # ── KPIs ──────────────────────────────────────────────────────────────────
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

    # ── Daily alert count + edge ───────────────────────────────────────────────
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

    # ── Market mix over time (stacked bar) ────────────────────────────────────
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

    # ── Best/worst days table ─────────────────────────────────────────────────
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
