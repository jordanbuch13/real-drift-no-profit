"""League tables for the E1 stakes split (Step 4): final tables from English Wikipedia league season
articles ("2016–17 Serie A"), and the table before every league match built from football-data results.

Wikipedia gives, per league and season, what football-data cannot: point deductions (points minus
3·W + D), and which places qualified for the Champions League and which were relegated or went to
a relegation play-off (the "Qualification or relegation" column). The rendered HTML of each article
is saved unmodified to data/raw/wikipedia_leagues/ as a snapshot (text CC BY-SA).
"""
from __future__ import annotations

import io
import json
import re
import time
import urllib.parse
from pathlib import Path

import pandas as pd
import yaml

from .common import PROCESSED, RAW_FD, ROOT, load_config
from .step1_expectations import load_season_file
from .wikipedia_fixtures import API, _get

RAW_WPL = ROOT / "data" / "raw" / "wikipedia_leagues"

# Article title per league; {s} is the season as "2016–17".
LEAGUE_TITLES = {
    "D1": "{s} Bundesliga",
    "E0": "{s} Premier League",
    "F1": "{s} Ligue 1",
    "I1": "{s} Serie A",
    "N1": "{s} Eredivisie",
    "P1": "{s} Primeira Liga",
    "SC0": "{s} Scottish Premiership",
    "T1": "{s} Süper Lig",
}
# Earlier names of a league, tried when the title above has no article.
TITLE_FALLBACKS = {"SC0": ["{s} Scottish Premier League"]}


def season_label(code: str) -> str:
    return f"20{code[:2]}–{code[2:]}"


def download_tables(seasons: list[str] | None = None, raw_dir: Path = RAW_WPL, pause: float = 3.0) -> None:
    """Save the rendered HTML of every league season article to raw_dir/{league}_{season}.json.
    Skips files already on disk."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    for league in cfg.leagues:
        for code in seasons or cfg.seasons:
            path = raw_dir / f"{league}_{code}.json"
            if path.exists():
                continue
            data = {}
            for pattern in [LEAGUE_TITLES[league], *TITLE_FALLBACKS.get(league, [])]:
                title = pattern.format(s=season_label(code))
                query = urllib.parse.urlencode({"action": "parse", "page": title, "prop": "text", "redirects": 1,
                                                "format": "json", "formatversion": 2})
                data = _get(f"{API}?{query}")
                time.sleep(pause)
                if "error" not in data:
                    break
                print(f"  no article: {title} ({data['error'].get('code')})")
            path.write_text(json.dumps(data, ensure_ascii=False))


# Parsing

_NOTE = re.compile(r"\[[a-z0-9 ]+\]")
_SPAN = re.compile(r'(colspan|rowspan)="(\d+\.\d+)"')
_STATUS = re.compile(r"\s*\((?:[A-Z]{1,2}|[A-Z], [A-Z])\)\s*$")   # (C), (R), (O), (Q), (X)...


def _clean(text) -> str:
    if pd.isna(text):
        return ""
    return _STATUS.sub("", _NOTE.sub("", str(text)).replace("vte", "")).strip()


def _num(text) -> float:
    s = _NOTE.sub("", str(text)).replace("−", "-").replace("+", "").strip()
    try:
        return float(s)
    except ValueError:
        return float("nan")


def parse_table(html: str) -> pd.DataFrame:
    """The final league table: the first table with Pos, Team, Pld, W, D, L, GF, GA and Pts columns.
    Columns: pos, team, pld, w, d, l, gf, ga, pts, adjustment (pts - 3·w - d), note (the
    "Qualification or relegation" text, empty if none)."""
    html = _SPAN.sub(lambda m: f'{m[1]}="{int(float(m[2]))}"', html)   # colspan="2.5" breaks read_html
    for t in pd.read_html(io.StringIO(html)):
        if isinstance(t.columns, pd.MultiIndex):
            t.columns = [c[-1] for c in t.columns]
        cols = {c: _NOTE.sub("", str(c)).replace("vte", "").strip() for c in t.columns}
        t = t.rename(columns=cols)
        need = ["Pos", "Team", "Pld", "W", "D", "L", "GF", "GA", "Pts"]
        if not all(c in t.columns for c in need):
            continue
        note_col = next((c for c in t.columns if c.startswith(("Qualification", "Relegation"))), None)
        out = pd.DataFrame({
            "pos": t["Pos"].map(_num), "team": t["Team"].map(_clean),
            **{c.lower(): t[c].map(_num) for c in need[2:]},
            "note": t[note_col].map(_clean) if note_col else "",
        })
        out = out.dropna(subset=["pos", "pld"]).reset_index(drop=True)
        out[["pos", "pld", "w", "d", "l", "gf", "ga", "pts"]] = out[["pos", "pld", "w", "d", "l", "gf", "ga", "pts"]].astype(int)
        out["adjustment"] = out["pts"] - 3 * out["w"] - out["d"]
        return out
    raise ValueError("no league table found")


def load_tables(raw_dir: Path = RAW_WPL) -> pd.DataFrame:
    """All downloaded final tables, with league and season columns."""
    frames = []
    for path in sorted(raw_dir.glob("*.json")):
        league, code = path.stem.split("_")
        data = json.loads(path.read_text())
        if "parse" not in data:
            print(f"  {path.name}: no article")
            continue
        t = parse_table(data["parse"]["text"])
        t.insert(0, "season", code)
        t.insert(0, "league", league)
        t.insert(2, "article", data["parse"]["title"])
        frames.append(t)
    return pd.concat(frames, ignore_index=True)


_CL = re.compile(r"champions league", re.I)
_REL = re.compile(r"relegat|premiership play-off", re.I)   # Scotland: "Qualification for the Premiership play-off final"
_NOT_REL = re.compile(r"tie-breaker", re.I)   # Serie A 2022/23: a play-off between clubs level on points


def season_places(tables: pd.DataFrame, eps: pd.DataFrame, overrides: pd.DataFrame) -> pd.DataFrame:
    """Per league and season: teams, scheduled matches per team, last Champions League place and first
    relegation place.

    last_cl: the run of places from 1st whose note names the Champions League (any round), less one
    where the league won a European Performance Spot (eps: league, season), which was only known late
    in the season. A Champions League place won by a cup (Europa League winner in 6th, say) breaks the
    run and is not counted. first_rel: first place whose note names relegation, play-offs included.
    Seasons with no relegation (Eredivisie and Super Lig 2019/20) take the number of relegation places
    of the season before. overrides (league, season, last_cl, first_rel) replace what the table shows.
    The places read from the tables are kept as last_cl_table and first_rel_table."""
    rows = []
    eps_keys = set(zip(eps["league"], eps["season"].astype(str)))
    for (league, code), t in tables.groupby(["league", "season"], sort=True):
        t = t.sort_values("pos")
        is_cl = t["note"].str.contains(_CL).to_numpy()
        last_cl = 0
        while last_cl < len(t) and is_cl[last_cl]:
            last_cl += 1
        rel = t[t["note"].str.contains(_REL) & ~t["note"].str.contains(_NOT_REL)]
        first_rel = int(rel["pos"].min()) if len(rel) else None
        rows.append({"league": league, "season": code, "teams": len(t),
                     "matches_per_team": 38 if league == "SC0" else 2 * (len(t) - 1),
                     "last_cl_table": last_cl, "first_rel_table": first_rel,
                     "last_cl": last_cl - ((league, code) in eps_keys), "first_rel": first_rel, "source": ""})
    out = pd.DataFrame(rows)
    for i, r in out.iterrows():
        if pd.isna(r["first_rel"]):
            prev = out[(out["league"] == r["league"]) & (out["season"] < r["season"])].iloc[-1]
            out.loc[i, "first_rel"] = r["teams"] - (prev["teams"] - prev["first_rel"])
            out.loc[i, "source"] = f"no relegation; places as {prev['season']}"
    for _, o in overrides.iterrows():
        i = out.index[(out["league"] == o["league"]) & (out["season"] == str(o["season"]))]
        for col in ["last_cl", "first_rel"]:
            if pd.notna(o.get(col)):
                out.loc[i, col] = o[col]
        out.loc[i, "source"] = "override: " + o["reason"]
    out.loc[[(l, s) in eps_keys for l, s in zip(out["league"], out["season"])], "source"] = "European Performance Spot not counted"
    out[["last_cl", "first_rel"]] = out[["last_cl", "first_rel"]].astype(int)
    return out


def load_results(cfg, raw_dir: Path = RAW_FD) -> pd.DataFrame:
    """Every league result in the football-data files (forfeits included: the awarded score counts in
    the table). Columns: league, season, date, home, away, hg, ag."""
    frames = []
    for league in cfg.leagues:
        for code in cfg.seasons:
            df = load_season_file(raw_dir / f"{code}_{league}.csv", league, code)
            frames.append(pd.DataFrame({"league": league, "season": code,
                                        "date": pd.to_datetime(df["Date"], dayfirst=True, format="mixed"),
                                        "home": df["HomeTeam"], "away": df["AwayTeam"],
                                        "hg": df["FTHG"].astype(int), "ag": df["FTAG"].astype(int)}))
    return pd.concat(frames, ignore_index=True)


def _team_rows(results: pd.DataFrame) -> pd.DataFrame:
    """One row per team per match: league, season, date, team, opponent, gf, ga, pts. Points from the
    score, or from points_home / points_away where given (awarded matches)."""
    sides = []
    for team, opp, gf, ga, pts in [("home", "away", "hg", "ag", "points_home"), ("away", "home", "ag", "hg", "points_away")]:
        s = results[["league", "season", "date"]].copy()
        s["team"], s["opponent"], s["gf"], s["ga"] = results[team], results[opp], results[gf], results[ga]
        s["pts"] = 3 * (s["gf"] > s["ga"]) + (s["gf"] == s["ga"])
        if pts in results:
            s["pts"] = results[pts].fillna(s["pts"]).astype(int)
        sides.append(s)
    r = pd.concat(sides, ignore_index=True)
    return r.sort_values(["league", "season", "date", "team"]).reset_index(drop=True)


def apply_awarded(results: pd.DataFrame, awarded: pd.DataFrame) -> pd.DataFrame:
    """results with the awarded matches' scores (and points_home / points_away) in place of the pitch."""
    out = results.copy()
    out["points_home"] = out["points_away"] = float("nan")
    for _, a in awarded.iterrows():
        i = out.index[(out["league"] == a["league"]) & (out["date"] == a["date"]) & (out["home"] == a["home"])
                      & (out["away"] == a["away"])]
        if len(i) != 1:
            raise ValueError(f"awarded match not found in football-data, fix config/clubs.yaml: {a.to_dict()}")
        out.loc[i, ["hg", "ag", "points_home", "points_away"]] = [a["hg"], a["ag"], a.get("points_home"), a.get("points_away")]
    return out


def awarded_adjustments(results: pd.DataFrame, awarded: pd.DataFrame) -> pd.DataFrame:
    """The change an award makes to each team's points, goal difference and goals, counted from the
    decision: league, season, team, date, points, gd, gf."""
    before = _team_rows(results.assign(points_home=float("nan"), points_away=float("nan")))
    after = _team_rows(apply_awarded(results, awarded))
    d = after[["pts", "gf", "ga"]] - before[["pts", "gf", "ga"]]
    changed = after.assign(points=d["pts"], gd=d["gf"] - d["ga"], gf=d["gf"])[(d != 0).any(axis=1)]
    decided = awarded.assign(decided=pd.to_datetime(awarded["decided"]))
    out = []
    for _, c in changed.iterrows():
        a = decided[(decided["league"] == c["league"]) & (decided["date"] == c["date"])
                    & decided[["home", "away"]].isin([c["team"]]).any(axis=1)].iloc[0]
        out.append({"league": c["league"], "season": c["season"], "team": c["team"], "date": a["decided"],
                    "points": c["points"], "gd": c["gd"], "gf": c["gf"]})
    return pd.DataFrame(out, columns=["league", "season", "team", "date", "points", "gd", "gf"])


def final_tables(results: pd.DataFrame) -> pd.DataFrame:
    """Final tables from the results, without deductions: league, season, team, pld, w, d, l, gf, ga, pts."""
    r = _team_rows(results)
    r["w"], r["d"], r["l"] = r["pts"] == 3, r["pts"] == 1, r["pts"] == 0
    t = r.groupby(["league", "season", "team"]).agg(pld=("pts", "size"), w=("w", "sum"), d=("d", "sum"),
                                                    l=("l", "sum"), gf=("gf", "sum"), ga=("ga", "sum"),
                                                    pts=("pts", "sum"))
    return t.reset_index()


def match_teams(fd: pd.DataFrame, wp: pd.DataFrame, goal_diffs: pd.DataFrame) -> pd.DataFrame:
    """Pair football-data teams with Wikipedia rows of the same league and season on the record
    (pld, w, d, l, gf, ga), which is unique within a season in practice. Teams listed in goal_diffs
    (league, season, teams) are paired on (pld, w, d, l) among themselves. Returns the Wikipedia rows
    with fd_team (None where no football-data team has that record)."""
    key = ["league", "season", "pld", "w", "d", "l", "gf", "ga"]
    fd_keys = fd[key + ["team"]].rename(columns={"team": "fd_team"})
    dup = fd_keys.duplicated(key, keep=False)
    if dup.any():
        print(f"  identical records, not paired: {fd_keys[dup].to_dict('records')}")
    out = wp.merge(fd_keys[~dup], on=key, how="left")
    for _, g in goal_diffs.iterrows():
        cand = fd[(fd["league"] == g["league"]) & (fd["season"] == str(g["season"])) & fd["team"].isin(g["teams"])]
        for i in out.index[(out["league"] == g["league"]) & (out["season"] == str(g["season"])) & out["fd_team"].isna()]:
            hit = cand[(cand[["pld", "w", "d", "l"]] == out.loc[i, ["pld", "w", "d", "l"]].to_numpy()).all(axis=1)]
            if len(hit) == 1:
                out.loc[i, "fd_team"] = hit["team"].iloc[0]
    return out


def standings_before(results: pd.DataFrame, adjustments: pd.DataFrame) -> pd.DataFrame:
    """For every team's league match: its match number in the season and the table on the morning of
    the match (all results of earlier dates). adjustments: league, season, team, date, points, gd, gf
    (deductions and awarded results, counted from their date). Returns league, season, date, team,
    opponent, match_no, pts, rank (by points, goal difference, goals scored) and the points of the
    whole table, highest first (table_pts, a tuple)."""
    r = _team_rows(results)
    r["gd"] = r["gf"] - r["ga"]
    out = []
    for (league, code), g in r.groupby(["league", "season"], sort=False):
        g = g.assign(match_no=g.groupby("team").cumcount() + 1)
        dates = pd.DatetimeIndex(sorted(g["date"].unique()))
        daily = g.pivot_table(index="date", columns="team", values=["pts", "gd", "gf"], aggfunc="sum", fill_value=0)
        before = daily.reindex(dates, fill_value=0).cumsum().shift(1, fill_value=0).astype(float)
        adj = adjustments[(adjustments["league"] == league) & (adjustments["season"] == code)]
        for _, a in adj.iterrows():
            if a["team"] not in before["pts"].columns:
                raise ValueError(f"adjustment for a team not in football-data, fix config/clubs.yaml: {a.to_dict()}")
            for col in ["pts", "gd", "gf"]:
                before.loc[dates > a["date"], (col, a["team"])] += a["points" if col == "pts" else col]
        for date, day in g.groupby("date", sort=True):
            tab = pd.DataFrame({c: before.loc[date, c] for c in ["pts", "gd", "gf"]})
            tab = tab.sort_values(["pts", "gd", "gf"], ascending=False)
            rank = pd.Series(range(1, len(tab) + 1), index=tab.index)
            table_pts = tuple(tab["pts"].astype(int))
            for m in day.itertuples():
                out.append({"league": league, "season": code, "date": date, "team": m.team,
                            "opponent": m.opponent, "match_no": m.match_no,
                            "pts": int(tab.at[m.team, "pts"]), "rank": int(rank[m.team]), "table_pts": table_pts})
    return pd.DataFrame(out)


def gap_to_place(rank: int, pts: int, table_pts: tuple, place: int) -> int:
    """Points between the club and the line below `place` (between places place and place+1): a club
    on or above the line is that many points ahead of the team just below it, a club below it that
    many behind the team on `place`. Clubs level on points give 0 whichever side the tiebreak puts
    them, so the tiebreak rules do not matter."""
    if place < 1 or place >= len(table_pts):
        return 10 ** 6
    return pts - table_pts[place] if rank <= place else table_pts[place - 1] - pts


def stakes(st: pd.DataFrame, places: pd.DataFrame, last_rounds: int, within: int) -> pd.DataFrame:
    """E1 flag per team league match: in the last `last_rounds` scheduled rounds and within `within`
    points of the title line (below 1st), the line below the last Champions League place or the line
    above the first relegation place."""
    st = st.merge(places[["league", "season", "matches_per_team", "last_cl", "first_rel"]], on=["league", "season"])
    for name, place in [("title", lambda r: 1), ("cl", lambda r: r.last_cl), ("rel", lambda r: r.first_rel - 1)]:
        st[f"gap_{name}"] = [gap_to_place(r.rank, r.pts, r.table_pts, place(r)) for r in st.itertuples()]
    st["late"] = st["match_no"] > st["matches_per_team"] - last_rounds
    for name in ["title", "cl", "rel"]:
        st[f"near_{name}"] = st[f"gap_{name}"].abs() <= within
    st["stakes"] = st["late"] & st[["near_title", "near_cl", "near_rel"]].any(axis=1)
    return st


def build_e1(out_dir: Path = PROCESSED, raw_dir: Path = RAW_WPL) -> pd.DataFrame:
    """Writes league_tables_wikipedia.csv (final tables, paired with football-data names),
    league_places.csv (places per league and season) and league_stakes.csv (one row per league match
    of a listed club: table position before the match, gaps to the three lines, late, stakes)."""
    cfg = load_config()
    e1 = yaml.safe_load((ROOT / "config" / "clubs.yaml").read_text())["e1_stakes"]
    awarded = pd.DataFrame(e1["awarded"]).assign(date=lambda d: pd.to_datetime(d["date"]))
    goal_diffs = pd.DataFrame(e1["goal_differences"])

    wp = load_tables(raw_dir)
    results = load_results(cfg)
    fd = final_tables(apply_awarded(results, awarded))
    wp = match_teams(fd, wp, goal_diffs)
    _check_tables(fd, wp, goal_diffs)
    wp.to_csv(out_dir / "league_tables_wikipedia.csv", index=False)

    ded = pd.DataFrame(e1["deductions"]).assign(gd=0, gf=0)
    ded = ded.assign(season=ded["season"].astype(str), date=pd.to_datetime(ded["date"]))
    _check_deductions(wp, ded, pd.DataFrame(e1["wikipedia_errors"]))
    adj = pd.concat([ded[["league", "season", "team", "date", "points", "gd", "gf"]],
                     awarded_adjustments(results, awarded)], ignore_index=True)

    places = season_places(wp, pd.DataFrame(e1["european_performance_spots"]), pd.DataFrame(e1["place_overrides"]))
    places.to_csv(out_dir / "league_places.csv", index=False)

    _check_final_points(results, adj, wp, pd.DataFrame(e1["wikipedia_errors"]))
    st = standings_before(results, adj)
    clubs = cfg.clubs.set_index("football_data_name")["club"]
    st = st[st["team"].isin(clubs.index)].copy()
    st.insert(3, "club", st["team"].map(clubs))
    st = stakes(st, places, e1["last_rounds"], e1["within_points"]).drop(columns=["table_pts", "team"])
    st.to_csv(out_dir / "league_stakes.csv", index=False)

    late = st[st["late"]]
    print(f"League matches of listed clubs: {len(st)}; late (last {e1['last_rounds']} rounds): {len(late)}; "
          f"with stakes: {int(st['stakes'].sum())}")
    print(f"Late matches within {e1['within_points']} points of each line:")
    print(late[["near_title", "near_cl", "near_rel"]].sum().to_string())
    print("Share of late matches with stakes, by club:")
    print(late.groupby("club")["stakes"].agg(["size", "mean"]).round(2).to_string())
    return st


def _check_tables(fd: pd.DataFrame, wp: pd.DataFrame, goal_diffs: pd.DataFrame) -> None:
    """Every Wikipedia row has a football-data team with the same record and the other way round,
    apart from the goal differences listed in the config."""
    bad = wp[wp["fd_team"].isna()]
    if len(bad):
        print(f"  Wikipedia rows with no football-data team of the same record: {len(bad)}")
        print(bad[["league", "season", "pos", "team", "pld", "w", "d", "l", "gf", "ga", "pts"]].to_string())
    seen = wp.dropna(subset=["fd_team"]).set_index(["league", "season", "fd_team"]).index
    extra = fd[~fd.set_index(["league", "season", "team"]).index.isin(seen)]
    if len(extra):
        print(f"  football-data teams with no Wikipedia row of the same record: {len(extra)}")
        print(extra.to_string())
    paired = wp.dropna(subset=["fd_team"]).merge(fd, left_on=["league", "season", "fd_team"],
                                                 right_on=["league", "season", "team"], suffixes=("", "_fd"))
    goals = paired[(paired["gf"] != paired["gf_fd"]) | (paired["ga"] != paired["ga_fd"])]
    print(f"Wikipedia v football-data: {len(paired)} of {len(wp)} rows paired; "
          f"{len(goals)} differ in goals only (listed in config goal_differences)")


def _check_deductions(wp: pd.DataFrame, ded: pd.DataFrame, errors: pd.DataFrame) -> None:
    """The config deductions, plus the known Wikipedia errors, add up to Wikipedia's points minus
    3·W + D, team by team."""
    errors = errors.assign(season=errors["season"].astype(str))
    got = pd.concat([ded, errors]).groupby(["league", "season", "team"])["points"].sum()
    want = wp[wp["adjustment"] != 0].set_index(["league", "season", "fd_team"])["adjustment"]
    want.index.names = got.index.names
    both = pd.concat([want.rename("wikipedia"), got.rename("config")], axis=1).fillna(0)
    diff = both[both["wikipedia"] != both["config"]]
    if len(diff):
        print("  Point deductions: Wikipedia and config/clubs.yaml (e1_stakes.deductions) differ:")
        print(diff.to_string())
    else:
        print(f"Point deductions: {len(ded)} config entries agree with Wikipedia ({len(errors)} Wikipedia errors set aside)")


def _check_final_points(results: pd.DataFrame, adj: pd.DataFrame, wp: pd.DataFrame, errors: pd.DataFrame) -> None:
    """The table built the same way on the day after the last match has, season by season, the
    points of the Wikipedia table (Wikipedia errors corrected)."""
    last = results.groupby(["league", "season"])["date"].max().reset_index()
    # one dummy fixture per season the day after its last match, to read the final table
    dummy = last.assign(date=last["date"] + pd.Timedelta(days=1), home="_dummy", away="_dummy2", hg=0, ag=0)
    end = standings_before(pd.concat([results, dummy], ignore_index=True), adj)
    end = end[end["team"] == "_dummy"]
    fix = errors.assign(season=errors["season"].astype(str)).rename(columns={"team": "fd_team", "points": "error"})
    w = wp.merge(fix[["league", "season", "fd_team", "error"]], how="left")
    w = (w["pts"] - w["error"].fillna(0)).set_axis(pd.MultiIndex.from_frame(w[["league", "season", "fd_team"]]))
    n_bad = 0
    for e in end.itertuples():
        built = list(e.table_pts)
        built.remove(0), built.remove(0)   # the two dummies
        want = sorted(w.loc[(e.league, e.season)].astype(int), reverse=True)
        if built != want:
            n_bad += 1
            print(f"  final points differ from Wikipedia: {e.league} {e.season}\n    wikipedia {want}\n    built     {built}")
    print(f"Final points: built tables match Wikipedia in {len(end) - n_bad} of {len(end)} league seasons")


if __name__ == "__main__":
    download_tables()
    build_e1()
