#!/usr/bin/env python3
"""
Simple MQTT publisher utility - replacement for mosquitto_pub
Usage: python3 mqtt_publish.py [options]
"""

import argparse
import sys
import os
import json
from typing import Optional
import paho.mqtt.client as mqtt


def publish_message(
    host: str,
    port: int,
    topic: str,
    payload: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    retain: bool = False,
    timeout: int = 10
) -> bool:
    """Publish a single message to MQTT broker"""

    def on_connect(client, userdata, flags, rc, properties):
        if rc == 0:
            userdata['connected'] = True
        else:
            userdata['error'] = f"Connection failed with code {rc}"

    def on_publish(client, userdata, mid, reason_code, properties):
        userdata['published'] = True

    def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
        userdata['disconnected'] = True

    # Client data to track state
    client_data = {
        'connected': False,
        'published': False,
        'disconnected': False,
        'error': None
    }

    try:
        # Create MQTT client
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, userdata=client_data)
        client.on_connect = on_connect
        client.on_publish = on_publish
        client.on_disconnect = on_disconnect

        # Set credentials if provided
        if username and password:
            client.username_pw_set(username, password)

        # Connect to broker
        client.connect(host, port, timeout)

        # Start network loop
        client.loop_start()

        # Wait for connection
        import time
        start_time = time.time()
        while not client_data['connected'] and not client_data['error']:
            if time.time() - start_time > timeout:
                client_data['error'] = "Connection timeout"
                break
            time.sleep(0.1)

        if client_data['error']:
            print(f"MQTT Error: {client_data['error']}", file=sys.stderr)
            return False

        # Publish message
        result = client.publish(topic, payload, retain=retain)

        # Wait for publish confirmation
        start_time = time.time()
        while not client_data['published']:
            if time.time() - start_time > timeout:
                print("Publish timeout", file=sys.stderr)
                return False
            time.sleep(0.1)

        # Disconnect
        client.disconnect()

        # Wait for disconnect
        start_time = time.time()
        while not client_data['disconnected']:
            if time.time() - start_time > 5:  # Shorter timeout for disconnect
                break
            time.sleep(0.1)

        client.loop_stop()
        return True

    except Exception as e:
        print(f"MQTT Error: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description='Publish message to MQTT broker')
    parser.add_argument('--host', required=True, help='MQTT broker host')
    parser.add_argument('-p', '--port', type=int, default=1883, help='MQTT broker port')
    parser.add_argument('-t', '--topic', required=True, help='MQTT topic')
    parser.add_argument('-u', '--username', help='MQTT username')
    parser.add_argument('-P', '--password', help='MQTT password')
    parser.add_argument('-r', '--retain', action='store_true', help='Retain message')
    parser.add_argument('-s', '--stdin', action='store_true', help='Read payload from stdin')
    parser.add_argument('-m', '--message', help='Message payload')
    parser.add_argument('--timeout', type=int, default=10, help='Connection timeout in seconds')

    args = parser.parse_args()

    # Get payload
    if args.stdin:
        payload = sys.stdin.read()
    elif args.message:
        payload = args.message
    else:
        print("Error: Must specify either --message or --stdin", file=sys.stderr)
        return 1

    # Publish message
    success = publish_message(
        host=args.host,
        port=args.port,
        topic=args.topic,
        payload=payload,
        username=args.username,
        password=args.password,
        retain=args.retain,
        timeout=args.timeout
    )

    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())