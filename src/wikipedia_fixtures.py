"""Club fixture lists from English Wikipedia season articles ("2016–17 FC Porto season").

Used to name competitions of Betfair rows (Betfair files do not say which competition a match
is in), to confirm friendlies, and to cross-check the event set. Text is CC BY-SA; the raw
wikitext is saved unmodified to data/raw/wikipedia/ as a snapshot.

Each article lists matches as {{football box collapsible}} templates under section headings:
the competition is the heading below "Competitions" (e.g. "UEFA Champions League"), and
friendlies sit under a heading such as "Pre-season and friendlies".
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

from .common import ROOT, load_config

RAW_WP = ROOT / "data" / "raw" / "wikipedia"
API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "matchday-alpha/0.1 (student research project)"

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], 1)}


def season_title(wikipedia_name: str, first_year: int) -> str:
    return f"{first_year}–{(first_year + 1) % 100:02d} {wikipedia_name} season"


def download_seasons(first_year: int, last_year: int, raw_dir: Path = RAW_WP, pause: float = 3.0) -> None:
    """Save the wikitext of every listed club's season article, first_year/first_year+1 to
    last_year/last_year+1, to raw_dir/{club}_{season}.json. Skips files already on disk. Requests
    are spaced `pause` seconds apart and back off on HTTP 429 (Wikipedia throttles bursts)."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    for _, row in cfg.clubs.iterrows():
        for year in range(first_year, last_year + 1):
            path = raw_dir / f"{row['club']}_{year}-{(year + 1) % 100:02d}.json"
            if path.exists():
                continue
            title = season_title(row["wikipedia_name"], year)
            query = urllib.parse.urlencode({"action": "parse", "page": title, "prop": "wikitext", "redirects": 1,
                                            "format": "json", "formatversion": 2})
            data = _get(f"{API}?{query}")
            if "error" in data:
                print(f"  no article: {title} ({data['error'].get('code')})")
                data = {"missing": title}
            path.write_text(json.dumps(data, ensure_ascii=False))
            time.sleep(pause)


def _get(url: str, tries: int = 6) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == tries - 1:
                raise
            time.sleep(int(e.headers.get("Retry-After", 5)) + 2 * attempt + 1)
    raise RuntimeError("unreachable")


# Parsing

_HEADING = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$", re.M)
_BOX = re.compile(r"\{\{\s*(?:football ?box(?: collapsible)?|footballbox(?: collapsible)?)\s*\|", re.I)
FRIENDLY_WORDS = ("friendl", "pre-season", "preseason", "international champions cup", "antalya cup")


def _template_end(text: str, start: int) -> int:
    depth, i = 0, start
    while i < len(text) - 1:
        two = text[i:i + 2]
        if two == "{{":
            depth += 1
            i += 2
        elif two == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                return i
        else:
            i += 1
    return len(text)


def _fields(body: str) -> dict[str, str]:
    """Top-level |key = value fields of a template body (nested templates and links kept whole)."""
    out, depth, cur = {}, 0, []
    parts = []
    i = 0
    while i < len(body):
        two = body[i:i + 2]
        if two in ("{{", "[["):
            depth += 1
            cur.append(two)
            i += 2
        elif two in ("}}", "]]"):
            depth -= 1
            cur.append(two)
            i += 2
        elif body[i] == "|" and depth == 0:
            parts.append("".join(cur))
            cur = []
            i += 1
        else:
            cur.append(body[i])
            i += 1
    parts.append("".join(cur))
    for part in parts:
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip().lower()] = v.strip()
    return out


def _plain(text: str) -> str:
    """Wikitext to plain text: [[A|B]] -> B, [[A]] -> A, templates and tags removed."""
    text = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>|<[^>]+>", "", text, flags=re.S)
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_date(text: str) -> pd.Timestamp | None:
    """Match date from a box's date field; None if missing or invalid (e.g. a typo like 31 June)."""
    try:
        return _parse_date(text)
    except ValueError:
        return None


def _parse_date(text: str) -> pd.Timestamp | None:
    m = re.search(r"\{\{\s*(?:start date|dts|date)[^|]*\|\s*(\d{4})\s*\|\s*(\d{1,2})\s*\|\s*(\d{1,2})", text, re.I)
    if m:
        return pd.Timestamp(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    plain = _plain(text)
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", plain) or None
    if m and m.group(2).lower() in MONTHS:
        return pd.Timestamp(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", plain)
    if m and m.group(1).lower() in MONTHS:
        return pd.Timestamp(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", plain)
    if m:
        return pd.Timestamp(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def parse_article(wikitext: str) -> pd.DataFrame:
    """One row per match box: date, team1, team2, score, aet, penalties, section (the nearest
    competition heading), friendly (True when the match sits under a friendlies heading)."""
    headings = [(m.start(), len(m.group(1)), _plain(m.group(2))) for m in _HEADING.finditer(wikitext)]
    rows = []
    for m in _BOX.finditer(wikitext):
        end = _template_end(wikitext, m.start())
        f = _fields(wikitext[m.end():end - 2])
        # heading path at this position: the latest heading of each level above it
        path: dict[int, str] = {}
        for pos, level, title in headings:
            if pos > m.start():
                break
            path = {k: v for k, v in path.items() if k < level}
            path[level] = title
        trail = [path[k] for k in sorted(path)]
        friendly = any(w in t.lower() for t in trail for w in FRIENDLY_WORDS)
        section = _competition_from_trail(trail)
        rows.append({"date": parse_date(f.get("date", "")), "time": _plain(f.get("time", "")),
                     "team1": _plain(f.get("team1", "")), "team2": _plain(f.get("team2", "")),
                     "score": _plain(f.get("score", "")), "aet": f.get("aet", "").lower() in ("yes", "y", "true"),
                     "penalties": _plain(f.get("penaltyscore", "")), "section": section, "friendly": friendly,
                     "trail": " > ".join(trail)})
    if not rows:  # articles that list matches in plain tables (Manchester United)
        rows = _parse_tables(wikitext, headings)
    return pd.DataFrame(rows, columns=["date", "time", "team1", "team2", "score", "aet", "penalties", "section",
                                       "friendly", "trail"])


def _trail_at(headings: list[tuple[int, int, str]], pos: int) -> list[str]:
    path: dict[int, str] = {}
    for hpos, level, title in headings:
        if hpos > pos:
            break
        path = {k: v for k, v in path.items() if k < level}
        path[level] = title
    return [path[k] for k in sorted(path)]


def _parse_tables(wikitext: str, headings: list[tuple[int, int, str]]) -> list[dict]:
    """Match rows of wikitables with Date, Opponent(s), H / A and Result columns. team1 is "(club)",
    team2 the opponent; these tables have no kickoff time, so `time` holds the venue (H, A or N)."""
    rows = []
    for m in re.finditer(r"\{\|.*?\n\|\}", wikitext, re.S):
        table = m.group(0)
        lines = table.split("\n")
        header = [_plain(c).lower() for ln in lines if ln.startswith("!") for c in re.split(r"!!|^!", ln) if c.strip()]
        if not header or "date" not in header[0] or not any(h.startswith("opponent") for h in header):
            continue
        col = {name: next((i for i, h in enumerate(header) if h.startswith(name)), None)
               for name in ("date", "opponent", "h / a", "result")}
        trail = _trail_at(headings, m.start())
        friendly = any(w in t.lower() for t in trail for w in FRIENDLY_WORDS)
        for block in re.split(r"\n\|-[^\n]*", table)[1:]:
            cells = [c for ln in block.split("\n") if ln.startswith("|") and not ln.startswith("|}")
                     for c in re.split(r"\|\|", ln[1:])]
            cells = [re.sub(r"^\s*[a-z-]+=\"?[^|]*\"?\s*\|", "", c) for c in cells]  # cell attributes
            if col["date"] is None or len(cells) <= max(v for v in col.values() if v is not None):
                continue
            date = parse_date(cells[col["date"]])
            if date is None:
                continue
            venue = _plain(cells[col["h / a"]]).upper()[:1] if col["h / a"] is not None else ""
            score = re.sub(r"\[\S+\s+([^\]]+)\]", r"\1", cells[col["result"]]) if col["result"] is not None else ""
            rows.append({"date": date, "time": venue, "team1": "(club)", "team2": _plain(cells[col["opponent"]]),
                         "score": _plain(score), "aet": "a.e.t" in score.lower() or "aet" in score.lower(),
                         "penalties": "", "section": _competition_from_trail(trail), "friendly": friendly,
                         "trail": " > ".join(trail)})
    return rows


_ROUND_WORDS = ("round", "stage", "matches", "group", "final", "play-off", "playoff", "qualif", "knockout",
                "results", "fixtures", "league table", "summary", "league phase", "league stage", "matchday")


def _competition_from_trail(trail: list[str]) -> str | None:
    """The competition heading: the deepest heading that is not a round or stage name, below
    'Competitions' when the article has one."""
    if "Competitions" in trail:
        trail = trail[trail.index("Competitions") + 1:]
    for title in reversed(trail):
        t = title.lower()
        if t and not any(w in t for w in _ROUND_WORDS):
            return title
    return trail[0] if trail else None


def load_fixtures(raw_dir: Path = RAW_WP) -> pd.DataFrame:
    """Every parsed match box of every saved article, with club and season."""
    frames = []
    for path in sorted(raw_dir.glob("*.json")):
        data = json.loads(path.read_text())
        if "parse" not in data:
            continue
        club, season = path.stem.rsplit("_", 1)
        df = parse_article(data["parse"]["wikitext"])
        frames.append(df.assign(club=club, season=season, article=data["parse"]["title"]))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# Kickoff times. Boxes give local time with a zone, usually with the UTC offset:
# "20:15 WEST (UTC+01:00)", "19:45 CET", "20:00 TRT (UTC+3)".
ZONE_OFFSETS = {"GMT": 0, "WET": 0, "UTC": 0, "BST": 1, "WEST": 1, "CET": 1, "CEST": 2, "EET": 2, "EEST": 3,
                "TRT": 3, "FET": 3, "MSK": 3, "EDT": -4, "EST": -5, "CDT": -5, "PDT": -7}


def kickoff_uk(time_text: str, date: pd.Timestamp) -> str | None:
    """Local kickoff time to UK time (HH:MM), using the explicit UTC offset if given, else the
    zone abbreviation. None when there is no time or no zone (the local zone is then unknown)."""
    if not isinstance(time_text, str) or date is None or pd.isna(date):
        return None
    m = re.search(r"(\d{1,2})[:.](\d{2})", time_text)
    if not m:
        return None
    off = re.search(r"UTC\s*([+\-−±])\s*(\d{1,2})(?::?(\d{2}))?", time_text)
    if off:
        sign = -1 if off.group(1) in "-−" else 1
        hours = sign * (int(off.group(2)) + int(off.group(3) or 0) / 60)
    else:
        zone = re.search(r"\b([A-Z]{3,4})\b", time_text[m.end():])
        if not zone or zone.group(1) not in ZONE_OFFSETS:
            return None
        hours = ZONE_OFFSETS[zone.group(1)]
    local = pd.Timestamp(date.year, date.month, date.day, int(m.group(1)), int(m.group(2)))
    utc = (local - pd.Timedelta(hours=hours)).tz_localize("UTC")
    return utc.tz_convert("Europe/London").strftime("%H:%M")


def kickoffs(wp: pd.DataFrame) -> pd.DataFrame:
    """Club, date, kickoff_time (UK) for every parsed match with a usable time."""
    if wp.empty:
        return pd.DataFrame(columns=["club", "date", "kickoff_time"])
    out = wp.dropna(subset=["date"]).copy()
    out["date"] = pd.to_datetime(out["date"])
    out["kickoff_time"] = [kickoff_uk(t, d) for t, d in zip(out["time"], out["date"])]
    return out.dropna(subset=["kickoff_time"])[["club", "date", "kickoff_time"]].drop_duplicates(["club", "date"])
