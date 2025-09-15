# AirTracker ESP32 (Nearest Aircraft Display)

A minimal ESP32-C3 firmware that subscribes to your AirTracker MQTT `nearest` topic and renders the nearest aircraft on a 320x240 ILI9341 SPI TFT, using the GPIOs and layout from `display/office-airplane-tracker.yaml`.

- Board: `esp32-c3-devkitm-1` (changeable)
- Display: ILI9341 (SPI)
- MQTT: subscribes to `<MQTT_PREFIX>/nearest` (retained JSON payload)

## Pinout (from office-airplane-tracker.yaml)

SPI (TFT):
- `SCLK` → GPIO4
- `MOSI` → GPIO6
- `MISO` → GPIO5
- `CS`   → GPIO7
- `DC`   → GPIO10
- `RST`  → GPIO1

Buttons (active LOW, INPUT_PULLUP):
- `BTN_A` → GPIO2 (go to Screen 2)
- `BTN_B` → GPIO3 (go to Screen 3)
- `BTN_BACK` → GPIO20 (cycle screens)

If you use different pins/board, adjust them in `include/config.h`.

## Configure

Edit `include/config.h`:
- `WIFI_SSID` / `WIFI_PASS` for your network
- `WIFI_TZ` for your timezone or leave `UTC`
- MQTT defaults are pre-filled from your repo `.env`:
  - `MQTT_HOST=192.168.2.244`
  - `MQTT_PORT=1883`
  - `MQTT_USER=mqtt`
  - `MQTT_PASS=…`
  - `MQTT_PREFIX=airtracker` (topic becomes `airtracker/nearest`)

You can override any `#define` at build time with `-D` flags in `platformio.ini` if desired.

Config and version control
- The repo includes `include/config.example.h` with placeholders.
- On build, a missing `include/config.h` is auto-created from the example (see `tools/check_config.py`).
- `include/config.h` is gitignored to keep your Wi‑Fi/MQTT secrets out of Git.

## Build and Upload (PlatformIO)

- Install the PlatformIO extension in VS Code (or use `pio` CLI)
- Open the workspace root, select this environment: `display/esp32-airtracker/platformio.ini`
- Connect your ESP32-C3 board in bootloader mode if needed
- Build: `pio run -d display/esp32-airtracker`
- Upload: `pio run -d display/esp32-airtracker -t upload`
- Serial monitor: `pio device monitor -b 115200`

## Prebuilt Image

- A ready-to-flash single image is in `display/esp32-airtracker/release/factory.bin` with Windows scripts.
- See `display/esp32-airtracker/release/README-Windows.md` for flashing instructions.

## What it shows

Screen 1 (Overview):
- Top: `ORIGIN → DEST` and `remaining km • ETA HH:MM`
- Middle: `Aircraft — Airline`, Callsign
- Bottom-left: `now km – direction • GS km/h`
- Bottom-mid: Souls on board (or max seats proxy)
- Bottom-right: `alt ft  ±vv fpm`

Screen 2 (Gallery):
- Placeholder with registration/type/airline and “last flights” header (ready for expansion)

Screen 3 (Radar):
- Simple scope with range rings and a plotted target using `bearing_deg` and `distance_nm`

All fields are derived from the `nearest` JSON published by `mqtt/producer/publish_mqtt.sh`. The keys match the YAML logic (e.g. `origin_iata`, `destination_iata`, `distance_nm`, `remaining_nm`, `eta_min`, `ground_speed_kt`, `altitude_ft`, `vertical_rate_fpm`, `bearing_deg`, `track_deg`, `lookups.airline.name`, `lookups.aircraft.name`).

## Notes

- The UI is intentionally lightweight (Adafruit_GFX + ILI9341). You can swap to a faster library later if needed.
- Plane photo (right) and airline logo (left) are fetched from URLs in the `nearest` payload when available. They are cached as JPEGs in SPIFFS and rendered into the tiles. If no airline logo is available, the tile shows “Unknown”. HTTPS is allowed with certificate verification disabled for simplicity.
- Timezone is used for ETA display via NTP; set `WIFI_TZ` accordingly or keep `UTC`.
- If no `souls_on_board` is present, the code uses `lookups.aircraft.seats_max` as a proxy when available.
- Topics are retained; the device will render the most recent snapshot shortly after connecting.

## Troubleshooting

- White screen or no text: verify pin wiring and that the display really is ILI9341.
- MQTT connects but no data: check broker creds and confirm `publish_mqtt.sh` is running and publishing to `<prefix>/nearest`.
- Re-map pins: change `include/config.h` and rebuild.
