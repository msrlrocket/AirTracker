# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture Overview

AirTracker is a multi-component aircraft tracking system with three main parts:

1. **Unified MQTT Producer** (`mqtt/unified/`) - Single Python script that fetches aircraft data from multiple providers (OpenSky, ADSB.lol, FlightRadar24), merges the data, enriches with datasets, and publishes to MQTT
2. **ESP32 Display** (`display/esp32-airtracker/`) - Arduino-based firmware for ESP32 devices with LCD displays
3. **LVGL Simulator** (`display/sim-lvgl/`) - C/CMake desktop simulator for testing the display UI

### Data Flow Architecture

The recommended architecture is "One Producer, Many Consumers":
- **Producer**: Runs `airtracker_complete.py` → publishes to MQTT topics
- **Consumers**: ESP32 display and Home Assistant subscribe to MQTT for real-time updates
- **Topics**: `airtracker/nearest` (retained, tiny JSON) and `airtracker/planes` (retained, full list)

## Common Development Commands

### Unified AirTracker Producer

```bash
# Install Python dependencies
pip install requests pandas openpyxl

# Single run (test) with debug output
cd mqtt/unified
python3 airtracker_complete.py --debug

# Continuous operation
python3 airtracker_complete.py --continuous

# Custom location and MQTT publishing
python3 airtracker_complete.py --lat 46.168689 --lon -123.020309 --radius 25 --mqtt-publish-all --mqtt-publish-commercial

# Test MQTT connection
python3 airtracker_complete.py --test-mqtt

# Output to file only (no MQTT)
WRITE_JSON_PATH=data/planes_complete.json python3 airtracker_complete.py
```

### ESP32 Development

```bash
# Build and upload ESP32 firmware
cd display/esp32-airtracker
pio run -t upload

# Monitor serial output
pio device monitor

# Build only (no upload)
pio run
```

### LVGL Simulator

```bash
# Build simulator (requires SDL2, CMake)
cd display/sim-lvgl
mkdir build && cd build
cmake ..
make

# Run simulator
./airtracker_sim
```

## Environment Configuration

- Copy `.env.example` to `.env` and configure:
  - `LAT`, `LON`, `RADIUS_NM` - Query location and radius
  - `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASS` - MQTT broker settings
  - `OSK_CLIENT_ID`, `OSK_CLIENT_SECRET` - OpenSky API credentials (optional)
  - Provider toggles: `SKIP_OPENSKY`, `SKIP_ADSB`, `SKIP_FR24`

## Key File Locations

- **Main script**: `mqtt/unified/airtracker_complete.py` (unified producer)
- **Configuration**: `mqtt/unified/.env` (environment settings)
- **ESP32 source**: `display/esp32-airtracker/src/main.cpp`
- **Simulator source**: `display/sim-lvgl/src/main.c`
- **Datasets**: `mqtt/unified/datasets/` (aircraft types, airports, airlines, countries)
- **Data output**: `mqtt/unified/data/` directory (JSON files, caches)

## Data Processing Pipeline

1. **Retrieval**: Query multiple aviation data providers for aircraft near a point
2. **Merge**: Combine per-provider data into unified records per aircraft (ICAO hex)
3. **Enrichment**: Add aircraft type, airline, airport details from local datasets
4. **Publishing**: Send via MQTT as compact `nearest` object and full `planes` array
5. **Consumption**: ESP32 displays nearest aircraft, Home Assistant tracks all aircraft

## Testing and Development

- Use `--dump-raw --debug` flags for debugging provider responses
- Monitor MQTT topics: `mosquitto_sub -h $MQTT_HOST -t "airtracker/+"`
- Test military detection: set `MILITARY_CACHE_DEBUG=1` in `.env`
- ESP32 config must exist: copy `config.example.h` to `config.h` before building
- Run with environment: `WRITE_JSON_PATH=data/planes_complete.json python3 airtracker_complete.py --debug`