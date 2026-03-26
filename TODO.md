# B.L.A.S.T. MLB Pipeline — TODO

## Pre-Season 2026

- [x] **Retrain ML models on 2023–2025 data** *(completed 2026-03-24)*
  - `build_dataset.py` defaults updated to `2023-04-01` → `2025-09-30`
  - All 8 models retrained with updated AUC/Brier scores

## Player Insights Enhancements

- [ ] **Add CSW% (Called Strikes + Whiffs %)** — Fetch from Statcast pitch-level data, store in pitcher gamelogs, display in Player Insights
- [ ] **Add Whiff rate** — Track swinging strikes / total swings per game, surface in Player Insights last 5 games and matchup tables

## Backlog

- [ ] **Starting lineup filter** — `mlb_schedule.py` provides rosters, but pipeline doesn't yet skip players not in confirmed starting lineup (~1-2 hrs pre-game)
- [x] **Pitcher BF from Statcast** — `gamelog_updater.py` now stores actual BF per game from Statcast (replaces IP × 3.5 estimate)
- [x] **Rolling game logs at inference** — Pitcher gamelogs backfilled from Statcast; `ev_calculator.py` uses last-N-game stats via `pitcher_gamelogs_cache`
