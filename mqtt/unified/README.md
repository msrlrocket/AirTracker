# AirTracker - Unified Edition

Compare and merge live aircraft data around a point by querying multiple providers, then export, analyze, and share results via MQTT.

This repository contains a **unified Python script** that replaces the previous two-script approach, providing a complete aircraft tracking solution in a single command.

## Quick Start

**Installation:**
```bash
cd mqtt/unified
pip install requests pandas openpyxl paho-mqtt python-dotenv
```

**Basic Usage:**
```bash
# Copy and configure environment
cp .env.example .env
# Edit .env with your location, MQTT broker, and API credentials

# Single run (test)
python3 airtracker_complete.py

# Continuous operation
python3 airtracker_complete.py --continuous

# Custom location with MQTT publishing
python3 airtracker_complete.py --lat 46.168689 --lon -123.020309 --radius 25 --mqtt-publish-all --mqtt-publish-commercial

# Debug mode
python3 airtracker_complete.py --debug --dump-raw
```

## Architecture: One Producer, Many Consumers

**Unified Producer:**
- Single `airtracker_complete.py` script handles everything:
  - Fetches from OpenSky, ADSB.lol, FlightRadar24
  - Merges data by ICAO hex code
  - Enriches with aircraft types, airlines, airports
  - Detects military aircraft via ADSB.lol `/v2/mil` API
  - Publishes to MQTT topics

**MQTT Topics:**
- `airtracker/nearest` - Closest aircraft (retained)
- `airtracker/planes` - Full aircraft list (retained, optional)
- `airtracker/nearest_commercial` - Closest commercial aircraft (retained, optional)
- `airtracker/stats` - Runtime statistics

**Consumers:**
- ESP32 displays subscribe to `airtracker/nearest`
- Home Assistant subscribes to all topics for sensors and maps

## Environment Configuration

### .env File Locations (Auto-loaded)

The script automatically loads environment variables from these files (in order):
1. **`mqtt/unified/.env`** (local to script)
2. **Root project `.env`** (if exists)
3. **System environment variables**

For **Unraid** and **Docker** setups, you can place your `.env` file anywhere and set:
```bash
# Point to custom .env location
export WRITE_JSON_PATH=/mnt/user/appdata/airtracker/data/planes_complete.json
export MQTT_HOST=192.168.1.100
# ... other vars
```

### .env Configuration Options

```bash
# Location
LAT=46.168689
LON=-123.020309
RADIUS_NM=25

# MQTT broker
MQTT_HOST=192.168.2.244
MQTT_PORT=1883
MQTT_PREFIX=airtracker
# MQTT_USER=username
# MQTT_PASS=password

# Features
MQTT_DISCOVERY_ON_START=1          # Publish HA discovery on startup
MQTT_PUBLISH_ALL_PLANES=1          # Publish full aircraft list
MQTT_PUBLISH_NEAREST_COMMERCIAL=1  # Publish closest commercial aircraft

# Provider toggles
SKIP_OPENSKY=0
SKIP_ADSB=0
SKIP_FR24=0

# API credentials (optional)
# OSK_CLIENT_ID=your_opensky_client_id
# OSK_CLIENT_SECRET=your_opensky_secret

# Debug
DUMP_RAW=0                         # Dump raw provider responses
MILITARY_CACHE_DEBUG=0             # Write military aircraft debug file

# Timing
FETCH_INTERVAL_MIN_SEC=80
FETCH_INTERVAL_MAX_SEC=100
```

## Command Line Options

```bash
# Operation modes
python3 airtracker_complete.py                    # Single run
python3 airtracker_complete.py --continuous       # Continuous loop
python3 airtracker_complete.py --test-mqtt        # Test MQTT connection

# Location override
python3 airtracker_complete.py --lat 40.7 --lon -74.0 --radius 15

# Configuration file
python3 airtracker_complete.py --env-file /path/to/custom.env

# MQTT publishing
python3 airtracker_complete.py --mqtt-publish-all --mqtt-publish-commercial

# Output options
python3 airtracker_complete.py --output-file data/custom_output.json

# Debug and development
python3 airtracker_complete.py --debug --dump-raw
```

## Automation & Cron

### Option 1: Direct Cron (Recommended)

Add to crontab (`crontab -e`):
```bash
# Run every 2 minutes
*/2 * * * * cd /path/to/AirTracker/mqtt/unified && /usr/bin/python3 airtracker_complete.py --mqtt-publish-all --mqtt-publish-commercial

# Run every minute (high frequency)
* * * * * cd /path/to/AirTracker/mqtt/unified && /usr/bin/python3 airtracker_complete.py --mqtt-publish-all --mqtt-publish-commercial

# With logging
*/2 * * * * cd /path/to/AirTracker/mqtt/unified && /usr/bin/python3 airtracker_complete.py --mqtt-publish-all --mqtt-publish-commercial >> /var/log/airtracker.log 2>&1
```

### Option 2: Continuous Mode with Systemd

Create `/etc/systemd/system/airtracker.service`:
```ini
[Unit]
Description=AirTracker Aircraft Tracking Service
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/path/to/AirTracker/mqtt/unified
Environment=PATH=/usr/local/bin:/usr/bin:/bin
ExecStart=/usr/bin/python3 airtracker_complete.py --continuous --mqtt-publish-all --mqtt-publish-commercial
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable airtracker.service
sudo systemctl start airtracker.service
sudo systemctl status airtracker.service
```

### Option 3: Home Assistant Automation

Add to Home Assistant `configuration.yaml`:
```yaml
shell_command:
  airtracker_update: "cd /path/to/AirTracker/mqtt/unified && python3 airtracker_complete.py --mqtt-publish-all --mqtt-publish-commercial"

automation:
  - alias: "AirTracker Update"
    trigger:
      - platform: time_pattern
        minutes: "/2"  # Every 2 minutes
    action:
      - service: shell_command.airtracker_update
```

### Option 4: Unraid User Scripts

**Method 1: Using Environment Variables**
```bash
#!/bin/bash
# Set custom environment
export MQTT_HOST=192.168.1.100
export LAT=46.168689
export LON=-123.020309
export WRITE_JSON_PATH=/mnt/user/appdata/airtracker/planes_complete.json

# Run AirTracker
cd /mnt/user/appdata/AirTracker/mqtt/unified
python3 airtracker_complete.py --mqtt-publish-all --mqtt-publish-commercial
```

**Method 2: Using Custom .env File (Recommended for Unraid)**
```bash
#!/bin/bash
# Create custom .env file for Unraid paths
ENV_FILE="/mnt/user/appdata/airtracker/config.env"

# Run AirTracker with custom env file
cd /mnt/user/appdata/AirTracker/mqtt/unified
python3 airtracker_complete.py --env-file "$ENV_FILE" --mqtt-publish-all --mqtt-publish-commercial
```

**Sample Unraid .env file (`/mnt/user/appdata/airtracker/config.env`):**
```bash
# Location
LAT=46.168689
LON=-123.020309
RADIUS_NM=25

# MQTT broker (Unraid host IP)
MQTT_HOST=192.168.1.100
MQTT_PORT=1883
MQTT_PREFIX=airtracker

# Data output (Unraid appdata path)
WRITE_JSON_PATH=/mnt/user/appdata/airtracker/data/planes_complete.json

# Features
MQTT_DISCOVERY_ON_START=1
MQTT_PUBLISH_ALL_PLANES=1
MQTT_PUBLISH_NEAREST_COMMERCIAL=1

# Providers
SKIP_OPENSKY=0
SKIP_ADSB=0
SKIP_FR24=0
```

Set to run every 2 minutes in Unraid's User Scripts plugin.

## Home Assistant MQTT Discovery

The script automatically creates Home Assistant sensors when `MQTT_DISCOVERY_ON_START=1`:

### Automatic Sensors Created

**Nearest Aircraft:**
- `sensor.airtracker_nearest_callsign`
- `sensor.airtracker_nearest_distance`
- `sensor.airtracker_nearest_altitude`
- `sensor.airtracker_nearest_aircraft_type`
- `sensor.airtracker_nearest_classification`

**Nearest Commercial:**
- `sensor.airtracker_nearest_commercial_callsign`
- `sensor.airtracker_nearest_commercial_distance`
- `sensor.airtracker_nearest_commercial_route`

**Statistics:**
- `sensor.airtracker_aircraft_count`
- `sensor.airtracker_runs_total`
- `sensor.airtracker_successful_publishes`

### Using in Home Assistant

**Lovelace Card Example:**
```yaml
type: entities
title: Aircraft Tracker
entities:
  - entity: sensor.airtracker_nearest_callsign
    name: "Nearest Aircraft"
  - entity: sensor.airtracker_nearest_distance
    name: "Distance"
  - entity: sensor.airtracker_nearest_altitude
    name: "Altitude"
  - entity: sensor.airtracker_nearest_classification
    name: "Type"
  - entity: sensor.airtracker_aircraft_count
    name: "Total Aircraft"
```

**Automation Example:**
```yaml
automation:
  - alias: "Military Aircraft Alert"
    trigger:
      - platform: state
        entity_id: sensor.airtracker_nearest_classification
        to: "Military"
    action:
      - service: notify.mobile_app
        data:
          message: "Military aircraft {{ states('sensor.airtracker_nearest_callsign') }} detected at {{ states('sensor.airtracker_nearest_distance') }}nm"
```

## Military Aircraft Detection

The unified script includes enhanced military aircraft detection:

- **Automatic**: Uses ADSB.lol `/v2/mil` API to fetch all military aircraft
- **Cached**: 1-hour TTL cache with 146+ military aircraft hex codes
- **Debug**: Set `MILITARY_CACHE_DEBUG=1` to output detailed military aircraft data
- **Logging**: Shows cache status and age in output

## Features

### Data Providers
- **OpenSky Network** (with OAuth2 support)
- **ADSB.lol** (with military detection)
- **FlightRadar24** (unofficial endpoint)

### Data Enrichment
- Aircraft types, manufacturers, seat counts
- Airlines and callsigns
- Airport details (origin/destination)
- Country information
- Military classification
- Distance and bearing calculations

### MQTT Integration
- Retained messages for reliability
- **Home Assistant MQTT Discovery** (automatic sensor creation)
- Configurable topic prefixes
- Multiple data streams (nearest, all planes, commercial)

### Image Processing
- JetPhotos aircraft images
- Zipline image hosting integration
- ESP32-compatible BMP conversion

## Output Data Structure

**Nearest Aircraft (`airtracker/nearest`):**
```json
{
  "hex": "A3D2F5",
  "callsign": "N3455N",
  "aircraft_type": "M20P",
  "classification": "Private",
  "distance_nm": 15.5,
  "bearing_deg": 145.9,
  "altitude_ft": 2125,
  "ground_speed_kt": 124,
  "is_military": false,
  "registration": "N3455N",
  "origin_iata": "FRD"
}
```

**All Planes (`airtracker/planes`):**
```json
[
  {
    "hex": "A3D2F5",
    "sources": ["opensky", "adsb_lol", "fr24"],
    "is_military": false,
    "classification": "Private",
    "distance_nm": 15.5,
    "lookups": {
      "aircraft": {"icao": "M20P", "name": "Mooney M20"},
      "origin_airport": {"iata": "FRD", "name": "Friday Harbor Airport"}
    }
  }
]
```

## You Can Now Replace Your Old Scripts

This unified approach **replaces** the old two-script method:

**OLD (deprecated):**
```bash
python3 plane_retreiver.py ... | python3 plane_merge.py ...
```

**NEW (unified):**
```bash
python3 airtracker_complete.py
```

The unified script handles everything the old scripts did, plus:
- Built-in MQTT publishing
- Enhanced military detection
- Better caching and performance
- Comprehensive logging
- Single configuration file

## Troubleshooting

**MQTT Connection Issues:**
```bash
python3 airtracker_complete.py --test-mqtt
```

**Debug Provider Responses:**
```bash
python3 airtracker_complete.py --debug --dump-raw
```

**Check Military Cache:**
```bash
# Set in .env: MILITARY_CACHE_DEBUG=1
python3 airtracker_complete.py --debug
# Check: data/military_aircraft_debug.json
```

**Monitor MQTT Topics:**
```bash
mosquitto_sub -h your-broker -t "airtracker/+"
```

## License

This code queries third-party services under their respective terms. Use responsibly and respect rate limits.