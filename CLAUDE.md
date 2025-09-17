# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture Overview

AirTracker is a multi-component aircraft tracking system with three main parts:

1. **MQTT Producer** (`mqtt/producer/`) - Python scripts that fetch aircraft data from multiple providers (OpenSky, ADSB.lol, FlightRadar24), merge the data, and publish to MQTT
2. **ESP32 Display** (`display/esp32-airtracker/`) - Arduino-based firmware for ESP32 devices with LCD displays
3. **LVGL Simulator** (`display/sim-lvgl/`) - C/CMake desktop simulator for testing the display UI

### Data Flow Architecture

The recommended architecture is "One Producer, Many Consumers":
- **Producer**: Runs `plane_retreiver.py` → `plane_merge.py` → publishes to MQTT topics
- **Consumers**: ESP32 display and Home Assistant subscribe to MQTT for real-time updates
- **Topics**: `airtracker/nearest` (retained, tiny JSON) and `airtracker/planes` (retained, full list)

## Common Development Commands

### Python/MQTT Producer

```bash
# Install Python dependencies
pip install requests pandas openpyxl

# Run single retrieval (test)
python3 mqtt/producer/plane_retreiver.py 46.168689 -123.020309 -r 50

# Retrieve and merge in one command
python3 mqtt/producer/plane_retreiver.py 46.168689 -123.020309 -r 50 --json-stdout --quiet --merge --merge-minify

# Start MQTT publisher (continuous)
bash mqtt/producer/publish_mqtt.sh

# One-shot MQTT publish (for testing/automation)
RUN_ONCE=1 bash mqtt/producer/publish_mqtt.sh

# Publish Home Assistant discovery configs
bash mqtt/producer/publish_ha_discovery.sh
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

- **Main scripts**: `mqtt/producer/plane_retreiver.py`, `mqtt/producer/plane_merge.py`
- **MQTT publisher**: `mqtt/producer/publish_mqtt.sh`
- **ESP32 source**: `display/esp32-airtracker/src/main.cpp`
- **Simulator source**: `display/sim-lvgl/src/main.c`
- **Datasets**: `mqtt/producer/datasets/` (aircraft types, airports, airlines, countries)
- **Data output**: `./data/` directory (JSON files, caches)

## Data Processing Pipeline

1. **Retrieval**: Query multiple aviation data providers for aircraft near a point
2. **Merge**: Combine per-provider data into unified records per aircraft (ICAO hex)
3. **Enrichment**: Add aircraft type, airline, airport details from local datasets
4. **Publishing**: Send via MQTT as compact `nearest` object and full `planes` array
5. **Consumption**: ESP32 displays nearest aircraft, Home Assistant tracks all aircraft

## Testing and Development

- Use `--dump --debug` flags with retriever for debugging provider responses
- Test merge logic with: `python3 mqtt/producer/plane_merge.py ./data/planes_combo.json --json-stdout`
- Monitor MQTT topics: `mosquitto_sub -h $MQTT_HOST -t "airtracker/+"`
- ESP32 config must exist: copy `config.example.h` to `config.h` before building