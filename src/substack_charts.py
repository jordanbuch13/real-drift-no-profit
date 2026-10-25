"""Dark theme charts for the Substack write up, from the Step 4 outputs in data/processed/.

    python -m src.substack_charts

Outputs (figures/, 1600 x 1000 px):
    substack_backtest.png     value of 1,000 GBP in the long/short backtest, before and after costs
    substack_matchweek.png    abnormal return around every match (match-week pattern)
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FixedLocator, NullLocator

from .common import PROCESSED
from .step4_event_study import FIGURES

DPI, SIZE = 200, (8.0, 5.0)
SURFACE, INK, MUTED, AXIS, GRID = "#0f1724", "#f5f5f7", "#9aa3b2", "#9aa3b2", "#243042"
GOOD, BAD = "#34c38f", "#ff5a4f"
START = 1000.0


def _style():
    plt.rcParams.update({"figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
                         "axes.edgecolor": AXIS, "axes.labelcolor": MUTED, "xtick.color": MUTED,
                         "ytick.color": MUTED, "text.color": INK, "font.size": 10.5,
                         "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                         "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True})


def _figure(title, subtitle, title_size=20):
    fig = plt.figure(figsize=SIZE)
    fig.text(0.05, 0.935, title, fontsize=title_size, fontweight="bold", va="top")
    fig.text(0.05, 0.84, subtitle, fontsize=11.5, color=MUTED, va="top", linespacing=1.4)
    return fig, fig.add_axes([0.09, 0.125, 0.87, 0.605])


def _pounds(v):
    return f"{v * 100:.0f}p" if v < 1 else f"£{v:,.0f}"


def backtest(fig_dir=FIGURES):
    daily = pd.read_csv(PROCESSED / "backtest_daily.csv", parse_dates=["date"], index_col="date")
    value = START * (1 + daily[["long_short_gross", "long_short_net"]]).cumprod()
    fig, ax = _figure("Real drift, no profit",
                      "Value of £1,000 in the long/short strategy, 2013/14 to 2025/26 (log scale).\n"
                      "5,461 trades: long after the biggest positive surprises, short after the biggest negative ones.")
    ax.set_yscale("log")
    ticks = [0.01, 0.1, 1, 10, 100, 1000, 10000]
    ax.yaxis.set_major_locator(FixedLocator(ticks))
    ax.yaxis.set_minor_locator(NullLocator())
    ax.set_yticks(ticks, [_pounds(t) for t in ticks])
    ax.set_ylim(0.004, 30000)
    ax.axhline(START, color=AXIS, linewidth=1)
    ax.plot(value.index, value["long_short_gross"], color=GOOD, linewidth=2.2)
    ax.plot(value.index, value["long_short_net"], color=BAD, linewidth=2.2, linestyle=(0, (4, 1.5)))
    end = value.index[-1]
    for col, label, color in [("long_short_gross", "Before costs", GOOD), ("long_short_net", "After costs", BAD)]:
        v = value[col].iloc[-1]
        ax.scatter([end], [v], s=36, color=color, zorder=3, edgecolors=SURFACE, linewidths=1.5)
        ax.annotate(f"{label}: {_pounds(v)}", (end, v), xytext=(-8, 12 if col.endswith("gross") else -18),
                    textcoords="offset points", ha="right", fontsize=11.5, color=INK)
    ax.set_xlim(value.index[0], end + pd.Timedelta(days=60))
    fig_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_dir / "substack_backtest.png", dpi=DPI)
    plt.close(fig)
    return value.iloc[-1]


def matchweek(fig_dir=FIGURES):
    week = pd.read_csv(PROCESSED / "match_week_coefficients.csv").set_index("k")
    cum, band = week["cumulative"] * 100, 1.96 * week["cumulative_se"] * 100
    fig, ax = _figure("Club shares rise before matches and fall after",
                      "Abnormal return around every match, whatever the result, %.\n"
                      "Exploratory finding. Shaded: 95% confidence band.", title_size=18)
    for part, color in [(cum.loc[:-1], GOOD), (cum.loc[-1:], BAD)]:
        k = part.index
        ax.fill_between(k, (part - band.loc[k]).to_numpy(), (part + band.loc[k]).to_numpy(), color=color,
                        alpha=0.2, linewidth=0)
        ax.plot(k, part, color=color, linewidth=2.6, marker="o", markersize=5.5)
    ax.plot([-1], [cum.loc[-1]], color=GOOD, marker="o", markersize=5.5)
    ax.set_ylim(-0.65, 1.12)
    ax.axhline(0, color=AXIS, linewidth=1)
    ax.axvline(0, color=AXIS, linewidth=0.8, linestyle=":")
    ax.annotate(f"Day before the match: {cum.loc[-1]:+.2f}%", (-1, cum.loc[-1]), xytext=(-4.95, cum.loc[-1] + 0.16),
                fontsize=11.5, color=INK, arrowprops={"arrowstyle": "-", "color": MUTED, "linewidth": 0.8,
                                                      "shrinkA": 0, "shrinkB": 4,
                                                      "relpos": (0.75, 0)})
    ax.set_xticks(np.arange(-5, 6), [str(k).replace("-", "−") for k in range(-5, 6)])
    ax.set_xlim(-5.5, 5.5)
    ax.set_xlabel("Trading days relative to the match", fontsize=11.5)
    ax.set_ylabel("%", rotation=0, labelpad=12, fontsize=11.5)
    fig_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_dir / "substack_matchweek.png", dpi=DPI)
    plt.close(fig)


def charts(fig_dir=FIGURES):
    _style()
    ends = backtest(fig_dir)
    matchweek(fig_dir)
    print(f"Substack charts in {fig_dir}: 1,000 GBP long/short ends at {ends.iloc[0]:,.0f} gross, "
          f"{ends.iloc[1]:.4f} net")


if __name__ == "__main__":
    charts()
