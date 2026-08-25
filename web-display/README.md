# AirTracker Web Display

A touch-optimized web interface for displaying real-time aircraft data on Pi Zero with touchscreen. Subscribes to MQTT streams from the AirTracker unified system and provides a responsive, touch-friendly interface.

## Features

- **Touch-Optimized**: 44px minimum touch targets, responsive design
- **Real-Time Updates**: WebSocket integration for live MQTT data streaming
- **Multiple Views**: Nearest aircraft, military aircraft, radar view, all aircraft list
- **Responsive Design**: Optimized for small touchscreens and mobile devices
- **Docker Ready**: Configured for unRAID deployment with Docker Compose

## Architecture

```
┌─────────────────┐    MQTT     ┌──────────────────┐    WebSocket   ┌─────────────────┐
│   AirTracker    │ ──────────► │   Flask Server   │ ─────────────► │   Web Browser   │
│   (Producer)    │             │   (MQTT Client)  │                │   (Pi Zero)     │
└─────────────────┘             └──────────────────┘                └─────────────────┘
```

## Quick Start

### Local Development

1. **Install Dependencies**
   ```bash
   cd web-display/server
   pip install -r requirements.txt
   ```

2. **Configure Environment**
   ```bash
   # Copy and edit environment variables
   cp ../../.env.example .env

   # Edit MQTT settings
   vim .env
   ```

3. **Run Development Server**
   ```bash
   python app.py
   ```

4. **Access Interface**
   - Open browser to `http://localhost:5000`
   - Use touch gestures or click navigation

### Docker Development

1. **Build and Run**
   ```bash
   cd web-display
   docker-compose up --build
   ```

2. **Test with Mock MQTT** (optional)
   ```bash
   # Start with local MQTT broker
   docker-compose --profile testing up
   ```

### Production Deployment (unRAID)

1. **Build Image**
   ```bash
   docker build -t airtracker-web-display .
   ```

2. **Deploy to unRAID**
   - Container Repository: `airtracker-web-display`
   - Network Type: `bridge`
   - Port Mapping: `5000:5000`
   - Environment Variables:
     - `MQTT_HOST`: Your MQTT broker host
     - `MQTT_PORT`: 1883
     - `MQTT_USER`: (if required)
     - `MQTT_PASS`: (if required)

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASK_SECRET_KEY` | auto-generated | Flask session secret |
| `MQTT_HOST` | `localhost` | MQTT broker hostname |
| `MQTT_PORT` | `1883` | MQTT broker port |
| `MQTT_USER` | (empty) | MQTT username |
| `MQTT_PASS` | (empty) | MQTT password |
| `FLASK_DEBUG` | `false` | Enable debug mode |

### MQTT Topics

The web display subscribes to these AirTracker topics:

- `airtracker/nearest` - Nearest aircraft (any type)
- `airtracker/nearest_commercial` - Nearest commercial aircraft
- `airtracker/nearest_military` - Nearest military aircraft
- `airtracker/planes` - Full aircraft list

## Interface

### Navigation

- **Hamburger Menu**: Touch-friendly slide-out navigation
- **Views**:
  - 🎯 Nearest Aircraft (default)
  - 🪖 Military Aircraft
  - 📡 Radar View (placeholder)
  - 📋 All Aircraft List

### Touch Interaction

- **44px minimum touch targets** for accessibility
- **Touch feedback** with visual scaling
- **iOS bounce scroll prevention** for app-like feel
- **Responsive breakpoints** for different screen sizes

### Data Display

- **Real-time updates** via WebSocket
- **Connection status indicator**
- **Last update timestamp**
- **Aircraft count tracking**
- **Automatic retry** on connection loss

## API Endpoints

- `GET /api/status` - System and connection status
- `GET /api/data/<type>` - Specific data type (nearest, planes, etc.)
- `WebSocket /` - Real-time data streaming

## Development

### File Structure

```
web-display/
├── server/
│   ├── app.py              # Flask application
│   ├── mqtt_client.py      # MQTT client wrapper
│   ├── requirements.txt    # Python dependencies
│   ├── static/
│   │   ├── css/style.css   # Touch-optimized styles
│   │   └── js/app.js       # WebSocket client logic
│   └── templates/
│       └── index.html      # Single-page application
├── Dockerfile              # Production container
├── docker-compose.yml      # Development setup
├── mosquitto.conf          # Test MQTT broker config
└── README.md              # This file
```

### Testing

1. **Start AirTracker Producer**
   ```bash
   cd ../../mqtt/unified
   python airtracker.py --mqtt-publish-all --continuous
   ```

2. **Monitor MQTT Topics**
   ```bash
   mosquitto_sub -h localhost -t "airtracker/+"
   ```

3. **Check Web Interface**
   - Navigate between views
   - Test touch interactions
   - Verify real-time updates

### Troubleshooting

- **No MQTT Connection**: Check `MQTT_HOST` and broker accessibility
- **No Data Updates**: Verify AirTracker is publishing to MQTT
- **Touch Issues**: Ensure 44px minimum touch targets in CSS
- **Container Issues**: Check Docker logs and health checks

## Contributing

1. Follow existing code style and conventions
2. Test on actual Pi Zero touchscreen when possible
3. Maintain responsive design for various screen sizes
4. Update documentation for any new features