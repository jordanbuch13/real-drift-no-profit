# Bloomberg data pull, 8 October 2026

Pulled by Jordan on an Imperial Abdus Salam Library terminal. The exported workbook is `data/raw/bloomberg/matchday_alpha_bloomberg.xlsx` and is **not committed** to git (`data/raw/` is ignored). Imperial's Bloomberg licence says exported data should stay on the terminal; Jordan confirmed on 2026-10-13 that the export can be included in the capstone submission's data snapshot.

## What was pulled

| Item | Status | Where |
|---|---|---|
| AS Roma | done | sheet `ASR_EU` |
| PSI 20 index | done | sheet `Sheet2` |
| Corporate actions (CACS) of the Turkish clubs | done, 6 events | `corporate_actions` in `config/clubs.yaml` |
| Cross-check of the other 12 clubs and benchmarks | not done (no time) | Yahoo Finance is kept for these |

BDH settings: `Days=T` (trading days only), `Fill=B` (no carry-forward), fields `PX_LAST, PX_OPEN, PX_VOLUME, TOT_RETURN_INDEX_GROSS_DVDS, PX_BID, PX_ASK`, from 03/01/2011. Sheet layout: row 1 the ticker, row 2 the headers (`Date, PX_Last, PX_OPEN, PX_VOLUME, TOT_RETURN, PX_BID, PX_ASK`), data from row 3.

## AS Roma

- `ASR IM Equity` no longer resolves (the Milan line was retired after the 2022 delisting). Used `ASR EU Equity` (European Composite, flagged "Acquired") through its FIGI `/bbgid/BBG000MHXQF7`; ISIN IT0001008876; IPO 23 May 2000.
- 2,977 days, 03/01/2011 to 12/09/2022, the **last trading day** (close 0.404).
- Composite line, not the Milan primary: Roma only traded in Milan, so prices should match, but volume combines venues. It has rows on Italian holidays (Ferragosto), some with volume, so trading calendars are built without Bloomberg equity lines.
- `TOT_RETURN` equals `PX_LAST` every day: Roma paid no cash dividends. Capital increases could not be checked against a second source (Yahoo has no Roma); no single-day move in the series looks like an unadjusted capital change (largest: +56% on 09/11/2020, a market-wide rally day).
- Bid and ask only from 24/06/2019 (823 days).

## PSI 20

- 4,035 days, 03/01/2011 to 07/10/2026; bid and ask empty. Matches Yahoo's `PSI20.LS` within 0.9% on the 3,425 days both have, and covers 2011 to April 2013, which Yahoo lacks. The pipeline uses the price (`PX_LAST`), like the other benchmark indices, which are price indices.

## Turkish corporate actions (CACS)

Paid, renounceable rights issues, not bonus issues. Istanbul line only.

| Ticker | Ex-date | Rights per 100 | Subscription (TRY) | Adjustment factor | CACS id |
|---|---|---|---|---|---|
| BJKAS TI | 2024-07-03 | 400 | 1 | 0.223881 | 237825303 |
| FENER TI | 2024-12-17 | 152.58 | 6 | 0.430243 | 240506333 |
| GSRAY TI | 2024-12-30 | 400 | 1 | 0.326984 | 240647684 |
| BJKAS TI | 2025-04-16 | 400 | 2 | 0.740541 | 241709291 |
| FENER TI | 2025-06-30 | 400 | 1 | 0.216488 | 242621727 |
| GSRAY TI | 2025-07-07 | 150 | 1 | 0.752941 | 242705762 |
| FENER TI | 2026-01-05 | 400 | 2 | 0.37094 | 244903404 |

No other split, bonus or rights events in CACS for these three stocks between 06/2024 and 12/2025. The FENER January 2026 event (announced 26/11/2025, record date 06/01/2026, 4,795M shares, TRY 9,590M) was looked up afterwards, also on 2026-10-08, to explain Yahoo's 64% drop on 29/12/2025. Yahoo applies each of these about a week before the ex-date (only BJKAS 2024-07-03 on the day); see `docs/issues.md`.

## Second CACS lookup (same day): Juventus, Lyon, Roma

Checked because Yahoo or Bloomberg prices had drops that looked like capital changes.

| Ticker | Ex-date | Terms | Factor | CACS id | Used |
|---|---|---|---|---|---|
| JUVE IM | 2021-11-29 | 9 per 10 at EUR 0.334 (EUR 399.87M) | 0.801704 | 228500564 | No: Yahoo adjusts it correctly (no jump) |
| JUVE IM | 2024-03-11 | 1 per 2 at EUR 1.582 (EUR 199.92M) | 0.853664 | 237549327 | Yes: Yahoo applies it on 04/03/2024; -14.5% becomes +0.1% (market -0.1%) |
| ASR (ASRAF US line, date from the Milan primary) | 2014-06-30 | 2 per 1 at EUR 0.377 (EUR 99.92M) | 0.595138 | 92970997 | Return on 30/06/2014 excluded: Bloomberg's own series is adjusted but shows +30% that day |

Lyon (EFG FP): no rights issues 2011 to 2026, so its large drops are genuine.

## Citations

- Bloomberg L.P., AS Roma SpA (ASR EU Equity; FIGI BBG000MHXQF7; ISIN IT0001008876), daily prices 3 Jan 2011 to 12 Sep 2022, retrieved 8 Oct 2026.
- Bloomberg L.P., PSI 20 Index (PSI20 Index), daily price and gross total return index, 2011 to 2026, retrieved 8 Oct 2026.
- Bloomberg L.P., Corporate Actions (CACS) for GSRAY, FENER and BJKAS TI Equity, JUVE IM Equity, EFG FP Equity and AS Roma, retrieved 8 Oct 2026.
