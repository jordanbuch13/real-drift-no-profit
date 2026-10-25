"""Step 1b: European and cup match expectations from Betfair BASIC historical data.

Two parts:
  download_basic()      authenticated pull of MATCH_ODDS files, searched by club name (needs credentials)
  build_betfair_expectations()  parse whatever files are in data/raw/betfair (downloaded
                         by the script OR extracted from a manual .tar download)

See docs/step1b_betfair.md.
"""
from __future__ import annotations

import bz2
import difflib
import io
import json
import os
import tarfile
import time
from pathlib import Path
from typing import Iterator, TextIO

import numpy as np
import pandas as pd

from .european_fixtures import RAW_OF, load_fixtures
from .wikipedia_fixtures import RAW_WP, kickoffs as wikipedia_kickoffs, load_fixtures as load_wikipedia
from .oddsportal import RAW_OP, club_match_links, league_kickoffs, load_oddsportal, missing_from_betfair, same_team
from .common import (CLUB_COLUMNS, PROCESSED, RAW_BF, ROOT, check_club_rows, implied_probabilities,
                     load_config, to_club_rows)

DRAW_NAMES = {"The Draw", "Draw"}
MAX_SNAPSHOT_AGE_MIN = 60  # warn if the last prematch trade is older than this
BASIC_FIRST_DAY = pd.Timestamp("2015-05-01")  # Betfair Basic soccer data starts here


# Download (needs BETFAIR_USERNAME, BETFAIR_PASSWORD, BETFAIR_APP_KEY in .env or the environment)

def search_terms(names: dict[str, str]) -> list[str]:
    """Betfair's event_name filter matches substrings, so drop aliases another alias already covers
    (e.g. "AS Roma" is covered by "Roma")."""
    aliases = sorted(names, key=len)
    return [a for i, a in enumerate(aliases) if not any(b.lower() in a.lower() for b in aliases[:i])]


def download_basic(start: str, end: str, raw_dir: Path = RAW_BF, retries: int = 3) -> None:
    """Download Soccer MATCH_ODDS BASIC files for the listed clubs, month by month.

    The file listing is searched by each club's Betfair name (a substring match), so every
    competition and every weekday is covered. Each file is opened and kept only if a team name
    exactly matches a configured alias (the search also returns e.g. "Man Utd (W)", "Romania").
    Files go to raw_dir/YYYY/MM/. Resumable: a marker per finished month, and files already on
    disk are not downloaded again.
    """
    import betfairlightweight  # imported here so parsing works without it installed
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")  # credentials stay out of the code; real env vars take precedence
    client = betfairlightweight.APIClient(os.environ["BETFAIR_USERNAME"],
                                          os.environ["BETFAIR_PASSWORD"],
                                          app_key=os.environ["BETFAIR_APP_KEY"])
    client.login_interactive()
    names = _betfair_name_map()
    terms = search_terms(names)
    done_dir = raw_dir / "_done"
    done_dir.mkdir(parents=True, exist_ok=True)
    on_disk = {p.name for p in raw_dir.rglob("*.bz2")}

    def call(fn, *args, **kwargs):
        for attempt in range(retries):
            try:
                return fn(*args, **kwargs)
            except Exception as e:  # network blips, expired session
                if attempt == retries - 1:
                    raise
                print(f"  retry after {type(e).__name__}: {str(e)[:120]}")
                time.sleep(5 * (attempt + 1))
                client.login_interactive()

    first, last = pd.Timestamp(start), pd.Timestamp(end)
    for month in pd.date_range(first.replace(day=1), last, freq="MS"):
        marker = done_dir / f"{month:%Y-%m}"
        if marker.exists():
            continue
        lo, hi = max(month, first), min(month + pd.offsets.MonthEnd(0), last)
        remote = set()
        for term in terms:
            remote |= set(call(client.historic.get_file_list, "Soccer", "Basic Plan",
                               from_day=lo.day, from_month=lo.month, from_year=lo.year,
                               to_day=hi.day, to_month=hi.month, to_year=hi.year, event_name=term,
                               market_types_collection=["MATCH_ODDS"], countries_collection=[],
                               file_type_collection=["M"]))
        month_dir = raw_dir / f"{month:%Y/%m}"
        month_dir.mkdir(parents=True, exist_ok=True)
        kept = skipped = 0
        for path in sorted(remote):
            if Path(path).name in on_disk:
                skipped += 1
                continue
            local = Path(call(client.historic.download_file, file_path=path, store_directory=str(month_dir)))
            with _open_text(local.read_bytes()) as fh:
                if _event_teams_from_stream(fh) & names.keys():
                    kept += 1
                    on_disk.add(local.name)
                else:
                    local.unlink()
        marker.touch()
        client.keep_alive()
        print(f"{month:%Y-%m}: {len(remote)} files matched the search, {kept} kept, {skipped} already on disk")


# Parsing

def _open_text(data: bytes) -> TextIO:
    if data[:3] == b"BZh":
        data = bz2.decompress(data)
    return io.TextIOWrapper(io.BytesIO(data), encoding="utf-8")


def iter_market_streams(raw_dir: Path = RAW_BF) -> Iterator[tuple[str, TextIO]]:
    """Yield (name, text stream) for every market file, including inside .tar archives."""
    for path in sorted(raw_dir.rglob("*")):
        if not path.is_file() or path.parent.name == "_done":
            continue
        if path.name.endswith(".tar"):
            with tarfile.open(path) as tf:
                for m in tf.getmembers():
                    if m.isfile() and m.name.endswith(".bz2"):
                        yield m.name, _open_text(tf.extractfile(m).read())
        elif path.suffix == ".bz2" or path.name.startswith("1."):
            yield str(path), _open_text(path.read_bytes())


def _split_event(event_name: str) -> tuple[str, str] | None:
    parts = event_name.split(" v ")
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else None


def _event_teams_from_stream(fh: TextIO) -> set[str]:
    for line in fh:
        for mc in json.loads(line).get("mc", []):
            md = mc.get("marketDefinition")
            if md and (teams := _split_event(md.get("eventName", ""))):
                return set(teams)
    return set()


def _runner_ids(home: str, away: str, runners: list[dict]) -> dict[str, int] | None:
    """Runner ids for H, D, A. Runner names do not always repeat the event name exactly
    ("Spal" in "Juventus v SPAL", "Qarabag FK" in "Celtic v Karabakh"), so names are matched
    ignoring case, and if one team is still unmatched it gets the one remaining non-draw runner.
    sortPriority is not used: it is not always home, away, draw."""
    draws = [r for r in runners if r["name"] in DRAW_NAMES]
    teams = [r for r in runners if r["name"] not in DRAW_NAMES]
    if len(draws) != 1 or len(teams) != 2:
        return None
    found = {side: [r for r in teams if r["name"].casefold() == name.casefold()]
             for side, name in (("H", home), ("A", away))}
    if len(found["H"]) > 1 or len(found["A"]) > 1:
        return None
    unmatched = [side for side, rs in found.items() if not rs]
    if len(unmatched) == 2:
        return None
    if unmatched:
        other = "A" if unmatched[0] == "H" else "H"
        found[unmatched[0]] = [r for r in teams if r is not found[other][0]]
    if found["H"][0] is found["A"][0]:
        return None
    return {"H": found["H"][0]["id"], "D": draws[0]["id"], "A": found["A"][0]["id"]}


def parse_market(fh: TextIO) -> dict | None:
    """Last traded prices just before kickoff, plus the settled result, for one MATCH_ODDS market."""
    md, market_id, kickoff_ms, ltp, snapshot, snapshot_pt = None, None, None, {}, None, None
    n_updates, went_in_play = 0, False
    for line in fh:
        msg = json.loads(line)
        pt = msg.get("pt")
        n_updates += 1
        for mc in msg.get("mc", []):
            if "marketDefinition" in mc:
                md, market_id = mc["marketDefinition"], mc["id"]
                kickoff_ms = pd.Timestamp(md["marketTime"]).value // 1_000_000
                went_in_play |= md.get("inPlay", False)
            if md is None:
                continue
            prematch = not md.get("inPlay", False) and pt < kickoff_ms
            if prematch:
                for rc in mc.get("rc", []):
                    if "ltp" in rc:
                        ltp[rc["id"]] = rc["ltp"]
                snapshot, snapshot_pt = dict(ltp), pt
    if md is None or md.get("marketType") != "MATCH_ODDS":
        return None
    teams = _split_event(md.get("eventName", ""))
    if teams is None:
        return None
    home, away = teams
    ids = _runner_ids(home, away, md["runners"])
    if ids is None:
        return None
    winner = [k for k, rid in ids.items()
              if next(r for r in md["runners"] if r["id"] == rid).get("status") == "WINNER"]
    kickoff = pd.Timestamp(md["marketTime"])
    snap = snapshot or {}
    return {
        "market_id": market_id, "event_id": md.get("eventId"), "event_name": md["eventName"],
        "home": home, "away": away, "kickoff_utc": kickoff,
        "odds_H": snap.get(ids["H"]), "odds_D": snap.get(ids["D"]), "odds_A": snap.get(ids["A"]),
        "minutes_before_kickoff": (None if snapshot_pt is None
                                   else (kickoff.value // 1_000_000 - snapshot_pt) / 60_000),
        "result_hda": winner[0] if len(winner) == 1 else None,
        "country_code": md.get("countryCode"),
        "n_updates": n_updates, "went_in_play": went_in_play,
    }


def _betfair_name_map() -> dict[str, str]:
    cfg = load_config()
    return {alias: row["club"] for _, row in cfg.clubs.iterrows() for alias in row["betfair_names"]}


def build_betfair_expectations(raw_dir: Path = RAW_BF, out_dir: Path = PROCESSED,
                               league_rows_path: Path | None = None,
                               method: str = "proportional", fixtures_dir: Path = RAW_OF,
                               oddsportal_dir: Path = RAW_OP, wikipedia_dir: Path = RAW_WP) -> pd.DataFrame:
    """Parse all Betfair files, keep listed clubs, add OddsPortal odds for matches Betfair lacks,
    label league / european / other, drop friendlies, write outputs."""
    names = _betfair_name_map()
    records, seen_teams = [], set()
    for _, fh in iter_market_streams(raw_dir):
        with fh:
            rec = parse_market(fh)
        if rec is None:
            continue
        seen_teams |= {rec["home"], rec["away"]}
        if rec["home"] in names or rec["away"] in names:
            records.append(rec)
    for club in sorted(set(names.values())):
        aliases = [a for a, c in names.items() if c == club]
        if not set(aliases) & seen_teams:
            close = {m for a in aliases for m in difflib.get_close_matches(a, seen_teams, n=3, cutoff=0.5)}
            print(f"WARNING no Betfair name for {club} found (tried {aliases}). "
                  f"Close matches: {sorted(close)}. Fix config/clubs.yaml.")
    if not records:
        raise RuntimeError(f"no markets with listed clubs found in {raw_dir}")

    m, dropped = _select_markets(pd.DataFrame(records))
    out_dir.mkdir(parents=True, exist_ok=True)
    dropped.to_csv(out_dir / "betfair_missing_odds.csv", index=False)
    print(f"Betfair markets dropped: {len(dropped)} (logged with reason to betfair_missing_odds.csv)")
    print(dropped["reason"].value_counts().to_string())

    stale = m[m["minutes_before_kickoff"] > MAX_SNAPSHOT_AGE_MIN]
    if not stale.empty:
        print(f"WARNING {len(stale)} markets whose last prematch trade is over "
              f"{MAX_SNAPSHOT_AGE_MIN} min before kickoff")

    m["match_id"] = "BF_" + m["market_id"].astype(str)
    m["source"] = "betfair"
    m["odds_source"] = "betfair_ltp_prematch"

    # Matches Betfair Basic lacks (mostly 2015/16 to 2017/18 Champions League): OddsPortal closing odds
    cfg = load_config()
    op_names = {a: row["club"] for _, row in cfg.clubs.iterrows() for a in row.get("oddsportal_names", [])}
    op = missing_from_betfair(load_oddsportal(op_names, cfg.oddsportal_results_90, oddsportal_dir),
                              op_names, m, names)
    listings = _competition_listings(oddsportal_dir / "links", cfg)
    if not op.empty:
        op = op.merge(listings.drop_duplicates("match_link")[["match_link", "competition"]], on="match_link", how="left")
        op["op_competition"] = op.pop("competition").fillna(op["op_competition"])
        op["match_id"] = "OP_" + op["match_link"].str.split("#").str[-1]
        op["source"] = "oddsportal"
        op["odds_source"] = "oddsportal_avg_closing"
        print(f"Added from OddsPortal (no Betfair market): {len(op)} matches, "
              f"{op['result_hda'].isna().sum()} without a 90 minute result")
        m = pd.concat([m, op], ignore_index=True)
        names = {**names, **op_names}

    m = pd.concat([m, implied_probabilities(m["odds_H"], m["odds_D"], m["odds_A"], method)], axis=1)
    m["date"] = m["kickoff_utc"].dt.tz_convert("Europe/London").dt.tz_localize(None).dt.normalize()
    m["kickoff_time"] = m["kickoff_utc"].dt.tz_convert("Europe/London").dt.strftime("%H:%M")
    m["home_goals"] = m["away_goals"] = pd.NA  # BASIC data has no score; OddsPortal's includes extra time
    m["season"] = m["date"].apply(_season_of)
    m["league"] = None

    of_names = {a: row["club"] for _, row in cfg.clubs.iterrows() for a in row.get("openfootball_names", [])}
    fixtures = load_fixtures(of_names, fixtures_dir)
    league_path = league_rows_path or out_dir / "match_expectations.csv"
    rows = to_club_rows(m, names)
    rows = _label_competition(rows, league_path, fixtures)
    rows = _name_from_listings(rows, listings)
    wiki_raw = load_wikipedia(wikipedia_dir)
    wiki = _wikipedia_matches(wiki_raw, cfg)
    rows = _apply_wikipedia(rows, wiki, out_dir)
    rows, friendlies = _drop_friendlies(rows, league_path, cfg.friendly_filter, cfg.super_cups,
                                        dict(zip(cfg.clubs["club"], cfg.clubs["league"])))
    rows["competition"] = rows["competition"].replace(cfg.competition_names)  # super cup keys -> names
    friendlies.to_csv(out_dir / "betfair_excluded_friendlies.csv", index=False)
    print(f"\nBetfair club rows excluded as friendlies: {len(friendlies)} (betfair_excluded_friendlies.csv)")
    if not friendlies.empty:
        print(friendlies["reason"].value_counts().to_string())
    print("\nBetfair club rows kept by competition type:")
    print(rows["competition_type"].value_counts().to_string())
    check_club_rows(rows, "step1b")
    rows.to_csv(out_dir / "betfair_expectations.csv", index=False)
    _european_coverage(rows, fixtures)
    coverage = _coverage(rows, out_dir / "match_expectations.csv")
    if coverage is not None:
        coverage.to_csv(out_dir / "betfair_coverage.csv", index=False)

    ids = {str(r["oddsportal_id"]): r["club"] for _, r in cfg.clubs.iterrows()}
    op_times = league_kickoffs(oddsportal_dir / "league_kickoffs", ids)
    combined = _combine(rows, out_dir / "match_expectations.csv", cfg.league_names, op_times,
                        wikipedia_kickoffs(wiki_raw))
    if combined is not None:
        combined.to_csv(out_dir / "match_expectations_all.csv", index=False)
    return rows


def _select_markets(m: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One usable MATCH_ODDS market per event. Returns (kept, dropped with reason).

    Real BASIC files often hold two MATCH_ODDS markets per event: a main one with hundreds of
    updates and a thin one with a few dozen and stale or missing prices. Keep the market with
    complete prematch prices and the most updates. Markets that never went in play are
    postponed or abandoned matches and are not events.
    """
    m = m.copy()
    m["complete"] = m[["odds_H", "odds_D", "odds_A"]].notna().all(axis=1)
    not_played = m[~m["went_in_play"]].assign(reason="never went in play (postponed or abandoned)")
    m = m[m["went_in_play"]].sort_values(["event_id", "complete", "n_updates"], ascending=[True, False, False])
    dup = m.duplicated("event_id", keep="first")
    duplicates = m[dup].assign(reason="second market for the same event (fewer updates)")
    m = m[~dup]
    incomplete = m[~m["complete"]].assign(reason="no prematch trade on every runner")
    kept = m[m["complete"]].drop(columns="complete").reset_index(drop=True)
    dropped = pd.concat([not_played, duplicates, incomplete]).drop(columns="complete")
    return kept, dropped.reset_index(drop=True)


def _competition_listings(links_dir: Path, cfg) -> pd.DataFrame:
    """The listed clubs' matches in the OddsPortal competition link lists: one row per club and
    match, with club, date (match day), match_link and competition (display name from the config)."""
    ids = {str(r["oddsportal_id"]): r["club"] for _, r in cfg.clubs.iterrows() if pd.notna(r.get("oddsportal_id"))}
    # The 2015/16 to 2018/19 Champions League lists from the first gap fill sit one level up
    links = club_match_links(links_dir, ids, sorted(links_dir.parent.glob("cl_links_*.csv")))
    links = links.assign(club=links["clubs"].str.split(", ")).explode("club")
    club_ids = {c: i for i, c in ids.items()}
    # Opponent from the link: the team slug without the club's id ("sv-sandhausen-xxxx" -> "sv sandhausen")
    slugs = links["match_link"].str.extract(r"/h2h/([^/]+)/([^/]+)/")
    own = [slug_a.endswith("-" + club_ids[c]) for slug_a, c in zip(slugs[0], links["club"])]
    other = slugs[1].where(own, slugs[0])
    links["opponent"] = other.str.rsplit("-", n=1).str[0].str.replace("-", " ")
    links["competition"] = links["league"].map(cfg.competition_names)
    unknown = sorted(links.loc[links["competition"].isna(), "league"].unique())
    if unknown:
        raise ValueError(f"no competition_names entry in config/clubs.yaml for {unknown}")
    links["date"] = pd.to_datetime(links["match_day"])
    return links[["club", "date", "opponent", "match_link", "competition"]].reset_index(drop=True)


def _wikipedia_matches(wp: pd.DataFrame, cfg) -> pd.DataFrame:
    """Wikipedia club season matches as club, date, opponent, competition (display name, None when
    the heading is not a known competition), friendly, league (True for league sections)."""
    if wp.empty:
        return pd.DataFrame(columns=["club", "date", "opponent", "competition", "friendly", "league"])
    wp = wp.dropna(subset=["date"]).copy()
    wp["date"] = pd.to_datetime(wp["date"])
    aliases = {}
    for _, r in cfg.clubs.iterrows():
        names = {r["club"], r["football_data_name"], r["wikipedia_name"], *r["betfair_names"],
                 *(r.get("oddsportal_names") or [])}
        aliases[r["club"]] = {n for n in names if isinstance(n, str)}
    def opponent(r):
        if r["team1"] == "(club)":
            return r["team2"]
        own1 = any(same_team(r["team1"], a) for a in aliases[r["club"]])
        own2 = any(same_team(r["team2"], a) for a in aliases[r["club"]])
        return r["team2"] if own1 and not own2 else r["team1"] if own2 and not own1 else None
    wp["opponent"] = wp.apply(opponent, axis=1)
    league_names = set(cfg.league_names.values()) | {"Süper Lig", "Scottish Premier League"}
    wp["league"] = wp["section"].isin(league_names)
    wp["competition"] = wp["section"].map(cfg.competition_names)
    return wp[["club", "date", "opponent", "competition", "friendly", "league", "article"]].reset_index(drop=True)


def _apply_wikipedia(rows: pd.DataFrame, wiki: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    """Use the Wikipedia club season articles on the non-league rows. A row matches a Wikipedia
    match of the same club on the same day, or one day either side against the same opponent.
    - listed as a friendly: wp_friendly = True (dropped by the friendly filter)
    - listed under a competition: competitive (wp_competitive = True, skips the date rules), and
      named from it when still unnamed; a different name from OddsPortal is logged, the
      OddsPortal (or fixture list) name is kept
    Writes wikipedia_name_conflicts.csv and wikipedia_missing_matches.csv (competitive non-league
    Wikipedia matches with no row here, from May 2015 or any OddsPortal season)."""
    rows = rows.copy()
    rows["wp_friendly"] = False
    rows["wp_competitive"] = False
    if wiki.empty:
        return rows
    by_club = {c: g for c, g in wiki.groupby("club")}
    conflicts, used = [], set()
    for i in rows.index[rows["competition_type"] != "league"]:
        g = by_club.get(rows.at[i, "club"])
        if g is None:
            continue
        gap = (g["date"] - rows.at[i, "date"]).abs()
        opp = rows.at[i, "opponent"]
        same_opp = pd.Series([isinstance(o, str) and same_team(opp, o) for o in g["opponent"]], index=g.index)
        hit = g[((gap == pd.Timedelta(0)) | ((gap <= pd.Timedelta(days=1)) & same_opp)) & ~g["league"]]
        if hit.empty:
            continue
        best = hit.loc[(gap[hit.index] - pd.to_timedelta(same_opp[hit.index].astype(int), unit="D")).idxmin()]
        used.add(best.name)
        if best["friendly"]:
            rows.at[i, "wp_friendly"] = True
            continue
        rows.at[i, "wp_competitive"] = True
        name, current = best["competition"], rows.at[i, "competition"]
        if pd.isna(current) and isinstance(name, str):
            rows.at[i, "competition"] = name
        elif isinstance(name, str) and isinstance(current, str) and not current.startswith(name) \
                and not current.startswith("two-legged"):  # "Champions League qualifying" agrees
            conflicts.append({"club": rows.at[i, "club"], "date": rows.at[i, "date"], "opponent": opp,
                              "competition": current, "wikipedia": name, "article": best["article"]})
    euro = (rows["competition_type"] == "other") & rows["competition"].isin(EUROPEAN_OP_NAMES)
    rows.loc[euro, "competition_type"] = "european"
    pd.DataFrame(conflicts).to_csv(out_dir / "wikipedia_name_conflicts.csv", index=False)
    start = min(pd.Timestamp("2015-05-01"), rows["date"].min())
    missing = wiki[~wiki.index.isin(used) & ~wiki["friendly"] & ~wiki["league"] & (wiki["date"] >= start)]
    missing.to_csv(out_dir / "wikipedia_missing_matches.csv", index=False)
    print(f"Wikipedia: {rows['wp_competitive'].sum()} non-league rows confirmed competitive, "
          f"{rows['wp_friendly'].sum()} listed as friendlies, {len(conflicts)} name conflicts "
          f"(wikipedia_name_conflicts.csv), {len(missing)} competitive matches with no row "
          f"(wikipedia_missing_matches.csv)")
    return rows


def _name_from_listings(rows: pd.DataFrame, listings: pd.DataFrame) -> pd.DataFrame:
    """Name unnamed 'other' rows from the OddsPortal competition listings: the same club plays a
    listed match on the same day, or one day either side against the same opponent (kickoffs near
    midnight; a friendly the day after a super cup, Dortmund v Sandhausen 15/08/2016, must not take
    its name). Named rows are competitive and skip the friendly filter. European names make the row
    european."""
    rows = rows.copy()
    todo = rows.index[(rows["competition_type"] == "other") & rows["competition"].isna()]
    if listings.empty or todo.empty:
        return rows
    by_club = {c: g for c, g in listings.groupby("club")}
    named = 0
    for i in todo:
        g = by_club.get(rows.at[i, "club"])
        if g is None:
            continue
        gap = (g["date"] - rows.at[i, "date"]).abs()
        opp = rows.at[i, "opponent"]
        same_opp = pd.Series([same_team(opp, o) for o in g["opponent"]], index=g.index)
        hit = g[(gap == pd.Timedelta(0)) | ((gap <= pd.Timedelta(days=1)) & same_opp)]
        if hit.empty:
            continue
        rows.at[i, "competition"] = hit.loc[gap[hit.index].idxmin(), "competition"]
        named += 1
    euro = rows.index.isin(todo) & rows["competition"].isin(EUROPEAN_OP_NAMES)
    rows.loc[euro, "competition_type"] = "european"
    print(f"Named from OddsPortal competition listings: {named} of {len(todo)} unnamed other rows "
          f"({euro.sum()} European)")
    return rows


# OddsPortal competition names that are UEFA club competitions
EUROPEAN_OP_NAMES = ["Champions League", "Europa League", "Conference League", "UEFA Super Cup"]


def _season_of(d: pd.Timestamp) -> str:
    y = d.year if d.month >= 7 else d.year - 1
    return f"{y % 100:02d}{(y + 1) % 100:02d}"


def _label_competition(bf: pd.DataFrame, league_path: Path, fixtures: pd.DataFrame) -> pd.DataFrame:
    """Label each Betfair club row:
      league    Step 1 has the same club playing within one day
      european  in the openfootball European fixture list within one day (competition column says which)
      other     anything else: domestic cups, European matches missing from the fixture list, friendlies
    Also prints how closely Betfair and bookmaker probabilities agree on shared league matches."""
    bf = bf.sort_values("date").copy()
    if not league_path.exists():
        print("WARNING Step 1 output missing, cannot separate league from non league matches")
        bf["competition_type"] = bf["competition"] = "unknown"
        return bf
    lg = pd.read_csv(league_path, parse_dates=["date"], dtype={"season": str})[["club", "date", "p_win", "season"]]
    bf = pd.merge_asof(bf, lg.sort_values("date").rename(
        columns={"date": "league_date", "p_win": "league_p_win", "season": "league_season"}),
                       left_on="date", right_on="league_date", by="club",
                       direction="nearest", tolerance=pd.Timedelta(days=1))
    fx = fixtures.rename(columns={"date": "euro_date", "competition": "euro_competition"})[
        ["club", "euro_date", "euro_competition"]].sort_values("euro_date")
    bf = pd.merge_asof(bf, fx, left_on="date", right_on="euro_date", by="club",
                       direction="nearest", tolerance=pd.Timedelta(days=1))
    # One Betfair row per league or European match: a side friendly on the same evening
    # (e.g. Ajax v VVSB next to Fortuna Sittard v Ajax, 21/09/2021) must not inherit the label.
    # A market with a result beats one without: an abandoned match and its replay a day later
    # (Nacional v Benfica, abandoned 10/01/2016, replayed 11/01/2016) are both within a day of Step 1's date.
    bf["_no_result"] = bf["result"].isna()
    bf["_lg_fit"] = (bf["p_win"] - bf["league_p_win"]).abs()
    bf["_eu_fit"] = (bf["date"] - bf["euro_date"]).abs()
    for key, fit, cols in [("league_date", "_lg_fit", ["league_date", "league_p_win", "league_season"]),
                           ("euro_date", "_eu_fit", ["euro_date", "euro_competition"])]:
        matched = bf[bf[key].notna()].sort_values(["_no_result", fit])
        losers = matched.index[matched.duplicated(["club", key], keep="first")]
        bf.loc[losers, cols] = None
    bf = bf.drop(columns=["_no_result", "_lg_fit", "_eu_fit"])
    bf["competition_type"] = "other"
    bf.loc[bf["euro_date"].notna(), "competition_type"] = "european"
    bf.loc[bf["league_date"].notna(), "competition_type"] = "league"
    # Seasons by calendar (July cut) are wrong for e.g. the July 2020 Covid restart; use Step 1's
    bf["season"] = bf["league_season"].where(bf["league_season"].notna(), bf["season"])
    bf["competition"] = bf["euro_competition"].where(bf["competition_type"] == "european",
                                                     bf["competition_type"].map({"league": "league"}))
    # OddsPortal rows come from competition listings, so they name their competition. European
    # competitions missing from the fixture list (Europa League before 2020/21, qualifiers) become
    # european; cups and super cups stay other, named.
    if "op_competition" in bf:
        named = bf["op_competition"].notna() & (bf["competition_type"] == "other")
        euro = named & bf["op_competition"].str.contains("|".join(EUROPEAN_OP_NAMES), regex=True, na=False)
        bf.loc[euro, "competition_type"] = "european"
        bf.loc[named, "competition"] = bf.loc[named, "op_competition"]
        bf = bf.drop(columns="op_competition")
    shared = bf[bf["competition_type"] == "league"]
    if len(shared) > 10:
        print(f"Cross check on {len(shared)} shared league matches: corr(p_win betfair, bookmaker) = "
              f"{shared['p_win'].corr(shared['league_p_win']):.3f}, "
              f"mean abs diff = {(shared['p_win'] - shared['league_p_win']).abs().mean():.3f}")
    return bf.drop(columns=["league_date", "league_p_win", "league_season", "euro_date",
                            "euro_competition"]).reset_index(drop=True)


def _drop_friendlies(rows: pd.DataFrame, league_path: Path, rule: dict, super_cups: pd.DataFrame | None = None,
                     club_league: dict[str, str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Remove 'other' rows that are probably friendlies. Returns (kept, dropped with reason).

    1. Off-season: from off_season_buffer_days after the club's last Step 1 league match of a
       season to its first league match of the next season. The buffer keeps cup finals played
       just after the league ends (e.g. the July 2020 Covid-delayed finals).
    2. Winter break: inside a gap of at least winter_break_min_days between the club's league
       matches that overlaps 15 December to 15 February.
    Clubs in date_rule_exempt, and dates in date_rule_exempt_periods (e.g. the 2025 Club World
    Cup), skip 1 and 2.
    Kept despite 2: matches against a team from the club's own league, outside the leagues in
    winter_camp_friendly_leagues (they are cup ties).
    Kept despite 1 and 2: domestic super cups (exact date of a configured super cup of the
    club's league, against a team the club also meets in the league) and two-legged ties.
    3. Two matches on the same day: keep the league or European one; if neither is, drop both.
    """
    rows = rows.copy()
    rows["reason"] = None
    exempt = {e["club"] for e in rule.get("date_rule_exempt", [])}
    # Rows already named (OddsPortal cup and super cup listings) are competitive by source
    wp_comp = rows["wp_competitive"] if "wp_competitive" in rows else False
    other = (rows["competition_type"] == "other") & rows["competition"].isna() & ~rows["club"].isin(exempt) & ~wp_comp
    for period in rule.get("date_rule_exempt_periods", []):
        other &= ~rows["date"].between(pd.Timestamp(period["from"]), pd.Timestamp(period["to"]))
    if league_path.exists():
        lg = pd.read_csv(league_path, parse_dates=["date"], dtype={"season": str})[["club", "season", "date"]]
        lg = lg.sort_values(["club", "date"])
        lg["next"] = lg.groupby("club")["date"].shift(-1)
        lg["next_season"] = lg.groupby("club")["season"].shift(-1)
        buffer = pd.Timedelta(days=rule.get("off_season_buffer_days", 14))
        min_gap = pd.Timedelta(days=rule.get("winter_break_min_days", 18))
        for _, g in lg[lg["next"].notna()].iterrows():
            if g["next_season"] != g["season"]:
                start, reason = g["date"] + buffer, "friendly: off-season (before first league match)"
            elif g["next"] - g["date"] >= min_gap and g["date"] <= pd.Timestamp(g["next"].year, 2, 15) \
                    and g["next"] >= pd.Timestamp(g["next"].year - 1, 12, 15):
                start, reason = g["date"], "friendly: winter break"
            else:
                continue  # normal week, or a long gap outside winter such as the 2020 Covid stoppage
            inside = other & (rows["club"] == g["club"]) & (rows["date"] > start) & (rows["date"] < g["next"])
            rows.loc[inside & rows["reason"].isna(), "reason"] = reason
        # Before the club's first league match in the data (start of the Betfair period)
        first = lg.groupby("club")["date"].min()
        pre = other & (rows["date"] < rows["club"].map(first)) & rows["reason"].isna()
        rows.loc[pre, "reason"] = "friendly: off-season (before first league match)"

    domestic = rows[rows["competition_type"] == "league"].groupby("club")["opponent"].apply(set)
    vs_domestic = pd.Series([op in domestic.get(c, set()) for c, op in zip(rows["club"], rows["opponent"])],
                            index=rows.index)
    if club_league:
        # Winter-break matches against a team from the club's own league are cup ties (Portugal,
        # Turkey, France, Italy and England have no real winter break; cup rounds create the gap),
        # except in leagues whose clubs play domestic sides at winter camps (Germany, Netherlands).
        camp = set(rule.get("winter_camp_friendly_leagues", []))
        cup = (rows["reason"] == "friendly: winter break") & vs_domestic & ~rows["club"].map(club_league).isin(camp)
        rows.loc[cup, "reason"] = None
        rows.loc[cup, "competition"] = "domestic cup (inferred: winter, league opponent)"

    if super_cups is not None and not super_cups.empty and club_league:
        for _, cup in super_cups.iterrows():
            # Also names super cups played mid-season, which the date rule never flagged
            hit = ((rows["competition_type"] == "other") & (rows["club"].map(club_league) == cup["league"])
                   & (rows["date"] == cup["date"])  # exact: cup rounds sit a day either side in January
                   & ~rows["club"].isin(cup.get("exclude_clubs") or set()))
            hit &= vs_domestic
            rows.loc[hit, "reason"] = None
            rows.loc[hit, "competition"] = cup["cup"]

    # Two-legged ties are competitive (European qualifiers missing from the fixture list):
    # the same opponent at home and away within two_leg_max_days. Friendlies are almost never.
    # The other leg may be flagged too, or already named (an OddsPortal European listing); a flagged
    # leg of a named tie takes the other leg's competition (Ajax v Nice, 2017 CL qualifier).
    flagged = rows[rows["reason"].notna()]
    partners = rows[(rows["competition_type"] != "league") & (rows["reason"].notna() | rows["competition"].notna())]
    legs = flagged.reset_index().merge(partners, on=["club", "opponent"], suffixes=("", "_other"))
    max_days = pd.Timedelta(days=rule.get("two_leg_max_days", 14))
    tie = legs[(legs["venue"] != legs["venue_other"]) & ((legs["date"] - legs["date_other"]).abs() <= max_days)]
    tie = tie.sort_values("competition_other", na_position="last").drop_duplicates("index").set_index("index")
    named = tie["competition_other"].notna() & tie["reason_other"].isna()
    rows.loc[tie.index, "reason"] = None
    rows.loc[tie.index, "competition"] = "two-legged tie (probably European qualifying)"
    rows.loc[tie.index[named], "competition"] = tie.loc[named, "competition_other"]
    rows.loc[tie.index[named], "competition_type"] = tie.loc[named, "competition_type_other"]

    # Same-day pairs: league, then European, then a named match (super cup, two-legged tie)
    rank = rows["competition_type"].map({"league": 0, "european": 1}).fillna(
        rows["competition"].notna().map({True: 1.5, False: 2}))
    live = rows[rows["reason"].isna()].assign(rank=rank)
    same_day = live[live.duplicated(["club", "date"], keep=False)]
    for _, grp in same_day.groupby(["club", "date"]):
        best = grp["rank"].min()
        drop = grp.index if best == 2 else grp.index[grp["rank"] > best]
        rows.loc[drop, "reason"] = "friendly: second match on the same day"

    # Listed as a friendly on Wikipedia: dropped whatever the date rules said (e.g. Celtic's
    # pre-season matches, exempt from the date rules because of early qualifiers)
    if "wp_friendly" in rows:
        rows.loc[rows["wp_friendly"] & (rows["competition_type"] != "league"), "reason"] = \
            "friendly: listed as a friendly on Wikipedia"
    dropped = rows[rows["reason"].notna()].reset_index(drop=True)
    return rows[rows["reason"].isna()].drop(columns="reason").reset_index(drop=True), dropped


def _european_coverage(rows: pd.DataFrame, fixtures: pd.DataFrame) -> None:
    """How many fixture-list European matches of the listed clubs Betfair Basic has."""
    if fixtures.empty:
        return
    fx = fixtures[(fixtures["date"] >= BASIC_FIRST_DAY) & (fixtures["date"] <= rows["date"].max())].copy()
    fx["season"] = fx["date"].apply(_season_of)
    eu = rows[rows["competition_type"] == "european"]
    for col, sub in [("in_betfair", eu[eu["source"] == "betfair"]), ("with_oddsportal", eu)]:
        fx[col] = [((sub["club"] == c) & ((sub["date"] - d).abs() <= pd.Timedelta(days=1))).any()
                   for c, d in zip(fx["club"], fx["date"])]
    t = fx.groupby(["season", "competition"]).agg(
        fixtures=("in_betfair", "size"), in_betfair=("in_betfair", "sum"), with_oddsportal=("with_oddsportal", "sum"))
    t["coverage"] = (t["in_betfair"] / t["fixtures"]).round(3)
    t["coverage_with_oddsportal"] = (t["with_oddsportal"] / t["fixtures"]).round(3)
    print("\nBetfair coverage of European fixtures (openfootball list), and with OddsPortal gap fill:")
    print(t.to_string())


def _coverage(bf: pd.DataFrame, league_path: Path) -> pd.DataFrame | None:
    """Share of Step 1 league matches that Betfair also has, per club and season.

    Every league match is known from Step 1, so this measures how complete the Basic data is.
    Non league matches have no such reference list; their counts are shown alongside.
    """
    if not league_path.exists():
        return None
    lg = pd.read_csv(league_path, parse_dates=["date"], dtype={"season": str})
    lg = lg[(lg["date"] >= BASIC_FIRST_DAY) & (lg["date"] <= bf["date"].max())]
    t = pd.DataFrame({
        "league_matches": lg.groupby(["club", "season"]).size(),
        "betfair_league": bf[bf["competition_type"] == "league"].groupby(["club", "season"]).size(),
        "betfair_european": bf[bf["competition_type"] == "european"].groupby(["club", "season"]).size(),
        "betfair_other": bf[bf["competition_type"] == "other"].groupby(["club", "season"]).size(),
    }).fillna(0).astype(int).reset_index()
    t["league_coverage"] = (t["betfair_league"] / t["league_matches"].where(t["league_matches"] > 0)).round(3)
    by_season = t.groupby("season")[["league_matches", "betfair_league", "betfair_european", "betfair_other"]].sum()
    by_season["league_coverage"] = (by_season["betfair_league"] / by_season["league_matches"]).round(3)
    print("\nBetfair coverage of Step 1 league matches, by season (per club in betfair_coverage.csv):")
    print(by_season.to_string())
    return t


def _combine(bf: pd.DataFrame, league_path: Path, league_names: dict[str, str],
             op_times: pd.DataFrame | None = None, wp_times: pd.DataFrame | None = None) -> pd.DataFrame | None:
    """League rows from Step 1 plus Betfair non league rows: the full event set, with a competition
    column (league name for league rows, the Step 1b label for the rest, empty if unknown)."""
    if not league_path.exists():
        return None
    lg = pd.read_csv(league_path, parse_dates=["date"])
    lg = _fill_kickoff_times(lg, bf, op_times, wp_times)
    lg["competition"] = lg["league"].map(league_names)
    if lg["competition"].isna().any():
        missing = sorted(lg.loc[lg["competition"].isna(), "league"].unique())
        raise ValueError(f"no league_names entry in config/clubs.yaml for {missing}")
    extra = bf[bf["competition_type"] != "league"][CLUB_COLUMNS + ["competition"]].assign(kickoff_source="betfair")
    extra.loc[extra["source"] == "oddsportal", "kickoff_source"] = "oddsportal"
    out = pd.concat([lg, extra], ignore_index=True).sort_values(["date", "club"]).reset_index(drop=True)
    dup = out[out.duplicated(["club", "date"], keep=False)]
    if not dup.empty:
        raise ValueError(f"duplicate (club, date) in the combined file:\n{dup[['match_id', 'club', 'date']]}")
    return out


def _fill_kickoff_times(lg: pd.DataFrame, bf: pd.DataFrame, op_times: pd.DataFrame | None = None,
                        wp_times: pd.DataFrame | None = None) -> pd.DataFrame:
    """Football Data has kickoff times only from 2019/20. Earlier league rows take the time of the
    Betfair market for the same club on the same date (both UK time; Betfair's is the actual off,
    usually within a few minutes of the scheduled time), then the OddsPortal match page time
    (2012/13 to 2014/15, before Betfair), then as a last resort the Wikipedia club season article
    (volunteer edited: within 15 minutes of the other sources on 92% of matches). kickoff_source says where each time came from; weekday
    rows still without a time are marked assumed_evening (midweek league matches are evening
    matches, after European markets close), weekend rows none. See docs/step1b_betfair.md."""
    lg = lg.copy()
    lg["kickoff_source"] = np.where(lg["kickoff_time"].notna(), "football_data", None)
    sources = [("betfair", bf[bf["competition_type"] == "league"])]
    if op_times is not None and not op_times.empty:
        sources.append(("oddsportal", op_times))
    if wp_times is not None and not wp_times.empty:
        sources.append(("wikipedia", wp_times))
    fill = pd.Series(False, index=lg.index)
    for name, src in sources:
        times = src.drop_duplicates(["club", "date"]).set_index(["club", "date"])["kickoff_time"]
        found = pd.Series(list(zip(lg["club"], lg["date"])), index=lg.index).map(times)
        new = lg["kickoff_time"].isna() & found.notna()
        lg.loc[new, "kickoff_time"] = found[new]
        lg.loc[new, "kickoff_source"] = name
        fill |= new
    still = lg["kickoff_time"].isna()
    weekday = lg["date"].dt.dayofweek < 5
    lg.loc[still & weekday, "kickoff_source"] = "assumed_evening"
    lg.loc[still & ~weekday, "kickoff_source"] = "none"
    print(f"\nLeague kickoff times: {fill.sum()} filled from Betfair, OddsPortal and Wikipedia; source counts:")
    print(lg["kickoff_source"].value_counts().to_string())
    return lg
