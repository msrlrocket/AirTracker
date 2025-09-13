# AirTracker

Compare and merge live aircraft data around a point by querying multiple providers, then export, analyze, and share results.

This repo contains two scripts that work together:

- plane_retreiver.py: Fetches aircraft near a latitude/longitude from OpenSky, ADSB.lol, and the (unofficial) Flightradar24 feed.js endpoint. It prints tables, can tag military aircraft via ADSB.lol, and can export JSON or Excel.
- plane_merge.py: Takes the JSON output from plane_retreiver.py and merges rows per ICAO hex into a single, human-friendly record, choosing the freshest provider per field. It can output merged JSON and Excel.

Both scripts aim to be transparent and debuggable: URLs are echoed, optional headers can be tweaked, and data can be dumped for inspection.

Note: Access to FR24’s internal endpoints can be rate-limited or blocked (e.g., Cloudflare). Consider their official API for production use and rely on OpenSky/ADSB.lol when blocked.

## Recommended Architecture: One Producer, Many Consumers

Goal: fetch + merge once, share to multiple consumers (ESP32 display and Home Assistant) without duplicating work.

High-level flow

1) Producer (runs on HA or a nearby host)

- Runs `plane_retreiver.py` for a point and radius, then pipes into `plane_merge.py`.
- Publishes compact MQTT topics for consumers, e.g.:
  - `airtracker/nearest` (retained): a tiny JSON with only the closest plane.
  - `airtracker/planes` (optional snapshot): the full merged list for map/logging.

2) Consumers

- ESP32: subscribes to `airtracker/nearest` for instant, tiny updates to the LCD/touch UI. Optionally subscribes to `airtracker/planes` to render a map or detail view.
- Home Assistant: subscribes to both. Use sensors from `nearest` for quick state and the snapshot for map/log/history.

Why this design

- One source of truth: no skew between what HA and the ESP32 see.
- Efficient: ESP32 processes only a very small payload; HA can handle larger snapshots.
- Robust: MQTT retained messages give devices the latest state after reconnect without polling.

Suggested cadence

- Publish `nearest` every 1–2 seconds (tiny payload).
- Publish `planes` every 5–15 seconds (or when it changes).
- Use `--minify` to reduce bandwidth and parsing overhead.

Example producer command (stdout → MQTT)

```bash
# Retrieve + merge (stdout), publish nearest (retained)
python3 plane_retreiver.py <lat> <lon> -r <nm> --json-stdout --quiet \
  | python3 plane_merge.py --json-stdout --minify \
  | tee /tmp/planes_merged.json \
  | jq -cr '.nearest' \
  | mosquitto_pub -t airtracker/nearest -r -s

# Optionally publish the full merged list (retained)
cat /tmp/planes_merged.json \
  | jq -cr '.merged' \
  | mosquitto_pub -t airtracker/planes -r -s
```

Notes

- If you prefer HTTP/file instead of MQTT, write `--json-out planes_merged.json` and have consumers read it. MQTT is recommended for push updates and low-latency ESP32 updates.
- `--by-hex` adds a `by_hex` object for O(1) lookups by hex (handy in HA templates). It duplicates the list data, so keep it off for the ESP32 to save memory.

Payloads for consumers

- Top-level `nearest` (added by `plane_merge.py`):

  ```json
  {
    "hex": "A27A94",
    "distance_nm": 12.345,
    "bearing_deg": 278.4,
    "latitude": 46.46,
    "longitude": -122.72,
    "altitude_ft": 19650,
    "vertical_rate_fpm": -768,
    "ground_speed_kt": 371,
    "track_deg": 358.6,
    "squawk": "3641",
    "on_ground": false,
    "registration": "N259SY",
    "aircraft_type": "E75L",
    "airline_icao": "DAL",
    "callsign": "SKW3991",
    "flight_no": "DL3991",
    "origin_iata": "SFO",
    "destination_iata": "SEA",
    "origin_country": "United States",
    "is_military": false,
    "position_timestamp": 1757743600,
    "position_age_sec": 0.1
  }
  ```

- Full snapshot (`merged` array) contains one object per hex with the fields below (see “Enriched fields” in the merge section).

Home Assistant patterns

- MQTT sensors from `airtracker/nearest` (distance, bearing, callsign, altitude, etc.) and a Lovelace map using the `merged` snapshot.
- If you frequently look up a known hex in templates, consider running the merge with `--by-hex` so you can directly index `value_json.by_hex[hex]` rather than looping.

ESP32 patterns

- Subscribe only to `airtracker/nearest` for the LCD/touch UI. This keeps payloads tiny and parsing simple.
- Optionally subscribe to `airtracker/planes` to show a tappable list/map (parse latitude/longitude/track/registration/callsign and `distance_nm`/`bearing_deg`).

Tuning outputs

- Use `--minify` to reduce JSON size.
- Keep `--by-hex` off for small devices to avoid duplicate data.
- If you ever need a dedicated small feed, add a “nearest-only” publish step (as in the example above) to keep the ESP32 work minimal.

## Quick Start

Python 3.9+ recommended.

Install dependencies:

- Required: `pip install requests`
- Optional Excel export: `pip install pandas openpyxl`

Environment variables and .env

- Copy `.env.example` to `.env` (ignored by Git) and fill in your credentials and options. The scripts auto-load `.env` if present.
- Example keys (see `.env.example`):
  - `OSK_CLIENT_ID`, `OSK_CLIENT_SECRET` — OpenSky OAuth2 client credentials
  - `FR24_COOKIE` — optional raw cookie header value if needed
  - `FR24_UA` — optional custom User-Agent for FR24 requests
  - `FR24_ESP` — set to `1`/`true` to mimic an ESP32 HTTP client

Home Assistant tips

- The scripts auto-read `.env` at runtime, so you can ship the `.env` alongside the scripts or set env vars via HA.
- In HA command_line/shell_command integrations, prefer passing variables through HA’s `secrets.yaml` or environment.
- You can also override via CLI flags: e.g., `--fr24-cookie "$FR24_COOKIE"`.

Run a retrieval around a point (default wide tables):

```
python3 plane_retreiver.py 46.168689 -123.020309 -r 50
```

Compact tables (legacy view):

```
python3 plane_retreiver.py 46.168689 -123.020309 -r 50 --narrow
```

Export to Excel (one sheet per provider + Notes):

```
python3 plane_retreiver.py 46.168689 -123.020309 -r 50 --xlsx flights.xlsx
```

MIL tagging options:

```
# Per-hex lookups (default), 3h TTL, custom cache, then print cache summary
python3 plane_retreiver.py 46.168689 -123.020309 -r 50 --mil-ttl 10800 --mil-cache my_mil_cache.json --print-mil-cache

# Use the global MIL list once per TTL; also export a 'MIL' sheet to Excel
python3 plane_retreiver.py 46.168689 -123.020309 -r 50 --mil-mode list --xlsx flights.xlsx

# Purge the per-hex cache before running
python3 plane_retreiver.py 46.168689 -123.020309 -r 50 --purge-mil-cache
```

JSON handoff (clean stdout) to merge per-hex:

```
python3 plane_retreiver.py 46.168689 -123.020309 -r 50 --json-stdout --quiet \
  | python3 plane_merge.py --json-stdout
```

Dump raw provider payloads for debugging:

```
python3 plane_retreiver.py 46.168689 -123.020309 -r 50 --dump --debug
```

## OpenSky Credentials

OpenSky supports OAuth2 client credentials for higher limits. You can provide credentials either via CLI or environment variables:

- CLI: `--osk-client-id` and `--osk-client-secret`
- Env: `OSK_CLIENT_ID` and `OSK_CLIENT_SECRET`

If only `--osk-client-id` is given, the script prompts for the secret.

## FR24 Notes (Unofficial Endpoint)

- Endpoint: `https://data-cloud.flightradar24.com/zones/fcgi/feed.js`
- The service may respond with HTML or filtered metadata if blocked or rate-limited. In such cases, Excel/JSON dumps (`--dump`) can help diagnose.
- You can adjust headers or pass a browser cookie if necessary:
  - `--fr24-ua` custom User-Agent
  - `--fr24-esp` mimic an ESP32 HTTP client
  - `--fr24-cookie` raw `Cookie` header copied from your browser

## plane_retreiver.py

Fetch and compare provider data near a point; optionally export JSON/Excel and tag MIL.

Key features

- URL echo for each provider (helpful for debugging)
- Wide tables (default) or `--narrow` for a compact per-provider view
- Excel export (`--xlsx file.xlsx`) with one sheet per provider and a Notes sheet
- JSON export (no merging):
  - `--json-out path.json` → write one combined JSON payload to disk
  - `--json-stdout` → print combined JSON to stdout (clean for piping)
  - `--json-shm /dev/shm/file` → also write JSON to a tmpfs path
  - `--json-minify` → compact JSON (default is pretty)
  - `--quiet` → redirect console logs/tables to stderr so stdout stays clean
- MIL tagging via ADSB.lol:
  - `--mil-mode perhex` (default): query `/v2/hex/{HEX}` once per new hex (cached with TTL)
  - `--mil-mode list`: fetch `/v2/mil` global list once per TTL and tag via membership
  - `--mil-mode off`: no network lookups; rely on your own heuristics
  - `--mil-ttl N`: cache TTL seconds (default 21600 = 6h)
  - `--mil-cache path`: per-hex cache file (default `mil_cache.json`)
  - `--mil-list-cache path`: global list cache file (default `mil_list_cache.json`)
  - `--print-mil-cache`: print per-hex cache summary/sample
  - `--purge-mil-cache`: delete per-hex cache file before running

CLI highlights

- Display mode: Wide tables by default; use `--narrow` for compact view
- Skip any provider with `--skip-opensky`, `--skip-adsb`, or `--skip-fr24`
- Write raw responses with `--dump` and verbose HTTP logs with `--debug`
- FR24 header toggles: `--fr24-esp`, `--fr24-ua`, `--fr24-cookie`

Excel Notes reference

The following summarizes field meanings that appear in the Excel export.

- OpenSky (sheet: “OpenSky”)

  These come from OpenSky’s `/states/all` state-vector array; extra fields are conveniences.

  - icao24 — 24-bit ICAO hex address (e.g., a6177c)
  - callsign — ATC callsign/flight ID as broadcast (often padded with spaces)
  - origin_country — Country inferred from the ICAO allocation
  - time_position — Unix time (s) of last position report
  - last_contact — Unix time (s) of last message seen (any)
  - longitude/latitude — Last known position
  - baro_altitude — Barometric altitude (m), may be null
  - on_ground — True if aircraft reports on-ground
  - velocity — Ground speed (m/s) computed by OpenSky
  - true_track — Track over ground (deg 0–360)
  - vertical_rate — Vertical speed (m/s; positive up)
  - sensors — Sensor IDs (often null)
  - geo_altitude — Geometric/GNSS altitude (m)
  - squawk — 4-octal transponder code (string)
  - spi — IDENT flag (boolean)
  - position_source — Source enum (0=ADS-B, 1=ASTERIX/MLAT, 2=FLARM)
  - category — ADS-B emitter category code (integer)

  Convenience columns added:
  - baro_ft — baro_altitude converted to feet
  - geo_ft — geo_altitude converted to feet
  - gs_kt — velocity converted to knots
  - vs_fpm — vertical_rate converted to feet/min

- ADSB.lol (sheet: “ADSB.lol”)

  Keys vary by feeder; common ones include:

  - hex — ICAO address (24-bit)
  - flight — Callsign/flight ID (trim as needed)
  - r — Registration/tail (e.g., N4QP)
  - t — Aircraft type/model code (e.g., E75L, A320)
  - lat/lon — Position
  - alt_baro — Baro altitude in feet (or "ground" on stand)
  - alt_geom — Geometric altitude in feet (GNSS-based)
  - gs — Ground speed in knots
  - track — Track over ground in degrees
  - true_heading — True heading in degrees (if available)
  - baro_rate / geom_rate — Vertical rate ft/min (from baro or geometric source)
  - squawk — Transponder code
  - category — ADS-B emitter category (letter/number grouping like A3)
  - emergency — Emergency status when set
  - nav_* — Selected alt/heading/modes (when broadcast)
  - mlat / tisb — MLAT/TIS-B indicators
  - seen / seen_pos — Age counters in seconds
  - rssi/messages — Receiver strength and message count
  - nac_*, sil, gva, sda — Quality metrics

- Flightradar24 feed.js (sheet: “FR24”)

  The feed is a JSON map keyed by an internal ID; values are arrays. Useful indices:

  - hex (0)
  - lat/lon (1, 2)
  - trk (3)
  - alt_ft (4)
  - gs_kt (5)
  - squawk (6)
  - radar (7) — internal source tag (e.g., F-, T-, MLAT)
  - type (8)
  - reg (9)
  - timestamp (10)
  - from_iata / to_iata (11, 12)
  - flight (13) — commercial number (IATA-style)
  - on_ground (14)
  - vs_fpm (15)
  - callsign (16)
  - airline_icao (18)

Cross-provider cautions

- Baro vs Geo Altitude: OpenSky baro_altitude/geo_altitude (m); ADSB.lol alt_baro/alt_geom (ft); FR24 publishes one altitude (alt_ft)
- Ground Speed: OpenSky velocity (m/s → gs_kt); ADSB.lol gs (knots); FR24 gs_kt (knots)
- Track vs Heading: Track is movement over ground; heading is the nose direction. ADSB.lol may report both.
- Flight vs Callsign: FR24 splits (flight = commercial number; callsign = ATC). Others expose transponder callsign.
- Timestamps: OpenSky time_position/last_contact; FR24 per-target timestamp; ADSB.lol seen/seen_pos (ages).
- Data source tags: FR24 radar vs ADSB.lol mlat/tisb vs OpenSky position_source

JSON schema (retriever output)

- `timestamp` — Unix time seconds
- `point` — `{lat, lon, radius_nm}` of query
- `mil` — `{mode, ttl}` summarizing MIL options
- `providers` — object with `opensky`, `adsb_lol`, and `fr24` arrays (provider-native fields)
- `all` — flattened list with a `provider` tag for each row

## plane_merge.py

Merge rows per hex into single records, choosing the freshest provider per field and exporting merged data.

Freshness and tie-breaks

- Age (lower is fresher):
  - OpenSky: `now - (last_contact or time_position)`
  - ADSB.lol: `seen`
  - FR24: `now - timestamp`
- Tie-break provider priority: `adsb_lol > fr24 > opensky` (configurable via `--prefer`)

Merge rules (summary)

- Live telemetry (latitude, longitude, altitude_ft, vertical_rate_fpm, ground_speed_kt, track_deg, squawk, on_ground) comes from the freshest provider; ties use the priority above.
- `vertical_rate_fpm` is feet per minute (negative = descent)
- Identity precedence:
  - registration: `FR24.reg > ADSB.lol.r`
  - aircraft_type: `ADSB.lol.t > FR24.type > OpenSky.type`
  - airline_icao: FR24 only (when present)
  - callsign: `ADSB.lol.flight/callsign > FR24.callsign > OpenSky.callsign`
  - flight_no: `FR24.flight` if it looks like a commercial number (IATA/ICAO); else use `ADSB.lol.flight`
- `is_military`: True if any provider True; False if any provider False and none True; else None
- `extras_*` fields retain provider-specific keys that aren’t telemetry duplicates
- `age_*_sec` columns show how old each provider’s latest report is (lower = fresher)

Enriched fields

- `field_sources` — map of which provider supplied each telemetry field (e.g., `{ "latitude": "adsb_lol", "squawk": "fr24" }`).
- `position_timestamp` — unix time derived from the provider that supplied the chosen position.
- `position_age_sec` — freshness of that position at merge time.
- `distance_nm` — great-circle distance from the query point to the plane.
- `bearing_deg` — initial bearing from the query point to the plane (0–360).
- `within_radius` — boolean, true if within the input `radius_nm`.
- Top-level `nearest` — convenience object summarizing the closest plane (for low-latency UIs and HA sensors).

Merged JSON schema (output)

- `timestamp` — unix time (from input payload)
- `point` — original query point
- `merged` — list of unified rows per hex
- `stats` — counts and present providers
- Optional `by_hex` mapping when `--by-hex` is used
- Optional `nearest` object summarizing the closest aircraft

Excel export (merged)

- Sheet “Merged”: unified records per hex
- Sheet “Stats”: summary stats from the input payload
- Sheet “Notes”: this merge rules summary
- Optional raw sheets: provider-native rows when `--xlsx-raw` is given

## Troubleshooting

- FR24 HTML response or only meta keys: you’re likely being filtered. Use `--dump` to inspect responses; consider FR24’s official API, or rely on OpenSky/ADSB.lol.
- Excel export requires pandas and openpyxl; install with `pip install pandas openpyxl`.
- For clean JSON piping, use `--quiet` to send tables/logs to stderr.

## License

This code queries third-party services under their respective terms. Use responsibly and respect rate limits.

To Run:
python plane_retreiver.py 46.168689192763544, -123.02030882679537 -r 25 --json-out ./planes_combo.json
python plane_merge.py planes_combo.json --json-out ./planes_merged.json
