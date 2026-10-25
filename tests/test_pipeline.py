"""Offline tests on synthetic data. Run: python -m pytest tests  (or python tests/test_pipeline.py)."""
import bz2
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.common import implied_probabilities  # noqa: E402
from src.step1_expectations import build_match_expectations, drop_excluded, select_odds  # noqa: E402
from src.european_fixtures import parse_file  # noqa: E402
from src.oddsportal import load_oddsportal, missing_from_betfair, result_90  # noqa: E402
from src.step3_prices import apply_corporate_actions, event_day, match_end_utc  # noqa: E402
from src.wikipedia_fixtures import kickoff_uk, parse_article  # noqa: E402
from src.step4_event_study import Fit, corwin_schultz, match_week_fit, dimson_beta, expanding_terciles, holm, lag_matrix, wald_p  # noqa: E402
from src.league_tables import apply_awarded, awarded_adjustments, gap_to_place, parse_table, season_places, standings_before, stakes  # noqa: E402
from src.step2_surprise import add_congestion, add_surprise, add_terciles, build_match_surprise  # noqa: E402
from src.step1b_betfair import _drop_friendlies, _fill_kickoff_times, _label_competition, _name_from_listings, _select_markets, build_betfair_expectations, parse_market, search_terms  # noqa: E402


def test_proportional_and_power_sum_to_one():
    for method in ("proportional", "power"):
        p = implied_probabilities([1.5, 3.0], [4.2, 3.3], [7.0, 2.5], method)
        assert np.allclose(p[["p_H", "p_D", "p_A"]].sum(axis=1), 1)
        assert (p["overround"] > 1).all()


def test_power_shifts_margin_to_longshot():
    prop = implied_probabilities([1.3], [5.5], [11.0], "proportional")
    power = implied_probabilities([1.3], [5.5], [11.0], "power")
    assert power["p_H"][0] > prop["p_H"][0] and power["p_A"][0] < prop["p_A"][0]


def test_select_odds_priority():
    df = pd.DataFrame({"PSCH": [2.0, None], "PSCD": [3.4, None], "PSCA": [4.0, None],
                       "AvgH": [1.9, 2.1], "AvgD": [3.3, 3.2], "AvgA": [4.1, 3.6]})
    out = select_odds(df)
    assert list(out["odds_source"]) == ["pinnacle_closing", "average_prematch"]
    assert out.loc[1, "odds_H"] == 2.1


def test_select_odds_skips_overround_below_one():
    # Real case: Celtic v Hearts 16/05/2026, one bookmaker's 251.00 inflated the closing average.
    df = pd.DataFrame({"AvgCH": [1.55], "AvgCD": [4.98], "AvgCA": [20.28],
                       "AvgH": [1.56], "AvgD": [4.20], "AvgA": [5.01]})
    out = select_odds(df)
    assert out.loc[0, "odds_source"] == "average_prematch"
    assert out.loc[0, "odds_A"] == 5.01


def test_select_odds_ignores_pinnacle_after_api_closure():
    df = pd.DataFrame({"date": pd.to_datetime(["2025-07-22", "2025-07-23"]),
                       "PSCH": [2.0, 2.0], "PSCD": [3.4, 3.4], "PSCA": [4.0, 4.0],
                       "AvgCH": [1.9, 1.9], "AvgCD": [3.3, 3.3], "AvgCA": [4.1, 4.1]})
    assert list(select_odds(df)["odds_source"]) == ["pinnacle_closing", "average_closing"]


def test_drop_excluded_removes_forfeit_and_fails_if_missing():
    matches = pd.DataFrame({"league": ["T1", "T1"], "season": ["2223", "2223"],
                            "date": pd.to_datetime(["2023-04-19", "2023-04-20"]),
                            "HomeTeam": ["Besiktas", "Besiktas"], "AwayTeam": ["Hatayspor", "Konyaspor"]})
    ex = pd.DataFrame([{"league": "T1", "season": "2223", "date": "19/04/2023",
                        "home": "Besiktas", "away": "Hatayspor", "reason": "forfeit"}])
    kept, dropped = drop_excluded(matches, ex)
    assert list(kept["AwayTeam"]) == ["Konyaspor"] and list(dropped["reason"]) == ["forfeit"]
    try:
        drop_excluded(matches, ex.assign(date="18/04/2023"))
    except AssertionError:
        pass
    else:
        raise AssertionError("a configured exclusion that is not in the data must fail")


FD_CSV = """Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,PSCH,PSCD,PSCA,AvgH,AvgD,AvgA
I1,25/08/12,19:45,Juventus,Lazio,2,0,H,1.60,4.00,6.50,1.58,3.90,6.20
I1,01/09/12,17:00,Roma,Juventus,1,1,D,,,,2.90,3.30,2.50
I1,15/09/12,17:00,Bologna,Lazio,0,1,A,2.10,3.30,3.80,2.05,3.25,3.70
I1,16/09/12,17:00,Bologna,Inter,0,1,A,2.10,3.30,3.80,2.05,3.25,3.70
"""

OF_TXT = """= UEFA Champions League 2012/13

\u25aa Group E
  Tue Oct 2 2012
    20:45  Juventus (ITA)          v Manchester United (ENG)  0-1
"""


def _market_stream(market_id, event, home, away, kickoff, ltps, winner):
    ids = {home: 1, "The Draw": 2, away: 3}
    k = pd.Timestamp(kickoff)
    pt = lambda minutes: int((k + pd.Timedelta(minutes=minutes)).value // 1_000_000)  # noqa: E731
    md = {"eventId": "E" + market_id, "eventName": event, "marketType": "MATCH_ODDS",
          "marketTime": kickoff, "inPlay": False, "status": "OPEN",
          "runners": [{"id": i, "name": n, "status": "ACTIVE"} for n, i in ids.items()]}
    lines = [{"op": "mcm", "pt": pt(-600), "mc": [{"id": market_id, "marketDefinition": md}]}]
    lines.append({"op": "mcm", "pt": pt(-120), "mc": [{"id": market_id, "rc": [
        {"id": ids[n], "ltp": o * 1.1} for n, o in ltps.items()]}]})
    lines.append({"op": "mcm", "pt": pt(-2), "mc": [{"id": market_id, "rc": [
        {"id": ids[n], "ltp": o} for n, o in ltps.items()]}]})
    inplay = dict(md, inPlay=True)
    lines.append({"op": "mcm", "pt": pt(1), "mc": [{"id": market_id, "marketDefinition": inplay,
                                                     "rc": [{"id": ids[home], "ltp": 1.01}]}]})
    settled = dict(md, inPlay=True, status="CLOSED", runners=[
        {"id": i, "name": n, "status": "WINNER" if n == winner else "LOSER"} for n, i in ids.items()])
    lines.append({"op": "mcm", "pt": pt(120), "mc": [{"id": market_id, "marketDefinition": settled}]})
    return "\n".join(json.dumps(x) for x in lines)


def test_parse_market_takes_last_prematch_price():
    import io
    text = _market_stream("1.1", "Juventus v Man Utd", "Juventus", "Man Utd",
                          "2012-10-02T18:45:00.000Z",
                          {"Juventus": 2.2, "The Draw": 3.4, "Man Utd": 3.5}, "Man Utd")
    rec = parse_market(io.StringIO(text))
    assert rec["odds_H"] == 2.2 and rec["odds_A"] == 3.5  # not the in play 1.01, not the older 2.42
    assert rec["result_hda"] == "A"
    assert rec["minutes_before_kickoff"] == 2


def test_parse_market_runner_names_differ_from_event_name():
    import io
    # Real cases: "Celtic v Karabakh" with runner "Qarabag FK"; "Juventus v SPAL" with runner "Spal"
    text = _market_stream("1.2", "Celtic v Karabakh", "Celtic", "Qarabag FK", "2015-07-29T18:45:00.000Z",
                          {"Celtic": 1.6, "The Draw": 4.0, "Qarabag FK": 6.0}, "Celtic")
    rec = parse_market(io.StringIO(text))
    assert (rec["home"], rec["away"], rec["odds_H"], rec["odds_A"], rec["result_hda"]) == (
        "Celtic", "Karabakh", 1.6, 6.0, "H")
    text = _market_stream("1.3", "Juventus v SPAL", "Juventus", "Spal", "2018-03-17T17:00:00.000Z",
                          {"Juventus": 1.2, "The Draw": 7.0, "Spal": 17.0}, "The Draw")
    rec = parse_market(io.StringIO(text))
    assert (rec["odds_H"], rec["odds_A"], rec["result_hda"]) == (1.2, 17.0, "D")
    # neither team name matches a runner: cannot tell home from away, so no record
    text = _market_stream("1.4", "Juventus v SPAL", "Juve", "Spal FC", "2018-03-17T17:00:00.000Z",
                          {"Juve": 1.2, "The Draw": 7.0, "Spal FC": 17.0}, "The Draw")
    assert parse_market(io.StringIO(text)) is None


def test_oddsportal_result_after_90_minutes():
    assert result_90("(1:1, 0:1)") == "A"
    assert result_90("(0:1, 2:1)") == "D"  # Juventus v Bayern 2016: 2-2, not a final score
    assert result_90(None) is None and result_90("(1:0)") is None


def test_oddsportal_extra_time_without_half_time_scores(tmp_path):
    odds = [{"1": "2.0", "X": "3.3", "2": "3.8"}]
    recs = [  # single match to extra time: draw after 90; second leg to extra time: unknown, or the override
        {"match_link": "a", "home_team": "Chelsea", "away_team": "Manchester Utd", "league_name": "Capital One Cup",
         "match_date": "2012-10-31 19:45:00 UTC", "home_score": "5", "away_score": "4", "1x2_market": odds},
        {"match_link": "b", "home_team": "Sunderland", "away_team": "Manchester Utd", "league_name": "Capital One Cup",
         "match_date": "2014-01-07 19:45:00 UTC", "home_score": "2", "away_score": "1",
         "partial_results": "(1:1, 1:0)", "1x2_market": odds},
        {"match_link": "c", "home_team": "Manchester Utd", "away_team": "Sunderland", "league_name": "Capital One Cup",
         "match_date": "2014-01-22 19:45:00 UTC", "home_score": "2", "away_score": "2", "1x2_market": odds}]
    (tmp_path / "x.json").write_text(json.dumps(recs))
    names = {"Manchester Utd": "Manchester United"}
    op = load_oddsportal(names, None, tmp_path)
    assert list(op["result_hda"].fillna("")) == ["D", "H", ""]
    override = pd.DataFrame({"date": ["22/01/2014"], "home": ["Manchester Utd"], "away": ["Sunderland"],
                             "result_hda": ["H"]})
    assert list(load_oddsportal(names, override, tmp_path)["result_hda"]) == ["D", "H", "H"]


def test_oddsportal_added_only_when_betfair_lacks_the_match():
    t = lambda d: pd.Timestamp(d, tz="UTC")  # noqa: E731
    op = pd.DataFrame({"home": ["Linfield", "Zenit", "Celtic", "PSG"], "away": ["Celtic", "Benfica", "Qarabag", "Celtic"],
                       "kickoff_utc": [t("2017-07-14 18:45"), t("2016-03-09 17:00"), t("2015-07-29 18:45"),
                                       t("2017-11-22 19:45")]})
    bf = pd.DataFrame({"home": ["Celtic", "Zenit St Petersburg", "Celtic", "Paris St-G"],
                       "away": ["Lyon", "Benfica", "Karabakh", "Celtic"],
                       "kickoff_utc": [t("2017-07-15 14:00"), t("2016-03-09 17:00"), t("2015-07-29 18:45"),
                                       t("2017-11-22 19:45")]})
    names = {"Celtic": "Celtic", "Benfica": "Benfica"}
    # Celtic v Lyon is a different match (a friendly the next day); Betfair has the other three
    # (PSG / Paris St-G: names do not match, same venue and kickoff do)
    assert list(missing_from_betfair(op, names, bf, names)["home"]) == ["Linfield"]


def test_select_markets_keeps_main_market_and_drops_postponed():
    m = pd.DataFrame({
        "event_id": ["E1", "E1", "E2", "E3"],
        "market_id": ["1.1", "1.2", "1.3", "1.4"],
        "odds_H": [1.31, 1.32, 2.0, 2.0], "odds_D": [5.8, 5.8, 3.4, None], "odds_A": [15.0, 14.5, 4.0, 4.0],
        "n_updates": [730, 42, 5, 300], "went_in_play": [True, True, False, True]})
    kept, dropped = _select_markets(m)
    assert list(kept["market_id"]) == ["1.1"]  # main market of E1; E2 postponed; E3 incomplete
    assert dict(zip(dropped["market_id"], dropped["reason"].str.split(" ").str[0])) == {
        "1.2": "second", "1.3": "never", "1.4": "no"}


def test_search_terms_drops_aliases_covered_by_substring():
    names = {"Roma": "Roma", "AS Roma": "Roma", "Porto": "Porto", "FC Porto": "Porto",
             "Sporting Lisbon": "Sporting CP", "Man Utd": "Manchester United"}
    assert sorted(search_terms(names)) == ["Man Utd", "Porto", "Roma", "Sporting Lisbon"]


def test_parse_openfootball_carries_year_across_groups(tmp_path):
    f = tmp_path / "2015-16_cl.txt"
    f.write_text("= UEFA Champions League 2015/16\n\n\u25aa Group A\n  Tue Sep 15 2015\n"
                 "    20:45  Real Madrid (ESP)       v Shakhtar Donetsk (UKR)   4-0 (1-0)\n"
                 "  Tue Dec 8\n           Real Madrid (ESP)       v Malm\u00f6 FF (SWE)           8-0 (3-0)\n"
                 "\u25aa Group B\n  Tue Sep 15\n    20:45  PSV Eindhoven (NED)     v Manchester United (ENG)  2-1\n"
                 "\u25aa Round of 16\n  Tue Feb 16 2016\n    20:45  Benfica (POR) v Zenit (RUS)  1-0\n",
                 encoding="utf-8")
    fx = parse_file(f)
    assert list(fx["date"].dt.strftime("%Y-%m-%d")) == ["2015-09-15", "2015-12-08", "2015-09-15", "2016-02-16"]
    assert list(fx["away"]) == ["Shakhtar Donetsk", "Malm\u00f6 FF", "Manchester United", "Zenit"]


def test_drop_friendlies(tmp_path):
    league = pd.DataFrame({"club": ["Ajax"] * 5 + ["Celtic"],
                           "season": ["1516"] + ["1617"] * 5,
                           "date": pd.to_datetime(["2016-05-15", "2016-08-07", "2016-12-21", "2017-01-15",
                                                   "2017-01-22", "2016-08-06"])})
    path = tmp_path / "lg.csv"
    league.to_csv(path, index=False)
    rows = pd.DataFrame({
        "club": ["Ajax", "Ajax", "Ajax", "Ajax", "Ajax", "Celtic", "Ajax", "Ajax"],
        "season": ["1617"] * 8,
        "date": pd.to_datetime(["2016-07-20", "2017-01-07", "2016-10-26", "2016-09-21", "2016-09-21", "2016-07-12",
                                "2016-07-26", "2016-08-03"]),
        "opponent": ["PSV", "RB Leipzig", "Willem II", "VVSB", "Rostov", "Astana", "PAOK", "PAOK"],
        "venue": ["H", "A", "H", "H", "A", "H", "H", "A"],
        "competition": [None] * 8,
        "competition_type": ["other", "other", "other", "other", "european", "other", "other", "other"]})
    rule = {"winter_break_min_days": 18, "date_rule_exempt": [{"club": "Celtic", "reason": "qualifiers"}]}
    kept, dropped = _drop_friendlies(rows, path, rule)
    # cup tie, Europe, exempt Celtic, and a two-legged qualifier in the off-season
    assert sorted(kept["opponent"]) == ["Astana", "PAOK", "PAOK", "Rostov", "Willem II"]

    assert dict(zip(dropped["opponent"], dropped["reason"].str.split(": ").str[1])) == {
        "PSV": "off-season (before first league match)", "RB Leipzig": "winter break",
        "VVSB": "second match on the same day"}

    # A super cup on a configured date against a league opponent is kept; a friendly that day is not
    cup_rows = pd.DataFrame({
        "club": ["Ajax", "Ajax", "Ajax"], "season": ["1617"] * 3,
        "date": pd.to_datetime(["2016-10-02", "2016-07-31", "2016-07-31"]),
        "opponent": ["PSV", "PSV", "Bourg-Peronnas"], "venue": ["H", "A", "H"],
        "competition": ["league", None, None], "competition_type": ["league", "other", "other"]})
    cups = pd.DataFrame({"cup": ["johan_cruijff_schaal"], "league": ["N1"], "date": pd.to_datetime(["2016-07-31"])})
    kept, dropped = _drop_friendlies(cup_rows, path, rule, cups, {"Ajax": "N1"})
    assert list(kept["competition"]) == ["league", "johan_cruijff_schaal"]
    assert list(dropped["opponent"]) == ["Bourg-Peronnas"]

    # Winter break: league opponent kept as a cup tie, except in winter-camp leagues
    win_rows = pd.DataFrame({
        "club": ["Ajax", "Ajax"], "season": ["1617"] * 2,
        "date": pd.to_datetime(["2016-10-02", "2017-01-07"]),
        "opponent": ["Excelsior", "Excelsior"], "venue": ["H", "H"],
        "competition": ["league", None], "competition_type": ["league", "other"]})
    rule_camp = dict(rule, winter_camp_friendly_leagues=["N1"])
    _, dropped = _drop_friendlies(win_rows, path, rule_camp, None, {"Ajax": "N1"})
    assert list(dropped["opponent"]) == ["Excelsior"]  # Dutch winter camp friendly
    kept, _ = _drop_friendlies(win_rows, path, rule, None, {"Ajax": "N1"})
    assert list(kept["competition"]) == ["league", "domestic cup (inferred: winter, league opponent)"]

    # A flagged leg whose other leg is already named takes that name (Ajax v Nice, 2017 CL qualifier)
    tie_rows = pd.DataFrame({
        "club": ["Ajax", "Ajax"], "season": ["1617"] * 2,
        "date": pd.to_datetime(["2016-07-26", "2016-08-02"]), "opponent": ["Nice", "Nice"], "venue": ["A", "H"],
        "competition": ["Champions League", None], "competition_type": ["european", "other"]})
    kept, dropped = _drop_friendlies(tie_rows, path, rule)
    assert dropped.empty and list(kept["competition"]) == ["Champions League"] * 2
    assert list(kept["competition_type"]) == ["european"] * 2


def test_label_competition_prefers_market_with_result(tmp_path):
    # Nacional v Benfica abandoned on 10/01/2016 and replayed on 11/01/2016: both Betfair
    # markets are within a day of Step 1's date. The replay (with a result) is the league match.
    league = pd.DataFrame({"club": ["Benfica"], "date": pd.to_datetime(["2016-01-11"]),
                           "p_win": [0.54], "season": ["1516"]})
    path = tmp_path / "lg.csv"
    league.to_csv(path, index=False)
    bf = pd.DataFrame({"match_id": ["BF_abandoned", "BF_replay"], "club": ["Benfica"] * 2,
                       "date": pd.to_datetime(["2016-01-10", "2016-01-11"]), "season": ["1516"] * 2,
                       "p_win": [0.54, 0.57], "result": [None, "W"]})
    fixtures = pd.DataFrame({"club": pd.Series(dtype=str), "date": pd.Series(dtype="datetime64[us]"),
                             "competition": pd.Series(dtype=str)})
    out = _label_competition(bf, path, fixtures)
    assert dict(zip(out["match_id"], out["competition_type"])) == {"BF_abandoned": "other", "BF_replay": "league"}


def test_fill_kickoff_times_from_betfair():
    lg = pd.DataFrame({"club": ["Porto"] * 4,
                       "date": pd.to_datetime(["2020-01-04", "2016-01-06", "2015-12-14", "2013-01-05"]),
                       "kickoff_time": ["20:30", None, None, None]})
    bf = pd.DataFrame({"club": ["Porto"] * 3, "competition_type": ["league", "league", "league"],
                       "date": pd.to_datetime(["2020-01-04", "2016-01-06", "2015-12-13"]),
                       "kickoff_time": ["20:31", "20:15", "16:00"]})
    out = _fill_kickoff_times(lg, bf)
    # own time kept; same-date Betfair time used; a Betfair date one day off is not used
    assert list(out["kickoff_time"].fillna("")) == ["20:30", "20:15", "", ""]
    assert list(out["kickoff_source"]) == ["football_data", "betfair", "assumed_evening", "none"]
    op = pd.DataFrame({"club": ["Porto", "Porto"], "date": pd.to_datetime(["2016-01-06", "2013-01-05"]),
                       "kickoff_time": ["20:00", "18:15"]})
    out = _fill_kickoff_times(lg, bf, op)
    # Betfair first, OddsPortal for the rest
    assert list(out["kickoff_time"].fillna("")) == ["20:30", "20:15", "", "18:15"]
    assert list(out["kickoff_source"]) == ["football_data", "betfair", "assumed_evening", "oddsportal"]


def test_name_from_listings():
    rows = pd.DataFrame({"club": ["Porto", "Porto", "Porto", "Lazio", "Borussia Dortmund"],
                         "date": pd.to_datetime(["2016-01-20", "2016-02-10", "2016-07-20", "2016-01-21",
                                                 "2016-08-15"]),
                         "opponent": ["Braga", "Borussia Dortmund", "Lyon", "Inter", "SV Sandhausen"],
                         "competition_type": ["other", "other", "other", "league", "other"],
                         "competition": [None, None, None, "league", None]})
    listings = pd.DataFrame({"club": ["Porto", "Porto", "Porto", "Lazio", "Borussia Dortmund"],
                             "date": pd.to_datetime(["2016-01-19", "2016-01-20", "2016-02-11", "2016-01-21",
                                                     "2016-08-14"]),
                             "opponent": ["benfica", "braga", "dortmund", "inter", "bayern munich"],
                             "match_link": ["a", "b", "c", "d", "e"],
                             "competition": ["Taca da Liga", "Taca de Portugal", "Europa League", "Coppa Italia",
                                             "DFL-Supercup"]})
    out = _name_from_listings(rows, listings)
    # same day beats a day off; one day off names only against the same opponent; a pre-season
    # friendly stays unnamed; league rows are left alone; a European listing makes the row european
    assert list(out["competition"].fillna("")) == ["Taca de Portugal", "Europa League", "", "league", ""]
    assert list(out["competition_type"]) == ["other", "european", "other", "league", "other"]


def test_end_to_end():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        fd_raw, bf_raw, out = tmp / "fd", tmp / "bf", tmp / "out"
        fd_raw.mkdir()
        (fd_raw / "1213_I1.csv").write_text(FD_CSV)
        rows = build_match_expectations(download=False, raw_dir=fd_raw, out_dir=out)
        # Juve v Lazio gives two rows, Roma v Juve two rows, Bologna v Lazio one, Bologna v Inter none
        assert len(rows) == 5
        juve_home = rows[(rows.club == "Juventus") & (rows.venue == "H")].iloc[0]
        assert juve_home.result == "W" and juve_home.odds_source == "pinnacle_closing"
        roma = rows[rows.club == "Roma"].iloc[0]
        assert roma.odds_source == "average_prematch" and roma.result == "D"

        bf_raw.mkdir()
        (bf_raw / "1.1.bz2").write_bytes(bz2.compress(_market_stream(
            "1.1", "Juventus v Man Utd", "Juventus", "Man Utd", "2012-10-02T18:45:00.000Z",
            {"Juventus": 2.2, "The Draw": 3.4, "Man Utd": 3.5}, "Man Utd").encode()))
        (bf_raw / "1.2.bz2").write_bytes(bz2.compress(_market_stream(
            "1.2", "Juventus v Lazio", "Juventus", "Lazio", "2012-08-25T18:45:00.000Z",
            {"Juventus": 1.62, "The Draw": 4.1, "Lazio": 6.6}, "Juventus").encode()))
        (bf_raw / "1.3.bz2").write_bytes(bz2.compress(_market_stream(
            "1.3", "Bologna v Inter", "Bologna", "Inter", "2012-09-16T15:00:00.000Z",
            {"Bologna": 2.1, "The Draw": 3.3, "Inter": 3.8}, "Inter").encode()))
        fx = tmp / "fixtures"
        fx.mkdir()
        (fx / "2012-13_cl.txt").write_text(OF_TXT + """  Tue Oct 23 2012
    20:45  Juventus (ITA)          v FC Nordsjælland (DEN)    4-0
""", encoding="utf-8")
        op_raw = tmp / "oddsportal"
        op_raw.mkdir()
        odds = [{"1": "1.15", "X": "8.0", "2": "19.0", "bookmaker_name": "a"},
                {"1": "1.17", "X": "7.5", "2": "17.0", "bookmaker_name": "b"}]
        (op_raw / "cl_odds_2012-2013.json").write_text(json.dumps([
            {"match_link": "https://op/juve-nord/#AAA", "home_team": "Juventus", "away_team": "Nordsjaelland",
             "match_date": "2012-10-23 18:45:00 UTC", "partial_results": "(2:0, 2:0)", "1x2_market": odds},
            {"match_link": "https://op/juve-mu/#BBB", "home_team": "Juventus", "away_team": "Manchester Utd",
             "match_date": "2012-10-02 18:45:00 UTC", "partial_results": "(0:1, 0:0)", "1x2_market": odds}]))
        bf = build_betfair_expectations(raw_dir=bf_raw, out_dir=out, fixtures_dir=fx, oddsportal_dir=op_raw,
                                        wikipedia_dir=tmp / "wikipedia")
        # Juve and Man Utd from 1.1, Juve and Lazio from 1.2, nothing from 1.3, Juve from OddsPortal
        # (Juve v Man Utd is not taken from OddsPortal: Betfair has it)
        assert len(bf) == 5
        op = bf[bf.source == "oddsportal"]
        assert list(op.match_id) == ["OP_AAA"] and op.iloc[0].odds_H == 1.16
        assert op.iloc[0].result == "W" and op.iloc[0].competition_type == "european"
        assert set(bf[bf.match_id == "BF_1.1"].competition_type) == {"european"}
        assert set(bf[bf.match_id == "BF_1.1"].competition) == {"Champions League"}
        assert set(bf[bf.match_id == "BF_1.2"].competition_type) == {"league"}
        mu = bf[bf.club == "Manchester United"].iloc[0]
        assert mu.venue == "A" and mu.result == "W"

        combined = pd.read_csv(out / "match_expectations_all.csv")
        assert len(combined) == 8  # 5 league rows + 3 European rows
        assert (combined.competition_type == "european").sum() == 3
        assert set(combined[combined.competition_type == "league"].competition) == {"Serie A"}
        assert set(combined[combined.competition_type == "european"].competition) == {"Champions League"}



def test_surprise_values():
    rows = pd.DataFrame({"result": ["W", "W", "D", "L", "D"],
                         "p_win": [0.80, 0.38, 0.80, 0.80, 0.20], "p_draw": [0.14, 0.29, 0.14, 0.14, 0.25],
                         "p_loss": [0.06, 0.33, 0.06, 0.06, 0.55]})
    rows["exp_points"] = 3 * rows["p_win"] + rows["p_draw"]
    out = add_surprise(rows)
    # the examples table in docs/step2_surprise.md
    assert np.allclose(out["surprise"], [0.26, 0.95, -0.74, -1.74, 0.35])
    assert list(out["surprise_sign"]) == ["pos", "pos", "neg", "neg", "pos"]
    assert np.allclose(out["p_outcome"], [0.80, 0.38, 0.14, 0.06, 0.25])
    assert np.isclose(out["info"].iloc[0], -np.log(0.8))
    assert np.allclose(out["surprise_points"], [3 - 2.54, 3 - 1.43, 1 - 2.54, -2.54, 1 - 0.85])
    out, (lo, hi) = add_terciles(out)
    assert lo < hi and list(out["surprise_tercile"]) == ["mid", "high", "low", "low", "high"]


def test_congestion():
    rows = pd.DataFrame({"club": ["Ajax"] * 4 + ["Celtic"],
                         "date": pd.to_datetime(["2020-01-01", "2020-01-04", "2020-01-08", "2020-01-20",
                                                 "2020-01-02"]),
                         "competition_type": ["league", "european", "league", "other", "league"]})
    out = add_congestion(rows).set_index(["club", "date"])
    ajax = out.loc["Ajax"]
    assert list(ajax["days_since_prev"].astype("float").fillna(-1)) == [-1, 3, 4, 12]
    assert list(ajax["days_to_next"].astype("float").fillna(-1)) == [3, 4, 12, -1]
    assert list(ajax["matches_next_7d"]) == [2, 1, 0, 0]
    assert list(ajax["next_competition_type"].fillna("")) == ["european", "league", "other", ""]
    assert out.loc[("Celtic", pd.Timestamp("2020-01-02")), "matches_next_7d"] == 0


def test_build_match_surprise_drops_abandoned(tmp_path):
    rows = pd.DataFrame({"match_id": ["a", "b", "c"], "club": ["Roma"] * 3,
                         "date": ["2024-04-14", "2024-04-21", "2024-04-25"], "season": ["2324"] * 3,
                         "opponent": ["Udinese", "Bologna", "Udinese"], "odds_source": ["x"] * 3,
                         "competition_type": ["other", "league", "league"],
                         "competition": [None, "Serie A", "Serie A"], "result": [None, "L", "W"],
                         "p_win": [0.6, 0.5, 0.6], "p_draw": [0.25, 0.3, 0.25], "p_loss": [0.15, 0.2, 0.15]})
    rows["exp_points"] = 3 * rows["p_win"] + rows["p_draw"]
    rows.to_csv(tmp_path / "in.csv", index=False)
    out = build_match_surprise(tmp_path / "in.csv", tmp_path)
    assert list(out["match_id"]) == ["b", "c"] and list(out["days_since_prev"].fillna(-1)) == [-1, 4]
    assert list(pd.read_csv(tmp_path / "surprise_abandoned.csv")["match_id"]) == ["a"]



WIKI_BOXES = """==Pre-season and friendlies==
{{football box collapsible
|date = 17 July 2016
|team1 = [[VfL Osnabrück]]
|score = 1–2
|team2 = [[FC Porto|Porto]]
}}
==Competitions==
===Taça de Portugal===
====Fourth round====
{{football box collapsible
|date = {{Start date|2016|11|18}}
|time = 20:15 [[Western European Time|WET]]
|team1 = [[G.D. Chaves|Chaves]]
|score = 0–0
|aet = yes
|team2 = [[FC Porto|Porto]]
|penaltyscore = 3–2
}}
===UEFA Champions League===
====Group stage====
{{Football box collapsible
|date = September 13, 2016
|team1 = [[FC Porto|Porto]]
|score = 1–1
|team2 = [[F.C. Copenhagen|Copenhagen]]
}}
"""

WIKI_TABLE = """==UEFA Europa League==
===Knockout phase===
{| class="wikitable"
|-
!Date
!Round
!Opponents
!H / A
!Result<br />F–A
|- bgcolor="#ddffdd"
|10 March 2016
|Round of 16<br />First leg
|[[Liverpool F.C.|Liverpool]]
|A
|[https://www.bbc.co.uk/sport/football/1 0–2]
|}
"""


def test_wikipedia_parse_boxes_and_tables():
    d = parse_article(WIKI_BOXES)
    assert list(d["date"].dt.strftime("%Y-%m-%d")) == ["2016-07-17", "2016-11-18", "2016-09-13"]
    assert list(d["friendly"]) == [True, False, False]
    assert list(d["section"]) == ["Pre-season and friendlies", "Taça de Portugal", "UEFA Champions League"]
    assert d.iloc[1]["team1"] == "Chaves" and d.iloc[1]["aet"] and d.iloc[1]["penalties"] == "3–2"
    t = parse_article(WIKI_TABLE)  # Manchester United style: no boxes, a results table
    assert len(t) == 1 and t.iloc[0]["team2"] == "Liverpool" and t.iloc[0]["time"] == "A"
    assert t.iloc[0]["section"] == "UEFA Europa League" and t.iloc[0]["score"] == "0–2"
    # local time with offset or zone to UK time; no zone, no time
    assert kickoff_uk("20:15 WEST (UTC+01:00)", pd.Timestamp("2016-10-15")) == "20:15"
    assert kickoff_uk("20:45 CET", pd.Timestamp("2017-02-16")) == "19:45"
    assert kickoff_uk("19:00 TRT (UTC+3)", pd.Timestamp("2018-01-20")) == "16:00"
    assert kickoff_uk("20:45", pd.Timestamp("2017-02-16")) is None



def test_event_day():
    cal = pd.DatetimeIndex(pd.to_datetime(["2017-08-08", "2017-08-09", "2017-08-11", "2017-08-14"]))
    nyse = {"timezone": "America/New_York", "close_times": [{"from": "2000-01-01", "close": "16:00"}]}
    ist = {"timezone": "Europe/Istanbul", "close_times": [{"from": "2000-01-01", "close": "17:30"},
                                                          {"from": "2015-11-30", "close": "18:00"}]}
    # 19:45 UK kickoff ends 16:40 New York: after the close, next session, flagged near the close
    end = match_end_utc(pd.Timestamp("2017-08-08"), "19:45", "betfair")
    assert event_day(end, cal, nyse) == (pd.Timestamp("2017-08-09"), True)
    # 14:00 UK (BST) kickoff ends 17:55 Istanbul (UTC+3): before the 18:00 close, same day, near it;
    # 13:00 ends 16:55, same day, more than an hour before the close
    end = match_end_utc(pd.Timestamp("2017-08-08"), "14:00", "betfair")
    assert event_day(end, cal, ist) == (pd.Timestamp("2017-08-08"), True)
    end = match_end_utc(pd.Timestamp("2017-08-08"), "13:00", "betfair")
    assert event_day(end, cal, ist) == (pd.Timestamp("2017-08-08"), False)
    # weekend match with no time: next trading day; a gap in the calendar (holiday) is skipped
    end = match_end_utc(pd.Timestamp("2017-08-12"), None, "none")
    assert event_day(end, cal, ist) == (pd.Timestamp("2017-08-14"), False)
    end = match_end_utc(pd.Timestamp("2017-08-09"), None, "assumed_evening")
    assert event_day(end, cal, ist)[0] == pd.Timestamp("2017-08-11")


def test_apply_corporate_actions():
    prices = pd.DataFrame({"ticker": ["X"] * 4, "date": pd.to_datetime(["2024-07-01", "2024-07-02", "2024-07-03",
                                                                        "2024-07-04"]),
                           "adj_close": [32.0, 33.5, 7.8, 7.49]})
    # without a factor: rescaled by the jump, that day's return excluded
    actions = pd.DataFrame({"ticker": ["X"], "date": ["2024-07-03"], "ex_date": [None], "factor": [None],
                            "reason": ["unknown"]})
    out = apply_corporate_actions(prices, actions)
    ret = out["adj_close"].pct_change()
    assert abs(ret.iloc[1] - (33.5 / 32 - 1)) < 1e-12 and abs(ret.iloc[2]) < 1e-12  # continuous
    assert list(out["corporate_action"]) == [False, False, True, False]
    assert list(out["exclude_return"]) == [False, False, True, False]
    # with Bloomberg's factor: earlier prices scaled by it, the day's return kept (BJKAS 03/07/2024)
    actions = actions.assign(factor=[0.223881])
    out = apply_corporate_actions(prices, actions)
    ret = out["adj_close"].pct_change()
    assert abs(ret.iloc[2] - (7.8 / (33.5 * 0.223881) - 1)) < 1e-12 and not out["exclude_return"].any()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")


def test_dimson_beta_recovers_lagged_beta():
    rng = np.random.default_rng(0)
    rm = rng.normal(0, 0.01, 600)
    # A stale stock: half of the market move shows up a day late; true beta 0.8
    r = 0.4 * rm + 0.4 * np.r_[0, rm[:-1]] + rng.normal(0, 0.002, 600)
    beta, _ = dimson_beta(r, rm)
    assert np.isnan(beta[:130]).all()                    # fewer than 120 returns in the window
    assert abs(np.nanmean(beta[300:]) - 0.8) < 0.05


def test_lag_matrix_stays_within_club_and_regression_recovers_drift():
    rng = np.random.default_rng(1)
    n = 2000
    panel = pd.DataFrame({"club": ["A"] * n + ["B"] * n,
                          "date": list(pd.bdate_range("2015-01-01", periods=n)) * 2})
    rows = np.r_[np.arange(5, n - 12, 4), n + np.arange(5, n - 12, 4)]
    ev = pd.DataFrame({"row": rows, "club_start": np.where(rows < n, 0, n), "club_end": np.where(rows < n, n, 2 * n),
                       "surprise": rng.uniform(-1.5, 1.5, len(rows))})
    X = lag_matrix(len(panel), ev, ev["surprise"].to_numpy()[:, None], lags=[0, 1])
    assert X[n - 1, 1] == 0 and X[n, 1] == 0             # club A's last event does not reach club B
    panel["ar"] = X[:, 0] * 0.01 + X[:, 1] * 0.003 + rng.normal(0, 0.002, 2 * n)
    f = Fit(panel, ev, ["S"], ev["surprise"].to_numpy()[:, None], lags=[0, 1])
    assert abs(f.coef("S", [0])[0] - 0.01) < 0.0005
    d, se, p = f.coef("S", [1])
    assert abs(d - 0.003) < 0.0005 and p < 0.001


def test_expanding_terciles_use_earlier_seasons_only():
    ev = pd.DataFrame({"season": ["1213"] * 3 + ["1314"] * 3 + ["1415"] * 2,
                       "surprise": [-1.0, 0.0, 1.0, -2.0, 0.2, 2.0, 0.0, 0.0]})
    sig = expanding_terciles(ev)
    assert sig[:3].isna().all()
    assert list(sig[3:6]) == ["low", "mid", "high"]
    later = ev.copy()
    later.loc[6:, "surprise"] = [5.0, -5.0]               # changing a later season changes no earlier signal
    assert expanding_terciles(later)[:6].equals(sig[:6])


def test_corwin_schultz():
    flat = pd.DataFrame({"date": pd.bdate_range("2020-01-01", periods=3), "High": [1.0] * 3, "Low": [1.0] * 3,
                         "Close": [1.0] * 3, "Volume": [10] * 3})
    assert (corwin_schultz(flat) == 0).all()              # one trade a day: the estimator returns 0
    bounce = flat.assign(High=[1.01, 1.01, 1.01], Low=[0.99, 0.99, 0.99])
    s = corwin_schultz(bounce)
    assert (s > 0.01).all() and (s < 0.05).all()
    assert corwin_schultz(bounce.assign(Volume=[10, 0, 10])).isna().all()


def test_holm_and_wald():
    assert holm([0.01, 0.04, 0.03]) == [0.03, 0.06, 0.06]
    b, V = np.array([1.0, 1.0]), np.eye(2)
    stat, p = wald_p(b, V, np.eye(2))
    assert stat == 2.0 and abs(p - np.exp(-1)) < 1e-12


def test_match_week_fit_separates_common_pattern_from_surprise():
    rng = np.random.default_rng(2)
    n = 3000
    panel = pd.DataFrame({"club": "A", "date": pd.bdate_range("2014-01-01", periods=n)})
    rows = np.arange(10, n - 10, 7)
    ev = pd.DataFrame({"row": rows, "club_start": 0, "club_end": n, "surprise": rng.uniform(-1.5, 1.5, len(rows))})
    ar = rng.normal(0, 0.002, n)
    ar[rows - 1] += 0.003                                  # rise the day before every match
    ar[rows + 1] -= 0.004                                  # fall the day after, whatever the result
    ar[rows] += 0.01 * ev["surprise"].to_numpy()
    panel["ar"] = ar
    f = match_week_fit(panel, ev)
    assert abs(f.coef("any", [-1])[0] - 0.003) < 0.0005
    assert abs(f.coef("any", [1])[0] + 0.004) < 0.0005
    assert abs(f.coef("S", [0])[0] - 0.01) < 0.0005


def test_parse_league_table_reads_deductions_and_notes():
    html = """<table><tr><th>Pos</th><th>Team</th><th>Pld</th><th>W</th><th>D</th><th>L</th><th>GF</th><th>GA</th>
    <th>GD</th><th>Pts</th><th>Qualification or relegation</th></tr>
    <tr><td>1</td><td>Napoli (C)</td><td>2</td><td>2</td><td>0</td><td>0</td><td>3</td><td>0</td><td>+3</td><td>6</td>
    <td rowspan="2">Qualification for the Champions League group stage[a]</td></tr>
    <tr><td>2</td><td>Juventus[c]</td><td>2</td><td>1</td><td>0</td><td>1</td><td>1</td><td>1</td><td>0</td><td>−7[d]</td></tr>
    <tr><td>3</td><td>Spezia (R)</td><td>2</td><td>0</td><td>0</td><td>2</td><td>0</td><td colspan="2.5">3</td><td>0</td><td>Relegation to Serie B</td></tr>
    </table>"""
    t = parse_table(html)
    assert list(t["team"]) == ["Napoli", "Juventus", "Spezia"]
    assert list(t["adjustment"]) == [0, -10, 0]
    assert t.loc[1, "note"] == "Qualification for the Champions League group stage"
    places = season_places(t.assign(league="I1", season="2223"), pd.DataFrame(columns=["league", "season"]),
                           pd.DataFrame(columns=["league", "season"]))
    assert places.loc[0, ["last_cl", "first_rel", "matches_per_team"]].tolist() == [2, 3, 4]


def test_gap_to_place_ignores_tiebreaks():
    table = (80, 70, 60, 60, 50)
    assert gap_to_place(3, 60, table, 3) == 0 and gap_to_place(4, 60, table, 3) == 0   # level: 0 either side
    assert gap_to_place(2, 70, table, 3) == 10      # above the line: lead over the team below it
    assert gap_to_place(5, 50, table, 3) == 10      # below the line: behind the team on the place
    assert gap_to_place(1, 80, table, 0) > 100      # no such line


def test_standings_before_counts_earlier_days_deductions_and_awards():
    d = pd.to_datetime
    res = pd.DataFrame({"league": "I1", "season": "2021", "date": d(["2020-09-19", "2020-09-26", "2020-10-03"]),
                        "home": ["Verona", "Roma", "Verona"], "away": ["Roma", "Verona", "Roma"],
                        "hg": [0, 1, 2], "ag": [0, 0, 2]})
    awarded = pd.DataFrame([{"league": "I1", "season": "2021", "date": d("2020-09-19"), "home": "Verona",
                             "away": "Roma", "hg": 3, "ag": 0, "decided": "2020-09-22"}])
    ded = pd.DataFrame([{"league": "I1", "season": "2021", "team": "Roma", "date": d("2020-09-30"),
                         "points": -5, "gd": 0, "gf": 0}])
    adj = pd.concat([ded, awarded_adjustments(res, awarded)], ignore_index=True)
    st = standings_before(res, adj).set_index(["date", "team"])
    assert st.loc[(d("2020-09-19"), "Roma"), "pts"] == 0                      # nothing before the first day
    assert st.loc[(d("2020-09-26"), "Verona"), ["pts", "rank"]].tolist() == [3, 1]   # award counted from 22/09
    assert st.loc[(d("2020-09-26"), "Roma"), "pts"] == 0
    assert st.loc[(d("2020-10-03"), "Roma"), "pts"] == -2                     # 3 - 5 after the deduction
    assert st.loc[(d("2020-10-03"), "Roma"), "match_no"] == 3
    assert apply_awarded(res, awarded).loc[0, ["hg", "ag"]].tolist() == [3, 0]
    places = pd.DataFrame([{"league": "I1", "season": "2021", "matches_per_team": 4, "last_cl": 1, "first_rel": 2}])
    flags = stakes(standings_before(res, adj), places, last_rounds=2, within=6)
    assert flags["late"].tolist() == [False, False, False, False, True, True]   # match 3 of 4 scheduled
    assert flags["stakes"].sum() == 2              # Verona 3, Roma -2: 5 points either side of the title line
