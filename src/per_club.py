"""Per-club breakdown (EXPLORATORY, after submission; not part of the submitted report).

Reruns the Step 4 methods club by club. Imports src/step4_event_study.py unchanged and never
overwrites the pipeline's files: every output goes to data/processed/per_club/.

    python -m src.per_club

Outputs (data/processed/per_club/):
    per_club_table.csv        section 1: one row per club (counts, regression, match week, costs, backtest)
    per_club_backtest.csv     section 1: backtest per club, version and period (long form)
    liquid_flat_costs.csv     section 2: Man Utd, Juventus, Dortmund at flat round trip costs
    multiple_testing.csv      section 3: drift p-values per club with Holm adjustment
    *.png                     section 4: charts, 1600 px wide
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .common import PROCESSED
from .step4_event_study import (COMMISSION, DRIFT, ILLIQUID, OOS_START, PERIOD_SPLIT, POST, PRE, WEEK_LAGS,
                                   Fit, build_trades, calendar_portfolio, club_panel, expanding_terciles, holm,
                                   load_inputs, locate_events, match_week_fit, monthly_spreads, performance)

OUT = PROCESSED / "per_club"
LIQUID = ["Manchester United", "Juventus", "Borussia Dortmund"]
FLAT = [0.001, 0.002, 0.003]                 # section 2: round trip, all in
WEEK_CLUBS = ["Benfica", "Porto", "Fenerbahce", "Manchester United"]
POWER = 1.96 + 0.84                          # minimum detectable effect at 80% power, 5% two-sided


def periods(start):
    """Same split as run_backtest(): trades by season, days by date."""
    return {"full": (lambda t: t["season"] >= "0000", lambda d: d.index >= start),
            "in_sample": (lambda t: t["season"] < PERIOD_SPLIT, lambda d: d.index < OOS_START),
            "out_of_sample": (lambda t: t["season"] >= PERIOD_SPLIT, lambda d: d.index >= OOS_START)}


def flat_costs(trades: pd.DataFrame, rt: float) -> pd.DataFrame:
    """Copy of the trades with an all-in round trip cost rt, half on each leg."""
    t = trades.copy()
    t["cost_in"] = t["cost_out"] = rt / 2
    t["cost"] = rt
    t["net"] = t["gross"] - rt
    return t


def club_regressions(panel, events) -> pd.DataFrame:
    """The task 3 distributed lag regression and the match-week regression, run on each club's own
    panel (standard errors clustered by date; with one club that is one row per date)."""
    rows = []
    for club, p in panel.groupby("club"):
        p = p.reset_index(drop=True)
        ev = locate_events(p, events)
        f = Fit(p, ev, ["S"], ev["surprise"].to_numpy()[:, None])
        b0, b0_se, b0_p = f.coef("S", [0])
        d, d_se, d_p = f.coef("S", DRIFT)
        w = match_week_fit(p, ev)
        pre, pre_se, pre_p = w.coef("any", PRE)
        post, post_se, post_p = w.coef("any", POST)
        cum = [w.coef("any", [j for j in WEEK_LAGS if j <= k])[:2] for k in WEEK_LAGS]
        rows.append({"club": club, "matches": len(ev), "days": f.n,
                     "first_day": p["date"].min().date(), "last_day": p["date"].max().date(),
                     "b0": b0, "b0_se": b0_se, "b0_p": b0_p, "D": d, "D_se": d_se, "D_p": d_p,
                     "pre": pre, "pre_se": pre_se, "pre_p": pre_p, "post": post, "post_se": post_se,
                     "post_p": post_p, "zero_volume_share": float(p["stale"].mean()),
                     "week_cum": [c[0] for c in cum], "week_cum_se": [c[1] for c in cum]})
    return pd.DataFrame(rows)


def club_backtests(trades, start, end, stoxx) -> pd.DataFrame:
    rows = []
    for club, tc in trades.groupby("club"):
        for version, t in (("long_short", tc), ("long_only", tc[tc["side"] == 1])):
            t = t.reset_index(drop=True)
            if t.empty:
                continue
            g = calendar_portfolio(t, "gross", start, end)
            n = calendar_portfolio(t, "net", start, end)
            for period, (pick_t, pick_d) in periods(start).items():
                tp = t[pick_t(t)]
                if tp.empty:
                    continue
                pg, pn = performance(tp, g[pick_d(g)], stoxx, "gross"), performance(tp, n[pick_d(n)], stoxx, "net")
                rows.append({"club": club, "version": version, "period": period, "trades": len(tp),
                             "gross_mean": tp["gross"].mean(), "net_mean": tp["net"].mean(),
                             "hit_rate_gross": (tp["gross"] > 0).mean(), "hit_rate_net": (tp["net"] > 0).mean(),
                             "cum_gross": pg["cumulative_return"], "cum_net": pn["cumulative_return"],
                             "t_gross": pg["t_newey_west"], "breakeven_cost": tp["gross"].mean(),
                             "mean_cost": tp["cost"].mean()})
    return pd.DataFrame(rows)


def cost_split(trades) -> pd.DataFrame:
    """Mean round trip cost paid on the club's trades, split into spread, commission and tax."""
    t = trades.assign(spread=trades["cost"] - trades["commission"],
                      tax=trades["commission"] - 2 * COMMISSION)
    return (t.groupby("club").agg(cost=("cost", "mean"), cost_spread=("spread", "mean"), cost_tax=("tax", "mean"))
            .assign(cost_commission=2 * COMMISSION))


def liquid_flat(trades, start, end, stoxx) -> pd.DataFrame:
    rows = []
    for club in LIQUID:
        tc = trades[trades["club"] == club]
        for version, t0 in (("long_short", tc), ("long_only", tc[tc["side"] == 1])):
            for rt in FLAT:
                t = flat_costs(t0, rt).reset_index(drop=True)
                n = calendar_portfolio(t, "net", start, end)
                for period, (pick_t, pick_d) in periods(start).items():
                    tp = t[pick_t(t)]
                    perf = performance(tp, n[pick_d(n)], stoxx, "net")
                    rows.append({"club": club, "version": version, "round_trip_cost": rt, "period": period,
                                 "trades": len(tp), "gross_mean": tp["gross"].mean(), "net_mean": tp["net"].mean(),
                                 "hit_rate_net": (tp["net"] > 0).mean(), "cum_net": perf["cumulative_return"],
                                 "sharpe_net": perf["sharpe"], "t_net": perf["t_newey_west"]})
    return pd.DataFrame(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg, prices, cal, events = load_inputs()
    panel = club_panel(prices, cal, cfg)
    events = events.copy()
    events["signal"] = expanding_terciles(events)
    ev = locate_events(panel, events)
    trades = build_trades(panel, ev, monthly_spreads(cfg))
    start, end = trades["entry_date"].min(), panel["date"].max()
    stoxx = prices[prices["ticker"] == cfg.robustness_benchmark].set_index("date")["adj_close"].pct_change()

    # 1. Per-club table
    reg = club_regressions(panel, events)
    bt = club_backtests(trades, start, end, stoxx)
    bt.to_csv(OUT / "per_club_backtest.csv", index=False)
    costs = cost_split(trades)
    wide = bt[bt["version"] == "long_short"].pivot(index="club", columns="period")
    tab = reg.drop(columns=["week_cum", "week_cum_se"]).set_index("club").join(costs)
    tab["trades_long_short"] = trades.groupby("club").size()
    tab["trades_long_only"] = trades[trades["side"] == 1].groupby("club").size()
    for col in ("gross_mean", "net_mean", "hit_rate_gross", "hit_rate_net", "cum_net"):
        for period in ("in_sample", "out_of_sample"):
            tab[f"{col}_{period}"] = wide[(col, period)]
    tab["breakeven_cost"] = trades.groupby("club")["gross"].mean()
    tab["breakeven_cost_long_only"] = trades[trades["side"] == 1].groupby("club")["gross"].mean()
    tab["share_of_trades"] = tab["trades_long_short"] / len(trades)
    tab["share_of_gross_profit"] = trades.groupby("club")["gross"].sum() / trades["gross"].sum()
    tab["illiquid"] = tab.index.isin(ILLIQUID)
    # Reliability: the drift a club's own regression could detect, against the pooled drift (+0.23%)
    tab["min_detectable_D"] = POWER * tab["D_se"]
    tab["note"] = np.select(
        [tab.index.isin(ILLIQUID), tab["last_day"].astype(str) < "2023-01-01"],
        ["thin trading: stale prices on many days, day 0 reaction spread over later days",
         "delisted 12/09/2022: out of sample covers three seasons only"], "")

    # 3. Multiple testing across clubs (drift, and day 0 for contrast)
    tab["D_p_holm"] = holm(tab["D_p"].tolist())
    tab["b0_p_holm"] = holm(tab["b0_p"].tolist())
    tab["pre_p_holm"] = holm(tab["pre_p"].tolist())
    tab = tab.sort_values("b0", ascending=False)
    tab.to_csv(OUT / "per_club_table.csv")
    mt = tab[["D", "D_se", "D_p", "D_p_holm", "b0_p", "b0_p_holm", "pre_p", "pre_p_holm"]].sort_values("D_p")
    mt.to_csv(OUT / "multiple_testing.csv")

    # 2. Liquid clubs at flat costs
    lf = liquid_flat(trades, start, end, stoxx)
    lf.to_csv(OUT / "liquid_flat_costs.csv", index=False)

    _print(tab, lf, len(trades))
    from .per_club_charts import charts
    charts(tab, reg.set_index("club"), OUT)


def _print(tab, lf, n_trades):
    pct = lambda x: f"{100 * x:+.2f}%"
    pd.set_option("display.width", 250)
    show = tab[["matches", "trades_long_short", "trades_long_only", "b0", "b0_se", "D", "D_se", "D_p", "pre", "post",
                "cost", "cost_spread", "cost_tax", "zero_volume_share", "breakeven_cost",
                "net_mean_in_sample", "net_mean_out_of_sample", "share_of_trades", "share_of_gross_profit"]]
    print("Per club (EXPLORATORY; returns in %):")
    print(show.assign(**{c: 100 * show[c] for c in show if c not in ("matches", "trades_long_short",
                                                                     "trades_long_only", "D_p")})
          .round(3).to_string())
    print(f"\nTotal trades {n_trades}")
    sig = tab["D_p"] < 0.05
    print(f"\nDrift significant at 5%: {int(sig.sum())} of {len(tab)} clubs ({', '.join(tab.index[sig])}); "
          f"expected by chance {0.05 * len(tab):.1f}. Surviving Holm: "
          f"{', '.join(tab.index[tab['D_p_holm'] < 0.05]) or 'none'}")
    print("\nLiquid clubs at flat round trip costs, out of sample:")
    o = lf[lf["period"] == "out_of_sample"]
    print(o.to_string(index=False, float_format=lambda x: f"{x:.4f}"))


if __name__ == "__main__":
    main()
