# Step 1: Match Expectations from Betting Odds

**Status:** implemented in `src/step1_expectations.py`, run on the real files 2026-10-05. Issues found and how they were handled: `docs/issues.md`.

## Context

This is the first stage of a capstone project for the Imperial Data Structures and Algorithms module. The hypothesis: listed football club stocks underreact to match results measured against betting market expectations, so the price keeps drifting in the direction of the surprise for several days after the match.

This step builds the "expected" side of that comparison. For every league match played by a listed club, compute what the betting market expected before kickoff. Later steps compute the surprise, line it up with stock returns, and backtest.

**Goal of this step:** one clean table with one row per club per match, containing the market implied probabilities and expected points for that club.

## Data source

Football Data (https://www.football-data.co.uk), free CSVs per league per season.

URL pattern: `https://www.football-data.co.uk/mmz4281/{season}/{league}.csv`

`season` is a four digit code, for example `1213` for 2012/13 and `2526` for 2025/26.

**Sample period:** 2012/13 to 2025/26 (complete seasons only). The start is set by Manchester United listing on the NYSE in August 2012.

## Clubs and leagues

Put this in `config/clubs.yaml` so later steps can reuse it. Team names must match exactly how Football Data spells them. Verify every name against the downloaded files and fix any mismatch; do not assume these spellings are right.

| Club | League code | Expected Football Data name |
|---|---|---|
| Manchester United | E0 | Man United |
| Juventus | I1 | Juventus |
| Lazio | I1 | Lazio |
| Roma | I1 | Roma |
| Borussia Dortmund | D1 | Dortmund |
| Ajax | N1 | Ajax |
| Celtic | SC0 | Celtic |
| Benfica | P1 | Benfica |
| Porto | P1 | Porto |
| Sporting CP | P1 | Sp Lisbon |
| Lyon | F1 | Lyon |
| Galatasaray | T1 | Galatasaray |
| Fenerbahce | T1 | Fenerbahce |
| Besiktas | T1 | Besiktas |

Some of these clubs have delisted or changed listing during the sample (Roma and Lyon in particular). Keep them in this step anyway. Whether and how they enter the backtest is decided in the stock data step, and keeping them is what lets the report address survivorship bias honestly.

## Tasks

### 1. Download and snapshot the raw data

Download every league and season CSV needed for the clubs above. Save each file unmodified to `data/raw/football_data/{season}_{league}.csv`. The submission requires a raw data snapshot, so never overwrite or edit these files. Skip the download if the file already exists, so the notebook reruns without hitting the site again.

Files use mixed encodings and some have trailing empty columns. Read with `encoding="latin1"` and drop fully empty columns and rows.

### 2. Choose the odds columns

Use closing odds wherever available, because they are the best estimate of market expectation at kickoff. Older seasons may only have prematch odds, which Football Data collected earlier (check the notes file on the site for exact timing and record it in a comment).

For each row, pick the first available set in this priority order, where each set is home, draw, away:

1. Pinnacle closing: `PSCH, PSCD, PSCA`
2. Market average closing: `AvgCH, AvgCD, AvgCA`
3. Betfair Exchange closing: `BFECH, BFECD, BFECA` (only from 2024/25)
4. Pinnacle prematch: `PSH, PSD, PSA`
5. Market average prematch: `AvgH, AvgD, AvgA`, or `BbAvH, BbAvD, BbAvA` in older files

Pinnacle sets are not used for matches on or after 23/07/2025, when Pinnacle closed its public API and Football Data's Pinnacle odds became unreliable (see `docs/issues.md`). An odds set with overround below 1.00 is treated as invalid and the next set is tried.

Store which set was used in an `odds_source` column. Print a table of counts of `odds_source` by season so it is clear where the data shifts from closing to prematch odds.

Matches listed under `excluded_matches` in `config/clubs.yaml` (forfeits: awarded results that were never played) are removed first and logged with their reason to `data/processed/excluded_matches.csv`. A configured exclusion that cannot be found in a loaded league season fails the run.

A row with no complete odds set is not dropped silently. Log it to `data/processed/missing_odds.csv` with the reason, and print the count.

### 3. Convert odds to probabilities

For decimal odds `o_H, o_D, o_A`:

```
raw_H = 1 / o_H,  raw_D = 1 / o_D,  raw_A = 1 / o_A
overround = raw_H + raw_D + raw_A
p_H = raw_H / overround   (same for D and A)
```

The overround is the bookmaker margin. Dividing by it makes the probabilities sum to 1. Keep `overround` as a column for sanity checks.

Write the conversion as a standalone function so a different margin removal method (Shin, or the power method) can be swapped in later as a robustness check. Proportional normalisation is the default.

### 4. Reshape to the club's perspective

Each match row becomes a row for the listed club only. If both teams are listed (for example Juventus vs Lazio), the match produces two rows, one per club.

For the listed club:

```
if club is home:  p_win = p_H, p_loss = p_A
if club is away:  p_win = p_A, p_loss = p_H
p_draw = p_D
exp_points = 3 * p_win + 1 * p_draw
```

### 5. Output

Save to `data/processed/match_expectations.csv` with these columns:

| Column | Description |
|---|---|
| match_id | Unique id: league, season, date, home, away |
| source | `football_data` |
| competition_type | `league` |
| season | Season code |
| league | League code |
| date | Match date, parsed to a proper date |
| kickoff_time | Kickoff time if present (only in recent seasons), else empty |
| club | Listed club, using the canonical name from the config |
| opponent | Opposing team |
| venue | H or A |
| goals_for, goals_against | Full time goals from the club's perspective |
| result | W, D or L from the club's perspective |
| odds_source | Which odds set was used |
| odds_H, odds_D, odds_A | The raw decimal odds used, kept for spot checks |
| overround | Bookmaker margin |
| p_win, p_draw, p_loss | Implied probabilities |
| exp_points | Expected points |

Keep the code in `src/step1_expectations.py` with a single `build_match_expectations()` entry point, and call it from the notebook under a markdown heading "Data acquisition: match odds".

## Checks (fail loudly if any break)

1. `p_win + p_draw + p_loss` equals 1 within 1e-9 on every row.
2. `overround` is between 1.00 and 1.15. Print any rows outside that range instead of dropping them.
3. Dates parse correctly. Football Data mixes `dd/mm/yy` and `dd/mm/yyyy` formats, so check that no date falls outside its season.
4. No duplicate `(club, date)` pairs.
5. Season lengths. `league_matches_per_team` in the config gives each league's normal matches per team. Any league season that differs must have an entry in `season_notes` with the reason (Covid, league size changes), otherwise print a warning. Per club and season, matches in the raw file must equal excluded + no odds + rows kept, or the run fails. Save this to `data/processed/season_counts.csv` and print the non-standard club seasons.
6. Spot check: for five random matches, print the raw odds next to the computed probabilities.

## Known limitations to carry forward

These do not need solving in this step, but the report will need them:

1. Only domestic league matches are covered. Champions League and Europa League matches, which carry the biggest financial stakes, are not in these files. They are a natural extension once a source for European competition odds is found.
2. The switch from prematch to closing odds partway through the sample means older expectations are slightly noisier. The `odds_source` column makes it possible to test whether results differ by period.
3. Closing odds are known before kickoff, so using them involves no look-ahead. Kickoff time matters later, when deciding which trading day a match first affects.

## Not in this step

Do not compute surprise, download stock prices, or match matches to trading days yet. Those are steps 2 and 3.
