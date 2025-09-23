# AirTracker Unified Pipeline

This directory contains the consolidated aircraft tracking pipeline that combines ALL functionality in completely self-contained scripts.

## Complete Self-Contained Operation

**`airtracker_complete.py`** - Complete aircraft tracking pipeline with ALL functionality built-in:
- ✅ Aircraft data fetching from OpenSky, ADSB.lol, FlightRadar24
- ✅ Data merging and enrichment
- ✅ Military aircraft detection via ADSB.lol
- ✅ MQTT publishing
- ✅ No external script dependencies

### Usage Examples

```bash
# Single run (default - exits after one cycle)
python3 airtracker_complete.py

# Continuous operation (runs forever with internal scheduling)
python3 airtracker_complete.py --continuous

# Test MQTT connection
python3 airtracker_complete.py --test-mqtt

# Custom location and settings
python3 airtracker_complete.py --lat 40.7 --lon -74.0 --radius 15 --debug

# Save processed data to file
python3 airtracker_complete.py --output-file data/planes_complete.json
```

### For Unraid Cron Setup

Since the script now runs once and exits (perfect for cron), you should add randomized timing to your Unraid UserScript to avoid hammering APIs at exact intervals.

Replace your existing Unraid UserScript with:

```bash
#!/bin/bash

# AirTracker MQTT Publisher - Unraid UserScript
# Fetches aircraft data and publishes to MQTT with randomized timing

# Set the path to your AirTracker installation
AIRTRACKER_PATH="/mnt/user/appdata/airtracker"

# Add random delay (0-60 seconds) to avoid hitting APIs at exact intervals
DELAY=$(shuf -i 0-60 -n 1)
echo "Waiting ${DELAY} seconds before running AirTracker..."
sleep $DELAY

# Change to the unified directory and run once
cd "$AIRTRACKER_PATH/mqtt/unified" || {
    echo "Error: Could not access $AIRTRACKER_PATH/mqtt/unified"
    exit 1
}

# Run AirTracker once (script exits after single cycle by default)
python3 airtracker_complete.py
```

**Recommended Unraid Cron Schedule:**

Set your Unraid UserScript to run every 2-3 minutes for good data freshness:

- **Cron expression**: `*/2 * * * *` (every 2 minutes)
- **Or**: `*/3 * * * *` (every 3 minutes for lighter API usage)

**Key Benefits:**
- Script exits after one cycle (perfect for cron)
- Random delay prevents API rate limiting
- Cron handles the scheduling, no internal loops
- Logs show provider statistics and aircraft counts
- Beautiful summary output in Unraid logs

### What it does

1. **Fetches** aircraft data from OpenSky, ADSB.lol, and FlightRadar24
2. **Merges** data from multiple providers into unified aircraft records
3. **Enriches** with airline, aircraft type, and airport information
4. **Detects** military aircraft using ADSB.lol military database
5. **Publishes** to MQTT topics:
   - `airtracker/nearest` - Closest aircraft (retained)
   - `airtracker/planes` - All aircraft in area (retained)
   - `airtracker/stats` - Pipeline statistics

### Data Output Files

The script creates files in the `data/` subfolder:
- `planes_complete.json` - Processed aircraft data with enrichment
- `mil_cache.json` - Military aircraft detection cache (TTL-based)

### Configuration

Create a `.env` file in the `mqtt/unified/` directory with your settings:

```bash
# Location settings
LAT=46.168689
LON=-123.020309
RADIUS_NM=40

# MQTT settings
MQTT_HOST=192.168.2.244
MQTT_PORT=1883
MQTT_PREFIX=airtracker

# Data processing
WRITE_JSON_PATH=data/planes_complete.json

# Provider toggles (1 to disable, 0 to enable)
SKIP_OPENSKY=0
SKIP_ADSB=0
SKIP_FR24=0

# OpenSky credentials (optional for higher rate limits)
# OSK_CLIENT_ID=your_client_id
# OSK_CLIENT_SECRET=your_client_secret
```

The script automatically loads the `.env` file on startup.

### Dependencies

- ✅ No external script dependencies - all functionality built-in
- ✅ All original datasets and functionality preserved
- ✅ Python dependencies: `paho-mqtt`, `requests`

### Migration from Old Workflow

**Before:**
```bash
bash mqtt/producer/publish_mqtt.sh  # Complex orchestration script
```

**After:**
```bash
python3 mqtt/unified/airtracker_complete.py  # Single self-contained script
```

**Key Improvements:**
- ✅ One script with ALL functionality built-in
- ✅ No subprocess calls or external dependencies
- ✅ Beautiful log output with provider statistics
- ✅ Perfect for cron scheduling (runs once and exits)
- ✅ Automatic .env file loading

The old producer scripts remain untouched as backup in `mqtt/producer/`.