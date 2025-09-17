#!/bin/bash

# AirTracker Unraid Runner Script
#
# This script handles Python virtual environment activation and runs AirTracker
#
# Usage:
#   ./run_airtracker.sh                    # Run once with default .env
#   ./run_airtracker.sh continuous        # Run continuously
#   ./run_airtracker.sh /path/to/.env     # Run once with custom .env
#   ./run_airtracker.sh continuous /path/to/.env  # Run continuously with custom .env

set -e  # Exit on any error

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AIRTRACKER_ROOT="$SCRIPT_DIR"

# Default values
RUN_MODE="once"
ENV_FILE="$AIRTRACKER_ROOT/.env"

# Parse arguments
if [[ "$1" == "continuous" ]]; then
    RUN_MODE="continuous"
    if [[ -n "$2" ]]; then
        ENV_FILE="$2"
    fi
elif [[ -n "$1" ]]; then
    ENV_FILE="$1"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] AirTracker Unraid Runner"
echo "[$(date '+%Y-%m-%d %H:%M:%S')]   Mode: $RUN_MODE"
echo "[$(date '+%Y-%m-%d %H:%M:%S')]   Config: $ENV_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S')]   Root: $AIRTRACKER_ROOT"
echo ""

# Check if we're in a virtual environment
if [[ -n "$VIRTUAL_ENV" ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✓ Using virtual environment: $VIRTUAL_ENV"
elif [[ -f "$AIRTRACKER_ROOT/venv/bin/activate" ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✓ Activating virtual environment: $AIRTRACKER_ROOT/venv"
    source "$AIRTRACKER_ROOT/venv/bin/activate"
elif [[ -f "$AIRTRACKER_ROOT/.venv/bin/activate" ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✓ Activating virtual environment: $AIRTRACKER_ROOT/.venv"
    source "$AIRTRACKER_ROOT/.venv/bin/activate"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠ No virtual environment found - using system Python"
fi

# Check Python dependencies
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Checking Python dependencies..."
python3 -c "import paho.mqtt.client, requests, pandas" 2>/dev/null && echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✓ Dependencies OK" || {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ Missing dependencies. Install with:"
    echo "   pip install paho-mqtt requests pandas openpyxl"
    exit 1
}

# Check required files
REQUIRED_FILES=(
    "$AIRTRACKER_ROOT/mqtt/producer/publish_mqtt.sh"
    "$AIRTRACKER_ROOT/mqtt/producer/mqtt_publish.py"
    "$AIRTRACKER_ROOT/mqtt/producer/plane_retreiver.py"
    "$AIRTRACKER_ROOT/mqtt/producer/plane_merge.py"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [[ ! -f "$file" ]]; then
        echo "❌ Missing required file: $file"
        exit 1
    fi
done
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✓ All required files present"

# Check config file
if [[ ! -f "$ENV_FILE" ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ Config file not found: $ENV_FILE"
    echo "Create it from .env.example or specify a different path"
    exit 1
fi
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✓ Config file found: $ENV_FILE"

# Set environment variables based on run mode
if [[ "$RUN_MODE" == "once" ]]; then
    export RUN_ONCE=1
else
    export RUN_ONCE=0
fi

export ENV_FILE="$ENV_FILE"

# Random delay for RUN_ONCE mode to avoid API rate limiting
if [[ "$RUN_MODE" == "once" ]]; then
    DELAY=$((RANDOM % 31))  # 0-30 seconds
    echo ""
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⏱ Random delay: ${DELAY} seconds (to avoid API rate limits)"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting AirTracker in ${DELAY} seconds..."
    sleep $DELAY
else
    echo ""
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting AirTracker immediately..."
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] ----------------------------------------"

# Change to AirTracker root and run
cd "$AIRTRACKER_ROOT"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Executing: bash mqtt/producer/publish_mqtt.sh"
bash mqtt/producer/publish_mqtt.sh