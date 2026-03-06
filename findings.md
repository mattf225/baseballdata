# Project Findings & Discoveries

## Architecture Context
* The architecture separates the system into three layers: SOPs (Architecture), Navigation (Core Logic), and Tools (Python Scripts).
* Relational database (Supabase) acts as the source of truth preventing spam and tracking analytical inputs/outputs.
* Integrations will be required for MLB Data (`pybaseball`), Sportsbook APIs (`The Odds API`), and a Messaging service (Discord).

## MLB Automation & +EV Findings
* **pybaseball:** The gold standard for free Python MLB data. It scrapes Statcast, providing granular pitch-level features (pitch types, exit velocity, launch angle) and team/player stats.
* **The Odds API:** Covers MLB (`baseball_mlb` sport key) and includes player props (`batter_home_runs`, `pitcher_strikeouts`). It returns clean JSON and has a free tier.
* **python-mlb-statsapi:** A useful wrapper for the official MLB Stats API to grab weather, stadium dimensions, and play-by-play.
* **+EV Logic:** Positive Expected Value exists when `True Probability > Implied Probability`. We will generate true probability using a model fed by `pybaseball` stats, and compare it against the `The Odds API` prices.
