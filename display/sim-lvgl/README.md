LVGL PC Simulator (macOS/Linux/Windows)

Overview
- Runs your UI at 320x240 in an SDL window (mouse = touch).
- Mirrors the structure of your ESPHome screens: Overview, Gallery, Radar.
- Lets you iterate on layout/logic without flashing the ESP32.

Prereqs (macOS)
- Install tools: `brew install cmake ninja sdl2`
- Optional live data:
  - JSON file loader: no extra deps.
  - MQTT → file helper: `pip install paho-mqtt` (and have an MQTT broker reachable).

Build
- Configure: `cmake -S display/sim-lvgl -B display/sim-lvgl/build -G Ninja`
- Build: `cmake --build display/sim-lvgl/build`
- Run: `./display/sim-lvgl/build/airtracker_sim`
  - Optional refresh cadence: `export SIM_UPDATE_MS=5000` (default 5000; 1000–20000 supported)

Notes
- The project uses CMake FetchContent to download LVGL at configure time.
- By default we target LVGL v8 + SDL driver (stable for PC sim).
- The window scales 2x for readability; logical resolution stays 320x240.

Controls
- Mouse/touch: click buttons/zones to navigate.
- From Overview: click plane box → Gallery; click RADAR → Radar.
- Click ← Back (top-left) on Gallery/Radar to return.

Live data options
- Easiest: MQTT → file helper (no simulator rebuild needed)
  1) Export your broker/topic env (matching your ESPHome YAML):
     - `export MQTT_HOST=192.168.1.10; export MQTT_PORT=1883`
     - `export NEAREST_TOPIC=airtracker/nearest` (or your topic)
     - Optional: `export MQTT_USERNAME=...; export MQTT_PASSWORD=...`
  2) Choose output path (defaults to `display/sim-lvgl/data/nearest.json`):
     - `export SIM_JSON_PATH=display/sim-lvgl/data/nearest.json`
  3) Run the helper (separate terminal):
     - `python3 display/sim-lvgl/tools/mqtt_to_file.py`
  4) Run the simulator. It polls and refreshes at `SIM_UPDATE_MS` cadence.

- Alternative: Write JSON snapshots directly
  - Save a payload file at `display/sim-lvgl/data/nearest.json` (or set `SIM_JSON_PATH`)
  - The sim reloads whenever the file’s mtime changes.

Direct MQTT inside the simulator
- Possible using `libmosquitto` + a JSON parser, but adds a compiled dep.
- If you want this, I can wire it so the sim subscribes directly (brew install mosquitto).

Folder Layout
- `CMakeLists.txt` — build config; fetches LVGL and compiles the simulator.
- `lv_conf.h` — LVGL configuration (enables SDL, fonts, log).
- `src/main.c` — entry point, SDL init, LVGL tick/loop.
- `src/ui/ui.h/.c` — UI creation; three screens and navigation.
- `src/model/model.h/.c` — Data model (same fields as ESPHome globals) + mock updates.
- `src/io/json_loader.h/.c` — Optional file-based JSON loader (auto picks up changes).
- `data/` — drop live JSON here (optional for live updates).
- `tools/` — helper scripts (e.g., MQTT → file).

Adapting to Your Project
- Replace text/layout in `src/ui/ui.c` to match your style.
- Live data: either run the helper `tools/mqtt_to_file.py` to write `data/nearest.json`, or ask me to enable direct MQTT (libmosquitto) in the sim.
- When ready, reuse the same LVGL widgets/assets on the ESP32 target.
