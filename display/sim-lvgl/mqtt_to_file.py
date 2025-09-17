#!/usr/bin/env python3
"""
MQTT to File Bridge for AirTracker Simulator

Subscribes to MQTT airtracker/nearest topic and writes the data to a JSON file
that the LVGL simulator can read using its existing JSON loader.
"""

import json
import time
import signal
import sys
from pathlib import Path
import paho.mqtt.client as mqtt

# MQTT Configuration (matches your .env)
MQTT_HOST = "192.168.2.244"
MQTT_PORT = 1883
MQTT_USER = "mqtt"
MQTT_PASS = "Tannerman1!1"
MQTT_TOPIC = "airtracker/nearest"

# Output file for simulator
OUTPUT_FILE = "sim_data.json"

# Global state
running = True
last_data = None

def signal_handler(sig, frame):
    global running
    print("Shutting down MQTT bridge...")
    running = False

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"Connected to MQTT broker at {MQTT_HOST}:{MQTT_PORT}")
        client.subscribe(MQTT_TOPIC)
        print(f"Subscribed to {MQTT_TOPIC}")
    else:
        print(f"Failed to connect to MQTT broker (code {rc})")

def on_disconnect(client, userdata, rc):
    print("Disconnected from MQTT broker")

def on_message(client, userdata, msg):
    global last_data
    try:
        # Parse the MQTT message
        data = json.loads(msg.payload.decode('utf-8'))

        # Keep original MQTT format for the JSON loader to parse correctly
        sim_data = data.copy()  # Start with original data

        # Add the history data formatting that the loader expects
        history = data.get("history", [])
        if history:
            sim_data["history"] = []
            for h in history[:5]:  # Only take first 5
                sim_data["history"].append({
                    "flight": h.get("flight", ""),
                    "origin": h.get("origin", ""),
                    "destination": h.get("destination", ""),
                    "date_yyyy_mm_dd": h.get("date_yyyy_mm_dd", ""),
                    "block_time_hhmm": h.get("block_time_hhmm", ""),
                    "arr_or_eta_hhmm": h.get("arr_or_eta_hhmm", "")
                })


        last_data = sim_data

        # Write to file
        with open(OUTPUT_FILE, 'w') as f:
            json.dump(sim_data, f, indent=2)

        print(f"Updated {OUTPUT_FILE} - {sim_data['callsign']} from {sim_data['route_origin']} to {sim_data['route_destination']}")

    except Exception as e:
        print(f"Error processing MQTT message: {e}")

def get_nested(data, keys, default=""):
    """Safely get nested dictionary value"""
    current = data
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current if current is not None else default

def bearing_to_cardinal(deg):
    """Convert bearing to cardinal direction"""
    directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    idx = int((deg + 22.5) / 45) % 8
    return directions[idx]

def format_eta(eta_min):
    """Format ETA minutes as HH:MM"""
    if eta_min <= 0:
        return "--:--"
    hours = int(eta_min // 60)
    minutes = int(eta_min % 60)
    return f"{hours:02d}:{minutes:02d}"

def main():
    global running

    print("AirTracker MQTT to File Bridge")
    print(f"Will write live data to: {OUTPUT_FILE}")
    print("Use this file with: SIM_JSON_PATH=sim_data.json ./airtracker_sim")
    print()

    # Set up signal handler
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create MQTT client
    client = mqtt.Client()
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    try:
        # Connect to MQTT broker
        client.connect(MQTT_HOST, MQTT_PORT, 60)

        # Start the loop
        client.loop_start()

        # Keep running until interrupted
        while running:
            time.sleep(1)

    except Exception as e:
        print(f"MQTT error: {e}")
    finally:
        client.loop_stop()
        client.disconnect()
        print("MQTT bridge stopped")

if __name__ == "__main__":
    main()