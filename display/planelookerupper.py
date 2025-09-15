#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Aircraft info scraper (JetPhotos + FlightRadar24) that does NOT error on empty results.

Changes vs prior:
- JetPhotos: if search has no matches, returns Images: [] and adds a Notice.
- Orchestrator never raises; it returns JSON with optional "Errors"/"Notices".
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import dataclasses
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
import ssl


# =================
# HTTP / TLS setup
# =================

CIPHERS = ":".join(
    [
        "ECDHE-RSA-AES128-GCM-SHA256",
        "ECDHE-RSA-AES256-GCM-SHA384",
        "ECDHE-ECDSA-AES128-GCM-SHA256",
        "ECDHE-ECDSA-AES256-GCM-SHA384",
    ]
)
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
)


class TLSAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context(ciphers=CIPHERS)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.maximum_version = ssl.TLSVersion.TLSv1_3
        super().init_poolmanager(*args, ssl_context=ctx, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        ctx = create_urllib3_context(ciphers=CIPHERS)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.maximum_version = ssl.TLSVersion.TLSv1_3
        kwargs["ssl_context"] = ctx
        return super().proxy_manager_for(*args, **kwargs)


def get_session(timeout_s: int = 10) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    s.mount("https://", TLSAdapter())
    s.mount("http://", HTTPAdapter())
    s.request_timeout = timeout_s
    return s


def fetch_html(url: str, session: Optional[requests.Session] = None) -> str:
    s = session or get_session()
    last_err: Optional[Exception] = None
    for attempt in range(3):
        try:
            resp = s.get(url, timeout=s.request_timeout)
            if resp.status_code == 200:
                ctype = resp.headers.get("Content-Type", "")
                if not ctype.startswith("text/html"):
                    raise RuntimeError(f"Content-Type not text/html: {ctype}")
                return resp.text
            if resp.status_code == 403 and attempt < 2:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {resp.status_code} for URL: {url}")
        except Exception as e:
            last_err = e
            if attempt >= 2:
                break
            time.sleep(0.3 * (attempt + 1))
    raise RuntimeError(f"Error sending request to {url}: {last_err}")


# =====================
# Tokenizer / Scraper
# =====================

@dataclass
class Token:
    kind: str  # "start" | "text"
    tag: Optional[str] = None
    attrs: Optional[Dict[str, str]] = None
    data: Optional[str] = None


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tokens: List[Token] = []

    def handle_starttag(self, tag, attrs):
        self.tokens.append(Token(kind="start", tag=tag, attrs=dict(attrs)))

    def handle_data(self, data):
        self.tokens.append(Token(kind="text", data=data))


class Scraper:
    def __init__(self, html_text: str):
        p = _Parser()
        p.feed(html_text)
        p.close()
        self.tokens: List[Token] = p.tokens
        self.pos: int = 0

    def _token_has_class(self, t: Token, cls: str) -> bool:
        # Be tolerant of class order and extra classes.
        # If caller passes multiple classes (space-separated), require all to be present.
        if not cls:
            return True
        if not t.attrs:
            return False
        tcls = t.attrs.get("class", "")
        if not tcls:
            return False
        # Normalize whitespace and compare as sets
        req = {c for c in cls.split() if c}
        have = {c for c in tcls.split() if c}
        return req.issubset(have)

    def _next_start(self, tag: str, cls: str) -> Token:
        for i in range(self.pos, len(self.tokens)):
            tok = self.tokens[i]
            if tok.kind == "start" and tok.tag == tag and self._token_has_class(tok, cls):
                self.pos = i + 1
                return tok
        raise RuntimeError(f"tag '{tag}' with class '{cls}' not found")

    def try_scrape_text(self) -> Tuple[str, bool]:
        i = self.pos
        while i < len(self.tokens) and self.tokens[i].kind == "text" and (self.tokens[i].data or "").strip() == "":
            i += 1
        if i >= len(self.tokens):
            return "", False
        tok = self.tokens[i]
        if tok.kind != "text":
            return "", False
        self.pos = i + 1
        return tok.data or "", True

    def _scrape_next(self, start_tag: str, cls: str, count: int, want_text: bool, scrape: bool) -> List[Token]:
        results: List[Token] = []
        at_least_one = False
        remaining = count
        while remaining > 0:
            try:
                tag_tok = self._next_start(start_tag, cls)
            except Exception as e:
                if at_least_one:
                    break
                raise e
            tok = tag_tok
            if want_text:
                text, ok = self.try_scrape_text()
                if not ok:
                    raise RuntimeError(f"Expected text after <{start_tag} class='{cls}'>")
                tok = Token(kind="text", data=text)
            if scrape:
                results.append(tok)
                at_least_one = True
            remaining -= 1
        return results

    def scrape_links(self, start_tag: str, cls: str, count: int) -> List[str]:
        toks = self._scrape_next(start_tag, cls, count, want_text=False, scrape=True)
        out: List[str] = []
        for t in toks:
            href = ""
            if t.attrs:
                # Prefer explicit href/src, then data-* fallbacks
                for k in ("href", "src", "data-src"):
                    if k in t.attrs and t.attrs[k]:
                        href = t.attrs[k]
                        break
                if not href:
                    for k in ("srcset", "data-srcset"):
                        if k in t.attrs and t.attrs[k]:
                            # Take the first URL from a srcset list
                            first = t.attrs[k].split(",")[0].strip().split()[0]
                            href = first
                            break
            out.append(href)
        return out

    def scrape_text(self, start_tag: str, cls: str, count: int) -> List[str]:
        toks = self._scrape_next(start_tag, cls, count, want_text=True, scrape=True)
        return [t.data or "" for t in toks]

    def advance(self, start_tag: str, cls: str, count: int) -> None:
        self._scrape_next(start_tag, cls, count, want_text=False, scrape=False)


# ==========================
# Site-specific scrapers
# ==========================

FR_AIRCRAFT_URL = "https://www.flightradar24.com/data/aircraft/"
FR_API_FLIGHTS_URL = "https://api.flightradar24.com/common/v1/flight/list.json"
JP_HOME_URL = "https://www.jetphotos.com"


@dataclass
class FlightAttributes:
    Date: str
    From: str
    To: str
    Flight: str
    FlightTime: str
    STD: str
    ATD: str
    STA: str
    Status: str


@dataclass
class FlightRadarResult:
    Aircraft: str
    Airline: str
    Operator: str
    TypeCode: str
    AirlineCode: str
    OperatorCode: str
    ModeS: str
    Flights: List[FlightAttributes]


@dataclass
class ImageAttributes:
    Image: str
    Link: str
    Thumbnail: str
    DateTaken: str
    DateUploaded: str
    Location: str
    Photographer: str
    Aircraft: str
    Serial: str
    Airline: str


@dataclass
class JetPhotosResult:
    Reg: str
    Images: List[ImageAttributes]


@dataclass
class ScrapeResult:
    JetPhotos: Optional[JetPhotosResult]
    FlightRadar: Optional[FlightRadarResult]
    Errors: List[str]
    Notices: List[str]


@dataclass
class APIQueries:
    Reg: str
    Photos: int = 1
    Flights: int = 5
    OnlyJP: bool = False
    OnlyFR: bool = False


def scrape_flightradar(q: APIQueries, session: Optional[requests.Session] = None) -> FlightRadarResult:
    reg = q.Reg
    url = f"{FR_AIRCRAFT_URL}{reg}"
    html = fetch_html(url, session=session)
    s = Scraper(html)

    aircraft = s.scrape_text("span", "details", 1)[0].strip()

    s.advance("span", "details", 1)
    airline, ok = s.try_scrape_text()
    if ok:
        airline = airline.strip()
    else:
        airline = s.scrape_text("a", "", 1)[0].strip()

    details = s.scrape_text("span", "details", 5)
    if len(details) != 5:
        raise RuntimeError(f"Unexpected details count for {reg} at {url}")
    operator = details[0].strip()
    type_code = details[1].strip()
    airline_code = details[2].strip()
    operator_code = details[3].strip()
    mode_s = details[4].strip()

    flights: List[FlightAttributes] = []

    # First try the public JSON API used by the FR24 webapp; fall back to HTML if blocked
    try:
        flights = _fetch_fr_api_flights(reg, q.Flights, session=session)
    except Exception:
        # Ignore and fall back to HTML scraping below
        flights = []

    if not flights:
        try:
            # Legacy HTML table parsing (structure may change over time)
            s.advance("td", "w40 hidden-xs hidden-sm", 3)
            for _ in range(q.Flights):
                flights.append(_scrape_fr_flight_row(s))
        except Exception:
            # No flights section or layout changed — leave empty
            pass

    return FlightRadarResult(
        Aircraft=aircraft,
        Airline=airline,
        Operator=operator,
        TypeCode=type_code,
        AirlineCode=airline_code,
        OperatorCode=operator_code,
        ModeS=mode_s,
        Flights=flights,
    )


def _scrape_fr_flight_row(s: Scraper) -> FlightAttributes:
    date = s.scrape_text("td", "hidden-xs hidden-sm", 1)[0].strip()
    ft = s.scrape_text("td", "text-center-sm hidden-xs hidden-sm", 2)
    from_airport = ft[0].strip()
    to_airport = ft[1].strip()
    s.advance("td", "hidden-xs hidden-sm", 1)
    flight = s.scrape_text("a", "fbold", 1)[0].strip()
    times = s.scrape_text("td", "hidden-xs hidden-sm", 4)
    flight_time = times[0].strip()
    std = times[1].strip()
    atd = times[2].strip()
    sta = times[3].strip()
    status_arr = s.scrape_text("td", "hidden-xs hidden-sm", 2)
    status = status_arr[1].strip()
    return FlightAttributes(Date=date, From=from_airport, To=to_airport, Flight=flight,
                            FlightTime=flight_time, STD=std, ATD=atd, STA=sta, Status=status)


def _fetch_fr_api_flights(reg: str, limit: int, session: Optional[requests.Session] = None) -> List[FlightAttributes]:
    """Fetch recent flights for a registration via FR24 JSON API.

    Falls back to empty list if unreachable or schema changes.
    """
    s = session or get_session()
    params = {
        "query": reg,
        "fetchBy": "reg",
        "limit": max(1, int(limit)),
        "page": 1,
    }
    headers = {
        "Accept": "application/json,text/plain,*/*",
        "Referer": f"{FR_AIRCRAFT_URL}{reg}",
    }
    r = s.get(FR_API_FLIGHTS_URL, params=params, headers=headers, timeout=getattr(s, "request_timeout", 10))
    if r.status_code != 200:
        raise RuntimeError(f"FR24 API HTTP {r.status_code}")
    js = r.json()

    def _safe_get(d: Dict[str, Any], path: List[str], default: Any = "") -> Any:
        cur: Any = d
        for p in path:
            if not isinstance(cur, dict) or p not in cur:
                return default
            cur = cur[p]
        return cur

    data_list = _safe_get(js, ["result", "response", "data"], [])
    flights: List[FlightAttributes] = []
    if not isinstance(data_list, list):
        return flights

    def _fmt_epoch(ts: Optional[int]) -> str:
        try:
            if not ts:
                return ""
            return time.strftime("%d %b %Y", time.localtime(int(ts)))
        except Exception:
            return ""

    def _tzinfo_from_fields(tz_name: Any, tz_offset: Any):
        # Try full tz database name first
        if tz_name and isinstance(tz_name, str) and ZoneInfo is not None:
            try:
                return ZoneInfo(tz_name)
            except Exception:
                pass
        # Fallback to numeric or string offset
        seconds: Optional[int] = None
        if isinstance(tz_offset, (int, float)):
            seconds = int(tz_offset)
        elif isinstance(tz_offset, str):
            # Accept forms like "+02:00", "-0700", "+2", "7200"
            s = tz_offset.strip()
            try:
                seconds = int(s)
            except Exception:
                sign = 1
                if s.startswith("+"):
                    s_ = s[1:]
                elif s.startswith("-"):
                    s_ = s[1:]
                    sign = -1
                else:
                    s_ = s
                parts = s_.split(":") if ":" in s_ else [s_[:-2], s_[-2:]] if len(s_) >= 3 and s_.isdigit() else [s_]
                try:
                    if len(parts) == 2:
                        hours = int(parts[0])
                        mins = int(parts[1])
                        seconds = sign * (hours * 3600 + mins * 60)
                    elif len(parts) == 1:
                        hours = int(parts[0])
                        seconds = sign * hours * 3600
                except Exception:
                    seconds = None
        if seconds is not None:
            try:
                return timezone(timedelta(seconds=seconds))
            except Exception:
                return None
        return None

    def _fmt_hhmm_tz(ts: Optional[int], tzinfo) -> str:
        try:
            if not ts:
                return ""
            if tzinfo is not None:
                dt = datetime.fromtimestamp(int(ts), tz=tzinfo)
                return dt.strftime("%H:%M")
            # Fallback to localtime if tz unknown
            return time.strftime("%H:%M", time.localtime(int(ts)))
        except Exception:
            return ""

    for item in data_list[:limit]:
        flight_num = _safe_get(item, ["identification", "number", "default"], "").strip()
        if not flight_num:
            # sometimes in historic entries it may be in callsign
            flight_num = _safe_get(item, ["identification", "callsign"], "").strip()

        org = _safe_get(item, ["airport", "origin"], {}) or {}
        dst = _safe_get(item, ["airport", "destination"], {}) or {}

        from_name = _safe_get(org, ["name"], "") or _safe_get(org, ["code", "iata"], "") or _safe_get(org, ["code", "icao"], "")
        to_name = _safe_get(dst, ["name"], "") or _safe_get(dst, ["code", "iata"], "") or _safe_get(dst, ["code", "icao"], "")

        # Timezone info for origin/destination
        org_tz_name = _safe_get(org, ["timezone", "name"], "") or _safe_get(org, ["timezone", "tz"], "")
        org_tz_offset = _safe_get(org, ["timezone", "offset"], None)
        dst_tz_name = _safe_get(dst, ["timezone", "name"], "") or _safe_get(dst, ["timezone", "tz"], "")
        dst_tz_offset = _safe_get(dst, ["timezone", "offset"], None)
        org_tzinfo = _tzinfo_from_fields(org_tz_name, org_tz_offset)
        dst_tzinfo = _tzinfo_from_fields(dst_tz_name, dst_tz_offset)

        sched_dep = _safe_get(item, ["time", "scheduled", "departure"]) or None
        sched_arr = _safe_get(item, ["time", "scheduled", "arrival"]) or None
        real_dep = _safe_get(item, ["time", "real", "departure"]) or None
        real_arr = _safe_get(item, ["time", "real", "arrival"]) or None

        # Prefer real date if present, else scheduled
        date_epoch = real_dep or sched_dep or real_arr or sched_arr
        date_str = _fmt_epoch(date_epoch)

        std = _fmt_hhmm_tz(sched_dep, org_tzinfo)
        sta = _fmt_hhmm_tz(sched_arr, dst_tzinfo)
        atd = _fmt_hhmm_tz(real_dep, org_tzinfo)

        # Flight time: prefer actual (real) if both present; else use scheduled
        flight_time = ""
        if real_dep and real_arr and isinstance(real_dep, int) and isinstance(real_arr, int) and real_arr >= real_dep:
            mins = int((real_arr - real_dep) // 60)
            flight_time = f"{mins//60:02d}:{mins%60:02d}"
        elif isinstance(sched_dep, int) and isinstance(sched_arr, int) and sched_arr >= sched_dep:
            mins = int((sched_arr - sched_dep) // 60)
            flight_time = f"{mins//60:02d}:{mins%60:02d}"

        status_text = _safe_get(item, ["status", "text"], "").strip()

        flights.append(
            FlightAttributes(
                Date=date_str,
                From=from_name or "",
                To=to_name or "",
                Flight=flight_num or "",
                FlightTime=flight_time,
                STD=std,
                ATD=atd,
                STA=sta,
                Status=status_text,
            )
        )

    return flights


def scrape_jetphotos(q: APIQueries, session: Optional[requests.Session] = None) -> Tuple[JetPhotosResult, Optional[str]]:
    reg = q.Reg
    if q.Photos == 0:
        return JetPhotosResult(Reg=reg.upper(), Images=[]), None

    search_url = f"{JP_HOME_URL}/photo/keyword/{reg}"
    html = fetch_html(search_url, session=session)
    s = Scraper(html)

    page_links: List[str] = []
    thumbnails: List[str] = []
    notice: Optional[str] = None

    for i in range(q.Photos):
        try:
            link = s.scrape_links("a", "result__photoLink", 1)
            thumb = s.scrape_links("img", "result__photo", 1)
        except Exception:
            # If nothing found on the very first attempt, treat as "no results"
            if i == 0:
                return JetPhotosResult(Reg=reg.upper(), Images=[]), f"JetPhotos: no results for {reg}"
            # Otherwise, we reached the end of the list
            break
        page_links.append(link[0])
        thumbnails.append(thumb[0])

    if not page_links and notice is None:
        notice = f"JetPhotos: no results for {reg}"

    images: List[ImageAttributes] = [
        ImageAttributes("", "", "", "", "", "", "", "", "", "") for _ in page_links
    ]

    def page_scraper(i: int, rel_link: str):
        photo_url = f"{JP_HOME_URL}{rel_link}"
        images[i].Link = photo_url
        thumb = thumbnails[i]
        images[i].Thumbnail = ("https:" + thumb) if thumb.startswith("//") else thumb

        phtml = fetch_html(photo_url, session=session)
        ps = Scraper(phtml)

        images[i].Image = ps.scrape_links("img", "large-photo__img", 1)[0]
        if images[i].Image.startswith("//"):
            images[i].Image = "https:" + images[i].Image
        hdr = ps.scrape_text("h4", "headerText4 color-shark", 3)
        images[i].DateTaken = hdr[1]
        images[i].DateUploaded = hdr[2]
        ps.advance("h2", "header-reset", 1)
        trio = ps.scrape_text("a", "link", 3)
        images[i].Aircraft = trio[0]
        images[i].Airline = trio[1]
        images[i].Serial = trio[2].strip()
        ps.advance("h5", "header-reset", 1)
        images[i].Location = ps.scrape_text("a", "link", 1)[0]
        images[i].Photographer = ps.scrape_text("h6", "header-reset", 1)[0]

    if page_links:
        with cf.ThreadPoolExecutor(max_workers=min(8, len(page_links))) as ex:
            futs = [ex.submit(page_scraper, i, link) for i, link in enumerate(page_links)]
            for f in cf.as_completed(futs):
                _ = f.result()

    return JetPhotosResult(Reg=reg.upper(), Images=images), notice


def scrape_all(q: APIQueries) -> ScrapeResult:
    session = get_session()
    jp_res: Optional[JetPhotosResult] = None
    fr_res: Optional[FlightRadarResult] = None
    errors: List[str] = []
    notices: List[str] = []

    def run_jp():
        nonlocal jp_res
        if q.OnlyFR:
            return
        try:
            jp, note = scrape_jetphotos(q, session=session)
            jp_res = jp
            if note:
                notices.append(note)
        except Exception as e:
            errors.append(f"JetPhotos: {e}")

    def run_fr():
        nonlocal fr_res
        if q.OnlyJP:
            return
        try:
            fr_res = scrape_flightradar(q, session=session)
        except Exception as e:
            errors.append(f"FlightRadar: {e}")

    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(run_jp), ex.submit(run_fr)]
        for f in cf.as_completed(futs):
            try:
                f.result()
            except Exception as e:
                errors.append(str(e))

    # Never raise; return whatever we have with messages
    return ScrapeResult(JetPhotos=jp_res, FlightRadar=fr_res, Errors=errors, Notices=notices)


# ==========================
# Public function & CLI
# ==========================

def get_aircraft_info(registration: str, photos: int = 1, flights: int = 5,
                      only_jp: bool = False, only_fr: bool = False) -> Dict[str, Any]:
    q = APIQueries(Reg=registration, Photos=photos, Flights=flights, OnlyJP=only_jp, OnlyFR=only_fr)
    res = scrape_all(q)

    def to_dict(obj):
        if obj is None:
            return None
        if dataclasses.is_dataclass(obj):
            d = {}
            for f in dataclasses.fields(obj):
                d[f.name] = to_dict(getattr(obj, f.name))
            return d
        if isinstance(obj, (list, tuple)):
            return [to_dict(x) for x in obj]
        return obj

    out = {
        "JetPhotos": to_dict(res.JetPhotos),
        "FlightRadar": to_dict(res.FlightRadar),
    }
    if res.Errors:
        out["Errors"] = res.Errors
    if res.Notices:
        out["Notices"] = res.Notices
    return out


def main():
    ap = argparse.ArgumentParser(description="Scrape JetPhotos + FlightRadar24 by registration (no hard errors on empty results).")
    ap.add_argument("registration", help="Aircraft registration, e.g., N274AK")
    ap.add_argument("--photos", type=int, default=1, help="Number of JetPhotos images to fetch (default 1)")
    ap.add_argument("--flights", type=int, default=5, help="Number of recent flights to fetch (default 5)")
    ap.add_argument("--only-jp", action="store_true", help="Only scrape JetPhotos")
    ap.add_argument("--only-fr", action="store_true", help="Only scrape FlightRadar24")
    ap.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = ap.parse_args()

    data = get_aircraft_info(
        args.registration,
        photos=args.photos,
        flights=args.flights,
        only_jp=args.only_jp,
        only_fr=args.only_fr,
    )

    if args.pretty:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(data, separators=(",", ":"), ensure_ascii=False))


if __name__ == "__main__":
    main()
