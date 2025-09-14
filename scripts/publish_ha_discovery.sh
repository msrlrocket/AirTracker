#!/usr/bin/env bash

# Publish Home Assistant MQTT Discovery configs for AirTracker sensors
#
# Creates entities that read from the AirTracker publisher's topics, e.g.:
#   - <prefix>/nearest (JSON with the closest aircraft)
#
# It publishes retained config messages under the HA discovery prefix (default: homeassistant).
# After running this, restart HA or wait a few seconds for entities to appear.
#
# Requirements:
#   - mosquitto_pub
#   - jq

set -u -o pipefail

# Optional flags (also via env):
#  - HA_DISCOVERY_PRUNE=1       → remove retained discovery topics no longer defined
#  - HA_DISCOVERY_DRY_RUN=1     → print actions without publishing/deleting
#  - HA_DISCOVERY_PRUNE_WAIT_SEC → seconds to wait for retained topics (default 2)

show_usage() {
  cat <<EOF
Usage: $(basename "$0") [--dry-run|-n] [--prune|-p] [--help|-h]

Publishes Home Assistant MQTT Discovery configs for AirTracker sensors.

Options:
  -n, --dry-run   Print what would be published/removed, no changes
  -p, --prune     After publishing, remove stale retained discovery topics
  -h, --help      Show this help and exit

Also accepts env toggles: HA_DISCOVERY_DRY_RUN=1, HA_DISCOVERY_PRUNE=1
EOF
}

# Note: we load .env first, then compute flag defaults from env, then parse CLI

# Load repository .env if present (exports vars like MQTT_* and defaults)
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  . "$ROOT_DIR/.env"
  set +a
fi

# MQTT connection (from .env or inline env vars)
: "${MQTT_HOST:=127.0.0.1}"
: "${MQTT_PORT:=1883}"
: "${MQTT_USER:=}"
: "${MQTT_PASS:=}"
: "${MQTT_PREFIX:=airtracker}"

# HA discovery options
: "${HA_DISCOVERY_PREFIX:=homeassistant}"
: "${HA_DEVICE_ID:=airtracker}"
: "${HA_DEVICE_NAME:=AirTracker}"
: "${MQTT_DEVICE_TRACKER:=0}"

# Flag defaults (after .env load so env toggles apply), then parse CLI
DRY_RUN=${HA_DISCOVERY_DRY_RUN:-0}
PRUNE=${HA_DISCOVERY_PRUNE:-0}
PRUNE_WAIT_SEC=${HA_DISCOVERY_PRUNE_WAIT_SEC:-2}

# Parse CLI flags (override env)
while [[ ${1:-} ]]; do
  case "$1" in
    -n|--dry-run) DRY_RUN=1 ;;
    -p|--prune)   PRUNE=1 ;;
    -h|--help)    show_usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; show_usage; exit 1 ;;
  esac
  shift
done

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }; }
need mosquitto_pub
need jq

mosq_args=( -h "$MQTT_HOST" -p "$MQTT_PORT" )
[[ -n "${MQTT_USER}" ]] && mosq_args+=( -u "$MQTT_USER" )
[[ -n "${MQTT_PASS}" ]] && mosq_args+=( -P "$MQTT_PASS" )

STATE_TOPIC_NEAREST="${MQTT_PREFIX}/nearest"

# Device object groups entities in HA UI
device_json=$(jq -nc --arg id "$HA_DEVICE_ID" --arg name "$HA_DEVICE_NAME" '
  {
    identifiers: [$id],
    name: $name,
    manufacturer: "AirTracker",
    model: "MQTT Publisher"
  }
')

# Track expected discovery config topics so we can prune stales if requested
expected_topics=()

publish_config() {
  local topic="$1"
  local payload="$2"
  expected_topics+=("$topic")
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "DRY-RUN publish: $topic"
    return 0
  fi
  mosquitto_pub "${mosq_args[@]}" -t "$topic" -r -m "$payload"
}

publish_sensor() {
  local object_id="$1"; shift
  local name="$1"; shift
  local unit="$1"; shift
  local value_tmpl="$1"; shift
  local device_class="${1:-}"; shift || true
  local state_class="${1:-}"; shift || true
  local icon="${1:-}"; shift || true

  local uid="${HA_DEVICE_ID}_${object_id}"
  local payload
  payload=$(jq -nc \
    --arg name "$name" \
    --arg st "$STATE_TOPIC_NEAREST" \
    --arg unit "$unit" \
    --arg vt "$value_tmpl" \
    --arg uid "$uid" \
    --arg devclass "$device_class" \
    --arg stateclass "$state_class" \
    --arg icon "$icon" \
    --argjson device "$device_json" '
      {
        name: $name,
        state_topic: $st,
        value_template: $vt,
        unique_id: $uid,
        device: $device
      }
      + ( if ($unit       | length) > 0 then { unit_of_measurement: $unit } else {} end )
      + ( if ($devclass   | length) > 0 then { device_class: $devclass } else {} end )
      + ( if ($stateclass | length) > 0 then { state_class: $stateclass } else {} end )
      + ( if ($icon       | length) > 0 then { icon: $icon } else {} end )
    ')

  local topic="${HA_DISCOVERY_PREFIX}/sensor/${HA_DEVICE_ID}/${object_id}/config"
  publish_config "$topic" "$payload"
}

publish_sensor_attrs() {
  local object_id="$1"; shift
  local name="$1"; shift
  local unit="$1"; shift
  local value_tmpl="$1"; shift
  local attrs_topic="$1"; shift
  local attrs_tmpl="${1:-}"; shift || true
  local device_class="${1:-}"; shift || true
  local state_class="${1:-}"; shift || true
  local icon="${1:-}"; shift || true

  local uid="${HA_DEVICE_ID}_${object_id}"
  local payload
  payload=$(jq -nc \
    --arg name "$name" \
    --arg st "$STATE_TOPIC_NEAREST" \
    --arg unit "$unit" \
    --arg vt "$value_tmpl" \
    --arg at "$attrs_topic" \
    --arg att "$attrs_tmpl" \
    --arg uid "$uid" \
    --arg devclass "$device_class" \
    --arg stateclass "$state_class" \
    --arg icon "$icon" \
    --argjson device "$device_json" '
      {
        name: $name,
        state_topic: $st,
        value_template: $vt,
        unique_id: $uid,
        device: $device,
        json_attributes_topic: $at
      }
      + ( if ($unit       | length) > 0 then { unit_of_measurement: $unit } else {} end )
      + ( if ($devclass   | length) > 0 then { device_class: $devclass } else {} end )
      + ( if ($stateclass | length) > 0 then { state_class: $stateclass } else {} end )
      + ( if ($icon       | length) > 0 then { icon: $icon } else {} end )
      + ( if ($att        | length) > 0 then { json_attributes_template: $att } else {} end )
    ')

  local topic="${HA_DISCOVERY_PREFIX}/sensor/${HA_DEVICE_ID}/${object_id}/config"
  publish_config "$topic" "$payload"
}

publish_binary_sensor() {
  local object_id="$1"; shift
  local name="$1"; shift
  local value_tmpl="$1"; shift
  local device_class="${1:-}"; shift || true
  local icon="${1:-}"; shift || true

  local uid="${HA_DEVICE_ID}_${object_id}"
  local payload
  payload=$(jq -nc \
    --arg name "$name" \
    --arg st "$STATE_TOPIC_NEAREST" \
    --arg vt "$value_tmpl" \
    --arg uid "$uid" \
    --arg devclass "$device_class" \
    --arg icon "$icon" \
    --argjson device "$device_json" '
      {
        name: $name,
        state_topic: $st,
        value_template: $vt,
        unique_id: $uid,
        device: $device,
        payload_on: "true",
        payload_off: "false"
      }
      + ( if ($devclass | length) > 0 then { device_class: $devclass } else {} end )
      + ( if ($icon     | length) > 0 then { icon: $icon } else {} end )
    ')

  local topic="${HA_DISCOVERY_PREFIX}/binary_sensor/${HA_DEVICE_ID}/${object_id}/config"
  publish_config "$topic" "$payload"
}

# Optional: MQTT device_tracker for nearest plane (map + history in HA)
publish_device_tracker() {
  local object_id="nearest_tracker"
  local name="AirTracker Nearest (Tracker)"
  local uid="${HA_DEVICE_ID}_${object_id}"

  # Attributes template: publish only the keys map consumers care about
  # HA will use latitude/longitude attributes for map position
  local attrs_tmpl
  attrs_tmpl='{{ {"latitude": value_json.latitude, "longitude": value_json.longitude, "altitude_ft": value_json.altitude_ft, "ground_speed_kt": value_json.ground_speed_kt, "track_deg": value_json.track_deg, "registration": value_json.registration, "hex": value_json.hex, "callsign": value_json.callsign, "classification": value_json.classification} | tojson }}'

  local state_tmpl
  # Show callsign/hex as state for readability
  state_tmpl='{{ value_json.callsign or value_json.hex or "plane" }}'

  local payload
  payload=$(jq -nc \
    --arg name "$name" \
    --arg st "$STATE_TOPIC_NEAREST" \
    --arg uid "$uid" \
    --arg icon "mdi:airplane" \
    --arg statetmpl "$state_tmpl" \
    --arg attrtmpl "$attrs_tmpl" \
    --argjson device "$device_json" '
      {
        name: $name,
        unique_id: $uid,
        device: $device,
        state_topic: $st,
        value_template: $statetmpl,
        json_attributes_topic: $st,
        json_attributes_template: $attrtmpl,
        source_type: "gps",
        icon: $icon
      }
    ')

  local topic="${HA_DISCOVERY_PREFIX}/device_tracker/${HA_DEVICE_ID}/${object_id}/config"
  publish_config "$topic" "$payload"
}

echo "Publishing HA discovery configs to '${HA_DISCOVERY_PREFIX}' for device '${HA_DEVICE_ID}' (reads '${STATE_TOPIC_NEAREST}')"

# Numeric telemetry
publish_sensor "distance_nm"       "Nearest Distance"   "nm" "{{ value_json.distance_nm }}"     ""           "measurement" "mdi:map-marker-distance"
publish_sensor "bearing_deg"       "Nearest Bearing"    "°"  "{{ value_json.bearing_deg }}"     ""           "measurement" "mdi:compass"
publish_sensor "altitude_ft"       "Altitude"           "ft" "{{ value_json.altitude_ft }}"      ""           "measurement" "mdi:arrow-collapse-down"
publish_sensor "ground_speed_kt"   "Ground Speed"       "kt" "{{ value_json.ground_speed_kt }}" ""           "measurement" "mdi:speedometer"
publish_sensor "track_deg"         "Track"              "°"  "{{ value_json.track_deg }}"       ""           "measurement" "mdi:angle-acute"
publish_sensor "vertical_rate_fpm" "Vertical Rate"      "fpm" "{{ value_json.vertical_rate_fpm }}" ""        "measurement" "mdi:swap-vertical"
publish_sensor "position_age_sec"  "Position Age"       "s"  "{{ value_json.position_age_sec }}" ""         "measurement" "mdi:timer-outline"
publish_sensor "latitude"          "Latitude"           "°"  "{{ value_json.latitude }}"        ""           "measurement" "mdi:latitude"
publish_sensor "longitude"         "Longitude"          "°"  "{{ value_json.longitude }}"       ""           "measurement" "mdi:longitude"
publish_sensor "position_timestamp" "Position Timestamp" "s"  "{{ value_json.position_timestamp }}" ""        "measurement" "mdi:clock-outline"
publish_sensor "remaining_nm"      "Remaining Distance" "nm" "{{ value_json.remaining_nm }}"     ""           "measurement" "mdi:map-marker-distance"
publish_sensor "eta_min"           "ETA"                "min" "{{ value_json.eta_min }}"        ""           "measurement" "mdi:clock-end"
publish_sensor "souls_on_board_max" "Souls On Board (Max)" "people" "{{ value_json.souls_on_board_max }}" "" "measurement" "mdi:account-group"

# Text identifiers
publish_sensor "hex"            "ICAO Hex"        "" "{{ value_json.hex }}"            "" "" "mdi:hexagon"
publish_sensor "registration"   "Registration"    "" "{{ value_json.registration }}"   "" "" "mdi:card-account-details"
publish_sensor "callsign"       "Callsign"        "" "{{ value_json.callsign }}"       "" "" "mdi:account-voice"
publish_sensor "flight_no"      "Flight Number"   "" "{{ value_json.flight_no }}"      "" "" "mdi:airplane"
publish_sensor "airline_icao"   "Airline ICAO"    "" "{{ value_json.airline_icao }}"   "" "" "mdi:office-building"
publish_sensor "aircraft_type"  "Aircraft Type"   "" "{{ value_json.aircraft_type }}"  "" "" "mdi:airplane"
publish_sensor "classification"  "Classification"   "" "{{ value_json.classification }}"  "" "" "mdi:account-badge"
publish_sensor "origin_iata"    "Origin IATA"     "" "{{ value_json.origin_iata }}"    "" "" "mdi:airplane-takeoff"
publish_sensor "destination_iata" "Destination IATA" "" "{{ value_json.destination_iata }}" "" "" "mdi:airplane-landing"
publish_sensor "squawk"         "Squawk"          "" "{{ value_json.squawk }}"         "" "" "mdi:numeric"
publish_sensor "origin_country" "Origin Country"  "" "{{ value_json.origin_country }}" "" "" "mdi:flag"
publish_sensor "souls_on_board_max_text" "Souls On Board (Text)" "" "{{ value_json.souls_on_board_max_text }}" "" "" "mdi:account-group-outline"

# Route (prefers IATA codes, falls back to city names)
publish_sensor "route" "Route" "" "{{ ((value_json.origin_iata | default('', true)) or (value_json.lookups.origin_airport.iata | default('', true)) or (value_json.lookups.origin_airport.city | default('', true)) or '?') ~ ' → ' ~ ((value_json.destination_iata | default('', true)) or (value_json.lookups.destination_airport.iata | default('', true)) or (value_json.lookups.destination_airport.city | default('', true)) or '?') }}" "" "" "mdi:airplane"

# Verbose route "City (IATA) → City (IATA)", with graceful fallbacks
publish_sensor "route_verbose" "Route (Verbose)" "" "{{ ( (((value_json.lookups.origin_airport.city | default('', true)) or (value_json.lookups.origin_airport.name | default('', true))) ~ ( ' (' ~ (value_json.origin_iata | default(value_json.lookups.origin_airport.iata | default('', true), true)) ~ ')' ) if (value_json.origin_iata | default(value_json.lookups.origin_airport.iata | default('', true), true)) else ((value_json.lookups.origin_airport.city | default('', true)) or (value_json.lookups.origin_airport.name | default('', true))) ) or (value_json.origin_iata | default(value_json.lookups.origin_airport.iata | default('', true), true)) or '?' ) ~ ' → ' ~ ( (((value_json.lookups.destination_airport.city | default('', true)) or (value_json.lookups.destination_airport.name | default('', true))) ~ ( ' (' ~ (value_json.destination_iata | default(value_json.lookups.destination_airport.iata | default('', true), true)) ~ ')' ) if (value_json.destination_iata | default(value_json.lookups.destination_airport.iata | default('', true), true)) else ((value_json.lookups.destination_airport.city | default('', true)) or (value_json.lookups.destination_airport.name | default('', true))) ) or (value_json.destination_iata | default(value_json.lookups.destination_airport.iata | default('', true), true)) or '?' ) }}" "" "" "mdi:airplane"

# Origin airport details (from lookups.origin_airport, when available)
publish_sensor "origin_airport_name"           "Origin Airport Name"         ""  "{{ value_json.lookups.origin_airport.name | default(\"\", true) }}"                    "" "" "mdi:airport"
publish_sensor "origin_airport_city"           "Origin City"                 ""  "{{ value_json.lookups.origin_airport.city | default(\"\", true) }}"                    "" "" "mdi:city"
publish_sensor "origin_airport_region"         "Origin Region"               ""  "{{ value_json.lookups.origin_airport.region | default(\"\", true) }}"                  "" "" "mdi:map"
publish_sensor "origin_airport_country_code"   "Origin Country Code"         ""  "{{ value_json.lookups.origin_airport.country_code | default(\"\", true) }}"            "" "" "mdi:flag"
publish_sensor "origin_airport_country_name"   "Origin Airport Country"      ""  "{{ value_json.lookups.origin_airport.country_name | default(\"\", true) }}"            "" "" "mdi:flag"
publish_sensor "origin_airport_lat"            "Origin Latitude"             "°"  "{{ value_json.lookups.origin_airport.lat }}"                    "" "measurement" "mdi:latitude"
publish_sensor "origin_airport_lon"            "Origin Longitude"            "°"  "{{ value_json.lookups.origin_airport.lon }}"                    "" "measurement" "mdi:longitude"
publish_sensor "origin_airport_elevation_ft"   "Origin Elevation"            "ft" "{{ value_json.lookups.origin_airport.elevation_ft }}"           "" "measurement" "mdi:altimeter"

# Destination airport details (from lookups.destination_airport, when available)
publish_sensor "destination_airport_name"         "Destination Airport Name"   ""  "{{ value_json.lookups.destination_airport.name | default(\"\", true) }}"               "" "" "mdi:airport"
publish_sensor "destination_airport_city"         "Destination City"           ""  "{{ value_json.lookups.destination_airport.city | default(\"\", true) }}"               "" "" "mdi:city"
publish_sensor "destination_airport_region"       "Destination Region"         ""  "{{ value_json.lookups.destination_airport.region | default(\"\", true) }}"             "" "" "mdi:map"
publish_sensor "destination_airport_country_code" "Destination Country Code"   ""  "{{ value_json.lookups.destination_airport.country_code | default(\"\", true) }}"       "" "" "mdi:flag"
publish_sensor "destination_airport_country_name" "Destination Airport Country" ""  "{{ value_json.lookups.destination_airport.country_name | default(\"\", true) }}"       "" "" "mdi:flag"
publish_sensor "destination_airport_lat"          "Destination Latitude"       "°"  "{{ value_json.lookups.destination_airport.lat }}"               "" "measurement" "mdi:latitude"
publish_sensor "destination_airport_lon"          "Destination Longitude"      "°"  "{{ value_json.lookups.destination_airport.lon }}"               "" "measurement" "mdi:longitude"
publish_sensor "destination_airport_elevation_ft" "Destination Elevation"      "ft" "{{ value_json.lookups.destination_airport.elevation_ft }}"      "" "measurement" "mdi:altimeter"

# Airline lookup details (from lookups.airline, when available)
publish_sensor "airline_name"           "Airline Name"           ""  "{{ value_json.lookups.airline.name | default(\"\", true) }}"         "" "" "mdi:office-building"
publish_sensor "airline_callsign"       "Airline Callsign"       ""  "{{ value_json.lookups.airline.callsign | default(\"\", true) }}"     "" "" "mdi:account-voice"
publish_sensor "airline_iata"           "Airline IATA"           ""  "{{ value_json.lookups.airline.iata | default(\"\", true) }}"         "" "" "mdi:label"
publish_sensor "airline_country_code"   "Airline Country Code"   ""  "{{ value_json.lookups.airline.country_code | default(\"\", true) }}" "" "" "mdi:flag"
publish_sensor "airline_country_name"   "Airline Country"        ""  "{{ value_json.lookups.airline.country_name | default(\"\", true) }}" "" "" "mdi:flag"

# Aircraft lookup details (from lookups.aircraft, when available)
publish_sensor "aircraft_name"           "Aircraft Name"          ""       "{{ value_json.lookups.aircraft.name | default(\"\", true) }}"           "" "" "mdi:airplane"
publish_sensor "aircraft_manufacturer"   "Aircraft Manufacturer"  ""       "{{ value_json.lookups.aircraft.manufacturer | default(\"\", true) }}" "" "" "mdi:factory"
publish_sensor "aircraft_model"          "Aircraft Model"         ""       "{{ value_json.lookups.aircraft.model | default(\"\", true) }}"        "" "" "mdi:cube-outline"
publish_sensor "aircraft_seats_max"      "Aircraft Seats (Catalog)" "people" "{{ value_json.lookups.aircraft.seats_max | default(\"\", true) }}"   "" "measurement" "mdi:account-group"
publish_sensor "aircraft_lookup_status"  "Aircraft Lookup Status" ""       "{{ value_json.lookups.aircraft.lookup_status | default(\"\", true) }}" "" "" "mdi:check-decagram"
publish_sensor "aircraft_iata_aliases"   "Aircraft IATA Aliases"  ""       "{{ (value_json.lookups.aircraft.iata_aliases | default([], true)) | join(',') }}" "" "" "mdi:label-multiple-outline"

# Binary on_ground flag
publish_binary_sensor "on_ground" "On Ground" "{{ value_json.on_ground }}" "" "mdi:airplane-landing"
publish_binary_sensor "is_military" "Is Military" "{{ value_json.is_military }}" "" "mdi:shield-airplane"
publish_binary_sensor "souls_on_board_max_is_estimate" "Souls Max Is Estimate" "{{ value_json.souls_on_board_max_is_estimate }}" "" "mdi:account-question"

# Raw attributes sensor with full JSON attached as attributes
# State shows the hex or callsign; all fields are available in attributes
publish_sensor_attrs "nearest" "AirTracker Nearest (RAW)" "" "{{ value_json.callsign or value_json.hex }}" "$STATE_TOPIC_NEAREST" "" "" "" "mdi:airplane"

# Optional: device_tracker for nearest
if [[ "${MQTT_DEVICE_TRACKER}" == "1" || "${MQTT_DEVICE_TRACKER}" == "true" ]]; then
  publish_device_tracker
fi

echo "Done. If entities don’t show, check HA’s MQTT integration and discovery prefix."

# Optionally prune stale retained discovery topics for this device
if [[ "$PRUNE" == "1" ]]; then
  # Need mosquitto_sub only when pruning
  need mosquitto_sub
  echo "Pruning stale discovery topics under '${HA_DISCOVERY_PREFIX}/+/$(printf %s "$HA_DEVICE_ID")/+/config' (wait ${PRUNE_WAIT_SEC}s)"

  # Membership helper compatible with Bash 3.2 (no associative arrays)
  topic_in_expected() {
    local needle="$1"
    local t
    for t in "${expected_topics[@]}"; do
      [[ "$t" == "$needle" ]] && return 0
    done
    return 1
  }

  # Collect existing retained topics for this device (Bash 3.2 compatible)
  existing_lines=()
  while IFS= read -r __line; do
    existing_lines+=("$__line")
  done < <(
    mosquitto_sub "${mosq_args[@]}" -v \
      -t "${HA_DISCOVERY_PREFIX}/+/$(printf %s "$HA_DEVICE_ID")/+/config" \
      -W "$PRUNE_WAIT_SEC" 2>/dev/null || true
  )

  stale_topics=()
  for line in "${existing_lines[@]}"; do
    [[ -z "$line" ]] && continue
    topic=${line%% *}
    payload=${line#* }
    # If there was no space, payload equals topic; clear it
    [[ "$payload" == "$topic" ]] && payload=""

    # Only consider topics not republished in this run
    if ! topic_in_expected "$topic"; then
      # Extra safety: ensure payload claims our device id
      if echo "$payload" | jq -e --arg id "$HA_DEVICE_ID" '((.device.identifiers // []) | index($id)) or ((.unique_id // "") | startswith($id + "_"))' >/dev/null 2>&1; then
        stale_topics+=("$topic")
      fi
    fi
  done

  if [[ ${#stale_topics[@]} -eq 0 ]]; then
    echo "No stale discovery topics found."
  else
    for t in "${stale_topics[@]}"; do
      if [[ "$DRY_RUN" == "1" ]]; then
        echo "DRY-RUN prune: $t"
      else
        mosquitto_pub "${mosq_args[@]}" -t "$t" -r -n
        echo "Pruned: $t"
      fi
    done
  fi
fi
