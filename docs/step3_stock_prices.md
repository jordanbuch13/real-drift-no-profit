# Step 3: Stock Prices and Trading Day Alignment

**Status:** implemented in `src/step3_prices.py`, run on real data 2026-10-08 (prices to 07/10/2026). 10,038 matches: day 0 found for all; the club stock has a price on day 0 for 9,834 (Roma's matches after its last trading day, 12/09/2022, are not listed); 401 stale on day 0 (no trade), 264 near the close. Day 0 is the next calendar day for 66% of matches, two days later (weekend to Monday) for 25%, the match day itself for 80 matches.

## Context

Steps 1 to 2 give one row per club per match with the market's expectation and the surprise (`data/processed/match_surprise.csv`, 10,038 rows, 2012/13 to 2025/26). This step gets the clubs' share prices and a benchmark index for each, and finds for every match the first trading day on which the result could move the price (event day 0). Step 4 computes abnormal returns, runs the event study and the backtest.

**Goal:** daily prices for each club and benchmark, and `match_surprise.csv` extended with the event day and a few liquidity flags.

## Stocks and benchmarks

Checked on Yahoo Finance (`yfinance`) on 2026-10-08:

| Club | Ticker | Exchange (currency) | History | Zero-volume days | Local benchmark |
|---|---|---|---|---|---|
| Manchester United | MANU | NYSE (USD) | from 10/08/2012 (IPO) | 0% | S&P 500 `^GSPC` |
| Juventus | JUVE.MI | Borsa Italiana (EUR) | 2012 on | 0% | FTSE MIB `FTSEMIB.MI` |
| Lazio | SSL.MI | Borsa Italiana | 2012 on | 0% | FTSE MIB |
| Roma | `ASR EU Equity` (Bloomberg; Milan line ASR.MI retired) | Borsa Italiana | 03/01/2011 to 12/09/2022 (last trading day; Yahoo has none) | 0% | FTSE MIB |
| Borussia Dortmund | BVB.DE | Xetra (EUR) | 2012 on | 0% | DAX `^GDAXI` |
| Ajax | AJAX.AS | Euronext Amsterdam (EUR) | 2012 on | 1% | AEX `^AEX` |
| Celtic | CCP.L | London AIM (GBP) | 2012 on | 13% | FTSE AIM All-Share `^FTAI` |
| Benfica | SLBEN.LS | Euronext Lisbon (EUR) | 2012 on | 1% | PSI 20 (`PSI20 Index`, Bloomberg, 2011 on; Yahoo's `PSI20.LS` starts 30/04/2013) |
| Porto | FCP.LS | Euronext Lisbon | 2012 on | 24% | PSI |
| Sporting CP | SCP.LS | Euronext Lisbon | 2012 on | 19% | PSI |
| Lyon | EFG.PA (Eagle Football Group, formerly OL Groupe `OLG.PA`) | Euronext Paris (EUR) | 2012 on | 1% | CAC 40 `^FCHI` |
| Galatasaray | GSRAY.IS | Borsa Istanbul (TRY) | 2012 on | 2% | BIST 100 `XU100.IS` |
| Fenerbahce | FENER.IS | Borsa Istanbul | 2012 on | 2% | BIST 100 |
| Besiktas | BJKAS.IS | Borsa Istanbul | 2012 on | 2% | BIST 100 |

Tickers, exchanges (time zone, close times) and benchmarks are in `config/clubs.yaml`; STOXX Europe 600 (`^STOXX`) is downloaded as the robustness benchmark.

## Tasks

### 1. Download and snapshot prices

Daily open, high, low, close, adjusted close, volume, dividends and splits for every club and benchmark, 2012-01-01 to the day before the download (the download day may be an unfinished session), saved unmodified to `data/raw/prices/{ticker}.csv` (`^` becomes `IDX_`); skip if on disk. Returns use the adjusted close.

Bloomberg exports (`data/raw/bloomberg/*.xlsx`, not committed, see `bloomberg_pull_2026-10-08.md`) add Roma and the PSI 20; `load_prices` reads both sources (`source` column). Equities use Bloomberg's total return index as adjusted close, indices the price.

Yahoo misdates the Turkish clubs' rights issues: it applies each adjustment about a week before the ex-date and only to later prices, leaving one fake crash (BJKAS 03/07/2024 and 07/04/2025; FENER 09/12/2024, 23/06/2025 and 29/12/2025; GSRAY 23/12/2024 and 30/06/2025: falls of 23 to 79%). `corporate_actions` in the config lists them with Bloomberg's CACS adjustment factors: earlier adjusted prices are multiplied by the factor, and the day's return is kept (it comes out between -5.9% and +4.0%, so Yahoo used the same factors). FENER 29/12/2025 (-64%, ex-date 05/01/2026) was added after a second CACS lookup. Juventus's March 2024 rights issue is misdated the same way (04/03/2024, Bloomberg factor 0.853664). An event without a usable factor has earlier prices divided by the jump and its return excluded (`exclude_return`): only Roma's ex-date, 30/06/2014, where Bloomberg's own adjusted series jumps +30% (off-season, no match nearby). Trading calendars leave out Bloomberg equity lines (Roma's composite line has rows on Italian holidays).

### 2. Trading calendar per stock

A trading day is a day the stock's exchange was open: every date on which the exchange's benchmark or any of its club stocks has a price with a volume (Bloomberg's Roma line has volume-less rows on Italian holidays such as Ferragosto). Days the exchange was open but the stock did not trade (zero volume, or a missing row) are kept and flagged: the price is stale.

### 3. Event day 0

For each match: kickoff (UK time, `kickoff_time`) plus 115 minutes is the estimated end. Extra time is not added (the data does not record it for most matches); a match that went to extra time ends about 35 minutes later, which matters only near a close and is covered by `near_close`. Convert to the exchange's local time. Event day 0 is the first trading day whose close comes after the end of the match:
- match ends before that day's close (e.g. a Turkish Cup tie at 13:00 on a weekday): day 0 is that day,
- match ends after the close or on a non-trading day (evening and weekend matches, almost all): day 0 is the next trading day.

Exchange close times (local, `exchanges` in the config): NYSE 16:00; Borsa Italiana, Xetra, Euronext Amsterdam and Paris 17:30; Euronext Lisbon 16:30; LSE 16:30; Borsa Istanbul 17:30, then 18:00 from 30/11/2015 (the Istanbul change date is to verify). Rows with `kickoff_source = none` (weekend) are put after every close; `assumed_evening` rows take 19:45 UK.

Man Utd: a 19:45 UK kickoff ends about 16:40 in New York, 40 minutes after the NYSE close, so many Man Utd matches are `near_close`; day 0 is correctly the next session (after-hours trades are not in daily closes).

Flag matches ending within an hour of the close (`near_close`): day 0 is uncertain there, Step 4 can drop them as a robustness check.

### 4. Outputs

`data/processed/prices.csv` (long: ticker, date, close, adj_close (corporate actions applied), volume, source, corporate_action, exclude_return, stale, role club/benchmark) and `data/processed/match_events.csv`: every column of `match_surprise.csv` plus

| Column | Description |
|---|---|
| ticker, exchange | from the config |
| match_end_local | estimated end of the match in exchange local time |
| event_date | trading day 0 |
| days_to_next_match_trading | trading days from day 0 to the next match's day 0 (overlapping windows) |
| listed | the club's stock was listed and has prices on day 0 |
| stale_day0 | no trade in the stock on day 0 |
| near_close | match ended within an hour of the close |

Code in `src/step3_prices.py`, entry point `build_match_events()`, notebook heading "Data acquisition: stock prices".

## Checks

1. Every listed club has prices on at least 95% of its exchange's trading days in its listing period; print per club.
2. No adjusted daily return beyond ±50% without a printed explanation (splits, rights issues, data errors).
3. `event_date` is a trading day, never before the match date, at most 5 calendar days after it.
4. Spot check: five matches with kickoff, estimated end, exchange close and event date.

## Decisions

Decided with Jordan, 2026-10-08:

1. **Price source: Yahoo Finance**, via `yfinance` (free, unofficial; Yahoo's terms are for personal use), **plus Bloomberg** (Imperial library, pulled 2026-10-08) for what Yahoo lacks or gets wrong: Roma, the PSI 20, the Turkish corporate actions. A Bloomberg cross-check of the other clubs was not done; possible later.
2. **Roma: in, from Bloomberg**, to its last trading day 12/09/2022 (delisted after the Friedkin takeover). Later matches have `listed = False`. Survivorship point for the report: the delisted club needed a licensed database.
3. **Benchmark: local index** (table above) for the main analysis, **STOXX Europe 600** as a robustness check. The PSI 20 now covers the whole period (Bloomberg).

## Not in this step

Abnormal returns, event windows, the event study and the backtest are Step 4.
