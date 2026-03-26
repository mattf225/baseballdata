# B.L.A.S.T. MLB Pipeline — Claude Code Guide

## Project Purpose
Automatically identify positive expected value (+EV) MLB bets by comparing ML model probabilities against live sportsbook player prop odds, and instantly alert via Discord.

Full project spec lives in [gemini.md](gemini.md). Always defer to it for north-star decisions.

---

## Architecture (4 Layers)

| Layer | Location | Purpose |
|---|---|---|
| Architecture | `architecture/*.md` | SOPs — update these before touching code |
| Navigation | `run_mlb_pipeline.py` | Orchestrates tool execution, owns pipeline flow |
| Tools | `tools/*.py` | Deterministic scripts — each has one job |
| ML | `model/` | Training pipeline + `.pkl` model artifacts |

### Data Flow
```
Bovada API   → bovada_client.py  → run_mlb_pipeline.py
Kalshi API   → kalshi_client.py  ↗        ↓
pybaseball   → api_client.py    ↗   ev_calculator.py  (lazy-loads .pkl models)
                                          ↓
                                   db_client.py  (daily spam gate via Supabase)
                                          ↓
                                   notifier.py  (Discord webhooks — separate channels for Bovada/Kalshi)
```

---

## Key Files

| File | Role |
|---|---|
| `run_mlb_pipeline.py` | Entry point. Validates env, fetches odds (Bovada + Kalshi), then stats. Archives odds with model_prob/edge. |
| `tools/bovada_client.py` | Fetches MLB player props from Bovada's public API. Parses market descriptions with regex. |
| `tools/kalshi_client.py` | Fetches MLB props from Kalshi exchange API. Filters by model-matching thresholds. |
| `tools/api_client.py` | DataIngestor: season stats (pybaseball). No longer used for odds fetching. |
| `tools/ev_calculator.py` | Implied prob, true prob (ML), edge check. EV_THRESHOLD is configurable. |
| `tools/db_client.py` | Supabase: log_alert(), is_spam() (same-day filter), odds archiving, line movements, pitcher gamelogs. |
| `tools/notifier.py` | Discord embed with separate webhooks for Bovada (main) and Kalshi alerts. |
| `tools/gamelog_updater.py` | Fetches yesterday's Statcast, upserts pitcher gamelogs to Supabase. |
| `model/build_dataset.py` | Builds CSVs from Statcast. Fetches statcast ONCE for both pipelines. |
| `model/train_model.py` | Trains 8 Random Forest classifiers + saves `*_metadata.json` per model. |
| `dashboard/app.py` | Streamlit monitoring dashboard with 7 tabs. |
| `dashboard/backfill_outcomes.py` | Resolves alert outcomes (hit/miss) from Statcast data. |

---

## Environment Setup

Copy `.env.example` to `.env` and fill in all values:

```bash
cp .env.example .env
```

Required vars:
- `SUPABASE_URL` — Supabase project URL
- `SUPABASE_SERVICE_ROLE_KEY` — **Service role key** (not anon key; needed for inserts)
- `DISCORD_WEBHOOK_URL` — Discord channel webhook (Bovada / main alerts)

Optional:
- `ODDS_API_KEY` — The Odds API (not currently used, kept for future)
- `KALSHI_API_KEY` — Kalshi exchange API key
- `DISCORD_WEBHOOK_URL_KALSHI` — Separate Discord webhook for Kalshi alerts
- `EV_THRESHOLD` — Edge required to trigger alert (default: `0.05` = 5%)
- `ALLOW_SPRING_TRAINING` — Set to any value to run pipeline outside regular season

---

## Running the Pipeline

```bash
# Run pipeline once (regular season only by default)
python run_mlb_pipeline.py

# Run during spring training / off-season
ALLOW_SPRING_TRAINING=true python run_mlb_pipeline.py

# Test individual tools
python tools/test_notification.py     # Tests both Discord webhooks
python tools/test_bovada_connection.py
python tools/test_kalshi_connection.py
python tools/test_db_connection.py
```

---

## Retraining ML Models (Annual, Pre-Season)

```bash
# 1. Build training datasets (default: 2023–2025 seasons)
#    Override dates with args: python model/build_dataset.py 2023-04-01 2025-09-30
python model/build_dataset.py

# 2. Train all 8 market models
python model/train_model.py
```

Model artifacts saved to `model/trained_models/`:
- `{market}_model.pkl` — calibrated Random Forest classifier
- `{market}_metadata.json` — training date, AUC, Brier score, data source

---

## Supported Markets

**Batter:** `batter_home_runs`, `batter_hits`, `batter_total_bases_1.5`, `batter_strikeouts`

**Pitcher:** `pitcher_strikeouts`, `pitcher_outs`, `pitcher_hits_allowed`, `pitcher_walks_allowed`

Note: Bovada/Kalshi send `batter_total_bases` — this is remapped to `batter_total_bases_1.5` internally in `run_mlb_pipeline.py`.

---

## Odds Sources

### Bovada (Primary)
- Undocumented public JSON API — no key required
- Parses market descriptions with regex: `"{Stat Type} - {Player Name} ({Team})"`
- Only processes "Over" outcomes (models predict P(over threshold))
- Display groups: "Pitcher Props" and "Player Props"

### Kalshi (Exchange)
- REST API at `api.elections.kalshi.com` — requires API key
- Only processes markets where `floor_strike` matches model thresholds
- Filters: skip odds ≤ -185 (heavily juiced) and ≥ +9900 (extreme longshots)
- Converts `yes_ask_dollars` to American odds
- Alerts routed to separate Discord webhook (`DISCORD_WEBHOOK_URL_KALSHI`)

---

## Coding Conventions

- **Architecture first:** Update `architecture/*.md` SOPs before modifying tool code.
- **Logging:** Use `logger` (not `print`) in `run_mlb_pipeline.py`. Tools use `print` for simplicity.
- **Player name matching:** `ev_calculator._normalize_name()` strips accents and lowercases — use this when comparing names across data sources.
- **Model loading:** `ev_calculator` lazy-loads `.pkl` files on first call via `_load_models()`. Do not move back to module-level loading.
- **EV threshold:** Never hardcode `0.05`. Always read from `EV_THRESHOLD` env var via the constant at top of `ev_calculator.py`.
- **Supabase writes:** Always use `SUPABASE_SERVICE_ROLE_KEY`. The anon key is read-only.
- **Spam gate:** One alert per player + market + sportsbook per day (resets midnight UTC).

---

## Key Constraints

- Only alert if edge ≥ EV_THRESHOLD (default 5%)
- No duplicate alerts for same player + market + sportsbook on the same day
- Skip Kalshi odds ≤ -185 (juiced) and ≥ +9900 (longshots)
- Skip odds with `abs(price) > 50,000` as likely API errors
- Discord tone: purely analytical, data-only, no commentary
- Do NOT include players not in the starting lineup *(lineup check not yet implemented — future work)*

---

## CI/CD

### Pipeline: `.github/workflows/mlb_cron.yml`
- Runs hourly 12pm–2am EST (UTC: 16:00–06:00), April–October
- Capped at 15 runs/day via cron expression `0 16-23,0-6 * 4-10 *`
- Manual trigger available via `workflow_dispatch`
- Required GitHub Secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `ODDS_API_KEY`, `DISCORD_WEBHOOK_URL`, `DISCORD_WEBHOOK_URL_KALSHI`, `KALSHI_API_KEY`

### Outcome Backfill: `.github/workflows/backfill_outcomes.yml`
- Runs daily at 8am ET (12:00 UTC), April–October
- Resolves pending alerts as hit/miss using Statcast data
- Required GitHub Secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`

---

## Supabase Tables & Migrations

Run these SQL migrations in the Supabase SQL Editor:

| Migration File | Table | Purpose |
|---|---|---|
| `dashboard/migrate_add_outcome.sql` | `mlb_alert_log` | Adds `actual_outcome` column |
| `dashboard/migrate_add_pitcher_gamelogs.sql` | `pitcher_gamelogs` | Per-start pitcher stats (SO, HA, Outs, K%, opp_team) |
| `dashboard/migrate_add_line_movements.sql` | `mlb_line_movements` | Tracks odds shifts between pipeline runs |
| `dashboard/migrate_add_model_prob.sql` | `mlb_odds_log` | Adds `model_prob` and `edge` columns |
| `dashboard/migrate_add_alert_point.sql` | `mlb_alert_log` | Adds `point` (line) column |
| `dashboard/migrate_add_movement_points.sql` | `mlb_line_movements` | Adds `old_point` and `new_point` columns |

**Important:** Pitcher gamelogs columns must use quoted uppercase names (`"BF"`, `"SO"`, `"HA"`, `"Outs"`, `"BBA"`, `"K_pct"`).

---

## Monitoring Dashboard

Located in `dashboard/`. Built with Streamlit + Plotly.

### First-time setup
```bash
pip install -r dashboard/requirements_dashboard.txt

# 1. Run all SQL migrations in Supabase SQL Editor
# 2. Backfill outcomes (after games are final)
python dashboard/backfill_outcomes.py

# 3. Launch dashboard
streamlit run dashboard/app.py
```

### Dashboard Tabs
| Tab | Contents |
|---|---|
| Overview | KPI cards, alert volume chart, market mix donut, recent alerts |
| Alert History | Filterable table (market/book/outcome/date/line), CSV export |
| Model Accuracy | Win rate by market, weekly trend, edge histogram, calibration chart |
| P&L & Retraining | Cumulative P&L, ROI by edge bucket, P&L by market/sportsbook, biggest misses, CSV export for retraining |
| Daily EV Summary | Daily alert count + edge overlay, market mix stacked bar, best/worst days |
| Odds Explorer | Live odds with model prob, edge, and line. Player insights section with pitcher last 5 games and matchup history |
| Line Movements | Tracks odds shifts ≥1% implied probability between pipeline runs |

### Outcome Resolution Logic (`backfill_outcomes.py`)
Fetches Statcast for each alert's game date, evaluates the actual result:

| Market | Hit condition |
|---|---|
| batter_home_runs | HR ≥ 1 |
| batter_hits | H ≥ 1 |
| batter_total_bases_1.5 | TB ≥ 2 |
| batter_strikeouts | SO ≥ 1 (as batter) |
| pitcher_strikeouts | SO ≥ 5 |
| pitcher_outs | Outs ≥ 16 |
| pitcher_hits_allowed | HA ≥ 5 |
| pitcher_walks_allowed | BB ≥ 2 |

`actual_outcome` in `mlb_alert_log`: `NULL` = pending, `TRUE` = hit, `FALSE` = miss.

---

## Deployment (Free Tier)

- **Pipeline + Backfill:** GitHub Actions (free for public repos)
- **Dashboard:** Streamlit Community Cloud (free, deploy from GitHub)
- **Database:** Supabase free tier (500MB)
- **Odds Sources:** Bovada (free, no key), Kalshi (free API key)
- **Alerts:** Discord webhooks (free)

---

## Known Limitations / Future Work

1. **Starting lineup check** — Pipeline currently evaluates all players with odds. Need to integrate an MLB lineup API (e.g. `python-mlb-statsapi`) to filter to confirmed starters only.
2. **Pitcher BF approximation** — `rolling_5_BF` is estimated from IP (`ip * 3.5`). Replace with actual per-game Statcast logs when possible.
3. **Batter game logs** — Dashboard player insights only supports pitcher gamelogs. Batter game log storage not yet implemented.
4. **Kalshi rate limiting** — Kalshi API returns 429 errors on rapid requests. Could add retry/backoff logic.
