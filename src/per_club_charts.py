"""Charts for src/per_club.py (EXPLORATORY). PNG, 1600 px wide (8 in at 200 dpi)."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .step4_event_study import WEEK_LAGS

DPI, WIDTH = 200, 8.0
SURFACE, INK, INK_2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#e4e3df"
SERIES = "#2a78d6"
# Ordinal ramp (one hue, light to dark = cheap to expensive), validated with validate_palette.js --ordinal
BANDS = [(0.0, 0.010, "under 1.0%", "#86b6ef"), (0.010, 0.013, "1.0% to 1.3%", "#2a78d6"),
         (0.013, 1.0, "over 1.3%", "#104281")]
NOTE = "Exploratory. Daily data 2012/13 to 2025/26; costs estimated from daily high and low prices."


def _style():
    plt.rcParams.update({"figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
                         "axes.edgecolor": MUTED, "axes.labelcolor": INK_2, "xtick.color": INK_2,
                         "ytick.color": INK_2, "text.color": INK, "font.size": 10.5, "axes.titlesize": 13,
                         "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                         "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True})


def _band(cost):
    return next(b for b in BANDS if b[0] <= cost < b[1])


def _title(fig, title, subtitle):
    h = fig.get_figheight()
    fig.text(0.02, 1 - 0.14 / h, title, fontsize=14, fontweight="bold", va="top")
    fig.text(0.02, 1 - 0.47 / h, subtitle, fontsize=10.5, color=INK_2, va="top")
    fig.text(0.02, 0.1 / h, NOTE, fontsize=8.5, color=MUTED)


def reaction_bars(tab, path):
    t = tab.sort_values("b0")
    fig, ax = plt.subplots(figsize=(WIDTH, 6.2))
    y = np.arange(len(t))
    colors = [_band(c)[3] for c in t["cost"]]
    ax.barh(y, 100 * t["b0"], color=colors, height=0.7, edgecolor=SURFACE, linewidth=1)
    ax.errorbar(100 * t["b0"], y, xerr=196 * t["b0_se"], fmt="none", ecolor=MUTED, elinewidth=1, capsize=0)
    for yi, (b0, se, cost) in enumerate(zip(t["b0"], t["b0_se"], t["cost"])):
        ax.text(100 * (b0 + 1.96 * se) + 0.04, yi, f"cost {100 * cost:.2f}%", va="center", fontsize=8.5, color=INK_2)
    ax.set_yticks(y, t.index)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, 2.6)
    ax.set_xlabel("move on the first trading day after the match, % per unit of surprise (lines: 95% range)")
    handles = [plt.Rectangle((0, 0), 1, 1, color=b[3]) for b in BANDS]
    ax.legend(handles, [b[2] for b in BANDS], title="estimated cost of a round trip", loc="lower right",
              frameon=False, fontsize=9, title_fontsize=9)
    _title(fig, "Which clubs' shares react most to a surprising result",
           "Darker bars cost more to trade: the costliest stocks mostly react least (Benfica is the exception)")
    fig.subplots_adjust(left=0.2, right=0.97, top=0.86, bottom=0.12)
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def edge_scatter(tab, path):
    fig, ax = plt.subplots(figsize=(WIDTH, 5.6))
    x, y = 100 * tab["cost"], 100 * tab["breakeven_cost"]
    lim = (0, 1.9)
    ax.fill_between(lim, lim, [lim[1]] * 2, color="#cde2fb", alpha=0.5, lw=0)
    ax.plot(lim, lim, color=INK_2, lw=1.2, ls="--")
    ax.text(0.12, 0.42, "break-even: gain = cost", rotation=45 * 5.6 / 8 * 1.1, color=INK_2, fontsize=9,
            rotation_mode="anchor")
    ax.text(0.08, 1.75, "profitable after costs", color=INK_2, fontsize=9)
    ax.axhline(0, color=MUTED, lw=0.8)
    ax.scatter(x, y, s=70, color=SERIES, edgecolor=SURFACE, linewidth=2, zorder=3)
    # label offsets in points; crowded ones get a leader line
    offsets = {"Roma": (-8, 4, "right"), "Lyon": (-8, -4, "right"), "Fenerbahce": (-8, 4, "right"),
               "Borussia Dortmund": (-30, -40, "right"), "Manchester United": (10, -44, "left"),
               "Ajax": (8, -2, "left"), "Juventus": (8, -6, "left"), "Galatasaray": (-6, 26, "left"),
               "Besiktas": (8, 2, "left"), "Sporting CP": (8, -6, "left")}
    for club, xi, yi in zip(tab.index, x, y):
        dx, dy, ha = offsets.get(club, (8, 4, "left"))
        lead = dict(arrowstyle="-", color=MUTED, lw=0.8, shrinkB=5) if abs(dx) > 10 or abs(dy) > 14 else None
        ax.annotate(club, (xi, yi), xytext=(dx, dy), textcoords="offset points", fontsize=8.5, color=INK,
                    ha=ha, va="center", arrowprops=lead)
    ax.set_xlim(*lim)
    ax.set_ylim(-0.3, 1.9)
    ax.set_xlabel("estimated cost of a round trip (spread, commission, tax), %")
    ax.set_ylabel("average gain per trade before costs, %")
    _title(fig, "No club's post-match drift pays for the cost of trading it",
           "Trade after each big surprise and hold up to 3 days: every club sits below the break-even line")
    fig.subplots_adjust(left=0.1, right=0.97, top=0.85, bottom=0.13)
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def match_week(reg, clubs, path):
    fig, axes = plt.subplots(1, len(clubs), figsize=(WIDTH, 4.2), sharey=True)
    for ax, club in zip(axes, clubs):
        cum, se = 100 * np.array(reg.loc[club, "week_cum"]), 196 * np.array(reg.loc[club, "week_cum_se"])
        ax.fill_between(WEEK_LAGS, cum - se, cum + se, color=SERIES, alpha=0.15, lw=0)
        ax.plot(WEEK_LAGS, cum, color=SERIES, lw=2, marker="o", ms=4)
        ax.axhline(0, color=MUTED, lw=0.8)
        ax.axvline(0, color=MUTED, lw=0.8, ls=":")
        ax.set_title(club, fontsize=10.5)
        ax.set_xticks([-4, -2, 0, 2, 4], ["−4", "−2", "0", "+2", "+4"], fontsize=8.5)
    axes[0].set_ylabel("cumulative move vs market, %")
    fig.text(0.535, 0.1, "trading days from the match (0 = first trading day after it)", ha="center", color=INK_2)
    _title(fig, "Shares rise before matches and fall after, whatever the result",
           "Average path around a match with an as-expected result (shaded: 95% range). Manchester United barely moves")
    fig.subplots_adjust(left=0.09, right=0.98, top=0.74, bottom=0.24, wspace=0.12)
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def charts(tab, reg, out):
    from .per_club import WEEK_CLUBS
    _style()
    reaction_bars(tab, out / "day0_reaction_by_club.png")
    edge_scatter(tab, out / "edge_vs_cost.png")
    match_week(reg, WEEK_CLUBS, out / "match_week_by_club.png")
