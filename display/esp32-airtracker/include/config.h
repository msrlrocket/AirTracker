// AirTracker ESP32 firmware configuration
// Uses office-airplane-tracker.yaml pinout and .env MQTT defaults.

#pragma once

// ---- WiFi ----
#ifndef WIFI_SSID
#define WIFI_SSID "Verizon 5G Tower"
#endif
#ifndef WIFI_PASS
#define WIFI_PASS "2088201236"
#endif

// ---- Timezone (for ETA local time). Use TZ database rules or "UTC" ----
#ifndef WIFI_TZ
// Example US Pacific: "PST8PDT,M3.2.0/2,M11.1.0/2"
#define WIFI_TZ "UTC"
#endif

// ---- MQTT (.env defaults) ----
#ifndef MQTT_HOST
#define MQTT_HOST "192.168.2.244"
#endif
#ifndef MQTT_PORT
#define MQTT_PORT 1883
#endif
#ifndef MQTT_USER
#define MQTT_USER "mqtt"
#endif
#ifndef MQTT_PASS
#define MQTT_PASS "Tannerman1!1"
#endif
#ifndef MQTT_PREFIX
#define MQTT_PREFIX "airtracker"
#endif

#ifndef MQTT_TOPIC_NEAREST
#define MQTT_TOPIC_NEAREST MQTT_PREFIX "/nearest"
#endif

// ---- Hardware pins (ESP32-C3 DevKitM-1 from YAML) ----
// SPI for ILI9341
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

// Optional buttons (INPUT_PULLUP, active LOW)
#ifndef BTN_A_PIN
#define BTN_A_PIN 2   // screen 2
#endif
#ifndef BTN_B_PIN
#define BTN_B_PIN 3   // screen 3
#endif
#ifndef BTN_BACK_PIN
#define BTN_BACK_PIN 20 // cycle screens
#endif

// ---- Display tuning ----
#ifndef TFT_ROTATION
#define TFT_ROTATION 1 // 0=portrait, 1=landscape
#endif

#ifndef TFT_SPI_FREQ
#define TFT_SPI_FREQ 40000000 // 40 MHz
#endif

