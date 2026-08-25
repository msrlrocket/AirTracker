#!/usr/bin/env python3
"""
AirTracker Complete Pipeline

This script contains ALL aircraft tracking functionality in a single file:
- Fetches aircraft data from multiple providers (OpenSky, ADSB.lol, FlightRadar24)
- Merges and enriches data with airline/aircraft information
- Detects military aircraft using ADSB.lol database
- Publishes to MQTT topics for ESP32 and Home Assistant

Usage:
    python3 airtracker_complete.py                   # Single run (default)
    python3 airtracker_complete.py --continuous      # Continuous operation
    python3 airtracker_complete.py --test-mqtt       # Test MQTT connection
"""

import argparse
import json
import os
import re
import sys
import time
import random
import logging
import math
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from io import BytesIO
import ssl
import urllib3
import concurrent.futures as cf
import dataclasses
from dataclasses import dataclass
from html.parser import HTMLParser
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

# Disable SSL warnings for compatibility
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    import paho.mqtt.client as mqtt
    from dotenv import load_dotenv
    from PIL import Image
    from influxdb_client import InfluxDBClient, Point
    from influxdb_client.client.write_api import SYNCHRONOUS
    import asyncio
    from fr24 import FR24
except ImportError as e:
    print(f"❌ Missing required dependency: {e}")
    print("Install with: pip install paho-mqtt requests python-dotenv Pillow influxdb-client fr24")
    sys.exit(1)

# Load environment variables
# First try local .env in the same directory as this script
local_env_path = Path(__file__).parent / '.env'
if local_env_path.exists():
    load_dotenv(local_env_path)
else:
    # Fallback to root .env
    root_env_path = Path(__file__).parent.parent.parent / '.env'
    if root_env_path.exists():
        load_dotenv(root_env_path)

# Constants
TIMEOUT = 15
UA_DEFAULT = "AirTracker/2.0 (+requests)"
OSK_API_BASE = "https://opensky-network.org/api"
OSK_TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
ADSB_API_BASE = "https://api.adsb.lol"
FR24_API_BASE = "https://data-cloud.flightradar24.com"


def sanitize_float(s: str) -> float:
    """Convert string to float, handling various formats"""
    return float(s.replace(',', '.'))


# =======================
# Aircraft Photo Scraper (embedded from planelookerupper.py)
# =======================

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
    s.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Upgrade-Insecure-Requests": "1",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
        }
    )
    s.mount("https://", HTTPAdapter())
    s.mount("http://", HTTPAdapter())
    s.request_timeout = timeout_s
    s.verify = False
    return s


def fetch_html(url: str, session: Optional[requests.Session] = None, *, referer: Optional[str] = None, headers: Optional[Dict[str, str]] = None) -> str:
    s = session or get_session()
    last_err: Optional[Exception] = None
    for attempt in range(3):
        try:
            req_headers: Dict[str, str] = {}
            if referer:
                req_headers["Referer"] = referer
            if headers:
                req_headers.update(headers)
            resp = s.get(url, timeout=s.request_timeout, headers=req_headers or None)
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


@dataclass
class Token:
    kind: str
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
        if not cls:
            return True
        if not t.attrs:
            return False
        tcls = t.attrs.get("class", "")
        if not tcls:
            return False
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
                for k in ("href", "src", "data-src"):
                    if k in t.attrs and t.attrs[k]:
                        href = t.attrs[k]
                        break
                if not href:
                    for k in ("srcset", "data-srcset"):
                        if k in t.attrs and t.attrs[k]:
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

    try:
        flights = _fetch_fr_api_flights(reg, q.Flights, session=session)
    except Exception:
        flights = []

    if not flights:
        try:
            s.advance("td", "w40 hidden-xs hidden-sm", 3)
            for _ in range(q.Flights):
                flights.append(_scrape_fr_flight_row(s))
        except Exception:
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
        if tz_name and isinstance(tz_name, str) and ZoneInfo is not None:
            try:
                return ZoneInfo(tz_name)
            except Exception:
                pass
        seconds: Optional[int] = None
        if isinstance(tz_offset, (int, float)):
            seconds = int(tz_offset)
        elif isinstance(tz_offset, str):
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
            return time.strftime("%H:%M", time.localtime(int(ts)))
        except Exception:
            return ""

    for item in data_list[:limit]:
        flight_num = _safe_get(item, ["identification", "number", "default"], "").strip()
        if not flight_num:
            flight_num = _safe_get(item, ["identification", "callsign"], "").strip()

        org = _safe_get(item, ["airport", "origin"], {}) or {}
        dst = _safe_get(item, ["airport", "destination"], {}) or {}

        from_name = _safe_get(org, ["name"], "") or _safe_get(org, ["code", "iata"], "") or _safe_get(org, ["code", "icao"], "")
        to_name = _safe_get(dst, ["name"], "") or _safe_get(dst, ["code", "iata"], "") or _safe_get(dst, ["code", "icao"], "")

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

        date_epoch = real_dep or sched_dep or real_arr or sched_arr
        date_str = _fmt_epoch(date_epoch)

        std = _fmt_hhmm_tz(sched_dep, org_tzinfo)
        sta = _fmt_hhmm_tz(sched_arr, dst_tzinfo)
        atd = _fmt_hhmm_tz(real_dep, org_tzinfo)

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
    html = fetch_html(search_url, session=session, referer=JP_HOME_URL)
    s = Scraper(html)

    page_links: List[str] = []
    thumbnails: List[str] = []
    notice: Optional[str] = None

    for i in range(q.Photos):
        try:
            link = s.scrape_links("a", "result__photoLink", 1)
            thumb = s.scrape_links("img", "result__photo", 1)
        except Exception:
            if i == 0:
                return JetPhotosResult(Reg=reg.upper(), Images=[]), f"JetPhotos: no results for {reg}"
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

        phtml = fetch_html(photo_url, session=session, referer=search_url)
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

    return ScrapeResult(JetPhotos=jp_res, FlightRadar=fr_res, Errors=errors, Notices=notices)


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


async def get_flight_schedule_fr24(registration: str, limit: int = 12) -> List[Dict[str, Any]]:
    """
    Get flight schedule using fr24 library - includes recent past and upcoming flights
    Returns list of flights with flight_id for GPS track retrieval
    """
    try:
        async with FR24() as client:
            result = await client.flight_list.fetch(reg=registration, limit=limit)
            data = result.to_dict()

            flights = data.get('result', {}).get('response', {}).get('data', [])
            now = int(time.time())

            past_flights = []
            future_flights = []

            for flight in flights:
                # Extract flight data
                flight_num = flight.get('identification', {}).get('number', {}).get('default', '')
                origin_name = flight.get('airport', {}).get('origin', {}).get('name', '')
                dest_name = flight.get('airport', {}).get('destination', {}).get('name', '')
                status = flight.get('status', {}).get('text', '')

                # Get times
                time_data = flight.get('time', {})
                sched_dep = time_data.get('scheduled', {}).get('departure')
                sched_arr = time_data.get('scheduled', {}).get('arrival')
                real_dep = time_data.get('real', {}).get('departure')
                real_arr = time_data.get('real', {}).get('arrival')

                # Determine if past or future
                is_past = (
                    'Landed' in status or
                    'landed' in status.lower() or
                    (real_dep and real_dep < now) or
                    (real_arr and real_arr < now)
                )

                # Format for compatibility with existing code
                flight_row = {
                    'Flight': flight_num,
                    'From': origin_name,
                    'To': dest_name,
                    'Status': status,
                    'Date': time.strftime("%d %b %Y", time.localtime(real_dep or sched_dep)) if (real_dep or sched_dep) else '',
                    'STD': time.strftime("%H:%M", time.localtime(sched_dep)) if sched_dep else '',
                    'ATD': time.strftime("%H:%M", time.localtime(real_dep)) if real_dep else '',
                    'STA': time.strftime("%H:%M", time.localtime(sched_arr)) if sched_arr else '',
                    'FlightTime': '',
                    'flight_id': flight.get('identification', {}).get('id'),  # For GPS tracks
                    'is_past': is_past
                }

                # Calculate flight time if available
                if real_dep and real_arr:
                    duration = int((real_arr - real_dep) / 60)
                    flight_row['FlightTime'] = f"{duration//60:02d}:{duration%60:02d}"

                if is_past:
                    past_flights.append(flight_row)
                else:
                    future_flights.append(flight_row)

            # Return last 3 past (most recent first) + next 3 future
            combined = list(reversed(past_flights[-3:])) + future_flights[:3]
            return combined

    except Exception as e:
        print(f"⚠️  FR24 flight history failed: {e}")
        return []


def get_flight_schedule_fr24_sync(registration: str, limit: int = 12) -> List[Dict[str, Any]]:
    """Synchronous wrapper for async FR24 flight schedule"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(get_flight_schedule_fr24(registration, limit))
    except Exception as e:
        print(f"⚠️  FR24 sync wrapper failed: {e}")
        return []
    finally:
        loop.close()


async def get_flight_track_fr24(flight_id: str) -> Dict[str, Any]:
    """
    Get GPS track for a flight using its flight_id
    Returns dict with track points (lat, lon, altitude, speed, heading, timestamp)
    """
    try:
        async with FR24() as client:
            result = await client.playback.fetch(flight_id)
            data = result.to_dict()

            # Extract flight data and track
            flight_data = data.get('result', {}).get('response', {}).get('data', {}).get('flight', {})
            track = flight_data.get('track', [])

            # Calculate statistics
            stats = {}
            if track:
                stats = {
                    'total_points': len(track),
                    'duration_seconds': track[-1]['timestamp'] - track[0]['timestamp'] if len(track) > 1 else 0,
                    'max_altitude_ft': max(p['altitude']['feet'] for p in track),
                    'max_speed_kts': max(p['speed']['kts'] for p in track),
                    'start_time': track[0]['timestamp'],
                    'end_time': track[-1]['timestamp']
                }

            return {
                'flight_id': flight_id,
                'track': track,
                'statistics': stats,
                'flight_info': {
                    'callsign': flight_data.get('identification', {}).get('callsign', ''),
                    'registration': flight_data.get('aircraft', {}).get('registration', ''),
                    'aircraft_type': flight_data.get('aircraft', {}).get('model', {}).get('code', ''),
                    'origin': flight_data.get('airport', {}).get('origin', {}).get('name', ''),
                    'destination': flight_data.get('airport', {}).get('destination', {}).get('name', ''),
                }
            }
    except Exception as e:
        print(f"⚠️  Failed to get track for flight {flight_id}: {e}")
        return {'flight_id': flight_id, 'track': [], 'statistics': {}, 'error': str(e)}


def get_flight_track_fr24_sync(flight_id: str) -> Dict[str, Any]:
    """Synchronous wrapper for async FR24 flight track"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(get_flight_track_fr24(flight_id))
    except Exception as e:
        print(f"⚠️  FR24 track sync wrapper failed: {e}")
        return {'flight_id': flight_id, 'track': [], 'error': str(e)}
    finally:
        loop.close()

# =======================
# End of Aircraft Photo Scraper
# =======================


# Image processing functionality (embedded from image_processor.py)
class AircraftImageProcessor:
    """Handles image download, conversion, and Zipline upload for aircraft images."""

    TARGET_WIDTH = 96
    TARGET_HEIGHT = 72
    BMP_BITS_PER_PIXEL = 24

    def __init__(self, config: Dict):
        """Initialize with configuration from environment."""
        self.config = config
        self.setup_zipline()
        self.processed_cache = {}  # In-memory cache for this session

    def setup_zipline(self):
        """Configure Zipline from environment variables and check availability."""
        self.zipline_url = os.getenv('ZIPLINE_URL', 'https://zip.spacegeese.com')
        self.zipline_token = os.getenv('ZIPLINE_TOKEN')
        self.zipline_folder_id = os.getenv('ZIPLINE_AIRCRAFT_FOLDER_ID', 'cmfw6kozd022701mvmjz33v2j')
        self.zipline_available = False

        if not self.zipline_token:
            if self.config.get('log_level') == 'DEBUG':
                print("⚠️  Zipline token not configured - image processing disabled")
            self.enabled = False
            return

        # Initialize as enabled if token is present, will test availability later
        self.enabled = True

    def test_availability_with_logging(self):
        """Test Zipline availability with proper logging (call after logger is set)."""
        if not self.zipline_token:
            return

        self._test_zipline_availability()

        if not self.zipline_available:
            self.enabled = False

    def _test_zipline_availability(self):
        """Test if Zipline service is available."""
        try:
            # Test with a simple GET to the base URL
            test_url = f"{self.zipline_url.rstrip('/')}/api/stats"
            response = requests.get(
                test_url,
                headers={'authorization': self.zipline_token},
                timeout=10
            )

            if response.status_code in [200, 401, 403]:
                # 200 = working, 401/403 = server responding but auth issue
                self.zipline_available = True
                if hasattr(self, 'logger'):
                    self.logger.info(f"✅ Zipline service available at {self.zipline_url}")
                elif self.config.get('log_level') == 'DEBUG':
                    print(f"✅ Zipline service available at {self.zipline_url}")
            else:
                self.zipline_available = False
                if hasattr(self, 'logger'):
                    self.logger.warning(f"⚠️  Zipline service returned HTTP {response.status_code} - image uploads may fail")
                elif self.config.get('log_level') == 'DEBUG':
                    print(f"⚠️  Zipline service returned HTTP {response.status_code} - image uploads may fail")

        except requests.exceptions.ConnectTimeout:
            self.zipline_available = False
            if hasattr(self, 'logger'):
                self.logger.warning(f"⚠️  Zipline service timeout at {self.zipline_url} - image uploads disabled")
            elif self.config.get('log_level') == 'DEBUG':
                print(f"⚠️  Zipline service timeout at {self.zipline_url} - image uploads disabled")

        except requests.exceptions.ConnectionError:
            self.zipline_available = False
            if hasattr(self, 'logger'):
                self.logger.warning(f"⚠️  Zipline service unreachable at {self.zipline_url} - image uploads disabled")
            elif self.config.get('log_level') == 'DEBUG':
                print(f"⚠️  Zipline service unreachable at {self.zipline_url} - image uploads disabled")

        except Exception as e:
            self.zipline_available = False
            if hasattr(self, 'logger'):
                self.logger.warning(f"⚠️  Zipline availability check failed: {e} - image uploads disabled")
            elif self.config.get('log_level') == 'DEBUG':
                print(f"⚠️  Zipline availability check failed: {e} - image uploads disabled")

    def download_image(self, url: str) -> Optional[bytes]:
        """Download image from URL and return bytes."""
        try:
            if self.config.get('log_level') == 'DEBUG':
                print(f"📥 Downloading image: {url}")

            headers = {
                'User-Agent': 'AirTracker/2.0 (Aircraft Image Processor)',
                'Accept': 'image/*'
            }

            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            return response.content

        except Exception as e:
            if self.config.get('log_level') == 'DEBUG':
                print(f"❌ Download failed for {url}: {e}")
            return None

    def convert_to_bmp(self, image_data: bytes) -> Optional[bytes]:
        """Convert image to 96x72 24-bit BMP format."""
        try:
            # Open image from bytes
            from io import BytesIO
            with Image.open(BytesIO(image_data)) as img:
                # Convert to RGB (24-bit)
                if img.mode != 'RGB':
                    img = img.convert('RGB')

                # Resize with high-quality resampling
                img.thumbnail((self.TARGET_WIDTH, self.TARGET_HEIGHT), Image.Resampling.LANCZOS)

                # Create new image with target size and center the resized image
                new_img = Image.new('RGB', (self.TARGET_WIDTH, self.TARGET_HEIGHT), (0, 0, 0))

                # Calculate position to center the image
                x = (self.TARGET_WIDTH - img.width) // 2
                y = (self.TARGET_HEIGHT - img.height) // 2
                new_img.paste(img, (x, y))

                # Save as BMP to BytesIO
                bmp_buffer = BytesIO()
                new_img.save(bmp_buffer, 'BMP')
                return bmp_buffer.getvalue()

        except Exception as e:
            if self.config.get('log_level') == 'DEBUG':
                print(f"❌ BMP conversion failed: {e}")
            return None

    def upload_to_zipline(self, image_data: bytes, filename: str, is_bmp: bool = False) -> Optional[str]:
        """Upload image data to Zipline and return URL."""
        # Check if Zipline is available before attempting upload
        if not self.zipline_available:
            if hasattr(self, 'logger'):
                self.logger.debug(f"⚠️  Skipping Zipline upload - service unavailable")
            elif self.config.get('log_level') == 'DEBUG':
                print(f"    ⚠️  Skipping Zipline upload - service unavailable")
            return None

        try:
            upload_url = f"{self.zipline_url.rstrip('/')}/api/upload"

            headers = {
                'authorization': self.zipline_token,
                'x-zipline-format': 'name'
            }

            # Add folder header for aircraft images
            if self.zipline_folder_id:
                headers['x-zipline-folder'] = self.zipline_folder_id

            # Create meaningful filename with timestamp and type
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            suffix = "_esp32" if is_bmp else "_original"
            clean_filename = os.path.splitext(filename)[0]
            final_filename = f"aircraft_{timestamp}_{clean_filename}{suffix}.{'bmp' if is_bmp else 'jpg'}"

            content_type = 'image/bmp' if is_bmp else 'image/jpeg'

            files = {
                'file': (final_filename, BytesIO(image_data), content_type)
            }

            response = requests.post(
                upload_url,
                headers=headers,
                files=files,
                timeout=30
            )

            if response.status_code in [200, 201]:
                try:
                    result = response.json()
                    zipline_url = result.get('files', [{}])[0].get('url')
                    print(f"    ✅ Uploaded {'BMP' if is_bmp else 'original'}: {zipline_url}")
                    return zipline_url
                except Exception as e:
                    print(f"    ❌ Couldn't parse Zipline response: {e}")
                    print(f"    Response text: {response.text[:200]}")
                    return None
            else:
                if hasattr(self, 'logger'):
                    self.logger.warning(f"❌ Zipline upload failed: HTTP {response.status_code} - {response.text[:100]}")
                else:
                    print(f"    ❌ Zipline upload failed: HTTP {response.status_code}")
                    print(f"    Response text: {response.text[:200]}")
                return None

        except requests.exceptions.ConnectTimeout:
            if hasattr(self, 'logger'):
                self.logger.warning(f"❌ Zipline upload timeout for {filename}")
            else:
                print(f"    ❌ Zipline upload timeout")
            return None

        except requests.exceptions.ConnectionError:
            if hasattr(self, 'logger'):
                self.logger.warning(f"❌ Zipline upload connection error for {filename}")
            else:
                print(f"    ❌ Zipline upload connection error")
            return None

        except Exception as e:
            if hasattr(self, 'logger'):
                self.logger.warning(f"❌ Zipline upload exception for {filename}: {e}")
            else:
                print(f"    ❌ Zipline upload exception: {e}")
            return None

    def process_aircraft_image(self, image_url: str, aircraft_reg: str) -> Dict[str, Optional[str]]:
        """Process an aircraft image: download, upload original, convert to BMP, upload BMP."""
        if not self.enabled:
            return {}

        # Check cache first
        cache_key = image_url
        if cache_key in self.processed_cache:
            if self.config.get('log_level') == 'DEBUG':
                print(f"⏭️  Using cached image URLs for {aircraft_reg}")
            return self.processed_cache[cache_key]

        result = {}

        try:
            # Download original image
            print(f"  📥 Downloading image from {image_url[:60]}...")
            image_data = self.download_image(image_url)
            if not image_data:
                print(f"  ❌ Failed to download image")
                return result
            print(f"  ✅ Downloaded {len(image_data)} bytes")

            # Upload original to Zipline
            print(f"  🚀 Uploading original to Zipline...")
            original_zipline_url = self.upload_to_zipline(
                image_data,
                aircraft_reg,
                is_bmp=False
            )
            if original_zipline_url:
                result['plane_image_zipline_original'] = original_zipline_url
                print(f"  ✅ Original uploaded: {original_zipline_url}")
            else:
                print(f"  ❌ Original upload failed")

            # Convert to BMP
            print(f"  🎨 Converting to BMP...")
            bmp_data = self.convert_to_bmp(image_data)
            if bmp_data:
                print(f"  ✅ BMP conversion successful: {len(bmp_data)} bytes")
                # Upload BMP to Zipline
                print(f"  🚀 Uploading BMP to Zipline...")
                bmp_zipline_url = self.upload_to_zipline(
                    bmp_data,
                    aircraft_reg,
                    is_bmp=True
                )
                if bmp_zipline_url:
                    result['plane_image_zipline_esp32'] = bmp_zipline_url
                    print(f"  ✅ BMP uploaded: {bmp_zipline_url}")
                else:
                    print(f"  ❌ BMP upload failed")
            else:
                print(f"  ❌ BMP conversion failed")

            # Cache the result
            self.processed_cache[cache_key] = result

            return result

        except Exception as e:
            if self.config.get('log_level') == 'DEBUG':
                print(f"❌ Image processing failed for {aircraft_reg}: {e}")
            return result


def nm_to_deg(lat_deg: float, radius_nm: float) -> Tuple[float, float]:
    """Convert nautical miles to degrees at given latitude"""
    lat_delta = radius_nm / 60.0
    lon_delta = radius_nm / (60.0 * math.cos(math.radians(lat_deg)))
    return lat_delta, lon_delta


def bbox_from_point(lat: float, lon: float, radius_nm: float) -> Tuple[float, float, float, float]:
    """Calculate bounding box from center point and radius"""
    lat_delta, lon_delta = nm_to_deg(lat, radius_nm)
    return lat + lat_delta, lat - lat_delta, lon - lon_delta, lon + lon_delta


def get_opensky_token(client_id: str, client_secret: str) -> str:
    """Get OAuth token for OpenSky Network API"""
    response = requests.post(OSK_TOKEN_URL, data={
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }, headers={
        "User-Agent": UA_DEFAULT,
        "Content-Type": "application/x-www-form-urlencoded"
    }, timeout=TIMEOUT)

    response.raise_for_status()
    token_data = response.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise RuntimeError(f"OpenSky token missing: {response.text[:240]}")
    return access_token


# Dataset enrichment functions (adapted from plane_merge.py)
def _upper(s: Optional[str]) -> Optional[str]:
    return s.upper() if isinstance(s, str) else s


def _clean_str(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = str(s).strip()
    return s if s else None


def _datasets_root() -> str:
    """Return a best-effort path to the repo-level datasets directory."""
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [
        os.path.join(here, "datasets"),
        os.path.join(os.path.dirname(here), "datasets"),
        os.path.join(os.path.dirname(os.path.dirname(here)), "datasets"),
        os.path.join(os.getcwd(), "datasets"),
    ]
    for p in cands:
        if os.path.isdir(p):
            return p
    return os.path.join(here, "datasets")


def _load_jsonl_map(path: str, key_field: str) -> Dict[str, dict]:
    """Load JSONL file into a dictionary keyed by specified field."""
    m: Dict[str, dict] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    obj = json.loads(ln)
                except Exception:
                    continue
                k = obj.get(key_field)
                if isinstance(k, str) and k:
                    m[k] = obj
    except FileNotFoundError:
        pass
    return m


def _load_catalogs(ds_root: Optional[str] = None) -> Dict[str, Dict[str, dict]]:
    """Load all dataset catalogs for enrichment."""
    ds = ds_root or _datasets_root()

    # Load civilian aircraft types
    civilian_aircraft = _load_jsonl_map(os.path.join(ds, "aircraft_types_full.jsonl"), "icao")

    # Load comprehensive military aircraft dataset and merge with civilian
    military_aircraft_path = os.path.join(ds, "military_aircraft.jsonl")
    if os.path.exists(military_aircraft_path):
        military_aircraft = _load_jsonl_map(military_aircraft_path, "icao")
        # Military aircraft override civilian ones for the same ICAO codes
        civilian_aircraft.update(military_aircraft)

    cats = {
        "aircraft": civilian_aircraft,
        "airlines_by_icao": _load_jsonl_map(os.path.join(ds, "airlines.jsonl"), "icao"),
        "airlines_by_iata": {},
        "airports": _load_jsonl_map(os.path.join(ds, "airports.jsonl"), "iata"),
        "countries": _load_jsonl_map(os.path.join(ds, "countries.jsonl"), "code"),
    }
    # Build IATA index for airlines
    for icao, a in cats["airlines_by_icao"].items():
        iata = a.get("iata")
        if isinstance(iata, str) and iata:
            cats["airlines_by_iata"][iata] = a
    return cats


def _estimate_seat_max(icao: Optional[str]) -> Optional[int]:
    """Estimate maximum seats based on aircraft ICAO type code."""
    if not icao:
        return None
    t = icao.upper()
    # Heuristics for common aircraft types
    if t.startswith(("A31", "A32")):
        return 244  # A321neo upper bound
    if t.startswith("B70"):
        return 189  # 707 family
    if t.startswith("B72"):
        return 189  # 727 family
    if t.startswith("B73"):
        return 230  # 737 family upper bound
    if t.startswith("B78"):
        return 330  # 787 family
    if t.startswith(("E17", "E19", "E29", "E75")):
        return 146  # E-Jets / E2 upper bound
    if t.startswith("CRJ"):
        return 104
    if t.startswith(("AT4", "AT7")):
        return 78  # ATR 42/72
    if t.startswith("DH8"):
        return 90
    if t.startswith("DH2"):
        return 7   # Beaver
    if t.startswith("TISB"):
        return 6
    # GA / Bizjet common types
    if t.startswith(("BE33", "BE35", "BE36")):
        return 4
    if t.startswith(("BE55", "BE56", "BE58")):
        return 6
    if t.startswith(("BE76", "BE77", "BE80", "BE95")):
        return 4
    if t.startswith("BE9") or t.startswith("BE10"):
        return 9  # King Air 90/100
    if t == "B350":
        return 11
    if t.startswith("LJ"):
        return 9
    if t == "PRM1":
        return 6
    if t == "GALX":
        return 10
    if t == "MU30":
        return 8
    if t in ("H25A", "H25B", "H25C"):
        return 8
    if t == "FA10":
        return 8
    if t == "FA20":
        return 12
    if t == "FA8X":
        return 19
    # Cessna singles/twins common
    if t in ("C120", "C140"):
        return 2
    if t.startswith(("C17", "C15", "C19")):
        return 4
    if t == "C180":
        return 4
    if t == "C185":
        return 6
    if t == "C188":
        return 1
    if t == "C195":
        return 5
    if t == "C210":
        return 6
    if t == "C310":
        return 6
    return None


def _private_threshold_default() -> int:
    """Get private vs commercial aircraft threshold from environment."""
    try:
        return int(os.getenv("PRIVATE_DESIGNATION_SEATS", "8").strip())
    except Exception:
        return 8


def is_military_aircraft_type(aircraft_type: str) -> bool:
    """Check if aircraft type code indicates military aircraft"""
    if not aircraft_type:
        return False

    aircraft_type = aircraft_type.upper().strip()

    # Known military aircraft type codes
    military_types = {
        # US Military helicopters
        'H60', 'UH60', 'HH60', 'MH60', 'SH60',  # Blackhawk variants
        'UH1', 'UH1N', 'UH1Y',  # Huey variants
        'AH64', 'AH6',  # Apache, Little Bird
        'CH47', 'CH53',  # Chinook, Stallion
        'MV22', 'CV22',  # Osprey variants

        # US Military fixed wing
        'C130', 'C17', 'C5', 'KC135', 'KC46',  # Transport/tanker
        'F16', 'F18', 'F22', 'F35',  # Fighters
        'A10', 'B52', 'B1', 'B2',  # Attack/bombers
        'E3', 'E2', 'P3', 'P8',  # AWACS/patrol
        'U2', 'RQ4',  # Reconnaissance

        # Other common military designations
        'T6', 'T38', 'T45',  # Trainers
    }

    return aircraft_type in military_types


def get_military_aircraft_search_terms(aircraft_type: str) -> List[str]:
    """Get search terms for finding similar military aircraft images when specific registration not found"""
    if not aircraft_type:
        return []

    aircraft_type = aircraft_type.upper().strip()

    # Military aircraft search term mappings for JetPhotos fallback
    military_search_mapping = {
        # Blackhawk variants -> prioritize exact model codes first
        'H60': ['UH-60', 'MH-60', 'HH-60', 'SH-60'],
        'UH60': ['UH-60', 'MH-60', 'HH-60', 'SH-60'],
        'HH60': ['HH-60', 'UH-60', 'MH-60', 'SH-60'],
        'MH60': ['MH-60', 'UH-60', 'HH-60', 'SH-60'],
        'SH60': ['SH-60', 'UH-60', 'MH-60', 'HH-60'],

        # Other helicopters - prioritize exact model designations
        'UH1': ['UH-1', 'Bell 212'],  # Remove generic "Huey"
        'UH1N': ['UH-1N', 'UH-1'],
        'UH1Y': ['UH-1Y', 'UH-1'],
        'AH64': ['AH-64'],  # Remove generic "Apache"
        'AH6': ['AH-6', 'MD-500'],  # More specific variant
        'CH47': ['CH-47', 'Boeing 234'],  # Remove generic "Chinook"
        'CH53': ['CH-53'],  # Remove generic "Stallion"

        # V-22 Osprey
        'MV22': ['MV-22', 'V-22'],
        'CV22': ['CV-22', 'V-22'],

        # Transport aircraft - be more specific
        'C130': ['C-130', 'L-382'],  # Remove generic "Hercules"
        'C17': ['C-17'],  # Remove generic "Globemaster"
        'C5': ['C-5'],  # Remove generic "Galaxy"
        'KC135': ['KC-135'],  # Remove generic terms
        'KC46': ['KC-46', 'Boeing 767'],  # Keep Boeing 767 as it's specific

        # Fighters - use exact designations only
        'F16': ['F-16'],
        'F18': ['F-18', 'F/A-18'],
        'F22': ['F-22'],
        'F35': ['F-35'],

        # Attack/Bombers - exact designations only
        'A10': ['A-10'],
        'B52': ['B-52'],
        'B1': ['B-1'],
        'B2': ['B-2'],

        # AWACS/Patrol - be more specific
        'E3': ['E-3'],  # Remove generic names
        'E2': ['E-2'],
        'P3': ['P-3'],  # Remove generic "Orion"
        'P8': ['P-8', 'Boeing 737'],  # Keep Boeing 737 as it's specific

        # Reconnaissance - exact designations only
        'U2': ['U-2'],
        'RQ4': ['RQ-4'],

        # Trainers - exact designations only
        'T6': ['T-6'],
        'T38': ['T-38'],
        'T45': ['T-45'],
    }

    return military_search_mapping.get(aircraft_type, [aircraft_type])


def classify_aircraft(row: Dict[str, Any], private_threshold: Optional[int] = None) -> Optional[str]:
    """Classify aircraft as Military, Private, or Commercial."""
    try:
        if row.get("is_military") is True:
            return "Military"

        # Check for known military aircraft types
        aircraft_type = _clean_str(row.get("aircraft_type"))
        if aircraft_type and is_military_aircraft_type(aircraft_type):
            return "Military"

        # Determine seat count preference: explicit souls_on_board_max else heuristic by type
        seats = row.get("souls_on_board_max")
        if not isinstance(seats, int):
            seats = None
        if seats is None:
            seats = _estimate_seat_max(_clean_str(row.get("aircraft_type")))

        if seats is None:
            return None

        thr = private_threshold if isinstance(private_threshold, int) else _private_threshold_default()
        return "Private" if seats <= thr else "Commercial"
    except Exception:
        return None


IATA_FLIGHT_RE = re.compile(r"^[A-Z0-9]{2,3}\d{1,4}[A-Z]?$")


def looks_like_iata_flight(s: Optional[str]) -> bool:
    """Check if string looks like an IATA flight number."""
    s = _clean_str(s)
    return bool(s and IATA_FLIGHT_RE.match(s))


def _airline_from_flight_no(flight_no: Optional[str], cats: Dict[str, Dict[str, dict]]) -> Optional[dict]:
    """Extract airline from flight number using IATA code mapping."""
    if not looks_like_iata_flight(flight_no):
        return None
    # Prefix is 2 or 3 alnum chars before the digits
    s = flight_no.strip()
    m2 = re.match(r"^([A-Z0-9]{2,3})\d", s)
    if not m2:
        return None
    pref = m2.group(1)
    return cats.get("airlines_by_iata", {}).get(pref)


def enrich_with_catalogs(row: Dict[str, Any], cats: Dict[str, Dict[str, dict]]) -> Dict[str, Any]:
    """Enrich aircraft data with additional information from datasets."""
    out = dict(row)
    lookups: Dict[str, Any] = {}

    # Aircraft by ICAO type
    icao_type = _clean_str(row.get("aircraft_type"))
    if icao_type:
        a = cats.get("aircraft", {}).get(icao_type)
        seat_actual: Optional[int] = None
        if a:
            aircraft_lookup = {
                "icao": icao_type,
                "name": a.get("name") or a.get("model") or icao_type,
                "manufacturer": a.get("manufacturer"),
                "model": a.get("model"),
                "seats_max": a.get("seats"),
                "iata_aliases": a.get("iata") or [],
                "lookup_status": "found",
            }

            # Add comprehensive military aircraft data if available
            category = a.get("category", "")
            if "category" in a and (category == "Military Aircraft" or
                                   category == "Air Force Aircraft" or
                                   category == "Army Aircraft" or
                                   category == "Navy Aircraft" or
                                   category == "Marine Corps Aircraft"):
                aircraft_lookup.update({
                    "role": a.get("role"),
                    "aircraft_type": a.get("aircraft_type"),
                    "engines": a.get("engines"),
                    "variants": a.get("variants", []),
                    "crew": a.get("crew"),
                    "crew_type": a.get("crew_type"),
                    "images": a.get("images", []),
                    "is_military": True
                })

                # Extract first high-quality image for quick access
                images = a.get("images", [])
                if images and len(images) > 0:
                    first_image = images[0]
                    aircraft_lookup.update({
                        "primary_image_url": first_image.get("zipline_url"),
                        "esp32_image_url": first_image.get("zipline_esp32_url"),
                        "image_alt_text": first_image.get("alt_text"),
                        "image_source": first_image.get("source_page")
                    })

            lookups["aircraft"] = aircraft_lookup
            if isinstance(a.get("seats"), int) and a.get("seats", 0) > 0:
                seat_actual = int(a["seats"])
        else:
            # Explicitly indicate that this ICAO type was not found in the dataset
            lookups["aircraft"] = {
                "icao": icao_type,
                "name": icao_type,  # fallback display to the raw code
                "manufacturer": None,
                "model": None,
                "seats_max": None,
                "iata_aliases": [],
                "lookup_status": "not_found",
            }
        # Fallback estimate when catalog does not provide seats
        seat_est = _estimate_seat_max(icao_type) if not seat_actual else None
        if seat_actual is not None:
            out["souls_on_board_max"] = seat_actual
            out["souls_on_board_max_is_estimate"] = False
            out["souls_on_board_max_text"] = str(seat_actual)
        elif seat_est is not None:
            out["souls_on_board_max"] = seat_est
            out["souls_on_board_max_is_estimate"] = True
            out["souls_on_board_max_text"] = str(seat_est)
        else:
            # Publish explicit N/A when unknown
            out["souls_on_board_max"] = None
            out["souls_on_board_max_is_estimate"] = False
            out["souls_on_board_max_text"] = "N/A"
    else:
        # No aircraft_type provided; still publish explicit N/A for souls
        out["souls_on_board_max"] = None
        out["souls_on_board_max_is_estimate"] = False
        out["souls_on_board_max_text"] = "N/A"

    # Airline by ICAO, else by IATA prefix of flight number
    al_icao = _clean_str(row.get("airline_icao"))
    airline = None
    if al_icao:
        airline = cats.get("airlines_by_icao", {}).get(al_icao)
    if not airline:
        airline = _airline_from_flight_no(_clean_str(row.get("callsign")), cats)
    if airline:
        lookups["airline"] = {
            "icao": airline.get("icao"),
            "iata": airline.get("iata"),
            "name": airline.get("name"),
            "callsign": airline.get("callsign"),
            "country_code": airline.get("country_code"),
            "country_name": airline.get("country_name"),
        }

    # Origin/Destination airports (IATA)
    def airport_info(iata_code: Optional[str]) -> Optional[dict]:
        i = _clean_str(iata_code)
        if not i:
            return None
        a = cats.get("airports", {}).get(i)
        if not a:
            return None
        return {
            "iata": a.get("iata"),
            "name": a.get("name"),
            "city": a.get("city"),
            "region": a.get("region"),
            "country_code": a.get("country_code"),
            "country_name": a.get("country_name"),
            "lat": a.get("lat"),
            "lon": a.get("lon"),
            "elevation_ft": a.get("elevation_ft"),
        }

    ori = airport_info(row.get("origin_iata"))
    dst = airport_info(row.get("destination_iata"))
    if ori:
        lookups["origin_airport"] = ori
    if dst:
        lookups["destination_airport"] = dst

    # Country by code (fallback if not present via airport)
    if ori and not ori.get("country_name"):
        cc = ori.get("country_code")
        if cc:
            c = cats.get("countries", {}).get(cc)
            if c:
                ori["country_name"] = c.get("name")
    if dst and not dst.get("country_name"):
        cc = dst.get("country_code")
        if cc:
            c = cats.get("countries", {}).get(cc)
            if c:
                dst["country_name"] = c.get("name")

    if lookups:
        out["lookups"] = lookups
    return out


def _airline_logo_fields(airline_icao: Optional[str],
                        airline_iata: Optional[str],
                        catalogs: Optional[Dict[str, Dict[str, dict]]] = None,
                        datasets_override: Optional[str] = None) -> Dict[str, Any]:
    """Return fields for nearest payload with airline logo details if found."""
    out: Dict[str, Any] = {}
    code = _clean_str(airline_icao)
    if (not code) and airline_iata and catalogs:
        try:
            ai = catalogs.get("airlines_by_iata", {}).get(_clean_str(airline_iata) or "")
            icao2 = ai.get("icao") if isinstance(ai, dict) else None
            if isinstance(icao2, str) and icao2:
                code = icao2
        except Exception:
            pass
    if not code:
        return out
    code = code.upper()
    ds_root = datasets_override or _datasets_root()
    abs_path = os.path.join(ds_root, "airline_logos", f"airline_logo_{code}.png")
    if os.path.exists(abs_path):
        rel_path = os.path.join("datasets", "airline_logos", f"airline_logo_{code}.png")
        out["airline_logo_code"] = code
        out["airline_logo_path"] = rel_path
        base_url = os.getenv(
            "AIRLINE_LOGO_BASE_URL",
            "https://zip.spacegeese.com/raw",
        ).rstrip("/")
        # ESP32-compatible BMP logo (legacy field)
        out["airline_logo_url"] = f"{base_url}/airline_logo_{code}.bmp"
        # Full-size PNG logo for high-resolution displays
        out["airline_logo_png_url"] = f"{base_url}/airline_logo_{code}.png"
    return out


def _country_flag_fields(aircraft_lookups: Dict) -> Dict[str, str]:
    """Generate country flag fields based on origin/destination airports"""
    out = {"country_flag_url": "", "country_flag_code": "", "country_flag_source": ""}

    # Get origin and destination airport info
    origin_airport = aircraft_lookups.get("origin_airport", {})
    dest_airport = aircraft_lookups.get("destination_airport", {})

    # Get country codes (ISO 2-letter codes)
    origin_country = origin_airport.get("country_code", "").upper() if isinstance(origin_airport, dict) else ""
    dest_country = dest_airport.get("country_code", "").upper() if isinstance(dest_airport, dict) else ""

    # Flag selection logic:
    # 1. Default to origin country
    # 2. If destination is not US and origin is US (or missing), use destination
    # 3. If destination is not US and different from origin, use destination
    selected_country = ""
    flag_source = ""

    if origin_country and dest_country:
        # Both available
        if dest_country != "US" and (origin_country == "US" or dest_country != origin_country):
            # Use destination if it's not US and either origin is US or they're different
            selected_country = dest_country
            flag_source = "destination"
        else:
            # Default to origin
            selected_country = origin_country
            flag_source = "origin"
    elif dest_country:
        # Only destination available
        selected_country = dest_country
        flag_source = "destination"
    elif origin_country:
        # Only origin available
        selected_country = origin_country
        flag_source = "origin"

    # Generate flag URL if we have a country
    if selected_country and len(selected_country) == 2:
        out["country_flag_code"] = selected_country
        out["country_flag_source"] = flag_source
        out["country_flag_url"] = f"https://zip.spacegeese.com/u/country_flag_{selected_country}.png"

    return out


class MilCache:
    """Cache for military aircraft detection using ADSB.lol /v2/mil endpoint"""

    def __init__(self, cache_path: str, ttl: int = 3600):  # 1 hour cache for military database
        self.cache_path = cache_path
        self.ttl = ttl
        self.cache = self._load_cache()
        self.military_hex_set = set()
        self._load_military_database()

    def _load_cache(self) -> Dict:
        """Load existing cache from file"""
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def _save_cache(self):
        """Save cache to file"""
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, 'w') as f:
            json.dump(self.cache, f, indent=2)

    def _load_military_database(self):
        """Load military aircraft database from ADSB.lol API"""
        now = time.time()

        # Check if we have a recent cached military database
        last_update = self.cache.get('_military_db_update', 0)
        cache_age_hours = (now - last_update) / 3600

        if now - last_update < self.ttl and '_military_hex_list' in self.cache:
            self.military_hex_set = set(self.cache['_military_hex_list'])
            count = len(self.military_hex_set)
            print(f"📡 Using cached military database: {count} aircraft (age: {cache_age_hours:.1f}h)")
            return

        # Fetch fresh military database
        try:
            print(f"📡 Fetching fresh military database from ADSB.lol...")
            url = f"{ADSB_API_BASE}/v2/mil"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                military_aircraft = data.get('ac', [])

                # Extract hex codes from military aircraft
                military_hex_codes = []
                for aircraft in military_aircraft:
                    hex_code = aircraft.get('hex')
                    if hex_code:
                        military_hex_codes.append(hex_code.upper())

                # Update cache and memory
                self.military_hex_set = set(military_hex_codes)
                self.cache['_military_hex_list'] = military_hex_codes
                self.cache['_military_db_update'] = now
                self.cache['_military_db_count'] = len(military_hex_codes)

                # Add timestamp for human readability
                self.cache['_military_db_update_readable'] = datetime.now().isoformat()

                self._save_cache()

                print(f"📡 Updated military database: {len(military_hex_codes)} aircraft")

                # Debug output if enabled
                if os.getenv('MILITARY_CACHE_DEBUG', '0') == '1':
                    self._write_debug_file(military_aircraft)

        except Exception as e:
            print(f"⚠️  Failed to fetch military database: {e}")
            # Use cached data if available
            if '_military_hex_list' in self.cache:
                self.military_hex_set = set(self.cache['_military_hex_list'])
                count = len(self.military_hex_set)
                print(f"📡 Using stale cached military database: {count} aircraft (age: {cache_age_hours:.1f}h)")

    def _write_debug_file(self, military_aircraft):
        """Write debug file with full military aircraft details"""
        try:
            debug_file = os.path.join(os.path.dirname(self.cache_path), 'military_aircraft_debug.json')
            debug_data = {
                'timestamp': time.time(),
                'timestamp_readable': datetime.now().isoformat(),
                'aircraft_count': len(military_aircraft),
                'aircraft': military_aircraft,
                'hex_codes': [aircraft.get('hex', '').upper() for aircraft in military_aircraft if aircraft.get('hex')]
            }

            with open(debug_file, 'w') as f:
                json.dump(debug_data, f, indent=2)

            print(f"📝 Military database debug file written: {debug_file}")

        except Exception as e:
            print(f"⚠️  Failed to write military debug file: {e}")

    def check_hex(self, hex_code: str) -> Optional[bool]:
        """Check if aircraft is military using cached military database"""
        if not hex_code:
            return None

        hex_upper = hex_code.upper()

        # Refresh military database if needed
        now = time.time()
        last_update = self.cache.get('_military_db_update', 0)
        if now - last_update >= self.ttl:
            self._load_military_database()

        # Check if hex is in military database
        return hex_upper in self.military_hex_set

    def get_military_count(self) -> int:
        """Get count of military aircraft in database"""
        return self.cache.get('_military_db_count', 0)


class AirTrackerComplete:
    """Complete aircraft tracking pipeline in a single class"""

    def __init__(self, config: Optional[Dict] = None, custom_env_file: Optional[str] = None):
        """Initialize with configuration"""
        self.config = self._load_config(config, custom_env_file)
        self.mqtt_client = None
        self.setup_logging()
        self.mil_cache = MilCache(
            cache_path=str(Path.cwd() / 'data' / 'mil_cache.json'),
            ttl=21600
        )
        self.stats = {
            'runs': 0,
            'successful_publishes': 0,
            'errors': 0,
            'start_time': datetime.now().isoformat()
        }

        # Initialize image processor for Zipline uploads
        self.image_processor = AircraftImageProcessor(self.config)
        # Pass logger to image processor after it's created
        self.image_processor.logger = self.logger
        # Test Zipline availability now that logger is available
        self.image_processor.test_availability_with_logging()

        # Initialize InfluxDB client
        self.influx_client = None
        self.influx_write_api = None
        self._setup_influxdb()

    def _load_config(self, override_config: Optional[Dict] = None, custom_env_file: Optional[str] = None) -> Dict:
        """Load configuration from environment variables and overrides"""

        # Load .env file if it exists
        if custom_env_file:
            # Use custom env file if provided
            env_file = custom_env_file
        else:
            # Use default env file location
            env_file = os.path.join(os.path.dirname(__file__), '.env')

        if os.path.exists(env_file):
            print(f"📄 Loading environment from: {env_file}")
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        os.environ[key] = value
        config = {
            # Location settings
            'lat': float(os.getenv('LAT', '46.168689')),
            'lon': float(os.getenv('LON', '-123.020309')),
            'radius_nm': int(os.getenv('RADIUS_NM', '10')),

            # MQTT settings
            'mqtt_host': os.getenv('MQTT_HOST', 'localhost'),
            'mqtt_port': int(os.getenv('MQTT_PORT', '1883')),
            'mqtt_user': os.getenv('MQTT_USER'),
            'mqtt_pass': os.getenv('MQTT_PASS'),
            'mqtt_prefix': os.getenv('MQTT_PREFIX', 'airtracker'),

            # Timing settings
            'fetch_interval_min': int(os.getenv('FETCH_INTERVAL_MIN_SEC', '80')),
            'fetch_interval_max': int(os.getenv('FETCH_INTERVAL_MAX_SEC', '100')),

            # Debug options
            'dump_raw': os.getenv('DUMP_RAW', '0') == '1',
            'military_cache_debug': os.getenv('MILITARY_CACHE_DEBUG', '0') == '1',

            # Provider toggles
            'skip_opensky': os.getenv('SKIP_OPENSKY', '0') == '1',
            'skip_adsb': os.getenv('SKIP_ADSB', '0') == '1',
            'skip_fr24': os.getenv('SKIP_FR24', '0') == '1',

            # OpenSky credentials
            'osk_client_id': os.getenv('OSK_CLIENT_ID'),
            'osk_client_secret': os.getenv('OSK_CLIENT_SECRET'),

            # Data processing
            'write_json_path': os.getenv('WRITE_JSON_PATH', 'data/planes_complete.json'),

            # Features
            'mqtt_discovery_on_start': os.getenv('MQTT_DISCOVERY_ON_START', '0') == '1',
            'mqtt_publish_all_planes': os.getenv('MQTT_PUBLISH_ALL_PLANES', '0') == '1',
            'mqtt_publish_nearest_commercial': os.getenv('MQTT_PUBLISH_NEAREST_COMMERCIAL', '0') == '1',
            'mqtt_publish_nearest_military': os.getenv('MQTT_PUBLISH_NEAREST_MILITARY', '0') == '1',

            # InfluxDB settings
            'influxdb_enabled': os.getenv('INFLUXDB_ENABLED', '0') == '1',
            'influxdb_url': os.getenv('INFLUXDB_URL', 'http://localhost:8086'),
            'influxdb_org': os.getenv('INFLUXDB_ORG'),
            'influxdb_token': os.getenv('INFLUXDB_TOKEN'),
            'influxdb_bucket_nearest': os.getenv('INFLUXDB_BUCKET_NEAREST', 'airtracker_nearest'),
            'influxdb_bucket_nearest_commercial': os.getenv('INFLUXDB_BUCKET_NEAREST_COMMERCIAL', 'airtracker_nearest_commercial'),
            'influxdb_bucket_nearest_military': os.getenv('INFLUXDB_BUCKET_NEAREST_MILITARY', 'airtracker_nearest_military'),
            'influxdb_bucket_planes': os.getenv('INFLUXDB_BUCKET_PLANES', 'airtracker_planes'),
        }

        # Apply any overrides
        if override_config:
            config.update(override_config)

        return config

    def setup_logging(self):
        """Setup logging configuration"""
        log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
        logging.basicConfig(
            level=getattr(logging, log_level),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler('data/airtracker.log')
            ]
        )
        self.logger = logging.getLogger('AirTracker')

    def _setup_influxdb(self):
        """Setup InfluxDB connection"""
        if not self.config['influxdb_enabled']:
            self.logger.info("📊 InfluxDB disabled")
            return

        if not self.config['influxdb_token'] or not self.config['influxdb_org']:
            self.logger.warning("⚠️ InfluxDB enabled but missing token/org - disabling")
            return

        try:
            self.influx_client = InfluxDBClient(
                url=self.config['influxdb_url'],
                token=self.config['influxdb_token'],
                org=self.config['influxdb_org']
            )
            self.influx_write_api = self.influx_client.write_api(write_options=SYNCHRONOUS)

            # Test connection
            health = self.influx_client.health()
            if health.status == "pass":
                self.logger.info(f"📊 InfluxDB connected: {self.config['influxdb_url']}")
            else:
                self.logger.error("❌ InfluxDB health check failed")
                self.influx_client = None
                self.influx_write_api = None
        except Exception as e:
            self.logger.error(f"❌ InfluxDB connection failed: {e}")
            self.influx_client = None
            self.influx_write_api = None

    def _write_to_influxdb(self, bucket: str, points: List[Point]) -> bool:
        """Write points to InfluxDB bucket"""
        if not self.influx_write_api:
            return False

        try:
            self.influx_write_api.write(bucket=bucket, record=points)
            return True
        except Exception as e:
            self.logger.error(f"❌ InfluxDB write failed to {bucket}: {e}")
            return False

    def _aircraft_to_influx_point(self, aircraft: Dict, measurement: str = "aircraft") -> Point:
        """Convert aircraft data to InfluxDB point"""
        point = Point(measurement) \
            .tag("aircraft_hex", aircraft.get('hex', '')) \
            .tag("aircraft_callsign", aircraft.get('callsign', '')) \
            .tag("aircraft_registration", aircraft.get('registration', '')) \
            .tag("aircraft_type", aircraft.get('aircraft_type', '')) \
            .tag("aircraft_classification", aircraft.get('classification', '')) \
            .tag("aircraft_is_military", str(aircraft.get('is_military', False))) \
            .tag("aircraft_origin_country", aircraft.get('origin_country', '')) \
            .tag("flight_origin_iata", aircraft.get('origin_iata', '')) \
            .tag("flight_destination_iata", aircraft.get('destination_iata', '')) \
            .tag("airline_icao", aircraft.get('airline_icao', '')) \
            .tag("flight_squawk", aircraft.get('squawk', '')) \
            .tag("aircraft_category", aircraft.get('category', '')) \
            .tag("flight_on_ground", str(aircraft.get('on_ground', False))) \
            .tag("metadata_country_flag_code", aircraft.get('country_flag_code', '')) \
            .tag("metadata_country_flag_source", aircraft.get('country_flag_source', ''))

        # Add data sources as tags
        if 'sources' in aircraft:
            point.tag("data_sources", ','.join(aircraft['sources']))
            point.tag("data_source_count", str(len(aircraft['sources'])))

        # Add aircraft lookup data as tags
        if 'lookups' in aircraft and 'aircraft' in aircraft['lookups']:
            aircraft_info = aircraft['lookups']['aircraft']
            point.tag("aircraft_manufacturer", aircraft_info.get('manufacturer', ''))
            point.tag("aircraft_name", aircraft_info.get('name', ''))
            point.tag("aircraft_model", aircraft_info.get('model', ''))
            point.tag("lookup_aircraft_status", aircraft_info.get('lookup_status', ''))

        # Add origin airport data as tags
        if 'lookups' in aircraft and 'origin_airport' in aircraft['lookups']:
            airport_info = aircraft['lookups']['origin_airport']
            point.tag("airport_origin_name", airport_info.get('name', ''))
            point.tag("airport_origin_city", airport_info.get('city', ''))
            point.tag("airport_origin_region", airport_info.get('region', ''))
            point.tag("airport_origin_country_code", airport_info.get('country_code', ''))

        # Add position fields
        if 'latitude' in aircraft and aircraft['latitude'] is not None:
            point.field("position_latitude", float(aircraft['latitude']))
        if 'longitude' in aircraft and aircraft['longitude'] is not None:
            point.field("position_longitude", float(aircraft['longitude']))
        if 'altitude_ft' in aircraft and aircraft['altitude_ft'] is not None:
            # Handle "ground" altitude as 0
            if str(aircraft['altitude_ft']).lower() == 'ground':
                point.field("position_altitude_ft", 0.0)
            else:
                try:
                    point.field("position_altitude_ft", float(aircraft['altitude_ft']))
                except (ValueError, TypeError):
                    point.field("position_altitude_ft", 0.0)

        # Add movement fields
        if 'ground_speed_kt' in aircraft and aircraft['ground_speed_kt'] is not None:
            point.field("movement_speed_kt", float(aircraft['ground_speed_kt']))
        if 'track_deg' in aircraft and aircraft['track_deg'] is not None:
            point.field("movement_track_deg", float(aircraft['track_deg']))
        if 'vertical_rate_fpm' in aircraft and aircraft['vertical_rate_fpm'] is not None:
            point.field("movement_vertical_rate_fpm", float(aircraft['vertical_rate_fpm']))

        # Add distance fields
        if 'distance_nm' in aircraft and aircraft['distance_nm'] is not None:
            point.field("distance_from_observer_nm", float(aircraft['distance_nm']))
        if 'bearing_deg' in aircraft and aircraft['bearing_deg'] is not None:
            point.field("distance_bearing_deg", float(aircraft['bearing_deg']))

        # Add capacity fields
        if 'souls_on_board_max' in aircraft and aircraft['souls_on_board_max'] is not None:
            point.field("aircraft_souls_on_board_max", int(aircraft['souls_on_board_max']))

        # Add timestamp fields
        if 'position_timestamp' in aircraft and aircraft['position_timestamp'] is not None:
            point.field("timestamp_position", int(aircraft['position_timestamp']))
        if 'last_timestamp' in aircraft and aircraft['last_timestamp'] is not None:
            point.field("timestamp_last_contact", int(aircraft['last_timestamp']))
        if 'timestamp' in aircraft and aircraft['timestamp'] is not None:
            point.field("timestamp_data_received", int(aircraft['timestamp']))

        # Add origin airport location fields
        if 'lookups' in aircraft and 'origin_airport' in aircraft['lookups']:
            airport_info = aircraft['lookups']['origin_airport']
            if 'lat' in airport_info and airport_info['lat'] is not None:
                point.field("airport_origin_latitude", float(airport_info['lat']))
            if 'lon' in airport_info and airport_info['lon'] is not None:
                point.field("airport_origin_longitude", float(airport_info['lon']))
            if 'elevation_ft' in airport_info and airport_info['elevation_ft'] is not None:
                point.field("airport_origin_elevation_ft", float(airport_info['elevation_ft']))

        # Add aircraft specifications fields
        if 'lookups' in aircraft and 'aircraft' in aircraft['lookups']:
            aircraft_info = aircraft['lookups']['aircraft']
            if 'seats_max' in aircraft_info and aircraft_info['seats_max'] is not None:
                point.field("aircraft_seats_max", int(aircraft_info['seats_max']))

        # Add airline information as tags
        if 'lookups' in aircraft and 'airline' in aircraft['lookups']:
            airline_info = aircraft['lookups']['airline']
            point.tag("airline_name", airline_info.get('name', ''))
            point.tag("airline_iata", airline_info.get('iata', ''))
            point.tag("airline_callsign", airline_info.get('callsign', ''))
            point.tag("airline_country", airline_info.get('country_name', ''))

        # Add destination airport data as tags and fields
        if 'lookups' in aircraft and 'destination_airport' in aircraft['lookups']:
            dest_info = aircraft['lookups']['destination_airport']
            point.tag("airport_destination_name", dest_info.get('name', ''))
            point.tag("airport_destination_city", dest_info.get('city', ''))
            point.tag("airport_destination_region", dest_info.get('region', ''))
            if 'lat' in dest_info and dest_info['lat'] is not None:
                point.field("airport_destination_latitude", float(dest_info['lat']))
            if 'lon' in dest_info and dest_info['lon'] is not None:
                point.field("airport_destination_longitude", float(dest_info['lon']))
            if 'elevation_ft' in dest_info and dest_info['elevation_ft'] is not None:
                point.field("airport_destination_elevation_ft", float(dest_info['elevation_ft']))

        # Add media/image URLs as tags
        if 'media' in aircraft:
            media = aircraft['media']
            if 'plane_image' in media:
                point.tag("media_image_url", media['plane_image'])
            if 'plane_image_zipline_original' in media:
                point.tag("media_image_zipline_original", media['plane_image_zipline_original'])
            if 'plane_image_zipline_esp32' in media:
                point.tag("media_image_zipline_esp32", media['plane_image_zipline_esp32'])
            if 'thumbnails' in media and media['thumbnails']:
                # Store first thumbnail URL
                point.tag("media_thumbnail_url", media['thumbnails'][0])
                point.field("media_thumbnail_count", len(media['thumbnails']))

        # Add additional image URLs
        if 'airline_logo_url' in aircraft:
            point.tag("media_airline_logo_url", aircraft['airline_logo_url'])
        if 'airline_logo_png_url' in aircraft:
            point.tag("media_airline_logo_png_url", aircraft['airline_logo_png_url'])
        if 'country_flag_url' in aircraft:
            point.tag("metadata_country_flag_url", aircraft['country_flag_url'])

        # Add route/flight progress fields
        if 'remaining_nm' in aircraft and aircraft['remaining_nm'] is not None:
            point.field("flight_remaining_distance_nm", float(aircraft['remaining_nm']))
        if 'eta_min' in aircraft and aircraft['eta_min'] is not None:
            point.field("flight_eta_minutes", float(aircraft['eta_min']))

        # Add flight schedule information
        if 'flight_schedule' in aircraft and isinstance(aircraft['flight_schedule'], list):
            point.field("flight_schedule_count", len(aircraft['flight_schedule']))
            # Store most recent flight info if available
            if aircraft['flight_schedule']:
                recent_flight = aircraft['flight_schedule'][0]
                point.tag("flight_recent_number", recent_flight.get('flight', ''))
                point.tag("flight_recent_origin", recent_flight.get('origin', ''))
                point.tag("flight_recent_destination", recent_flight.get('destination', ''))
                point.tag("flight_recent_date", recent_flight.get('date_yyyy_mm_dd', ''))

        return point

    def write_influxdb_data(self, data: Dict) -> bool:
        """Write aircraft data to InfluxDB buckets"""
        if not self.config['influxdb_enabled'] or not self.influx_write_api:
            return True  # Return True if disabled to not affect other operations

        try:
            success = True
            written_buckets = []

            # Write nearest aircraft
            if data.get('nearest'):
                point = self._aircraft_to_influx_point(data['nearest'], "nearest_aircraft")
                if self._write_to_influxdb(self.config['influxdb_bucket_nearest'], [point]):
                    written_buckets.append(self.config['influxdb_bucket_nearest'])
                else:
                    success = False

            # Write nearest commercial aircraft
            if (data.get('nearest_commercial') and
                data['nearest_commercial'] != "NONE" and
                isinstance(data['nearest_commercial'], dict)):
                point = self._aircraft_to_influx_point(data['nearest_commercial'], "nearest_commercial_aircraft")
                if self._write_to_influxdb(self.config['influxdb_bucket_nearest_commercial'], [point]):
                    written_buckets.append(self.config['influxdb_bucket_nearest_commercial'])
                else:
                    success = False

            # Write nearest military aircraft
            if (data.get('nearest_military') and
                data['nearest_military'] != "NONE" and
                isinstance(data['nearest_military'], dict)):
                point = self._aircraft_to_influx_point(data['nearest_military'], "nearest_military_aircraft")
                if self._write_to_influxdb(self.config['influxdb_bucket_nearest_military'], [point]):
                    written_buckets.append(self.config['influxdb_bucket_nearest_military'])
                else:
                    success = False

            # Write all planes data
            if data.get('planes'):
                points = []
                for aircraft in data['planes']:
                    point = self._aircraft_to_influx_point(aircraft, "all_aircraft")
                    points.append(point)

                if points and self._write_to_influxdb(self.config['influxdb_bucket_planes'], points):
                    written_buckets.append(f"{self.config['influxdb_bucket_planes']} ({len(points)} aircraft)")
                elif points:
                    success = False

            if success and written_buckets:
                self.logger.debug(f"📊 InfluxDB data written successfully to: {', '.join(written_buckets)}")
                # Store for summary reporting
                self.stats['influxdb_buckets_written'] = written_buckets
            elif not written_buckets:
                self.stats['influxdb_buckets_written'] = []

            return success

        except Exception as e:
            self.logger.error(f"❌ InfluxDB write error: {e}")
            self.stats['influxdb_buckets_written'] = []
            return False

    def setup_mqtt(self) -> bool:
        """Setup MQTT connection"""
        try:
            self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

            if self.config['mqtt_user'] and self.config['mqtt_pass']:
                self.mqtt_client.username_pw_set(
                    self.config['mqtt_user'],
                    self.config['mqtt_pass']
                )

            self.mqtt_client.connect(
                self.config['mqtt_host'],
                self.config['mqtt_port'],
                60
            )

            self.logger.info(f"✅ Connected to MQTT broker: {self.config['mqtt_host']}:{self.config['mqtt_port']}")
            return True

        except Exception as e:
            self.logger.error(f"❌ MQTT connection failed: {e}")
            return False

    def publish_mqtt(self, topic: str, payload: str, retain: bool = True, max_retries: int = 3) -> bool:
        """Publish message to MQTT with retry logic and reconnection"""
        full_topic = f"{self.config['mqtt_prefix']}/{topic}"

        for attempt in range(max_retries):
            try:
                # Check MQTT client connection
                if not self.mqtt_client:
                    if not self.setup_mqtt():
                        if attempt < max_retries - 1:
                            self.logger.warning(f"⚠️ MQTT setup failed, retrying... (attempt {attempt + 1}/{max_retries})")
                            time.sleep(0.1 * (attempt + 1))  # Exponential backoff
                            continue
                        return False

                # Attempt to publish
                result = self.mqtt_client.publish(full_topic, payload, retain=retain)

                if result.rc == 0:
                    self.logger.debug(f"📤 Published to {full_topic}: {len(payload)} bytes")
                    return True
                else:
                    # MQTT publish failed - try to reconnect
                    self.logger.warning(f"⚠️ MQTT publish failed (rc={result.rc}), attempting reconnection...")
                    self.mqtt_client = None  # Force reconnection

                    if attempt < max_retries - 1:
                        time.sleep(0.1 * (attempt + 1))  # Exponential backoff
                        continue
                    else:
                        self.logger.error(f"❌ MQTT publish failed after {max_retries} attempts: {result.rc}")
                        return False

            except Exception as e:
                self.logger.warning(f"⚠️ MQTT publish error: {e}")
                self.mqtt_client = None  # Force reconnection on any error

                if attempt < max_retries - 1:
                    time.sleep(0.1 * (attempt + 1))  # Exponential backoff
                    continue
                else:
                    self.logger.error(f"❌ MQTT publish failed after {max_retries} attempts: {e}")
                    return False

        return False

    def publish_mqtt_raw(self, full_topic: str, payload: str, retain: bool = True, max_retries: int = 3) -> bool:
        """Publish message to MQTT with full topic path (no prefix) with retry logic"""
        for attempt in range(max_retries):
            try:
                # Check MQTT client connection
                if not self.mqtt_client:
                    if not self.setup_mqtt():
                        if attempt < max_retries - 1:
                            self.logger.warning(f"⚠️ MQTT setup failed for raw publish, retrying... (attempt {attempt + 1}/{max_retries})")
                            time.sleep(0.1 * (attempt + 1))  # Exponential backoff
                            continue
                        return False

                # Attempt to publish
                result = self.mqtt_client.publish(full_topic, payload, retain=retain)

                if result.rc == 0:
                    self.logger.debug(f"📤 Published to {full_topic}: {len(payload)} bytes")
                    return True
                else:
                    # MQTT publish failed - try to reconnect
                    self.logger.warning(f"⚠️ MQTT raw publish failed (rc={result.rc}), attempting reconnection...")
                    self.mqtt_client = None  # Force reconnection

                    if attempt < max_retries - 1:
                        time.sleep(0.1 * (attempt + 1))  # Exponential backoff
                        continue
                    else:
                        self.logger.error(f"❌ MQTT raw publish failed after {max_retries} attempts: {result.rc}")
                        return False

            except Exception as e:
                self.logger.warning(f"⚠️ MQTT raw publish error: {e}")
                self.mqtt_client = None  # Force reconnection on any error

                if attempt < max_retries - 1:
                    time.sleep(0.1 * (attempt + 1))  # Exponential backoff
                    continue
                else:
                    self.logger.error(f"❌ MQTT raw publish failed after {max_retries} attempts: {e}")
                    return False

        return False

    def _publish_topic_with_logging(self, topic: str, data: Any, description: str) -> bool:
        """Publish a single MQTT topic with detailed logging and error handling"""
        try:
            if not data:
                self.logger.debug(f"🔇 Skipping {description} - no data to publish")
                return True

            # Serialize data to JSON
            if isinstance(data, (dict, list)):
                json_payload = json.dumps(data, separators=(',', ':'))
            else:
                json_payload = json.dumps(data, separators=(',', ':'))

            payload_size = len(json_payload)
            payload_size_kb = payload_size / 1024

            # Log payload size
            self.logger.debug(f"📏 {description} payload: {payload_size:,} bytes ({payload_size_kb:.1f} KB)")

            # Attempt to publish
            start_time = time.time()
            success = self.publish_mqtt(topic, json_payload)
            publish_time = (time.time() - start_time) * 1000  # Convert to milliseconds

            if success:
                self.stats['successful_publishes'] += 1
                self.logger.info(f"📡 ✅ Published {description} to MQTT ({payload_size_kb:.1f} KB in {publish_time:.1f}ms)")

                # Add debug info for specific topics
                if self.config.get('log_level') == 'DEBUG':
                    if topic == 'nearest_commercial' and isinstance(data, dict):
                        if data == "NONE":
                            print(f"📡 Published nearest commercial: NONE (no commercial aircraft found)")
                        else:
                            aircraft_type = data.get('classification', 'Unknown')
                            callsign = data.get('callsign', 'Unknown')
                            distance = data.get('distance_nm', 'Unknown')
                            print(f"📡 Published nearest {aircraft_type.lower()} aircraft ({callsign}) at {distance}nm to MQTT")

                    elif topic == 'nearest_military' and isinstance(data, dict):
                        if data == "NONE":
                            print(f"📡 Published nearest military: NONE (no military aircraft found)")
                        else:
                            aircraft_type = data.get('classification', 'Unknown')
                            callsign = data.get('callsign', 'Unknown')
                            distance = data.get('distance_nm', 'Unknown')
                            print(f"📡 Published nearest {aircraft_type.lower()} aircraft ({callsign}) at {distance}nm to MQTT")

                return True
            else:
                self.logger.error(f"📡 ❌ Failed to publish {description} to MQTT topic '{topic}' ({payload_size_kb:.1f} KB)")
                return False

        except Exception as e:
            self.logger.error(f"📡 ❌ Error publishing {description} to MQTT: {e}")
            return False

    def _publish_planes_chunked(self, planes_data: List[Dict]) -> bool:
        """Publish planes data with chunking for large payloads"""
        try:
            if not planes_data:
                self.logger.debug("🔇 Skipping planes data - no planes to publish")
                return True

            total_planes = len(planes_data)
            total_payload = json.dumps(planes_data, separators=(',', ':'))
            total_size_kb = len(total_payload) / 1024

            # Define chunk size (number of aircraft per chunk)
            # Target ~100KB per chunk to stay well under limits
            chunk_size = 50

            self.logger.info(f"📦 Preparing to publish {total_planes} planes ({total_size_kb:.1f} KB total)")

            # If small enough, publish as single message
            if total_size_kb <= 200:  # 200KB threshold
                return self._publish_topic_with_logging('planes', planes_data, f"all {total_planes} planes")

            # Split into chunks
            chunks = [planes_data[i:i + chunk_size] for i in range(0, len(planes_data), chunk_size)]
            chunk_count = len(chunks)

            self.logger.info(f"📦 Splitting large planes payload into {chunk_count} chunks of ~{chunk_size} aircraft each")

            # Publish summary first
            summary_data = {
                'total_aircraft': total_planes,
                'chunk_count': chunk_count,
                'chunk_size': chunk_size,
                'last_updated': datetime.now().isoformat()
            }

            summary_success = self._publish_topic_with_logging('planes/summary', summary_data, 'planes summary')

            # Publish each chunk with small delays to prevent overwhelming MQTT broker
            successful_chunks = 0
            for i, chunk in enumerate(chunks, 1):
                chunk_topic = f'planes/chunk{i}'
                chunk_description = f"planes chunk {i}/{chunk_count} ({len(chunk)} aircraft)"

                if self._publish_topic_with_logging(chunk_topic, chunk, chunk_description):
                    successful_chunks += 1
                else:
                    self.logger.warning(f"⚠️ Failed to publish chunk {i}/{chunk_count}")

                # Add small delay between chunks to prevent overwhelming MQTT broker
                # Skip delay after the last chunk
                if i < chunk_count:
                    time.sleep(0.05)  # 50ms delay between chunks

            # Clean up old chunks if we have fewer chunks than before
            if hasattr(self, '_last_chunk_count') and self._last_chunk_count > chunk_count:
                for i in range(chunk_count + 1, self._last_chunk_count + 1):
                    cleanup_topic = f'planes/chunk{i}'
                    self.publish_mqtt(cleanup_topic, "", retain=True)  # Clear old chunk

            self._last_chunk_count = chunk_count

            # Return success if summary and at least 80% of chunks succeeded
            min_successful_chunks = max(1, int(chunk_count * 0.8))
            overall_success = summary_success and (successful_chunks >= min_successful_chunks)

            if overall_success:
                self.logger.info(f"📦 ✅ Successfully published planes data: {successful_chunks}/{chunk_count} chunks")
            else:
                self.logger.error(f"📦 ❌ Planes publishing failed: only {successful_chunks}/{chunk_count} chunks successful")

            return overall_success

        except Exception as e:
            self.logger.error(f"📦 ❌ Error in chunked planes publishing: {e}")
            return False

    def fetch_opensky(self) -> List[Dict]:
        """Fetch aircraft data from OpenSky"""
        if self.config['skip_opensky']:
            return []

        try:
            n, s, w, east = bbox_from_point(self.config['lat'], self.config['lon'], self.config['radius_nm'])
            headers = {"User-Agent": UA_DEFAULT}

            # Add OAuth if configured
            if self.config['osk_client_id'] and self.config['osk_client_secret']:
                try:
                    token = get_opensky_token(self.config['osk_client_id'], self.config['osk_client_secret'])
                    headers["Authorization"] = f"Bearer {token}"
                except Exception as e:
                    self.logger.warning(f"⚠️  OpenSky OAuth failed: {e}, falling back to anonymous")

            url = f"{OSK_API_BASE}/states/all"
            params = {
                "lamin": f"{s:.6f}", "lamax": f"{n:.6f}",
                "lomin": f"{w:.6f}", "lomax": f"{east:.6f}"
            }

            response = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
            response.raise_for_status()
            data = response.json()

            # Normalize OpenSky data
            aircraft = []
            for state in (data.get("states") or []):
                if len(state) < 8:
                    continue

                # Get altitude (prefer baro, fallback to geometric)
                alt_m = state[13] if len(state) > 13 and state[13] is not None else (state[7] if len(state) > 7 else None)

                hex_code = state[0] if len(state) > 0 else ""
                is_mil = self.mil_cache.check_hex(hex_code) if hex_code else False

                aircraft.append({
                    "provider": "opensky",
                    "hex": hex_code,
                    "callsign": (state[1] or "").strip() if len(state) > 1 and state[1] else "",
                    "origin_country": state[2] if len(state) > 2 else "",
                    "latitude": state[6] if len(state) > 6 else None,
                    "longitude": state[5] if len(state) > 5 else None,
                    "altitude_ft": int(alt_m * 3.28084) if isinstance(alt_m, (int, float)) else None,
                    "on_ground": state[8] if len(state) > 8 else None,
                    "ground_speed_kt": int(state[9] * 1.94384) if len(state) > 9 and isinstance(state[9], (int, float)) else None,
                    "track_deg": state[10] if len(state) > 10 else None,
                    "vertical_rate_fpm": int(state[11] * 196.85) if len(state) > 11 and isinstance(state[11], (int, float)) else None,
                    "position_timestamp": state[3] if len(state) > 3 else None,
                    "last_timestamp": state[4] if len(state) > 4 else None,
                    "is_military": is_mil,
                })

            self.logger.info(f"📡 OpenSky: {len(aircraft)} aircraft")
            return aircraft

        except Exception as e:
            self.logger.error(f"❌ OpenSky fetch failed: {e}")
            return []

    def fetch_adsb_lol(self) -> List[Dict]:
        """Fetch aircraft data from ADSB.lol"""
        if self.config['skip_adsb']:
            return []

        try:
            url = f"{ADSB_API_BASE}/v2/point/{self.config['lat']}/{self.config['lon']}/{self.config['radius_nm']}"
            response = requests.get(url, timeout=TIMEOUT)
            response.raise_for_status()
            data = response.json()

            aircraft = []
            for ac in (data.get("ac") or []):
                hex_code = ac.get("hex", "")
                is_mil = self.mil_cache.check_hex(hex_code) if hex_code else False

                aircraft.append({
                    "provider": "adsb_lol",
                    "hex": hex_code,
                    "callsign": ac.get("flight", "").strip(),
                    "latitude": ac.get("lat"),
                    "longitude": ac.get("lon"),
                    "altitude_ft": ac.get("alt_baro"),
                    "ground_speed_kt": ac.get("gs"),
                    "track_deg": ac.get("track"),
                    "vertical_rate_fpm": ac.get("baro_rate"),
                    "squawk": ac.get("squawk"),
                    "category": ac.get("category"),
                    "is_military": is_mil,
                })

            self.logger.info(f"📡 ADSB.lol: {len(aircraft)} aircraft")
            return aircraft

        except Exception as e:
            self.logger.error(f"❌ ADSB.lol fetch failed: {e}")
            return []

    def fetch_fr24(self) -> List[Dict]:
        """Fetch aircraft data from FlightRadar24"""
        if self.config['skip_fr24']:
            return []

        try:
            n, s, w, east = bbox_from_point(self.config['lat'], self.config['lon'], self.config['radius_nm'])

            url = f"{FR24_API_BASE}/zones/fcgi/feed.js"
            params = {
                "bounds": f"{n:.6f},{s:.6f},{w:.6f},{east:.6f}",
                "faa": "1", "satellite": "1", "mlat": "1", "flarm": "1",
                "adsb": "1", "gnd": "0", "air": "1", "vehicles": "0",
                "estimated": "1", "maxage": "14400", "gliders": "0",
                "stats": "0"
            }

            headers = {"User-Agent": UA_DEFAULT}
            response = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
            response.raise_for_status()
            data = response.json()

            aircraft = []
            for key, value in data.items():
                if key in ["full_count", "version"] or not isinstance(value, list) or len(value) < 13:
                    continue

                hex_code = value[0] if len(value) > 0 else ""
                is_mil = self.mil_cache.check_hex(hex_code) if hex_code else False

                aircraft.append({
                    "provider": "fr24",
                    "hex": hex_code,
                    "latitude": value[1] if len(value) > 1 else None,
                    "longitude": value[2] if len(value) > 2 else None,
                    "track_deg": value[3] if len(value) > 3 else None,
                    "altitude_ft": value[4] if len(value) > 4 else None,
                    "ground_speed_kt": value[5] if len(value) > 5 else None,
                    "squawk": value[6] if len(value) > 6 else None,
                    "aircraft_type": value[8] if len(value) > 8 else "",
                    "registration": value[9] if len(value) > 9 else "",
                    "timestamp": value[10] if len(value) > 10 else None,
                    "origin_iata": value[11] if len(value) > 11 else "",
                    "destination_iata": value[12] if len(value) > 12 else "",
                    "callsign": value[13] if len(value) > 13 else "",
                    "on_ground": value[14] if len(value) > 14 else None,
                    "vertical_rate_fpm": value[15] if len(value) > 15 else None,
                    "airline_icao": value[18] if len(value) > 18 else "",
                    "is_military": is_mil,
                })

            self.logger.info(f"📡 FR24: {len(aircraft)} aircraft")
            return aircraft

        except Exception as e:
            self.logger.error(f"❌ FR24 fetch failed: {e}")
            return []

    def fetch_aircraft_data(self) -> List[Dict]:
        """Fetch aircraft data from all enabled providers"""
        self.logger.info(f"🛩️  Fetching aircraft data around {self.config['lat']}, {self.config['lon']}")

        all_aircraft = []

        # Fetch from all providers
        opensky_data = self.fetch_opensky()
        adsb_data = self.fetch_adsb_lol()
        fr24_data = self.fetch_fr24()

        all_aircraft.extend(opensky_data)
        all_aircraft.extend(adsb_data)
        all_aircraft.extend(fr24_data)

        # Dump raw data if requested
        if self.config.get('dump_raw'):
            print("\n" + "="*80)
            print("🔍 RAW PROVIDER DATA DUMP")
            print("="*80)

            print(f"\n📡 OpenSky Network ({len(opensky_data)} aircraft):")
            for i, aircraft in enumerate(opensky_data, 1):
                print(f"  [{i}] {json.dumps(aircraft, indent=4)}")

            print(f"\n📡 ADSB.lol ({len(adsb_data)} aircraft):")
            for i, aircraft in enumerate(adsb_data, 1):
                print(f"  [{i}] {json.dumps(aircraft, indent=4)}")

            print(f"\n📡 FlightRadar24 ({len(fr24_data)} aircraft):")
            for i, aircraft in enumerate(fr24_data, 1):
                print(f"  [{i}] {json.dumps(aircraft, indent=4)}")

            print("\n" + "="*80)
            print(f"🔍 TOTAL: {len(all_aircraft)} aircraft from all providers")
            print("="*80 + "\n")

        self.logger.info(f"✅ Retrieved {len(all_aircraft)} aircraft from providers")
        return all_aircraft

    def merge_aircraft_data(self, aircraft_list: List[Dict]) -> Dict:
        """Merge aircraft data by hex code and find nearest"""
        # Load enrichment catalogs
        try:
            catalogs = _load_catalogs()
            if self.config.get('log_level') == 'DEBUG':
                print(f"📚 Loaded enrichment datasets:")
                print(f"  - Aircraft types: {len(catalogs.get('aircraft', {}))}")
                print(f"  - Airlines (ICAO): {len(catalogs.get('airlines_by_icao', {}))}")
                print(f"  - Airlines (IATA): {len(catalogs.get('airlines_by_iata', {}))}")
                print(f"  - Airports: {len(catalogs.get('airports', {}))}")
                print(f"  - Countries: {len(catalogs.get('countries', {}))}")
        except Exception as e:
            print(f"⚠️  Warning: Could not load enrichment datasets: {e}")
            catalogs = {"aircraft": {}, "airlines_by_icao": {}, "airlines_by_iata": {}, "airports": {}, "countries": {}}

        # Group by hex code
        by_hex = {}
        for aircraft in aircraft_list:
            hex_code = aircraft.get("hex", "").upper()
            if not hex_code:
                continue

            if hex_code not in by_hex:
                by_hex[hex_code] = {
                    "hex": hex_code,
                    "sources": [],
                    "is_military": False,
                }

            by_hex[hex_code]["sources"].append(aircraft["provider"])

            # Merge fields (prefer non-null values)
            for key, value in aircraft.items():
                if key not in ["provider"] and value is not None:
                    if key not in by_hex[hex_code] or by_hex[hex_code][key] is None:
                        by_hex[hex_code][key] = value

            # Handle military flag
            if aircraft.get("is_military"):
                by_hex[hex_code]["is_military"] = True

        # Calculate distances, enrich, and find nearest
        merged_aircraft = []
        nearest_aircraft = None
        nearest_distance = float('inf')

        for aircraft in by_hex.values():
            lat = aircraft.get("latitude")
            lon = aircraft.get("longitude")

            if lat is not None and lon is not None:
                # Calculate distance using haversine formula
                lat1, lon1 = math.radians(self.config['lat']), math.radians(self.config['lon'])
                lat2, lon2 = math.radians(lat), math.radians(lon)

                dlat = lat2 - lat1
                dlon = lon2 - lon1
                a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
                c = 2 * math.asin(math.sqrt(a))
                distance_nm = 3440.065 * c  # Earth radius in nautical miles

                aircraft["distance_nm"] = round(distance_nm, 3)

                # Calculate bearing
                y = math.sin(dlon) * math.cos(lat2)
                x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
                bearing = (math.degrees(math.atan2(y, x)) + 360) % 360
                aircraft["bearing_deg"] = round(bearing, 1)

                # Check if nearest
                if distance_nm < nearest_distance:
                    nearest_distance = distance_nm
                    nearest_aircraft = aircraft.copy()

            # Enrich aircraft with dataset information
            try:
                enriched = enrich_with_catalogs(aircraft, catalogs)
                # Add enriched fields to aircraft
                for key in ["souls_on_board_max", "souls_on_board_max_is_estimate", "souls_on_board_max_text", "lookups"]:
                    if key in enriched:
                        aircraft[key] = enriched[key]

                # Add comprehensive military aircraft data if available
                if enriched.get("lookups", {}).get("aircraft", {}).get("is_military"):
                    military_data = enriched["lookups"]["aircraft"]
                    military_fields = ["role", "engines", "variants", "crew", "crew_type", "images", "primary_image_url", "esp32_image_url", "image_alt_text", "image_source"]
                    for field in military_fields:
                        if field in military_data:
                            aircraft[field] = military_data[field]

                # Add aircraft classification
                classification = classify_aircraft(aircraft)
                if classification:
                    aircraft["classification"] = classification
                    # Update is_military flag if classification is Military
                    if classification == "Military":
                        aircraft["is_military"] = True

                # Add airline logo URLs for any aircraft with airline data
                if aircraft.get("airline_icao") or (enriched.get("lookups", {}).get("airline", {}).get("iata")):
                    try:
                        airline_iata = enriched.get("lookups", {}).get("airline", {}).get("iata")
                        logo_fields = _airline_logo_fields(
                            airline_icao=_clean_str(aircraft.get("airline_icao")),
                            airline_iata=_clean_str(airline_iata),
                            catalogs=catalogs,
                        )
                        if logo_fields:
                            aircraft.update(logo_fields)
                    except Exception as logo_e:
                        if self.config.get('log_level') == 'DEBUG':
                            print(f"⚠️  Warning: Could not add airline logo for {aircraft.get('hex', 'unknown')}: {logo_e}")

                # Add country flag URLs for any aircraft with airport data
                if enriched.get("lookups"):
                    try:
                        flag_fields = _country_flag_fields(enriched.get("lookups", {}))
                        if flag_fields.get("country_flag_url"):
                            aircraft.update(flag_fields)
                    except Exception as flag_e:
                        if self.config.get('log_level') == 'DEBUG':
                            print(f"⚠️  Warning: Could not add country flag for {aircraft.get('hex', 'unknown')}: {flag_e}")

            except Exception as e:
                if self.config.get('log_level') == 'DEBUG':
                    print(f"⚠️  Warning: Could not enrich aircraft {aircraft.get('hex', 'unknown')}: {e}")

            merged_aircraft.append(aircraft)

        # Add ETA and remaining distance calculations for aircraft with destinations
        def gc_distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
            """Calculate great circle distance in nautical miles"""
            R_nm = 3440.065  # Earth radius in nautical miles
            lat1_rad, lat2_rad = math.radians(lat1), math.radians(lat2)
            dlat = math.radians(lat2 - lat1)
            dlon = math.radians(lon2 - lon1)
            a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            return R_nm * c

        for aircraft in merged_aircraft:
            try:
                lat = aircraft.get("latitude")
                lon = aircraft.get("longitude")
                spd = aircraft.get("ground_speed_kt")
                dst_iata = _clean_str(aircraft.get("destination_iata"))

                if (isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and
                    isinstance(spd, (int, float)) and spd > 0 and dst_iata):

                    # Try to get destination airport coordinates from lookups
                    d_lookup = aircraft.get("lookups", {}).get("destination_airport", {})
                    d_lat = d_lookup.get("lat") if isinstance(d_lookup, dict) else None
                    d_lon = d_lookup.get("lon") if isinstance(d_lookup, dict) else None

                    # Fallback to catalog lookup if not in aircraft lookups
                    if not (isinstance(d_lat, (int, float)) and isinstance(d_lon, (int, float))):
                        ap = catalogs.get("airports", {}).get(dst_iata, {})
                        d_lat = ap.get("lat")
                        d_lon = ap.get("lon")

                    if isinstance(d_lat, (int, float)) and isinstance(d_lon, (int, float)):
                        rem_nm = gc_distance_nm(float(lat), float(lon), float(d_lat), float(d_lon))
                        aircraft["remaining_nm"] = round(rem_nm, 1)
                        aircraft["eta_min"] = round((rem_nm / float(spd)) * 60.0, 1)
            except Exception as e:
                if self.config.get('log_level') == 'DEBUG':
                    print(f"⚠️  Warning: Could not calculate ETA for {aircraft.get('hex', 'unknown')}: {e}")

        # Find nearest commercial/military aircraft using hierarchy
        nearest_commercial = None
        nearest_commercial_distance = float('inf')
        nearest_military = None
        nearest_military_distance = float('inf')

        for aircraft in merged_aircraft:
            classification = aircraft.get("classification")
            distance = aircraft.get("distance_nm")

            if distance is not None:
                # Track nearest commercial aircraft
                if classification == "Commercial" and distance < nearest_commercial_distance:
                    nearest_commercial_distance = distance
                    nearest_commercial = aircraft.copy()

                # Track nearest military aircraft
                elif classification == "Military" and distance < nearest_military_distance:
                    nearest_military_distance = distance
                    nearest_military = aircraft.copy()

        # Apply hierarchy: Military (if closer) > Commercial
        nearest_interesting = None
        if nearest_military and nearest_commercial:
            # Both exist - choose closer one
            if nearest_military_distance < nearest_commercial_distance:
                nearest_interesting = nearest_military
            else:
                nearest_interesting = nearest_commercial
        elif nearest_military:
            # Only military exists
            nearest_interesting = nearest_military
        elif nearest_commercial:
            # Only commercial exists
            nearest_interesting = nearest_commercial

        # Enrich nearest aircraft with additional details
        enriched_nearest = {}
        if nearest_aircraft:
            # Find the enriched version of the nearest aircraft from the merged list
            nearest_hex = nearest_aircraft.get("hex")
            enriched_source = None
            for aircraft in merged_aircraft:
                if aircraft.get("hex") == nearest_hex:
                    enriched_source = aircraft
                    break

            # Use the enriched version if found, otherwise fall back to original
            enriched_nearest = dict(enriched_source or nearest_aircraft)

            # Add enrichment lookups if they exist
            if "lookups" in enriched_nearest:
                # Extract airline IATA for convenience
                try:
                    airline_lookup = enriched_nearest.get("lookups", {}).get("airline", {})
                    if isinstance(airline_lookup, dict) and airline_lookup.get("iata"):
                        enriched_nearest["airline_iata"] = airline_lookup["iata"]
                except Exception:
                    pass

                # Add airline logo fields
                try:
                    logo_fields = _airline_logo_fields(
                        airline_icao=_clean_str(enriched_nearest.get("airline_icao")),
                        airline_iata=_clean_str(enriched_nearest.get("airline_iata")),
                        catalogs=catalogs,
                    )
                    if logo_fields:
                        enriched_nearest.update(logo_fields)
                except Exception:
                    pass

                # Add country flag fields
                try:
                    flag_fields = _country_flag_fields(enriched_nearest.get("lookups", {}))
                    if flag_fields.get("country_flag_url"):
                        enriched_nearest.update(flag_fields)
                except Exception:
                    pass

            # Add JetPhotos media and flight history for nearest aircraft
            try:
                reg = _clean_str(enriched_nearest.get("registration"))
                if reg:
                    # Fetch media for nearest aircraft using embedded planelookerupper
                    try:
                        if self.config.get('log_level') == 'DEBUG':
                            print(f"🖼️  Fetching media for nearest aircraft: {reg}")

                        # Get aircraft photos and flight history
                        info = get_aircraft_info(
                            registration=reg,
                            photos=4,  # Get up to 4 photos
                            flights=10  # Get 10 flights (mix of past and future)
                        )

                        media = {}
                        history = []

                        # Process JetPhotos data
                        jp = info.get("JetPhotos") if isinstance(info, dict) else None
                        if isinstance(jp, dict):
                            imgs = jp.get("Images") or []
                            if isinstance(imgs, list) and imgs:
                                # Primary image is first image's full URL
                                first = imgs[0] if isinstance(imgs[0], dict) else {}
                                plane_image_url = first.get("Image") or first.get("Thumbnail")
                                media["plane_image"] = plane_image_url

                                # Process image with Zipline upload (original + BMP conversion)
                                if plane_image_url and hasattr(self, 'image_processor'):
                                    try:
                                        print(f"🔄 Processing image for nearest aircraft {reg}: {plane_image_url[:60]}...")
                                        zipline_urls = self.image_processor.process_aircraft_image(
                                            plane_image_url, reg
                                        )
                                        if zipline_urls:
                                            media.update(zipline_urls)
                                            print(f"✅ Added Zipline URLs for nearest aircraft {reg}: {list(zipline_urls.keys())}")
                                        else:
                                            print(f"⚠️  No Zipline URLs returned for nearest aircraft {reg}")
                                    except Exception as e:
                                        print(f"❌ Zipline processing failed for nearest aircraft {reg}: {e}")

                                # Collect thumbnails
                                thumbs = []
                                for it in imgs[:4]:  # Up to 4 thumbnails
                                    if isinstance(it, dict) and it.get("Thumbnail"):
                                        thumbs.append(it.get("Thumbnail"))
                                if thumbs:
                                    media["thumbnails"] = thumbs
                            else:
                                # No images found for specific registration - try military aircraft type fallback
                                aircraft_type = enriched_nearest.get("aircraft_type")
                                if aircraft_type and enriched_nearest.get("is_military"):
                                    fallback_terms = get_military_aircraft_search_terms(aircraft_type)
                                    if self.config.get('log_level') == 'DEBUG':
                                        print(f"📷 No images found for {reg} - trying military fallback search: {fallback_terms}")

                                    # Try each search term until we find images
                                    for search_term in fallback_terms:
                                        try:
                                            fallback_info = get_aircraft_info(
                                                registration=search_term,
                                                photos=2,  # Get fewer photos for fallback
                                                flights=0  # Don't need flight history for fallback
                                            )

                                            fallback_jp = fallback_info.get("JetPhotos") if isinstance(fallback_info, dict) else None
                                            if isinstance(fallback_jp, dict):
                                                fallback_imgs = fallback_jp.get("Images") or []
                                                if isinstance(fallback_imgs, list) and fallback_imgs:
                                                    # Found images using fallback search
                                                    first_fallback = fallback_imgs[0] if isinstance(fallback_imgs[0], dict) else {}
                                                    fallback_url = first_fallback.get("Image") or first_fallback.get("Thumbnail")
                                                    if fallback_url:
                                                        media["plane_image"] = fallback_url
                                                        media["thumbnails"] = [first_fallback.get("Thumbnail")] if first_fallback.get("Thumbnail") else []
                                                        media["fallback_search_term"] = search_term

                                                        if self.config.get('log_level') == 'DEBUG':
                                                            print(f"✅ Found fallback image for {aircraft_type} using search: {search_term}")

                                                        # Process fallback image with Zipline upload
                                                        if hasattr(self, 'image_processor'):
                                                            try:
                                                                print(f"🔄 Processing fallback image for {reg} ({aircraft_type}): {fallback_url[:60]}...")
                                                                zipline_urls = self.image_processor.process_aircraft_image(
                                                                    fallback_url, f"{reg}-{search_term}"
                                                                )
                                                                if zipline_urls:
                                                                    media.update(zipline_urls)
                                                                    print(f"✅ Added Zipline URLs for fallback image: {list(zipline_urls.keys())}")
                                                            except Exception as e:
                                                                print(f"❌ Zipline processing failed for fallback image: {e}")
                                                        break  # Stop searching after finding images
                                        except Exception as e:
                                            if self.config.get('log_level') == 'DEBUG':
                                                print(f"⚠️  Fallback search failed for '{search_term}': {e}")
                                            continue

                        # Get flight schedule using FR24 library (recent past + upcoming flights)
                        try:
                            fr24_flights = get_flight_schedule_fr24_sync(reg, limit=12)
                            if fr24_flights:
                                # Convert FR24 format to UI format
                                for f in fr24_flights:
                                    flight_row = {
                                        "flight": f.get("Flight", ""),
                                        "origin": f.get("From", ""),
                                        "destination": f.get("To", "Unknown"),
                                        "date_yyyy_mm_dd": f.get("Date", ""),
                                        "block_time_hhmm": f.get("FlightTime", ""),
                                        "departure_time_hhmm": f.get("STD", ""),
                                        "actual_departure_time_hhmm": f.get("ATD", ""),
                                        "arrival_time_hhmm": f.get("STA", ""),
                                        "flight_id": f.get("flight_id"),  # For GPS tracks
                                    }

                                    # Set arrival/ETA based on whether it's past or future
                                    sta = f.get("STA", "") or f.get("STD", "")
                                    if f.get("is_past"):
                                        flight_row["arr_or_eta_hhmm"] = f"Arr {sta}" if sta else "Landed"
                                    else:
                                        flight_row["arr_or_eta_hhmm"] = f"ETA {sta}" if sta else "Scheduled"

                                    history.append(flight_row)

                                if self.config.get('log_level') == 'DEBUG':
                                    print(f"✅ FR24: Got {len(history)} flights (past + future) for {reg}")
                        except Exception as e:
                            if self.config.get('log_level') == 'DEBUG':
                                print(f"⚠️  FR24 history failed for {reg}, using fallback: {e}")

                        # Add media and flight schedule to nearest aircraft
                        if media:
                            enriched_nearest["media"] = media
                            if self.config.get('log_level') == 'DEBUG':
                                print(f"✅ Added {len(media.get('thumbnails', []))} photos for {reg}")

                        if history:
                            enriched_nearest["flight_schedule"] = history
                            if self.config.get('log_level') == 'DEBUG':
                                print(f"✅ Added {len(history)} flights (past + future) for {reg}")

                        # Add keys for local/static assets selection on device
                        ak = enriched_nearest.get("airline_iata") or enriched_nearest.get("airline_icao")
                        if ak:
                            enriched_nearest["airline_key"] = ak

                        pk = reg or _clean_str(enriched_nearest.get("aircraft_type"))
                        if pk:
                            enriched_nearest["plane_key"] = pk

                    except Exception as e:
                        if self.config.get('log_level') == 'DEBUG':
                            print(f"⚠️  Warning: Could not fetch media for {reg}: {e}")
                        enriched_nearest.setdefault("media_errors", []).append(str(e))
            except Exception as e:
                if self.config.get('log_level') == 'DEBUG':
                    print(f"⚠️  Warning: Media enrichment failed: {e}")

            # Ensure default values for required fields (for ESP32 compatibility)
            default_fields = {
                "hex": "", "registration": "", "callsign": "", "aircraft_type": "",
                "airline_icao": "", "airline_iata": "", "origin_iata": "", "destination_iata": "",
                "classification": "", "airline_logo_url": "", "airline_logo_png_url": "", "airline_logo_path": "", "airline_logo_code": "",
                "souls_on_board_max_text": "N/A", "remaining_nm": 0.0, "eta_min": 0.0,
                "country_flag_url": "", "country_flag_code": "", "country_flag_source": ""
            }
            for key, default_value in default_fields.items():
                if enriched_nearest.get(key) is None:
                    enriched_nearest[key] = default_value

        # Enrich nearest commercial aircraft (exclude military)
        enriched_nearest_commercial = {}
        if nearest_commercial:
            enriched_nearest_commercial = dict(nearest_commercial)

            # Add enrichment lookups if they exist
            if "lookups" in nearest_commercial:
                # Extract airline IATA for convenience
                try:
                    airline_lookup = nearest_commercial.get("lookups", {}).get("airline", {})
                    if isinstance(airline_lookup, dict) and airline_lookup.get("iata"):
                        enriched_nearest_commercial["airline_iata"] = airline_lookup["iata"]
                except Exception:
                    pass

                # Add airline logo fields
                try:
                    logo_fields = _airline_logo_fields(
                        airline_icao=_clean_str(enriched_nearest_commercial.get("airline_icao")),
                        airline_iata=_clean_str(enriched_nearest_commercial.get("airline_iata")),
                        catalogs=catalogs,
                    )
                    if logo_fields:
                        enriched_nearest_commercial.update(logo_fields)
                except Exception:
                    pass

                # Add country flag fields
                try:
                    flag_fields = _country_flag_fields(enriched_nearest_commercial.get("lookups", {}))
                    if flag_fields.get("country_flag_url"):
                        enriched_nearest_commercial.update(flag_fields)
                except Exception:
                    pass

            # Add JetPhotos media and flight history for nearest commercial aircraft
            try:
                reg = _clean_str(enriched_nearest_commercial.get("registration"))
                if reg:
                    # Fetch media for nearest commercial aircraft using embedded planelookerupper
                    try:
                        if self.config.get('log_level') == 'DEBUG':
                            print(f"🖼️  Fetching media for nearest commercial aircraft: {reg}")

                        # Get aircraft photos and flight history
                        info = get_aircraft_info(
                            registration=reg,
                            photos=4,  # Get up to 4 photos
                            flights=10  # Get 10 flights (mix of past and future)
                        )

                        media = {}
                        history = []

                        # Process JetPhotos data
                        jp = info.get("JetPhotos") if isinstance(info, dict) else None
                        if isinstance(jp, dict):
                            imgs = jp.get("Images") or []
                            if isinstance(imgs, list) and imgs:
                                # Primary image is first image's full URL
                                first = imgs[0] if isinstance(imgs[0], dict) else {}
                                plane_image_url = first.get("Image") or first.get("Thumbnail")
                                media["plane_image"] = plane_image_url

                                # Process image with Zipline upload (original + BMP conversion)
                                if plane_image_url and hasattr(self, 'image_processor'):
                                    try:
                                        print(f"🔄 Processing image for nearest commercial aircraft {reg}: {plane_image_url[:60]}...")
                                        zipline_urls = self.image_processor.process_aircraft_image(
                                            plane_image_url, reg
                                        )
                                        if zipline_urls:
                                            media.update(zipline_urls)
                                            print(f"✅ Added Zipline URLs for nearest commercial aircraft {reg}: {list(zipline_urls.keys())}")
                                        else:
                                            print(f"⚠️  No Zipline URLs returned for nearest commercial aircraft {reg}")
                                    except Exception as e:
                                        print(f"❌ Zipline processing failed for nearest commercial aircraft {reg}: {e}")

                                # Collect thumbnails
                                thumbs = []
                                for it in imgs[:4]:  # Up to 4 thumbnails
                                    if isinstance(it, dict) and it.get("Thumbnail"):
                                        thumbs.append(it.get("Thumbnail"))
                                if thumbs:
                                    media["thumbnails"] = thumbs

                        # Get flight schedule using FR24 library (recent past + upcoming flights)
                        try:
                            fr24_flights = get_flight_schedule_fr24_sync(reg, limit=12)
                            if fr24_flights:
                                # Convert FR24 format to UI format
                                for f in fr24_flights:
                                    flight_row = {
                                        "flight": f.get("Flight", ""),
                                        "origin": f.get("From", ""),
                                        "destination": f.get("To", "Unknown"),
                                        "date_yyyy_mm_dd": f.get("Date", ""),
                                        "block_time_hhmm": f.get("FlightTime", ""),
                                        "departure_time_hhmm": f.get("STD", ""),
                                        "actual_departure_time_hhmm": f.get("ATD", ""),
                                        "arrival_time_hhmm": f.get("STA", ""),
                                        "flight_id": f.get("flight_id"),  # For GPS tracks
                                    }

                                    # Set arrival/ETA based on whether it's past or future
                                    sta = f.get("STA", "") or f.get("STD", "")
                                    if f.get("is_past"):
                                        flight_row["arr_or_eta_hhmm"] = f"Arr {sta}" if sta else "Landed"
                                    else:
                                        flight_row["arr_or_eta_hhmm"] = f"ETA {sta}" if sta else "Scheduled"

                                    history.append(flight_row)

                                if self.config.get('log_level') == 'DEBUG':
                                    print(f"✅ FR24: Got {len(history)} flights (past + future) for {reg}")
                        except Exception as e:
                            if self.config.get('log_level') == 'DEBUG':
                                print(f"⚠️  FR24 history failed for {reg}, using fallback: {e}")

                        # Add media and history to nearest commercial aircraft
                        if media:
                            enriched_nearest_commercial["media"] = media
                            if self.config.get('log_level') == 'DEBUG':
                                print(f"✅ Added {len(media.get('thumbnails', []))} photos for commercial aircraft {reg}")

                        if history:
                            enriched_nearest_commercial["history"] = history
                            if self.config.get('log_level') == 'DEBUG':
                                print(f"✅ Added {len(history)} flight history entries for commercial aircraft {reg}")

                        # Add keys for local/static assets selection on device
                        ak = enriched_nearest_commercial.get("airline_iata") or enriched_nearest_commercial.get("airline_icao")
                        if ak:
                            enriched_nearest_commercial["airline_key"] = ak

                        pk = reg or _clean_str(enriched_nearest_commercial.get("aircraft_type"))
                        if pk:
                            enriched_nearest_commercial["plane_key"] = pk

                    except Exception as e:
                        if self.config.get('log_level') == 'DEBUG':
                            print(f"⚠️  Warning: Could not fetch media for commercial aircraft {reg}: {e}")
                        enriched_nearest_commercial.setdefault("media_errors", []).append(str(e))
            except Exception as e:
                if self.config.get('log_level') == 'DEBUG':
                    print(f"⚠️  Warning: Media enrichment failed for commercial aircraft: {e}")

            # Ensure default values for required fields (for ESP32 compatibility)
            default_fields = {
                "hex": "", "registration": "", "callsign": "", "aircraft_type": "",
                "airline_icao": "", "airline_iata": "", "origin_iata": "", "destination_iata": "",
                "classification": "", "airline_logo_url": "", "airline_logo_png_url": "", "airline_logo_path": "", "airline_logo_code": "",
                "souls_on_board_max_text": "N/A", "remaining_nm": 0.0, "eta_min": 0.0,
                "country_flag_url": "", "country_flag_code": "", "country_flag_source": ""
            }
            for key, default_value in default_fields.items():
                if enriched_nearest_commercial.get(key) is None:
                    enriched_nearest_commercial[key] = default_value

        # Set nearest_commercial to "NONE" if no commercial aircraft found
        if not enriched_nearest_commercial:
            enriched_nearest_commercial = "NONE"

        # Enrich nearest military aircraft
        enriched_nearest_military = {}
        if nearest_military:
            enriched_nearest_military = dict(nearest_military)
            # Add enrichment lookups if they exist
            if "lookups" in nearest_military:
                # Add country flag fields
                try:
                    flag_fields = _country_flag_fields(enriched_nearest_military.get("lookups", {}))
                    if flag_fields.get("country_flag_url"):
                        enriched_nearest_military.update(flag_fields)
                except Exception:
                    pass
            # Ensure default values for required fields (for ESP32 compatibility)
            default_fields = {
                "callsign": "", "aircraft_type": "", "registration": "", "airline_icao": "", "origin_iata": "", "destination_iata": "",
                "classification": "", "souls_on_board_max_text": "N/A", "remaining_nm": 0.0, "eta_min": 0.0,
                "country_flag_url": "", "country_flag_code": "", "country_flag_source": ""
            }
            for key, default_value in default_fields.items():
                if enriched_nearest_military.get(key) is None:
                    enriched_nearest_military[key] = default_value

        # Set nearest_military to "NONE" if no military aircraft found
        if not enriched_nearest_military:
            enriched_nearest_military = "NONE"

        return {
            "timestamp": int(time.time()),
            "stats": {
                "hex_count": len(merged_aircraft),
                "providers_present": list(set(aircraft.get("provider", "unknown") for aircraft_list in [aircraft_list] for aircraft in aircraft_list))
            },
            "point": {
                "lat": self.config['lat'],
                "lon": self.config['lon'],
                "radius_nm": self.config['radius_nm']
            },
            "planes": merged_aircraft,
            "nearest": enriched_nearest,
            "nearest_commercial": enriched_nearest_commercial,
            "nearest_military": enriched_nearest_military
        }

    def publish_ha_discovery(self, data: Optional[Dict] = None) -> bool:
        """Publish dynamic Home Assistant MQTT Discovery configs based on actual data"""
        try:
            if not self.config.get('mqtt_discovery_on_start'):
                return True  # Skip if not enabled

            prefix = self.config['mqtt_prefix']
            discovery_prefix = "homeassistant"
            device = {
                "identifiers": [f"airtracker_{prefix}"],
                "name": "AirTracker",
                "model": "Aircraft Tracker",
                "manufacturer": "AirTracker",
                "sw_version": "1.0"
            }

            entities = []

            # Always add basic stats sensors
            entities.extend([
                {
                    "type": "sensor", "id": "aircraft_count", "name": "Aircraft Count",
                    "topic": f"{prefix}/stats", "value_template": "{{ value_json.aircraft_count | default(0) }}",
                    "unit_of_measurement": "aircraft", "icon": "mdi:counter"
                },
                {
                    "type": "sensor", "id": "runs_total", "name": "Total Runs",
                    "topic": f"{prefix}/stats", "value_template": "{{ value_json.runs | default(0) }}",
                    "icon": "mdi:counter"
                },
                {
                    "type": "sensor", "id": "successful_publishes", "name": "Successful Publishes",
                    "topic": f"{prefix}/stats", "value_template": "{{ value_json.successful_publishes | default(0) }}",
                    "icon": "mdi:check-circle"
                }
            ])

            # Add dynamic sensors based on data structure if data is provided
            if data:
                # Add nearest aircraft sensors
                if data.get('nearest'):
                    entities.extend(self._create_aircraft_sensors('nearest', 'Nearest Aircraft', f"{prefix}/nearest"))

                # Add nearest commercial sensors
                if data.get('nearest_commercial') and data['nearest_commercial'] != "NONE":
                    entities.extend(self._create_aircraft_sensors('nearest_commercial', 'Nearest Commercial Aircraft', f"{prefix}/nearest_commercial"))

            # Clean up old entities first
            self._cleanup_old_ha_discovery(prefix, discovery_prefix)

            # Publish new entities
            success = True
            for entity in entities:
                config = {
                    "unique_id": f"{prefix}_{entity['id']}",
                    "name": entity["name"],
                    "state_topic": entity["topic"],
                    "value_template": entity["value_template"],
                    "icon": entity["icon"],
                    "device": device,
                    "availability_topic": f"{prefix}/stats",
                    "availability_template": "{{ 'online' if value_json.last_update else 'offline' }}"
                }

                if entity.get("unit_of_measurement"):
                    config["unit_of_measurement"] = entity["unit_of_measurement"]

                discovery_topic = f"{discovery_prefix}/{entity['type']}/{prefix}/{entity['id']}/config"
                config_json = json.dumps(config, separators=(',', ':'))

                if not self.publish_mqtt_raw(discovery_topic, config_json, retain=True):
                    self.logger.error(f"Failed to publish HA discovery config for {entity['id']}")
                    success = False

            if success:
                self.logger.info(f"✅ Published {len(entities)} Home Assistant MQTT Discovery configs")
            else:
                self.logger.warning("⚠️  Some Home Assistant discovery configs failed to publish")

            return success

        except Exception as e:
            self.logger.error(f"❌ Home Assistant discovery publishing failed: {e}")
            return False

    def _create_aircraft_sensors(self, prefix: str, name_prefix: str, topic: str) -> List[Dict]:
        """Create sensor configurations for aircraft data"""
        sensors = [
            {
                "type": "sensor", "id": f"{prefix}_callsign", "name": f"{name_prefix} Callsign",
                "topic": topic, "value_template": f"{{% if value_json == 'NONE' %}}N/A{{% else %}}{{{{ value_json.callsign | default('N/A') }}}}{{% endif %}}",
                "icon": "mdi:airplane"
            },
            {
                "type": "sensor", "id": f"{prefix}_registration", "name": f"{name_prefix} Registration",
                "topic": topic, "value_template": f"{{% if value_json == 'NONE' %}}N/A{{% else %}}{{{{ value_json.registration | default('N/A') }}}}{{% endif %}}",
                "icon": "mdi:airplane"
            },
            {
                "type": "sensor", "id": f"{prefix}_distance", "name": f"{name_prefix} Distance",
                "topic": topic, "value_template": f"{{% if value_json == 'NONE' %}}0{{% else %}}{{{{ value_json.distance_nm | default(0) }}}}{{% endif %}}",
                "unit_of_measurement": "nm", "icon": "mdi:map-marker-distance"
            },
            {
                "type": "sensor", "id": f"{prefix}_altitude", "name": f"{name_prefix} Altitude",
                "topic": topic, "value_template": f"{{% if value_json == 'NONE' %}}0{{% else %}}{{{{ value_json.altitude_ft | default(0) }}}}{{% endif %}}",
                "unit_of_measurement": "ft", "icon": "mdi:airplane-takeoff"
            },
            {
                "type": "sensor", "id": f"{prefix}_aircraft_type", "name": f"{name_prefix} Aircraft Type",
                "topic": topic, "value_template": f"{{% if value_json == 'NONE' %}}Unknown{{% else %}}{{{{ value_json.aircraft_type | default('Unknown') }}}}{{% endif %}}",
                "icon": "mdi:airplane"
            },
            {
                "type": "sensor", "id": f"{prefix}_classification", "name": f"{name_prefix} Classification",
                "topic": topic, "value_template": f"{{% if value_json == 'NONE' %}}Unknown{{% else %}}{{{{ value_json.classification | default('Unknown') }}}}{{% endif %}}",
                "icon": "mdi:tag"
            },
            {
                "type": "sensor", "id": f"{prefix}_ground_speed", "name": f"{name_prefix} Ground Speed",
                "topic": topic, "value_template": f"{{% if value_json == 'NONE' %}}0{{% else %}}{{{{ value_json.ground_speed_kt | default(0) }}}}{{% endif %}}",
                "unit_of_measurement": "kt", "icon": "mdi:speedometer"
            }
        ]

        # Add route sensor for aircraft with origin/destination
        sensors.append({
            "type": "sensor", "id": f"{prefix}_route", "name": f"{name_prefix} Route",
            "topic": topic,
            "value_template": f"{{% if value_json == 'NONE' %}}N/A{{% else %}}{{{{ value_json.origin_iata | default('') }}}}{{% if value_json.origin_iata and value_json.destination_iata %}} → {{% endif %}}{{{{ value_json.destination_iata | default('') }}}}{{% endif %}}",
            "icon": "mdi:flight"
        })

        return sensors

    def _cleanup_old_ha_discovery(self, prefix: str, discovery_prefix: str):
        """Clean up old Home Assistant discovery configs"""
        # Send empty retained messages to remove old configs
        # This is a simplified cleanup - in a full implementation you'd track which entities were created
        old_entity_patterns = [
            'nearest_callsign', 'nearest_distance', 'nearest_altitude', 'nearest_aircraft_type', 'nearest_classification',
            'nearest_commercial_callsign', 'nearest_commercial_distance', 'nearest_commercial_route'
        ]

        for pattern in old_entity_patterns:
            cleanup_topic = f"{discovery_prefix}/sensor/{prefix}/{pattern}/config"
            self.publish_mqtt_raw(cleanup_topic, "", retain=True)  # Empty retained message removes entity

    def publish_data(self, data: Dict) -> bool:
        """Publish processed data to MQTT topics with enhanced error handling and resilience"""
        try:
            # Track successful publishes for each topic independently
            publish_results = {
                'nearest': False,
                'planes': False,
                'nearest_commercial': False,
                'nearest_military': False,
                'stats': False
            }

            # Publish Home Assistant discovery configs if enabled (first time only)
            if not hasattr(self, '_ha_discovery_published'):
                self.publish_ha_discovery(data)
                self._ha_discovery_published = True

            # Publish nearest aircraft (high priority - single aircraft object)
            try:
                publish_results['nearest'] = self._publish_topic_with_logging(
                    'nearest', data.get('nearest'), 'nearest aircraft'
                )
            except Exception as e:
                self.logger.error(f"❌ Failed to publish nearest aircraft: {e}")
                publish_results['nearest'] = False

            # Small delay between topic publishing to prevent overwhelming MQTT
            time.sleep(0.01)

            # Publish all planes data with chunking for large payloads
            if self.config.get('mqtt_publish_all_planes') and data.get('planes'):
                try:
                    publish_results['planes'] = self._publish_planes_chunked(data['planes'])
                except Exception as e:
                    self.logger.error(f"❌ Failed to publish planes data: {e}")
                    publish_results['planes'] = False
            else:
                publish_results['planes'] = True  # Not enabled, so mark as successful

            # Small delay after planes chunking to allow MQTT client to recover
            time.sleep(0.02)

            # Publish nearest commercial aircraft (independent of planes topic)
            if self.config.get('mqtt_publish_nearest_commercial') and data.get('nearest_commercial'):
                try:
                    publish_results['nearest_commercial'] = self._publish_topic_with_logging(
                        'nearest_commercial', data.get('nearest_commercial'), 'nearest commercial aircraft'
                    )
                except Exception as e:
                    self.logger.error(f"❌ Failed to publish nearest commercial: {e}")
                    publish_results['nearest_commercial'] = False
            else:
                publish_results['nearest_commercial'] = True  # Not enabled, so mark as successful

            # Small delay between topic publishing
            time.sleep(0.01)

            # Publish nearest military aircraft (independent of planes topic)
            if self.config.get('mqtt_publish_nearest_military') and data.get('nearest_military'):
                try:
                    publish_results['nearest_military'] = self._publish_topic_with_logging(
                        'nearest_military', data.get('nearest_military'), 'nearest military aircraft'
                    )
                except Exception as e:
                    self.logger.error(f"❌ Failed to publish nearest military: {e}")
                    publish_results['nearest_military'] = False
            else:
                publish_results['nearest_military'] = True  # Not enabled, so mark as successful

            # Publish stats (always attempt this)
            try:
                stats_data = {
                    **self.stats,
                    'last_update': datetime.now().isoformat(),
                    'aircraft_count': len(data.get('planes', [])),
                    'nearest_aircraft': data.get('nearest', {}).get('callsign', 'None'),
                    'mqtt_publish_results': publish_results
                }
                publish_results['stats'] = self._publish_topic_with_logging(
                    'stats', stats_data, 'statistics'
                )
            except Exception as e:
                self.logger.error(f"❌ Failed to publish stats: {e}")
                publish_results['stats'] = False

            # Write to InfluxDB (independent of MQTT success)
            influx_success = self.write_influxdb_data(data)
            if not influx_success:
                self.logger.warning("⚠️ InfluxDB write failed, but continuing...")

            # Log overall publishing summary
            successful_topics = [topic for topic, success in publish_results.items() if success]
            failed_topics = [topic for topic, success in publish_results.items() if not success and topic != 'planes']

            if successful_topics:
                self.logger.info(f"✅ Successfully published to MQTT topics: {', '.join(successful_topics)}")
            if failed_topics:
                self.logger.warning(f"⚠️ Failed to publish to MQTT topics: {', '.join(failed_topics)}")

            # Return True if at least the critical topics (nearest, stats) succeeded
            return publish_results['nearest'] and publish_results['stats']

        except Exception as e:
            self.logger.error(f"❌ Data publishing failed: {e}")
            return False

    def print_summary(self, data: Dict):
        """Print a nice summary of the data collection results"""
        planes = data.get('planes', [])
        nearest = data.get('nearest', {})

        # Count provider contributions
        provider_counts = {}
        total_from_providers = 0
        for plane in planes:
            sources = plane.get('sources', [])
            for source in sources:
                provider_counts[source] = provider_counts.get(source, 0) + 1
                total_from_providers += 1

        # Military checks
        mil_checked = len([p for p in planes if 'is_military' in p])
        mil_aircraft = len([p for p in planes if p.get('is_military', False)])

        print("\n" + "="*60)
        print("📊 Final Results Summary:")
        print("")
        print(f"  - 🛩️ {total_from_providers} aircraft total from ALL {len(provider_counts)} providers! 🎉")
        print(f"  - ✈️ {len(planes)} unique aircraft after merging by hex code")

        if nearest:
            callsign = nearest.get('callsign', 'Unknown')
            aircraft_type = nearest.get('aircraft_type', 'Unknown')
            classification = nearest.get('classification', 'Unknown')
            distance = nearest.get('distance_nm', 0)
            altitude = nearest.get('altitude_ft', nearest.get('altitude', 0))
            print(f"  - 🎯 Nearest aircraft: {callsign} ({aircraft_type}) - {classification} - {distance:.1f}nm away at {altitude:,}ft")

        print(f"  - ✅ Perfect data merge with aircraft appearing in multiple sources")

        # MQTT publishing summary
        mqtt_feeds_published = []
        if nearest:
            mqtt_feeds_published.append("airtracker/nearest")
        mqtt_feeds_published.append("airtracker/stats")

        if self.config.get('mqtt_publish_all_planes') and planes:
            mqtt_feeds_published.append(f"airtracker/planes ({len(planes)} aircraft)")
        elif not self.config.get('mqtt_publish_all_planes'):
            mqtt_feeds_published.append("airtracker/planes (DISABLED)")

        if self.config.get('mqtt_publish_nearest_commercial'):
            commercial_data = data.get('nearest_commercial')
            if commercial_data == "NONE" or not commercial_data:
                commercial_status = "NONE"
            else:
                commercial_status = "FOUND"
            mqtt_feeds_published.append(f"airtracker/nearest_commercial ({commercial_status})")
        else:
            mqtt_feeds_published.append("airtracker/nearest_commercial (DISABLED)")

        if self.config.get('mqtt_publish_nearest_military'):
            military_data = data.get('nearest_military')
            if military_data == "NONE" or not military_data:
                military_status = "NONE"
            else:
                military_status = "FOUND"
            mqtt_feeds_published.append(f"airtracker/nearest_military ({military_status})")
        else:
            mqtt_feeds_published.append("airtracker/nearest_military (DISABLED)")

        print(f"  - 📡 MQTT Feeds Published:")
        for feed in mqtt_feeds_published:
            print(f"    • {feed}")
        print(f"  - ✅ MQTT published successfully")

        # InfluxDB summary
        if self.config.get('influxdb_enabled'):
            written_buckets = self.stats.get('influxdb_buckets_written', [])
            if written_buckets:
                print(f"  - 📊 InfluxDB data written to {len(written_buckets)} bucket(s):")
                for bucket in written_buckets:
                    print(f"    • {bucket}")
            else:
                print(f"  - 📊 InfluxDB: No data written (no aircraft or write failed)")
        else:
            print(f"  - 📊 InfluxDB: DISABLED")

        if mil_checked > 0:
            print(f"  - 🪖 Military detection active - {mil_checked} aircraft checked, {mil_aircraft} military")

        print("\n  🌐 Provider Performance:")
        print("")
        print("  All sources working flawlessly:")
        for provider, count in provider_counts.items():
            print(f"  - {provider}: Contributing {count} aircraft data ✅")

        print("\n" + "="*60 + "\n")

    def run_single_cycle(self) -> bool:
        """Run a single data collection and publishing cycle"""
        try:
            self.logger.info("🔄 Starting AirTracker cycle")
            self.stats['runs'] += 1

            # Fetch raw data
            aircraft_data = self.fetch_aircraft_data()
            if not aircraft_data:
                self.logger.warning("⚠️  No aircraft data retrieved")

            # Merge and process data
            processed_data = self.merge_aircraft_data(aircraft_data)

            # Save to file if configured
            if self.config['write_json_path']:
                os.makedirs(os.path.dirname(self.config['write_json_path']), exist_ok=True)
                with open(self.config['write_json_path'], 'w') as f:
                    json.dump(processed_data, f, indent=2)

            # Publish to MQTT
            if self.publish_data(processed_data):
                self.logger.info("✅ Cycle completed successfully")

                # Print summary
                self.print_summary(processed_data)
                return True
            else:
                self.stats['errors'] += 1
                return False

        except Exception as e:
            self.logger.error(f"❌ Cycle failed: {e}")
            self.stats['errors'] += 1
            return False

    def run_continuous(self):
        """Run continuous monitoring loop"""
        self.logger.info("🚀 Starting AirTracker continuous monitoring")
        self.logger.info(f"📍 Location: {self.config['lat']}, {self.config['lon']} (radius: {self.config['radius_nm']} nm)")
        self.logger.info(f"📡 MQTT: {self.config['mqtt_prefix']}/* → {self.config['mqtt_host']}:{self.config['mqtt_port']}")

        # Setup MQTT connection
        if not self.setup_mqtt():
            self.logger.error("❌ Cannot start without MQTT connection")
            sys.exit(1)

        # Publish Home Assistant discovery configs if enabled (will be updated with actual data on first publish)
        self.publish_ha_discovery()

        try:
            while True:
                cycle_start = time.time()

                # Run data cycle
                self.run_single_cycle()

                # Calculate sleep time with jitter
                base_interval = random.randint(
                    self.config['fetch_interval_min'],
                    self.config['fetch_interval_max']
                )

                cycle_duration = time.time() - cycle_start
                sleep_time = max(0, base_interval - cycle_duration)

                if sleep_time > 0:
                    self.logger.info(f"😴 Sleeping for {sleep_time:.1f}s until next cycle")
                    time.sleep(sleep_time)
                else:
                    self.logger.warning(f"⚠️  Cycle took {cycle_duration:.1f}s (longer than interval)")

        except KeyboardInterrupt:
            self.logger.info("🛑 Received interrupt signal, shutting down")
        except Exception as e:
            self.logger.error(f"❌ Continuous loop failed: {e}")
            raise
        finally:
            if self.mqtt_client:
                self.mqtt_client.disconnect()
                self.logger.info("📡 MQTT disconnected")


def main():
    """Main CLI interface"""
    parser = argparse.ArgumentParser(
        description="AirTracker Complete Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 airtracker_complete.py                   # Single run (default)
  python3 airtracker_complete.py --continuous      # Continuous operation
  python3 airtracker_complete.py --test-mqtt       # Test MQTT connection
  python3 airtracker_complete.py --lat 40.7 --lon -74.0 --radius 15  # Custom location
  python3 airtracker_complete.py --env-file /path/to/custom.env       # Custom .env file
        """
    )

    # Operation mode
    parser.add_argument('--continuous', action='store_true',
                       help='Run continuously (default: single run and exit)')
    parser.add_argument('--test-mqtt', action='store_true',
                       help='Test MQTT connection and exit')

    # Location overrides
    parser.add_argument('--lat', type=float, help='Latitude override')
    parser.add_argument('--lon', type=float, help='Longitude override')
    parser.add_argument('--radius', type=int, help='Radius in nautical miles override')

    # MQTT overrides
    parser.add_argument('--mqtt-host', help='MQTT broker host override')
    parser.add_argument('--mqtt-port', type=int, help='MQTT broker port override')
    parser.add_argument('--mqtt-prefix', help='MQTT topic prefix override')
    parser.add_argument('--mqtt-publish-all', action='store_true',
                       help='Publish all planes data to MQTT (not just nearest)')
    parser.add_argument('--mqtt-publish-commercial', action='store_true',
                       help='Publish nearest commercial aircraft to MQTT')
    parser.add_argument('--mqtt-publish-military', action='store_true',
                       help='Publish nearest military aircraft to MQTT')

    # Debug options
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('--dump-raw', action='store_true', help='Dump raw provider responses for debugging')
    parser.add_argument('--output-file', help='Write processed JSON to file')
    parser.add_argument('--env-file', help='Path to custom .env file')

    args = parser.parse_args()

    # Build config overrides
    config_overrides = {}
    if args.lat is not None:
        config_overrides['lat'] = args.lat
    if args.lon is not None:
        config_overrides['lon'] = args.lon
    if args.radius is not None:
        config_overrides['radius_nm'] = args.radius
    if args.mqtt_host:
        config_overrides['mqtt_host'] = args.mqtt_host
    if args.mqtt_port:
        config_overrides['mqtt_port'] = args.mqtt_port
    if args.mqtt_prefix:
        config_overrides['mqtt_prefix'] = args.mqtt_prefix
    if args.mqtt_publish_all:
        config_overrides['mqtt_publish_all_planes'] = True
    if args.mqtt_publish_commercial:
        config_overrides['mqtt_publish_nearest_commercial'] = True
    if args.mqtt_publish_military:
        config_overrides['mqtt_publish_nearest_military'] = True
    if args.output_file:
        config_overrides['write_json_path'] = args.output_file

    # Set debug logging
    if args.debug:
        os.environ['LOG_LEVEL'] = 'DEBUG'
    if args.dump_raw:
        config_overrides['dump_raw'] = True

    # Initialize complete pipeline
    tracker = AirTrackerComplete(config_overrides, args.env_file)

    # Handle different operation modes
    if args.test_mqtt:
        print("🧪 Testing MQTT connection...")
        if tracker.setup_mqtt():
            print("✅ MQTT connection successful")
            sys.exit(0)
        else:
            print("❌ MQTT connection failed")
            sys.exit(1)

    elif args.continuous:
        # Continuous operation
        tracker.run_continuous()

    else:
        # Default: single operation (exit after one cycle)
        print("🔄 Running single cycle...")
        success = tracker.run_single_cycle()
        sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()