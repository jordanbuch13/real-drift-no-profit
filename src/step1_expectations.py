"""Step 1: domestic league match expectations from football-data.co.uk odds.

Entry point: build_match_expectations(). See docs/step1_match_expectations.md.
"""
from __future__ import annotations

import difflib
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from .common import (CLUB_COLUMNS, PROCESSED, RAW_FD, check_club_rows, implied_probabilities,
                     load_config, season_bounds, to_club_rows)

URL = "https://www.football-data.co.uk/mmz4281/{season}/{league}.csv"

# First complete set wins. Closing odds preferred: best estimate of expectation at kickoff.
ODDS_PRIORITY = [
    ("pinnacle_closing", ("PSCH", "PSCD", "PSCA")),
    ("average_closing", ("AvgCH", "AvgCD", "AvgCA")),
    ("betfair_exchange_closing", ("BFECH", "BFECD", "BFECA")),
    ("pinnacle_prematch", ("PSH", "PSD", "PSA")),
    ("average_prematch", ("AvgH", "AvgD", "AvgA")),
    ("betbrain_average_prematch", ("BbAvH", "BbAvD", "BbAvA")),
]

# Pinnacle closed its public API on this date. Football Data says its Pinnacle odds since then
# (pre-closing and closing) are systematically out of date, so they are not used. docs/issues.md.
PINNACLE_UNRELIABLE_FROM = pd.Timestamp("2025-07-23")


def download_season(league: str, season: str, raw_dir: Path = RAW_FD) -> Path:
    """Save the raw CSV unmodified. Skips if already on disk (raw data is a snapshot)."""
    path = raw_dir / f"{season}_{league}.csv"
    if path.exists():
        return path
    raw_dir.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(URL.format(season=season, league=league),
                                 headers={"User-Agent": "Mozilla/5.0 (research project)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        path.write_bytes(resp.read())
    return path


def load_season_file(path: Path, league: str, season: str) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="latin1", on_bad_lines="warn")
    df = df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")]
    df = df.dropna(axis=1, how="all").dropna(subset=["HomeTeam", "AwayTeam"]).copy()
    df["league"] = league
    df["season"] = season
    return df


def select_odds(df: pd.DataFrame) -> pd.DataFrame:
    """Adds odds_H, odds_D, odds_A and odds_source using ODDS_PRIORITY, row by row."""
    out = df.copy()
    out[["odds_H", "odds_D", "odds_A"]] = np.nan
    out["odds_source"] = pd.Series([None] * len(out), index=out.index, dtype="object")
    for name, cols in ODDS_PRIORITY:
        if not set(cols) <= set(df.columns):
            continue
        vals = df[list(cols)].apply(pd.to_numeric, errors="coerce")
        # Overround below 1 is an arbitrage no real market offers: a junk price in the set
        # (e.g. one bookmaker's 251.00 inflating an average). Fall through to the next set.
        sane = (1 / vals).sum(axis=1) >= 1
        ok = vals.notna().all(axis=1) & (vals > 1).all(axis=1) & sane & out["odds_source"].isna()
        if name.startswith("pinnacle") and "date" in df:
            ok &= df["date"] < PINNACLE_UNRELIABLE_FROM
        out.loc[ok, ["odds_H", "odds_D", "odds_A"]] = vals.loc[ok].to_numpy()
        out.loc[ok, "odds_source"] = name
    return out


def check_names(matches: pd.DataFrame, clubs: pd.DataFrame) -> None:
    """Warn (with suggestions) for configured names never seen in their league."""
    for _, c in clubs.iterrows():
        lg = matches[matches["league"] == c["league"]]
        teams = set(lg["HomeTeam"]) | set(lg["AwayTeam"])
        if teams and c["football_data_name"] not in teams:
            close = difflib.get_close_matches(c["football_data_name"], teams, n=3, cutoff=0.4)
            print(f"WARNING name {c['football_data_name']!r} ({c['club']}) not found in "
                  f"{c['league']}. Close matches: {close}. Fix config/clubs.yaml.")


def build_match_expectations(download: bool = True, method: str = "proportional",
                             raw_dir: Path = RAW_FD, out_dir: Path = PROCESSED) -> pd.DataFrame:
    cfg = load_config()
    frames = []
    for league in cfg.leagues:
        for season in cfg.seasons:
            if download:
                try:
                    download_season(league, season, raw_dir)
                except Exception as e:  # report, never silently skip
                    print(f"WARNING download failed {season} {league}: {e}")
            path = raw_dir / f"{season}_{league}.csv"
            if path.exists():
                frames.append(load_season_file(path, league, season))
            else:
                print(f"WARNING missing raw file {path.name}")
    matches = pd.concat(frames, ignore_index=True).copy()  # defragment wide frame
    check_names(matches, cfg.clubs)

    # Dates: files mix dd/mm/yy and dd/mm/yyyy.
    matches["date"] = pd.to_datetime(matches["Date"], dayfirst=True, format="mixed")
    matches["kickoff_time"] = matches["Time"] if "Time" in matches else None

    name_to_club = dict(zip(cfg.clubs["football_data_name"], cfg.clubs["club"]))
    lengths = check_season_lengths(matches, cfg)
    games_in_file = club_games(matches, name_to_club)

    out_dir.mkdir(parents=True, exist_ok=True)
    matches, excluded = drop_excluded(matches, cfg.excluded)
    excluded.to_csv(out_dir / "excluded_matches.csv", index=False)
    print(f"Excluded matches (forfeits etc.): {len(excluded)} (logged to excluded_matches.csv)")

    involved = matches["HomeTeam"].isin(name_to_club) | matches["AwayTeam"].isin(name_to_club)
    matches = select_odds(matches[involved])

    missing = matches[matches["odds_source"].isna()]
    missing.assign(reason="no complete odds set").to_csv(out_dir / "missing_odds.csv", index=False)
    print(f"Matches with no usable odds: {len(missing)} (logged to missing_odds.csv)")
    matches = matches[matches["odds_source"].notna()].reset_index(drop=True)

    probs = implied_probabilities(matches["odds_H"], matches["odds_D"], matches["odds_A"], method)
    matches = pd.concat([matches, probs], axis=1).rename(columns={
        "HomeTeam": "home", "AwayTeam": "away", "FTHG": "home_goals",
        "FTAG": "away_goals", "FTR": "result_hda"})
    matches["match_id"] = (matches["league"] + "_" + matches["season"] + "_"
                           + matches["date"].dt.strftime("%Y%m%d") + "_"
                           + matches["home"] + "_" + matches["away"]).str.replace(" ", "")
    matches["source"] = "football_data"
    matches["competition_type"] = "league"

    rows = to_club_rows(matches, name_to_club)[CLUB_COLUMNS]
    run_checks(rows)
    counts = season_counts(rows, games_in_file, club_games(excluded, name_to_club),
                           club_games(missing, name_to_club), lengths, cfg)
    counts.to_csv(out_dir / "season_counts.csv", index=False)
    rows.to_csv(out_dir / "match_expectations.csv", index=False)
    return rows


def drop_excluded(matches: pd.DataFrame, excluded: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Remove configured matches (forfeits). Fails if one is missing from a loaded league season."""
    if excluded.empty:
        return matches, matches.iloc[0:0].assign(reason=None)
    ex = excluded.assign(date=pd.to_datetime(excluded["date"], dayfirst=True), season=excluded["season"].astype(str))
    keys = ["league", "season", "date", "HomeTeam", "AwayTeam"]
    merged = matches.merge(ex.rename(columns={"home": "HomeTeam", "away": "AwayTeam"}),
                           on=keys, how="left", indicator=True)
    hit = merged["_merge"].eq("both").to_numpy()
    loaded = set(zip(matches["league"], matches["season"]))
    found = set(map(tuple, merged.loc[hit, keys].to_numpy().tolist()))
    for _, e in ex.iterrows():
        key = (e["league"], e["season"], e["date"], e["home"], e["away"])
        assert (e["league"], e["season"]) not in loaded or key in found, \
            f"excluded match not found in raw data, fix config/clubs.yaml: {key}"
    return (matches[~hit].reset_index(drop=True),
            merged.loc[hit].drop(columns="_merge").reset_index(drop=True))


def club_games(matches: pd.DataFrame, name_to_club: dict[str, str]) -> pd.Series:
    """Count of matches per (club, season) where the club is home or away."""
    home = "HomeTeam" if "HomeTeam" in matches else "home"
    away = "AwayTeam" if "AwayTeam" in matches else "away"
    sides = pd.concat([matches[["season", home]].set_axis(["season", "team"], axis=1),
                       matches[["season", away]].set_axis(["season", "team"], axis=1)])
    sides = sides[sides["team"].isin(name_to_club)]
    return sides.assign(club=sides["team"].map(name_to_club)).groupby(["club", "season"]).size()


def check_season_lengths(matches: pd.DataFrame, cfg) -> pd.DataFrame:
    """Matches per team per league season. Warns on non-standard seasons with no season_notes entry."""
    sides = pd.concat([matches[["league", "season", "HomeTeam"]].set_axis(["league", "season", "team"], axis=1),
                       matches[["league", "season", "AwayTeam"]].set_axis(["league", "season", "team"], axis=1)])
    per_team = sides.groupby(["league", "season", "team"]).size()
    lengths = per_team.groupby(["league", "season"]).agg(["min", "max"]).reset_index()
    lengths["standard"] = lengths["league"].map(cfg.matches_per_team)
    notes = cfg.season_notes.assign(season=cfg.season_notes["season"].astype(str))
    lengths = lengths.merge(notes[["league", "season", "reason"]], on=["league", "season"], how="left")
    odd = lengths[((lengths["min"] != lengths["standard"]) | (lengths["max"] != lengths["standard"]))
                  & lengths["reason"].isna()]
    if not odd.empty:
        print(f"WARNING non-standard season length with no season_notes entry in config/clubs.yaml:\n"
              f"{odd.to_string(index=False)}")
    return lengths


def season_counts(rows, in_file, excluded, no_odds, lengths, cfg) -> pd.DataFrame:
    """Per club and season: matches in the raw file, how many were dropped and why, rows kept.
    Fails if they do not reconcile, i.e. a match was lost without being logged."""
    kept = rows.groupby(["club", "season"]).size()
    t = pd.DataFrame({"games_in_file": in_file, "excluded": excluded, "no_odds": no_odds,
                      "rows": kept}).fillna(0).astype(int).reset_index()
    t = t.merge(cfg.clubs[["club", "league"]], on="club").merge(
        lengths[["league", "season", "standard", "reason"]], on=["league", "season"], how="left")
    bad = t[t["games_in_file"] != t["excluded"] + t["no_odds"] + t["rows"]]
    assert bad.empty, f"club match counts do not reconcile:\n{bad.to_string(index=False)}"
    t = t.rename(columns={"reason": "season_note"})[
        ["club", "league", "season", "standard", "games_in_file", "excluded", "no_odds", "rows", "season_note"]]
    noted = t[t["season_note"].notna() | (t["excluded"] > 0) | (t["no_odds"] > 0)]
    print(f"\nShort, long or reduced club seasons ({len(noted)}, full table in season_counts.csv):")
    print(noted.to_string(index=False))
    return t


def run_checks(rows: pd.DataFrame) -> None:
    check_club_rows(rows, "step1")
    bounds = rows["season"].map(season_bounds)
    outside = rows[(rows["date"] < bounds.str[0]) | (rows["date"] > bounds.str[1])]
    assert outside.empty, f"dates outside their season:\n{outside[['season', 'date', 'club']]}"

    print("\nOdds source by season:")
    print(pd.crosstab(rows["season"], rows["odds_source"]).to_string())
    print("\nMatches per club per season:")
    print(pd.crosstab(rows["club"], rows["season"]).to_string())

    print("\nSpot check, raw odds next to probabilities:")
    print(rows.sample(min(5, len(rows)), random_state=0)[
        ["match_id", "club", "venue", "odds_H", "odds_D", "odds_A", "p_win", "p_draw", "p_loss"]].to_string())
