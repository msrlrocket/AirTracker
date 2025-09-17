#!/bin/bash

# ESP-IDF Build Script for AirTracker
echo "Setting up ESP-IDF environment..."

# Deactivate any virtual environment
if [[ "$VIRTUAL_ENV" != "" ]]; then
    echo "Deactivating virtual environment..."
    deactivate
fi

# Force use of system Python and ESP-IDF environment
export IDF_PATH=~/esp-idf-v5.1.5
export PATH=/Users/mattlindsay/.espressif/python_env/idf5.1_py3.9_env/bin:$PATH

. $IDF_PATH/export.sh

echo "Setting target to ESP32-C3..."
idf.py set-target esp32c3

echo "Building firmware..."
idf.py build

echo "Build complete! Flash with:"
echo ". ~/esp-idf-v5.1.5/export.sh && idf.py flash monitor"
echo ""
echo "Or use esptool directly:"
echo "esptool.py --chip esp32c3 --port /dev/cu.usbserial-* --baud 921600 write_flash --flash_mode dio --flash_freq 80m --flash_size 4MB 0x0 build/bootloader/bootloader.bin 0x10000 build/airtracker.bin 0x8000 build/partition_table/partition-table.bin"