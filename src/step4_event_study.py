"""Step 4: abnormal returns, the event study (distributed lag panel regression) and the backtest.

Entry points: build_abnormal_returns(), run_event_study(), run_exploratory(), run_backtest(). See
docs/step4_event_study.md.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from .common import PROCESSED, ROOT, load_config
from .step3_prices import RAW_BLOOMBERG, RAW_PRICES, _file, trading_calendars

FIGURES = ROOT / "figures"
LAGS = list(range(-3, 11))         # k: S(i, t - k); negative k are leads (leak check)
DRIFT = [1, 2, 3]                  # H1: D = b_1 + b_2 + b_3
BETA_WINDOW = (260, 11)            # beta from trading days t-260 to t-11
BETA_MIN_OBS = 120
ILLIQUID = ["Porto", "Sporting CP", "Celtic"]   # stale on day 0 for 21%, 17%, 11% of matches
TYPES = ["league", "european", "other"]
E1_GROUPS = ["stakes", "late_no_stakes", "rest"]   # E1: late league matches with and without stakes, all others
COMMISSION = 0.001                 # per side
HOLD = 3                           # backtest: exit at the close of day +3 at the latest
CLEAN = (3, 3)                     # descriptive event study: no other match within 3 trading days either side


# ---------------------------------------------------------------- abnormal returns

def dimson_beta(r: np.ndarray, rm: np.ndarray, window=BETA_WINDOW, min_obs=BETA_MIN_OBS):
    """Rolling Dimson regression r_t = a + c1 rm_{t-1} + c2 rm_t + c3 rm_{t+1} over rows
    t - window[0] .. t - window[1]. Returns (beta = c1 + c2 + c3, alpha) per row, NaN where fewer
    than min_obs usable rows. Rolling sums of cross-products, so one pass."""
    n = len(r)
    lag = np.r_[np.nan, rm[:-1]]
    lead = np.r_[rm[1:], np.nan]
    z = np.column_stack([np.ones(n), lag, rm, lead, r])
    ok = ~np.isnan(z).any(axis=1)
    z = np.where(ok[:, None], z, 0.0)
    cross = np.cumsum(z[:, :, None] * z[:, None, :], axis=0)
    cross = np.concatenate([np.zeros((1, 5, 5)), cross])          # cross[i] = sum of rows < i
    beta, alpha = np.full(n, np.nan), np.full(n, np.nan)
    first, last = window
    for t in range(n):
        lo, hi = max(t - first, 0), t - last + 1                    # rows lo .. hi - 1
        if hi <= lo:
            continue
        m = cross[hi] - cross[lo]
        if m[0, 0] < min_obs:
            continue
        coef = np.linalg.solve(m[:4, :4], m[:4, 4])
        alpha[t], beta[t] = coef[0], coef[1:].sum()
    return beta, alpha


def club_panel(prices: pd.DataFrame, cal: dict, cfg, benchmark: str | None = None,
               trade_to_trade: bool = False) -> pd.DataFrame:
    """One row per club per trading day of its exchange, within the stock's price history.
    Price carried forward over days without a trade (stale: no row or zero volume), so a stale day
    has return 0. benchmark: None for the club's local index, or a ticker (e.g. ^STOXX).
    trade_to_trade: stale days dropped, returns run from trade to trade, the benchmark's compounded
    over the same span."""
    by_ticker = {t: g.set_index("date") for t, g in prices.groupby("ticker")}
    frames = []
    for _, c in cfg.clubs.dropna(subset=["ticker"]).iterrows():
        p = by_ticker[c["ticker"]]
        days = cal[c["exchange"]]
        days = days[(days >= p.index.min()) & (days <= p.index.max())]
        s = p.reindex(days)
        b = by_ticker[benchmark or c["benchmark"]]["adj_close"].reindex(days).ffill()
        f = pd.DataFrame({"club": c["club"], "ticker": c["ticker"], "date": days,
                          "price": s["adj_close"].ffill().to_numpy(), "bench": b.to_numpy(),
                          "stale": (s["volume"].isna() | (s["volume"] == 0)).to_numpy(),
                          "exclude": s["exclude_return"].fillna(False).astype(bool).to_numpy()})
        if trade_to_trade:
            f = f[~f["stale"]].reset_index(drop=True)
        f["r"] = f["price"].pct_change()
        f["r_benchmark"] = f["bench"].pct_change()
        f.loc[f["exclude"], "r"] = np.nan
        f["beta"], f["alpha"] = dimson_beta(f["r"].to_numpy(), f["r_benchmark"].to_numpy())
        f["ar"] = f["r"] - f["beta"] * f["r_benchmark"]
        f["ar_alpha"] = f["ar"] - f["alpha"]
        frames.append(f.drop(columns=["price", "bench", "exclude"]))
    return pd.concat(frames, ignore_index=True)


def load_inputs():
    cfg = load_config()
    prices = pd.read_csv(PROCESSED / "prices.csv", parse_dates=["date"])
    cal = trading_calendars(prices, cfg)
    events = pd.read_csv(PROCESSED / "match_events.csv", parse_dates=["date", "event_date"], dtype={"season": str})
    return cfg, prices, cal, events


def build_abnormal_returns(out_dir: Path = PROCESSED) -> pd.DataFrame:
    cfg, prices, cal, _ = load_inputs()
    panel = club_panel(prices, cal, cfg)
    cols = ["club", "ticker", "date", "r", "r_benchmark", "beta", "ar", "stale"]
    panel[cols].to_csv(out_dir / "abnormal_returns.csv", index=False)
    yearly = panel.groupby(["club", panel["date"].dt.year])["beta"].mean().unstack()
    print("Mean Dimson beta per club and year:")
    print(yearly.round(2).to_string())
    return panel


# ---------------------------------------------------------------- events on the panel

def locate_events(panel: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Row of the panel holding each listed match's day 0 (for a trade to trade panel, the first
    traded day on or after it). Adds `row`, `club_start`, `club_end` (row bounds of the club)."""
    ev = events[events["listed"] & events["club"].isin(panel["club"].unique())].copy()
    rows, starts, ends = [], [], []
    bounds = {c: (g.index.min(), g.index.max() + 1, g["date"].to_numpy()) for c, g in panel.groupby("club")}
    for club, day in zip(ev["club"], ev["event_date"]):
        lo, hi, dates = bounds[club]
        i = np.searchsorted(dates, np.datetime64(day))
        rows.append(lo + i if i < len(dates) else -1)
        starts.append(lo)
        ends.append(hi)
    ev["row"], ev["club_start"], ev["club_end"] = rows, starts, ends
    return ev[ev["row"] >= 0].reset_index(drop=True)


def lag_matrix(n: int, ev: pd.DataFrame, values: np.ndarray, lags=LAGS) -> np.ndarray:
    """X[t, j * len(lags) + l] = sum of values[e, j] over the club's events e whose day 0 row is
    t - lags[l]. values: (events, m)."""
    values = np.asarray(values, dtype=float).reshape(len(ev), -1)
    X = np.zeros((n, values.shape[1] * len(lags)))
    row, lo, hi = ev["row"].to_numpy(), ev["club_start"].to_numpy(), ev["club_end"].to_numpy()
    for l, k in enumerate(lags):
        t = row + k
        ok = (t >= lo) & (t < hi)
        for j in range(values.shape[1]):
            np.add.at(X[:, j * len(lags) + l], t[ok], values[ok, j])
    return X


# ---------------------------------------------------------------- regression

def ols(y: np.ndarray, X: np.ndarray, dates: np.ndarray, errors: str = "date") -> tuple[np.ndarray, np.ndarray]:
    """OLS with a constant (added here). errors: 'date' (clustered by calendar date) or 'dk'
    (Driscoll-Kraay: date sums of the scores, Newey-West across dates). Returns coefficients and
    covariance, constant first."""
    X = np.column_stack([np.ones(len(y)), X])
    xtx_inv = np.linalg.pinv(X.T @ X)
    b = xtx_inv @ X.T @ y
    u = y - X @ b
    codes, uniq = pd.factorize(dates, sort=True)
    h = np.zeros((len(uniq), X.shape[1]))
    np.add.at(h, codes, X * u[:, None])
    n, k, g = len(y), X.shape[1], len(uniq)
    if errors == "date":
        meat = h.T @ h * g / (g - 1) * (n - 1) / (n - k)
    else:
        lags = int(4 * (g / 100) ** (2 / 9))
        meat = h.T @ h
        for l in range(1, lags + 1):
            gam = h[l:].T @ h[:-l]
            meat += (1 - l / (lags + 1)) * (gam + gam.T)
    return b, xtx_inv @ meat @ xtx_inv


def p_normal(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2))


def lincom(b, V, c) -> tuple[float, float, float]:
    est, se = float(c @ b), float(np.sqrt(c @ V @ c))
    return est, se, p_normal(est / se)


def wald_p(b, V, R) -> tuple[float, float]:
    """Wald test R b = 0; chi-square p-value for an even number of restrictions."""
    rb = R @ b
    stat = float(rb @ np.linalg.solve(R @ V @ R.T, rb))
    df = R.shape[0]
    assert df % 2 == 0, "chi-square tail implemented for even df only"
    x = stat / 2
    return stat, math.exp(-x) * sum(x ** j / math.factorial(j) for j in range(df // 2))


def holm(p: list[float]) -> list[float]:
    order = np.argsort(p)
    adj, running = [0.0] * len(p), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(p) - rank) * p[i]))
        adj[i] = running
    return adj


class Fit:
    """A distributed lag regression of the abnormal return on one or more surprise variables."""

    def __init__(self, panel, ev, names, values, ar_col="ar", errors="date", lags=LAGS):
        X = lag_matrix(len(panel), ev, values, lags)
        y = panel[ar_col].to_numpy()
        ok = ~np.isnan(y)
        self.names, self.lags, self.n = names, lags, int(ok.sum())
        self.b, self.V = ols(y[ok], X[ok], panel["date"].to_numpy()[ok], errors)
        self.resid_sd = float(np.std(y[ok] - np.column_stack([np.ones(ok.sum()), X[ok]]) @ self.b))

    def vec(self, name, ks) -> np.ndarray:
        c = np.zeros(len(self.b))
        j = self.names.index(name)
        for k in ks:
            c[1 + j * len(self.lags) + self.lags.index(k)] = 1
        return c

    def coef(self, name, ks):
        return lincom(self.b, self.V, self.vec(name, ks))

    def diff(self, a, b, ks):
        return lincom(self.b, self.V, self.vec(a, ks) - self.vec(b, ks))

    def equal(self, names, ks):
        R = np.array([self.vec(names[0], ks) - self.vec(n, ks) for n in names[1:]])
        return wald_p(self.b, self.V, R)


def surprise_values(ev: pd.DataFrame, spec: str, transform: str = "level") -> tuple[list[str], np.ndarray]:
    """Variables entering the regression for a specification:
    main: S; terciles: high and low indicators; asym: S+ and S-; competition: S by competition
    type; club: S by club. transform 'sign' replaces S by its sign (+1, 0, -1)."""
    s = ev["surprise"].to_numpy()
    if transform == "sign":
        s = np.sign(s)
    if spec == "main":
        return ["S"], s[:, None]
    if spec == "terciles":
        return ["high", "low"], np.column_stack([ev["surprise_tercile"] == "high", ev["surprise_tercile"] == "low"])
    if spec == "asym":
        return ["S_pos", "S_neg"], np.column_stack([np.maximum(s, 0), np.minimum(s, 0)])
    if spec == "competition":
        return TYPES, np.column_stack([s * (ev["competition_type"] == t) for t in TYPES])
    if spec == "stakes":
        return E1_GROUPS, np.column_stack([s * (ev["e1_group"] == g) for g in E1_GROUPS])
    if spec == "club":
        clubs = sorted(ev["club"].unique())
        return clubs, np.column_stack([s * (ev["club"] == c) for c in clubs])
    raise ValueError(spec)


def main_tests(panel, ev, ar_col="ar", errors="date", transform="level", match_dummies=False) -> dict:
    """H1 (drift), H2 (bad v good news drift), H3 (drift equal across competition types).
    match_dummies: also an indicator of any match at each lag, absorbing the abnormal returns
    around every match whatever its result (pre-match rise, post-match fall)."""
    out = {}

    def spec(name):
        names, values = surprise_values(ev, name, transform)
        if match_dummies:
            names, values = names + ["any"], np.column_stack([values, np.ones(len(ev))])
        return names, values

    f = Fit(panel, ev, *spec("main"), ar_col, errors)
    out["n_days"] = f.n
    out["b0"], out["b0_se"], out["b0_p"] = f.coef("S", [0])
    out["D"], out["D_se"], out["p_H1"] = f.coef("S", DRIFT)
    out["D5"], out["D5_se"], out["D5_p"] = f.coef("S", range(1, 6))
    out["D10"], out["D10_se"], out["D10_p"] = f.coef("S", range(1, 11))
    out["leak"], out["leak_se"], out["leak_p"] = f.coef("S", [-3, -2, -1])
    out["min_detectable_D"] = (1.96 + 0.84) * out["D_se"]
    a = Fit(panel, ev, *spec("asym"), ar_col, errors)
    for n in ("S_pos", "S_neg"):
        out[f"b0_{n}"] = a.coef(n, [0])[0]
        out[f"D_{n}"], out[f"D_{n}_se"], _ = a.coef(n, DRIFT)
    out["b0_neg_minus_pos"], _, out["p_b0_asym"] = a.diff("S_neg", "S_pos", [0])
    out["D_neg_minus_pos"], out["D_neg_minus_pos_se"], out["p_H2"] = a.diff("S_neg", "S_pos", DRIFT)
    c = Fit(panel, ev, *spec("competition"), ar_col, errors)
    for t in TYPES:
        out[f"b0_{t}"] = c.coef(t, [0])[0]
        out[f"D_{t}"], out[f"D_{t}_se"], _ = c.coef(t, DRIFT)
    _, out["p_H3"] = c.equal(TYPES, DRIFT)
    return out


# ---------------------------------------------------------------- event study

def e1_groups(events: pd.DataFrame, stakes_path: Path = PROCESSED / "league_stakes.csv") -> pd.Series:
    """E1 group of every match: 'stakes' (league, last 10 rounds, within 6 points of a line; from
    src/league_tables.py), 'late_no_stakes' (league, last 10 rounds, not within), 'rest' (all others)."""
    st = pd.read_csv(stakes_path, parse_dates=["date"], dtype={"season": str})
    st = st.drop_duplicates(["club", "date"]).set_index(["club", "date"])
    key = pd.MultiIndex.from_arrays([events["club"], events["date"]])
    league = (events["competition_type"] == "league").to_numpy()
    found = key.isin(st.index)
    if (league & ~found).any():
        print(f"  E1: {int((league & ~found).sum())} league matches not in league_stakes.csv, counted as rest")
    late = st["late"].reindex(key).fillna(False).astype(bool).to_numpy() & league
    with_stakes = st["stakes"].reindex(key).fillna(False).astype(bool).to_numpy() & league
    return pd.Series(np.where(with_stakes, "stakes", np.where(late, "late_no_stakes", "rest")), index=events.index)


def clean_events(ev: pd.DataFrame, before: int = CLEAN[0], after: int = CLEAN[1]) -> pd.Series:
    """True for matches with no other match of the club whose day 0 is within -before..+after rows."""
    clean = pd.Series(True, index=ev.index)
    for _, g in ev.groupby("club"):
        r = np.sort(g["row"].to_numpy())
        for i, row in zip(g.index, g["row"]):
            near = r[(r >= row - before) & (r <= row + after)]
            clean[i] = len(near) == 1
    return clean


def car_paths(panel, ev, before=CLEAN[0], after=CLEAN[1]) -> pd.DataFrame:
    """Cumulative abnormal return from day -before to +after of the clean matches, per match."""
    ar = panel["ar"].to_numpy()
    paths = []
    for e in ev.itertuples():
        lo, hi = e.row - before, e.row + after
        if lo < e.club_start or hi >= e.club_end:
            continue
        a = ar[lo:hi + 1]
        if np.isnan(a).any():
            continue
        paths.append([e.Index, e.surprise_tercile, *np.cumsum(a)])
    return pd.DataFrame(paths, columns=["event", "tercile", *range(-before, after + 1)])


def placebo(panel, ev, n: int = 500, seed: int = 0) -> np.ndarray:
    """Drift D with surprises shuffled across each club's matches (dates kept), n times."""
    rng = np.random.default_rng(seed)
    y = panel["ar"].to_numpy()
    ok = ~np.isnan(y)
    dates = panel["date"].to_numpy()[ok]
    out = []
    groups = [g.index.to_numpy() for _, g in ev.groupby("club")]
    for _ in range(n):
        s = ev["surprise"].to_numpy().copy()
        for idx in groups:
            s[idx] = rng.permutation(s[idx])
        X = lag_matrix(len(panel), ev, s[:, None])[ok]
        b, _ = ols(y[ok], X, dates)
        out.append(sum(b[1 + LAGS.index(k)] for k in DRIFT))
    return np.array(out)


def run_event_study(out_dir: Path = PROCESSED, fig_dir: Path = FIGURES, n_placebo: int = 500) -> pd.DataFrame:
    cfg, prices, cal, events = load_inputs()
    panel = club_panel(prices, cal, cfg)
    ev = locate_events(panel, events)
    print(f"{len(ev)} listed matches on the panel, {len(panel)} club trading days, "
          f"{panel['ar'].notna().sum()} with an abnormal return")

    # Coefficients of every specification
    coefs = []
    for spec in ("main", "terciles", "asym", "competition", "club"):
        names, values = surprise_values(ev, spec)
        f = Fit(panel, ev, names, values)
        for n in names:
            for k in LAGS:
                est, se, p = f.coef(n, [k])
                coefs.append({"spec": spec, "variable": n, "k": k, "estimate": est, "se": se, "p": p})
    coefs = pd.DataFrame(coefs)
    coefs.to_csv(out_dir / "event_study_coefficients.csv", index=False)

    # Main tests and robustness
    variants = {
        "main": dict(),
        "stoxx_benchmark": dict(panel=club_panel(prices, cal, cfg, benchmark=cfg.robustness_benchmark)),
        "liquid_clubs": dict(drop_clubs=ILLIQUID),
        "drop_stale_day0": dict(drop_events="stale_day0"),
        "trade_to_trade": dict(panel=club_panel(prices, cal, cfg, trade_to_trade=True)),
        "drop_near_close": dict(drop_events="near_close"),
        "with_alpha": dict(ar_col="ar_alpha"),
        "driscoll_kraay": dict(errors="dk"),
        "surprise_sign": dict(transform="sign"),
        "match_dummies": dict(match_dummies=True),
    }
    rows = []
    for name, v in variants.items():
        p = v.get("panel", panel)
        if "drop_clubs" in v:
            p = p[~p["club"].isin(v["drop_clubs"])].reset_index(drop=True)
        e_src = events[~events[v["drop_events"]]] if "drop_events" in v else events
        e = locate_events(p, e_src)
        res = main_tests(p, e, v.get("ar_col", "ar"), v.get("errors", "date"), v.get("transform", "level"),
                         v.get("match_dummies", False))
        rows.append({"variant": name, "matches": len(e), **res})
    tests = pd.DataFrame(rows)
    main = tests.iloc[0]
    adj = holm([main["p_H1"], main["p_H2"], main["p_H3"]])
    tests["p_H1_holm"], tests["p_H2_holm"], tests["p_H3_holm"] = np.nan, np.nan, np.nan
    tests.loc[0, ["p_H1_holm", "p_H2_holm", "p_H3_holm"]] = adj
    tests.to_csv(out_dir / "event_study_tests.csv", index=False)

    # Descriptive: clean matches
    clean = ev[clean_events(ev)]
    paths = car_paths(panel, clean)
    paths.to_csv(out_dir / "event_study_clean_car.csv", index=False)

    # Placebo
    pl = placebo(panel, ev, n_placebo) if n_placebo else np.array([])
    pd.DataFrame({"D": pl}).to_csv(out_dir / "event_study_placebo.csv", index=False)

    _print_results(tests, coefs, paths, pl)
    _event_figures(coefs, paths, fig_dir)
    return tests


SPLIT_GROUPS = {
    "E1": (["stakes", "late_no_stakes", "rest"], ("stakes", "late_no_stakes")),
    "E2": (["against", "with", "no_form"], ("against", "with")),
    "E3": (["early", "late"], ("early", "late")),
    "A1": (["big", "small"], ("big", "small")),
    "A2": (["gap", "next_day"], ("gap", "next_day")),
}
SPLIT_NAMES = {"E1": "stakes", "E2": "form", "E3": "period", "A1": "surprise size", "A2": "time to digest"}
FORM_MATCHES = 5
PERIOD_SPLIT = "1920"              # E3: seasons from 2019/20 are 'late'


def form_groups(events: pd.DataFrame) -> pd.Series:
    """E2: sum of the club's previous FORM_MATCHES surprises (all competitions, listed or not).
    'against' when this match's surprise has the other sign, 'with' the same sign, 'no_form' when
    either is 0 or the club has fewer than FORM_MATCHES earlier matches."""
    e = events.sort_values(["club", "date"])
    form = e.groupby("club")["surprise"].transform(lambda s: s.shift(1).rolling(FORM_MATCHES).sum())
    prod = np.sign(form) * np.sign(e["surprise"])
    g = np.select([prod < 0, prod > 0], ["against", "with"], "no_form")
    return pd.Series(g, index=e.index).reindex(events.index)


def split_groups(events: pd.DataFrame) -> pd.DataFrame:
    """Group of every match for each exploratory split.
    E1 stakes (src/league_tables.py), E2 form, E3 period (2012/13 to 2018/19 v 2019/20 to 2025/26),
    A1 surprise size (|S| in the top third of all matches: 'big'), A2 time to digest (day 0 two or
    more calendar days after the match, a weekend or holiday in between: 'gap'; else 'next_day')."""
    out = pd.DataFrame(index=events.index)
    out["E1"] = e1_groups(events)
    out["E2"] = form_groups(events)
    out["E3"] = np.where(events["season"] < PERIOD_SPLIT, "early", "late")
    size = events["surprise"].abs()
    out["A1"] = np.where(size >= size.quantile(2 / 3), "big", "small")
    out["A2"] = np.where((events["event_date"] - events["date"]).dt.days >= 2, "gap", "next_day")
    return out


def run_exploratory(out_dir: Path = PROCESSED, splits=tuple(SPLIT_GROUPS)) -> pd.DataFrame:
    """Exploratory splits (docs/step4_event_study.md, section 5 and "Exploratory splits"), no Holm
    correction. Each: the task 3 regression with S interacted with the split's groups, plain and with
    an indicator of any match at each lag per group (absorbs each group's match-week pattern; needed
    for E2, whose groups follow the sign of the surprise, like H2). Test: day 0 and drift of the two
    groups compared (E1: late league matches with and without stakes, same time of season); for
    three groups, all drifts equal too. Writes event_study_exploratory.csv (one row per split,
    variant and group, then a comparison row)."""
    cfg, prices, cal, events = load_inputs()
    events = events.join(split_groups(events))
    panel = club_panel(prices, cal, cfg)
    ev = locate_events(panel, events)
    rows = []
    for split in splits:
        groups, (a, b) = SPLIT_GROUPS[split]
        member = np.column_stack([ev[split] == g for g in groups]).astype(float)
        s = ev["surprise"].to_numpy()[:, None]
        for variant in ("plain", "match_dummies"):
            names, values = list(groups), member * s
            if variant == "match_dummies":
                names, values = names + [f"any_{g}" for g in groups], np.column_stack([values, member])
            f = Fit(panel, ev, names, values)
            for g in groups:
                b0, b0_se, b0_p = f.coef(g, [0])
                d, d_se, d_p = f.coef(g, DRIFT)
                rows.append({"split": split, "name": SPLIT_NAMES[split], "variant": variant, "group": g,
                             "n": int((ev[split] == g).sum()), "b0": b0, "b0_se": b0_se, "b0_p": b0_p,
                             "D": d, "D_se": d_se, "D_p": d_p})
            b0, b0_se, b0_p = f.diff(a, b, [0])
            d, d_se, d_p = f.diff(a, b, DRIFT)
            row = {"split": split, "name": SPLIT_NAMES[split], "variant": variant, "group": f"{a} - {b}",
                   "b0": b0, "b0_se": b0_se, "b0_p": b0_p, "D": d, "D_se": d_se, "D_p": d_p}
            if len(groups) == 3:
                _, row["p_D_all_equal"] = f.equal(groups, DRIFT)
            rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(out_dir / "event_study_exploratory.csv", index=False)
    pct = lambda x: f"{100 * x:+.3f}%"
    for (split, variant), g in out.groupby(["split", "variant"], sort=False):
        print(f"\n{split} {SPLIT_NAMES[split]} (exploratory), {variant}:")
        for r in g.itertuples():
            n = f"n {int(r.n):5d}" if pd.notna(r.n) else " " * 7
            print(f"  {r.group:24s} {n}  day 0 {pct(r.b0)} (p {r.b0_p:.3g})  drift {pct(r.D)} "
                  f"(se {100 * r.D_se:.3f}, p {r.D_p:.3g})")
    return out


def _print_results(tests, coefs, paths, pl):
    pct = lambda x: f"{100 * x:+.3f}%"
    m = tests.iloc[0]
    print("\nMain results (abnormal return per unit of surprise, % of price):")
    print(f"  day 0 reaction b0 = {pct(m.b0)} (se {100 * m.b0_se:.3f}, p {m.b0_p:.3g})")
    print(f"  H1 drift D = b1+b2+b3 = {pct(m.D)} (se {100 * m.D_se:.3f}, p {m.p_H1:.3g}, Holm {m.p_H1_holm:.3g}); "
          f"minimum detectable {100 * m.min_detectable_D:.3f}%")
    print(f"  drift to day 5 {pct(m.D5)} (p {m.D5_p:.3g}), to day 10 {pct(m.D10)} (p {m.D10_p:.3g})")
    print(f"  leak b-3..b-1 = {pct(m.leak)} (p {m.leak_p:.3g})")
    print(f"  H2 drift bad {pct(m.D_S_neg)} v good {pct(m.D_S_pos)}: p {m.p_H2:.3g} (Holm {m.p_H2_holm:.3g}); "
          f"day 0 bad {pct(m.b0_S_neg)} v good {pct(m.b0_S_pos)}: p {m.p_b0_asym:.3g}")
    print(f"  H3 drift league {pct(m.D_league)}, european {pct(m.D_european)}, other {pct(m.D_other)}: "
          f"p {m.p_H3:.3g} (Holm {m.p_H3_holm:.3g}); day 0 {pct(m.b0_league)}, {pct(m.b0_european)}, {pct(m.b0_other)}")
    print("\nRobustness:")
    print(tests[["variant", "matches", "b0", "D", "p_H1", "D_neg_minus_pos", "p_H2", "p_H3"]]
          .to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    c = coefs[coefs["spec"] == "club"]
    club = c[c["k"] == 0].set_index("variable")[["estimate", "se"]].rename(columns={"estimate": "b0", "se": "b0_se"})
    club["D"] = c[c["k"].isin(DRIFT)].groupby("variable")["estimate"].sum()
    print("\nPer club (descriptive, % per unit of surprise):")
    print((100 * club).round(3).to_string())
    if len(paths):
        print(f"\nClean matches: {len(paths)}; mean CAR (%) from day -{CLEAN[0]} by tercile:")
        print(paths.groupby("tercile")[list(range(-CLEAN[0], CLEAN[1] + 1))].mean().mul(100).round(3).to_string())
        print(paths.groupby("tercile").size().to_string())
    if len(pl):
        print(f"\nPlacebo D (shuffled surprises, {len(pl)} runs): mean {pct(pl.mean())}, sd {100 * pl.std():.3f}; "
              f"actual {pct(m.D)} beyond {np.mean(np.abs(pl) >= abs(m.D)):.1%} of runs")


def _event_figures(coefs, paths, fig_dir: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig_dir.mkdir(parents=True, exist_ok=True)
    m = coefs[coefs["spec"] == "main"].sort_values("k")
    cum = 100 * m["estimate"].cumsum()
    # Bands from the coefficient standard errors (covariances ignored: approximate)
    band = 196 * np.sqrt((m["se"] ** 2).cumsum())
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(m["k"], cum, marker="o")
    ax.fill_between(m["k"], cum - band, cum + band, alpha=0.2)
    ax.axhline(0, color="grey", lw=0.8)
    ax.axvline(0, color="grey", lw=0.8, ls=":")
    ax.set(xlabel="trading day relative to day 0", ylabel="cumulative % per unit of surprise",
           title="Cumulative response of abnormal returns to the surprise")
    fig.tight_layout()
    fig.savefig(fig_dir / "event_study_cumulative_response.png", dpi=150)
    plt.close(fig)

    if len(paths):
        fig, ax = plt.subplots(figsize=(7, 4))
        ks = list(range(-CLEAN[0], CLEAN[1] + 1))
        for t in ("high", "mid", "low"):
            g = paths[paths["tercile"] == t][ks]
            mean, sem = 100 * g.mean(), 196 * g.sem()
            ax.plot(ks, mean, marker="o", label=f"{t} surprise (n={len(g)})")
            ax.fill_between(ks, mean - sem, mean + sem, alpha=0.15)
        ax.axhline(0, color="grey", lw=0.8)
        ax.axvline(0, color="grey", lw=0.8, ls=":")
        ax.set(xlabel="trading day relative to day 0", ylabel=f"mean CAR from day -{CLEAN[0]} (%)",
               title=f"Mean CAR by surprise tercile, no other match within {CLEAN[0]} trading days")
        ax.legend()
        fig.tight_layout()
        fig.savefig(fig_dir / "event_study_clean_car.png", dpi=150)
        plt.close(fig)


# ---------------------------------------------------------------- backtest

def expanding_terciles(events: pd.DataFrame) -> pd.Series:
    """Tercile of each match's surprise with cutoffs from all earlier seasons only. NaN in the
    first season."""
    out = pd.Series(np.nan, index=events.index, dtype=object)
    for season in sorted(events["season"].unique()):
        past = events.loc[events["season"] < season, "surprise"]
        if past.empty:
            continue
        lo, hi = past.quantile([1 / 3, 2 / 3])
        cur = events["season"] == season
        s = events.loc[cur, "surprise"]
        out[cur] = np.select([s <= lo, s > hi], ["low", "high"], "mid")
    return out


def corwin_schultz(h: pd.DataFrame, skip_dates=()) -> pd.Series:
    """Daily two-day Corwin-Schultz spread estimates from High, Low, Close (overnight adjustment,
    negative estimates set to 0). Pairs with a zero-volume day or touching a skip date are left out."""
    hi, lo, cl = h["High"].to_numpy(float), h["Low"].to_numpy(float), h["Close"].to_numpy(float)
    hi1, lo1 = hi[1:].copy(), lo[1:].copy()
    up = lo1 - cl[:-1]
    hi1 = np.where(up > 0, hi1 - up, hi1)
    lo1 = np.where(up > 0, lo1 - up, lo1)
    down = cl[:-1] - hi1
    hi1 = np.where(down > 0, hi1 + down, hi1)
    lo1 = np.where(down > 0, lo1 + down, lo1)
    with np.errstate(divide="ignore", invalid="ignore"):
        beta = np.log(hi[:-1] / lo[:-1]) ** 2 + np.log(hi1 / lo1) ** 2
        gamma = np.log(np.maximum(hi[:-1], hi1) / np.minimum(lo[:-1], lo1)) ** 2
        k = 3 - 2 * math.sqrt(2)
        alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)
        s = np.maximum(2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha)), 0)
    vol = h["Volume"].to_numpy(float)
    dates = pd.DatetimeIndex(h["date"])
    bad = (vol[:-1] == 0) | (vol[1:] == 0) | ~np.isfinite(s)
    skip = pd.DatetimeIndex(pd.to_datetime(list(skip_dates)))
    bad |= dates[:-1].isin(skip) | dates[1:].isin(skip)
    return pd.Series(np.where(bad, np.nan, s), index=dates[1:])


def abdi_ranaldo(h: pd.DataFrame, skip_dates=()) -> pd.Series:
    """Daily terms 4 (c_t - eta_t)(c_t - eta_t+1) of the Abdi-Ranaldo (2017) estimator: c the log
    close, eta the mid-range (log high + log low) / 2. The spread of a period is the square root of
    their mean (0 if negative). Pairs with a zero-volume day or touching a skip date are left out."""
    c = np.log(h["Close"].to_numpy(float))
    eta = (np.log(h["High"].to_numpy(float)) + np.log(h["Low"].to_numpy(float))) / 2
    x = 4 * (c[:-1] - eta[:-1]) * (c[:-1] - eta[1:])
    vol = h["Volume"].to_numpy(float)
    dates = pd.DatetimeIndex(h["date"])
    bad = (vol[:-1] == 0) | (vol[1:] == 0) | ~np.isfinite(x)
    skip = pd.DatetimeIndex(pd.to_datetime(list(skip_dates)))
    bad |= dates[:-1].isin(skip) | dates[1:].isin(skip)
    return pd.Series(np.where(bad, np.nan, x), index=dates[1:])


def monthly_spreads(cfg, raw_dir: Path = RAW_PRICES, bloomberg_dir: Path = RAW_BLOOMBERG) -> pd.DataFrame:
    """Estimated quoted spread (relative) per club per month, `spread` used for costs. Yahoo clubs:
    Corwin-Schultz from daily high and low (`spread_cs`), except for stocks with high = low on more
    than half their traded days (one trade a day: Porto, Sporting), where it returns 0 and
    Abdi-Ranaldo from close, high and low (`spread_ar`) is used. Abdi-Ranaldo is not used
    throughout: it returns 0 for the Turkish clubs. Roma (Bloomberg, no high and low): mean
    (ask - bid) / mid from 24/06/2019 in all columns. Months without an estimate take the club's
    median month."""
    ca = cfg.corporate_actions
    out = []
    for _, c in cfg.clubs.dropna(subset=["ticker"]).iterrows():
        t = c["ticker"]
        months = pd.period_range("2012-01", "2026-12", freq="M")
        monthly = lambda s: s.groupby(s.index.to_period("M")).mean().reindex(months)
        if t.endswith(" Equity"):
            ar = cs = monthly(_bloomberg_quoted_spread(t, bloomberg_dir))
            single_trade = False
        else:
            h = pd.read_csv(_file(t, raw_dir), parse_dates=["date"])
            skip = list(ca.loc[ca["ticker"] == t, "date"]) + list(ca.loc[ca["ticker"] == t, "ex_date"])
            ar = np.sqrt(monthly(abdi_ranaldo(h, skip)).clip(lower=0))
            cs = monthly(corwin_schultz(h, skip))
            traded = h[h["Volume"] > 0]
            single_trade = (traded["High"] == traded["Low"]).mean() > 0.5
        ar, cs = ar.fillna(ar.median()).to_numpy(), cs.fillna(cs.median()).to_numpy()
        out.append(pd.DataFrame({"club": c["club"], "month": months, "spread": ar if single_trade else cs,
                                 "spread_cs": cs, "spread_ar": ar,
                                 "estimator": "abdi_ranaldo" if single_trade else "corwin_schultz"}))
    return pd.concat(out, ignore_index=True)


def _bloomberg_quoted_spread(ticker: str, bloomberg_dir: Path) -> pd.Series:
    for path in sorted(bloomberg_dir.glob("*.xlsx")):
        book = pd.ExcelFile(path)
        for sheet in book.sheet_names:
            if str(pd.read_excel(book, sheet, header=None, nrows=1).iloc[0, 0]).strip() != ticker:
                continue
            h = pd.read_excel(book, sheet, header=1)
            h.columns = [str(c).upper() for c in h.columns]
            h = h.dropna(subset=["DATE", "PX_BID", "PX_ASK"])
            h = h[(h["PX_BID"] > 0) & (h["PX_ASK"] >= h["PX_BID"])]
            mid = (h["PX_BID"] + h["PX_ASK"]) / 2
            return pd.Series(((h["PX_ASK"] - h["PX_BID"]) / mid).to_numpy(), index=pd.to_datetime(h["DATE"]))
    raise FileNotFoundError(f"no Bloomberg sheet for {ticker}")


def taxes_on_buy(club: str, day: pd.Timestamp) -> float:
    """Transaction taxes on a purchase (to verify, see the spec): Italian FTT 0.1% on Juventus
    (market value above EUR 500m for much of the period; applied throughout, conservative);
    UK stamp duty 0.5% on Celtic (AIM) before AIM shares were exempted on 28/04/2014."""
    if club == "Juventus":
        return 0.001
    if club == "Celtic" and day < pd.Timestamp("2014-04-28"):
        return 0.005
    return 0.0


def build_trades(panel, ev, spreads) -> pd.DataFrame:
    """One trade per match with a high or low surprise (expanding terciles): entry at the close of
    day 0, exit at the close of day +HOLD or of the day before the club's next day 0, whichever
    comes first. Hedged with beta (known on day 0) times the benchmark."""
    ev = ev.sort_values(["club", "row"]).reset_index(drop=True)
    ev["next_row"] = ev.groupby("club")["row"].shift(-1)
    spread = spreads.set_index(["club", "month"])["spread"]
    r, rm, beta = panel["r"].to_numpy(), panel["r_benchmark"].to_numpy(), panel["beta"].to_numpy()
    dates = panel["date"].to_numpy()
    trades = []
    for e in ev.itertuples():
        if e.signal not in ("high", "low") or np.isnan(beta[e.row]):
            continue
        exit_row = min(e.row + HOLD, (e.next_row - 1) if not np.isnan(e.next_row) else e.row + HOLD, e.club_end - 1)
        exit_row = int(exit_row)
        if exit_row <= e.row:
            continue
        side = 1 if e.signal == "high" else -1
        days = np.arange(e.row + 1, exit_row + 1)
        daily = side * (np.nan_to_num(r[days]) - beta[e.row] * np.nan_to_num(rm[days]))
        d_in, d_out = pd.Timestamp(dates[e.row]), pd.Timestamp(dates[exit_row])
        k_in = COMMISSION + (taxes_on_buy(e.club, d_in) if side == 1 else 0)
        k_out = COMMISSION + (taxes_on_buy(e.club, d_out) if side == -1 else 0)
        c_in = spread[(e.club, d_in.to_period("M"))] / 2 + k_in
        c_out = spread[(e.club, d_out.to_period("M"))] / 2 + k_out
        trades.append({"club": e.club, "match_date": e.date, "season": e.season, "competition_type": e.competition_type,
                       "surprise": e.surprise, "signal": e.signal, "side": side, "entry_date": d_in,
                       "exit_date": d_out, "days": len(days), "beta": beta[e.row],
                       "gross": float(np.prod(1 + daily) - 1), "cost": c_in + c_out,
                       "path_days": dates[days], "path_daily": daily, "cost_in": c_in, "cost_out": c_out,
                       "commission": k_in + k_out, "commission_in": k_in, "commission_out": k_out})
    t = pd.DataFrame(trades)
    t["net"] = t["gross"] - t["cost"]
    t["net_commission_only"] = t["gross"] - t["commission"]
    return t


def calendar_portfolio(trades: pd.DataFrame, costs: str, start, end) -> pd.Series:
    """Daily return of the equal weighted portfolio of open positions; 0 on days with none.
    costs: gross, net (spread, commission, taxes) or commission_only (commission and taxes)."""
    recs = []
    for t in trades.itertuples():
        d = t.path_daily.copy()
        if costs == "net":
            d[0] -= t.cost_in
            d[-1] -= t.cost_out
        elif costs == "commission_only":
            d[0] -= t.commission_in
            d[-1] -= t.commission_out
        recs.append(pd.DataFrame({"date": t.path_days, "r": d}))
    daily = pd.concat(recs).groupby("date")["r"].mean()
    idx = pd.bdate_range(start, end)
    return daily.reindex(idx.union(daily.index)).fillna(0.0)


def performance(trades: pd.DataFrame, daily: pd.Series, stoxx: pd.Series, costs: str) -> dict:
    tr = trades[{"gross": "gross", "net": "net", "commission_only": "net_commission_only"}[costs]]
    x = daily.to_numpy()
    mean = x.mean()
    xc = x - mean
    n = len(x)
    s = xc @ xc / n
    for l in range(1, 6):
        s += 2 * (1 - l / 6) * (xc[l:] @ xc[:-l]) / n
    wealth = np.cumprod(1 + x)
    j = pd.concat([daily.rename("p"), stoxx.rename("m")], axis=1, join="inner").dropna()
    return {"trades": len(trades), "mean_per_trade": tr.mean(), "median_per_trade": tr.median(),
            "hit_rate": (tr > 0).mean(), "cumulative_return": float(wealth[-1] - 1),
            "annual_return": mean * 252, "annual_vol": x.std() * np.sqrt(252),
            "sharpe": mean / x.std() * np.sqrt(252) if x.std() > 0 else np.nan,
            "t_newey_west": np.sqrt(n) * mean / np.sqrt(s),
            "max_drawdown": float((wealth / np.maximum.accumulate(wealth) - 1).min()),
            "breakeven_cost": trades["gross"].mean(), "mean_cost": trades["cost"].mean(),
            "beta_stoxx": float(np.polyfit(j["m"], j["p"], 1)[0])}


OOS_START = pd.Timestamp("2019-07-01")   # out-of-sample: seasons 2019/20 to 2025/26 (PERIOD_SPLIT)


def run_backtest(out_dir: Path = PROCESSED, fig_dir: Path = FIGURES) -> pd.DataFrame:
    """Backtest of the drift strategy (spec task 7). Metrics for the whole trading period and split
    into in-sample (2013/14 to 2018/19) and out-of-sample (2019/20 to 2025/26). The rules were fixed
    in the spec before any backtest was run; tercile cutoffs come from earlier seasons only
    (walk-forward), so the out-of-sample period never informs a signal in the in-sample one or
    vice versa. Writes backtest_summary.csv, backtest_daily.csv, backtest_trades.csv."""
    cfg, prices, cal, events = load_inputs()
    panel = club_panel(prices, cal, cfg)
    events = events.copy()
    events["signal"] = expanding_terciles(events)
    ev = locate_events(panel, events)
    spreads = monthly_spreads(cfg)
    spreads.assign(month=spreads["month"].astype(str)).to_csv(out_dir / "spreads_monthly.csv", index=False)
    trades = build_trades(panel, ev, spreads)
    start = trades["entry_date"].min()
    end = panel["date"].max()
    stoxx = prices[prices["ticker"] == cfg.robustness_benchmark].set_index("date")["adj_close"].pct_change()

    versions = {"long_short": trades, "long_only": trades[trades["side"] == 1]}
    rows, series = [], {}
    periods = {"full": (lambda t: t["season"] >= "0000", lambda d: d.index >= start),
               "in_sample": (lambda t: t["season"] < PERIOD_SPLIT, lambda d: d.index < OOS_START),
               "out_of_sample": (lambda t: t["season"] >= PERIOD_SPLIT, lambda d: d.index >= OOS_START)}
    for name, t in versions.items():
        for costs in ("gross", "commission_only", "net"):
            d = calendar_portfolio(t, costs, start, end)
            series[f"{name}_{costs}"] = d
            for period, (pick_trades, pick_days) in periods.items():
                rows.append({"version": name, "costs": costs, "period": period,
                             **performance(t[pick_trades(t)], d[pick_days(d)], stoxx, costs)})
    summary = pd.DataFrame(rows)
    summary.to_csv(out_dir / "backtest_summary.csv", index=False)
    pd.DataFrame(series).rename_axis("date").to_csv(out_dir / "backtest_daily.csv")
    trades.drop(columns=[c for c in trades if c.startswith("path_")]).to_csv(out_dir / "backtest_trades.csv", index=False)

    _backtest_checks(trades, ev, events)
    print("\nSpread estimates (median of monthly values, %):")
    sp = spreads.groupby("club")[["spread", "spread_cs", "spread_ar"]].median().mul(100).round(2)
    print(sp.join(spreads.groupby("club")["estimator"].first()).to_string())
    print("\nBacktest (trading from the second season; returns per trade and per year):")
    print(summary.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\nKey results (cumulative return, Sharpe, max drawdown; in-sample 2013/14-2018/19, "
          "out-of-sample 2019/20-2025/26):")
    key = summary.pivot_table(index=["version", "costs"], columns="period",
                              values=["cumulative_return", "sharpe", "max_drawdown"], sort=False)
    print(key.round(3).to_string())
    print("\nMean gross return per trade by signal and competition (%):")
    print((100 * trades.pivot_table(index="competition_type", columns="signal", values="gross", aggfunc="mean")).round(3).to_string())
    _backtest_figure(series, fig_dir)
    return summary


def _backtest_checks(trades, ev, events):
    first = sorted(events["season"].unique())[0]
    assert not (events.loc[events["season"] == first, "signal"].notna()).any(), "first season has a signal"
    assert (trades["entry_date"] >= trades["match_date"]).all(), "entry before the match"
    nxt = ev.sort_values(["club", "row"]).assign(nd=lambda d: d.groupby("club")["event_date"].shift(-1))
    nxt = nxt.dropna(subset=["nd"]).set_index(["club", "date"])["nd"]
    span = trades.set_index(["club", "match_date"])["exit_date"]
    common = span.index.intersection(nxt.index)
    assert (span[common] < nxt[common]).all(), "position held into the next match's day 0"
    print(f"Backtest checks passed: {len(trades)} trades; spot check:")
    print(trades.sample(5, random_state=1)[["club", "match_date", "signal", "entry_date", "exit_date", "days",
                                             "beta", "gross", "cost", "net"]].to_string(index=False))


def _backtest_figure(series: dict, fig_dir: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig_dir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 4))
    for label, d in series.items():
        ax.plot(d.index, np.cumprod(1 + d.to_numpy()), label=label.replace("_", " "))
    ax.axhline(1, color="grey", lw=0.8)
    ax.set_yscale("log")
    ax.set(ylabel="value of 1 invested (log scale)", title="Backtest: trading the drift after surprises")
    ax.legend()
    fig.tight_layout()
    fig.savefig(fig_dir / "backtest_cumulative.png", dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- match-week pattern

WEEK_LAGS = list(range(-5, 6))
PRE, POST = [-2, -1], [0, 1, 2, 3]


def match_week_fit(panel, ev):
    """AR on an indicator of any match of the club at each lag -5..+5, with the surprise at the same
    lags as a control: the abnormal return around a match whatever its result."""
    values = np.column_stack([np.ones(len(ev)), ev["surprise"].to_numpy()])
    return Fit(panel, ev, ["any", "S"], values, lags=WEEK_LAGS)


def _week_row(label, panel, ev):
    f = match_week_fit(panel, ev)
    pre, pre_se, pre_p = f.coef("any", PRE)
    post, post_se, post_p = f.coef("any", POST)
    return {"sample": label, "matches": len(ev), "pre": pre, "pre_se": pre_se, "pre_p": pre_p,
            "post": post, "post_se": post_se, "post_p": post_p}


def match_week_windows(panel, ev, spreads) -> pd.DataFrame:
    """Per match: abnormal return over the pre-match window (close of day -3 to close of day -1)
    and the post-match window (close of day -1 to close of day +3), whether another match of the
    club has its day 0 inside the window, and the round trip cost of trading the window."""
    ar = panel["ar"].to_numpy()
    dates = panel["date"].to_numpy()
    spread = spreads.set_index(["club", "month"])["spread"]
    ev = ev.sort_values(["club", "row"]).reset_index(drop=True)
    rows_by_club = {c: np.sort(g["row"].to_numpy()) for c, g in ev.groupby("club")}
    out = []
    for e in ev.itertuples():
        rec = {"club": e.club, "date": e.date, "season": e.season, "competition_type": e.competition_type,
               "surprise_tercile": e.surprise_tercile}
        for name, (a, b) in {"pre": (-2, -1), "post": (0, 3)}.items():
            lo, hi = e.row + a, e.row + b
            if lo - 1 < e.club_start or hi >= e.club_end or np.isnan(ar[lo:hi + 1]).any():
                rec[name] = np.nan
                continue
            others = rows_by_club[e.club]
            rec[name] = ar[lo:hi + 1].sum()
            rec[f"{name}_overlap"] = bool(((others >= lo) & (others <= hi) & (others != e.row)).any())
            month = pd.Timestamp(dates[lo - 1]).to_period("M")
            rec[f"{name}_cost"] = spread[(e.club, month)] + 2 * COMMISSION
        out.append(rec)
    return pd.DataFrame(out)


def run_match_week(out_dir: Path = PROCESSED, fig_dir: Path = FIGURES) -> pd.DataFrame:
    """The match-week pattern: regression profile, by period and club group, and per-match windows
    with the cost of trading them. See docs/step4_event_study.md, "Match-week pattern"."""
    cfg, prices, cal, events = load_inputs()
    panel = club_panel(prices, cal, cfg)
    ev = locate_events(panel, events)

    f = match_week_fit(panel, ev)
    coefs = []
    for k in WEEK_LAGS:
        est, se, p = f.coef("any", [k])
        cum, cum_se, _ = f.coef("any", [j for j in WEEK_LAGS if j <= k])
        coefs.append({"k": k, "estimate": est, "se": se, "p": p, "cumulative": cum, "cumulative_se": cum_se})
    coefs = pd.DataFrame(coefs)
    coefs.to_csv(out_dir / "match_week_coefficients.csv", index=False)

    rows = [_week_row("all", panel, ev)]
    early = panel["date"] < pd.Timestamp("2019-07-01")
    for label, keep in (("2012/13 to 2018/19", early), ("2019/20 to 2025/26", ~early)):
        p = panel.copy()
        p.loc[~keep, "ar"] = np.nan
        rows.append(_week_row(label, p, ev))
    liquid = panel[~panel["club"].isin(ILLIQUID)].reset_index(drop=True)
    rows.append(_week_row("liquid clubs", liquid, locate_events(liquid, events)))
    for t in TYPES:
        e = ev[ev["competition_type"] == t]
        rows.append(_week_row(f"{t} matches (others ignored)", panel, e.reset_index(drop=True)))
    tests = pd.DataFrame(rows)
    tests.to_csv(out_dir / "match_week_tests.csv", index=False)

    w = match_week_windows(panel, ev, monthly_spreads(cfg))
    w.to_csv(out_dir / "match_week_windows.csv", index=False)

    pct = lambda x: f"{100 * x:+.3f}%"
    print("Abnormal return around any match (surprise controlled), sum of days -2..-1 and 0..+3:")
    print(tests.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\nPer-match windows (abnormal return; cost = round trip spread + commission):")
    for name in ("pre", "post"):
        for label, d in (("all", w), ("no other match inside", w[w[f"{name}_overlap"] == False])):  # noqa: E712
            x = d[name].dropna()
            net = (x - d.loc[x.index, f"{name}_cost"]) if name == "pre" else (-x - d.loc[x.index, f"{name}_cost"])
            print(f"  {name:4s} {label:22s} n={len(x):5d} mean {pct(x.mean())} median {pct(x.median())} "
                  f"t {x.mean() / x.std() * np.sqrt(len(x)):+.2f}; trade ({'long' if name == 'pre' else 'short'}) "
                  f"after commission {pct((net + d.loc[x.index, f'{name}_cost'] - 2 * COMMISSION).mean())}, "
                  f"after all costs {pct(net.mean())}")
    print("\nPer club, mean and median (%):")
    g = w.groupby("club")
    print(pd.DataFrame({"pre_mean": g["pre"].mean(), "pre_median": g["pre"].median(),
                        "post_mean": g["post"].mean(), "post_median": g["post"].median()}).mul(100).round(2).to_string())
    _match_week_figure(coefs, fig_dir)
    return tests


def _match_week_figure(coefs, fig_dir: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig_dir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7, 4))
    cum, band = 100 * coefs["cumulative"], 196 * coefs["cumulative_se"]
    ax.plot(coefs["k"], cum, marker="o")
    ax.fill_between(coefs["k"], cum - band, cum + band, alpha=0.2)
    ax.axhline(0, color="grey", lw=0.8)
    ax.axvline(0, color="grey", lw=0.8, ls=":")
    ax.set(xlabel="trading day relative to day 0", ylabel="cumulative abnormal return (%)",
           title="Abnormal return around any match, surprise held fixed")
    fig.tight_layout()
    fig.savefig(fig_dir / "match_week_pattern.png", dpi=150)
    plt.close(fig)
