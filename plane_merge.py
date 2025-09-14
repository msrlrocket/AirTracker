#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, json, argparse, time, re, os, math
from typing import Dict, Any, List, Optional

PROVIDERS = ["adsb_lol", "fr24", "opensky"]
DEFAULT_PRIORITY = ["adsb_lol", "fr24", "opensky"]

# unit helpers
MPS_TO_FPM = 196.850394  # meters/sec -> feet/min
MPS_TO_KT  = 1.943844    # meters/sec -> knots
M_TO_FT    = 3.280839895 # meters -> feet

# ---------- helpers ----------
def _upper(s: Optional[str]) -> Optional[str]:
    return s.upper() if isinstance(s, str) else s

def _clean_str(s: Optional[str]) -> Optional[str]:
    if s is None: return None
    s = str(s).strip()
    return s if s else None

def stringify_complex(v: Any) -> Any:
    if isinstance(v, (dict, list, tuple)):
        return json.dumps(v, ensure_ascii=False)
    return v

def union_fields(rows: List[Dict[str, Any]], preferred: List[str]) -> List[str]:
    keys = set()
    for r in rows:
        keys.update(r.keys())
    ordered = [k for k in preferred if k in keys]
    rest = sorted(k for k in keys if k not in ordered)
    return ordered + rest

IATA_FLIGHT_RE = re.compile(r"^[A-Z0-9]{2,3}\d{1,4}[A-Z]?$")

def looks_like_iata_flight(s: Optional[str]) -> bool:
    s = _clean_str(s)
    return bool(s and IATA_FLIGHT_RE.match(s))

# ---------- dataset lookups (JSONL) ----------
def _datasets_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "datasets")

def _load_jsonl_map(path: str, key_field: str) -> Dict[str, dict]:
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

def _ensure_parent_dir(path: str) -> None:
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
    except Exception:
        pass

def _load_catalogs(ds_root: Optional[str] = None) -> Dict[str, Dict[str, dict]]:
    ds = ds_root or _datasets_root()
    cats = {
        "aircraft": _load_jsonl_map(os.path.join(ds, "aircraft_types_full.jsonl"), "icao"),
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
    if not icao:
        return None
    t = icao.upper()
    # Heuristics inspired by aircraft_types.h family rules
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
    # GA / Bizjet common types (prefix or exact)
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

def _airline_from_flight_no(flight_no: Optional[str], cats: Dict[str, Dict[str, dict]]) -> Optional[dict]:
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
    """Returns a shallow copy of row with additional 'lookups' info and select flat fields such as
    souls_on_board_max. When the aircraft type is not found in the dataset, explicitly indicate that
    and fall back to the raw type code for display. Also always publish a text value for souls
    (e.g., 'N/A' when unknown)."""
    out = dict(row)
    lookups: Dict[str, Any] = {}

    # Aircraft by ICAO type
    icao_type = _clean_str(row.get("aircraft_type"))
    if icao_type:
        a = cats.get("aircraft", {}).get(icao_type)
        seat_actual: Optional[int] = None
        if a:
            lookups["aircraft"] = {
                "icao": icao_type,
                "name": a.get("name") or a.get("model") or icao_type,
                "manufacturer": a.get("manufacturer"),
                "model": a.get("model"),
                "seats_max": a.get("seats"),
                "iata_aliases": a.get("iata") or [],
                "lookup_status": "found",
            }
            if isinstance(a.get("seats"), int) and a.get("seats", 0) > 0:
                seat_actual = int(a["seats"])
        else:
            # Explicitly indicate that this ICAO type was not found in the dataset; fall back to code
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
        airline = _airline_from_flight_no(_clean_str(row.get("flight_no")), cats)
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

def provider_age(now_ts: int, p: str, row: Dict[str, Any]) -> Optional[float]:
    """Freshness age in seconds. Lower is fresher."""
    try:
        if p == "opensky":
            t = row.get("last_contact") or row.get("time_position")
            return float(now_ts - t) if t is not None else None
        elif p == "adsb_lol":
            seen = row.get("seen")
            return float(seen) if seen is not None else None
        elif p == "fr24":
            ts = row.get("timestamp")
            return float(now_ts - ts) if ts is not None else None
    except Exception:
        pass
    return None

def pick_value_and_source(candidates: Dict[str, Dict[str, Any]],
                          now_ts: int,
                          priority: List[str],
                          adapters: Dict[str, Any]):
    """
    Choose a field value among providers based on smallest age, then priority.
    Returns (value, provider) or (None, None).
    adapters: per-provider converter: adapters[p](provider_key) -> value_or_None
    """
    per: Dict[str, Any] = {}
    for p, row in candidates.items():
        try:
            # Adapter functions expect provider key (p), not the row.
            per[p] = adapters[p](p)
        except Exception:
            per[p] = None

    with_value = [p for p,v in per.items() if v not in (None, "", [])]
    if not with_value:
        return None, None

    scored = []
    for p in with_value:
        age = provider_age(now_ts, p, candidates[p])
        scored.append((age if age is not None else float("inf"), p))

    min_age = min(a for a,_ in scored)
    freshest = [p for a,p in scored if a == min_age]
    for pr in priority:
        if pr in freshest:
            return per[pr], pr
    for pr in priority:  # fallback
        if pr in with_value:
            return per[pr], pr
    return None, None

def pick_by_freshness(candidates: Dict[str, Dict[str, Any]],
                      now_ts: int,
                      priority: List[str],
                      adapters: Dict[str, Any]) -> Any:
    v, _ = pick_value_and_source(candidates, now_ts, priority, adapters)
    return v

# ---------- merging ----------
def merge_one_hex(now_ts: int,
                  by_provider: Dict[str, Dict[str, Any]],
                  priority: List[str]) -> Dict[str, Any]:
    # hex
    hex_candidates = []
    if "opensky" in by_provider: hex_candidates.append(by_provider["opensky"].get("hex") or by_provider["opensky"].get("icao24"))
    if "adsb_lol" in by_provider: hex_candidates.append(by_provider["adsb_lol"].get("hex"))
    if "fr24"     in by_provider: hex_candidates.append(by_provider["fr24"].get("hex"))
    hex_norm = _upper(next((h for h in hex_candidates if h), None)) or "UNKNOWN"

    out: Dict[str, Any] = {
        "hex": hex_norm,
        "merged_timestamp": now_ts,
        "sources": sorted(list(by_provider.keys()))
    }

    # ----- adapters for freshness-picked fields -----
    def get_lat(p: str) -> Optional[float]:
        r = by_provider[p]
        return r.get("latitude") if p == "opensky" else r.get("lat")

    def get_lon(p: str) -> Optional[float]:
        r = by_provider[p]
        return r.get("longitude") if p == "opensky" else r.get("lon")

    def get_alt_ft(p: str) -> Optional[float]:
        r = by_provider[p]
        if p == "adsb_lol":
            v = r.get("alt_geom")
            if v is None: v = r.get("alt_baro")
            return float(v) if v is not None else None
        if p == "fr24":
            v = r.get("alt_ft")
            return float(v) if v is not None else None
        # opensky: prefer *_ft if present, else convert meters
        v = r.get("geo_ft")
        if v is not None: return float(v)
        v = r.get("baro_ft")
        if v is not None: return float(v)
        geo_alt_m = r.get("geo_altitude")
        if geo_alt_m is not None: return float(geo_alt_m) * M_TO_FT
        baro_alt_m = r.get("baro_altitude")
        if baro_alt_m is not None: return float(baro_alt_m) * M_TO_FT
        return None

    def get_gs_kt(p: str) -> Optional[float]:
        r = by_provider[p]
        if p == "adsb_lol":
            v = r.get("gs")
            return float(v) if v is not None else None
        if p == "fr24":
            v = r.get("gs_kt")
            return float(v) if v is not None else None
        # opensky
        v = r.get("gs_kt")
        if v is not None: return float(v)
        vel_mps = r.get("velocity")
        return float(vel_mps) * MPS_TO_KT if vel_mps is not None else None

    def get_trk(p: str) -> Optional[float]:
        r = by_provider[p]
        if p == "adsb_lol":
            v = r.get("track")
            return float(v) if v is not None else None
        if p == "fr24":
            v = r.get("trk")
            return float(v) if v is not None else None
        v = r.get("true_track")
        return float(v) if v is not None else None

    def get_squawk(p: str) -> Optional[str]:
        return _clean_str(by_provider[p].get("squawk"))

    def get_on_ground(p: str) -> Optional[bool]:
        v = by_provider[p].get("on_ground")
        if isinstance(v, (int, float)): return bool(v)
        return v if isinstance(v, bool) else None

    def get_vs_fpm(p: str) -> Optional[int]:
        r = by_provider[p]
        try:
            if p == "adsb_lol":
                vv = r.get("baro_rate")
                if vv is None: vv = r.get("geom_rate")
                return int(round(float(vv))) if vv is not None else None
            if p == "fr24":
                vv = r.get("vs_fpm")
                return int(round(float(vv))) if vv is not None else None
            # opensky
            vv = r.get("vs_fpm")
            if vv is not None:
                return int(round(float(vv)))
            vr_mps = r.get("vertical_rate")
            return int(round(float(vr_mps) * MPS_TO_FPM)) if vr_mps is not None else None
        except Exception:
            return None

    # ----- live telemetry (picked by freshness) -----
    lat,   lat_src  = pick_value_and_source(by_provider, now_ts, priority, {"opensky": get_lat, "adsb_lol": get_lat, "fr24": get_lat})
    lon,   lon_src  = pick_value_and_source(by_provider, now_ts, priority, {"opensky": get_lon, "adsb_lol": get_lon, "fr24": get_lon})
    alt,   alt_src  = pick_value_and_source(by_provider, now_ts, priority, {"opensky": get_alt_ft, "adsb_lol": get_alt_ft, "fr24": get_alt_ft})
    vrfpm, vr_src   = pick_value_and_source(by_provider, now_ts, priority, {"opensky": get_vs_fpm, "adsb_lol": get_vs_fpm, "fr24": get_vs_fpm})
    gs,    gs_src   = pick_value_and_source(by_provider, now_ts, priority, {"opensky": get_gs_kt, "adsb_lol": get_gs_kt, "fr24": get_gs_kt})
    trk,   trk_src  = pick_value_and_source(by_provider, now_ts, priority, {"opensky": get_trk, "adsb_lol": get_trk, "fr24": get_trk})
    sq,    sq_src   = pick_value_and_source(by_provider, now_ts, priority, {"opensky": get_squawk, "adsb_lol": get_squawk, "fr24": get_squawk})
    grnd,  grnd_src = pick_value_and_source(by_provider, now_ts, priority, {"opensky": get_on_ground, "adsb_lol": get_on_ground, "fr24": get_on_ground})

    if lat  is not None: out["latitude"] = float(lat)
    if lon  is not None: out["longitude"] = float(lon)
    if alt  is not None: out["altitude_ft"] = int(round(float(alt)))
    if vrfpm is not None: out["vertical_rate_fpm"] = int(round(float(vrfpm)))
    if gs   is not None: out["ground_speed_kt"] = int(round(float(gs)))
    if trk  is not None: out["track_deg"] = float(trk)
    if sq   is not None: out["squawk"] = sq
    if grnd is not None: out["on_ground"] = grnd

    # Record which provider supplied each selected telemetry field
    field_sources: Dict[str, str] = {}
    for key, src in (
        ("latitude", lat_src),
        ("longitude", lon_src),
        ("altitude_ft", alt_src),
        ("vertical_rate_fpm", vr_src),
        ("ground_speed_kt", gs_src),
        ("track_deg", trk_src),
        ("squawk", sq_src),
        ("on_ground", grnd_src),
    ):
        if src is not None and out.get(key) is not None:
            field_sources[key] = src
    if field_sources:
        out["field_sources"] = field_sources

    # Position time/age derived from the provider used for lat/lon
    pos_src = lat_src or lon_src
    pos_ts = None
    if pos_src:
        r = by_provider.get(pos_src, {})
        if pos_src == "opensky":
            pos_ts = r.get("last_contact") or r.get("time_position")
        elif pos_src == "fr24":
            pos_ts = r.get("timestamp")
        elif pos_src == "adsb_lol":
            seen = r.get("seen")
            if seen is not None:
                try:
                    pos_ts = now_ts - float(seen)
                except Exception:
                    pos_ts = None
    if isinstance(pos_ts, (int, float)):
        out["position_timestamp"] = int(round(float(pos_ts)))
        out["position_age_sec"] = float(now_ts - float(pos_ts))

    # ----- identity-ish -----
    # Origin country (primarily available from OpenSky)
    oc = _clean_str(by_provider.get("opensky", {}).get("origin_country"))
    if oc: out["origin_country"] = oc
    reg = _clean_str(by_provider.get("fr24", {}).get("reg")) or _clean_str(by_provider.get("adsb_lol", {}).get("r"))
    if reg: out["registration"] = reg

    typ = (_clean_str(by_provider.get("adsb_lol", {}).get("t"))
           or _clean_str(by_provider.get("fr24", {}).get("type"))
           or _clean_str(by_provider.get("opensky", {}).get("type")))
    if typ: out["aircraft_type"] = typ

    air = _clean_str(by_provider.get("fr24", {}).get("airline_icao"))
    if air: out["airline_icao"] = air

    cs = (_clean_str(by_provider.get("adsb_lol", {}).get("flight"))
          or _clean_str(by_provider.get("adsb_lol", {}).get("callsign"))
          or _clean_str(by_provider.get("fr24", {}).get("callsign"))
          or _clean_str(by_provider.get("opensky", {}).get("callsign")))
    if cs: out["callsign"] = cs

    fr_f = _clean_str(by_provider.get("fr24", {}).get("flight"))
    ad_f = _clean_str(by_provider.get("adsb_lol", {}).get("flight"))
    if looks_like_iata_flight(fr_f): out["flight_no"] = fr_f
    elif looks_like_iata_flight(ad_f): out["flight_no"] = ad_f
    elif fr_f: out["flight_no"] = fr_f
    elif ad_f: out["flight_no"] = ad_f

    fr = by_provider.get("fr24", {})
    if _clean_str(fr.get("from_iata")) or _clean_str(fr.get("to_iata")):
        out["origin_iata"] = _clean_str(fr.get("from_iata"))
        out["destination_iata"] = _clean_str(fr.get("to_iata"))

    mil_vals = []
    for _, row in by_provider.items():
        v = row.get("mil")
        mil_vals.append(v if isinstance(v, bool) else None)
    out["is_military"] = (True if any(v is True for v in mil_vals)
                          else (False if any(v is False for v in mil_vals) and not any(v is True for v in mil_vals)
                                else None))

    ages = {p: provider_age(now_ts, p, row) for p, row in by_provider.items()}
    out["age_adsb_lol_sec"] = ages.get("adsb_lol")
    out["age_fr24_sec"]     = ages.get("fr24")
    out["age_opensky_sec"]  = ages.get("opensky")

    # extras
    telemetry_like = {
        "lat","latitude","lon","longitude","alt_ft","altitude_ft","gs_kt","ground_speed_kt",
        "trk","track","track_deg","squawk","on_ground",
        "vertical_rate","vertical_rate_fpm","baro_rate","geom_rate","vs_fpm","velocity",
        "alt_baro","alt_geom","baro_altitude","geo_altitude","baro_ft","geo_ft",
        "gs","gs_kt","true_track",
        "time_position","last_contact","timestamp","seen",
    }
    for p,row in by_provider.items():
        for k,v in row.items():
            if k in telemetry_like or k in ("hex","icao24"):
                continue
            key = f"extras_{p}_{k}"
            if key not in out:
                out[key] = v

    return out

# ---------- Excel helpers ----------
NOTES_TEXT = (
    "See README.md for merge rules, freshness/tie-breaks, and field precedence."
)

def write_excel(path: str,
                payload_in: Dict[str, Any],
                merged_rows: List[Dict[str, Any]],
                include_raw: bool):
    # Dynamic import to avoid Pylance "missing module" & optional-member warnings
    try:
        import importlib
        p = importlib.import_module("pandas")
    except ModuleNotFoundError:
        raise SystemExit("Excel export requested but pandas is not installed. Install with: pip install pandas openpyxl")

    def df_from_rows(rows: List[Dict[str, Any]], preferred: List[str]):
        if not rows:
            return p.DataFrame(columns=preferred)
        flat = [{k: stringify_complex(v) for k,v in r.items()} for r in rows]
        cols = union_fields(flat, preferred)
        return p.DataFrame(flat, columns=cols)

    with p.ExcelWriter(path) as writer:
        merged_pref = [
            "hex","merged_timestamp","sources",
            "latitude","longitude","altitude_ft","vertical_rate_fpm",
            "ground_speed_kt","track_deg","squawk","on_ground",
            "position_timestamp","position_age_sec",
            "distance_nm","bearing_deg","within_radius",
            "registration","aircraft_type","airline_icao","callsign","flight_no","origin_iata","destination_iata",
            "is_military",
            "age_adsb_lol_sec","age_fr24_sec","age_opensky_sec",
        ]
        df_from_rows(merged_rows, merged_pref).to_excel(writer, sheet_name="Merged", index=False)

        stats_items = [
            ("timestamp", payload_in.get("timestamp")),
            ("lat", (payload_in.get("point") or {}).get("lat")),
            ("lon", (payload_in.get("point") or {}).get("lon")),
            ("radius_nm", (payload_in.get("point") or {}).get("radius_nm")),
            ("merged_hex_count", len(merged_rows)),
            ("providers_opensky_rows", len((payload_in.get("providers") or {}).get("opensky") or [])),
            ("providers_adsb_lol_rows", len((payload_in.get("providers") or {}).get("adsb_lol") or (payload_in.get("providers") or {}).get("adsb") or [])),
            ("providers_fr24_rows", len((payload_in.get("providers") or {}).get("fr24") or [])),
        ]
        p.DataFrame(stats_items, columns=["key","value"]).to_excel(writer, sheet_name="Stats", index=False)
        p.DataFrame([{"Section":"Merge Rules", "Content": NOTES_TEXT.strip()}]).to_excel(writer, sheet_name="Notes", index=False)

        if include_raw:
            prov = payload_in.get("providers") or {}
            def df_raw(rows): return p.DataFrame([{k: stringify_complex(v) for k,v in r.items()} for r in (rows or [])])
            df_raw(prov.get("opensky") or []).to_excel(writer, sheet_name="OpenSky", index=False)
            df_raw(prov.get("adsb_lol") or prov.get("adsb") or []).to_excel(writer, sheet_name="ADSB.lol", index=False)
            df_raw(prov.get("fr24") or []).to_excel(writer, sheet_name="FR24", index=False)

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description="Merge OpenSky/ADSB.lol/FR24 rows into one record per hex; export JSON/Excel.")
    ap.add_argument("input", nargs="?", help="Input JSON file (default: STDIN)")
    ap.add_argument("--json-out", default=None, help="Write merged JSON to this file")
    ap.add_argument("--json-stdout", action="store_true", help="Print merged JSON to stdout")
    ap.add_argument("--minify", action="store_true", help="Compact JSON output")
    ap.add_argument("--by-hex", action="store_true", help="Also include a 'by_hex' mapping in JSON")
    ap.add_argument("--prefer", default=",".join(DEFAULT_PRIORITY),
                    help="Provider priority for tie-breaks, e.g. adsb_lol,fr24,opensky")
    ap.add_argument("--xlsx", default=None, help="Export an Excel workbook to this path")
    ap.add_argument("--xlsx-raw", action="store_true", help="Include raw provider sheets in the Excel workbook")
    ap.add_argument("--datasets", default=None, help="Optional path to datasets directory (defaults to ./datasets)")
    ap.add_argument("--enrich-all", action="store_true",
                    help="Enrich all merged aircraft using JSONL datasets (aircraft/airlines/airports/countries)")
    ap.add_argument("--enrich-in-radius", action="store_true",
                    help="[Deprecated] Enrich only aircraft within the provided radius")
    args = ap.parse_args()

    # Load input
    payload = json.load(open(args.input, "r", encoding="utf-8")) if args.input else json.load(sys.stdin)

    providers = payload.get("providers") or {}
    opensky = providers.get("opensky") or []
    adsb   = providers.get("adsb_lol") or providers.get("adsb") or []
    fr24   = providers.get("fr24") or []
    now_ts = int(payload.get("timestamp") or time.time())
    priority = [p.strip() for p in args.prefer.split(",") if p.strip()] or DEFAULT_PRIORITY

    # Group by hex
    groups: Dict[str, Dict[str, Dict[str, Any]]] = {}
    def add(pname: str, row: Dict[str, Any], hex_key: str):
        if not hex_key: return
        hx = _upper(hex_key)
        if not hx or hx == "UNKNOWN": return
        groups.setdefault(hx, {})[pname] = row

    for r in opensky: add("opensky", r, r.get("hex") or r.get("icao24"))
    for r in adsb:    add("adsb_lol", r, r.get("hex"))
    for r in fr24:    add("fr24", r, r.get("hex"))

    # Merge per hex
    merged_internal: List[Dict[str, Any]] = []
    by_hex_map: Dict[str, Dict[str, Any]] = {}
    for hx, bp in groups.items():
        m = merge_one_hex(now_ts, bp, priority)
        merged_internal.append(m)
        by_hex_map[hx] = m

    # Compute range metrics (distance/bearing) relative to point
    def to_rad(x: float) -> float: return x * math.pi / 180.0
    def to_deg(x: float) -> float: return x * 180.0 / math.pi
    def gc_distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        R_nm = 3440.065  # Earth radius in nautical miles
        phi1, phi2 = to_rad(lat1), to_rad(lat2)
        dphi = to_rad(lat2 - lat1)
        dlambda = to_rad(lon2 - lon1)
        a = math.sin(dphi/2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2.0)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R_nm * c
    def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        phi1, phi2 = to_rad(lat1), to_rad(lat2)
        dlambda = to_rad(lon2 - lon1)
        y = math.sin(dlambda) * math.cos(phi2)
        x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
        brng = (to_deg(math.atan2(y, x)) + 360.0) % 360.0
        return brng

    point = payload.get("point") or {}
    p_lat = point.get("lat")
    p_lon = point.get("lon")
    p_rad_nm = point.get("radius_nm")
    if isinstance(p_lat, (int, float)) and isinstance(p_lon, (int, float)):
        for m in merged_internal:
            lat = m.get("latitude")
            lon = m.get("longitude")
            if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                try:
                    dnm = gc_distance_nm(float(p_lat), float(p_lon), float(lat), float(lon))
                    m["distance_nm"] = round(dnm, 3)
                    m["bearing_deg"] = round(initial_bearing_deg(float(p_lat), float(p_lon), float(lat), float(lon)), 1)
                    if isinstance(p_rad_nm, (int, float)):
                        m["within_radius"] = bool(dnm <= float(p_rad_nm))
                except Exception:
                    pass

    # Sort by freshness then hex
    def min_age(m: Dict[str, Any]) -> float:
        ages = [a for a in (m.get("age_adsb_lol_sec"), m.get("age_fr24_sec"), m.get("age_opensky_sec")) if isinstance(a, (int,float))]
        return min(ages) if ages else float("inf")
    def dist_key(m: Dict[str, Any]) -> float:
        d = m.get("distance_nm")
        return float(d) if isinstance(d, (int, float)) else float("inf")
    merged_internal.sort(key=lambda m: (min_age(m), dist_key(m), m.get("hex","")))

    # Optional enrichment
    if args.enrich_all or args.enrich_in_radius:
        catalogs = _load_catalogs(args.datasets)
        for m in merged_internal:
            if args.enrich_all or m.get("within_radius") is True:
                e = enrich_with_catalogs(m, catalogs)
                if "souls_on_board_max" in e:
                    m["souls_on_board_max"] = e["souls_on_board_max"]
                    if "souls_on_board_max_is_estimate" in e:
                        m["souls_on_board_max_is_estimate"] = e["souls_on_board_max_is_estimate"]
                    if "souls_on_board_max_text" in e:
                        m["souls_on_board_max_text"] = e["souls_on_board_max_text"]
                if "lookups" in e:
                    m["lookups"] = e["lookups"]

    cats_for_eta = None
    for m in merged_internal:
        try:
            lat = m.get("latitude")
            lon = m.get("longitude")
            spd = m.get("ground_speed_kt")
            dst_iata = _clean_str(m.get("destination_iata"))
            if not (isinstance(lat, (int,float)) and isinstance(lon, (int,float)) and isinstance(spd, (int,float)) and spd > 0 and dst_iata):
                continue
            d_lookup = (m.get("lookups") or {}).get("destination_airport") if isinstance(m.get("lookups"), dict) else None
            d_lat = (d_lookup or {}).get("lat") if isinstance(d_lookup, dict) else None
            d_lon = (d_lookup or {}).get("lon") if isinstance(d_lookup, dict) else None
            if not (isinstance(d_lat, (int,float)) and isinstance(d_lon, (int,float))):
                if cats_for_eta is None:
                    cats_for_eta = _load_catalogs(args.datasets)
                ap = cats_for_eta.get("airports", {}).get(dst_iata)
                d_lat = (ap or {}).get("lat")
                d_lon = (ap or {}).get("lon")
            if not (isinstance(d_lat, (int,float)) and isinstance(d_lon, (int,float))):
                continue
            rem_nm = gc_distance_nm(float(lat), float(lon), float(d_lat), float(d_lon))
            m["remaining_nm"] = round(rem_nm, 3)
            m["eta_min"] = round((rem_nm / float(spd)) * 60.0, 1)
        except Exception:
            pass

    # Build top-level JSON with stats near the top for quick visibility
    out = {
        "timestamp": now_ts,
        "stats": {
            "hex_count": len(merged_internal),
            "providers_present": sorted([k for k,v in providers.items() if v]),
        },
        "point": payload.get("point"),
        "merged": merged_internal,
    }
    # Nearest aircraft summary (if distances computed)
    try:
        nearest = min((m for m in merged_internal if isinstance(m.get("distance_nm"), (int,float))), key=lambda m: m["distance_nm"]) if merged_internal else None
    except ValueError:
        nearest = None
    if nearest:
        base_nearest = {
            k: nearest.get(k) for k in [
                "hex","distance_nm","bearing_deg","latitude","longitude","altitude_ft",
                "ground_speed_kt","track_deg","squawk","on_ground","vertical_rate_fpm",
                "registration","aircraft_type","airline_icao","callsign","flight_no",
                "origin_iata","destination_iata","origin_country","is_military","position_timestamp","position_age_sec"
            ]
        }
        out["nearest"] = base_nearest
        # Also enrich the nearest aircraft within the main merged list (no separate object)
        try:
            catalogs = _load_catalogs(args.datasets)
            enriched = enrich_with_catalogs(nearest, catalogs)
            if "souls_on_board_max" in enriched:
                nearest["souls_on_board_max"] = enriched["souls_on_board_max"]
                # Mirror enriched fields into the top-level nearest summary for ESP32 consumers
                base_nearest["souls_on_board_max"] = enriched["souls_on_board_max"]
                if "souls_on_board_max_is_estimate" in enriched:
                    base_nearest["souls_on_board_max_is_estimate"] = enriched["souls_on_board_max_is_estimate"]
                if "souls_on_board_max_text" in enriched:
                    nearest["souls_on_board_max_text"] = enriched["souls_on_board_max_text"]
                    base_nearest["souls_on_board_max_text"] = enriched["souls_on_board_max_text"]
            if "lookups" in enriched:
                nearest["lookups"] = enriched["lookups"]
                base_nearest["lookups"] = enriched["lookups"]
            try:
                plat = nearest.get("latitude"); plon = nearest.get("longitude")
                spd = nearest.get("ground_speed_kt")
                dst = (enriched.get("lookups") or {}).get("destination_airport") if isinstance(enriched.get("lookups"), dict) else None
                dlat = (dst or {}).get("lat") if isinstance(dst, dict) else None
                dlon = (dst or {}).get("lon") if isinstance(dst, dict) else None
                if not (isinstance(dlat, (int,float)) and isinstance(dlon, (int,float))):
                    diata = _clean_str(nearest.get("destination_iata"))
                    if diata:
                        ap = catalogs.get("airports", {}).get(diata)
                        dlat = (ap or {}).get("lat"); dlon = (ap or {}).get("lon")
                if isinstance(plat, (int,float)) and isinstance(plon, (int,float)) and isinstance(spd, (int,float)) and spd > 0 and isinstance(dlat, (int,float)) and isinstance(dlon, (int,float)):
                    rem_nm = gc_distance_nm(float(plat), float(plon), float(dlat), float(dlon))
                    nearest["remaining_nm"] = round(rem_nm, 3)
                    base_nearest["remaining_nm"] = round(rem_nm, 3)
                    nearest["eta_min"] = round((rem_nm / float(spd)) * 60.0, 1)
                    base_nearest["eta_min"] = round((rem_nm / float(spd)) * 60.0, 1)
            except Exception:
                pass
        except Exception:
            pass
    if args.by_hex:
        out["by_hex"] = by_hex_map

    text = json.dumps(out, ensure_ascii=False, indent=None if args.minify else 2)

    if args.json_out:
        _ensure_parent_dir(args.json_out)
        with open(args.json_out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Wrote merged JSON: {args.json_out}", file=sys.stderr)
    if args.json_stdout or not args.json_out:
        print(text)

    if args.xlsx:
        _ensure_parent_dir(args.xlsx)
        write_excel(args.xlsx, payload, merged_internal, include_raw=args.xlsx_raw)
        print(f"Wrote Excel workbook: {args.xlsx}", file=sys.stderr)

if __name__ == "__main__":
    main()
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
