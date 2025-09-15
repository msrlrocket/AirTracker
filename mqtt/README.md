AirTracker MQTT Producer

Purpose
- Fetch planes around a point from OpenSky, ADSB.lol, and FR24.
- Merge rows per hex into a compact snapshot.
- Publish retained MQTT topics for consumers:
  - `<prefix>/nearest` — tiny JSON for the closest plane
  - `<prefix>/planes`  — optional full snapshot

Layout
- `producer/plane_retreiver.py` — retrieval + JSON handoff (stdout)
- `producer/plane_merge.py` — merge + enrichment and nearest media
- `producer/planelookerupper.py` — optional media scraper (JetPhotos/FR)
- `producer/publish_mqtt.sh` — loop: fetch + merge + publish
- `producer/publish_ha_discovery.sh` — Home Assistant discovery configs

Quick start
- Copy `.env.example` to `.env` at repo root and fill values (MQTT, FR24, etc.).
- One-shot publish (nearest + planes):
  - `bash mqtt/producer/publish_mqtt.sh` (uses `.env` at repo root)
- Or run the pipeline manually:
  - `python3 mqtt/producer/plane_retreiver.py <lat> <lon> -r <nm> --json-stdout --quiet \
     | python3 mqtt/producer/plane_merge.py --json-stdout --minify \
     | jq -cr '.nearest' \
     | mosquitto_pub -t airtracker/nearest -r -s`

Notes
- Datasets default to `mqtt/producer/datasets`. Override via `--datasets` or `MERGE_DATASETS`.
- The scripts also load `.env` from the repo root automatically.
