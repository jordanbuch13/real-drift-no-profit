"""Shared helpers: paths, config, odds to probabilities, club perspective rows."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
RAW_FD = ROOT / "data" / "raw" / "football_data"
RAW_BF = ROOT / "data" / "raw" / "betfair"
PROCESSED = ROOT / "data" / "processed"

CLUB_COLUMNS = [
    "match_id", "source", "competition_type", "season", "league", "date",
    "kickoff_time", "club", "opponent", "venue", "goals_for", "goals_against",
    "result", "odds_source", "odds_H", "odds_D", "odds_A", "overround", "p_win", "p_draw", "p_loss", "exp_points",
]


@dataclass
class Config:
    clubs: pd.DataFrame          # one row per club
    seasons: list[str]           # e.g. ["1213", ..., "2526"]
    matches_per_team: dict[str, int]   # league -> matches per team in a normal season
    season_notes: pd.DataFrame   # league, season, matches_per_team, reason
    excluded: pd.DataFrame       # league, season, date, home, away, reason
    friendly_filter: dict        # Step 1b: winter_break_min_days, date_rule_exempt
    super_cups: pd.DataFrame     # cup, league, date, exclude_clubs (one row per match day)
    oddsportal_results_90: pd.DataFrame  # date, home, away, result_hda, reason
    league_names: dict[str, str]       # league code -> name, e.g. E0 -> Premier League
    competition_names: dict[str, str]  # OddsPortal listing path or super cup key -> display name
    exchanges: dict                    # Step 3: exchange -> timezone, close_times
    robustness_benchmark: str | None   # Step 3: e.g. ^STOXX
    corporate_actions: pd.DataFrame    # Step 3: ticker, date, ex_date, factor, reason (Yahoo misadjustments)

    @property
    def leagues(self) -> list[str]:
        return sorted(self.clubs["league"].unique())


def season_codes(first: str, last: str) -> list[str]:
    start, end = int(first[:2]), int(last[:2])
    return [f"{y:02d}{y + 1:02d}" for y in range(start, end + 1)]


def season_bounds(code: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Loose window for a season. Runs to end of August to allow the 2019/20 Covid restart."""
    y1 = 2000 + int(code[:2])
    return pd.Timestamp(y1, 7, 1), pd.Timestamp(y1 + 1, 8, 31)


def load_config(path: Path = ROOT / "config" / "clubs.yaml") -> Config:
    raw = yaml.safe_load(path.read_text())
    clubs = pd.DataFrame(raw["clubs"])
    return Config(clubs=clubs, seasons=season_codes(raw["seasons"]["first"], raw["seasons"]["last"]),
                  matches_per_team=raw.get("league_matches_per_team", {}),
                  season_notes=pd.DataFrame(raw.get("season_notes", []),
                                            columns=["league", "season", "matches_per_team", "reason"]),
                  excluded=pd.DataFrame(raw.get("excluded_matches", []),
                                        columns=["league", "season", "date", "home", "away", "reason"]),
                  friendly_filter=raw.get("friendly_filter", {}),
                  super_cups=_super_cup_dates(raw.get("super_cups", {})),
                  oddsportal_results_90=pd.DataFrame(raw.get("oddsportal_results_90", []),
                                                     columns=["date", "home", "away", "result_hda", "reason"]),
                  league_names=raw.get("league_names", {}),
                  competition_names=raw.get("competition_names", {}),
                  exchanges=raw.get("exchanges", {}),
                  robustness_benchmark=raw.get("robustness_benchmark"),
                  corporate_actions=pd.DataFrame(raw.get("corporate_actions", []),
                                                 columns=["ticker", "date", "ex_date", "factor", "reason"]))


def _super_cup_dates(cups: dict) -> pd.DataFrame:
    rows = []
    for name, cup in cups.items():
        excluded = {(e["club"], pd.Timestamp(e["date"])) for e in cup.get("exclude", [])}
        for v in cup["dates"].values():
            for d in ([] if v is None else v if isinstance(v, list) else [v]):
                d = pd.Timestamp(d)
                rows.append({"cup": name, "league": cup["league"], "date": d,
                             "exclude_clubs": {c for c, x in excluded if x == d}})
    return pd.DataFrame(rows, columns=["cup", "league", "date", "exclude_clubs"])


# Odds to probabilities

def _power_method(raw: np.ndarray, iters: int = 100) -> np.ndarray:
    """Find k per row such that sum(raw_i ** k) == 1, by bisection. Margin falls more on longshots."""
    lo = np.full(len(raw), 0.2)
    hi = np.full(len(raw), 5.0)
    for _ in range(iters):
        k = (lo + hi) / 2
        too_big = (raw ** k[:, None]).sum(axis=1) > 1   # sum decreases as k rises (raw < 1)
        lo = np.where(too_big, k, lo)
        hi = np.where(too_big, hi, k)
    p = raw ** ((lo + hi) / 2)[:, None]
    return p / p.sum(axis=1, keepdims=True)  # clean up residual bisection error


def implied_probabilities(odds_home, odds_draw, odds_away, method: str = "proportional") -> pd.DataFrame:
    """Decimal odds to margin free probabilities. Returns p_H, p_D, p_A, overround."""
    o = np.column_stack([np.asarray(x, dtype=float) for x in (odds_home, odds_draw, odds_away)])
    raw = 1.0 / o
    overround = raw.sum(axis=1)
    if method == "proportional":
        p = raw / overround[:, None]
    elif method == "power":
        p = _power_method(raw)
    else:
        raise ValueError(f"unknown method {method!r}")
    return pd.DataFrame({"p_H": p[:, 0], "p_D": p[:, 1], "p_A": p[:, 2], "overround": overround})


# Match rows (home/away) to club rows

def to_club_rows(matches: pd.DataFrame, name_to_club: dict[str, str]) -> pd.DataFrame:
    """One row per listed club per match.

    `matches` needs: match_id, home, away, home_goals, away_goals, result_hda (H/D/A or NaN),
    p_H, p_D, p_A, plus any passthrough columns (date, season, league, ...).
    A match between two listed clubs yields two rows.
    """
    out = []
    for venue, side, other, gf, ga, p_win, p_loss, win_code, loss_code in [
        ("H", "home", "away", "home_goals", "away_goals", "p_H", "p_A", "H", "A"),
        ("A", "away", "home", "away_goals", "home_goals", "p_A", "p_H", "A", "H"),
    ]:
        sub = matches[matches[side].isin(name_to_club)].copy()
        sub["club"] = sub[side].map(name_to_club)
        sub["opponent"] = sub[other]
        sub["venue"] = venue
        sub["goals_for"] = sub[gf]
        sub["goals_against"] = sub[ga]
        sub["result"] = sub["result_hda"].map({win_code: "W", "D": "D", loss_code: "L"})
        sub["p_win"] = sub[p_win]
        sub["p_loss"] = sub[p_loss]
        sub["p_draw"] = sub["p_D"]
        out.append(sub)
    rows = pd.concat(out, ignore_index=True)
    rows["exp_points"] = 3 * rows["p_win"] + rows["p_draw"]
    return rows.sort_values(["date", "club"]).reset_index(drop=True)


def check_club_rows(rows: pd.DataFrame, label: str) -> None:
    """Hard checks shared by both sources. Raises on failure."""
    total = rows[["p_win", "p_draw", "p_loss"]].sum(axis=1)
    bad = rows[(total - 1).abs() > 1e-9]
    assert bad.empty, f"[{label}] probabilities do not sum to 1 on {len(bad)} rows"
    dup = rows[rows.duplicated(["club", "date"], keep=False)]
    assert dup.empty, f"[{label}] duplicate (club, date) rows:\n{dup[['club', 'date', 'opponent']]}"
    odd = rows[(rows["overround"] < 0.9) | (rows["overround"] > 1.15)]
    if not odd.empty:
        print(f"[{label}] WARNING {len(odd)} rows with overround outside 0.90 to 1.15:")
        print(odd[["date", "club", "opponent", "odds_source", "overround"]].head(20).to_string())
