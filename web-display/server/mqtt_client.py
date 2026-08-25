#!/usr/bin/env python3
"""
MQTT Client for AirTracker Web Display

This module provides a threaded MQTT client that subscribes to AirTracker
topics and provides callbacks for real-time data processing.
"""

import logging
import threading
import time
from typing import Callable, Optional

import paho.mqtt.client as mqtt


class MQTTClient:
    """
    Threaded MQTT client for AirTracker data subscription
    """

    def __init__(
        self,
        host: str,
        port: int = 1883,
        keepalive: int = 60,
        username: Optional[str] = None,
        password: Optional[str] = None,
        on_connect: Optional[Callable] = None,
        on_disconnect: Optional[Callable] = None,
        on_message: Optional[Callable] = None
    ):
        """
        Initialize MQTT client

        Args:
            host: MQTT broker hostname
            port: MQTT broker port
            keepalive: Keepalive interval in seconds
            username: MQTT username (optional)
            password: MQTT password (optional)
            on_connect: Callback for connection events
            on_disconnect: Callback for disconnection events
            on_message: Callback for message events
        """
        self.host = host
        self.port = port
        self.keepalive = keepalive
        self.username = username
        self.password = password

        # Initialize MQTT client
        self.client = mqtt.Client()

        # Set authentication if provided
        if username and password:
            self.client.username_pw_set(username, password)

        # Set callbacks
        if on_connect:
            self.client.on_connect = on_connect
        if on_disconnect:
            self.client.on_disconnect = on_disconnect
        if on_message:
            self.client.on_message = on_message

        # Threading
        self._thread = None
        self._running = False

        # Logging
        self.logger = logging.getLogger(__name__)

    def start(self) -> None:
        """Start the MQTT client in a separate thread"""
        if self._running:
            self.logger.warning("MQTT client is already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.logger.info("MQTT client thread started")

    def stop(self) -> None:
        """Stop the MQTT client"""
        if not self._running:
            return

        self.logger.info("Stopping MQTT client...")
        self._running = False

        # Disconnect from broker
        if self.client.is_connected():
            self.client.disconnect()

        # Wait for thread to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

        self.logger.info("MQTT client stopped")

    def _run(self) -> None:
        """Main thread loop for MQTT client"""
        retry_count = 0
        max_retries = 5
        retry_delay = 5  # seconds

        while self._running:
            try:
                self.logger.info(f"Connecting to MQTT broker {self.host}:{self.port}")

                # Attempt connection
                result = self.client.connect(self.host, self.port, self.keepalive)

                if result == mqtt.MQTT_ERR_SUCCESS:
                    retry_count = 0  # Reset retry counter on successful connection

                    # Start the network loop
                    self.client.loop_forever()

                else:
                    self.logger.error(f"Failed to connect to MQTT broker: {result}")
                    self._handle_connection_failure(retry_count, max_retries, retry_delay)
                    retry_count += 1

            except Exception as e:
                self.logger.error(f"MQTT client error: {e}")
                self._handle_connection_failure(retry_count, max_retries, retry_delay)
                retry_count += 1

        self.logger.info("MQTT client thread exiting")

    def _handle_connection_failure(self, retry_count: int, max_retries: int, retry_delay: int) -> None:
        """Handle connection failures with exponential backoff"""
        if retry_count < max_retries and self._running:
            # Exponential backoff with jitter
            delay = min(retry_delay * (2 ** retry_count), 60)
            self.logger.warning(f"Retrying connection in {delay} seconds... (attempt {retry_count + 1}/{max_retries})")
            time.sleep(delay)
        elif retry_count >= max_retries:
            self.logger.error("Max connection retries exceeded. Stopping MQTT client.")
            self._running = False

    def is_connected(self) -> bool:
        """Check if MQTT client is connected"""
        return self.client.is_connected()

    def publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False) -> bool:
        """
        Publish a message to MQTT broker

        Args:
            topic: MQTT topic
            payload: Message payload
            qos: Quality of Service level
            retain: Retain message flag

        Returns:
            True if message was queued for transmission, False otherwise
        """
        if not self.is_connected():
            self.logger.warning("Cannot publish: MQTT client not connected")
            return False

        try:
            result = self.client.publish(topic, payload, qos, retain)
            return result.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            self.logger.error(f"Error publishing message: {e}")
            return False

    def subscribe(self, topic: str, qos: int = 0) -> bool:
        """
        Subscribe to an MQTT topic

        Args:
            topic: MQTT topic to subscribe to
            qos: Quality of Service level

        Returns:
            True if subscription was successful, False otherwise
        """
        if not self.is_connected():
            self.logger.warning("Cannot subscribe: MQTT client not connected")
            return False

        try:
            result, _ = self.client.subscribe(topic, qos)
            return result == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            self.logger.error(f"Error subscribing to topic {topic}: {e}")
            return False