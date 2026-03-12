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
The Odds API → api_client.py → run_mlb_pipeline.py
pybaseball    ↗                       ↓
                              ev_calculator.py  (lazy-loads .pkl models)
                                      ↓
                              db_client.py  (12-hr spam gate via Supabase)
                                      ↓
                              notifier.py  (Discord webhook)
```

---

## Key Files

| File | Role |
|---|---|
| `run_mlb_pipeline.py` | Entry point. Validates env, fetches odds first, then stats. |
| `tools/api_client.py` | DataIngestor: odds (The Odds API) + season stats (pybaseball) |
| `tools/ev_calculator.py` | Implied prob, true prob (ML), edge check. EV_THRESHOLD is configurable. |
| `tools/db_client.py` | Supabase: log_alert(), is_spam() (12-hr server-side filter) |
| `tools/notifier.py` | Discord embed. MARKET_DISPLAY dict controls label names. |
| `model/build_dataset.py` | Builds CSVs from Statcast. Fetches statcast ONCE for both pipelines. |
| `model/train_model.py` | Trains 8 Random Forest classifiers + saves `*_metadata.json` per model. |

---

## Environment Setup

Copy `.env.example` to `.env` and fill in all values:

```bash
cp .env.example .env
```

Required vars:
- `ODDS_API_KEY` — The Odds API
- `SUPABASE_URL` — Supabase project URL
- `SUPABASE_SERVICE_ROLE_KEY` — **Service role key** (not anon key; needed for inserts)
- `DISCORD_WEBHOOK_URL` — Discord channel webhook

Optional:
- `EV_THRESHOLD` — Edge required to trigger alert (default: `0.05` = 5%)

---

## Running the Pipeline

```bash
# Run pipeline once
python run_mlb_pipeline.py

# Test individual tools
python tools/test_api_connection.py
python tools/test_db_connection.py
python tools/test_notification.py
python tools/mock_alert.py
```

---

## Retraining ML Models (Annual, Pre-Season)

```bash
# 1. Build training datasets (default: 2024 full season)
#    Override dates with args: python model/build_dataset.py 2024-04-01 2024-09-30
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

Note: The Odds API sends `batter_total_bases` — this is remapped to `batter_total_bases_1.5` internally in `run_mlb_pipeline.py`.

---

## Coding Conventions

- **Architecture first:** Update `architecture/*.md` SOPs before modifying tool code.
- **Logging:** Use `logger` (not `print`) in `run_mlb_pipeline.py`. Tools use `print` for simplicity.
- **Player name matching:** `ev_calculator._normalize_name()` strips accents and lowercases — use this when comparing names across data sources.
- **Model loading:** `ev_calculator` lazy-loads `.pkl` files on first call via `_load_models()`. Do not move back to module-level loading.
- **EV threshold:** Never hardcode `0.05`. Always read from `EV_THRESHOLD` env var via the constant at top of `ev_calculator.py`.
- **Supabase writes:** Always use `SUPABASE_SERVICE_ROLE_KEY`. The anon key is read-only.
- **Odds API key:** Always pass via `params={}`, never interpolated into the URL string.

---

## Key Constraints (from gemini.md)

- Only alert if edge ≥ EV_THRESHOLD (default 5%)
- No duplicate alerts for same player + market + sportsbook within 12 hours (Supabase gate)
- Do NOT include players not in the starting lineup *(lineup check not yet implemented — future work)*
- Skip odds with `abs(price) > 50,000` as likely API errors
- Discord tone: purely analytical, data-only, no commentary

---

## CI/CD

GitHub Actions: `.github/workflows/mlb_cron.yml`
- Runs hourly 12pm–2am EST (UTC: 16:00–06:00), April–October
- Capped at 15 runs/day via cron expression `0 16-23,0-6 * 4-10 *`
- Manual trigger available via `workflow_dispatch`
- Required GitHub Secrets: `ODDS_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `DISCORD_WEBHOOK_URL`

---

## Monitoring Dashboard

Located in `dashboard/`. Built with Streamlit + Plotly.

### First-time setup
```bash
pip install -r dashboard/requirements_dashboard.txt

# 1. Run SQL migration in Supabase SQL Editor
#    dashboard/migrate_add_outcome.sql

# 2. Backfill 2025 actual outcomes (fetches Statcast per alert date)
python dashboard/backfill_outcomes.py

# 3. Launch dashboard
streamlit run dashboard/app.py
```

### Dashboard Tabs
| Tab | Contents |
|---|---|
| Overview | KPI cards, alert volume chart, market mix donut, recent alerts |
| Alert History | Filterable table (market/book/outcome/date), CSV export |
| Model Accuracy | Win rate by market, weekly trend, edge histogram, calibration chart |
| Daily EV Summary | Daily alert count + edge overlay, market mix stacked bar, best/worst days |

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

## Known Limitations / Future Work

1. **Starting lineup check** — Pipeline currently evaluates all players with odds. Need to integrate an MLB lineup API (e.g. `python-mlb-statsapi`) to filter to confirmed starters only.
2. **Pitcher BF approximation** — `rolling_5_BF` is estimated from IP (`ip * 3.5`). Replace with actual per-game Statcast logs when possible.
3. **Season aggregate stats** — True probability uses full-season averages, not actual rolling last-N-game logs at inference time. A game log database would improve accuracy significantly.
