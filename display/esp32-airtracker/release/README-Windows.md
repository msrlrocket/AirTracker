**AirTracker ESP32 Firmware v2.0 (Windows Flash Guide)**
- Target board: `esp32-c3-devkitm-1` (Arduino framework)
- Image type: single merged image (`factory.bin`) at offset `0x0`
- **NEW**: Real-time airline logo and aircraft photo display via HTTP/HTTPS
- **NEW**: TJpg_Decoder library for JPEG image support
- **NEW**: Enhanced aircraft data processing with image URLs

**What's Included**
- `factory.bin` — single firmware image with image loading support (1.06MB)
- `flash_factory.bat` — helper to flash `factory.bin`
- `erase_flash.bat` — optional full chip erase
- `SHA256.txt` — checksum of `factory.bin` for verification

**Prerequisites**
- Windows 10/11
- Python 3.9+ (Windows Store or python.org)
- Install esptool (one-time): `py -3 -m pip install --user esptool`
- Optional USB drivers (if needed for your board): CP210x or CH340

**Find Your COM Port**
- Plug the ESP32-C3 in. Open Device Manager → Ports (COM & LPT) → note the `COM#` (e.g., `COM5`).

**Enter Bootloader Mode (if needed)**
- Hold BOOT, press RESET, release RESET, then release BOOT.

**Flash (Recommended: use the .bat)**
- Open Command Prompt in this folder, then run:
  - `flash_factory.bat COM5 921600`
  - If flashing is unstable, try: `flash_factory.bat COM5 460800`

**Flash (Manual esptool command)**
- `esptool.py --chip esp32c3 --port COM5 --baud 921600 write_flash 0x0 factory.bin`

**Optional: Erase Flash First**
- `erase_flash.bat COM5`  (or)  `esptool.py --chip esp32c3 --port COM5 erase_flash`

**After Flashing**
- Press RESET. The device boots the new firmware.
- For logs: use PuTTY or `py -3 -m serial.tools.miniterm COM5 115200` (install `pyserial` if prompted).
- **NEW**: Watch for image loading messages like "Downloaded airline logo" in the serial output.

**New Features in v2.0**
- **Real-time Image Loading**: Automatically downloads and displays airline logos and aircraft photos
- **JPEG Support**: Full JPEG decoding using TJpg_Decoder library
- **HTTP/HTTPS Downloads**: Fetches images from aviation databases and photo sites
- **Smart Caching**: Images are cached to reduce bandwidth usage
- **Visual Enhancements**: Rich display with actual airline branding and aircraft photos

**Important**
- This binary contains the Wi‑Fi and MQTT settings that were compiled at build time. To change them, update `display/esp32-airtracker/include/config.h` and rebuild.
- **Internet connection required** for image downloading. Device must have internet access via Wi-Fi.
- Image downloads use HTTPS and may take a few seconds for large aircraft photos.

**Troubleshooting**
- Stuck at connecting: verify Wi‑Fi credentials and 2.4GHz network.
- No MQTT data: confirm broker settings and that `airtracker/nearest` is published (retained).
- No images loading: check internet connectivity and monitor serial output for HTTP errors.
- Images appear black: JPEG decoder may need more memory - restart device if needed.
- Wrong board/pins: this image targets `esp32-c3-devkitm-1` with ILI9341 pins as documented in the repo.

