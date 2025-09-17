#include <Arduino.h>
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>

// Pin definitions matching working ESPHome configuration
#define TFT_CS      7
#define TFT_DC      10
#define TFT_RST     1
#define TFT_MISO    5   // SDO
#define TFT_MOSI    6   // SDI
#define TFT_SCLK    4   // CLK

// Create display instance with exact ESPHome pins
Adafruit_ILI9341 tft = Adafruit_ILI9341(TFT_CS, TFT_DC, TFT_MOSI, TFT_SCLK, TFT_RST, TFT_MISO);

void setup() {
  Serial.begin(115200);

  Serial.println("=== ESP32-C3 AirTracker Display Test ===");
  Serial.printf("ESPHome pins: CLK=%d, MISO=%d, MOSI=%d, CS=%d, DC=%d, RST=%d\n",
                TFT_SCLK, TFT_MISO, TFT_MOSI, TFT_CS, TFT_DC, TFT_RST);

  // Initialize display with exact ESPHome settings
  tft.begin(40000000);  // 40MHz like ESPHome

  Serial.println("ILI9341 initialized");

  // Set rotation to match ESPHome (0 = portrait)
  tft.setRotation(0);

  // Draw ESPHome P1 color bars test pattern
  drawColorBars();

  Serial.println("Setup complete - display should show color bars!");
}

void drawColorBars() {
  Serial.println("Drawing ESPHome P1 color bars...");

  const int w = 240;  // Portrait width
  const int h = 320;  // Portrait height
  const int bar = w / 6;  // ~40px per bar

  // Fill screen black first
  tft.fillScreen(ILI9341_BLACK);

  // Draw color bars exactly like ESPHome P1
  tft.fillRect(0*bar, 0, bar, h, ILI9341_RED);
  tft.fillRect(1*bar, 0, bar, h, ILI9341_GREEN);
  tft.fillRect(2*bar, 0, bar, h, ILI9341_BLUE);
  tft.fillRect(3*bar, 0, bar, h, ILI9341_YELLOW);
  tft.fillRect(4*bar, 0, bar, h, ILI9341_CYAN);
  tft.fillRect(5*bar, 0, w-5*bar, h, ILI9341_MAGENTA);

  Serial.println("Color bars complete!");
}

void drawCheckerboard() {
  Serial.println("Drawing checkerboard...");

  // Simple checkerboard pattern
  for (int y = 0; y < 320; y += 20) {
    for (int x = 0; x < 240; x += 20) {
      uint16_t color = ((x/20 + y/20) & 1) ? ILI9341_WHITE : ILI9341_BLACK;
      tft.fillRect(x, y, 20, 20, color);
    }
  }
}

void loop() {
  static int pattern = 0;
  static unsigned long lastChange = 0;

  if (millis() - lastChange > 5000) {  // 5 second cycle
    switch (pattern) {
      case 0:
        drawCheckerboard();
        break;

      case 1:
        drawColorBars();
        break;
    }

    pattern = (pattern + 1) % 2;
    lastChange = millis();
  }
}