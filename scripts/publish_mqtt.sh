#!/usr/bin/env bash

# AirTracker → MQTT publisher (looping)
#
# Uses existing scripts to fetch + merge, then publishes:
#  - <prefix>/nearest (retained) on every cycle
#  - <prefix>/planes  (retained) every N cycles
#
# Requirements on the host running this script:
#  - python3
#  - jq
#  - mosquitto_pub (from the Mosquitto clients package)
#
# Configure via env vars or inline edits below.

set -u -o pipefail

# Load repository .env if present (exports vars)
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  . "$ROOT_DIR/.env"
  set +a
fi

# ---------- Configuration ----------
: "${LAT:=46.168689}"
: "${LON:=-123.020309}"
: "${RADIUS_NM:=25}"

# MQTT broker settings (point at your HA Mosquitto add-on or another broker)
: "${MQTT_HOST:=127.0.0.1}"
: "${MQTT_PORT:=1883}"
: "${MQTT_USER:=}"
: "${MQTT_PASS:=}"
: "${MQTT_PREFIX:=airtracker}"

# Cadence controls
# How often to fetch from providers (limits network usage)
: "${FETCH_INTERVAL_SEC:=30}"
# How often to publish the cached nearest snapshot to MQTT
: "${NEAREST_INTERVAL_SEC:=2}"
# How often to publish the cached full planes list to MQTT
: "${PLANES_INTERVAL_SEC:=30}"

# Run once and exit (good for HA automations). Set to 1 for one-shot.
: "${RUN_ONCE:=0}"

# Auto-publish HA discovery configs once at start
: "${MQTT_DISCOVERY_ON_START:=1}"

# Merge output options
: "${MERGE_MINIFY:=1}"
: "${MERGE_BY_HEX:=0}"

# Optional: provider toggles (uncomment to skip a provider)
# SKIP_OPENSKY=1
# SKIP_ADSB=1
# SKIP_FR24=1

# ---------- Helpers ----------
need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }; }

need python3
need jq
need mosquitto_pub

mosq_args=( -h "$MQTT_HOST" -p "$MQTT_PORT" )
[[ -n "${MQTT_USER}" ]] && mosq_args+=( -u "$MQTT_USER" )
[[ -n "${MQTT_PASS}" ]] && mosq_args+=( -P "$MQTT_PASS" )

merge_flags=( --json-stdout )
[[ "${MERGE_MINIFY}" == "1" || "${MERGE_MINIFY}" == "true" ]] && merge_flags+=( --minify )
[[ "${MERGE_BY_HEX}" == "1" || "${MERGE_BY_HEX}" == "true" ]] && merge_flags+=( --by-hex )
# Optional merge enrichment and datasets
if [[ "${MERGE_ENRICH_ALL:-}" == "1" || "${MERGE_ENRICH_ALL:-}" == "true" ]]; then
  merge_flags+=( --enrich-all )
elif [[ "${MERGE_ENRICH_IN_RADIUS:-}" == "1" || "${MERGE_ENRICH_IN_RADIUS:-}" == "true" ]]; then
  merge_flags+=( --enrich-in-radius )
fi
[[ -n "${MERGE_DATASETS:-}" ]] && merge_flags+=( --datasets "$MERGE_DATASETS" )
[[ -n "${MERGE_PREFER:-}" ]] && merge_flags+=( --prefer "$MERGE_PREFER" )

# Nearest media enrichment via planelookerupper (optional; network-bound)
if [[ "${MERGE_NEAREST_SCRAPE:-0}" == "1" || "${MERGE_NEAREST_SCRAPE:-0}" == "true" ]]; then
  merge_flags+=( --nearest-scrape )
  : "${MERGE_NEAREST_PHOTOS:=4}"
  : "${MERGE_NEAREST_FLIGHTS:=5}"
  merge_flags+=( --nearest-photos "$MERGE_NEAREST_PHOTOS" )
  merge_flags+=( --nearest-flights "$MERGE_NEAREST_FLIGHTS" )
fi

# jq output formatting mirrors MERGE_MINIFY: compact when minified, pretty otherwise
jq_flags=( )
if [[ "${MERGE_MINIFY}" == "1" || "${MERGE_MINIFY}" == "true" ]]; then
  jq_flags+=( -c )
fi

retriever_flags=( --json-stdout --quiet )
[[ "${SKIP_OPENSKY:-}" == "1" ]] && retriever_flags+=( --skip-opensky )
[[ "${SKIP_ADSB:-}"    == "1" ]] && retriever_flags+=( --skip-adsb )
[[ "${SKIP_FR24:-}"    == "1" ]] && retriever_flags+=( --skip-fr24 )

echo "Starting AirTracker MQTT publisher → mqtt://${MQTT_HOST}:${MQTT_PORT}/${MQTT_PREFIX}"
echo "  Point: lat=${LAT}, lon=${LON}, radius_nm=${RADIUS_NM}"
echo "  Fetch every ${FETCH_INTERVAL_SEC}s | publish nearest every ${NEAREST_INTERVAL_SEC}s | planes every ${PLANES_INTERVAL_SEC}s"

last_fetch_ts=0
last_nearest_pub_ts=0
last_planes_pub_ts=0
payload=""

# Optional: write merged JSON to this path on every fetch (empty to disable)
: "${WRITE_JSON_PATH:=}"

run_fetch() {
  local out
  out=$(python3 "$(dirname "$0")/../plane_retreiver.py" "$LAT" "$LON" -r "$RADIUS_NM" "${retriever_flags[@]}" 2>/dev/null \
    | python3 "$(dirname "$0")/../plane_merge.py" "${merge_flags[@]}" 2>/dev/null) || out=""
  if [[ -n "$out" ]]; then
    payload="$out"
    last_fetch_ts=$(date +%s)
    if [[ -n "${WRITE_JSON_PATH}" ]]; then
      mkdir -p "$(dirname "${WRITE_JSON_PATH}")" 2>/dev/null || true
      printf '%s\n' "$payload" > "${WRITE_JSON_PATH}" || true
    fi
  fi
}

publish_nearest() {
  [[ -z "$payload" ]] && return 0
  printf '%s' "$payload" \
    | jq ${jq_flags+"${jq_flags[@]}"} '.nearest' \
    | mosquitto_pub -t "${MQTT_PREFIX}/nearest" -r -s "${mosq_args[@]}"
  last_nearest_pub_ts=$(date +%s)
}

publish_planes() {
  [[ -z "$payload" ]] && return 0
  printf '%s' "$payload" \
    | jq ${jq_flags+"${jq_flags[@]}"} '.merged' \
    | mosquitto_pub -t "${MQTT_PREFIX}/planes" -r -s "${mosq_args[@]}"
  last_planes_pub_ts=$(date +%s)
}

if [[ "$RUN_ONCE" == "1" || "$RUN_ONCE" == "true" ]]; then
  if [[ "${MQTT_DISCOVERY_ON_START}" == "1" || "${MQTT_DISCOVERY_ON_START}" == "true" ]]; then
    if [[ -x "$(dirname "$0")/publish_ha_discovery.sh" ]]; then
      # Honor discovery script env toggles, e.g. HA_DISCOVERY_PRUNE=1 to prune stale topics
      bash "$(dirname "$0")/publish_ha_discovery.sh" || true
    fi
  fi
  run_fetch
  publish_nearest
  publish_planes
  exit 0
fi

while :; do
  # Publish HA discovery once at startup for convenience
  if [[ "${MQTT_DISCOVERY_ON_START}" == "1" || "${MQTT_DISCOVERY_ON_START}" == "true" ]]; then
    if [[ -x "$(dirname "$0")/publish_ha_discovery.sh" ]]; then
      # Honor discovery script env toggles, e.g. HA_DISCOVERY_PRUNE=1 to prune stale topics
      bash "$(dirname "$0")/publish_ha_discovery.sh" || true
    fi
    MQTT_DISCOVERY_ON_START=0
  fi

  now=$(date +%s)

  # Fetch when interval elapsed or payload is empty
  if (( now - last_fetch_ts >= FETCH_INTERVAL_SEC )) || [[ -z "$payload" ]]; then
    run_fetch
  fi

  # Publish nearest and planes on their own cadences (from cached payload)
  if (( now - last_nearest_pub_ts >= NEAREST_INTERVAL_SEC )); then
    publish_nearest
  fi
  if (( now - last_planes_pub_ts >= PLANES_INTERVAL_SEC )); then
    publish_planes
  fi

  sleep 1
done
