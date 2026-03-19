# B.L.A.S.T. ML Model — How It Works

## Overview

The pipeline uses **8 calibrated Random Forest classifiers** — one per betting market — to estimate the true probability that a player hits a prop bet. This probability is compared against the sportsbook's implied probability (with vig removed) to identify positive expected value (+EV) opportunities.

---

## The 8 Markets

| Market | Type | Hit Condition |
|---|---|---|
| `batter_home_runs` | Batter | HR ≥ 1 in the game |
| `batter_hits` | Batter | H ≥ 1 in the game |
| `batter_total_bases_1.5` | Batter | TB ≥ 2 in the game |
| `batter_strikeouts` | Batter | SO ≥ 1 as batter |
| `pitcher_strikeouts` | Pitcher | K ≥ 5 in the start |
| `pitcher_outs` | Pitcher | Outs recorded ≥ 16 (≈ 5.1 IP) |
| `pitcher_hits_allowed` | Pitcher | H allowed ≥ 5 |
| `pitcher_walks_allowed` | Pitcher | BB ≥ 2 |

---

## Step 1: Building Training Data (`model/build_dataset.py`)

**Data source:** Statcast game logs via `pybaseball.statcast()` (default: full 2024 season).

### Batter Pipeline
1. Groups at-bats by `batter + game_date` to produce per-game totals: PA, AB, H, HR, SO, TB.
2. Computes a **10-game rolling average** for each stat (shifted by 1 game to avoid data leakage — only past games inform the prediction).
3. Creates binary target columns from actual game results: `Target_HR`, `Target_Hit`, `Target_TB_Over_1_5`, `Target_SO`.

### Pitcher Pipeline
1. Groups pitches by `pitcher + game_date` to produce per-start totals: BF, SO, BB (BBA), H allowed, Outs.
2. Computes a **5-game rolling average** for each stat (shifted by 1).
3. Creates binary targets: `Target_SO_Over_4_5`, `Target_Outs_Over_15_5`, `Target_HA_Over_4_5`, `Target_BBA_Over_1_5`.

The shorter 5-game window for pitchers reflects that starting pitchers take the mound every 5 days — a 5-game window covers roughly one month of starts.

---

## Step 2: Training Models (`model/train_model.py`)

Each market gets its own independently trained model.

### Model Architecture

```
RandomForestClassifier(
    n_estimators   = 100,    # 100 decision trees
    max_depth      = 3,      # shallow trees to reduce overfitting
    class_weight   = 'balanced'  # compensates for rare events (e.g. HR)
)
```

`class_weight='balanced'` is critical for rare props like home runs — without it, the model would just predict "no HR" on every plate appearance and be technically accurate but useless.

### Probability Calibration

Raw Random Forest output probabilities are often overconfident. The model is wrapped in:

```
CalibratedClassifierCV(method='isotonic', cv=5)
```

Isotonic regression fits a monotonic function that maps the raw model output to actual observed frequencies. After calibration, a model predicting 30% should be right about 30% of the time.

### Training Split

80/20 stratified train/test split (`stratify=y`) ensures both splits contain proportional positive/negative examples — important when positive events are rare.

### Saved Artifacts

For each market:
- `model/trained_models/{market}_model.pkl` — the calibrated classifier
- `model/trained_models/{market}_metadata.json` — training date, AUC, Brier score, feature list, positive class rate

---

## Step 3: Inference at Runtime (`tools/ev_calculator.py`)

At runtime, the pipeline doesn't have true rolling game logs — it has season aggregates from `pybaseball.batting_stats()` / `pybaseball.pitching_stats()`.

To approximate rolling features, season totals are divided by games played and multiplied by the window size:

### Batter Feature Approximation
```python
rolling_10_HR = (season_HR / games_played) * 10
rolling_10_H  = (season_H  / games_played) * 10
# ... and so on for PA, AB, SO, TB
```

### Pitcher Feature Approximation
```python
rolling_5_SO   = (season_SO / games_played) * 5
rolling_5_Outs = (IP * 3) / games_played * 5   # IP * 3 = total outs
rolling_5_BF   = (IP * 3.5) / games_played * 5  # approximated, no Statcast BF in season stats
```

These approximations assume the player's current season rate is representative of recent form. They lose accuracy early in the season (small sample) and miss hot/cold streaks.

---

## Step 4: EV Calculation

### Implied Probability (from the sportsbook)

American odds are converted to a no-vig probability:

```python
# Example: -130 odds
raw = 130 / (130 + 100) = 0.565

# Strip ~5% sportsbook margin
no_vig = 0.565 / 1.05 = 0.538
```

For positive odds: `raw = 100 / (odds + 100)`

### Edge Calculation

```
edge = model_true_prob - implied_prob
```

If `edge >= EV_THRESHOLD` (default: 5%), a Discord alert fires.

**Example:**
- Model says pitcher K > 4.5 has 62% true probability
- FanDuel implies 55% (after vig removal)
- Edge = 7% → alert fires

---

## Known Limitations

| Limitation | Impact | Future Fix |
|---|---|---|
| Season aggregates used instead of true rolling logs | Misses hot/cold streaks; inaccurate early in season | Store per-game logs in Supabase |
| `rolling_5_BF` approximated from IP | Batters-faced estimate is imprecise | Use Statcast per-start BF data |
| No starting lineup check | Evaluates all players with posted odds, including benched players | Integrate MLB Stats API for confirmed starters |
| Vig removal uses fixed 5% assumption | Different books have different margins | Per-market two-sided vig calculation |

---

## Retraining (Annual, Pre-Season)

Models should be retrained each spring using the prior full season:

```bash
# 1. Fetch Statcast data and build CSVs
python model/build_dataset.py

# 2. Train all 8 classifiers
python model/train_model.py
```

Check `model/trained_models/*_metadata.json` for AUC and Brier scores after training. A Brier score below 0.20 and AUC above 0.60 are reasonable baselines for these binary prop markets.
