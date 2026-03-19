# B.L.A.S.T. MLB Pipeline — TODO

## Pre-Season 2026

- [ ] **Retrain ML models on 2023–2025 data**
  - `build_dataset.py` defaults updated to `2023-04-01` → `2025-09-30`
  - Run `python model/build_dataset.py` to rebuild CSVs (takes several minutes for 3 seasons of Statcast data)
  - Run `python model/train_model.py` to retrain all 8 market models
  - Verify `*_metadata.json` files are generated with updated AUC/Brier scores
  - Previous training data only covered ~2 months of 2023 — this is a significant upgrade

## Backlog

- [ ] **Starting lineup check** — Filter to confirmed starters using an MLB lineup API (e.g. `python-mlb-statsapi`)
- [ ] **Pitcher BF approximation** — Replace IP-based estimate (`ip * 3.5`) with actual per-game Statcast BF logs
- [ ] **Rolling game logs at inference** — True probability currently uses full-season averages; a game log database with actual last-N-game stats would improve accuracy
