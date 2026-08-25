#!/usr/bin/env python3
"""
AirTracker Web Display Server

A Flask web server that provides a touch-friendly interface for the Pi Zero
to display real-time aircraft data. Subscribes to MQTT topics and pushes
updates to connected browsers via WebSocket.

Usage:
    python3 app.py
    or
    flask run --host=0.0.0.0 --port=5000

Features:
- Real-time MQTT data integration
- WebSocket for live browser updates
- Touch-optimized responsive design
- Multiple view modes (nearest, military, radar)
- Hamburger menu for space efficiency
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv

from mqtt_client import MQTTClient

# Load environment variables
load_dotenv()

# Configuration
class Config:
    SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'airtracker-web-display-secret')
    MQTT_HOST = os.getenv('MQTT_HOST', 'localhost')
    MQTT_PORT = int(os.getenv('MQTT_PORT', '1883'))
    MQTT_USER = os.getenv('MQTT_USER', '')
    MQTT_PASS = os.getenv('MQTT_PASS', '')
    DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)

# Initialize SocketIO with CORS for development
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Global data store for latest aircraft data
aircraft_data = {
    'nearest': None,
    'nearest_commercial': None,
    'nearest_military': None,
    'planes': [],
    'last_updated': None,
    'connection_status': 'disconnected'
}

# Initialize MQTT client
mqtt_client = None

def init_mqtt():
    """Initialize MQTT client with callback functions"""
    global mqtt_client

    def on_mqtt_connect(client, userdata, flags, rc):
        """Callback for MQTT connection"""
        if rc == 0:
            app.logger.info("Connected to MQTT broker")
            aircraft_data['connection_status'] = 'connected'

            # Subscribe to all AirTracker topics
            topics = [
                'airtracker/nearest',
                'airtracker/nearest_commercial',
                'airtracker/nearest_military',
                'airtracker/planes'
            ]

            for topic in topics:
                client.subscribe(topic)
                app.logger.info(f"Subscribed to {topic}")

            # Emit connection status to all clients
            socketio.emit('mqtt_status', {'status': 'connected'})
        else:
            app.logger.error(f"Failed to connect to MQTT broker: {rc}")
            aircraft_data['connection_status'] = 'error'
            socketio.emit('mqtt_status', {'status': 'error', 'code': rc})

    def on_mqtt_disconnect(client, userdata, rc):
        """Callback for MQTT disconnection"""
        app.logger.warning("Disconnected from MQTT broker")
        aircraft_data['connection_status'] = 'disconnected'
        socketio.emit('mqtt_status', {'status': 'disconnected'})

    def on_mqtt_message(client, userdata, msg):
        """Callback for MQTT message received"""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode())

            app.logger.info(f"Received MQTT message on {topic}: {len(str(payload))} bytes")

            # Update data store based on topic
            if topic == 'airtracker/nearest':
                aircraft_data['nearest'] = payload
            elif topic == 'airtracker/nearest_commercial':
                aircraft_data['nearest_commercial'] = payload
            elif topic == 'airtracker/nearest_military':
                aircraft_data['nearest_military'] = payload
            elif topic == 'airtracker/planes':
                aircraft_data['planes'] = payload if isinstance(payload, list) else []

            # Update timestamp
            aircraft_data['last_updated'] = datetime.now().isoformat()

            # Emit update to all connected clients
            socketio.emit('aircraft_update', {
                'topic': topic.replace('airtracker/', ''),
                'data': payload,
                'timestamp': aircraft_data['last_updated']
            })

        except Exception as e:
            app.logger.error(f"Error processing MQTT message: {e}")

    # Create MQTT client
    mqtt_client = MQTTClient(
        host=Config.MQTT_HOST,
        port=Config.MQTT_PORT,
        username=Config.MQTT_USER,
        password=Config.MQTT_PASS,
        on_connect=on_mqtt_connect,
        on_disconnect=on_mqtt_disconnect,
        on_message=on_mqtt_message
    )

    # Start MQTT client
    mqtt_client.start()

# Routes
@app.route('/')
def index():
    """Main dashboard - nearest aircraft view"""
    return render_template('index.html', view='nearest')

@app.route('/commercial')
def commercial():
    """Commercial aircraft view"""
    return render_template('index.html', view='commercial')

@app.route('/military')
def military():
    """Military aircraft view"""
    return render_template('index.html', view='military')

@app.route('/radar')
def radar():
    """Radar view (placeholder for future implementation)"""
    return render_template('index.html', view='radar')

@app.route('/planes')
def planes():
    """All planes list view"""
    return render_template('index.html', view='planes')

@app.route('/api/status')
def api_status():
    """API endpoint for system status"""
    return jsonify({
        'status': 'online',
        'mqtt_status': aircraft_data['connection_status'],
        'last_updated': aircraft_data['last_updated'],
        'data_available': {
            'nearest': aircraft_data['nearest'] is not None,
            'nearest_commercial': aircraft_data['nearest_commercial'] is not None,
            'nearest_military': aircraft_data['nearest_military'] is not None,
            'planes_count': len(aircraft_data['planes'])
        }
    })

@app.route('/api/data/<data_type>')
def api_data(data_type):
    """API endpoint for aircraft data"""
    if data_type in aircraft_data:
        return jsonify({
            'data': aircraft_data[data_type],
            'timestamp': aircraft_data['last_updated']
        })
    else:
        return jsonify({'error': 'Invalid data type'}), 400

# WebSocket events
@socketio.on('connect')
def handle_connect():
    """Handle WebSocket client connection"""
    app.logger.info(f"Client connected: {request.sid}")

    # Send current data to newly connected client
    emit('initial_data', {
        'nearest': aircraft_data['nearest'],
        'nearest_commercial': aircraft_data['nearest_commercial'],
        'nearest_military': aircraft_data['nearest_military'],
        'planes': aircraft_data['planes'],
        'last_updated': aircraft_data['last_updated'],
        'mqtt_status': aircraft_data['connection_status']
    })

@socketio.on('disconnect')
def handle_disconnect():
    """Handle WebSocket client disconnection"""
    app.logger.info(f"Client disconnected: {request.sid}")

@socketio.on('request_data')
def handle_data_request(data):
    """Handle client request for specific data"""
    data_type = data.get('type')
    if data_type in aircraft_data:
        emit('data_response', {
            'type': data_type,
            'data': aircraft_data[data_type],
            'timestamp': aircraft_data['last_updated']
        })

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return render_template('index.html', view='nearest'), 404

@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f"Internal error: {error}")
    return render_template('index.html', view='nearest'), 500

# Initialize logging
def setup_logging():
    """Configure application logging"""
    log_level = logging.DEBUG if Config.DEBUG else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Set Flask and SocketIO log levels
    logging.getLogger('flask_socketio').setLevel(logging.WARNING)
    logging.getLogger('socketio').setLevel(logging.WARNING)
    logging.getLogger('engineio').setLevel(logging.WARNING)

if __name__ == '__main__':
    # Setup logging
    setup_logging()

    # Initialize MQTT connection
    init_mqtt()

    try:
        # Run the application
        app.logger.info("Starting AirTracker Web Display Server")
        app.logger.info(f"MQTT Broker: {Config.MQTT_HOST}:{Config.MQTT_PORT}")

        socketio.run(
            app,
            host='0.0.0.0',
            port=5001,
            debug=Config.DEBUG,
            use_reloader=False,  # Disable reloader to prevent MQTT reconnection issues
            allow_unsafe_werkzeug=True  # Allow development server
        )
    except KeyboardInterrupt:
        app.logger.info("Shutting down server...")
    finally:
        if mqtt_client:
            mqtt_client.stop()