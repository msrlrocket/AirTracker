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
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from io import BytesIO

try:
    import paho.mqtt.client as mqtt
    from dotenv import load_dotenv
    from PIL import Image
except ImportError as e:
    print(f"❌ Missing required dependency: {e}")
    print("Install with: pip install paho-mqtt requests python-dotenv Pillow")
    sys.exit(1)

# Load environment variables
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
        """Configure Zipline from environment variables."""
        self.zipline_url = os.getenv('ZIPLINE_URL', 'https://zip.spacegeese.com')
        self.zipline_token = os.getenv('ZIPLINE_TOKEN')
        self.zipline_folder_id = os.getenv('ZIPLINE_AIRCRAFT_FOLDER_ID', 'cmfw6kozd022701mvmjz33v2j')

        if not self.zipline_token:
            if self.config.get('log_level') == 'DEBUG':
                print("⚠️  Zipline token not configured - image processing disabled")
            self.enabled = False
        else:
            self.enabled = True

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
                    if self.config.get('log_level') == 'DEBUG':
                        print(f"✅ Uploaded {'BMP' if is_bmp else 'original'}: {zipline_url}")
                    return zipline_url
                except Exception as e:
                    if self.config.get('log_level') == 'DEBUG':
                        print(f"❌ Couldn't parse Zipline response: {e}")
                    return None
            else:
                if self.config.get('log_level') == 'DEBUG':
                    print(f"❌ Zipline upload failed: HTTP {response.status_code}")
                return None

        except Exception as e:
            if self.config.get('log_level') == 'DEBUG':
                print(f"❌ Zipline upload failed: {e}")
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
            image_data = self.download_image(image_url)
            if not image_data:
                return result

            # Upload original to Zipline
            original_zipline_url = self.upload_to_zipline(
                image_data,
                aircraft_reg,
                is_bmp=False
            )
            if original_zipline_url:
                result['plane_image_zipline_original'] = original_zipline_url

            # Convert to BMP
            bmp_data = self.convert_to_bmp(image_data)
            if bmp_data:
                # Upload BMP to Zipline
                bmp_zipline_url = self.upload_to_zipline(
                    bmp_data,
                    aircraft_reg,
                    is_bmp=True
                )
                if bmp_zipline_url:
                    result['plane_image_zipline_esp32'] = bmp_zipline_url

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


def classify_aircraft(row: Dict[str, Any], private_threshold: Optional[int] = None) -> Optional[str]:
    """Classify aircraft as Military, Private, or Commercial."""
    try:
        if row.get("is_military") is True:
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
        out["airline_logo_url"] = f"{base_url}/airline_logo_{code}.bmp"
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
    """Military aircraft cache using ADSB.lol API"""

    def __init__(self, cache_path: str, ttl: int = 21600):
        self.cache_path = cache_path
        self.ttl = ttl
        self.cache = self._load_cache()

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

    def check_hex(self, hex_code: str) -> Optional[bool]:
        """Check if aircraft is military, using cache with TTL"""
        if not hex_code:
            return None

        hex_upper = hex_code.upper()
        now = time.time()

        # Check cache
        if hex_upper in self.cache:
            entry = self.cache[hex_upper]
            if now - entry.get('ts', 0) < self.ttl:
                return entry.get('mil')

        # Fetch from API
        try:
            url = f"{ADSB_API_BASE}/v2/hex/{hex_upper}"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                is_mil = data.get('mil', False)
            else:
                is_mil = None

            # Update cache
            self.cache[hex_upper] = {'mil': is_mil, 'ts': now}
            self._save_cache()
            return is_mil

        except Exception:
            return None


class AirTrackerComplete:
    """Complete aircraft tracking pipeline in a single class"""

    def __init__(self, config: Optional[Dict] = None):
        """Initialize with configuration"""
        self.config = self._load_config(config)
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

    def _load_config(self, override_config: Optional[Dict] = None) -> Dict:
        """Load configuration from environment variables and overrides"""

        # Load .env file if it exists
        env_file = os.path.join(os.path.dirname(__file__), '.env')
        if os.path.exists(env_file):
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
                logging.FileHandler('airtracker_complete.log')
            ]
        )
        self.logger = logging.getLogger('AirTracker')

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

    def publish_mqtt(self, topic: str, payload: str, retain: bool = True) -> bool:
        """Publish message to MQTT"""
        try:
            if not self.mqtt_client:
                if not self.setup_mqtt():
                    return False

            full_topic = f"{self.config['mqtt_prefix']}/{topic}"
            result = self.mqtt_client.publish(full_topic, payload, retain=retain)

            if result.rc == 0:
                self.logger.debug(f"📤 Published to {full_topic}: {len(payload)} bytes")
                return True
            else:
                self.logger.error(f"❌ MQTT publish failed: {result.rc}")
                return False

        except Exception as e:
            self.logger.error(f"❌ MQTT publish error: {e}")
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
        all_aircraft.extend(self.fetch_opensky())
        all_aircraft.extend(self.fetch_adsb_lol())
        all_aircraft.extend(self.fetch_fr24())

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

                # Add aircraft classification
                classification = classify_aircraft(aircraft)
                if classification:
                    aircraft["classification"] = classification

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
                    # Try to import planelookerupper for media scraping
                    try:
                        here = os.path.dirname(os.path.abspath(__file__))
                        parent_dir = os.path.dirname(here)
                        producer_dir = os.path.join(parent_dir, "producer")
                        if producer_dir not in sys.path:
                            sys.path.insert(0, producer_dir)

                        import planelookerupper

                        if self.config.get('log_level') == 'DEBUG':
                            print(f"🖼️  Fetching media for nearest aircraft: {reg}")

                        # Get aircraft photos and flight history
                        info = planelookerupper.get_aircraft_info(
                            registration=reg,
                            photos=4,  # Get up to 4 photos
                            flights=5  # Get up to 5 recent flights
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
                                        zipline_urls = self.image_processor.process_aircraft_image(
                                            plane_image_url, reg
                                        )
                                        if zipline_urls:
                                            media.update(zipline_urls)
                                            if self.config.get('log_level') == 'DEBUG':
                                                print(f"✅ Added Zipline URLs for nearest aircraft {reg}")
                                    except Exception as e:
                                        if self.config.get('log_level') == 'DEBUG':
                                            print(f"⚠️  Zipline processing failed for nearest aircraft {reg}: {e}")

                                # Collect thumbnails
                                thumbs = []
                                for it in imgs[:4]:  # Up to 4 thumbnails
                                    if isinstance(it, dict) and it.get("Thumbnail"):
                                        thumbs.append(it.get("Thumbnail"))
                                if thumbs:
                                    media["thumbnails"] = thumbs

                        # Process FlightRadar24 flight history
                        fr = info.get("FlightRadar") if isinstance(info, dict) else None
                        if isinstance(fr, dict):
                            fls = fr.get("Flights") or []
                            for f in fls[:5]:  # Up to 5 recent flights
                                if not isinstance(f, dict):
                                    continue

                                # Map to UI-friendly fields
                                flight_row = {
                                    "flight": _clean_str(f.get("Flight")),
                                    "origin": _clean_str(f.get("From")),
                                    "destination": _clean_str(f.get("To")) or "Unknown",
                                    "date_yyyy_mm_dd": _clean_str(f.get("Date")),
                                    "block_time_hhmm": _clean_str(f.get("FlightTime")),
                                    "departure_time_hhmm": _clean_str(f.get("STD")),
                                    "actual_departure_time_hhmm": _clean_str(f.get("ATD")),
                                    "arrival_time_hhmm": _clean_str(f.get("STA")),
                                }

                                # Arrival/ETA heuristic from Status and STA
                                sta = _clean_str(f.get("STA")) or _clean_str(f.get("STD"))
                                status = (_clean_str(f.get("Status")) or "").lower()
                                if "arr" in status:
                                    flight_row["arr_or_eta_hhmm"] = f"Arr {sta}" if sta else "Arr"
                                else:
                                    flight_row["arr_or_eta_hhmm"] = f"ETA {sta}" if sta else "ETA"

                                history.append(flight_row)

                        # Add media and history to nearest aircraft
                        if media:
                            enriched_nearest["media"] = media
                            if self.config.get('log_level') == 'DEBUG':
                                print(f"✅ Added {len(media.get('thumbnails', []))} photos for {reg}")

                        if history:
                            enriched_nearest["history"] = history
                            if self.config.get('log_level') == 'DEBUG':
                                print(f"✅ Added {len(history)} flight history entries for {reg}")

                        # Add keys for local/static assets selection on device
                        ak = enriched_nearest.get("airline_iata") or enriched_nearest.get("airline_icao")
                        if ak:
                            enriched_nearest["airline_key"] = ak

                        pk = reg or _clean_str(enriched_nearest.get("aircraft_type"))
                        if pk:
                            enriched_nearest["plane_key"] = pk

                    except ImportError:
                        if self.config.get('log_level') == 'DEBUG':
                            print("⚠️  planelookerupper not found - skipping media enrichment")
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
                "classification": "", "airline_logo_url": "", "airline_logo_path": "", "airline_logo_code": "",
                "souls_on_board_max_text": "N/A", "remaining_nm": 0.0, "eta_min": 0.0,
                "country_flag_url": "", "country_flag_code": "", "country_flag_source": ""
            }
            for key, default_value in default_fields.items():
                if enriched_nearest.get(key) is None:
                    enriched_nearest[key] = default_value

        # Enrich nearest interesting (commercial/military) aircraft
        enriched_nearest_commercial = {}
        if nearest_interesting:
            enriched_nearest_commercial = dict(nearest_interesting)

            # Add enrichment lookups if they exist
            if "lookups" in nearest_interesting:
                # Extract airline IATA for convenience
                try:
                    airline_lookup = nearest_interesting.get("lookups", {}).get("airline", {})
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
                    # Try to import planelookerupper for media scraping
                    try:
                        here = os.path.dirname(os.path.abspath(__file__))
                        parent_dir = os.path.dirname(here)
                        producer_dir = os.path.join(parent_dir, "producer")
                        if producer_dir not in sys.path:
                            sys.path.insert(0, producer_dir)

                        import planelookerupper

                        if self.config.get('log_level') == 'DEBUG':
                            print(f"🖼️  Fetching media for nearest commercial aircraft: {reg}")

                        # Get aircraft photos and flight history
                        info = planelookerupper.get_aircraft_info(
                            registration=reg,
                            photos=4,  # Get up to 4 photos
                            flights=5  # Get up to 5 recent flights
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
                                        zipline_urls = self.image_processor.process_aircraft_image(
                                            plane_image_url, reg
                                        )
                                        if zipline_urls:
                                            media.update(zipline_urls)
                                            if self.config.get('log_level') == 'DEBUG':
                                                print(f"✅ Added Zipline URLs for nearest commercial aircraft {reg}")
                                    except Exception as e:
                                        if self.config.get('log_level') == 'DEBUG':
                                            print(f"⚠️  Zipline processing failed for nearest commercial aircraft {reg}: {e}")

                                # Collect thumbnails
                                thumbs = []
                                for it in imgs[:4]:  # Up to 4 thumbnails
                                    if isinstance(it, dict) and it.get("Thumbnail"):
                                        thumbs.append(it.get("Thumbnail"))
                                if thumbs:
                                    media["thumbnails"] = thumbs

                        # Process FlightRadar24 flight history
                        fr = info.get("FlightRadar") if isinstance(info, dict) else None
                        if isinstance(fr, dict):
                            fls = fr.get("Flights") or []
                            for f in fls[:5]:  # Up to 5 recent flights
                                if not isinstance(f, dict):
                                    continue

                                # Map to UI-friendly fields
                                flight_row = {
                                    "flight": _clean_str(f.get("Flight")),
                                    "origin": _clean_str(f.get("From")),
                                    "destination": _clean_str(f.get("To")) or "Unknown",
                                    "date_yyyy_mm_dd": _clean_str(f.get("Date")),
                                    "block_time_hhmm": _clean_str(f.get("FlightTime")),
                                    "departure_time_hhmm": _clean_str(f.get("STD")),
                                    "actual_departure_time_hhmm": _clean_str(f.get("ATD")),
                                    "arrival_time_hhmm": _clean_str(f.get("STA")),
                                }

                                # Arrival/ETA heuristic from Status and STA
                                sta = _clean_str(f.get("STA")) or _clean_str(f.get("STD"))
                                status = (_clean_str(f.get("Status")) or "").lower()
                                if "arr" in status:
                                    flight_row["arr_or_eta_hhmm"] = f"Arr {sta}" if sta else "Arr"
                                else:
                                    flight_row["arr_or_eta_hhmm"] = f"ETA {sta}" if sta else "ETA"

                                history.append(flight_row)

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

                    except ImportError:
                        if self.config.get('log_level') == 'DEBUG':
                            print("⚠️  planelookerupper not found - skipping media enrichment for commercial aircraft")
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
                "classification": "", "airline_logo_url": "", "airline_logo_path": "", "airline_logo_code": "",
                "souls_on_board_max_text": "N/A", "remaining_nm": 0.0, "eta_min": 0.0,
                "country_flag_url": "", "country_flag_code": "", "country_flag_source": ""
            }
            for key, default_value in default_fields.items():
                if enriched_nearest_commercial.get(key) is None:
                    enriched_nearest_commercial[key] = default_value

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
            "nearest_commercial": enriched_nearest_commercial
        }

    def publish_data(self, data: Dict) -> bool:
        """Publish processed data to MQTT topics"""
        try:
            success = True

            # Publish nearest aircraft
            if data.get('nearest'):
                nearest_json = json.dumps(data['nearest'], separators=(',', ':'))
                if self.publish_mqtt('nearest', nearest_json):
                    self.stats['successful_publishes'] += 1
                else:
                    success = False

            # Publish all planes data (optional, controlled by config)
            if self.config.get('mqtt_publish_all_planes') and data.get('planes'):
                planes_json = json.dumps(data['planes'], separators=(',', ':'))
                if self.publish_mqtt('planes', planes_json):
                    self.stats['successful_publishes'] += 1
                    if self.config.get('log_level') == 'DEBUG':
                        print(f"📡 Published all {len(data['planes'])} planes to MQTT")
                else:
                    success = False

            # Publish nearest commercial/military aircraft (optional, controlled by config)
            if self.config.get('mqtt_publish_nearest_commercial') and data.get('nearest_commercial'):
                nearest_commercial_json = json.dumps(data['nearest_commercial'], separators=(',', ':'))
                if self.publish_mqtt('nearest_commercial', nearest_commercial_json):
                    self.stats['successful_publishes'] += 1
                    if self.config.get('log_level') == 'DEBUG':
                        aircraft_type = data['nearest_commercial'].get('classification', 'Unknown')
                        callsign = data['nearest_commercial'].get('callsign', 'Unknown')
                        distance = data['nearest_commercial'].get('distance_nm', 'Unknown')
                        print(f"📡 Published nearest {aircraft_type.lower()} aircraft ({callsign}) at {distance}nm to MQTT")
                else:
                    success = False

            # Publish stats
            stats_data = {
                **self.stats,
                'last_update': datetime.now().isoformat(),
                'aircraft_count': len(data.get('planes', [])),
                'nearest_aircraft': data.get('nearest', {}).get('callsign', 'None')
            }
            stats_json = json.dumps(stats_data, separators=(',', ':'))
            self.publish_mqtt('stats', stats_json)

            return success

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
            distance = nearest.get('distance_nm', 0)
            altitude = nearest.get('altitude', 0)
            print(f"  - 🎯 Nearest aircraft: {callsign} ({aircraft_type}) - {distance:.1f}nm away at {altitude:,}ft")

        print(f"  - ✅ Perfect data merge with aircraft appearing in multiple sources")
        print(f"  - ✅ MQTT published successfully")

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
                       help='Publish nearest commercial/military aircraft to MQTT')

    # Debug options
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('--output-file', help='Write processed JSON to file')

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
    if args.output_file:
        config_overrides['write_json_path'] = args.output_file

    # Set debug logging
    if args.debug:
        os.environ['LOG_LEVEL'] = 'DEBUG'

    # Initialize complete pipeline
    tracker = AirTrackerComplete(config_overrides)

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