# MLB EV Calculation SOP

## Goal
Receive raw statistical inputs from `DataIngestor` (`pybaseball`) and Live Odds from `The Odds API`, calculate a "True Probability" baseline, and determine if an edge > 5% exists (Positive Expected Value).

## The Math (+EV Formula)

### 1. Converting American Odds to Implied Probability
**The Odds API** returns American odds (e.g., +150, -110).
*   **Positive Odds (e.g., +150):** `100 / (Odds + 100)` -> `100 / 250 = 40%`
*   **Negative Odds (e.g., -110):** `|Odds| / (|Odds| + 100)` -> `110 / 210 = 52.38%`

### 2. Calculating Edge
`Edge = True_Probability - Implied_Probability`
*Constraint: Only return `is_ev = True` if `Edge >= 0.05` (5%).*

## True Probability Heuristics (Proof of Concept)
*Note: A true production MLB model requires machine learning. For this B.L.A.S.T. prototype, we use deterministic statistical weighting heuristics.*

### Market: `batter_home_runs`
`Base Probability (League Avg HR/PA)` = ~3%
*   **Modifier 1 (Batter Barrel Rate):** If `barrel_rate > 10%`, +1% true prob.
*   **Modifier 2 (Pitcher HR/9):** If opposing pitcher `hr_per_9 > 1.5`, +1% true prob.
*   *Stadium/Weather Modifiers can be added here.*

### Market: `pitcher_strikeouts` (Over/Under Line, e.g., O 5.5)
We estimate the pitcher will face ~22 batters (roughly 5-6 innings).
`Expected Ks = 22 * pitcher_k_percent * opposing_team_k_modifier`
If `Expected Ks > TheOddsAPI_Line + 0.5`, the "Over" is highly probable scenarios, we assign a True Probability of 60%. Otherwise, 40%.

## Execution Workflow (`ev_calculator.py`)
1.  **`calculate_implied_prob(american_odds)`**: Returns float.
2.  **`generate_true_prob(market, player_stats, opponent_stats)`**: Returns float based on heuristics above.
3.  **`check_ev(true_prob, implied_prob)`**: Returns Dict `{'is_ev': bool, 'edge': float}`.
