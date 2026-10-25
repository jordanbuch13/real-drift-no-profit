"""Step 3: club share prices, benchmark indices, and the trading day each match first affects.

Entry points: download_prices() and build_match_events(). See docs/step3_stock_prices.md.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .common import PROCESSED, ROOT, load_config

RAW_PRICES = ROOT / "data" / "raw" / "prices"
RAW_BLOOMBERG = ROOT / "data" / "raw" / "bloomberg"
MATCH_MINUTES = 115            # kickoff to final whistle: 90 minutes, half time, stoppage time
ASSUMED_EVENING_UK = "19:45"   # weekday matches with no kickoff time anywhere
NEAR_CLOSE = pd.Timedelta(hours=1)


def is_bloomberg(ticker: str) -> bool:
    """Bloomberg tickers end in Equity or Index ("ASR EU Equity", "PSI20 Index"); the rest is Yahoo."""
    return ticker.endswith((" Equity", " Index"))


def _file(ticker: str, raw_dir: Path) -> Path:
    return raw_dir / f"{ticker.replace('^', 'IDX_')}.csv"


def download_prices(start: str = "2012-01-01", end: str | None = None, raw_dir: Path = RAW_PRICES) -> None:
    """Save daily prices (open, high, low, close, adjusted close, volume) of every club ticker and
    benchmark from Yahoo Finance, unmodified, to raw_dir/{ticker}.csv. Skips files on disk."""
    import yfinance as yf  # imported here so the rest works without it

    cfg = load_config()
    tickers = sorted({t for t in cfg.clubs["ticker"].dropna()} | set(cfg.clubs["benchmark"])
                     | ({cfg.robustness_benchmark} if cfg.robustness_benchmark else set()))
    tickers = [t for t in tickers if not is_bloomberg(t)]  # Bloomberg data is exported by hand
    raw_dir.mkdir(parents=True, exist_ok=True)
    end = end or pd.Timestamp.today().strftime("%Y-%m-%d")  # exclusive: today may be an unfinished session
    for t in tickers:
        path = _file(t, raw_dir)
        if path.exists():
            continue
        h = yf.Ticker(t).history(start=start, end=end, auto_adjust=False, actions=True)
        if h.empty:
            print(f"WARNING no prices for {t}")
            continue
        h.index = h.index.tz_localize(None).normalize()
        h.index.name = "date"
        h.to_csv(path)
        print(f"{t}: {len(h)} days, {h.index.min():%Y-%m-%d} to {h.index.max():%Y-%m-%d}")


def load_bloomberg(raw_dir: Path = RAW_BLOOMBERG) -> pd.DataFrame:
    """Bloomberg BDH exports (data/raw/bloomberg/*.xlsx, one sheet per security: row 1 the
    ticker, row 2 Date, PX_Last, PX_OPEN, PX_VOLUME, TOT_RETURN, PX_BID, PX_ASK). Equities use the
    total return index as adjusted close; indices use the price (like the Yahoo indices)."""
    frames = []
    for path in sorted(raw_dir.glob("*.xlsx")):
        book = pd.ExcelFile(path)
        for sheet in book.sheet_names:
            ticker = str(pd.read_excel(book, sheet, header=None, nrows=1).iloc[0, 0]).strip()
            h = pd.read_excel(book, sheet, header=1)
            h.columns = [c.upper() for c in h.columns]
            h = h.dropna(subset=["DATE", "PX_LAST"])
            adj = h["TOT_RETURN"] if ticker.endswith("Equity") else h["PX_LAST"]
            frames.append(pd.DataFrame({"ticker": ticker, "date": pd.to_datetime(h["DATE"]), "close": h["PX_LAST"],
                                        "adj_close": adj, "volume": h["PX_VOLUME"]}))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["ticker", "date", "close", "adj_close", "volume"])


def load_prices(raw_dir: Path = RAW_PRICES, bloomberg_dir: Path = RAW_BLOOMBERG) -> pd.DataFrame:
    """Long table: ticker, date, close, adj_close, volume, source (yahoo or bloomberg)."""
    frames = [load_bloomberg(bloomberg_dir).assign(source="bloomberg")]
    for path in sorted(raw_dir.glob("*.csv")):
        h = pd.read_csv(path, parse_dates=["date"])
        ticker = path.stem.replace("IDX_", "^")
        frames.append(pd.DataFrame({"ticker": ticker, "date": h["date"], "close": h["Close"],
                                    "adj_close": h["Adj Close"], "volume": h["Volume"], "source": "yahoo"}))
    return pd.concat(frames, ignore_index=True)


def apply_corporate_actions(prices: pd.DataFrame, actions: pd.DataFrame) -> pd.DataFrame:
    """Corporate actions Yahoo misadjusts (config `corporate_actions`): adjusted prices before
    `date` are multiplied by Bloomberg's adjustment factor, and the day keeps its return; without a
    factor they are divided by the observed jump and the day's return is excluded
    (exclude_return = True). corporate_action marks the date either way."""
    prices = prices.sort_values(["ticker", "date"]).reset_index(drop=True)
    prices["corporate_action"] = False
    prices["exclude_return"] = False
    for a in actions.itertuples():
        day = pd.Timestamp(a.date)
        sel = prices["ticker"] == a.ticker
        before = sel & (prices["date"] < day)
        on = sel & (prices["date"] == day)
        if not on.any() or not before.any():
            raise ValueError(f"corporate action {a.ticker} {a.date}: no prices on or before that date")
        prev, now = prices.loc[before, "adj_close"].iloc[-1], prices.loc[on, "adj_close"].iloc[0]
        if pd.notna(a.factor):
            prices.loc[before, "adj_close"] *= a.factor
            note = f"factor {a.factor:.4f}, return that day {now / (prev * a.factor) - 1:+.1%}"
        else:
            prices.loc[before, "adj_close"] /= prev / now
            prices.loc[on, "exclude_return"] = True
            note = f"no factor: divided by the jump {prev / now:.3f}, return excluded"
        prices.loc[on, "corporate_action"] = True
        print(f"  {a.ticker} {day:%d/%m/%Y}: {note}")
    return prices


def trading_calendars(prices: pd.DataFrame, cfg) -> dict[str, pd.DatetimeIndex]:
    """Trading days per exchange: every date on which the exchange's benchmark or any of its club
    stocks has a price with a volume. Bloomberg equity lines are left out: Roma's is the European
    Composite, which has rows (some with volume from other venues) on Italian holidays such as
    Ferragosto, 15 August, when Borsa Italiana was closed."""
    cal = {}
    traded = prices[prices["volume"].notna() & ~prices["ticker"].str.endswith(" Equity")]
    for ex, g in cfg.clubs.groupby("exchange"):
        tickers = set(g["ticker"].dropna()) | set(g["benchmark"])
        cal[ex] = pd.DatetimeIndex(sorted(traded.loc[traded["ticker"].isin(tickers), "date"].unique()))
    return cal


def close_time(exchange: dict, day: pd.Timestamp) -> str:
    times = sorted(exchange["close_times"], key=lambda c: c["from"])
    current = times[0]["close"]
    for c in times:
        if day >= pd.Timestamp(c["from"]):
            current = c["close"]
    return current


def match_end_utc(date: pd.Timestamp, kickoff_time, kickoff_source) -> pd.Timestamp:
    """Estimated final whistle in UTC. Matches with no time (weekend rows, kickoff_source none)
    are put at 23:00 UK, after every close; weekday rows with no time at 19:45 UK."""
    if isinstance(kickoff_time, str) and ":" in kickoff_time:
        hhmm = kickoff_time
    elif kickoff_source == "assumed_evening":
        hhmm = ASSUMED_EVENING_UK
    else:
        hhmm = "23:00"
    start = pd.Timestamp(f"{date:%Y-%m-%d} {hhmm}").tz_localize("Europe/London")
    end = start + pd.Timedelta(minutes=MATCH_MINUTES) if hhmm != "23:00" else start
    return end.tz_convert("UTC")


def _close_at(exchange: dict, day: pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(f"{day:%Y-%m-%d} {close_time(exchange, day)}").tz_localize(exchange["timezone"])


def event_day(end_utc: pd.Timestamp, calendar: pd.DatetimeIndex, exchange: dict) -> tuple[pd.Timestamp, bool]:
    """First trading day whose close comes after the match ends, and whether the match ended
    within NEAR_CLOSE of that trading day's close on the match's own date (day 0 uncertain)."""
    end_local = end_utc.tz_convert(exchange["timezone"])
    end_date = pd.Timestamp(end_local.date())
    near = end_date in calendar and abs(end_local - _close_at(exchange, end_date)) <= NEAR_CLOSE
    for day in calendar[calendar.searchsorted(end_date):]:
        if _close_at(exchange, day) > end_local:
            return day, bool(near)
    return pd.NaT, bool(near)


def build_match_events(in_path: Path = PROCESSED / "match_surprise.csv", out_dir: Path = PROCESSED,
                       raw_dir: Path = RAW_PRICES) -> pd.DataFrame:
    cfg = load_config()
    prices = apply_corporate_actions(load_prices(raw_dir), cfg.corporate_actions)
    cal = trading_calendars(prices, cfg)
    rows = pd.read_csv(in_path, parse_dates=["date"], dtype={"season": str})
    clubs = cfg.clubs.set_index("club")
    rows["ticker"] = rows["club"].map(clubs["ticker"])
    rows["exchange"] = rows["club"].map(clubs["exchange"])
    rows["benchmark"] = rows["club"].map(clubs["benchmark"])

    ends, days, nears = [], [], []
    for r in rows.itertuples():
        ex = cfg.exchanges[r.exchange]
        end = match_end_utc(r.date, r.kickoff_time, r.kickoff_source)
        day, near = event_day(end, cal[r.exchange], ex)
        ends.append(end.tz_convert(ex["timezone"]).strftime("%Y-%m-%d %H:%M"))
        days.append(day)
        nears.append(near)
    rows["match_end_local"] = ends
    rows["event_date"] = pd.to_datetime(days)
    rows["near_close"] = nears

    # Stock trading on day 0, and listing (prices on day 0)
    px = prices.set_index(["ticker", "date"])
    key = list(zip(rows["ticker"], rows["event_date"]))
    vol = pd.Series([px["volume"].get(k, np.nan) if isinstance(k[0], str) else np.nan for k in key], index=rows.index)
    rows["listed"] = vol.notna()
    rows["stale_day0"] = rows["listed"] & (vol == 0)

    # Trading days from this match's day 0 to the club's next match's day 0
    rows = rows.sort_values(["club", "date"]).reset_index(drop=True)
    pos = [cal[ex].searchsorted(d) if pd.notna(d) else np.nan for ex, d in zip(rows["exchange"], rows["event_date"])]
    rows["_pos"] = pos
    rows["days_to_next_match_trading"] = (rows.groupby("club")["_pos"].shift(-1) - rows["_pos"]).astype("Int64")
    rows = rows.drop(columns="_pos")

    run_checks(rows, prices, cal, cfg)
    out = prices.merge(_stale_flags(prices, cal, cfg), on=["ticker", "date"], how="left")
    out["role"] = np.where(out["ticker"].isin(set(cfg.clubs["ticker"].dropna())), "club", "benchmark")
    out.to_csv(out_dir / "prices.csv", index=False)
    rows = rows.sort_values(["date", "club"]).reset_index(drop=True)
    rows.to_csv(out_dir / "match_events.csv", index=False)
    return rows


def _stale_flags(prices: pd.DataFrame, cal: dict, cfg) -> pd.DataFrame:
    """stale = no trade that day (zero volume) for club stocks; indices are never stale."""
    clubs = set(cfg.clubs["ticker"].dropna())
    f = prices[["ticker", "date", "volume"]].copy()
    f["stale"] = f["ticker"].isin(clubs) & (f["volume"] == 0)
    return f[["ticker", "date", "stale"]]


def run_checks(rows: pd.DataFrame, prices: pd.DataFrame, cal: dict, cfg) -> None:
    ok = rows["event_date"].notna()
    assert ok.all(), f"{(~ok).sum()} matches with no event date (after the end of the price data?)"
    lag = (rows["event_date"] - rows["date"]).dt.days
    assert (lag >= 0).all(), "event date before the match"
    late = rows[lag > 5]
    if not late.empty:
        print(f"WARNING {len(late)} matches with day 0 more than 5 days after the match:")
        print(late[["date", "club", "exchange", "event_date"]].head(10).to_string())

    print("\nPrice coverage per club (share of exchange trading days with a price, and with zero volume):")
    for _, c in cfg.clubs.dropna(subset=["ticker"]).iterrows():
        p = prices[prices["ticker"] == c["ticker"]]
        days = cal[c["exchange"]]
        days = days[(days >= p["date"].min()) & (days <= p["date"].max())]
        on_days = p["date"].isin(days).sum()
        print(f"  {c['club']:18s} {c['ticker']:9s} {on_days / len(days):6.1%} of {len(days)} days, "
              f"zero volume {(p['volume'] == 0).mean():5.1%}")

    adj = prices.sort_values(["ticker", "date"])
    adj["ret"] = adj.groupby("ticker")["adj_close"].pct_change()
    big = adj[(adj["ret"].abs() > 0.5) & ~adj["exclude_return"]]
    if not big.empty:
        print(f"\nDaily adjusted returns beyond ±50% left in (genuine: thin trading, news; see docs/issues.md):")
        print(big[["ticker", "date", "adj_close", "ret"]].to_string())
    hit = rows.merge(prices.loc[prices["exclude_return"], ["ticker", "date"]],
                     left_on=["ticker", "event_date"], right_on=["ticker", "date"], suffixes=("", "_ca"))
    if not hit.empty:
        print(f"WARNING {len(hit)} matches have day 0 on a corporate action date (return excluded):")
        print(hit[["date", "club", "event_date"]].to_string())

    print("\nEvent day 0 relative to the match date (calendar days):")
    print(lag.value_counts().sort_index().to_string())
    print(f"\nMatches whose club stock has prices on day 0: {rows['listed'].sum()} of {len(rows)}; "
          f"stale on day 0: {rows['stale_day0'].sum()}; near the close: {rows['near_close'].sum()}")
    print("\nSpot check:")
    print(rows.sample(min(5, len(rows)), random_state=1)[
        ["date", "club", "kickoff_time", "kickoff_source", "exchange", "match_end_local", "event_date",
         "near_close"]].to_string())
