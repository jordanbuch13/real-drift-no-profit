# Issues log

Data and pipeline issues found while running the steps on real data. Each entry says what was found, why it matters, and what was decided. Feeds the report's limitations section.

## Open

None.

## Resolved

### Step 4 E1: league tables from football-data and Wikipedia

Found and fixed: 2026-10-09.

E1 needs the table on the morning of every late-season league match, so tables are built from the football-data results; Wikipedia's final tables (no round by round tables exist in one place for 8 leagues) supply the places and deductions and check the build.

1. **Point deductions.** 22 club seasons with deductions, entered with their decision dates (31 entries; Juventus 2022/23 is -15 on 20/01/2023, annulled 20/04/2023, -10 on 22/05/2023; Everton 2023/24 -10, cut to -6, then -2 more). Dates from the articles' footnotes and news reports. Three Turkish dates are approximate (Istanbulspor and Adana Demirspor walk-offs dated at the match; Adana's FIFA deduction not found, set to 01/03/2025; Adana was last all season, so no line moves).
2. **Wikipedia errors.** The 2017/18 and 2018/19 Serie A tables give Lazio -1 and -2 points that did not happen (RSSSF and the final day of 2017/18: Lazio and Inter both on 72). Set aside in `wikipedia_errors`. RSSSF in turn misses Kayserispor's 2022/23 deduction (TFF licensing, 23/12/2022), which Wikipedia has.
3. **Awarded results.** Verona v Roma 2020/21 (0-0, awarded 3-0 to Verona on 22/09/2020, Roma fielded an unregistered player) and Nantes v Bastia 2013/14 (2-0, awarded to Bastia on 12/02/2014) count from their decision. Four goal-only differences between the sources are left (`goal_differences`).
4. **Ex ante places.** European Performance Spots (Germany and Italy 2023/24, England 2024/25 and 2025/26) were known only late in the season and are not counted. Overrides where the final table does not show the scheduled places: Turkey 2013/14 and 2019/20 (clubs banned by UEFA), Serie A 2022/23 (relegation tie-breaker), Covid seasons and Portugal 2019/20 (licence relegations). Eredivisie and Super Lig 2019/20 (no relegation) take the previous season's places.

Result: all 2,015 Wikipedia rows pair with a football-data team; built final points equal Wikipedia's (errors corrected) in 112 of 112 league seasons.

### Step 1b: no European or cup matches before May 2015, most cup matches unnamed

Found: 2026-10-07. Fixed 2026-10-08.

Betfair Basic starts in May 2015, so 2012/13 to 2014/15 had league matches only: no Champions League nights, and a median gap between matches of 7 days against 4 to 5 later. And Betfair files do not name the competition, so 2,003 non-league rows had no competition name.

Done:
1. **OddsPortal, 2012/13 to 2014/15.** Every European, domestic cup and super cup match of the listed clubs (589 match pages, none failed). Those seasons now have 104 to 132 European and 84 to 102 cup matches, like later seasons, and a median gap of 4 to 5 days.
2. **Extra-time results.** 37 OddsPortal pages have no half-time scores: matches that went to extra time, whose final score includes extra time (a shoot-out win counts as a goal: Bayern 1-2 Dortmund, 28/04/2015, was 1-1 after extra time). A single match is a draw after 90 minutes. Second legs can stand at anything; the five in 2012/13 to 2014/15 were checked on Wikipedia and entered in `oddsportal_results_90`.
3. **Naming.** OddsPortal competition listings (2012/13 to 2025/26) named 1,327 rows, then Wikipedia club season articles confirmed 2,920 non-league rows as competitive and named the rest. 24 unnamed `other` rows remain: 10 abandoned matches and about 12 friendlies Wikipedia does not list (international breaks, kept by decision 8 above; Porto v Wydad Casablanca, 31/05/2025, a pre-Club World Cup friendly inside the 14-day buffer after the league). The 2025 Club World Cup exemption period was removed (2026-10-08): the tournament's matches are named, so it only kept three Besiktas pre-season friendlies.
4. **Friendlies.** Wikipedia lists 570 Betfair rows as friendlies, now dropped whatever the date rules said, including 47 Celtic pre-season matches the Celtic exemption had kept. About 40 competitive matches the date rules had dropped are back: DFB-Pokal first rounds in August, European qualifiers, Man Utd's August 2020 Europa League games, January cup ties. Two inferred winter cup ties are friendlies on Wikipedia and are dropped, including the doubtful Galatasaray v Alanyaspor, 26/02/2023. One-day-off matches need the same opponent (Dortmund v Sandhausen 15/08/2016 and Dortmund v Hallescher FC 23/08/2016 are friendlies the day after a cup match).
5. **Kickoff times.** League rows before 2019/20 take Betfair's time (1,928) or, for 2012/13 to 2014/15, OddsPortal's (1,417). 25 weekday league rows remain `assumed_evening`.

Result: 10,038 club matches in Step 2 (was 9,368): 6,985 league, 1,828 European, 1,225 other.

Still open, for the report:
- **Betfair gaps found by Wikipedia, filled from OddsPortal (2026-10-08).** `wikipedia_missing_matches.csv` listed 86 competitive matches since May 2015 that Betfair Basic does not have: 42 European, concentrated in 2015/16 to 2018/19 knockout rounds (32 of 161 February to May European matches in those seasons, about 20%, including Man Utd v Liverpool 2016 and Man Utd's 2016/17 Europa League quarter- and semi-final), and 44 domestic cup ties. Not random: they were the highest-stakes events. 74 were on the OddsPortal competition lists and were scraped (none failed). 4 remain: Besiktas v Fenerbahce, Turkish Cup semi-final 19/04/2018 (abandoned, Besiktas's coach hit by an object; listed once per club), Besiktas v Darica Genclerbirligi (Turkish Cup, 29/11/2017) and Porto v Gafanha (Taca de Portugal, 15/10/2016), not on OddsPortal. The second leg of the abandoned semi-final (03/05/2018, not played) has no result and is dropped. Sporting v Porto, 18/04/2018, is a second leg whose first leg is a Betfair match, which the extra-time rule cannot see: its result was entered in `oddsportal_results_90` from Wikipedia (every other extra-time match was checked against the full event set; all are covered).
- **No odds anywhere**: 2012 Johan Cruijff Schaal (Ajax v PSV, 05/08/2012; the OddsPortal page is empty). Celtic v Legia, 06/08/2014 (Legia later expelled for fielding an ineligible player) has no score on OddsPortal and is dropped with the abandoned matches.
- **Wikipedia errors**: articles are edited by volunteers. One date conflict found (Juventus 2012/13 article lists a Champions League match on 12/12/2012 where OddsPortal has Juventus v Cagliari in the Coppa Italia); OddsPortal's name is kept.
- **Scraping terms**: OddsPortal's terms do not allow automated collection; see `docs/step1b_betfair.md` for what was fetched and when.

### Step 1b: competition dropped from the combined file, and an abandoned match labelled as league

Found and fixed: 2026-10-07, while writing the Step 2 spec.

1. `match_expectations_all.csv` had no `competition` column: `_combine` kept only the shared club columns, so the European competition and cup labels in `betfair_expectations.csv` were lost. Now kept. League rows get the league name from `league_names` in `config/clubs.yaml`. 1,292 `other` rows have no name (unlabelled domestic cups and the like): Betfair files do not name the competition, and the OddsPortal backup covers only the Champions League, so it cannot fill them.
2. Benfica v Nacional appeared twice. Nacional v Benfica was abandoned on 10/01/2016 (Betfair `1.122449006`, no result) and replayed on 11/01/2016 (`1.122558344`, Benfica won). Both are within a day of Step 1's 11/01 row, and the one-row-per-league-match rule picked the abandoned market (closer win probability), leaving the replay as an `other` row that duplicated the league match. The rule now prefers a market with a result. The abandoned market is an `other` row with no result, which Step 2 drops. `_combine` now fails on any duplicate (club, date); Step 1b's duplicate check had passed because it ran on Betfair rows alone. Covered by `test_label_competition_prefers_market_with_result`.

Abandoned matches (14 rows, market went in play but settled without a winner) stay in the combined file with an empty result and are dropped and logged in Step 2.

### Step 1b: friendlies mixed in with European and cup matches

Found: 2026-10-06, first full Betfair run. Resolved; remaining uncertainty listed at the end.

Betfair Basic files do not name the competition. Every Betfair match that is not a Step 1 league match was labelled `non_league`, which mixed European and cup matches with pre-season tours, winter-camp friendlies (Ajax played RB Leipzig and Excelsior on 07/01/2017) and side friendlies (Ajax v VVSB on the same evening as Fortuna Sittard v Ajax, 21/09/2021). About 19 non-league matches per club per season against a realistic 8 to 15.

Done:
1. **European fixture list** from openfootball (`src/european_fixtures.py`, raw files in `data/raw/openfootball/`). Matches within a day are labelled `european` with the competition name. Coverage of the list: Champions League from the group stage every season; Europa League from 2020/21; Conference League from 2021/22; qualifiers from 2024/25; no Europa League or Conference League main stage for 2025/26 yet.
2. **Date rule** for the remaining `other` rows: friendly if in the club's off-season (from 14 days after its last league match to its first league match of the next season; the buffer keeps the July 2020 Covid-delayed cup finals) or winter break (league gap of 18+ days overlapping 15 Dec to 15 Feb).
3. **Exemptions:** Celtic (qualifiers start before the Scottish season) and the 2025 Club World Cup period.
4. **Two-legged ties kept:** same opponent home and away within 14 days. This recovers every club's European qualifiers missing from the list (e.g. Ajax v Sturm Graz 2018, Fenerbahce v Shakhtar 2015) and pre-2020/21 Europa League knockout ties. 13 off-season ties found, all real qualifiers.
5. **Same-day pairs:** the league or European match is kept; a second match that day is dropped. League and European labels are now one-to-one (a side friendly can no longer inherit the league label).
6. **League rows take their season from Step 1** (fixes the July 2020 Covid restart being counted in 2020/21).

7. **Domestic super cups** (added 2026-10-06, `super_cups` in `config/clubs.yaml`): a row is a super cup if the club plays in that league, the date matches a listed super cup date exactly, and the opponent is a team the club also meets in the league. Rescues them from the off-season and winter-break rules, and names mid-season ones (e.g. DFL-Supercup 30/09/2020, Supertaca 23/12/2020, Turkish Super Cup replay 07/04/2024). 2015 editions and Supercoppa Italiana added the same day. Exact date match: a day's tolerance mislabelled four January Coppa Italia ties as Supercoppa. 54 rows. One false positive removed by an `exclude` entry: Man Utd v Everton, 07/08/2021, a friendly on the day of the Leicester v Man City Community Shield.

8. **Friendlies during international breaks** (e.g. Besiktas v Osmanlispor, 09/10/2015) stay in `other`, by decision (2026-10-06). Super cups are never dropped as friendlies: the 14 excluded rows that fall on a super cup date of the club's league are all friendlies of clubs not playing in it (foreign or lower league opponents, e.g. Man Utd v Atletico Madrid on Community Shield day 2022) plus the configured Man Utd v Everton exclusion.
9. **Winter-break cup ties kept** (2026-10-06): the winter-break rule also caught real cup ties (Taca da Liga, Turkish Cup, Coupe de France and Coupe de la Ligue, Coppa Italia, the 2017 League Cup final Man Utd v Southampton), because cup rounds create long league gaps in leagues without a real break. A winter-break match against a team from the club's own league is now kept as `domestic cup (inferred: winter, league opponent)`, except for Bundesliga and Eredivisie clubs (`winter_camp_friendly_leagues`), whose camp friendlies against domestic sides (e.g. Dortmund v Fortuna Dusseldorf in Marbella, Ajax v Excelsior) stay excluded. 29 rows kept.

Result: 5,375 league, 957 European and 1,381 other (domestic cups, super cups and unlisted European matches) club rows kept; 598 excluded as friendlies, logged with reason in `betfair_excluded_friendlies.csv`.

Still open: none. Remaining uncertainty, for the report:
- International-break friendlies are in `other` (decision 8).
- Inferred winter cup ties (decision 9) may include an occasional winter friendly against a domestic side outside Germany and the Netherlands. One doubtful case: Galatasaray v Alanyaspor, 26/02/2023, during the post-earthquake league suspension.

### Step 1: Pinnacle odds unreliable for all of 2025/26

Found and fixed: 2026-10-05.

Football Data's data page says: "Since 23/07/2025 Pinnacle's public API for odds delivery has become unreliable meaning their odds are systematically out of date relative to odds for other bookmakers, including both the pre-closing and closing odds. Consequently they should be used with caution [...] and are no longer being included for the calculation of market average and maximum odds." Pinnacle closed its public API on 23/07/2025; only bespoke commercial and academic access remains.

So the problem is not only the gap (Pinnacle columns stop between late October 2025 and mid January 2026, depending on the league). The 236 rows in 2025/26 that used `pinnacle_closing` were themselves suspect, because those prices may be stale.

Can the gap be filled? Not from a free source:
- The live Football Data file is byte-identical to our snapshot, so nothing has been backfilled.
- There is no public archive of historical Pinnacle odds. Third-party Pinnacle feeds (pinnapi, pinnodds, etc.) are real-time only.
- Pinnacle offers bespoke access to academics via api@pinnacle.com, but it is unclear whether that includes historical closing lines.

Alternatives already in our raw files for 2025/26:
- Market average closing (`AvgCH/D/A`): 2,518 of 2,518 matches. Pinnacle is now excluded from this average.
- Betfair Exchange closing (`BFECH/D/A`): 2,367 of 2,518 matches. An exchange price, sharp like Pinnacle, and consistent with Step 1b.

Fix: `select_odds` ignores both Pinnacle sets for matches on or after 23/07/2025 (`PINNACLE_UNRELIABLE_FROM`), and Betfair Exchange closing was added to the priority list after market average closing. 2025/26 now uses `average_closing` for 495 rows and `betfair_exchange_closing` for 1 (Celtic v Hearts, below). No Pinnacle odds are used after the cutoff. Covered by `test_select_odds_ignores_pinnacle_after_api_closure`.

For the report: 2012/13 to 2024/25 rest almost entirely on Pinnacle closing odds, 2025/26 on market average closing. The two are nearly equally accurate on matches that have both (Brier 0.56677 vs 0.56708, log loss 0.95553 vs 0.95621, 16,677 matches), but `odds_source` allows a robustness check by source.

Still possible: ask Pinnacle for academic access to 2025/26 closing lines (api@pinnacle.com).

### Step 1: bad average closing odds, Celtic v Hearts, 16/05/2026

Found and fixed: 2026-10-05, first real run of Step 1.

The row's market average closing odds were 1.55 / 4.98 / 20.28 (H/D/A), giving an overround of 0.895. An overround below 1 means backing all three outcomes would guarantee a profit, which no real market offers. Normal values are about 1.02 to 1.08.

Cause: one bookmaker posted junk closing prices (`MaxCD` 17.00, `MaxCA` 251.00), which dragged the average up. Every other price for this match agrees on an away price of about 5: Bet365 closing 1.57 / 4.10 / 5.00, average prematch 1.56 / 4.20 / 5.01. Left as is, Hearts' win probability would have been about 5% instead of about 19%.

Fix: `select_odds` now treats any odds set with overround below 1.00 as invalid and falls back to the next set in the priority list. This match now uses Betfair Exchange closing odds 1.67 / 4.40 / 5.60 (overround 1.005, p_loss 0.178), added to the priority list by the Pinnacle fix below. Before that fix it fell back to average prematch (1.56 / 4.20 / 5.01). It is the only row affected; the minimum overround in the output is now 1.007. Covered by `test_select_odds_skips_overround_below_one`.

The shared warning range in `check_club_rows` stays at 0.90 to 1.15, because Betfair exchange prices (Step 1b) can legitimately sum slightly below 1.

### Step 1: pandas PerformanceWarning noise

Found and fixed: 2026-10-05.

`load_season_file` added `league` and `season` columns to a wide, fragmented frame, which printed a large number of `PerformanceWarning` messages. Harmless to the results. Fixed by copying (defragmenting) the frame before adding columns, in `load_season_file` and after the concat in `build_match_expectations`. The run now prints no warnings.

## Known data features (no action needed, mention in report)

### Step 4: findings and method notes for the report

Found 2026-10-09 while running Step 4; details and numbers in `step4_event_study.md`.

- **Match-week pattern.** Whatever the result, club stocks' abnormal returns rise about 0.4% on the two trading days before a match and fall after it (-0.2% to -0.9% from day 0 to day +3 depending on the measure; see "Match-week pattern" in `step4_event_study.md`). Consistent with pre-match investor optimism reported in earlier studies. It made the pre-specified good v bad news test (H2) misleading: splitting the surprise into its positive and negative parts without absorbing the common fall reads it as asymmetric drift. With an indicator of any match at each lag the asymmetry disappears (p 0.99). Both results are reported; the pre-specified one is explained as misspecified.
- **Spread estimates are rough.** Range-based estimators break on this data: Corwin–Schultz gives 0 for Porto and Sporting (one trade a day, high = low on 78% and 76% of traded days), Abdi–Ranaldo gives 0 for the Turkish clubs and 2.5% for Benfica. Corwin–Schultz is used except for Porto and Sporting. The backtest conclusion does not rest on them: the gross gain per trade is about the size of the commission alone. Bloomberg bid and ask (only Roma pulled, from 2019) would give quoted spreads if ever needed.
- **Transaction taxes** applied as best known, to verify: Italian FTT on Juventus purchases throughout, UK stamp duty on Celtic before 28/04/2014.
- **Manchester United and Celtic barely react** on day 0 (about 0.1% per unit of surprise against 0.5% to 1.7% for the others). Not a timing error for Man Utd (no reaction the day before or after). Possible reasons for the report: Man Utd's small US-listed free float, Celtic's thin trading.
- **Outliers in the backtest.** A few large moves (Benfica +60% in two days, March 2014) drive the long only gross mean; medians are reported next to means.
- **Clean event window.** With a match every 3 to 4 days, almost no match has a clean -5 to +10 window (6 of 9,834); the descriptive picture uses -3 to +3.

### Step 3: share price data

Found: 2026-10-08, first Step 3 run (Yahoo Finance).

- **Roma: prices from Bloomberg** (updated 2026-10-08). AS Roma SpA delisted from Borsa Italiana on 12/09/2022 (last trading day; Friedkin takeover). Yahoo removed the history and Stooq blocks scripted access; Bloomberg's European Composite line `ASR EU Equity` has it (Milan line retired). Caveats in `bloomberg_pull_2026-10-08.md`: composite line, holiday rows without volume, capital increases not cross-checked.
- **Lyon** trades as Eagle Football Group (`EFG.PA`, formerly OL Groupe `OLG.PA`); Yahoo keeps the full history under the new ticker.
- **Turkish rights issues misdated by Yahoo (fixed with Bloomberg).** First read as bonus issues from five single-day falls of 59 to 79%. Bloomberg CACS shows seven paid rights issues (2024 to January 2026); Yahoo applies each about a week before the ex-date and only to later prices. Two smaller ones (BJKAS 07/04/2025 -27%, GSRAY 30/06/2025 -23%) were below the first check's threshold and had been missed. All seven use Bloomberg's adjustment factors, which give the misdated days plausible returns (-5.9% to +4.0%); no return is excluded. The last one (FENER 29/12/2025 on Yahoo, ex-date 05/01/2026) was found in CACS after the first pull. A second lookup covered Juventus, Lyon and Roma: Yahoo also misdates Juventus's March 2024 rights issue (-14.5% on 04/03/2024 becomes +0.1% with Bloomberg's factor; the market moved -0.1%) and adjusts the November 2021 one correctly; Lyon had none; Roma's June 2014 rights issue shows +30% on the ex-date in Bloomberg's own series, so that day's return is excluded. The remaining large drops of these clubs are genuine (e.g. Dortmund -27% on 29/05/2023 after losing the title on the last day, Ajax -20% on 09/05/2019 after the Champions League semi-final, the Italian club stocks -24 to -32% together on 16/10/2013).
- **Large genuine moves left in**: Porto +85% (07/04/2020) and Sporting +56%, +53%, +90% (2012/13): penny stocks (Sporting €0.16 to 0.95) jumping after days without trades; Benfica +70% (19/11/2019), the club's tender offer for the SAD's shares.
- **Illiquid stocks.** Share of trading days with zero volume: Porto 23.8%, Sporting 18.7%, Celtic 13.5%, all others 2% or less. A match's effect on these stocks can show up days late, when the stock next trades; `stale_day0` flags 401 matches. Step 4 should test robustness to dropping them, or measure returns from the last trade.
- **PSI 20**: Yahoo's series starts 30/04/2013; the Bloomberg series (2011 on) is used instead and matches Yahoo within 0.9% where both exist.
- **Remaining Turkish ±20% days** are real: Borsa Istanbul's daily price limit is 20% (and the COVID crash, 12/03/2020).
- **Borsa Istanbul close time** history (17:30, then 18:00 from 30/11/2015 in the config) is to verify. Matches ending within an hour of any close are flagged `near_close` (264).
- **Man Utd and the NYSE close**: UK evening kickoffs end around 16:40 New York time, just after the close; day 0 is the next session. After-hours trading is not in daily data.

### Step 2: listed clubs beat market expectations slightly in their domestic leagues

Found: 2026-10-07, first Step 2 run. Mean surprise is +0.033 overall (se 0.007, 9,368 rows). By competition: league +0.044 (se 0.008), european +0.006 (se 0.025), other -0.005 (se 0.019). So it is a league effect. On league matches the clubs won 61.6% against an implied 58.7%, about 2.8 points per club per 38-match season above expectation. Every season but two (2019/20, 2021/22) is positive.

By club (league): highest for dominant clubs in less competitive leagues (Sporting +0.090, Juventus +0.086, Benfica +0.086, Galatasaray +0.084), about zero for Dortmund (-0.015), Lyon (0.000) and Man Utd (+0.011).

Not a bookmaker artefact: on the 5,418 league matches both sources have, mean surprise is +0.039 against bookmaker odds and +0.025 against Betfair exchange prices (se about 0.01). The near-zero mean on Betfair rows in `match_surprise.csv` (0.000) is because those rows are all European and cup matches, not because exchange prices are unbiased. (Corrects the first version of this entry.)

Likely causes:
1. Margin removal. Proportional normalisation leaves part of the favourite-longshot bias in, and the listed clubs are usually favourites. The power method lowers the league mean by about a third (+0.042 to +0.030 on Pinnacle closing), the same size as the bookmaker vs Betfair gap above.
2. Club selection. The sample is the big listed clubs, several of which dominated their league in the period (Juventus nine titles in a row from 2011/12, the Portuguese and Turkish big three). Choosing clubs that are big today brings some hindsight.
3. A real market bias: the market slightly underrates dominant clubs against weaker domestic opponents. Betting the listed club to win at the closing odds used here returned +1.3% per bet over 7,017 bookmaker-odds matches (+3% for clubs priced 55% to 85%), before limits and with the selection caveat above.

Why it matters: terciles are relative, so the buckets are unaffected. A regression on raw surprise in Step 4 would mix in a constant, and part of a "positive surprise" for these clubs was predictable. Robustness options for Step 4: surprise demeaned by club or by `odds_source`, or probabilities from the power method. Also a side finding for the report.

### Step 1b: Betfair coverage

Found: 2026-10-06. Download fixed and run.

- Basic soccer data starts May 2015, so 2012/13 to 2014/15 have no Betfair (European or cup) coverage.
- The first download version listed every MATCH_ODDS file of each Tuesday to Thursday (about 24 hours, no weekend cup matches). Replaced by a search by club name, month by month, every weekday: 9,840 files, 77 minutes, no errors.
- Two MATCH_ODDS markets per event (main and thin) and postponed matches are handled by `_select_markets`: 1,557 duplicates, 255 never in play, 14 incomplete, all logged.
- Agreement with bookmaker odds on 5,422 shared league matches: correlation 0.999, mean absolute difference in win probability 0.011.
- League coverage (share of Step 1 league matches Betfair also has): 88% to 100% per season, lowest in 2017/18 (88%) and 2015/16 (92%); 100% in five seasons from 2019/20 after the runner-name fix below.
- European coverage (share of fixture-list matches Betfair has): 80% to 99% from 2015/16 to 2018/19 (CL only on the list), 100% from 2019/20. Checked 2026-10-06 against all 897 European fixtures of the listed clubs: every gap is a Champions League match, 24 of 25 from 2015/16 to 2017/18, both group and knockout (2015/16 mostly knockouts, 2017/18 mostly the last two group matchdays). For most of them the other leg is on Betfair under the same names, so the markets are absent from Basic, not missed by the search. Five qualifier legs are missing too (Man Utd v Club Brugge 2015, Celtic v Hapoel Beer Sheva 2016, Celtic v Astana, Linfield v Celtic and Nice v Ajax 2017).
- **Filled from OddsPortal (2026-10-06):** those 30 matches now use OddsPortal average closing odds (`odds_source = oddsportal_avg_closing`, 32 club rows); fixture-list coverage is 100% in every season. Validated on 252 CL matches both sources have: mean absolute difference 0.010 / 0.006 / 0.009 (H/D/A), correlation 0.999. Details and caveats (UK bookmakers only, 90 minute results, scraping terms) in `docs/step1b_betfair.md`. Europa League before 2020/21 and domestic cups have no reference list, so their gaps are not measured.
- Placeholder kickoffs: knockout markets open right after the draw with a provisional `marketTime`, corrected later (472 files). The parser reads the last market definition, so dates are right; anything reading the first definition gets them wrong.
- **Fixed 2026-10-06: runner names differing from the event name.** `parse_market` required runner names to equal the team names in the event name exactly, so 90 files (about 45 matches) were dropped without a log entry: "Spal" in "Juventus v SPAL", "Az Alkmaar", "FC GRONINGEN", "Qarabag Fk", "Karabakh" / "Qarabag FK", Bodrumspor spellings, "Sporting Lisbonn". Runners are now matched ignoring case, and a single unmatched team gets the remaining non-draw runner. Recovered 74 club rows (47 league, 6 European, 21 other); league coverage rose in every season it touched (2017/18 from 86.4% to 87.6%, 2018/19 from 94.6% to 96.4%, 2019/20 to 2022/23 from 97.9-99.6% to 100%). Covered by `test_parse_market_runner_names_differ_from_event_name`.

Library quirk: betfairlightweight 2.24.0 (latest) sends `historic.get_my_data()` as POST, but the endpoint now only accepts GET (405). Not used by the pipeline.

### Forfeits and season lengths are tracked in config

The Turkish 2022/23 forfeits (6 matches, Gaziantep and Hatayspor withdrew after the February 2023 earthquake) are listed under `excluded_matches` in `config/clubs.yaml`, removed explicitly and logged to `data/processed/excluded_matches.csv`. Before this they were only dropped because they happened to have no odds. Galatasaray, Fenerbahce and Besiktas each lose 2 matches in 2022/23 (36 played in the file, 34 kept).

Every non-standard league season is listed under `season_notes` in the config with its reason: Covid curtailments in 2019/20 (Eredivisie, Ligue 1, Scottish Premiership), the 16-team Primeira Liga in 2012/13 and 2013/14, Ligue 1 at 18 teams from 2023/24, and the Super Lig's changing size from 2020/21 to 2024/25. `data/processed/season_counts.csv` has, per club and season, matches in the raw file, excluded, no odds, rows kept and the season note. The run fails if those do not add up, and warns about any non-standard season with no note.
