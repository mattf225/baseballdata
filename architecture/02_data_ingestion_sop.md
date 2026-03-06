# MLB Data Ingestion SOP (pybaseball)

## Goal
Ingest relevant statistical features from MLB Statcast (via `pybaseball`) so that `ev_calculator.py` has the underlying probabilities needed to compare against implied sportsbook odds. We focus on specific Player Prop markets: Home Runs and Strikeouts.

## Dependencies
* `pybaseball`
* Pandas

## Target Markets & Core Features

### 1. Market: `batter_home_runs`
To calculate the true probability of a batter hitting a Home Run today, we need:
1.  **Batter Profiling:**
    *   `avg_exit_velo`: Average Exit Velocity (mph). Higher = more HR potential.
    *   `launch_angle_avg`: Average Launch Angle. Sweet spot for HRs is generally 25-30 degrees.
    *   `barrel_rate`: Percentage of batted balls that are "Barrels" (optimal exit velo + launch angle).
2.  **Opposing Pitcher Profiling:**
    *   `hr_per_9`: Home Runs allowed per 9 innings by the starting pitcher.
3.  **Environmental Factors (To be added via python-mlb-statsapi later):**
    *   Stadium Park Factor (e.g., Coors Field vs. Petco Park).
    *   Wind direction.

### 2. Market: `pitcher_strikeouts`
To calculate the true probability of a pitcher striking out X batters today:
1.  **Pitcher Profiling:**
    *   `k_percent`: Strikeout rate (Strikeouts / Batters Faced).
    *   `whiff_percent`: Pitch Whiff Rate (Swings and Misses / Total Swings).
2.  **Opposing Batter Profiling (Team Level):**
    *   `team_k_rate`: The opposing lineup's aggregate strikeout percentage against that pitcher's handedness (LHP vs RHP).

## Ingestion Workflow (`api_client.py` -> `DataIngestor` class)
1.  **`fetch_batter_stats(player_name)`**: Uses `pybaseball.batting_stats().loc[player_name]` to retrieve `barrel_rate` and `exit_velocity`.
2.  **`fetch_pitcher_stats(player_name)`**: Uses `pybaseball.pitching_stats().loc[player_name]` to retrieve `k_percent` and `hr_per_9`.

These outputs are packaged into a JSON dictionary and passed to the Layer 2 `run_mlb_pipeline.py` orchestrator.
