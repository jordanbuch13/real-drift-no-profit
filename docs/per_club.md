# Per-club breakdown (exploratory)

**Exploratory, written after the capstone was submitted. Not part of the submitted report.** It reruns the Step 4 methods club by club; the pipeline's own outputs are not changed; everything is written to `data/processed/per_club/`. Run with `python -m src.per_club` (about 10 s from the data snapshot). Code: `src/per_club.py`, `src/per_club_charts.py`.

With 14 clubs and 500 to 800 matches each, per-club estimates are noisy. Treat every club-level number as descriptive, not as a test (see section 3).

## Files

| File | Contents |
|---|---|
| `per_club_table.csv` | One row per club: matches, trades, day 0 reaction and drift (with standard errors), pre-match rise and post-match fall, cost split, share of zero-volume days, backtest per trade in and out of sample, break-even cost, shares of trades and gross profit |
| `per_club_backtest.csv` | Backtest per club, long-short and long only, full / in sample (2013/14 to 2018/19) / out of sample (2019/20 to 2025/26) |
| `liquid_flat_costs.csv` | Manchester United, Juventus, Dortmund at flat round trip costs of 0.10%, 0.20%, 0.30% |
| `multiple_testing.csv` | Drift, day 0 and pre-match p-values per club, raw and Holm-adjusted |
| `day0_reaction_by_club.png`, `edge_vs_cost.png`, `match_week_by_club.png` | Charts, 1600 px wide |
| `run_log.txt` | Printed output of the last run |

## 1. Per-club table

All figures in %. Day 0 and drift are per unit of surprise. Drift covers days +1 to +3. Pre is days −2 and −1, post is days 0 to +3, both from the match-week regression. Costs are mean round trips paid on the club's trades. Net returns are long-short, per trade. The table is sorted by day 0 reaction.

| Club | Matches | Trades L-S / long | Day 0 (se) | Drift (se) | Min. detectable drift | Pre / post | Cost: spread + comm. + tax | Zero-vol. days | Net per trade in / out | Break-even cost | Share of trades / gross profit |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Fenerbahce | 721 | 430 / 235 | 1.71 (0.18) | +0.69 (0.28) | 0.79 | +0.58 / −2.07 | 0.93 = 0.73 + 0.20 + 0 | 2.2 | −0.34 / −0.68 | 0.40 | 7.9 / 17.7 |
| Roma¹ | 499 | 292 / 147 | 1.69 (0.25) | −0.18 (0.35) | 0.98 | +0.49 / −1.67 | 0.87 = 0.67 + 0.20 + 0 | 0.1 | −0.65 / −0.56 | 0.25 | 5.3 / 7.5 |
| Borussia Dortmund | 694 | 455 / 224 | 1.65 (0.13) | +0.15 (0.15) | 0.42 | +0.34 / −0.60 | 0.91 = 0.71 + 0.20 + 0 | 0.1 | −0.72 / −0.77 | 0.16 | 8.3 / 7.4 |
| Lazio | 692 | 462 / 232 | 1.62 (0.12) | +0.18 (0.21) | 0.59 | +0.53 / −1.70 | 1.22 = 1.02 + 0.20 + 0 | 0.1 | −1.19 / −0.93 | 0.17 | 8.5 / 8.0 |
| Benfica | 762 | 339 / 154 | 1.53 (0.24) | +0.68 (0.40) | 1.13 | +0.98 / −0.85 | 1.54 = 1.34 + 0.20 + 0 | 0.7 | −0.40 / −1.29 | 0.64 | 6.2 / 22.1 |
| Besiktas | 661 | 449 / 231 | 1.44 (0.19) | +0.03 (0.30) | 0.83 | +0.52 / −1.83 | 1.05 = 0.85 + 0.20 + 0 | 2.2 | −0.69 / −0.87 | 0.26 | 8.2 / 11.7 |
| Galatasaray | 696 | 440 / 232 | 1.28 (0.22) | +0.40 (0.28) | 0.78 | +0.56 / −1.89 | 1.02 = 0.82 + 0.20 + 0 | 2.2 | −0.98 / −0.62 | 0.23 | 8.1 / 10.4 |
| Juventus | 739 | 440 / 239 | 0.95 (0.17) | +0.26 (0.22) | 0.62 | +0.27 / −1.96 | 1.11 = 0.81 + 0.20 + 0.10 | 0.0 | −1.08 / −1.26 | −0.07 | 8.1 / −3.1 |
| Lyon | 683 | 445 / 216 | 0.82 (0.11) | +0.16 (0.16) | 0.45 | +0.11 / −0.24 | 0.86 = 0.66 + 0.20 + 0 | 0.9 | −0.73 / −0.73 | 0.14 | 8.1 / 6.2 |
| Ajax | 681 | 303 / 134 | 0.69 (0.14) | +0.27 (0.16) | 0.46 | +0.39 / −0.17 | 1.02 = 0.82 + 0.20 + 0 | 0.7 | −0.73 / −1.16 | 0.06 | 5.5 / 1.7 |
| Porto² | 736 | 310 / 136 | 0.55 (0.27) | −0.22 (0.46) | 1.29 | +0.34 / −0.23 | 1.70 = 1.50 + 0.20 + 0 | 23.8 | −1.64 / −1.36 | 0.22 | 5.7 / 7.1 |
| Sporting CP² | 703 | 341 / 165 | 0.49 (0.29) | +0.37 (0.66) | 1.84 | −0.17 / −0.43 | 1.58 = 1.38 + 0.20 + 0 | 18.7 | −1.14 / −2.27 | −0.16 | 6.2 / −5.5 |
| Manchester United | 770 | 478 / 231 | 0.11 (0.11) | +0.16 (0.18) | 0.51 | +0.22 / −0.29 | 0.97 = 0.77 + 0.20 + 0 | 0.0 | −0.67 / −1.03 | 0.10 | 8.8 / 5.0 |
| Celtic² | 797 | 277 / 105 | 0.10 (0.06) | +0.15 (0.11) | 0.30 | −0.01 / +0.28 | 1.49 = 1.25 + 0.20 + 0.04 | 13.5 | −0.67 / −2.02 | 0.13 | 5.1 / 3.7 |

¹ Delisted 12/09/2022: its out-of-sample period covers three seasons only. ² Thin trading (stale prices on many days): the day 0 reaction is spread over later days, and the spread estimates use a different estimator (Abdi–Ranaldo for Porto and Sporting).

Hit rates, cumulative returns, gross returns and long-only versions are in the CSV files. All 5,461 trades of the submitted backtest are covered.

**Reliability.** The minimum detectable drift is the drift a club's own regression would detect with 80% power at 5%. It ranges from 0.30% (Celtic) to 1.84% (Sporting). The pooled drift in the report is +0.23%, below every club's minimum detectable drift. No single club has enough matches to confirm or rule out a drift of the pooled size, so per-club drift differences are mostly noise.

**What stands out**
- **Day 0 reaction** is large (1.3% to 1.7% per unit of surprise) for Fenerbahce, Roma, Dortmund, Lazio, Benfica, Besiktas and Galatasaray, and close to 0 for Manchester United and Celtic.
- **Reaction against cost:** across clubs the rank correlation is **−0.42**. The stocks that react most tend to be the *cheaper* ones (Fenerbahce, Roma, Dortmund cost under 1%). The costliest (Porto, Sporting, Celtic) react least, partly because their thin trading spreads the move over later days. Benfica is the exception: expensive and reactive. The expected story ("the clubs that react most are the expensive ones") is not what the data shows.
- **Gross profit is concentrated:** Benfica and Fenerbahce make 14% of trades but 40% of gross profit. Juventus and Sporting lose money even before costs.
- **Every club's break-even cost (0.64% at most, Benfica) is below its estimated cost (0.86% or more).** Out of sample, no club makes money net of estimated costs, long-short or long only.
- **Only club-period profitable after estimated costs:** Benfica long-only in sample (+1.38% per trade, +92% cumulative). It rests on three trades in 2014–15 (+60%, +35%, +31%). Without them it is −0.28% per trade (median −0.47%). Out of sample the same rule loses 70%.

## 2. Realistic-cost check: Manchester United, Juventus, Dortmund

The estimated costs above come from daily high and low prices (Corwin–Schultz). For liquid stocks that method probably overstates the spread. So the backtest is rerun for the three most liquid clubs at a flat all-in round trip cost. Out of sample (2019/20 to 2025/26), per trade, with cumulative return and Newey–West t:

| Club | Version | 0.10% | 0.20% | 0.30% |
|---|---|---|---|---|
| Manchester United | long-short | −0.16%, cum −40% | −0.26%, cum −54% | −0.36%, cum −65% |
| Manchester United | long only | −0.30%, cum −34% | −0.40%, cum −42% | −0.50%, cum −49% |
| Juventus | long-short | −0.28%, cum −58% | −0.38%, cum −67% | −0.48%, cum −74% |
| Juventus | long only | −0.47%, cum −50% | −0.57%, cum −56% | −0.67%, cum −61% |
| Borussia Dortmund | long-short | **+0.09%, cum +15%, t 0.55** | −0.01%, cum −12% | −0.11%, cum −32% |
| Borussia Dortmund | long only | **+0.09%, cum +9%, t 0.45** | −0.01%, cum −5% | −0.11%, cum −18% |

**Plainly:** Manchester United and Juventus lose money out of sample at every cost level, because their gross edge out of sample is already negative (−0.06% and −0.18% per trade). Dortmund is the only one in profit, and only at 0.10%. Its gross edge is +0.19% per trade, so it breaks even at about 0.19%. That profit is not statistically different from zero (t 0.55), and it is the best of 18 combinations (3 clubs × 2 versions × 3 costs), so it is what chance alone would produce. For Juventus, 0.10% all-in is not achievable anyway: the Italian FTT alone is 0.10% on every purchase.

*Flag:* the 0.10% to 0.30% levels are rough quoted-spread figures from general market knowledge (NYSE for Manchester United, Borsa Italiana for Juventus, Xetra for Dortmund), plus a low commission. They are not measured from data in this repository. The only quoted spreads in the repository are Roma's (Bloomberg bid and ask, 2019 to 2022, averaging about 0.6%). Read section 2 as "what if costs were this low", not as a measured cost.

## 3. Multiple-testing warning

- **Drift (days +1 to +3):** 1 of 14 clubs is significant at 5% (Fenerbahce, p 0.014). By chance alone, 14 × 0.05 = **0.7 clubs** would be expected. After a Holm correction across the 14 clubs, Fenerbahce's adjusted p is 0.19: **no club survives.** One significant club out of 14 is what pure noise looks like.
- **Day 0 reaction, for contrast:** 10 clubs survive Holm (all p < 0.001). Porto, Sporting, Manchester United and Celtic do not. The day 0 reaction is a robust club-level finding; the per-club drift is not.
- **Pre-match rise:** significant at 5% for 7 clubs, 3 after Holm (Benfica, Ajax, Lazio).

The pooled drift in the report (p 0.004) is the test. The per-club table only shows where it comes from.

## 4. Charts

- `day0_reaction_by_club.png`: day 0 reaction per club, sorted, with bars shaded by estimated round trip cost and the cost written next to each bar. The intended message ("the clubs that react most are the expensive ones") was **not supported**, so the chart shows the actual pattern: the costliest stocks mostly react least.
- `edge_vs_cost.png`: gross gain per trade against estimated round trip cost, one dot per club, with the break-even line. Every club is below it.
- `match_week_by_club.png`: cumulative abnormal return from 5 days before to 5 days after a match with an as-expected result, for Benfica, Porto, Fenerbahce and Manchester United. These three were picked from the per-match window means in `docs/step4_event_study.md`. By the regression measure used here, Porto's pre-match rise (+0.34%) ranks only 7th of 14 and is not significant. Benfica (+0.98%) and Fenerbahce (+0.58%) are the clearest cases.

## 5. For a LinkedIn post

- Across 14 listed European football clubs and about 10,000 matches (2012 to 2026), shares move most on a surprising result at Fenerbahce, Roma, Dortmund and Lazio: about 1.6% to 1.7% per unit of betting-market surprise on the next trading day. Manchester United and Celtic barely move (about 0.1%).
- Prices keep drifting in the direction of the surprise for a few days. That holds in the pooled data, but no single club shows it reliably: one club out of 14 is significant, roughly what chance predicts, and none survives a multiple-testing correction.
- Clubs that react most are not the hardest to trade. The costliest stocks to trade (Porto, Sporting, Celtic) react least; Benfica is the exception.
- No club's post-match drift pays for the cost of trading it, either in sample or out of sample, at the trading costs estimated from price data. Even at an assumed 0.10% to 0.30% round trip for the most liquid clubs*, Manchester United and Juventus lose money out of sample, and Dortmund's small gain at 0.10% is within noise.
- Takeaway: the market underreacts to match results, but the mispricing is smaller than the cost of trading it. A textbook limit to arbitrage, not a trading opportunity.

\* Assumed cost levels for the liquid clubs are rough quoted-spread figures from general market knowledge, not measured from data in this project. Everything else uses costs estimated from daily price data.

Before posting: present it as a finding, not a trading tip; keep the "exploratory" label; publish only these derived tables and charts, not raw Bloomberg, Betfair or OddsPortal data.
