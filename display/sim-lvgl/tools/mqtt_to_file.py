#!/usr/bin/env python3
import os
import json
import signal
import sys
from pathlib import Path

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("Please install paho-mqtt: pip install paho-mqtt", file=sys.stderr)
    sys.exit(1)


BROKER = os.getenv("MQTT_HOST", "127.0.0.1")
PORT = int(os.getenv("MQTT_PORT", "1883"))
TOPIC = os.getenv("NEAREST_TOPIC", "airtracker/nearest")
USERNAME = os.getenv("MQTT_USERNAME", "")
PASSWORD = os.getenv("MQTT_PASSWORD", "")
OUT_PATH = Path(os.getenv("SIM_JSON_PATH", "display/sim-lvgl/data/nearest.json"))


def on_connect(client, userdata, flags, rc):
    print(f"Connected to MQTT {BROKER}:{PORT} rc={rc}")
    client.subscribe(TOPIC)
    print(f"Subscribed to {TOPIC}")


def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode("utf-8")
        obj = json.loads(payload)
    except Exception as e:
        print(f"Bad JSON on {msg.topic}: {e}")
        return
    try:
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with OUT_PATH.open("w") as f:
            json.dump(obj, f, ensure_ascii=False)
        print(f"Wrote {OUT_PATH} ({len(payload)} bytes)")
    except Exception as e:
        print(f"Write error: {e}")


def main():
    client = mqtt.Client()
    if USERNAME:
        client.username_pw_set(USERNAME, PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER, PORT, 60)
    # Graceful shutdown
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
    client.loop_forever()


if __name__ == "__main__":
    main()

