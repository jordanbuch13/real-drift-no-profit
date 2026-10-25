"""OddsPortal closing odds for European and cup matches that Betfair Basic does not have.

Betfair Basic misses some Champions League matches, almost all in 2015/16 to 2017/18, and starts
in May 2015, so it has no European or cup matches for 2012/13 to 2014/15 (see docs/issues.md).
OddsPortal has them. Step 1b adds an OddsPortal match only when Betfair has no match for the same
listed club within a day, so Betfair stays the source wherever it exists.

Scraping (outside the pipeline, needs Python 3.12+, see docs/step1b_betfair.md):
  oddsharvester historic -s football -l champions-league --season 2015-2016 --links-only ...
  oddsharvester historic -s football --match-links-file links.txt --season 2015-2016 -m 1x2 -f json ...
Files go to data/raw/oddsportal/*_odds_*.json. Link lists of whole competitions go to
data/raw/oddsportal/links/; club_match_links picks the listed clubs' matches out of them.

Odds are the mean of the bookmakers OddsPortal shows (9 UK bookmakers from a UK address; no Pinnacle
or Betfair Exchange). On 252 CL matches with both, the margin-free probabilities agree closely with
Betfair (mean absolute difference about 0.01 per outcome).
"""
from __future__ import annotations

import difflib
import json
import re
import unicodedata
from pathlib import Path

import pandas as pd

from .common import ROOT

RAW_OP = ROOT / "data" / "raw" / "oddsportal"


def result_90(partial_results: str | None) -> str | None:
    """H/D/A after 90 minutes from OddsPortal's half-time scores, e.g. "(1:1, 0:1)" -> "A".
    The final score on OddsPortal includes extra time, which does not settle 1X2 bets."""
    halves = re.findall(r"(\d+):(\d+)", partial_results or "")
    if len(halves) != 2:
        return None
    home, away = (sum(int(h[i]) for h in halves) for i in (0, 1))
    return "H" if home > away else "A" if away > home else "D"


def load_oddsportal(name_to_club: dict[str, str], results_90: pd.DataFrame | None = None,
                    raw_dir: Path = RAW_OP) -> pd.DataFrame:
    """One row per scraped match involving a listed club, in the shape of Betfair's parsed markets:
    match_link, home, away, kickoff_utc, odds_H/D/A (mean over bookmakers), n_bookmakers, result_hda,
    op_competition (OddsPortal's competition name, e.g. "Europa League", "Coppa Italia").
    results_90 (date, home, away, result_hda) fills results the page does not give.

    A page with a final score but no half-time scores is a match that went to extra time or
    penalties (OddsPortal then counts a shoot-out win as a goal: Bayern 1-2 Dortmund, 28/04/2015,
    was 1-1 after extra time). A single match only goes to extra time when level, so its 90 minute
    result is a draw. A second leg (the same teams the other way round in the same competition
    1 to 40 days earlier) can stand at anything after 90 minutes: it needs a results_90 entry, and
    without one has no result (printed)."""
    overrides = {}
    if results_90 is not None:
        for r in results_90.itertuples():
            overrides[(pd.to_datetime(r.date, dayfirst=True).date(), r.home, r.away)] = r.result_hda
    rows = []
    for path in sorted(raw_dir.glob("*.json")):
        for rec in json.loads(path.read_text()):
            home, away, odds = rec.get("home_team"), rec.get("away_team"), rec.get("1x2_market") or []
            if not (home and away and odds) or not (home in name_to_club or away in name_to_club):
                continue
            o = pd.DataFrame(odds)[["1", "X", "2"]].apply(pd.to_numeric, errors="coerce").dropna()
            if o.empty:
                continue
            kickoff = pd.Timestamp(rec["match_date"].replace(" UTC", ""), tz="UTC")
            result = result_90(rec.get("partial_results"))
            went_long = result is None and rec.get("home_score") not in (None, "")
            result = overrides.get((kickoff.date(), home, away), result)
            rows.append({"went_long": went_long, "league_name": rec.get("league_name"),
                         "match_link": rec["match_link"], "home": home, "away": away, "kickoff_utc": kickoff,
                         "odds_H": o["1"].mean(), "odds_D": o["X"].mean(), "odds_A": o["2"].mean(),
                         "n_bookmakers": len(o), "result_hda": result, "op_competition": rec.get("league_name")})
    cols = ["match_link", "home", "away", "kickoff_utc", "odds_H", "odds_D", "odds_A", "n_bookmakers", "result_hda",
            "op_competition"]
    out = pd.DataFrame(rows, columns=cols + ["went_long", "league_name"]).drop_duplicates("match_link")
    out = out.reset_index(drop=True)
    for i in out.index[out["went_long"] & out["result_hda"].isna()]:
        r = out.loc[i]
        gap = (r["kickoff_utc"] - out["kickoff_utc"]).dt.days
        first_leg = ((out["home"] == r["away"]) & (out["away"] == r["home"]) & gap.between(1, 40)
                     & (out["league_name"] == r["league_name"]))
        if first_leg.any():
            print(f"  OddsPortal {r['home']} v {r['away']} ({r['kickoff_utc']:%d/%m/%Y}): second leg after extra "
                  f"time, 90 minute result unknown; add it to oddsportal_results_90 in config/clubs.yaml")
        else:
            out.loc[i, "result_hda"] = "D"
    return out[cols]


_NAME_NOISE = {"fc", "sc", "cf", "ac", "as", "sl", "fk", "kv", "sk", "afc", "cp", "st", "st.", "h.", "the"}


def _name_tokens(name: str) -> set[str]:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().casefold()
    return set(re.findall(r"[a-z0-9.]+", plain)) - _NAME_NOISE


def same_team(a: str, b: str) -> bool:
    """Loose match between spellings of a non listed opponent across sources:
    "Zenit" ~ "Zenit St Petersburg", "H. Beer Sheva" ~ "Hapoel Beer Sheva", "Qarabag" ~ "Karabakh"."""
    ta, tb = _name_tokens(a), _name_tokens(b)
    if ta and tb and (ta <= tb or tb <= ta or len(ta & tb) >= 2):
        return True
    return difflib.SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio() >= 0.6


def missing_from_betfair(op: pd.DataFrame, op_names: dict[str, str],
                         betfair: pd.DataFrame, bf_names: dict[str, str]) -> pd.DataFrame:
    """OddsPortal matches Betfair does not have. Betfair has the match if the same listed club plays
    there at the same venue within 3 hours of the kickoff, or within a day against the same opponent
    (names differ between sources: "PSG" / "Paris St-G", so time and venue come first). A Betfair match
    that day against someone else (e.g. Celtic v Lyon, a friendly the day after Linfield v Celtic,
    14/07/2017) does not count; those cases are printed."""
    bf = pd.concat([pd.DataFrame({"club": betfair[side].map(bf_names), "date": betfair["kickoff_utc"],
                                  "venue": venue, "opponent": betfair[other],
                                  "event": betfair["home"] + " v " + betfair["away"]})
                    for side, other, venue in (("home", "away", "H"), ("away", "home", "A"))]
                   ).dropna(subset=["club"])
    keep = []
    for r in op.itertuples():
        found = False
        for side, other, venue in ((r.home, r.away, "H"), (r.away, r.home, "A")):
            club = op_names.get(side)
            near = bf[(bf["club"] == club) & ((bf["date"] - r.kickoff_utc).abs() <= pd.Timedelta(days=1))]
            gaps = (near["date"] - r.kickoff_utc).abs()
            for opp, event, v, g in zip(near["opponent"], near["event"], near["venue"], gaps):
                if ((v == venue and g <= pd.Timedelta(hours=3))
                        or (op_names.get(other) or other) == (bf_names.get(opp) or opp) or same_team(other, opp)):
                    found = True
                elif club:
                    print(f"  OddsPortal {r.home} v {r.away} ({r.kickoff_utc:%d/%m/%Y}) kept: "
                          f"Betfair has only {event} that day")
        keep.append(not found)
    return op[keep].reset_index(drop=True)


def club_match_links(links_dir: Path, id_to_club: dict[str, str], extra: list[Path] = ()) -> pd.DataFrame:
    """Matches of the listed clubs in OddsPortal competition link lists (links_dir/*.csv and any
    extra files, written by oddsharvester --links-only). A club is in the match if its team id is in
    the link (.../h2h/<slug>-<id>/<slug>-<id>/#<match>). One row per match: match_link, league,
    season, match_day, clubs."""
    frames = [pd.read_csv(p, dtype=str) for p in sorted(links_dir.glob("*.csv")) + list(extra)]
    if not frames:
        return pd.DataFrame(columns=["match_link", "league", "season", "match_day", "clubs"])
    links = pd.concat(frames, ignore_index=True).drop_duplicates("match_link")
    teams = links["match_link"].str.extract(r"/h2h/([^/]+)/([^/]+)/")
    ids = teams.apply(lambda c: c.str.rsplit("-", n=1).str[-1])
    links["clubs"] = [", ".join(sorted({id_to_club[i] for i in pair if i in id_to_club}))
                      for pair in zip(ids[0], ids[1])]
    return links[links["clubs"] != ""].reset_index(drop=True)


def league_kickoffs(raw_dir: Path, id_to_club: dict[str, str]) -> pd.DataFrame:
    """Kickoff times (UK time) of the listed clubs' league matches scraped from OddsPortal match
    pages (raw_dir/*.json, 2012/13 to 2014/15, where Football Data has no times and Betfair no data).
    One row per club and match: club, date, kickoff_time."""
    rows = []
    for path in sorted(raw_dir.glob("*.json")):
        for rec in json.loads(path.read_text()):
            when = pd.Timestamp(rec["match_date"].replace(" UTC", ""), tz="UTC").tz_convert("Europe/London")
            for team_id in re.findall(r"-([A-Za-z0-9]{8})/", rec["match_link"].split("#")[0]):
                if team_id in id_to_club:
                    rows.append({"club": id_to_club[team_id], "date": when.tz_localize(None).normalize(),
                                 "kickoff_time": when.strftime("%H:%M")})
    return pd.DataFrame(rows, columns=["club", "date", "kickoff_time"]).drop_duplicates(["club", "date"])
