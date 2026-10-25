"""Cost audit of the backtest: verification and reporting only.

Changes nothing in the pipeline: imports the Step 4 functions, rebuilds the same trades, checks they
match the committed backtest files, and writes its own tables to data/processed/cost_audit/. Never overwrites
the pipeline's files in data/processed/.

    python -m src.cost_audit

Sections (printed and saved):
1. cost_breakdown.csv     mean round trip cost by component, by side, tax trades
2. turnover.csv           trades per year, holding period, days in cash, turnover, cost drag v the
                          gross to net gap (long-short and long only, in and out of sample)
3. spreads_by_club.csv    mean estimated round trip spread per club; roma_quoted_v_estimates.csv
4. sensitivity.csv        the same backtest at flat round trip costs, without commission, and for
                          the liquid clubs only; breakeven.csv
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .common import ROOT, PROCESSED
from .step3_prices import RAW_BLOOMBERG
from .step4_event_study import (COMMISSION, ILLIQUID, OOS_START, PERIOD_SPLIT, build_trades, calendar_portfolio,
                                club_panel, expanding_terciles, load_inputs, locate_events, monthly_spreads,
                                performance)

OUT = PROCESSED / "cost_audit"
FLAT = [0.0, 0.001, 0.002, 0.005]          # round trip, all in (spread, commission, tax)
VERSIONS = {"long_short": lambda t: t, "long_only": lambda t: t[t["side"] == 1]}
UNIVERSES = {"all_clubs": lambda t: t, "liquid_clubs": lambda t: t[~t["club"].isin(ILLIQUID)]}


def periods(start):
    """The same split as run_backtest(): trades by season, days by date."""
    return {"full": (lambda t: t["season"] >= "0000", lambda d: d.index >= start),
            "in_sample": (lambda t: t["season"] < PERIOD_SPLIT, lambda d: d.index < OOS_START),
            "out_of_sample": (lambda t: t["season"] >= PERIOD_SPLIT, lambda d: d.index >= OOS_START)}


def with_costs(trades: pd.DataFrame, scenario: str) -> pd.DataFrame:
    """Copy of the trades with cost_in / cost_out / cost / net for a cost scenario."""
    t = trades.copy()
    if scenario == "actual":
        return t
    if scenario == "no_commission":   # spreads and taxes kept
        t["cost_in"] = t["cost_in"] - COMMISSION
        t["cost_out"] = t["cost_out"] - COMMISSION
    else:
        c = float(scenario)
        t["cost_in"] = t["cost_out"] = c / 2
    t["cost"] = t["cost_in"] + t["cost_out"]
    t["net"] = t["gross"] - t["cost"]
    return t


def position_days(trades: pd.DataFrame) -> pd.DataFrame:
    """One row per trade per day held, with the trade's weight that day in calendar_portfolio()
    (1 / number of open positions)."""
    rows = pd.DataFrame({"trade": np.repeat(np.arange(len(trades)), trades["days"].to_numpy()),
                         "date": pd.DatetimeIndex(np.concatenate(trades["path_days"].to_numpy()))})
    rows["first"] = ~rows["trade"].duplicated()
    rows["last"] = ~rows["trade"].duplicated(keep="last")
    rows["w"] = 1 / rows.groupby("date")["trade"].transform("size")
    return rows


# ---------------------------------------------------------------- 1. cost breakdown

def cost_breakdown(t: pd.DataFrame) -> pd.DataFrame:
    spread = t["cost"] - t["commission"]
    tax = t["commission"] - 2 * COMMISSION
    rows = []
    for label, m in {"all trades": slice(None), "long": t["side"] == 1, "short": t["side"] == -1,
                     "Juventus": t["club"] == "Juventus",
                     "Celtic before 28/04/2014": (t["club"] == "Celtic") & (t["entry_date"] < "2014-04-28")}.items():
        rows.append({"trades": label, "n": int(t.loc[m].shape[0]), "round_trip_cost": t.loc[m, "cost"].mean(),
                     "spread": spread[m].mean(), "commission": 2 * COMMISSION, "tax": tax[m].mean()})
    return pd.DataFrame(rows)


def check_tax_legs(t: pd.DataFrame) -> list[str]:
    """Tax is paid on the buying leg only: entry of a long, exit (cover) of a short."""
    out = []
    juve = t[t["club"] == "Juventus"]
    tax_in, tax_out = juve["commission_in"] - COMMISSION, juve["commission_out"] - COMMISSION
    ok = np.allclose(tax_in, np.where(juve["side"] == 1, 0.001, 0)) and np.allclose(tax_out, np.where(juve["side"] == -1, 0.001, 0))
    out.append(f"Juventus: 0.10% FTT on the buy leg only, once per round trip: {ok}")
    cel = t[t["club"] == "Celtic"]
    exp_in = np.where((cel["side"] == 1) & (cel["entry_date"] < "2014-04-28"), 0.005, 0)
    exp_out = np.where((cel["side"] == -1) & (cel["exit_date"] < "2014-04-28"), 0.005, 0)
    ok = np.allclose(cel["commission_in"] - COMMISSION, exp_in) and np.allclose(cel["commission_out"] - COMMISSION, exp_out)
    out.append(f"Celtic: 0.50% stamp duty on the buy leg before 28/04/2014 only: {ok} "
               f"({int((exp_in > 0).sum() + (exp_out > 0).sum())} taxed legs)")
    others = t[~t["club"].isin(["Juventus", "Celtic"])]
    out.append(f"No tax on other clubs: {np.allclose(others['commission'], 2 * COMMISSION)}")
    return out


def check_scaling(trades: pd.DataFrame, start, end) -> list[str]:
    """Costs enter the portfolio once per leg at the position's weight on that day."""
    pos = position_days(trades)
    leg = (pos["first"] * trades["cost_in"].to_numpy()[pos["trade"]]
           + pos["last"] * trades["cost_out"].to_numpy()[pos["trade"]])
    drag = (leg * pos["w"]).groupby(pos["date"]).sum()
    g = calendar_portfolio(trades, "gross", start, end)
    n = calendar_portfolio(trades, "net", start, end)
    diff = (g - n).reindex(drag.index)
    return [f"Daily gross - net equals the sum of (weight x leg cost) over legs traded that day: "
            f"{np.allclose(diff, drag)} (max abs diff {np.abs(diff - drag).max():.1e})",
            f"Each trade charged one entry and one exit (one-day trades: both legs on the same day): "
            f"{(pos['first'].sum(), pos['last'].sum()) == (len(trades), len(trades))}",
            f"No two trades of the same club overlap: "
            f"{not (trades.sort_values('entry_date').groupby('club').apply(lambda g: (g['entry_date'].shift(-1) < g['exit_date']).any(), include_groups=False).any())}",
            f"No duplicate trades (club, match): {not trades.duplicated(['club', 'match_date']).any()}"]


# ---------------------------------------------------------------- 2. turnover and the gross to net gap

def turnover(trades: pd.DataFrame, start, end) -> pd.DataFrame:
    rows = []
    for vname, pick in VERSIONS.items():
        t = pick(trades).reset_index(drop=True)
        g = calendar_portfolio(t, "gross", start, end)
        n = calendar_portfolio(t, "net", start, end)
        pos = position_days(t)
        pos["leg_w"] = pos["w"] * (pos["first"].astype(int) + pos["last"].astype(int))
        pos["leg_cost"] = pos["w"] * (pos["first"] * t["cost_in"].to_numpy()[pos["trade"]]
                                      + pos["last"] * t["cost_out"].to_numpy()[pos["trade"]])
        # weights the equal weighted portfolio actually holds, so the trading it implies (resizing
        # the open positions when one opens or closes; drift between days ignored)
        w = pos.pivot_table(index="date", columns="trade", values="w", fill_value=0).reindex(g.index, fill_value=0)
        implied = w.diff().abs().sum(axis=1)
        implied.iloc[0] = w.iloc[0].sum()
        for period, (pick_t, pick_d) in periods(start).items():
            tp, days = t[pick_t(t)], g.index[pick_d(g)]
            years = len(days) / 261                       # business days, as in calendar_portfolio
            p = pos[pos["date"].isin(days)]
            rt = p["leg_w"].sum() / 2 / years              # round trips of the whole portfolio per year
            drag = p["leg_cost"].sum() / years
            G, N = np.prod(1 + g[days]) - 1, np.prod(1 + n[days]) - 1
            rows.append({
                "version": vname, "period": period, "years": years,
                "trades_per_year": len(tp) / years,
                "holding_days": tp["days"].mean(),
                "share_days_in_cash": float((w.loc[days].sum(axis=1) == 0).mean()),
                "mean_open_positions": float((1 / p.groupby("date")["w"].first()).mean()),
                "turnover_round_trips_per_year": rt,
                "turnover_implied_by_equal_weights": implied[days].sum() / 2 / years,
                "mean_round_trip_cost": tp["cost"].mean(),
                "turnover_x_mean_cost": rt * tp["cost"].mean(),
                "cost_drag_per_year": drag,
                "gross_annual_mean": g[days].mean() * 261, "net_annual_mean": n[days].mean() * 261,
                "gross_minus_net_annual_mean": (g[days] - n[days]).mean() * 261,
                "gross_cumulative": G, "net_cumulative": N,
                "log_gap_per_year": (np.log1p(G) - np.log1p(N)) / years,
                "net_cumulative_predicted": (1 + G) * np.exp(-drag * years) - 1})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 3. spreads

def spreads_by_club(spreads: pd.DataFrame, trades: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    paid = (trades["cost"] - trades["commission"]).groupby(trades["club"]).mean()
    rows = []
    for club, s in spreads.groupby("club"):
        days = panel.loc[panel["club"] == club, "date"]
        m = s[(s["month"] >= days.min().to_period("M")) & (s["month"] <= days.max().to_period("M"))]
        filled = m["spread"].eq(m["spread"].median())
        rows.append({"club": club, "estimator": s["estimator"].iloc[0], "spread_mean": m["spread"].mean(),
                     "spread_median": m["spread"].median(), "spread_p10": m["spread"].quantile(0.1),
                     "spread_p90": m["spread"].quantile(0.9), "spread_cs_mean": m["spread_cs"].mean(),
                     "spread_ar_mean": m["spread_ar"].mean(), "spread_paid_on_trades": paid.get(club, np.nan),
                     "months_at_median_(filled)": float(filled.mean()), "months": len(m),
                     "stale_day_share": panel.loc[panel["club"] == club, "stale"].mean()})
    return pd.DataFrame(rows).sort_values("spread_mean")


def roll_monthly(price: pd.Series) -> pd.Series:
    """Roll (1984) spread 2 sqrt(-cov(r_t, r_t-1)) per month from daily closes (NaN if cov > 0)."""
    r = np.log(price).diff()
    df = pd.DataFrame({"r": r, "r1": r.shift(1)}).dropna()
    cov = df.groupby(df.index.to_period("M")).apply(lambda g: np.cov(g["r"], g["r1"])[0, 1] if len(g) > 5 else np.nan)
    return 2 * np.sqrt((-cov).where(cov < 0))


def roma_check(spreads: pd.DataFrame, prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Roma has bid and ask from 24/06/2019 but no high and low, so the backtest's Roma spread *is*
    the quoted spread (and its median before). Cross-checks: a Roll estimate from Roma's closes
    against the quote, month by month, and Lazio's Corwin-Schultz estimate (same exchange) in the
    same months."""
    sheet = pd.read_excel(sorted(RAW_BLOOMBERG.glob("*.xlsx"))[0], "ASR_EU", header=1)
    sheet.columns = [str(c).upper() for c in sheet.columns]
    sheet = sheet.set_index(pd.to_datetime(sheet["DATE"]))
    q = sheet.dropna(subset=["PX_BID", "PX_ASK"])
    q = q[(q["PX_BID"] > 0) & (q["PX_ASK"] >= q["PX_BID"])]
    quoted = ((q["PX_ASK"] - q["PX_BID"]) / ((q["PX_ASK"] + q["PX_BID"]) / 2))
    quoted_m = quoted.groupby(quoted.index.to_period("M")).mean()
    traded = sheet[sheet["PX_VOLUME"] > 0]["PX_LAST"]
    roll = roll_monthly(traded)
    sp = spreads.set_index(["club", "month"])
    used = sp.loc["Roma", "spread"]
    lazio_cs = sp.loc["Lazio", "spread"]
    lazio_close = prices[prices["ticker"] == "SSL.MI"].set_index("date")
    lazio_roll = roll_monthly(lazio_close.loc[lazio_close["volume"] > 0, "close"])
    m = pd.DataFrame({"roma_quoted": quoted_m, "roma_used_in_backtest": used, "roma_roll": roll,
                      "lazio_corwin_schultz": lazio_cs, "lazio_roll": lazio_roll}).loc[quoted_m.index]
    summary = pd.DataFrame({
        "mean": m.mean(), "median": m.median(),
        "months_with_value": m.notna().sum(),
        "corr_with_roma_quoted": m.corrwith(m["roma_quoted"])})
    return m, summary


# ---------------------------------------------------------------- 4. sensitivity

def sensitivity(trades: pd.DataFrame, stoxx, start, end) -> pd.DataFrame:
    rows = []
    for uname, upick in UNIVERSES.items():
        for vname, vpick in VERSIONS.items():
            base = vpick(upick(trades)).reset_index(drop=True)
            for scen in ["gross"] + [str(c) for c in FLAT[1:]] + ["no_commission", "actual"]:
                t = with_costs(base, "0" if scen == "gross" else scen)
                d = calendar_portfolio(t, "net", start, end)
                for period, (pick_t, pick_d) in periods(start).items():
                    p = performance(t[pick_t(t)], d[pick_d(d)], stoxx, "net")
                    rows.append({"universe": uname, "version": vname,
                                 "scenario": {"gross": "0% (gross)", "0.001": "0.10%", "0.002": "0.20%",
                                              "0.005": "0.50%", "no_commission": "no commission (spread + tax)",
                                              "actual": "actual (~1.1%)"}[scen],
                                 "period": period, "mean_round_trip_cost": t[pick_t(t)]["cost"].mean(),
                                 **{k: p[k] for k in ["trades", "mean_per_trade", "cumulative_return",
                                                      "annual_return", "sharpe", "max_drawdown"]}})
    return pd.DataFrame(rows)


def breakeven(trades: pd.DataFrame, start, end) -> pd.DataFrame:
    """Flat round trip cost at which (a) the mean net return per trade is 0 (= mean gross per
    trade, the definition in backtest_summary.csv), (b) the portfolio's mean daily return and so
    its Sharpe ratio is 0, (c) its cumulative return is 0 (stricter: volatility drag)."""
    rows = []
    for uname, upick in UNIVERSES.items():
        for vname, vpick in VERSIONS.items():
            base = vpick(upick(trades)).reset_index(drop=True)
            series = {}
            def cum(c, pick_d):
                key = round(c, 7)
                if key not in series:
                    series[key] = calendar_portfolio(with_costs(base, str(c)), "net", start, end)
                d = series[key]
                return np.prod(1 + d[pick_d(d)]) - 1
            for period, (pick_t, pick_d) in periods(start).items():
                d0 = calendar_portfolio(with_costs(base, "0"), "net", start, end)
                d1 = calendar_portfolio(with_costs(base, "0.01"), "net", start, end)
                m0, m1 = d0[pick_d(d0)].mean(), d1[pick_d(d1)].mean()
                be_sharpe = 0.01 * m0 / (m0 - m1)          # mean daily return is linear in the cost
                if cum(0.0, pick_d) <= 0:
                    be_cum = np.nan
                else:
                    lo, hi = 0.0, max(be_sharpe, 0.0005)
                    for _ in range(30):
                        mid = (lo + hi) / 2
                        lo, hi = (mid, hi) if cum(mid, pick_d) > 0 else (lo, mid)
                    be_cum = (lo + hi) / 2
                    series.clear()
                tp = base[pick_t(base)]
                rows.append({"universe": uname, "version": vname, "period": period,
                             "actual_mean_round_trip_cost": tp["cost"].mean(),
                             "breakeven_per_trade": tp["gross"].mean(), "breakeven_sharpe_zero": be_sharpe,
                             "breakeven_cumulative_zero": be_cum})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- run

def run(out_dir=OUT):
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg, prices, cal, events = load_inputs()
    panel = club_panel(prices, cal, cfg)
    events = events.copy()
    events["signal"] = expanding_terciles(events)
    ev = locate_events(panel, events)
    spreads = monthly_spreads(cfg)
    trades = build_trades(panel, ev, spreads)
    start, end = trades["entry_date"].min(), panel["date"].max()
    stoxx = prices[prices["ticker"] == cfg.robustness_benchmark].set_index("date")["adj_close"].pct_change()
    pd.set_option("display.width", 250)
    fmt = lambda x: f"{x:.4f}"

    print("0. Same trades as the committed backtest")
    old = pd.read_csv(PROCESSED / "backtest_trades.csv")
    print(f"   trades {len(trades)} v {len(old)}; gross, cost, net identical: "
          f"{all(np.allclose(old[c], trades[c]) for c in ['gross', 'cost', 'net'])}")

    print("\n1. Costs")
    for line in check_tax_legs(trades) + check_scaling(trades, start, end):
        print("   " + line)
    cb = cost_breakdown(trades)
    cb.to_csv(out_dir / "cost_breakdown.csv", index=False)
    print((cb.set_index(["trades", "n"]) * 100).round(3).to_string())

    print("\n2. Turnover and the gross to net gap")
    to = turnover(trades, start, end)
    to.to_csv(out_dir / "turnover.csv", index=False)
    print(to.set_index(["version", "period"]).T.to_string(float_format=fmt))

    print("\n3. Spreads (round trip, %)")
    sc = spreads_by_club(spreads, trades, panel)
    sc.to_csv(out_dir / "spreads_by_club.csv", index=False)
    pct = [c for c in sc if c.startswith("spread")]
    print(sc.assign(**{c: sc[c] * 100 for c in pct}).to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    rm, rs = roma_check(spreads, prices)
    rm.to_csv(out_dir / "roma_quoted_v_estimates.csv")
    print(rs.to_string(float_format=fmt))

    print("\n4. Sensitivity")
    se = sensitivity(trades, stoxx, start, end)
    se.to_csv(out_dir / "sensitivity.csv", index=False)
    committed = pd.read_csv(PROCESSED / "backtest_summary.csv")
    a = se[(se["universe"] == "all_clubs") & (se["scenario"] == "actual (~1.1%)")].set_index(["version", "period"])
    c = committed[committed["costs"] == "net"].set_index(["version", "period"])
    print(f"   actual scenario reproduces backtest_summary.csv (net): "
          f"{np.allclose(a.loc[c.index, ['cumulative_return', 'sharpe', 'max_drawdown']], c[['cumulative_return', 'sharpe', 'max_drawdown']])}")
    key = se[se["period"] != "full"].pivot_table(index=["universe", "version", "scenario"], columns="period",
                                                 values=["cumulative_return", "sharpe", "max_drawdown"], sort=False)
    print(key.to_string(float_format=lambda x: f"{x:.3f}"))
    be = breakeven(trades, start, end)
    be.to_csv(out_dir / "breakeven.csv", index=False)
    print((be.set_index(["universe", "version", "period"]) * 100).to_string(float_format=lambda x: f"{x:.3f}"))
    return {"cost_breakdown": cb, "turnover": to, "spreads": sc, "roma": rs, "sensitivity": se, "breakeven": be}


if __name__ == "__main__":
    run()
