// AirTracker ESP32 firmware configuration (example)
// Copy this file to include/config.h and fill in your values.

#pragma once

// ---- WiFi ----
#ifndef WIFI_SSID
#define WIFI_SSID "YourSSID"
#endif
#ifndef WIFI_PASS
#define WIFI_PASS "YourPassword"
#endif

// ---- Timezone ----
#ifndef WIFI_TZ
#define WIFI_TZ "UTC"
#endif

// ---- MQTT ----
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

// ---- Pins (ESP32-C3 DevKitM-1 defaults) ----
#ifndef TFT_SCLK
#define TFT_SCLK 4
#endif
#ifndef TFT_MOSI
#define TFT_MOSI 6
#endif
#ifndef TFT_MISO
#define TFT_MISO 5
#endif
#ifndef TFT_CS
#define TFT_CS 7
#endif
#ifndef TFT_DC
#define TFT_DC 10
#endif
#ifndef TFT_RST
#define TFT_RST 1
#endif

#ifndef BTN_A_PIN
#define BTN_A_PIN 2
#endif
#ifndef BTN_B_PIN
#define BTN_B_PIN 3
#endif
#ifndef BTN_BACK_PIN
#define BTN_BACK_PIN 20
#endif

#ifndef TFT_ROTATION
#define TFT_ROTATION 1
#endif
#ifndef TFT_SPI_FREQ
#define TFT_SPI_FREQ 40000000
#endif
