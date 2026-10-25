# Step 4: Event Study and Strategy Backtest

**Status:** implemented in `src/step4_event_study.py`, run on the real data 2026-10-09 (spec confirmed by Jordan 2026-10-09). Results below; changes made while running are under "Changes from the spec".

## Context

Step 3 gives one row per club per match with the surprise (Step 2) and event day 0, the first trading day whose close comes after the match (`data/processed/match_events.csv`, 10,038 rows, 2012/13 to 2025/26), and daily adjusted prices for the 14 clubs and their benchmarks (`data/processed/prices.csv`). This step tests the hypothesis and checks whether it can be traded.

**Hypothesis:** prices underreact to the surprise: the day 0 abnormal return moves with the surprise, and the abnormal returns of the following days keep moving the same way (drift). Efficient pricing: no drift. Overreaction: drift the other way.

**Goal:** an estimate of the day 0 reaction and of the drift, with a test, for the whole sample and the agreed splits; a backtest of a strategy that trades the drift, after costs.

## The overlap problem

A club's next match usually falls inside any drift window: median 3 trading days from one day 0 to the next; 92% of matches have at least 1 clean trading day after day 0, 70% at least 2, 48% at least 3, 12% at least 5 (`days_to_next_match_trading`). A fixed window per match ([+1, +5]) would mostly measure the next match. Dropping overlapping matches would keep 12% of the sample, mostly international breaks and the end of seasons.

So the main test is a **panel regression with distributed lags** (task 3): every club trading day's abnormal return is explained by the surprises of all the club's recent matches at once, each at its own lag. Overlapping matches are then separated by the regression instead of being dropped. The classic event study picture (cumulative abnormal returns by tercile) is drawn from the clean matches only, as a description.

## Tasks

### 1. Daily returns

Simple daily returns from `adj_close` per ticker, on the ticker's trading calendar (Step 3). A stale day (no trade) keeps the last price, so its return is 0 and the next trade carries the catch up. Days with `exclude_return` (Roma 30/06/2014) are dropped. Roma ends 12/09/2022.

### 2. Abnormal returns

`AR = r_club - beta × r_benchmark`, local benchmark from the config.

- **beta:** Dimson beta (sum of the coefficients on the benchmark return of days t-1, t and t+1), estimated by OLS over trading days t-260 to t-11, at least 120 returns, recomputed each day. Dimson because stale trading biases plain betas of Porto, Sporting and Celtic towards 0.
- **No alpha.** An estimated one year alpha of a single club stock is mostly noise (often ±50% a year for these stocks) and would add a spurious drift term. Robustness: market model with alpha.
- Match days are not removed from the estimation window: with a match every 3 to 4 days there would be little left. Their effect on beta is small (match surprises are unrelated to market returns).

Output: `data/processed/abnormal_returns.csv` (club, ticker, date, r, r_benchmark, beta, ar, stale), one row per club trading day.

### 3. Main test: distributed lag regression

On the club trading day panel:

```
AR(i, t) = a + sum over k = -3 .. +10 of b_k × S(i, t - k) + e(i, t)
```

`S(i, t - k)`: surprise of club i's match whose day 0 is k trading days before t (0 if none; the sum if two). `b_0` is the day 0 reaction per unit of surprise; `b_1` to `b_10` the drift by day; `b_-3` to `b_-1` a leak check (should be 0: the stock should not move with a surprise before the match).

- **Drift (H1):** `D = b_1 + b_2 + b_3`, three trading days, about the median gap between matches. Underreaction: `D` has the sign of `b_0` and is different from 0. Also reported cumulated to day 5 and 10.
- **Standard errors:** clustered by date (cross-club correlation of residuals on a day). Robustness: Driscoll–Kraay. Not by club: 14 clusters are too few.
- **Tercile version:** the same regression with `high` and `low` indicators (`mid` the baseline) instead of `S`; the tercile is the one stored by Step 2 (full sample cutoffs, fine for the event study, not for the backtest).
- **Minimum detectable drift:** with the residual volatility from the regression, the drift the test would detect with 80% power at 5%. Needed to read a null result ("no drift larger than x").

Output: `data/processed/event_study_coefficients.csv` (specification, split, k, estimate, standard error), and the figure of cumulated `b_k` from -3 to +10 with confidence bands.

### 4. Descriptive event study

Clean matches only: no other match of the club with day 0 within 3 trading days either side. Mean cumulative abnormal return from day -3 to +3 by surprise tercile, with confidence bands. Shows the shape; the test is task 3. (The spec first said -5 to +10: only 6 matches qualify, see "Changes from the spec".)

### 5. Splits

Decided with Jordan, 2026-10-08. Each split is the task 3 regression with the surprise terms interacted with the split.

**Main (always reported, whatever they show):**

| # | Split | Definition | Question |
|---|---|---|---|
| H2 | Good v bad news | `S+ = max(S, 0)` and `S- = min(S, 0)` with separate coefficients | Is the reaction, and the drift, larger for bad surprises? |
| H3 | Competition | `competition_type`: league (6,985 matches), european (1,828), other (1,225) | Is the drift different where more money is at stake (European prize money)? |

H1 (task 3), H2 and H3 are the main family: Holm correction at 5% across the three.

**Backups (exploratory, run in this order, every one run is reported and labelled exploratory):**

| # | Split | Definition | Work |
|---|---|---|---|
| E1 | Stakes | League matches in the last 10 rounds of a season where, before the match, the club is within 6 points of a place that changes its revenue: first, the last Champions League place, the first relegation place. Places per league and season to the config | Done: `src/league_tables.py`. Tables built from all football-data results of the league; places, deductions and checks from Wikipedia final tables (see "E1 stakes") |
| E2 | Form | Sum of the club's previous 5 surprises (all competitions). A match is "against the run" if its surprise has the other sign | Cheap |
| E3 | Period | 2012/13 to 2018/19 v 2019/20 to 2025/26, 7 seasons each | Cheap |

Dropped: previous season's champion (almost the same as the club identity: Juventus won 2012 to 2020, Celtic most seasons; covered by E1 and the club table).

**Descriptive only:** day 0 reaction and drift per club, not tested (14 groups, one standing out proves little; if the Turkish clubs clearly differ, the report says so).

### 6. Robustness (run on H1, H2 and H3)

| Check | Why |
|---|---|
| STOXX Europe 600 as benchmark | Benchmark choice (Step 3 decision) |
| Liquid clubs only: drop Porto, Sporting, Celtic (stale on day 0 for 21%, 17% and 11% of matches) | Stale prices fake drift: a reaction recorded a day late looks like underreaction. Required, not optional |
| Drop `stale_day0` matches | Same |
| Trade to trade returns (return from the last trade before the match to the first trade from day 0) | Same, keeps the illiquid clubs |
| Drop `near_close` matches (264) | Day 0 uncertain |
| Market model with alpha; Driscoll–Kraay errors | Model choices |
| Surprise sign instead of terciles | Step 2 decision |
| Placebo: shuffle surprises across the club's matches (dates kept), 500 times | Distribution of `D` when there is nothing to find; checks the code |
| Match indicators: an indicator of any match at each lag next to the surprise (added while running) | Absorbs the abnormal returns around every match whatever its result (pre-match rise, post-match fall); without it the split into S+ and S- of H2 picks them up, see "Changes from the spec" |

### 7. Backtest

A strategy anyone could have run, only on information available at the time.

- **Signal:** the match's surprise tercile with cutoffs from all earlier seasons only (expanding window); 2012/13 is the burn in, trading 2013/14 to 2025/26.
- **Entry:** close of day 0 (the result is known, the match ended before that close). This trades the drift only, not the day 0 reaction. Variant: open of day 0 (catches the reaction, Yahoo has opens; Roma from Bloomberg `PX_OPEN`).
- **Exit:** close of day +3, or the close before the next match's day 0 if earlier (no position held through the next match). No trade if the next match's day 0 is day +1.
- **Positions:** long after a `high` surprise, short after a `low` one, equal weights, each hedged with beta × the benchmark (index futures or ETFs exist for all benchmarks but the FTSE AIM index: Celtic hedged with the FTSE 250, to note). Two versions reported side by side: **long-short** and **long only** (shorting Porto, Sporting or the Turkish clubs may not be possible or affordable; borrowing fees are not in the data, so long-short is an upper bound).
- **Portfolio:** calendar time: each day the equal weighted mean return of the open positions, cash (0) on days with none. Turns overlapping trades into one daily series.
- **Costs:** half the bid-ask spread per side plus 0.10% commission per side. Spread estimated by Corwin–Schultz from daily high and low (Yahoo), monthly mean; for stocks that trade once a day on most days (high = low on more than half their traded days: Porto 78%, Sporting 76%) Corwin–Schultz returns 0, and Abdi–Ranaldo (close, high and low) is used instead. Roma: Bloomberg bid and ask from 24/06/2019, Roma's median month before. Transaction taxes as applied (rules and thresholds to verify): Italian FTT 0.1% on purchases of Juventus throughout (market value above €500m for much of the period; conservative), none on Lazio and Roma (below); UK stamp duty 0.5% on Celtic purchases before AIM shares were exempted (28/04/2014); none for Lyon (French tax only above €1bn). A line with commission and taxes but no spread shows how much the conclusion depends on the spread estimates.
- **Results:** per version and gross / commission only / net: number of trades, mean and median return per trade, hit rate, annualised return and volatility, Sharpe ratio, t-statistic (Newey–West), maximum drawdown, cost per round trip at which the net return is 0 (break even), beta to the STOXX 600.

Output: `data/processed/backtest_trades.csv`, `backtest_daily.csv`, and the cumulative return figure.

## Reporting rules

1. H1, H2 and H3 are reported whatever they show.
2. Exploratory splits are run in the order E1, E2, E3; each one run is reported, labelled exploratory, without Holm correction.
3. A null main result is a finding: these markets price match news within the day, with the minimum detectable drift as its precision.
4. Robustness results are reported for the main tests in one table.

## Checks

1. Panel: one row per club trading day; betas between -0.5 and 2.5 for liquid clubs (print per club per year).
2. Leak coefficients `b_-3` to `b_-1` near 0; a large one is a timing error to explain.
3. The placebo distribution of `D` is centred on 0.
4. Backtest: no trade uses a cutoff from its own or a later season; entry date = day 0 or later; no position spans the next match's day 0.
5. Spot check: five trades with dates, prices, hedge, costs, net return.

## Decisions

Decided with Jordan, 2026-10-08:

1. Main tests H1 (drift), H2 (good v bad news), H3 (competition type); backups E1 stakes, E2 form, E3 period; previous season's champion dropped; club table descriptive.
2. Every backup run is reported as exploratory; a null main result is reported as a finding.

Confirmed by Jordan, 2026-10-09:

3. Drift window days +1 to +3 for the main test (median gap between matches), +5 and +10 reported.
4. Abnormal returns: Dimson beta, no alpha.
5. Distributed lag panel regression as the main test, standard errors clustered by date.
6. Backtest: entry at the close of day 0, exit at day +3 or before the next match, long-short and long only side by side, Corwin–Schultz spreads.

## Changes from the spec

Made while running, 2026-10-09:

1. **Clean window.** No other match within -5 to +10 trading days leaves 6 of 9,834 matches (a match every 3 to 4 days). Now no other match within 3 trading days either side, plotted from -3 to +3: 2,706 matches. Descriptive only, the tests are unaffected.
2. **Spread estimator.** Corwin–Schultz returns 0 for Porto and Sporting (high = low on most days); Abdi–Ranaldo is used for those two. Abdi–Ranaldo is not used throughout because it returns 0 for the three Turkish clubs and 2.5% for Benfica. Both estimates are in `spreads_monthly.csv`.
3. **H2 is misspecified as written.** Every match, whatever its result, is followed by a fall in the club's abnormal return (about -0.8% from day 0 to +3, after a rise of about 0.4% on days -2 and -1). With S split into S+ (0 or positive) and S- (0 or negative) and nothing absorbing that common fall, the fall loads on S- with a positive coefficient and on S+ with a negative one, which reads as "bad news drifts, good news reverses". With an indicator of any match at each lag (the `match_dummies` variant) the asymmetry is gone. Both are reported: the pre-specified H2 and the corrected one. H1 and H3 hardly change with the indicators (they use S itself, whose mean is close to 0).
4. **Match indicators variant** added to the robustness table (item 3). It also answers the Step 2 note in `issues.md` (the positive mean surprise of league matches would add a constant to a regression on raw surprise): the indicators absorb it.

## Results

Run 2026-10-09: 9,834 listed matches, 49,634 club trading days with an abnormal return. Coefficients are % abnormal return per unit of surprise (surprise runs from -2 to +2: a 70% favourite with a 12% chance of losing who loses is -1.6, a 30% outsider with a 45% chance of losing who wins is +1.15). Files: `event_study_tests.csv`, `event_study_coefficients.csv`, `event_study_clean_car.csv`, `event_study_placebo.csv`, `backtest_*.csv`, `spreads_monthly.csv` in `data/processed/`; figures in `reports/figures/`.

**Event study**

| | Estimate | SE | p | Holm p |
|---|---|---|---|---|
| Day 0 reaction b0 | +1.054% | 0.050 | <0.001 | |
| **H1 drift D (days +1 to +3)** | **+0.227%** | 0.078 | 0.004 | **0.007** |
| Drift to day 5 / day 10 | +0.264% / +0.430% | | 0.009 / 0.002 | |
| Leak (days -3 to -1) | +0.058% | | 0.45 | |
| H2 pre-specified: drift bad +0.515% v good -0.189% | difference +0.70% | | <0.001 | 0.002 |
| H2 with match indicators: drift bad +0.243% v good +0.239% | difference 0.00% | | 0.99 | |
| H3 drift league +0.30%, European +0.12%, other -0.02% | | | 0.33 | 0.33 |

- **H1: underreaction.** About a fifth of the day 0 reaction is added over the next three trading days, and the response keeps growing to day 10 (+0.43%, 40% of day 0). Significant in every robustness variant (p 0.0006 to 0.008), except the surprise sign (p 0.03, a coarser measure). Liquid clubs only: +0.26% (p 0.0006), so stale prices are not the cause; trade to trade returns: +0.22% (p 0.008).
- **Placebo:** shuffled surprises give D centred on -0.015% (sd 0.068%); the actual D is beyond 99.8% of 500 runs.
- **H2: no asymmetry in the drift** once the common match-week pattern is absorbed (see "Changes from the spec"). On day 0 good surprises move prices more than bad ones with the indicators (1.64% v 0.70% per unit); without them the order is reversed, so day 0 asymmetry is not a robust finding either.
- **H3: no difference between competitions** (p 0.22 to 0.83 across variants, 0.08 with the surprise sign). Cup matches (`other`) have half the day 0 reaction of league and European matches.
- **Minimum detectable drift** at 80% power: 0.22% per unit of surprise.
- **Per club** (descriptive): day 0 reaction from 1.3% to 1.7% per unit for Dortmund, Lazio, Roma, Fenerbahce, Besiktas, Benfica, Galatasaray; 0.5% to 0.95% for Ajax, Juventus, Lyon, Porto, Sporting; about 0.1% for Manchester United (not a timing error: no reaction on day -1 or +1 either) and Celtic (0.1% on day 0 and again on day +1: thin trading spreads it out).
- **Match-week pattern** (any match, whatever the result): abnormal returns +0.17% and +0.24% on days -2 and -1, then -0.32%, -0.18%, -0.18%, -0.12% on days 0 to +3. A pre-match rise and post-match fall, like the investor optimism around matches reported in earlier studies; for the report.

**Backtest** (2013/14 to 2025/26, 5,461 trades, 2,681 long)

| Version | Costs | Mean per trade | Median per trade | Sharpe | t (Newey–West) |
|---|---|---|---|---|---|
| Long-short | gross | +0.18% | +0.01% | 0.67 | 2.4 |
| Long-short | commission and taxes only | -0.03% | -0.20% | -0.01 | -0.0 |
| Long-short | net (spread, commission, taxes) | -0.96% | -0.99% | -2.94 | -10.2 |
| Long only | gross | +0.27% | -0.04% | 0.81 | 2.9 |
| Long only | commission and taxes only | +0.06% | -0.24% | 0.29 | 1.0 |
| Long only | net | -0.86% | -1.08% | -2.03 | -7.2 |

- The drift is there before costs, but the gross gain per trade (0.18% long-short, 0.27% long only) is about the size of the commission alone (0.20% a round trip). With estimated spreads (mean round trip cost 1.1%) the strategy loses about 1% per trade. The conclusion does not depend on the spread estimates.
- The long only gross mean is driven by a few large moves (Benfica +60% in two days in March 2014, Roma +35% in October 2013): its median trade loses. The drift is real in the regression but too small and too noisy to trade.
- Beta to the STOXX 600 about 0 (hedged as intended).

**In-sample v out-of-sample** (added 2026-10-13 for the capstone brief). In-sample 2013/14 to 2018/19, out-of-sample 2019/20 to 2025/26 (the E3 split). The rules were fixed in this spec before any backtest was run, and the tercile cutoffs use earlier seasons only (walk-forward), so no parameter was tuned on either period; the split shows whether the drift held up later. Cumulative return of the calendar-time portfolio, Sharpe ratio, maximum drawdown:

| Version | Costs | Cumulative in / out | Sharpe in / out | Max drawdown in / out |
|---|---|---|---|---|
| Long-short | gross | +257% / +76% | 0.91 / 0.44 | -35% / -50% |
| Long-short | commission and taxes | +26% / -48% | 0.27 / -0.26 | -57% / -68% |
| Long-short | net | -97% / -100% | -2.12 / -3.70 | -97% / -100% |
| Long only | gross | +665% / +58% | 1.28 / 0.37 | -32% / -44% |
| Long only | commission and taxes | +214% / -43% | 0.78 / -0.19 | -48% / -61% |
| Long only | net | -89% / -100% | -1.11 / -2.90 | -94% / -100% |

The gross edge halves out-of-sample (long-short mean per trade +0.19% then +0.17%, Newey–West t 2.2 then 1.2; long only +0.41% then +0.15%), in line with E3 (drift +0.30% then +0.18% per unit of surprise). After costs the strategy loses in both periods. The -100% net figures come from paying about 1.1% a round trip on every trade, with the whole portfolio turned over every few days.
- Reading for the report: prices underreact, and the mispricing survives because it costs more to trade than it pays (limits to arbitrage).

## E1 stakes (exploratory)

Run 2026-10-09: `python -m src.league_tables` (download and tables), then `run_exploratory()`. Files: `league_stakes.csv` (every league match of a listed club: match number, points and rank before the match, gaps to the three lines, `late`, `stakes`), `league_places.csv`, `league_tables_wikipedia.csv`, `event_study_exploratory.csv`.

**Definitions** (decided with Jordan 2026-10-09):
- Late: one of the club's last 10 scheduled league matches (38 in Scotland, 2 × (teams − 1) elsewhere; abandoned Covid seasons keep their schedule).
- Lines: below 1st (title), below the last Champions League place (any round, qualifiers included; European Performance Spots not counted, they were known only late in the season), above the first relegation place (play-off places count). The Scottish split is ignored.
- Within 6 points: a club on or above a line leads the team just below it by at most 6, or a club below trails the team on the place by at most 6. Clubs level on points give 0 either side, so tiebreak rules do not matter.
- Table on the morning of the match: all league results of earlier dates, with deductions and awarded results from their decision date (`e1_stakes` in `config/clubs.yaml`).
- Groups in the regression: `stakes` (late, within 6 points of a line), `late_no_stakes` (late, not within), `rest` (everything else, including European and cup matches). The test compares the first two, which are from the same part of the season.

**Counts:** 1,933 late league matches of the listed clubs, 1,138 with stakes (612 near the title line, 740 near the CL line, 14 near relegation; a match can be near two). On the panel: 1,103 stakes, 785 late without, 7,946 rest. Share of late matches with stakes ranges from 32% (Celtic) to 80% (Benfica).

| Group | Matches | Day 0 b0 | Drift D (days +1 to +3) | SE |
|---|---|---|---|---|
| Stakes | 1,103 | +1.59% | +0.51% | 0.27 |
| Late, no stakes | 785 | +0.34% | +0.23% | 0.25 |
| Rest | 7,946 | +1.07% | +0.19% | 0.09 |

- **Drift: no difference.** Stakes minus late without: +0.29% (p 0.45); all three groups equal p 0.53. With match indicators: +0.30% (p 0.43).
- **Day 0: much larger with stakes.** +1.25% per unit of surprise more than late matches without stakes (p < 0.001; with match indicators +1.31%, p < 0.001). A surprise in a dead rubber barely moves the price (0.34% per unit, a third of the average), one with a title, Champions League or relegation place in reach moves it by half again the average. Prices respond to what a result means for revenue, not to the result alone.
- Exploratory, no Holm correction (reporting rule 2). For the report: compare with Godinho & Cerqueira (2018), whose match importance weight makes the result–return relation significant for most clubs.

## Exploratory splits E2, E3, A1, A2

Run 2026-10-10 with `run_exploratory()`, which now runs every split (E1 included) the same way and writes `event_study_exploratory.csv` in long form (split, variant, group, n, b0, D with standard errors and p, then a comparison row). Each split: S interacted with the groups, plain and with an indicator of any match at each lag **per group** (`match_dummies`). The per-group indicators matter for E2, whose groups follow the sign of the surprise (most clubs' form is positive, so "against the run" is mostly bad results), the trap of H2. E1 moves slightly with per-group instead of common indicators (day 0 difference +1.33%, was +1.31%; drift difference +0.31%, was +0.30%).

A1 and A2 are not in the pre-specified list: chosen 2026-10-09 after the H2 result, as tests of limited attention. Reported as exploratory like the rest.

**Definitions**
- E2 form: sum of the club's previous 5 surprises, all competitions. `against` if the match's surprise has the other sign, `with` the same sign, `no_form` otherwise (72 matches: first five of a club, or a surprise of 0).
- E3 period: seasons 2012/13 to 2018/19 (`early`) v 2019/20 to 2025/26 (`late`).
- A1 surprise size: `big` if |S| is in the top third of all matches (3,259), else `small`.
- A2 time to digest: `gap` if day 0 is two or more calendar days after the match (a weekend or holiday before markets open: 3,274, almost all league matches), else `next_day`.

**Results** (with per-group match indicators; drift = days +1 to +3, % per unit of surprise)

| Split | Groups | Day 0 | Drift | Difference in drift | p |
|---|---|---|---|---|---|
| E2 form | against the run / with it | +1.10% / +0.99% | +0.13% / +0.30% | -0.17% | 0.32 |
| E3 period | 2012-19 / 2019-26 | +1.13% / +1.00% | +0.30% / +0.18% | +0.12% | 0.43 |
| A1 size | big / small surprises | +1.10% / +1.25% | +0.26% / +0.25% | +0.01% | 0.94 |
| A2 digest | weekend gap / next day | +1.13% / +1.04% | +0.44% / +0.15% | +0.29% | 0.08 |

- **E2: no difference.** If anything more drift with the run than against it, the opposite of investors discounting news that breaks a trend; not significant.
- **E3: no difference.** The drift is smaller in the later period (+0.18%, p 0.08) than the earlier (+0.30%, p 0.01): a hint it is fading, not significant.
- **A1: no difference with the indicators.** Plain, the drift looks concentrated in big surprises (+0.29% v -0.01%, p 0.11), but that comes from the common match-week pattern: small surprises sit near 0, where the pattern dominates. Limited attention predicted the reverse (more drift after small news); not found.
- **A2: more drift after a weekend gap, p 0.08.** Not competition type in disguise: within league matches alone the same gap (+0.47% v +0.18%, difference +0.29%, p 0.11). The direction matches DellaVigna & Pollet (2009): news released before a weekend gets less immediate attention and more delayed response. Suggestive only.
- None of the exploratory splits changes the drift significantly at 5%. Only E1 changes the **day 0** reaction (much larger with stakes).

## Not in this step

The written report. Further data (Bloomberg bid and ask for the other clubs) only if the spread estimates turn out to decide the backtest.

## Match-week pattern

Added 2026-10-09 after the H2 correction (Jordan: a finding for the report). `run_match_week()` in `src/step4_event_study.py`; outputs `match_week_coefficients.csv`, `match_week_tests.csv`, `match_week_windows.csv`, figure `match_week_pattern.png`. Not a pre-specified test: exploratory, reported as such.

**Method.** Two measures:
1. Regression of the abnormal return on an indicator of any match of the club at each lag -5 to +5, with the surprise at the same lags as a control. The coefficients are the abnormal return around a match whose result met expectations exactly (surprise 0), relative to days with no match within 5 trading days (intercept +0.045% a day).
2. Per match, model free: the sum of abnormal returns over the pre-match window (close of day -3 to close of day -1) and the post-match window (close of day -1 to close of day +3), with a flag when another match of the club has its day 0 inside the window.

**Results**

| Sample | Pre (days -2, -1) | p | Post (days 0 to +3) | p |
|---|---|---|---|---|
| All matches | +0.36% | <0.001 | -0.94% | <0.001 |
| 2012/13 to 2018/19 | +0.41% | <0.001 | -0.93% | <0.001 |
| 2019/20 to 2025/26 | +0.32% | <0.001 | -0.96% | <0.001 |
| Liquid clubs (no Porto, Sporting, Celtic) | +0.46% | <0.001 | -1.20% | <0.001 |
| League matches | +0.26% | 0.001 | -0.77% | <0.001 |
| European matches | +0.30% | 0.006 | -1.17% | <0.001 |
| Cup matches (`other`) | +0.23% | 0.11 | -0.16% | 0.44 |

Per match windows: pre +0.36% mean, +0.03% median (t 8.3, 9,794 matches); +0.43% mean, +0.07% median with no other match inside (6,901). Post -0.25% mean, -0.34% median (t -4.0); -0.19% mean, -0.30% median with no other match inside (4,759).

- **The pre-match rise is solid:** the same size in both measures, both halves of the period, larger for liquid clubs (so not stale prices). It builds over the five days before a match (cumulative about +0.65% from day -5). Largest for Benfica (+0.95% mean), Porto (+0.70%), Fenerbahce (+0.57%); smallest for Manchester United (+0.04%), Lyon and Celtic (+0.09%), Juventus (+0.13%). Consistent with pre-match fan optimism (Bernile & Lyandres 2011).
- **The post-match fall exists, its size is uncertain:** -0.94% in the regression, -0.19% to -0.25% in the raw windows. Matches every 3 to 4 days mean the fall after one match overlaps the rise before the next; the regression separates them by assuming the effects add up, the raw windows contain both. Report the range. Positive post windows for Porto, Sporting, Benfica and Celtic, negative for the rest (largest Fenerbahce, Galatasaray, Besiktas, Juventus).
- **Cup matches show neither.**
- **Not tradable.** Buying at the close of day -3 and selling at the close of day -1: +0.16% mean after commission (0.20% a round trip), median trade about 0, -0.80% after spreads. Shorting the post window: +0.05% after commission, -0.90% after spreads. The only free use is timing trades one would make anyway (buy after a match, sell just before one).

