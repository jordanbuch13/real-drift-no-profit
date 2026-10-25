"""European fixture list (UEFA Champions League, Europa League, Conference League) from openfootball.

Used by Step 1b to tell European matches apart from friendlies, because Betfair Basic files do not
say which competition a match belongs to. Source: https://github.com/openfootball/champions-league
(public domain). Coverage is partial, see docs/issues.md:
  Champions League group stage onwards: every season
  Europa League: from 2020/21. Conference League: from 2021/22. Qualifiers: from 2024/25.
"""
from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

import pandas as pd

from .common import ROOT

RAW_OF = ROOT / "data" / "raw" / "openfootball"
REPO_API = "https://api.github.com/repos/openfootball/champions-league/contents/{season}"
RAW_URL = "https://raw.githubusercontent.com/openfootball/champions-league/master/{season}/{name}"
COMPETITIONS = {
    "cl": "Champions League", "clq": "Champions League qualifying",
    "el": "Europa League", "elq": "Europa League qualifying",
    "conf": "Conference League", "confq": "Conference League qualifying",
}

MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}
DATE_LINE = re.compile(r"^\s+(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) ([A-Z][a-z]{2}) (\d{1,2})(?: (\d{4}))?\s*$")
TIME_PREFIX = re.compile(r"^\s*(?:\d{1,2}[:.]\d{2})?\s*")
COUNTRY_SUFFIX = re.compile(r"\s*\([A-Z]{3}\)$")


def download_openfootball(seasons: list[str], raw_dir: Path = RAW_OF) -> None:
    """Save every competition file for the given seasons (e.g. "2015-16") unmodified.
    Skips files already on disk: the raw data is a snapshot."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    for season in seasons:
        with urllib.request.urlopen(REPO_API.format(season=season), timeout=30) as resp:
            listing = json.load(resp)
        for item in listing:
            stem = item["name"].removesuffix(".txt")
            path = raw_dir / f"{season}_{item['name']}"
            if stem not in COMPETITIONS or path.exists():
                continue
            with urllib.request.urlopen(RAW_URL.format(season=season, name=item["name"]), timeout=30) as resp:
                path.write_bytes(resp.read())


def _team(text: str) -> str:
    text = re.split(r"\s{2,}|\s+\d+-\d+|\s+@\s", text.strip())[0]
    return COUNTRY_SUFFIX.sub("", text.strip())


def parse_file(path: Path) -> pd.DataFrame:
    """One row per match: competition, date, home, away. The files print the year only on the
    first date line after it changes; later lines carry it. Groups restart from September, so the
    year cannot be inferred from month order."""
    season, stem = path.stem.split("_", 1)
    year, current, rows = int(season[:4]), None, []
    for line in path.read_text(encoding="utf-8").splitlines():
        if m := DATE_LINE.match(line):
            year = int(m.group(3)) if m.group(3) else year
            current = pd.Timestamp(year, MONTHS[m.group(1)], int(m.group(2)))
            continue
        if current is None or " v " not in line or line.lstrip().startswith(("#", "=", "▪")):
            continue
        home, away = TIME_PREFIX.sub("", line).split(" v ", 1)
        rows.append({"competition": COMPETITIONS[stem], "season": season, "date": current,
                     "home": _team(home), "away": _team(away)})
    return pd.DataFrame(rows, columns=["competition", "season", "date", "home", "away"])


def load_fixtures(name_to_club: dict[str, str], raw_dir: Path = RAW_OF) -> pd.DataFrame:
    """European matches of the listed clubs, one row per club per match: club, date, opponent, competition."""
    files = sorted(raw_dir.glob("*.txt"))
    if not files:
        return pd.DataFrame(columns=["club", "date", "opponent", "competition"])
    fx = pd.concat([parse_file(p) for p in files], ignore_index=True)
    out = []
    for side, other in [("home", "away"), ("away", "home")]:
        sub = fx[fx[side].isin(name_to_club)]
        out.append(pd.DataFrame({"club": sub[side].map(name_to_club), "date": sub["date"],
                                 "opponent": sub[other], "competition": sub["competition"]}))
    return pd.concat(out, ignore_index=True).sort_values(["date", "club"]).reset_index(drop=True)
