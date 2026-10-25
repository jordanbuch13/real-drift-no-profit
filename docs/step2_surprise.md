# Step 2: Match Surprise

**Status:** implemented in `src/step2_surprise.py`, run on the real data 2026-10-07 (probability based surprise, terciles). Re-run 2026-10-08 on the extended event set (2012/13 to 2014/15 European and cup matches from OddsPortal, competitions named from OddsPortal and Wikipedia): 10,038 rows (after the 2026-10-08 Betfair gap fill), 17 matches without a result dropped, tercile cutoffs -0.168 and +0.427. Mean surprise is positive on bookmaker odds, see `docs/issues.md`.

## Context

Step 1 and Step 1b give, for every match of a listed club, what the betting market expected before kickoff (`p_win`, `p_draw`, `p_loss`). This step compares that with what happened and measures the surprise: how much better or worse the result was than the market expected. Step 3 lines the surprise up with stock returns, Step 4 runs the event study and backtest.

**Goal of this step:** one table, one row per club per match, with the surprise, the competition, and how close the match was to the club's previous and next matches.

## Input

`data/processed/match_expectations_all.csv` (Step 1 league rows plus Step 1b european and other rows, with `competition`). 9,382 rows, 14 clubs, 04/08/2012 to 24/05/2026.

## Tasks

### 0. Input fixes (done 2026-10-07, in Step 1b)

Found while writing this spec, fixed in `src/step1b_betfair.py`, logged in `docs/issues.md`:

1. **`competition` was dropped from `match_expectations_all.csv`.** Now kept. League rows get the league name from `league_names` in the config (e.g. `Premier League`); european rows have the openfootball name (OddsPortal gap-fill rows included, they go through the same labelling); other rows have the cup, super cup or inferred label where one was set, else empty (1,292 rows, mostly domestic cups: Betfair files do not name the competition and the OddsPortal backup only covers the Champions League).
2. **Duplicate (club, date), Benfica v Nacional 11/01/2016.** The match was abandoned on 10/01 and replayed on 11/01. Both Betfair markets were within a day of Step 1's date and the league label went to the abandoned one, so the replay was left as an `other` row duplicating the league match. The league label now prefers a market with a result. `_combine` fails on any duplicate (club, date).

### 1. Drop abandoned matches

Rows with no result: the Betfair market went in play but settled without a winner (14), plus Celtic v Legia 06/08/2014 and Fenerbahce v Besiktas 03/05/2018 (not played after the abandoned first leg), which have no score on OddsPortal (17 on the 2026-10-08 run). They are abandoned matches, not missing data, so there is no result to fill in from a backup source. Examples: Nacional v Benfica 10/01/2016 (completed 11/01), Lyon v Marseille 21/11/2021 (bottle thrown at Payet), Ajax v Feyenoord 24/09/2023 (fireworks, finished three days later), Fenerbahce v Galatasaray 07/04/2024 (Super Cup, Fenerbahce walked off), Roma v Udinese 14/04/2024 (Ndicka collapsed, finished 25/04). Where the match was completed or replayed later, Step 1 already has it on the later date.

Log them to `data/processed/surprise_abandoned.csv` with `match_id`, club, date, opponent, competition, and print the count. Do not guess a result.

### 2. Surprise (main measure, probability based)

Score each result from the club's side as win +1, draw 0, loss -1. The market's expected score is `p_win - p_loss`. Surprise is the difference:

```
actual_score   = +1 if W, 0 if D, -1 if L
expected_score = p_win - p_loss
surprise       = actual_score - expected_score        (between -2 and +2)
```

Examples:

| Match | p_win | p_loss | Result | Surprise |
|---|---|---|---|---|
| Heavy favourite wins | 0.80 | 0.06 | W | +0.26 |
| Even match, club wins | 0.38 | 0.33 | W | +0.95 |
| Heavy favourite draws | 0.80 | 0.06 | D | -0.74 |
| Heavy favourite loses | 0.80 | 0.06 | L | -1.74 |
| Underdog draws | 0.20 | 0.55 | D | +0.35 |

Why this and not points (`3·W + D - exp_points`): points weight a draw as a third of a win, which is a league table rule. It does not fit European and cup matches, where there are no points and a draw can mean anything depending on the tie. The probability measure only uses what the market priced. Wins always give a positive surprise, losses always negative, and draws go either way depending on who was favourite.

Properties on the current data: mean +0.03, standard deviation 0.71, median +0.26. The median is positive because the listed clubs are usually favourites, so most results are small positive surprises (favourite wins) and a few are large negative ones (favourite loses).

### 3. Extra columns (robustness checks for Step 4)

| Column | Formula | Why |
|---|---|---|
| `p_outcome` | probability of the result that happened (`p_win`, `p_draw` or `p_loss`) | how likely the market thought the actual result was |
| `info` | `-ln(p_outcome)` | unsigned size of the surprise: 0.22 for a 80% favourite winning, 3.0 for a 5% shock |
| `actual_points` | 3 / 1 / 0 | |
| `surprise_points` | `actual_points - exp_points` | the points based measure, for comparison |

### 4. Surprise buckets

Step 4 needs to say which matches count as good news and bad news. Options:

1. **Sign:** good news if `surprise > 0`. Simple, but almost the same as "wins vs losses": every win is good news, even a 90% favourite beating a bottom side (+0.1), which tells investors almost nothing. About 63% of rows would be good news.
2. **Fixed cutoff:** good news if `surprise >= c`, bad news if `surprise <= -c`, the rest neutral. With `c = 0.5` about 48% of rows are neutral. The cutoff is arbitrary and must be chosen before looking at returns.
3. **Terciles:** split into thirds by surprise. On the current data the cutoffs are about -0.16 and +0.43. Equal sized groups give the event study the same power in each, and it is the common choice in the event study literature.

**Decision (Jordan, 2026-10-07): terciles** as the main buckets, sign as a robustness check. For the event study (Step 4), terciles are computed over the full sample. For the backtest, full sample cutoffs are look-ahead (a 2015 trade would use cutoffs from 2026 results), so Step 4 must compute them from earlier seasons only. Step 2 stores `surprise_sign` and the full sample `surprise_tercile` (`low`, `mid`, `high`), and prints the cutoffs.

### 5. Fixture congestion

Clubs often play two or three times a week. When the next match comes before the drift window ends, its own surprise contaminates the returns. Step 2 records the gaps; Step 3 and Step 4 decide what to do with them once trading days and the window length are known.

Per club, sorted by date, over all kept rows (league, european, other):

| Column | Description |
|---|---|
| `days_since_prev` | calendar days since the club's previous match, empty for its first |
| `days_to_next` | calendar days to its next match, empty for its last |
| `prev_competition_type`, `next_competition_type` | competition type of those matches |
| `matches_next_7d` | number of the club's matches in the 7 days after this one |

Calendar days, not hours: half of the league rows have no kickoff time. Abandoned matches (task 1) and excluded friendlies do not count: an abandoned match is usually replayed within days, and counting both would show a gap that never affected the club's schedule.

On the current data the median gap is 5 days and 21% of matches come 3 days or fewer after the previous one.

### 6. Output

Save to `data/processed/match_surprise.csv`: every column of the input (abandoned rows removed), plus:

| Column | Description |
|---|---|
| actual_score | +1 / 0 / -1 |
| expected_score | `p_win - p_loss` |
| surprise | main measure |
| p_outcome, info | task 3 |
| actual_points, surprise_points | task 3 |
| surprise_sign | `pos`, `neg` (or `zero`, should not happen) |
| surprise_tercile | `low`, `mid`, `high` |
| days_since_prev, days_to_next, prev_competition_type, next_competition_type, matches_next_7d | task 5 |

Keep the code in `src/step2_surprise.py` with a single `build_match_surprise()` entry point, and call it from the notebook under a markdown heading "Match surprise". The surprise formula is a standalone function so a different measure can be swapped in.

## Checks (fail loudly if any break)

1. No duplicate (club, date) rows, and no row without a result after task 1.
2. `surprise` is between -2 and +2, and `surprise > 0` for every win and `< 0` for every loss.
3. `p_outcome` is between 0 and 1, and `info >= 0`.
4. Calibration: mean surprise should be close to 0 if the market is unbiased. Print the mean with its standard error overall, by `competition_type`, by club and by season. Do not fail on it. A mean far from 0 for one source or season points to a data problem; a mean far from 0 for one club would mean the market systematically misprices that club, which is worth reporting.
5. `days_since_prev` of a row equals `days_to_next` of the club's previous row, and no gap is negative.
6. Spot check: print five random rows with result, probabilities and surprise.

## Known limitations to carry forward

1. Surprise is measured at full time against the 1X2 market. European ties decided over two legs or on penalties are scored on the 90 minute result of each leg (Betfair settles match odds at 90 minutes), so a club that goes through on penalties scores a draw.
2. A draw in the second leg of a tie can be good or bad news depending on the first leg. The 1X2 surprise does not see aggregate scores.
3. Odds quality varies by source and period (Pinnacle closing, market average, Betfair last traded, OddsPortal). `odds_source` is kept so Step 4 can check results by source.

## Not in this step

Do not download stock prices, map matches to trading days or choose the event window. Those are Steps 3 and 4.
