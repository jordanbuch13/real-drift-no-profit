# Data Sources

How every piece of match data was acquired, from where, when, and in what order sources are used. Step specs (`step1_*.md`, `step1b_*.md`, `step2_*.md`) have the details; `issues.md` has what went wrong and how it was decided. Raw files live in `data/raw/` and processed files in `data/processed/`; neither is committed (`.gitignore`). `data/README.md` says how to get each source.

## Sources

| Source | What it gives | Seasons | How acquired | Terms | Raw files |
|---|---|---|---|---|---|
| **football-data.co.uk** | Domestic league results and bookmaker odds (Pinnacle, market average, Betfair Exchange closing), kickoff times from 2019/20 | 2012/13 to 2025/26 | `src/step1_expectations.py`, one CSV per league season, downloaded 2026-10-05 | Free download | `data/raw/football_data/` |
| **Betfair Exchange historical data (BASIC)** | Last traded prices before kickoff, settled 90 minute result, exact kickoff time, for every match of the listed clubs | May 2015 to May 2026 | `download_basic` in `src/step1b_betfair.py`, Betfair account and app key (credentials in `.env`, never committed), 9,840 files, 2026-10-06 | Free "purchase" of the Basic plan on historicdata.betfair.com | `data/raw/betfair/` |
| **OddsPortal** | Average closing 1X2 odds of UK bookmakers, half-time and final scores, kickoff time, competition name; competition-wide match link lists | 2012/13 to 2025/26 | OddsHarvester (separate Python 3.12 tool, not in the project environment), 2026-10-06 to 2026-10-08: ~330 competition listings, ~2,400 match pages | Terms do not allow automated collection; fetched once for this research project only | `data/raw/oddsportal/` |
| **openfootball** (GitHub `openfootball/champions-league`) | European fixture list: competition and date | CL 2012/13 to 2025/26 (group stage on), EL from 2020/21, Conference League from 2021/22, qualifiers from 2024/25 | `src/european_fixtures.py`, 2026-10-06 and 2026-10-07 | Public domain | `data/raw/openfootball/` |
| **Yahoo Finance** (via `yfinance` 1.7.0) | Daily prices (close, adjusted close, volume, dividends, splits) of the clubs' listed companies and benchmark indices | 2012-01-01 to 07/10/2026 | `download_prices` in `src/step3_prices.py`, 2026-10-08 | Unofficial API; Yahoo's terms are for personal use. Imperial library databases (Refinitiv, Bloomberg, WRDS) to be checked as an official source | `data/raw/prices/` |
| **Bloomberg** (Imperial library terminal) | AS Roma prices (delisted 2022), PSI 20 index 2011 on, Turkish clubs' corporate actions (CACS) | 2011 to 12/09/2022 (Roma), 2011 to 07/10/2026 (PSI) | BDH export to Excel, 2026-10-08; see `bloomberg_pull_2026-10-08.md` | Licensed; not committed to git; cleared on 2026-10-13 for the capstone submission's data snapshot only; not in this public repository | `data/raw/bloomberg/` |
| **Wikipedia** (English club season articles) | Every competitive match and friendly with competition, date, local kickoff time, score, extra time and penalties | 2012/13 to 2025/26, 196 articles (14 clubs × 14 seasons) | `src/wikipedia_fixtures.py`, MediaWiki API, requests 3 s apart, 2026-10-08 | CC BY-SA (attribute in the report) | `data/raw/wikipedia/` |
| **Wikipedia** (English league season articles, "2016–17 Serie A") | Final league tables: record, points (so point deductions), qualification and relegation notes, footnotes | 2012/13 to 2025/26, 112 articles (8 leagues × 14 seasons; Scotland 2012/13 is "Scottish Premier League") | `src/league_tables.py`, MediaWiki API (rendered HTML), requests 3 s apart, 2026-10-09 | CC BY-SA (attribute in the report) | `data/raw/wikipedia_leagues/` |
| **RSSSF** and news reports (BBC, FIGC, LFP, KNVB, TFF statements as reported) | Checks of the Wikipedia tables and the dates of point deductions and awarded matches (E1) | As needed | Read by hand 2026-10-09; each date and its source is in `e1_stakes` in `config/clubs.yaml` | Read only, nothing stored | — |

### What was fetched from OddsPortal

| When | What | Count | Why |
|---|---|---|---|
| 2026-10-06 | Champions League match pages 2015/16 to 2018/19 | ~290 | Betfair Basic lacks some CL matches |
| 2026-10-07 | Listings: CL, EL, 11 domestic cups, 7 super cups, 2012/13 to 2014/15; match pages of the listed clubs | 63 listings, 589 pages | No Betfair data before May 2015 |
| 2026-10-07/08 | Listings: domestic cups and super cups 2015/16 to 2025/26, EL 2015/16 to 2025/26, CL 2019/20 to 2025/26, Conference League | ~240 listings | Name the competition of Betfair rows |
| 2026-10-08 | League listings and the listed clubs' league match pages, 2012/13 to 2014/15 | 24 listings, 1,422 pages | Kickoff times (Football Data has none before 2019/20) |
| 2026-10-08 | Second pass over multi-page listings (stopped part way, replaced by the Wikipedia check) | ~90 listings | The tool can drop a 50-match page without reporting it |
| 2026-10-08 | Match pages of matches Betfair lacks, found by the Wikipedia check | 74 pages | Mostly 2015/16 to 2018/19 Europa League knockouts |

## Which source is used for what

### League tables (E1 stakes split)

Tables before each match are built from the football-data results of the whole league, with point deductions counted from their decision date and awarded results from theirs (`config/clubs.yaml`, `e1_stakes`). The Wikipedia final tables give the places (title, last Champions League place, first relegation place) and the deductions, and check the build: every team's record pairs with a football-data team (2,015 rows; 8 differ in goals only), and the built final points equal Wikipedia's in all 112 league seasons. See `step4_event_study.md`, E1.

Each field is taken from the first source in the list that has it.

### Odds (pre-match probabilities)

| Matches | Order |
|---|---|
| League | football-data: Pinnacle closing → market average closing → Betfair Exchange closing → Pinnacle prematch → market average prematch (Pinnacle never after 23/07/2025; overround below 1 skipped). See `step1_match_expectations.md`. |
| European, cup, super cup from May 2015 | Betfair last traded price before kickoff → OddsPortal average closing (only when Betfair has no match of the club within a day) |
| European, cup, super cup 2012/13 to 2014/15 | OddsPortal average closing |

Agreement: Betfair v bookmakers on 5,422 league matches, correlation 0.999 (mean absolute difference in win probability 0.011); OddsPortal v Betfair on 252 CL matches, mean absolute difference 0.006 to 0.010 per outcome.

### Result after 90 minutes (W/D/L)

1. football-data full-time result (league).
2. Betfair settled result (match odds settle at 90 minutes).
3. OddsPortal: from the half-time scores (the final score includes extra time, and counts a shoot-out win as a goal).
4. OddsPortal page without half-time scores = the match went to extra time: a single match was level after 90 minutes, so a draw.
5. A second leg that went to extra time can stand at anything after 90 minutes: `oddsportal_results_90` in `config/clubs.yaml`, each entry checked by hand in the Wikipedia article (goal minutes) and noted with its reason. 7 entries.
6. No result anywhere (abandoned, not played): row dropped and logged (`surprise_abandoned.csv`).

### Extra time and penalties

Not a column. Used only to get the 90 minute result (above). Wikipedia boxes carry `aet` and `penaltyscore` and were the reference for the manual second-leg entries.

### Kickoff time (UK time), column `kickoff_source`

1. `football_data` (league, from 2019/20).
2. `betfair` (all Betfair rows; league rows before 2019/20 by club and same date). The actual off, usually within minutes of the schedule.
3. `oddsportal` (OddsPortal rows; league 2012/13 to 2014/15 from match pages, UTC converted to UK time).
4. `wikipedia` (last resort: local time and zone from the article, converted to UK time; within 15 minutes of the other sources on 92% of 7,814 matches, within an hour on 98.7%; the rest are article errors). 91 league rows.
5. `assumed_evening` (weekday, no time anywhere: midweek matches are evening matches, after European markets close) or `none` (weekend, where the time does not change the trading day).

### Competition and competition type

1. League: football-data league row, or a Betfair row within a day of one (`league_names` in the config).
2. European: openfootball fixture list within a day.
3. OddsPortal match: its competition listing.
4. Betfair row: same club in an OddsPortal competition listing on the same day, or a day either side against the same opponent.
5. Wikipedia club season article: competition heading of the matching match box.
6. Super cup dates in the config; inferred winter cup ties; two-legged ties (same opponent home and away within 14 days).

Names are mapped to one display name per competition by `competition_names` in the config (sponsor names like Capital One Cup → EFL Cup, Wikipedia headings like UEFA Europa League → Europa League). OddsPortal and Wikipedia disagree on one match (logged in `wikipedia_name_conflicts.csv`).

### Friendlies (excluded)

1. Listed under a friendlies heading in the Wikipedia article.
2. Otherwise, unnamed rows in a club's off-season or winter break (date rules in `friendly_filter`), unless named by a source above.
3. Second match of a club on the same day.

### Coverage check

Wikipedia lists every competitive match; `wikipedia_missing_matches.csv` holds those with no row here. After the 2026-10-08 gap fill, 4 since May 2015: an abandoned Turkish Cup semi-final (twice, one per club) and two cup ties OddsPortal does not list. 2012 Johan Cruijff Schaal has no odds anywhere.

### Share prices

Yahoo Finance adjusted close for 12 clubs and the benchmarks; Bloomberg for Roma (total return index, = price, no dividends) and the PSI 20 (whole period). Corrections: seven Turkish capital events Yahoo misdates (`corporate_actions` in the config): six rights issues adjusted with Bloomberg's CACS factors, keeping the day's return, and one unexplained drop (FENER 29/12/2025) rescaled with the return excluded. Trading calendars count only days with a volume. Event day 0: first trading day whose close comes after the estimated end of the match (kickoff + 115 minutes, UK time converted to the exchange's time zone). See `step3_stock_prices.md`.

### Trading costs (Step 4 backtest)

Bid-ask spreads estimated from Yahoo daily high, low and close (Corwin–Schultz; Abdi–Ranaldo for Porto and Sporting, which mostly trade once a day); Roma's quoted spread from Bloomberg bid and ask (from 24/06/2019). Commission assumed 0.10% per side; transaction taxes from published rules (to verify). See `step4_event_study.md`.

## Reproducing

```
python -c "from src.step1_expectations import build_match_expectations as b; b()"
python -c "from src.step1b_betfair import download_basic as d; d('2015-05-01', '2026-05-31')"   # needs .env
python -c "from src.european_fixtures import download_openfootball as d; d([f'{y}-{(y+1)%100:02d}' for y in range(2012, 2026)])"
python -c "from src.wikipedia_fixtures import download_seasons as d; d(2012, 2025)"
python -c "from src.step1b_betfair import build_betfair_expectations as b; b()"
python -c "from src.step2_surprise import build_match_surprise as b; b()"
python -c "from src.step3_prices import download_prices as d; d()"
python -c "from src.step3_prices import build_match_events as b; b()"
python -c "from src.step4_event_study import build_abnormal_returns as b; b()"
python -c "from src.step4_event_study import run_event_study as r; r()"
python -c "from src.step4_event_study import run_backtest as r; r()"
```

OddsPortal files cannot be re-downloaded by the pipeline (separate tool, see `step1b_betfair.md` for the commands); the processing reads them from `data/raw/oddsportal/`.
