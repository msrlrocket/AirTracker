#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, math, json, argparse, getpass, requests, time

# Load environment variables from a local .env if present (no external deps)
def _load_local_env() -> None:
    try:
        paths = [
            ".env",
            os.path.join(os.path.dirname(__file__), ".env"),
        ]
        seen = set()
        for path in paths:
            if not path or path in seen:
                continue
            seen.add(path)
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if not s or s.startswith("#") or "=" not in s:
                        continue
                    k, v = s.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
    except Exception:
        pass

_load_local_env()
from typing import Tuple, List, Dict, Any, Optional, TYPE_CHECKING, cast

TIMEOUT = 15
UA_DEFAULT = "PlaneTester/2.4 (+requests)"

# Optional Excel deps (pandas + openpyxl or xlsxwriter)
try:
    import pandas as pd  # type: ignore
except Exception:
    pd = None  # type: ignore[assignment]

# ---------- OpenSky creds you can hardcode ----------
OSK_CLIENT_ID_DEFAULT = ""
OSK_CLIENT_SECRET_DEFAULT = ""

# ---------- MIL (ADSB.lol) ----------
MIL_TTL_DEFAULT = 6 * 3600
MIL_CACHE_FILE_DEFAULT = "mil_cache.json"
MIL_LIST_CACHE_FILE_DEFAULT = "mil_list_cache.json"

# ---------- Notes text for Excel sheet ----------
# Moved detailed field notes and cautions to README.md. Keep a minimal pointer here
# so the Excel export can still include a Notes sheet without embedding long text.
NOTES_TEXT = {
    "OpenSky (sheet: “OpenSky”)": "See README.md for field descriptions.",
    "ADSB.lol (sheet: “ADSB.lol”)": "See README.md for field descriptions.",
    "Flightradar24 feed.js (sheet: “FR24”)": "See README.md for field descriptions and caveats.",
    "Cross-provider cautions": "See README.md for details on altitude, speed, track vs heading, timestamps, and data source tags.",
}

# ====================== helpers ======================
def sanitize_float(s: str) -> float:
    return float(s.rstrip(", "))

def nm_to_deg(lat_deg: float, radius_nm: float) -> Tuple[float, float]:
    dlat = radius_nm / 60.0
    dlon = radius_nm / (60.0 * max(0.1, math.cos(math.radians(lat_deg))))
    return dlat, dlon

def bbox_from_point(lat: float, lon: float, radius_nm: float) -> Tuple[float, float, float, float]:
    dlat, dlon = nm_to_deg(lat, radius_nm)
    return lat + dlat, lat - dlat, lon - dlon, lon + dlon  # N,S,W,E

def header(msg: str):
    print("\n" + msg)
    print("=" * len(msg))

def _printable(v: Any) -> str:
    if v is None: return ""
    if isinstance(v, (dict, list, tuple)):
        s = json.dumps(v, ensure_ascii=False)
        return (s if len(s) <= 120 else s[:117] + "...")
    return str(v)

def table(rows: List[Dict[str, Any]], fields: List[str], max_rows=12):
    if not rows:
        print("  (no results)")
        return
    rows = rows[:max_rows]
    widths = {f: max(len(f), max(len(_printable(r.get(f,""))) for r in rows)) for f in fields}
    print("  " + " | ".join(f.ljust(widths[f]) for f in fields))
    print("  " + "-+-".join("-"*widths[f] for f in fields))
    for r in rows:
        print("  " + " | ".join(_printable(r.get(f,"")).ljust(widths[f]) for f in fields))

def log_http_response(r: requests.Response, name: str, debug: bool):
    print(f"  [{name}] HTTP {r.status_code} {r.reason}")
    ct = r.headers.get("Content-Type", "")
    cl = r.headers.get("Content-Length", "")
    ce = r.headers.get("Content-Encoding", "")
    print(f"  [{name}] Content-Type: {ct} | Content-Length: {cl} | Content-Encoding: {ce}")
    if debug:
        preview = r.text[:400].replace("\n", " ")
        print(f"  [{name}] Body preview: {preview}{'...' if len(r.text) > 400 else ''}")

def union_fields(rows: List[Dict[str, Any]], preferred: List[str]) -> List[str]:
    keys = set()
    for r in rows:
        keys.update(r.keys())
    ordered = [k for k in preferred if k in keys]
    rest = sorted(k for k in keys if k not in ordered)
    return ordered + rest

def stringify_complex(v: Any) -> Any:
    if isinstance(v, (dict, list, tuple)):
        return json.dumps(v, ensure_ascii=False)
    return v

# ====================== OpenSky ======================
OSK_TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
OSK_API_BASE  = "https://opensky-network.org/api"

def get_opensky_token(client_id: str, client_secret: str) -> str:
    r = requests.post(OSK_TOKEN_URL, data={
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }, headers={"User-Agent": UA_DEFAULT, "Content-Type": "application/x-www-form-urlencoded"}, timeout=TIMEOUT)
    r.raise_for_status()
    tok = r.json().get("access_token")
    if not tok: raise RuntimeError(f"OpenSky token missing: {r.text[:240]}")
    return tok

def fetch_opensky(lat: float, lon: float, radius_nm: float, client_id: Optional[str], client_secret: Optional[str], debug: bool, dump: bool) -> Dict[str, Any]:
    n,s,w,e = bbox_from_point(lat, lon, radius_nm)
    headers: Dict[str, str] = {"User-Agent": UA_DEFAULT}
    if client_id and client_secret:
        headers["Authorization"] = f"Bearer {get_opensky_token(client_id, client_secret)}"
    r = requests.get(f"{OSK_API_BASE}/states/all", params={
        "lamin": f"{s:.6f}", "lamax": f"{n:.6f}", "lomin": f"{w:.6f}", "lomax": f"{e:.6f}",
    }, headers=headers, timeout=TIMEOUT)
    print(f"  [OpenSky] Tried: {r.url}")
    log_http_response(r, "OpenSky", debug)
    r.raise_for_status()
    js: Dict[str, Any] = r.json()
    if dump:
        with open("opensky.json","w",encoding="utf-8") as f: json.dump(js, f, ensure_ascii=False, indent=2)
        print("  wrote opensky.json")
    return js

def normalize_opensky(js: Dict[str, Any]) -> List[Dict[str, Any]]:
    out=[]
    for s in (js.get("states") or []):
        alt_m = s[13] if len(s)>13 and s[13] is not None else (s[7] if len(s)>7 else None)
        out.append({
            "hex": s[0] if len(s)>0 else "",
            "flight": (s[1] or "").strip() if len(s)>1 and s[1] else "",
            "lat": s[6] if len(s)>6 else None,
            "lon": s[5] if len(s)>5 else None,
            "alt_ft": int(alt_m*3.28084) if isinstance(alt_m,(int,float)) else None,
            "gs_kt": int((s[9] or 0)*1.94384) if len(s)>9 and s[9] is not None else None,
            "trk": s[10] if len(s)>10 else None,
        })
    return out

_OSK_FIELDS = [
    "icao24","callsign","origin_country","time_position","last_contact",
    "longitude","latitude","baro_altitude","on_ground","velocity",
    "true_track","vertical_rate","sensors","geo_altitude",
    "squawk","spi","position_source","category"
]

def normalize_opensky_wide(js: Dict[str, Any]) -> List[Dict[str, Any]]:
    out=[]
    for s in (js.get("states") or []):
        row={}
        for i, name in enumerate(_OSK_FIELDS):
            row[name] = s[i] if len(s)>i else None
        row["hex"] = row.get("icao24")
        if isinstance(row.get("baro_altitude"), (int,float)): row["baro_ft"] = int(row["baro_altitude"]*3.28084)
        if isinstance(row.get("geo_altitude"), (int,float)):  row["geo_ft"]  = int(row["geo_altitude"]*3.28084)
        if isinstance(row.get("velocity"), (int,float)):      row["gs_kt"]   = int(row["velocity"]*1.94384)
        if isinstance(row.get("vertical_rate"), (int,float)): row["vs_fpm"]  = int(row["vertical_rate"]*196.850394)
        out.append(row)
    return out

# ====================== ADSB.lol ======================
def fetch_adsb(lat: float, lon: float, radius_nm: float, debug: bool, dump: bool) -> Dict[str, Any]:
    url = f"https://api.adsb.lol/v2/point/{lat:.6f}/{lon:.6f}/{int(radius_nm)}"
    r = requests.get(url, headers={"User-Agent": UA_DEFAULT}, timeout=TIMEOUT)
    print(f"  [ADSB.lol] Tried: {r.url}")
    log_http_response(r, "ADSB.lol", debug)
    r.raise_for_status()
    js: Dict[str, Any] = r.json()
    if dump:
        with open("adsb.json","w",encoding="utf-8") as f: json.dump(js, f, ensure_ascii=False, indent=2)
        print("  wrote adsb.json")
    return js

def normalize_adsb(js: Dict[str, Any]) -> List[Dict[str, Any]]:
    out=[]
    for a in (js.get("ac") or js.get("aircraft") or []):
        out.append({
            "hex": a.get("hex") or a.get("icao") or "",
            "flight": (a.get("flight") or a.get("callsign") or "").strip(),
            "lat": a.get("lat"),
            "lon": a.get("lon"),
            "alt_ft": a.get("alt_baro") or a.get("alt_geom"),
            "gs_kt": a.get("gs"),
            "trk": a.get("track") or a.get("true_heading"),
        })
    return out

def normalize_adsb_wide(js: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [dict(a) for a in (js.get("ac") or js.get("aircraft") or [])]

# ====================== FR24 (UNOFFICIAL feed.js via data-cloud HTTPS) ======================
FR24_HOST = "data-cloud.flightradar24.com"
FR24_PATH = "/zones/fcgi/feed.js"
# NOTE: annotate as Any so adding a string "bounds" later is type-safe for Pylance
FR24_DEFAULT_PARAMS: Dict[str, Any] = {
    "faa": 1, "satellite": 1, "mlat": 1, "flarm": 1, "adsb": 1,
    "gnd": 0, "air": 1, "vehicles": 0, "estimated": 1,
    "maxage": 14400, "gliders": 0, "stats": 0
}

def fr24_headers(ua: Optional[str], esp_mode: bool, cookie: Optional[str]) -> Dict[str, str]:
    if esp_mode:
        headers = {"User-Agent": ua or "ESP32HTTPClient/1.0", "Accept": "application/json,*/*", "Accept-Encoding": "identity", "Connection": "close"}
    else:
        headers = {
            "User-Agent": ua or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.flightradar24.com/",
            "Origin": "https://www.flightradar24.com",
            "Accept-Encoding": "identity",
            "Connection": "close",
        }
    if cookie:
        headers["Cookie"] = cookie
    return headers

def fetch_fr24_all(lat: float, lon: float, radius_nm: float, debug: bool, dump: bool,
                   esp_mode: bool, ua: Optional[str], cookie: Optional[str]) -> Dict[str, Any]:
    n,s,w,e = bbox_from_point(lat, lon, radius_nm)
    params: Dict[str, Any] = dict(FR24_DEFAULT_PARAMS)  # explicitly Any for bounds string
    params["bounds"] = f"{n:.6f},{s:.6f},{w:.6f},{e:.6f}"
    url = f"https://{FR24_HOST}{FR24_PATH}"
    r = requests.get(url, params=params, headers=fr24_headers(ua, esp_mode, cookie), timeout=TIMEOUT)
    print(f"  [FR24] Tried: {r.url}")
    log_http_response(r, f"FR24 {FR24_HOST}", debug)
    r.raise_for_status()
    ct = (r.headers.get("Content-Type") or "").lower()
    if "json" not in ct:
        body = r.text
        if dump:
            fname = f"fr24_{FR24_HOST}_https.html"
            with open(fname,"w",encoding="utf-8") as f: f.write(body)
            print(f"  wrote {fname} (non-JSON; likely HTML/CF)")
        raise RuntimeError(f"Non-JSON response ({ct})")
    js: Dict[str, Any] = r.json()
    if dump:
        fname = f"fr24_{FR24_HOST}_https.json"
        with open(fname,"w",encoding="utf-8") as f: json.dump(js, f, ensure_ascii=False, indent=2)
        print(f"  wrote {fname}")
    return js

def inspect_fr24(js: Dict[str, Any]) -> None:
    keys = list(js.keys())
    arr_keys = [k for k,v in js.items() if isinstance(v, list)]
    meta_keys = [k for k,v in js.items() if not isinstance(v, list)]
    print(f"  [FR24] keys: {keys[:12]}{' ...' if len(keys)>12 else ''}")
    print(f"  [FR24] aircraft arrays: {len(arr_keys)} | meta keys: {meta_keys[:10]}")
    if arr_keys:
        k = arr_keys[0]; v = js[k]
        print(f"  [FR24] sample key '{k}' len {len(v)}:")
        for i, val in enumerate(v[:18]):
            print(f"     idx[{i:02d}] = {val}")

def normalize_fr24(js: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows=[]
    for _, v in js.items():
        if not isinstance(v, list): continue
        rows.append({
            "hex": v[0] if len(v)>0 else "", "flight": (v[13] or "") if len(v)>13 else "",
            "reg": v[9] if len(v)>9 else "", "type": v[8] if len(v)>8 else "",
            "lat": v[1] if len(v)>1 else None, "lon": v[2] if len(v)>2 else None,
            "alt_ft": v[4] if len(v)>4 else None, "gs_kt": v[5] if len(v)>5 else None, "trk": v[3] if len(v)>3 else None
        })
    return rows

def normalize_fr24_wide(js: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows=[]
    named_map = {
        'hex':0, 'lat':1, 'lon':2, 'trk':3, 'alt_ft':4, 'gs_kt':5, 'squawk':6, 'radar':7,
        'type':8, 'reg':9, 'timestamp':10, 'from_iata':11, 'to_iata':12, 'flight':13,
        'on_ground':14, 'vs_fpm':15, 'callsign':16, 'airline_icao':18
    }
    named_idx = set(named_map.values())
    for _, v in js.items():
        if not isinstance(v, list): continue
        row = {k: (v[i] if len(v)>i else None) for k,i in named_map.items()}
        for i in range(len(v)):
            if i not in named_idx:
                row[f"idx_{i}"] = v[i]
        rows.append(row)
    return rows

# ====================== MIL (ADSB.lol) helpers ======================
class MilCache:
    """TTL cache for per-hex MIL lookups via /v2/hex/{HEX}."""
    def __init__(self, path=MIL_CACHE_FILE_DEFAULT, ttl=MIL_TTL_DEFAULT, debug=False):
        self.path, self.ttl, self.debug = path, ttl, debug
        self.cache: Dict[str, Dict[str, Any]] = {}
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.cache = json.load(f)
            except Exception:
                self.cache = {}

    def _save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _expired(self, t):
        return (time.time() - t) > self.ttl

    def check_hex(self, hex_str: str) -> Optional[bool]:
        if not hex_str or hex_str.startswith("~"):
            return None
        key = hex_str.upper()
        ent = self.cache.get(key)
        if ent and not self._expired(ent.get("ts", 0)):
            return ent.get("mil")
        url = f"https://api.adsb.lol/v2/hex/{key}"
        try:
            r = requests.get(url, headers={"User-Agent": UA_DEFAULT}, timeout=TIMEOUT)
            if self.debug: print(f"  [MIL perhex] {url} -> {r.status_code}")
            r.raise_for_status()
            js = r.json()
            ac = (js.get("ac") or js.get("aircraft") or [])
            mil_flag = None
            if ac:
                a0 = ac[0]
                flags = a0.get("dbFlags") or a0.get("dbflags") or 0
                mil_flag = bool(flags & 1) if isinstance(flags, int) else a0.get("mil")
            elif isinstance(js, dict) and "mil" in js:
                mil_flag = bool(js["mil"])
            self.cache[key] = {"mil": mil_flag, "ts": time.time()}
            self._save()
            return mil_flag
        except Exception as e:
            if self.debug: print(f"  [MIL perhex] error for {key}: {e}")
            self.cache[key] = {"mil": None, "ts": time.time()}
            self._save()
            return None

class MilListCache:
    """TTL cache for global /v2/mil list."""
    def __init__(self, path=MIL_LIST_CACHE_FILE_DEFAULT, ttl=MIL_TTL_DEFAULT, debug=False):
        self.path, self.ttl, self.debug = path, ttl, debug
        self.data: Optional[Dict[str, Any]] = None  # {'ts': float, 'hexes': set, 'rows': list}
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    blob = json.load(f)
                    blob["hexes"] = set(blob.get("hexes", []))
                    self.data = blob
            except Exception:
                self.data = None

    def _save(self):
        # Guard for None to satisfy type checker and runtime
        if not self.data:
            return
        try:
            blob = {"ts": self.data["ts"], "hexes": sorted(self.data["hexes"]), "rows": self.data["rows"]}
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(blob, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_list(self) -> Dict[str, Any]:
        if self.data and (time.time() - self.data["ts"]) <= self.ttl:
            return self.data
        url = "https://api.adsb.lol/v2/mil"
        r = requests.get(url, headers={"User-Agent": UA_DEFAULT}, timeout=TIMEOUT)
        print(f"  [ADSB.lol] Tried: {r.url}")
        log_http_response(r, "ADSB.lol /v2/mil", self.debug)
        r.raise_for_status()
        js = r.json()
        rows = [dict(a) for a in (js.get("ac") or [])]
        hexes = { (a.get("hex") or "").upper() for a in rows if a.get("hex") }
        self.data = {"ts": time.time(), "hexes": hexes, "rows": rows}
        self._save()
        return self.data

# Utility: print & purge per-hex cache file
def print_mil_cache_file(path: str, max_items: int = 25):
    print(f"\nMIL per-hex cache file: {path}")
    if not os.path.exists(path):
        print("  (no cache file)")
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        total = len(data)
        n_true = sum(1 for v in data.values() if v.get("mil") is True)
        n_false = sum(1 for v in data.values() if v.get("mil") is False)
        n_none = total - n_true - n_false
        print(f"  entries: {total} | mil=True: {n_true} | mil=False: {n_false} | mil=None: {n_none}")
        for i, (hx, ent) in enumerate(sorted(data.items())[:max_items]):
            ts = ent.get("ts")
            age = f"{int(time.time()-ts)}s ago" if isinstance(ts, (int,float)) else "?"
            print(f"   {hx}: mil={ent.get('mil')} | cached {age}")
        if total > max_items:
            print(f"  ... {total - max_items} more")
    except Exception as e:
        print(f"  (error reading cache: {e})")

def purge_mil_cache_file(path: str):
    if os.path.exists(path):
        try:
            os.remove(path)
            print(f"Purged MIL per-hex cache: {path}")
        except Exception as e:
            print(f"Could not purge MIL per-hex cache: {e}")
    else:
        print(f"No MIL per-hex cache to purge at: {path}")

# ====================== Main ======================
def main():
    epilog = "See README.md for examples and usage patterns."
    ap = argparse.ArgumentParser(
        description="Compare OpenSky, ADSB.lol, and FR24 feed.js near a point; with MIL tagging, Excel, and JSON export.",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("lat", type=sanitize_float); ap.add_argument("lon", type=sanitize_float)
    ap.add_argument("-r","--radius", type=float, default=50.0, help="radius in NM (default 50)")
    ap.add_argument("--dump", action="store_true", help="write opensky.json / adsb.json / fr24_*.json/html")
    ap.add_argument("--debug", action="store_true", help="verbose HTTP logs + FR24 key inspection")

    # ---- Display mode: wide default, --narrow to opt into compact view ----
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--wide",   dest="wide",   action="store_true",
                       help="show ALL fields from each provider (very wide tables) [default]")
    group.add_argument("--narrow", dest="wide",   action="store_false",
                       help="compact per-provider table (legacy view)")
    ap.set_defaults(wide=True)

    ap.add_argument("--xlsx", default=None, help="export results to an Excel .xlsx with one sheet per provider + a 'Notes' sheet (+MIL sheet in list mode)")

    # ---------- NEW: JSON export / handoff ----------
    ap.add_argument("--json-out", default=None,
                    help="write a single combined JSON payload to this path")
    ap.add_argument("--json-stdout", action="store_true",
                    help="print the combined JSON payload to stdout (useful for piping)")
    ap.add_argument("--json-shm", default=None,
                    help="also write JSON to a tmpfs path (e.g., /dev/shm/plane_compare.json) for fast local IPC")
    ap.add_argument("--json-minify", action="store_true",
                    help="emit compact JSON without whitespace (default is pretty)")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress console tables/logs by redirecting prints to stderr (use with --json-stdout)")

    # OpenSky credentials (CLI override)
    ap.add_argument("--osk-client-id", default=None); ap.add_argument("--osk-client-secret", default=None)
    # FR24 knobs
    ap.add_argument("--fr24-esp", action="store_true", help="mimic ESP32 HTTPClient headers")
    ap.add_argument("--fr24-cookie", default=None, help='raw Cookie header (paste from your browser if needed)')
    ap.add_argument("--fr24-ua", default=None, help="custom User-Agent for FR24 requests")
    # Skips
    ap.add_argument("--skip-fr24", action="store_true"); ap.add_argument("--skip-adsb", action="store_true"); ap.add_argument("--skip-opensky", action="store_true")
    # MIL options
    ap.add_argument("--mil-mode", choices=["off","perhex","list"], default="perhex",
                    help="MIL classification: off, perhex (/v2/hex/{HEX}+TTL), or list (/v2/mil global+TTL)")
    ap.add_argument("--mil-ttl", type=int, default=MIL_TTL_DEFAULT, help="TTL (seconds) for MIL cache/list (default 21600)")
    ap.add_argument("--mil-cache", default=MIL_CACHE_FILE_DEFAULT, help="path to per-hex MIL cache file")
    ap.add_argument("--mil-list-cache", default=MIL_LIST_CACHE_FILE_DEFAULT, help="path to /v2/mil list cache file")
    ap.add_argument("--print-mil-cache", action="store_true", help="print a summary/sample of the per-hex MIL cache after run")
    ap.add_argument("--purge-mil-cache", action="store_true", help="delete the per-hex MIL cache before running")

    args = ap.parse_args()

    # Environment fallbacks for FR24 parameters
    if args.fr24_cookie is None:
        args.fr24_cookie = os.getenv("FR24_COOKIE")
    if args.fr24_ua is None:
        args.fr24_ua = os.getenv("FR24_UA")
    if not args.fr24_esp:
        _env_esp = os.getenv("FR24_ESP")
        if _env_esp and _env_esp.lower() in ("1", "true", "yes", "on"):
            args.fr24_esp = True

    # Redirect prints to stderr for clean stdout JSON when --quiet is set
    import builtins as _bi
    _ORIG_PRINT = _bi.print
    if args.quiet:
        def _stderr_print(*a, **k):
            k = dict(k)
            k["file"] = sys.stderr
            _ORIG_PRINT(*a, **k)
        globals()["print"] = _stderr_print

    if args.purge_mil_cache:
        purge_mil_cache_file(args.mil_cache)

    client_id = args.osk_client_id or OSK_CLIENT_ID_DEFAULT or os.getenv("OSK_CLIENT_ID")
    client_secret = args.osk_client_secret or OSK_CLIENT_SECRET_DEFAULT or os.getenv("OSK_CLIENT_SECRET")
    if args.osk_client_id and not args.osk_client_secret:
        client_secret = getpass.getpass("OpenSky client_secret: ")

    print(f"\nPoint: lat={args.lat:.6f}, lon={args.lon:.6f}, radius={args.radius:.1f} NM")
    print("OpenSky auth:", "OAuth2 client credentials" if (client_id and client_secret) else "anonymous")

    # ---- MIL setup ----
    mil_list_rows: List[Dict[str, Any]] = []
    mil_hex_set: set = set()
    mil_list_loaded = False
    mil_perhex_cache = None

    if args.mil_mode == "list":
        header("ADSB.lol /v2/mil (global list of military hexes)")
        try:
            mil_list_cache = MilListCache(path=args.mil_list_cache, ttl=args.mil_ttl, debug=args.debug)
            data = mil_list_cache.get_list()
            mil_list_rows = data["rows"]
            mil_hex_set = data["hexes"]
            mil_list_loaded = True
            print(f"Loaded {len(mil_hex_set)} military hexes (cached TTL {args.mil_ttl}s)")
            if mil_list_rows:
                preferred = ["hex","r","t","flight","category","dbFlags","seen","messages"]
                fields = union_fields(mil_list_rows, preferred)[:min(12, len(preferred)+5)]
                table(mil_list_rows, fields)
        except Exception as e:
            print(f"  Error loading /v2/mil: {e}")

    elif args.mil_mode == "perhex":
        mil_perhex_cache = MilCache(path=args.mil_cache, ttl=args.mil_ttl, debug=args.debug)
        print(f"MIL mode: perhex (TTL {args.mil_ttl}s; cache file {args.mil_cache})")

    def annotate_mil(rows: List[Dict[str, Any]], hex_field: str):
        if not rows: return
        if args.mil_mode == "off": return
        if args.mil_mode == "list" and mil_list_loaded:
            for r in rows:
                hx = (r.get(hex_field) or "").upper()
                r["mil"] = (hx in mil_hex_set) if hx else None
        elif args.mil_mode == "perhex" and mil_perhex_cache is not None:
            for r in rows:
                hx = (r.get(hex_field) or "").upper()
                r["mil"] = mil_perhex_cache.check_hex(hx) if hx else None

    osk_rows: List[Dict[str, Any]] = []
    lol_rows: List[Dict[str, Any]] = []
    fr_rows: List[Dict[str, Any]] = []

    # ---- OpenSky ----
    if not args.skip_opensky:
        header("OpenSky /states/all")
        try:
            osk_raw = fetch_opensky(args.lat, args.lon, args.radius, client_id, client_secret, args.debug, args.dump)
            if args.wide:
                osk_rows = normalize_opensky_wide(osk_raw)
                annotate_mil(osk_rows, "hex")
                osk_fields = union_fields(osk_rows, _OSK_FIELDS + ["hex","baro_ft","geo_ft","gs_kt","vs_fpm","mil"])
                print(f"Found {len(osk_rows)} aircraft (wide)")
                table(osk_rows, osk_fields)
            else:
                osk_rows = normalize_opensky(osk_raw)
                annotate_mil(osk_rows, "hex")
                cols = ["hex","flight","lat","lon","alt_ft","gs_kt","trk"]
                if args.mil_mode != "off": cols.append("mil")
                print(f"Found {len(osk_rows)} aircraft (narrow)")
                table(osk_rows, cols)
        except Exception as e:
            print(f"  Error: {e}")

    # ---- ADSB.lol ----
    if not args.skip_adsb:
        header("ADSB.lol /v2/point")
        try:
            lol_raw = fetch_adsb(args.lat, args.lon, args.radius, args.debug, args.dump)
            if args.wide:
                lol_rows = normalize_adsb_wide(lol_raw)
                annotate_mil(lol_rows, "hex")
                preferred = ["hex","flight","r","t","lat","lon","alt_baro","alt_geom","gs","track","true_heading",
                             "baro_rate","geom_rate","squawk","category","emergency","nav_qnh","nav_altitude_mcp","nav_heading",
                             "nav_modes","mlat","tisb","seen","seen_pos","rssi","messages","nac_p","nac_v","sil","sil_type","gva","sda","mil"]
                lol_fields = union_fields(lol_rows, preferred)
                print(f"Found {len(lol_rows)} aircraft (wide)")
                table(lol_rows, lol_fields)
            else:
                lol_rows = normalize_adsb(lol_raw)
                annotate_mil(lol_rows, "hex")
                cols = ["hex","flight","lat","lon","alt_ft","gs_kt","trk"]
                if args.mil_mode != "off": cols.append("mil")
                print(f"Found {len(lol_rows)} aircraft (narrow)")
                table(lol_rows, cols)
        except Exception as e:
            print(f"  Error: {e}")

    # ---- FR24 ----
    if not args.skip_fr24:
        header("Flightradar24 feed.js (UNOFFICIAL, via data-cloud HTTPS)")
        try:
            fr_raw = fetch_fr24_all(args.lat, args.lon, args.radius, args.debug, args.dump, args.fr24_esp, args.fr24_ua, args.fr24_cookie)
            if args.debug: inspect_fr24(fr_raw)
            if args.wide:
                fr_rows = normalize_fr24_wide(fr_raw)
                annotate_mil(fr_rows, "hex")
                preferred = ["hex","flight","callsign","airline_icao","reg","type","lat","lon","alt_ft","gs_kt","trk",
                             "squawk","radar","timestamp","from_iata","to_iata","on_ground","vs_fpm","mil"]
                fr_fields = union_fields(fr_rows, preferred)
                print(f"Found {len(fr_rows)} aircraft (wide)")
                table(fr_rows, fr_fields)
            else:
                fr_rows = normalize_fr24(fr_raw)
                annotate_mil(fr_rows, "hex")
                cols = ["hex","flight","reg","type","lat","lon","alt_ft","gs_kt","trk"]
                if args.mil_mode != "off": cols.append("mil")
                print(f"Found {len(fr_rows)} aircraft (narrow)")
                table(fr_rows, cols)
        except Exception as e:
            print(f"  Error: {e}  (open any fr24_*.json/html files for details)")
            print("  If HTML/Cloudflare or only meta keys appear, you're being filtered; consider FR24's official API or use OpenSky/ADSB.lol.")

    # ---------- Combined JSON export (no merging) ----------
    combined_all: List[Dict[str, Any]] = []
    for r in osk_rows:
        combined_all.append({"provider": "opensky", **r})
    for r in lol_rows:
        combined_all.append({"provider": "adsb.lol", **r})
    for r in fr_rows:
        combined_all.append({"provider": "fr24", **r})

    payload: Dict[str, Any] = {
        "timestamp": int(time.time()),
        "point": {"lat": args.lat, "lon": args.lon, "radius_nm": args.radius},
        "mil": {"mode": args.mil_mode, "ttl": args.mil_ttl},
        "providers": {
            "opensky": osk_rows,
            "adsb_lol": lol_rows,
            "fr24": fr_rows,
        },
        "all": combined_all,
    }

    # write to file if requested
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=None if args.json_minify else 2)
        print(f"Wrote JSON: {args.json_out}")

    # write to tmpfs (Linux) for 'in-memory' style handoff if requested
    if args.json_shm:
        try:
            with open(args.json_shm, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=None if args.json_minify else 2)
            print(f"Wrote JSON to tmpfs: {args.json_shm}")
        except Exception as e:
            print(f"  Error writing --json-shm: {e}")

    # print to stdout for piping
    if args.json_stdout:
        _ORIG_PRINT(json.dumps(payload, ensure_ascii=False, indent=None if args.json_minify else 2))

    # ---------- Excel export ----------
    if args.xlsx:
        if pd is None:
            print("Excel export requested but pandas is not installed. Install with: pip install pandas openpyxl")
            sys.exit(2)

        pandas = cast(Any, pd)  # make Pylance happy about DataFrame/ExcelWriter

        def write_sheet(writer: Any, name: str, rows: List[Dict[str, Any]], preferred: List[str]) -> None:
            flat_rows = [{k: stringify_complex(v) for k, v in r.items()} for r in rows]
            if flat_rows:
                cols = union_fields(flat_rows, preferred)
                df = pandas.DataFrame(flat_rows, columns=cols)
            else:
                df = pandas.DataFrame(columns=preferred)
            df.to_excel(writer, sheet_name=name, index=False)

        with pandas.ExcelWriter(args.xlsx) as writer:
            write_sheet(writer, "OpenSky",  osk_rows, _OSK_FIELDS + ["hex","baro_ft","geo_ft","gs_kt","vs_fpm","mil"])
            write_sheet(writer, "ADSB.lol", lol_rows, ["hex","flight","r","t","lat","lon","alt_baro","alt_geom","gs","track",
                                                       "true_heading","baro_rate","geom_rate","squawk","category","emergency",
                                                       "nav_qnh","nav_altitude_mcp","nav_heading","nav_modes","mlat","tisb",
                                                       "seen","seen_pos","rssi","messages","nac_p","nac_v","sil","sil_type","gva","sda","mil"])
            write_sheet(writer, "FR24",     fr_rows,  ["hex","flight","callsign","airline_icao","reg","type","lat","lon","alt_ft","gs_kt","trk",
                                                       "squawk","radar","timestamp","from_iata","to_iata","on_ground","vs_fpm","mil"])

            # Notes sheet
            notes_rows = [{"Section": sec, "Content": txt} for sec, txt in NOTES_TEXT.items()]
            notes_df = pandas.DataFrame(notes_rows, columns=["Section","Content"])
            notes_df.to_excel(writer, sheet_name="Notes", index=False)

            # MIL sheet (only for list mode)
            if args.mil_mode == "list":
                flat = [{k: stringify_complex(v) for k, v in r.items()} for r in mil_list_rows]
                preferred = ["hex","r","t","flight","category","dbFlags","seen","seen_pos","messages",
                             "lat","lon","alt_baro","alt_geom","gs","track","true_heading"]
                cols = union_fields(flat, preferred)
                df = pandas.DataFrame(flat, columns=cols) if flat else pandas.DataFrame(columns=preferred)
                df.to_excel(writer, sheet_name="MIL", index=False)

        print(f"\nWrote Excel workbook: {args.xlsx}")

    if args.print_mil_cache:
        print_mil_cache_file(args.mil_cache)

if __name__ == "__main__":
    main()
