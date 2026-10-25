# Step 1b: European and Cup Match Expectations from Betfair

## Why this step exists

Step 1 uses football-data.co.uk, which only covers domestic leagues. Champions League, Europa League and domestic cup matches are missing, and these carry the largest financial stakes for clubs (prize money, broadcast revenue, qualification). The hypothesis says reactions should be strongest exactly there, so leaving them out would weaken the test.

Betfair's historical exchange data fills the gap. The BASIC plan is free and gives last traded prices at one minute resolution for every runner in every market.

## Status

Code: `src/step1b_betfair.py`. Tested offline on synthetic Betfair files (`tests/test_pipeline.py`). Test month February 2016 run on real data 2026-10-06; findings in `docs/issues.md`.

## Setup (done once)

1. Create a Betfair account (UK).
2. Get an application key through the Betfair Developer Program. The free delayed key is enough for historical data.
3. On historicdata.betfair.com, choose Sport: Soccer, Plan: Basic, and the date range of the sample. Complete the free "purchase". Files can only be downloaded for ranges added this way.
4. Copy `.env.example` to `.env` and fill in `BETFAIR_USERNAME`, `BETFAIR_PASSWORD`, `BETFAIR_APP_KEY`. Never commit `.env`. The submission must not contain credentials.

## Two ways to get the raw files

**Automated (preferred, credited by the brief).** `download_basic(start, end)` logs in and, month by month, searches the MATCH_ODDS file listing by each club's Betfair name (the `event_name` filter is a substring match, so overlapping aliases are searched once). Every weekday and competition is covered. Each file is opened and kept only if a team name exactly matches an alias, because the search also returns e.g. "Man Utd (W)" or "Romania". Files go to `data/raw/betfair/YYYY/MM/`. A marker per finished month, and skipping files already on disk, make it resumable. Basic soccer data starts in May 2015.

(The first version listed every MATCH_ODDS file for each Tuesday to Thursday and opened all of them. It was about 10 times slower and missed weekend cup matches. See `docs/issues.md`.)

Run one month first to measure speed and confirm the format before launching the full range.

**Manual fallback.** Download the monthly `.tar` bundles from the website and drop them in `data/raw/betfair/`. The parser reads `.tar` archives directly. Document in the report how and when they were downloaded.

## What the parser does

Real Basic files often hold two MATCH_ODDS markets per event (a main one and a thin one with stale prices). Keep one market per event: complete prematch prices first, then the most updates. Drop markets that never went in play (postponed or abandoned matches).

For each MATCH_ODDS market:

1. Read the stream line by line, tracking the latest market definition and the last traded price (ltp) per runner.
2. Record a snapshot of ltps after every message that arrives before kickoff and while the market is not in play. The last such snapshot is the prematch price.
3. Map runners to home, draw and away using the event name (`"Home v Away"`) and runner names (draw runner is `"The Draw"`). Runner names do not always repeat the event name ("Spal" in "Juventus v SPAL", "Qarabag FK" in "Celtic v Karabakh"), so names are matched ignoring case, and a team still unmatched gets the one remaining non-draw runner. Runner order (`sortPriority`) is not used: in a few files it is not home, away, draw.
4. Read the settled result from the final market definition (runner status `WINNER`).
5. Convert the three prices to probabilities with the same function as Step 1, then reshape to the club's perspective.

Keep only markets where a listed club plays, using `betfair_names` in `config/clubs.yaml`.

## Gap fill from OddsPortal

Betfair Basic lacks some matches, almost all Champions League games from 2015/16 to 2017/18, and starts in May 2015, so it has no European or cup matches for 2012/13 to 2014/15 (see `docs/issues.md`). `src/oddsportal.py` reads closing 1X2 odds scraped from OddsPortal (`data/raw/oddsportal/*_odds_*.json`: `cl_odds_*` for the 2015/16 to 2018/19 Champions League gaps, `cups_odds_*` for every European, domestic cup and super cup match of the listed clubs from 2012/13 to 2014/15, 589 matches; `gap_odds_*` for 74 matches from 2015/16 on that Betfair lacks, found through the Wikipedia check) and Step 1b adds an OddsPortal match only when Betfair does not have it: no Betfair match of the same listed club at the same venue within 3 hours, or against the same opponent within a day. Added rows have `source = oddsportal` and `odds_source = oddsportal_avg_closing` and then go through the same labelling and friendly filter as Betfair rows.

- Odds are the mean over the bookmakers OddsPortal shows. From a UK address that is 9 UK bookmakers (no Pinnacle, no Betfair Exchange). Margin removed as in Step 1.
- Results are taken after 90 minutes from the half-time scores, because OddsPortal's final score includes extra time (and counts a shoot-out win as a goal). Pages without half-time scores are matches that went to extra time: a single match is a draw after 90 minutes; a second leg can stand at anything, so its result comes from `oddsportal_results_90` in `config/clubs.yaml` (five entries for 2012/13 to 2014/15, checked on Wikipedia), and without an entry it has no result and is printed.
- Club spellings: `oddsportal_names` in `config/clubs.yaml`.
- Validation: on 252 CL matches 2015/16 to 2018/19 that both sources have, OddsPortal and Betfair margin-free probabilities differ by 0.010 (home), 0.006 (draw), 0.009 (away) on average, correlation 0.999 for the home win; the largest gaps (up to 0.06) are lopsided early qualifiers.

Scraping (done 2026-10-06, outside the pipeline) uses OddsHarvester, which needs Python 3.12+ and a Playwright browser, so it is installed as a separate tool, not in the project environment:

```
uv tool install --python 3.12 oddsharvester
uv tool run --from playwright playwright install chromium   # or the tool's own python -m playwright
oddsharvester historic -s football -l champions-league --season 2015-2016 --links-only -f csv -o cl_links_2015-2016 --headless
oddsharvester historic -s football --match-links-file links_ours_2015-2016.txt --season 2015-2016 -m 1x2 -f json -o cl_odds_2015-2016 --headless
```

Second scrape (2026-10-07/08): link lists of whole competitions (`--links-only`, saved to `data/raw/oddsportal/links/`) for the Champions League and Europa League 2012/13 to 2025/26, the Conference League 2024/25 and 2025/26, and every domestic cup and super cup of the listed clubs' leagues 2012/13 to 2025/26 (URLs per season differ with sponsor names, e.g. `capital-one-cup`, `insurance-league-cup`). `club_match_links` picks the listed clubs' matches out of them by OddsPortal team id (`oddsportal_id` in the config); for 2012/13 to 2014/15 their match pages were scraped. The lists are also used to name competitions (below). Two lessons: the tool can drop a 50-match listing page without reporting it (Europa League 2019/20 and FA Cup 2023/24 came back 50 short; both re-collected), and a few pages do not exist (2012 Johan Cruijff Schaal, Conference League 2021/22 to 2023/24 under that URL).

`links_ours_*.txt` are the link lists filtered to matches with a listed club (289 matches, CL 2015/16 to 2018/19, qualifiers included). Two matches failed twice (Porto v Liverpool, Barcelona v Man Utd, 2018/19) and Ajax v Tottenham (2019) came back incomplete; Betfair has all of them. OddsPortal's terms do not allow automated collection. Pages were fetched for this research project only: about 290 match pages on 2026-10-06, and on 2026-10-07/08 about 330 listings and 2,100 match pages (589 European and cup 2012/13 to 2014/15, 74 Betfair gaps, 1,422 league for kickoff times, below). No further OddsPortal scraping is planned: competition names are cross-checked against Wikipedia instead.

## League, European, other, and friendlies

Betfair files do not state the competition. Each Betfair club row is labelled:

- `league`: Step 1 has the same club playing within one day. One Betfair row per league match (a market with a result first, then the closest win probability), and the row takes Step 1's season.
- `european`: in the openfootball European fixture list (`src/european_fixtures.py`) within one day. The `competition` column names it.
- `other`: domestic cups, European matches missing from the list, friendlies.

Then each `other` row is named, in this order:

1. **OddsPortal listings.** An OddsPortal match (gap fill) carries its competition. A Betfair row is named when the same club plays a match in an OddsPortal competition listing on the same day, or a day either side against the same opponent (Dortmund v Sandhausen, a friendly the day after the 2016 DFL-Supercup, must not take its name). European names make the row `european`. Names are display names from `competition_names` in the config (sponsor names map to one competition).
2. **Wikipedia club season articles** (`src/wikipedia_fixtures.py`, raw wikitext in `data/raw/wikipedia/`, CC BY-SA). Every listed club's English season article 2012/13 to 2025/26 (196 articles, downloaded 2026-10-08 through the MediaWiki API, spaced 3 s apart because Wikipedia throttles bursts). Matches are `{{football box collapsible}}` templates under competition headings, or for Manchester United plain results tables; friendlies sit under headings such as "Pre-season and friendlies". A non-league row matching a Wikipedia match (same rules as above) is confirmed competitive and named if still unnamed, or marked a friendly and dropped. Different names from OddsPortal are logged (`wikipedia_name_conflicts.csv`; OddsPortal's is kept), and competitive Wikipedia matches with no row are listed in `wikipedia_missing_matches.csv`.

Unnamed `other` rows not confirmed by Wikipedia are then filtered for friendlies using the `friendly_filter` settings in `config/clubs.yaml`: off-season and winter-break windows from each club's Step 1 league schedule, an exemption for Celtic (the 2025 Club World Cup period exemption was removed 2026-10-08, its matches are named), two-legged ties kept as qualifiers, configured domestic super cup dates kept, winter-break matches against a domestic league opponent kept as cup ties (except Bundesliga and Eredivisie clubs), and same-day pairs resolved in favour of the league or European match. A flagged leg of a two-legged tie whose other leg is named takes that name (Ajax v Nice, 2017). Rows Wikipedia lists as friendlies are dropped whatever the date rules say. Excluded rows go to `data/processed/betfair_excluded_friendlies.csv` with a reason. Known gaps are in `docs/issues.md`.

Step 1 must run first. On league matches both sources exist, so the code prints the correlation between Betfair and bookmaker win probabilities (0.999 on the real data). A low value means the name mapping or price snapshot is wrong.

## Outputs

| File | Contents |
|---|---|
| `data/processed/betfair_expectations.csv` | Every Betfair club row, league and non league, plus OddsPortal gap-fill rows (`source`), same columns as Step 1 |
| `data/processed/betfair_missing_odds.csv` | Dropped markets with reason: never went in play (postponed), second market for the same event, no prematch trade on every runner |
| `data/processed/betfair_coverage.csv` | Per club and season: Step 1 league matches since May 2015, how many Betfair also has, Betfair european and other counts |
| `data/processed/betfair_excluded_friendlies.csv` | Club rows dropped as friendlies, with reason |
| `data/processed/wikipedia_name_conflicts.csv` | Rows whose OddsPortal or fixture-list competition differs from the Wikipedia article's (1 on the real data) |
| `data/processed/wikipedia_missing_matches.csv` | Competitive non-league matches in the Wikipedia articles with no row here: Betfair and OddsPortal gaps (15 after the gap fill, 4 since May 2015) |
| `data/processed/match_expectations_all.csv` | Step 1 league rows plus Betfair (and OddsPortal gap-fill) european and other rows: the full event set for Step 2. Adds `competition` (league name from `league_names` in the config, European competition, or cup label; empty for unnamed `other` rows) and `kickoff_source` (below). Fails on duplicate (club, date). |

Betfair rows have no score (`goals_for`, `goals_against` empty) but do have an exact kickoff time in London time, which Step 3 needs.

Kickoff times in the combined file (`kickoff_source`, added 2026-10-07): Football Data has times (UK) only from 2019/20. Earlier league rows take the time of the Betfair league market for the same club on the same date (`betfair`; the actual off, usually within a few minutes of the scheduled kickoff; 1,928 rows), then for 2012/13 to 2014/15 the kickoff on the OddsPortal match page (`oddsportal`, converted from UTC to UK time; 1,417 rows, from `data/raw/oddsportal/league_kickoffs/`, kept apart so these league matches never enter the cup data). Then, as a last resort, the Wikipedia club season article (`wikipedia`, 91 rows: local time and zone converted to UK time; within 15 minutes of the other sources on 92% of 7,814 matches both have). A date one day off is not used (one case, Porto 14/12/2015). League rows still without a time are `assumed_evening` on weekdays (11: midweek league matches are evening matches, after European markets close) and `none` at weekends (29), where the time does not change the trading day. Summary of all sources: `docs/data_sources.md`. Non-league rows have `betfair` or `oddsportal` times.

## Checks

1. Probabilities sum to 1 and no duplicate (club, date) rows (shared with Step 1).
2. Warning when no Betfair alias for a club is ever seen, with close matches suggested.
3. Warning when the last prematch trade is more than 60 minutes before kickoff (stale price).
4. Cross check correlation with bookmaker odds on shared league matches.

## Assumptions to verify on the first real run

1. Files are bz2 compressed JSON lines with `op`, `pt`, `mc`, `marketDefinition`, `rc` and `ltp` fields.
2. `marketDefinition` contains `eventName`, `marketTime`, `marketType`, `inPlay` and `runners` with `name` and `status`.
3. Event names use `" v "` between teams and the draw runner is `"The Draw"`.
4. How far back BASIC soccer data goes. If it starts after 2012/13, European coverage is shorter than league coverage, and the report must say so.
5. The `betfair_names` spellings in the config.
6. The `get_file_list` and `download_file` signatures in the installed `betfairlightweight` version.

If any of these fail, fix the parser and add a test reproducing the real format.

## Not in this step

Surprise, stock prices and trading day alignment are Steps 2 and 3.
