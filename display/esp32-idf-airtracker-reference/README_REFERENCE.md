# ESP32-IDF AirTracker Reference Implementation

This directory contains the **working reference implementation** of the AirTracker ESP32 display using ESP-IDF framework.

## What This Contains

This is a **proven working implementation** that successfully:
- ✅ Displays horizontal (landscape) layout on ILI9341 320x240 TFT
- ✅ Shows color bars and AirTracker UI alternating every 3 seconds
- ✅ Uses custom 5x7 bitmap font for readable text
- ✅ Implements proper SPI communication with the display
- ✅ Stable operation without boot loops or freezing

## Key Technical Details

### Display Configuration
- **Orientation**: Landscape (320x240) via MADCTL register `0x20`
- **Driver**: ILI9341 SPI TFT display
- **Font**: Custom 5x7 bitmap font with proper character spacing

### Hardware Pins (ESP32-C3)
- **SPI MOSI**: GPIO 6
- **SPI CLK**: GPIO 7
- **TFT CS**: GPIO 10
- **TFT DC**: GPIO 2
- **TFT RST**: GPIO 3

### UI Layout
- **Header**: Blue banner with "AIRTRACKER ESP32-C3" title
- **Two-column design**: Aircraft info (left) and flight data (right)
- **Status bar**: Yellow status indicator
- **Additional info**: Radar data section at bottom

## Why This Implementation Works

1. **Simple, direct approach**: No complex LVGL integration that caused boot loops
2. **Custom display driver**: Direct SPI communication with proper timing
3. **Bitmap font rendering**: Reliable text display without external font libraries
4. **Horizontal layout**: Takes advantage of wider screen format (320x240)
5. **Stable task management**: Proper FreeRTOS task with split delays

## How to Use This Reference

To recreate this working implementation:

```bash
# Copy this reference to a new project
cp -r esp32-idf-airtracker-reference new-project-name

# Build and flash
cd new-project-name
. ~/esp-idf-v5.1.5/export.sh
idf.py build
idf.py -p /dev/cu.usbmodem1101 flash
```

## Key Files

- `main/main.c` - Complete working implementation
- `main/CMakeLists.txt` - Simple component registration
- `CMakeLists.txt` - Project configuration
- `sdkconfig.defaults` - ESP32-C3 target configuration

## Build Requirements

- ESP-IDF v5.1.5
- ESP32-C3 target
- Driver component only (no external dependencies)

---

**Created**: September 18, 2025
**Status**: Working reference implementation
**Purpose**: Preserve working code for future reference and expansion