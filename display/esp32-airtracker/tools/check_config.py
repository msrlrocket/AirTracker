Import("env")

from pathlib import Path

proj = Path(env["PROJECT_DIR"]) / "display" / "esp32-airtracker"
inc = proj / "include"
dst = inc / "config.h"
src = inc / "config.example.h"

if not dst.exists():
    try:
        inc.mkdir(parents=True, exist_ok=True)
        if src.exists():
            dst.write_bytes(src.read_bytes())
            print("[pre] Created include/config.h from config.example.h — update Wi-Fi/MQTT before flashing.")
        else:
            # Create a minimal placeholder if example is missing
            dst.write_text(
                """
// Auto-generated placeholder. Fill in Wi-Fi and MQTT before flashing.
#pragma once
#ifndef WIFI_SSID
#define WIFI_SSID "YourSSID"
#endif
#ifndef WIFI_PASS
#define WIFI_PASS "YourPassword"
#endif
#ifndef MQTT_HOST
#define MQTT_HOST "192.168.1.10"
#endif
#ifndef MQTT_PORT
#define MQTT_PORT 1883
#endif
#ifndef MQTT_USER
#define MQTT_USER "mqtt"
#endif
#ifndef MQTT_PASS
#define MQTT_PASS "changeme"
#endif
#ifndef MQTT_PREFIX
#define MQTT_PREFIX "airtracker"
#endif
                """.strip()
            )
            print("[pre] Created include/config.h placeholder — update Wi-Fi/MQTT before flashing.")
    except Exception as e:
        print(f"[pre] Warning: could not create include/config.h: {e}")
