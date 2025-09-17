#include <Arduino.h>
#if defined(ARDUINO_USB_CDC_ON_BOOT)
#include <USB.h>
#endif
#include <WiFi.h>
#include <PubSubClient.h>
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>
#include <ArduinoJson.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <SPIFFS.h>
#include <FS.h>
#include <TJpg_Decoder.h>
#include <time.h>
#include <math.h>
#include "config.h"

// SPI + TFT (ILI9341)
Adafruit_ILI9341 tft = Adafruit_ILI9341(&SPI, TFT_CS, TFT_DC, TFT_RST);

// WiFi/MQTT
WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

// UI state and data model
struct FlightData {
  String route_origin = "SEA";
  String route_destination = "SFO";
  float distance_remaining_km = 412.0f;
  String eta_local_hhmm = "--:--";

  String airline_name = "";
  String aircraft_name = "";
  String callsign = "";

  int souls_on_board = 0;
  float distance_now_km = 0.0f;
  String direction_cardinal = "";
  int ground_speed_kmh = 0;
  int altitude_ft = 0;
  int vertical_rate_fpm = 0;

  // Radar
  int radar_bearing_deg = 0;
  float radar_range_km = 0.0f;
  int radar_rel_vertical_fpm = 0;
  int radar_gs_kmh = 0;
  int radar_heading_deg = 0;
  float radar_center_lat = 0.0f;
  float radar_center_lon = 0.0f;
  int radar_range_scale_km = 10;

  // Media URLs
  String airline_logo_url;
  String plane_image_url;
  // Cached local paths in SPIFFS
  String airline_logo_path;
  String plane_image_path;
} g;

// Single screen (overview only)
volatile bool invalidate = true;

// Minimal asset fetch state
static bool fetching_logo = false;
static bool fetching_plane = false;
static String last_logo_url;
static String last_plane_url;

// Select debug stream: always use Serial. On ESP32, Serial maps to USB CDC when enabled.
#define DBG Serial

// TJpg_Decoder callback to push decoded blocks to the display
static bool tft_output(int16_t x, int16_t y, uint16_t w, uint16_t h, uint16_t* bitmap) {
  if (y >= tft.height() || x >= tft.width()) return false;
  // Clip right/bottom overflows
  if (x + w > tft.width()) w = tft.width() - x;
  if (y + h > tft.height()) h = tft.height() - y;
  tft.startWrite();
  tft.setAddrWindow(x, y, w, h);
  // Adafruit_SPITFT no longer has pushColors; use writePixels
  tft.writePixels(bitmap, (uint32_t)w * h, true);
  tft.endWrite();
  return true;
}

// Fetch a URL into SPIFFS file path; returns true on success
static bool saveUrlToFile(const String& url, const char* path, size_t max_bytes = 200*1024) {
  if (url.length() == 0) return false;
  WiFiClient *baseClient = nullptr;
  WiFiClientSecure *tls = nullptr;
  bool is_https = url.startsWith("https://");
  if (is_https) {
    tls = new WiFiClientSecure();
    tls->setInsecure();
    baseClient = tls;
  } else {
    baseClient = new WiFiClient();
  }

  HTTPClient http;
  bool ok = false;
  if (http.begin(*baseClient, url)) {
    int code = http.GET();
    if (code == HTTP_CODE_OK) {
      int len = http.getSize();
      if (len <= 0 || (size_t)len > max_bytes) len = (int)max_bytes; // guard
      File f = SPIFFS.open(path, FILE_WRITE);
      if (f) {
        WiFiClient *stream = http.getStreamPtr();
        uint8_t buf[1024];
        int remaining = len;
        while (http.connected() && (remaining > 0 || len == -1)) {
          size_t avail = stream->available();
          if (avail) {
            int to_read = avail > sizeof(buf) ? sizeof(buf) : avail;
            if (len > 0 && to_read > remaining) to_read = remaining;
            int r = stream->readBytes(buf, to_read);
            if (r <= 0) break;
            f.write(buf, r);
            if (len > 0) remaining -= r;
          } else {
            delay(10);
          }
        }
        f.close();
        ok = true;
      }
    }
    http.end();
  }
  delete baseClient; // also deletes tls
  return ok;
}

// Draw a JPEG file from SPIFFS centered inside a box
static bool drawJpegFileBox(const char* path, int x, int y, int w, int h) {
  if (!SPIFFS.exists(path)) return false;
  File f = SPIFFS.open(path, FILE_READ);
  if (!f) return false;
  size_t size = f.size();
  if (size == 0 || size > 250*1024) { f.close(); return false; }
  uint8_t* buf = (uint8_t*) malloc(size);
  if (!buf) { f.close(); return false; }
  size_t rd = f.read(buf, size);
  f.close();
  if (rd != size) { free(buf); return false; }
  uint16_t iw = 0, ih = 0;
  if (!TJpgDec.getJpgSize(&iw, &ih, buf, size)) { free(buf); return false; }
  uint8_t scale = 1;
  while ((iw / (scale*2) > (uint16_t)w) || (ih / (scale*2) > (uint16_t)h)) scale *= 2;
  if (scale > 8) scale = 8;
  TJpgDec.setJpgScale(scale);
  int rw = iw / scale;
  int rh = ih / scale;
  int ox = x + (w - rw) / 2;
  int oy = y + (h - rh) / 2;
  bool ok = TJpgDec.drawJpg(ox, oy, buf, size);
  free(buf);
  return ok;
}

// No hardware buttons while focusing on one screen

// Time sync flag
volatile bool timeReady = false;

// Helpers
static inline String ellipsize(const String &s, size_t n) {
  if (s.length() <= n) return s;
  if (n == 0) return "";
  return s.substring(0, n - 1) + "\xE2\x80\xA6"; // …
}

static inline String fmtInt(int v) {
  char buf[16];
  snprintf(buf, sizeof(buf), "%d", v);
  return String(buf);
}

static inline String fmtIntComma(int v) {
  char raw[24];
  snprintf(raw, sizeof(raw), "%d", v);
  String s(raw);
  bool neg = false;
  if (s.length() && s[0] == '-') { neg = true; s.remove(0,1); }
  String out;
  int n = s.length();
  for (int i = 0; i < n; ++i) {
    out += s[i];
    int rem = n - i - 1;
    if (rem > 0 && rem % 3 == 0) out += ',';
  }
  if (neg) out = String('-') + out;
  return out;
}

static inline void drawHeader(const String &left, const String &right) {
  // Draw header snug to the top corners with small margin
  const int margin = 4;
  tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
  tft.setTextSize(1);
  tft.setCursor(margin, margin);
  tft.print(left);

  int16_t x1, y1; uint16_t w, h;
  tft.getTextBounds(right, 0, 0, &x1, &y1, &w, &h);
  tft.setCursor(tft.width() - margin - w, margin);
  tft.print(right);
}

static inline const char* bearingToCardinal(int deg) {
  static const char* dirs[8] = {"N","NE","E","SE","S","SW","W","NW"};
  int idx = ((deg % 360) + 360) % 360;
  idx = (int) floor((idx + 22.5) / 45.0) % 8;
  return dirs[idx];
}

static inline void drawOverview() {
  tft.fillScreen(ILI9341_BLACK);
  // Header
  String dest = g.route_destination.length() ? g.route_destination : String("Unknown");
  String route = g.route_origin + " -> " + dest; // ASCII arrow for reliability
  char right[48];
  snprintf(right, sizeof(right), "%.0f km | ETA %s", g.distance_remaining_km, g.eta_local_hhmm.c_str());
  drawHeader(route, right);

  // Center block — aircraft — airline — callsign
  // Airline logo area (64x64) — no decorative box
  if (g.airline_logo_path.length() && SPIFFS.exists(g.airline_logo_path)) {
    drawJpegFileBox(g.airline_logo_path.c_str(), 8, 52, 64, 64);
  } else {
    // Fallback: Unknown label
    tft.setTextSize(1);
    tft.setTextColor(ILI9341_LIGHTGREY, ILI9341_BLACK);
    int16_t x1,y1; uint16_t w,h; tft.getTextBounds("Unknown", 0, 0, &x1, &y1, &w, &h);
    tft.setCursor(8 + (64 - w)/2, 52 + (64 - h)/2);
    tft.print("Unknown");
  }
  tft.setTextSize(1);
  tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
  tft.setCursor(80, 56);
  String line1 = g.aircraft_name.length() ? (g.aircraft_name + " — " + g.airline_name) : g.airline_name;
  tft.print(ellipsize(line1, 26));
  if (g.callsign.length()) {
    tft.setCursor(80, 82);
    tft.setTextColor(ILI9341_LIGHTGREY, ILI9341_BLACK);
    tft.print("Callsign: "); tft.print(g.callsign);
  }
  // Plane photo area (80x64) — no decorative box
  if (g.plane_image_path.length() && SPIFFS.exists(g.plane_image_path)) {
    drawJpegFileBox(g.plane_image_path.c_str(), 232, 56, 80, 64);
  }

  // No soft RADAR label

  // Bottom bars (anchor to corners, no boxes)
  const int margin = 4;
  // Left: distance now / dir / GS
  tft.setTextSize(1);
  tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
  char left[64];
  snprintf(left, sizeof(left), "%.1f km - %s | %d km/h", g.distance_now_km, g.direction_cardinal.c_str(), g.ground_speed_kmh);
  int16_t x1, y1; uint16_t w, h;
  tft.getTextBounds(left, 0, 0, &x1, &y1, &w, &h);
  tft.setCursor(margin, tft.height() - margin - h);
  tft.print(left);

  // Middle: souls (no box, smaller font)
  tft.setTextSize(1);
  tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
  String souls = fmtInt(g.souls_on_board);
  tft.getTextBounds(souls, 0, 0, &x1, &y1, &w, &h);
  tft.setCursor((tft.width() - w)/2, tft.height() - margin - h);
  tft.print(souls);

  // Right: altitude / vertical
  tft.setTextSize(1);
  tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
  char arrow = g.vertical_rate_fpm > 0 ? '^' : (g.vertical_rate_fpm < 0 ? 'v' : ' ');
  int vmag = g.vertical_rate_fpm >= 0 ? g.vertical_rate_fpm : -g.vertical_rate_fpm;
  char right2[64];
  String alt = fmtIntComma(g.altitude_ft);
  String vvs = fmtIntComma(vmag);
  snprintf(right2, sizeof(right2), "%s ft  %c +%s fpm", alt.c_str(), arrow, vvs.c_str());
  tft.getTextBounds(right2, 0, 0, &x1, &y1, &w, &h);
  tft.setCursor(tft.width() - margin - w, tft.height() - margin - h);
  tft.print(right2);
}

// Gallery and Radar screens removed

static void draw() {
  drawOverview();
  invalidate = false;
}

// MQTT callback
static void onMqtt(char* topic, byte* payload, unsigned int length) {
  // Expect MQTT_TOPIC_NEAREST
  StaticJsonDocument<4096> doc;
  DeserializationError err = deserializeJson(doc, payload, length);
  if (err) {
    DBG.print("JSON parse error: "); DBG.println(err.f_str());
    return;
  }
  JsonObject x = doc.as<JsonObject>();

  auto strIf = [&](const char* key, String &ref) {
    if (x.containsKey(key)) {
      const char* s = x[key];
      ref = (s ? String(s) : String(""));
    }
  };

  strIf("origin_iata", g.route_origin);
  strIf("destination_iata", g.route_destination);
  strIf("callsign", g.callsign);

  if (x.containsKey("distance_nm")) g.distance_now_km = x["distance_nm"].as<float>() * 1.852f;
  if (x.containsKey("remaining_nm")) g.distance_remaining_km = x["remaining_nm"].as<float>() * 1.852f;
  if (x.containsKey("ground_speed_kt")) g.ground_speed_kmh = (int) lroundf(x["ground_speed_kt"].as<float>() * 1.852f);
  if (x.containsKey("altitude_ft")) g.altitude_ft = x["altitude_ft"].as<int>();
  if (x.containsKey("vertical_rate_fpm")) g.vertical_rate_fpm = x["vertical_rate_fpm"].as<int>();
  if (x.containsKey("bearing_deg")) {
    int b = x["bearing_deg"].as<int>();
    g.direction_cardinal = String(bearingToCardinal(b));
    g.radar_bearing_deg = b;
  }
  if (x.containsKey("lookups")) {
    JsonObject lk = x["lookups"].as<JsonObject>();
    if (!lk.isNull()) {
      if (lk.containsKey("airline")) {
        JsonObject al = lk["airline"].as<JsonObject>();
        if (al.containsKey("name")) g.airline_name = String(al["name"].as<const char*>());
        if (x.containsKey("airline_logo_url")) {
          const char* url = x["airline_logo_url"].as<const char*>();
          g.airline_logo_url = url ? String(url) : String("");
          if (g.airline_logo_url.length() == 0) { g.airline_logo_path = ""; last_logo_url = ""; }
        } else if (al.containsKey("logo_url")) {
          const char* url = al["logo_url"].as<const char*>();
          g.airline_logo_url = url ? String(url) : String("");
          if (g.airline_logo_url.length() == 0) { g.airline_logo_path = ""; last_logo_url = ""; }
        }
      }
      if (lk.containsKey("aircraft")) {
        JsonObject ac = lk["aircraft"].as<JsonObject>();
        if (ac.containsKey("name")) g.aircraft_name = String(ac["name"].as<const char*>());
        if (ac.containsKey("seats_max") && !x.containsKey("souls_on_board")) {
          g.souls_on_board = ac["seats_max"].as<int>();
        }
      }
    }
  }
  if (x.containsKey("souls_on_board")) g.souls_on_board = x["souls_on_board"].as<int>();
  else if (x.containsKey("souls_on_board_max")) g.souls_on_board = x["souls_on_board_max"].as<int>();

  if (x.containsKey("eta_min")) {
    float mins = x["eta_min"].as<float>();
    time_t now;
    time(&now);
    if (now > 0) {
      now += (time_t) lroundf(mins * 60.0f);
      struct tm local_tm = {};
      localtime_r(&now, &local_tm);
      char buf[6];
      snprintf(buf, sizeof(buf), "%02d:%02d", local_tm.tm_hour, local_tm.tm_min);
      g.eta_local_hhmm = String(buf);
    } else {
      g.eta_local_hhmm = String("--:--");
    }
  } else {
    // Clear stale ETA when not provided
    g.eta_local_hhmm = String("--:--");
  }

  if (x.containsKey("distance_nm")) g.radar_range_km = x["distance_nm"].as<float>() * 1.852f;
  if (x.containsKey("vertical_rate_fpm")) g.radar_rel_vertical_fpm = x["vertical_rate_fpm"].as<int>();
  if (x.containsKey("ground_speed_kt")) g.radar_gs_kmh = (int) lroundf(x["ground_speed_kt"].as<float>() * 1.852f);
  if (x.containsKey("track_deg")) g.radar_heading_deg = x["track_deg"].as<int>();
  if (x.containsKey("latitude")) g.radar_center_lat = x["latitude"].as<float>();
  if (x.containsKey("longitude")) g.radar_center_lon = x["longitude"].as<float>();

  // Media (plane image + thumbnails)
  if (x.containsKey("media")) {
    JsonObject m = x["media"].as<JsonObject>();
    if (m.containsKey("plane_image")) {
      const char* u = m["plane_image"].as<const char*>();
      if (u && strlen(u) > 0) g.plane_image_url = String(u);
    }
    if (!g.plane_image_url.length() && m.containsKey("thumbnails")) {
      JsonArray th = m["thumbnails"].as<JsonArray>();
      if (!th.isNull() && th.size() > 0) {
        const char* u = th[0].as<const char*>();
        if (u) g.plane_image_url = String(u);
      }
    }
    if (g.plane_image_url.length() == 0) { g.plane_image_path = ""; last_plane_url = ""; }
  }

  invalidate = true;
}

static void ensureMqtt() {
  if (mqtt.connected()) return;
  String clientId = String("airtracker-") + String((uint32_t)ESP.getEfuseMac(), HEX);
    DBG.print("MQTT connecting as "); DBG.println(clientId);
  if (mqtt.connect(clientId.c_str(), MQTT_USER, MQTT_PASS)) {
    DBG.println("MQTT connected");
    mqtt.subscribe(MQTT_TOPIC_NEAREST);
    DBG.print("Subscribed to "); DBG.println(MQTT_TOPIC_NEAREST);
  }
}

static void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  DBG.printf("Connecting to WiFi SSID '%s'...\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) {
    delay(250);
    DBG.print(".");
  }
  DBG.println();
  if (WiFi.status() == WL_CONNECTED) {
    DBG.print("WiFi connected. IP: "); DBG.println(WiFi.localIP());
  } else {
    DBG.println("WiFi connection failed.");
  }
}

static void syncTimeOnce() {
  if (timeReady) return;
  configTzTime(WIFI_TZ, "pool.ntp.org", "time.nist.gov");
  for (int i = 0; i < 20; i++) {
    time_t now; time(&now);
    if (now > 100000) { timeReady = true; break; }
    delay(250);
  }
  DBG.printf("Time sync: %s\n", timeReady ? "OK" : "not ready");
}

// No button init or polling

void setup() {
  DBG.begin(115200);
  delay(50);
  DBG.println("\nAirTracker ESP32 starting");

  // SPI and TFT
  SPI.begin(TFT_SCLK, TFT_MISO, TFT_MOSI, TFT_CS);
  tft.begin();
  SPI.setFrequency(TFT_SPI_FREQ);
  tft.setRotation(TFT_ROTATION);
  tft.fillScreen(ILI9341_BLACK);
  tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
  tft.setTextSize(1);
  tft.setCursor(8, 8);
  tft.print("Connecting WiFi…");

  // JPEG decoder callback
  TJpgDec.setCallback(tft_output);

  // SPIFFS for cached JPEGs
  if (!SPIFFS.begin(true)) {
    DBG.println("SPIFFS mount failed");
  }

  // WiFi + time
  connectWiFi();
  syncTimeOnce();

  // MQTT
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(onMqtt);

  // No buttons to initialize

  // Initial screen
  tft.fillScreen(ILI9341_BLACK);
  tft.setCursor(8, 8);
  tft.print("Waiting for nearest on ");
  tft.print(MQTT_TOPIC_NEAREST);
}

unsigned long lastUi = 0;
void loop() {
  // Network upkeep
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  ensureMqtt();
  mqtt.loop();

  // No buttons to poll

  // Opportunistically fetch media assets when URLs change
  if (!fetching_logo && g.airline_logo_url.length() && g.airline_logo_url != last_logo_url) {
    fetching_logo = true;
    if (saveUrlToFile(g.airline_logo_url, "/logo.jpg", 180*1024)) {
      g.airline_logo_path = "/logo.jpg";
      last_logo_url = g.airline_logo_url;
      invalidate = true;
    }
    fetching_logo = false;
  }
  if (!fetching_plane && g.plane_image_url.length() && g.plane_image_url != last_plane_url) {
    fetching_plane = true;
    if (saveUrlToFile(g.plane_image_url, "/plane.jpg", 220*1024)) {
      g.plane_image_path = "/plane.jpg";
      last_plane_url = g.plane_image_url;
      invalidate = true;
    }
    fetching_plane = false;
  }

  // UI draw at ~10 fps when invalidated, else once a second keep-alive
  unsigned long now = millis();
  if (invalidate || now - lastUi > 1000) {
    draw();
    lastUi = now;
  }

  delay(10);
}
