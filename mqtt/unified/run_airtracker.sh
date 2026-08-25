#!/bin/bash
# AirTracker Unraid Runner Script (Unified Edition)
#
# This script handles Python virtual environment activation and runs the unified AirTracker
#
# Usage:
#   ./run_airtracker.sh                           # Run once with default .env
#   ./run_airtracker.sh continuous               # Run continuously
#   ./run_airtracker.sh /path/to/.env            # Run once with custom .env
#   ./run_airtracker.sh --env-file /path/to/.env # Run once with custom .env (alternative syntax)
#   ./run_airtracker.sh continuous /path/to/.env # Run continuously with custom .env
#   ./run_airtracker.sh continuous --env-file /path/to/.env # Run continuously with custom .env (alternative syntax)

set -e  # Exit on any error

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AIRTRACKER_ROOT="$SCRIPT_DIR"

# Default values
RUN_MODE="once"
ENV_FILE="$AIRTRACKER_ROOT/.env"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        continuous)
            RUN_MODE="continuous"
            shift
            ;;
        --env-file)
            ENV_FILE="$2"
            shift 2
            ;;
        -*)
            echo "Unknown option: $1"
            echo "Usage: $0 [continuous] [--env-file /path/to/.env] [/path/to/.env]"
            exit 1
            ;;
        *)
            # If it's not an option and not 'continuous', treat as env file path
            if [[ "$1" != "continuous" ]]; then
                ENV_FILE="$1"
            fi
            shift
            ;;
    esac
done

echo "[$(date '+%Y-%m-%d %H:%M:%S')] AirTracker Unraid Runner (Unified Edition)"
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

# Check Python dependencies and install if missing
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Checking Python dependencies..."
MISSING_DEPS=0

# Check each dependency individually
python3 -c "import paho.mqtt.client" 2>/dev/null || MISSING_DEPS=1
python3 -c "import requests" 2>/dev/null || MISSING_DEPS=1
python3 -c "import pandas" 2>/dev/null || MISSING_DEPS=1
python3 -c "import dotenv" 2>/dev/null || MISSING_DEPS=1
python3 -c "import openpyxl" 2>/dev/null || MISSING_DEPS=1
python3 -c "import PIL" 2>/dev/null || MISSING_DEPS=1
python3 -c "import influxdb_client" 2>/dev/null || MISSING_DEPS=1

if [[ $MISSING_DEPS -eq 1 ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠ Missing dependencies detected. Installing..."
    pip install paho-mqtt requests pandas openpyxl python-dotenv Pillow influxdb-client

    # Verify installation succeeded
    python3 -c "import paho.mqtt.client, requests, pandas, dotenv, openpyxl, PIL, influxdb_client" 2>/dev/null && {
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ Dependencies installed successfully"
    } || {
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ Failed to install dependencies"
        exit 1
    }
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ All dependencies OK"
fi

# Check required files (updated for unified approach)
REQUIRED_FILES=(
    "$AIRTRACKER_ROOT/airtracker.py"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [[ ! -f "$file" ]]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ Missing required file: $file"
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

# Create data directory if it doesn't exist
mkdir -p "$AIRTRACKER_ROOT/data"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✓ Data directory ready: $AIRTRACKER_ROOT/data"

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

# Change to AirTracker root and run unified script
cd "$AIRTRACKER_ROOT"

# Build command arguments
ARGS=""
if [[ "$ENV_FILE" != "$AIRTRACKER_ROOT/.env" ]]; then
    ARGS="$ARGS --env-file \"$ENV_FILE\""
fi

if [[ "$RUN_MODE" == "continuous" ]]; then
    ARGS="$ARGS --continuous"
fi

# MQTT publishing controlled by .env file
# Remove the forced --mqtt-publish-all --mqtt-publish-commercial
# Let the .env configuration control MQTT behavior

# Execute the unified AirTracker script
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Executing: python3 airtracker.py$ARGS"
eval "python3 airtracker.py$ARGS"