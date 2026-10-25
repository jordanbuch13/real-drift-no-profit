# Data

No data is committed. The pipeline expects raw files in `data/raw/<source>/` and writes everything it builds to `data/processed/` (both folders are created as needed and ignored by git).

Three sources are licensed or have terms that forbid redistribution (Betfair, OddsPortal, Bloomberg), so you have to obtain them yourself. The public sources are downloaded by the code.

## Summary

| Folder | Source | Licence / terms | How to get it | Size |
|---|---|---|---|---|
| `raw/football_data/` | [football-data.co.uk](https://www.football-data.co.uk/) league results and closing odds, 2012/13 to 2025/26 | Free download | Automatic | 113 CSV files, 13 MB |
| `raw/openfootball/` | [openfootball/champions-league](https://github.com/openfootball/champions-league) European fixture lists | Public domain | Automatic | 29 files, 0.4 MB |
| `raw/wikipedia/` | English Wikipedia club season articles (wikitext) | CC BY-SA | Automatic, about 15 min | 196 files, 18 MB |
| `raw/wikipedia_leagues/` | English Wikipedia league season articles (rendered HTML) | CC BY-SA | Automatic, about 7 min | 112 files, 49 MB |
| `raw/prices/` | Yahoo Finance daily prices via `yfinance` | Yahoo terms, personal use | Automatic | 22 CSV files, 9 MB |
| `raw/betfair/` | Betfair Exchange historical data, BASIC plan, May 2015 to May 2026 | Betfair historical data terms: no redistribution | **Needs your own Betfair account**, then automatic, about 80 min | about 9,900 `.bz2` files, 70 MB |
| `raw/oddsportal/` | OddsPortal closing odds, results, kickoff times, competition listings | Terms do not allow automated collection | **Manual**, separate scraping tool | about 380 files, 16 MB |
| `raw/bloomberg/` | Bloomberg terminal: AS Roma prices (delisted 2022), PSI 20 index | Licensed, no redistribution | **Manual** export from a Bloomberg terminal | 1 `.xlsx` file |

## Automatic downloads

Open `notebooks/pipeline.ipynb`, set `DOWNLOAD = True` in the setup cell and run all cells. The acquisition cells only fetch files that are missing, so you can rerun safely. The same functions can be called directly from the repository root:

```
python -c "from src.common import load_config; from src.step1_expectations import download_season as d; c = load_config(); [d(l, s) for l in c.leagues for s in c.seasons]"
python -c "from src.european_fixtures import download_openfootball as d; d([f'{y}-{(y+1)%100:02d}' for y in range(2012, 2026)])"
python -c "from src.wikipedia_fixtures import download_seasons as d; d(2012, 2025)"
python -c "from src.league_tables import download_tables as d; d()"
python -c "from src.step3_prices import download_prices as d; d()"
```

Yahoo Finance revises adjusted prices when dividends and splits are added, and Wikipedia articles get edited, so a fresh download can give results that differ slightly from the published ones (snapshot taken 5 to 9 October 2026).

## Betfair (needs an account)

1. Open a Betfair account and create an application key ([developer docs](https://developer.betfair.com/)).
2. Sign in at [historicdata.betfair.com](https://historicdata.betfair.com/) and "purchase" the free BASIC plan for football, May 2015 to May 2026.
3. Copy `.env.example` to `.env` in the repository root and fill in `BETFAIR_USERNAME`, `BETFAIR_PASSWORD` and `BETFAIR_APP_KEY`. `.env` is ignored by git; never commit it.
4. Run the notebook with `DOWNLOAD = True`, or:

```
python -c "from src.step1b_betfair import download_basic as d; d('2015-05-01', '2026-05-31')"
```

Files are saved by month under `raw/betfair/YYYY/MM/`. The download resumes where it stopped.

## OddsPortal (manual)

OddsPortal fills what Betfair lacks: European and cup matches 2012/13 to 2014/15, some Champions League matches 2015/16 to 2018/19, 74 later gaps, league kickoff times before 2019/20, and competition names. The pages were fetched once with [OddsHarvester](https://github.com/jordantete/OddsHarvester), a separate tool that needs Python 3.12 and a Playwright browser. OddsPortal's terms do not allow automated collection, so check them before you scrape.

The exact commands, what was fetched and the file names the code expects are in `docs/step1b_betfair.md` and `docs/data_sources.md` ("What was fetched from OddsPortal"). The layout is:

```
raw/oddsportal/
  cl_odds_<season>.json, cups_odds_<season>.json, gap_odds_<season>.json    match odds (1X2)
  cl_links_<season>.csv                                                     Champions League link lists
  links/<country>_<competition>_<season>.csv                                competition link lists
  league_kickoffs/league_odds_<season>.json, league_kickoffs/links/*.csv    league kickoff times 2012/13 to 2014/15
```

## Bloomberg (manual)

Needed for AS Roma (no Yahoo history after its 2022 delisting), the PSI 20 before 2013, and Roma's quoted bid and ask for the cost checks. From a Bloomberg terminal, export one workbook to `raw/bloomberg/` (any `.xlsx` name) with one sheet per security:

| Sheet | Security |
|---|---|
| `ASR_EU` | `/bbgid/BBG000MHXQF7` (AS Roma, `ASR EU Equity`) |
| `Sheet2` | `PSI20 Index` |

BDH settings: `Days=T`, `Fill=B`, from 03/01/2011, fields `PX_LAST, PX_OPEN, PX_VOLUME, TOT_RETURN_INDEX_GROSS_DVDS, PX_BID, PX_ASK`. Row 1 holds the ticker, row 2 the headers (`Date, PX_Last, PX_OPEN, PX_VOLUME, TOT_RETURN, PX_BID, PX_ASK`), data from row 3. Details in `docs/bloomberg_pull_2026-10-08.md`. The Turkish and Juventus corporate actions also taken from Bloomberg are already in `config/clubs.yaml`.

## Processed files

`data/processed/` is rebuilt by running the notebook with all raw folders in place (about 2.5 minutes). Every step logs dropped or corrected rows there; `docs/issues.md` explains them.
