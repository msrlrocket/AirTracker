AirTracker Home Assistant Dashboard

Overview
- This folder contains a ready-to-import Lovelace dashboard and an optional MQTT sensor package to visualize the nearest flight from AirTracker.
- It expects the AirTracker MQTT topics (especially `airtracker/nearest`) to be published by the producer scripts in this repo.

Compatibility
- The included dashboard and compact card now tolerate alternate entity_ids that end with `_2` (e.g., `sensor.airtracker_callsign_2`).
- Where possible, the Markdown sections use template fallbacks and key cards are duplicated behind `conditional` blocks so either the original or `_2` entities render.
- If you have only the `_2` entities, the `_2` versions of the cards will show automatically; if you have the originals, those will be used.

Two ways to expose entities to HA

- Recommended (auto): run MQTT Discovery publisher to create all entities, plus an optional device_tracker for map/history.
  - Example: `MQTT_DEVICE_TRACKER=1 bash ./mqtt/producer/publish_ha_discovery.sh`
  - By default it creates entity_ids like `sensor.airtracker_distance_nm` (prefix configurable via `HA_ENTITY_PREFIX`).
- Manual (fallback): include `homeassistant/airtracker_package.yaml` in your HA config to define a small set of MQTT sensors used by the dashboard.

Importing the dashboard

Storage mode (default HA setup)
- Settings → Dashboards → Add Dashboard → Three-dots → Raw configuration editor → paste the contents of `homeassistant/airtracker_dashboard.yaml`.

YAML mode
- If you use YAML mode for Lovelace, include the view from `airtracker_dashboard.yaml` into your `ui-lovelace.yaml` or reference the file as a separate dashboard.

Notes
- To show the aircraft on the Map card, ensure the discovery publisher enabled the `device_tracker.airtracker_nearest_tracker` (set `MQTT_DEVICE_TRACKER=1` before running the discovery script). If you don’t use the device_tracker, remove the Map card from the dashboard.
- If you previously published discovery without the `airtracker_` prefix, re-run with the new defaults and prune stale topics: `HA_ENTITY_PREFIX=airtracker_ MQTT_DEVICE_TRACKER=1 bash mqtt/producer/publish_ha_discovery.sh -p`.
- For image and flight history, run the merge with `--nearest-scrape` so `media` and `history` are included in the `airtracker/nearest` payload.
  - Example: `python3 mqtt/producer/plane_retreiver.py <lat> <lon> -r <nm> --json-stdout --quiet | python3 mqtt/producer/plane_merge.py --json-stdout --minify --nearest-scrape`

Using the optional MQTT sensor package
- Either copy the contents of `airtracker_package.yaml` into your HA `configuration.yaml` under `sensor:` and `binary_sensor:`, or use HA packages:
  - Place the file under your HA config `packages/` dir and add this to `configuration.yaml` if not present:
    - `homeassistant:`
      - `packages: !include_dir_named packages`
  - Restart HA to load the sensors.
