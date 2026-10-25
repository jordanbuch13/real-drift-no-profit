"""Step 2: match surprise, the result measured against the betting market's expectation.

Entry point: build_match_surprise(). See docs/step2_surprise.md.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .common import PROCESSED

SCORE = {"W": 1, "D": 0, "L": -1}
POINTS = {"W": 3, "D": 1, "L": 0}
TERCILES = ["low", "mid", "high"]


def probability_surprise(result: pd.Series, p_win: pd.Series, p_loss: pd.Series) -> pd.Series:
    """Main measure: actual score (W +1, D 0, L -1) minus the market's expected score p_win - p_loss.
    Between -2 and +2; positive for every win, negative for every loss."""
    return result.map(SCORE) - (p_win - p_loss)


def add_surprise(rows: pd.DataFrame) -> pd.DataFrame:
    rows = rows.copy()
    rows["actual_score"] = rows["result"].map(SCORE)
    rows["expected_score"] = rows["p_win"] - rows["p_loss"]
    rows["surprise"] = probability_surprise(rows["result"], rows["p_win"], rows["p_loss"])
    rows["p_outcome"] = np.select([rows["result"] == "W", rows["result"] == "D", rows["result"] == "L"],
                                  [rows["p_win"], rows["p_draw"], rows["p_loss"]], np.nan)
    rows["info"] = -np.log(rows["p_outcome"])
    rows["actual_points"] = rows["result"].map(POINTS)
    rows["surprise_points"] = rows["actual_points"] - rows["exp_points"]
    rows["surprise_sign"] = np.select([rows["surprise"] > 0, rows["surprise"] < 0], ["pos", "neg"], "zero")
    return rows


def add_terciles(rows: pd.DataFrame) -> tuple[pd.DataFrame, tuple[float, float]]:
    """Full sample terciles of surprise, for the event study. The backtest must not use these
    cutoffs (look-ahead); Step 4 recomputes them from earlier seasons only."""
    lo, hi = rows["surprise"].quantile([1 / 3, 2 / 3])
    rows = rows.copy()
    rows["surprise_tercile"] = pd.cut(rows["surprise"], [-np.inf, lo, hi, np.inf], labels=TERCILES).astype(str)
    return rows, (lo, hi)


def add_congestion(rows: pd.DataFrame) -> pd.DataFrame:
    """Calendar days to the club's previous and next match (any competition), their competition
    types, and the number of the club's matches in the 7 days after this one."""
    rows = rows.sort_values(["club", "date"]).reset_index(drop=True)
    g = rows.groupby("club")
    rows["days_since_prev"] = g["date"].diff().dt.days
    rows["days_to_next"] = -g["date"].diff(-1).dt.days
    rows["prev_competition_type"] = g["competition_type"].shift(1)
    rows["next_competition_type"] = g["competition_type"].shift(-1)
    counts = []
    for _, dates in g["date"]:
        d = dates.to_numpy()
        counts.append(np.searchsorted(d, d + np.timedelta64(7, "D"), side="right")
                      - np.searchsorted(d, d, side="right"))
    rows["matches_next_7d"] = np.concatenate(counts)
    for col in ["days_since_prev", "days_to_next"]:
        rows[col] = rows[col].astype("Int64")
    return rows


def run_checks(rows: pd.DataFrame) -> None:
    dup = rows[rows.duplicated(["club", "date"], keep=False)]
    assert dup.empty, f"duplicate (club, date) rows:\n{dup[['match_id', 'club', 'date']]}"
    assert rows["result"].isin(SCORE).all(), "rows without a W/D/L result after dropping abandoned matches"
    assert rows["surprise"].between(-2, 2).all(), "surprise outside -2 to +2"
    assert (rows.loc[rows["result"] == "W", "surprise"] > 0).all(), "a win with surprise <= 0"
    assert (rows.loc[rows["result"] == "L", "surprise"] < 0).all(), "a loss with surprise >= 0"
    assert rows["p_outcome"].between(0, 1).all() and (rows["info"] >= 0).all(), "p_outcome outside 0 to 1"
    prev_next = rows.groupby("club")["days_to_next"].shift(1)
    linked = rows["days_since_prev"].notna()
    assert (rows.loc[linked, "days_since_prev"] == prev_next[linked]).all(), "gaps do not line up"
    assert (rows["days_since_prev"].dropna() > 0).all(), "a gap of zero or negative days"

    def mean_se(s: pd.Series) -> pd.Series:
        return pd.Series({"n": len(s), "mean": s.mean(), "se": s.std() / np.sqrt(len(s))})

    print("\nCalibration: mean surprise (close to 0 if the market is unbiased)")
    print(f"overall: {rows['surprise'].mean():+.3f} (se {rows['surprise'].std() / np.sqrt(len(rows)):.3f}, "
          f"n {len(rows)})")
    for by in ["competition_type", "odds_source", "club", "season"]:
        t = rows.groupby(by)["surprise"].apply(mean_se).unstack()
        t["n"] = t["n"].astype(int)
        print(f"\nby {by}:\n{t.round(3).to_string()}")

    print("\nSpot check:")
    print(rows.sample(min(5, len(rows)), random_state=0)[
        ["date", "club", "opponent", "competition", "result", "p_win", "p_draw", "p_loss",
         "surprise", "surprise_tercile", "days_since_prev"]].to_string())


def build_match_surprise(in_path: Path = PROCESSED / "match_expectations_all.csv",
                         out_dir: Path = PROCESSED) -> pd.DataFrame:
    """Read Step 1 and 1b's combined event set, drop abandoned matches, add surprise, terciles and
    fixture congestion, write match_surprise.csv."""
    rows = pd.read_csv(in_path, parse_dates=["date"], dtype={"season": str})
    out_dir.mkdir(parents=True, exist_ok=True)

    abandoned = rows["result"].isna()
    rows.loc[abandoned, ["match_id", "club", "date", "opponent", "competition_type", "competition"]].to_csv(
        out_dir / "surprise_abandoned.csv", index=False)
    print(f"Abandoned matches (no result) dropped: {abandoned.sum()} (logged to surprise_abandoned.csv)")
    rows = rows[~abandoned]

    rows = add_surprise(rows)
    rows, (lo, hi) = add_terciles(rows)
    print(f"Tercile cutoffs (full sample): low <= {lo:.3f} < mid <= {hi:.3f} < high")
    print(pd.crosstab(rows["result"], rows["surprise_tercile"]).reindex(columns=TERCILES, fill_value=0).to_string())
    rows = add_congestion(rows)

    run_checks(rows)
    gaps = rows["days_since_prev"].dropna()
    print(f"\nFixture congestion: median gap {gaps.median():.0f} days, "
          f"{(gaps <= 3).mean():.1%} of matches 3 days or fewer after the previous one")

    rows = rows.sort_values(["date", "club"]).reset_index(drop=True)
    rows.to_csv(out_dir / "match_surprise.csv", index=False)
    return rows
