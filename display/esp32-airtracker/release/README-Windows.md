**Windows Flash Guide (ESP32-C3, Single Image)**
- Target board: `esp32-c3-devkitm-1` (Arduino framework)
- Image type: single merged image (`factory.bin`) at offset `0x0`

**What’s Included**
- `factory.bin` — single image you can flash at `0x0`
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

**Important**
- This binary contains the Wi‑Fi and MQTT settings that were compiled at build time. To change them, update `display/esp32-airtracker/include/config.h` and rebuild.

**Troubleshooting**
- Stuck at connecting: verify Wi‑Fi credentials and 2.4GHz network.
- No MQTT data: confirm broker settings and that `airtracker/nearest` is published (retained).
- Wrong board/pins: this image targets `esp32-c3-devkitm-1` with ILI9341 pins as documented in the repo.

