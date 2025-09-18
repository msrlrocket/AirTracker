#include <stdio.h>
#include <string.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <driver/spi_master.h>
#include <driver/gpio.h>
#include <esp_log.h>

static const char* TAG = "AirTracker";

// ESPHome working pin configuration
#define TFT_SCLK    4
#define TFT_MISO    5
#define TFT_MOSI    6
#define TFT_CS      7
#define TFT_DC      10
#define TFT_RST     1

// ILI9341 commands
#define ILI9341_SWRESET    0x01
#define ILI9341_SLPOUT     0x11
#define ILI9341_DISPON     0x29
#define ILI9341_CASET      0x2A
#define ILI9341_PASET      0x2B
#define ILI9341_RAMWR      0x2C
#define ILI9341_MADCTL     0x36
#define ILI9341_COLMOD     0x3A

// Colors (16-bit RGB565)
#define COLOR_BLACK   0x0000
#define COLOR_RED     0xF800
#define COLOR_GREEN   0x07E0
#define COLOR_BLUE    0x001F
#define COLOR_YELLOW  0xFFE0
#define COLOR_CYAN    0x07FF
#define COLOR_MAGENTA 0xF81F
#define COLOR_WHITE   0xFFFF

static spi_device_handle_t spi;

void spi_write_cmd(uint8_t cmd) {
    spi_transaction_t trans;
    memset(&trans, 0, sizeof(trans));
    trans.length = 8;
    trans.tx_data[0] = cmd;
    trans.flags = SPI_TRANS_USE_TXDATA;

    gpio_set_level(TFT_DC, 0);
    ESP_ERROR_CHECK(spi_device_transmit(spi, &trans));
}

void spi_write_data(uint8_t data) {
    spi_transaction_t trans;
    memset(&trans, 0, sizeof(trans));
    trans.length = 8;
    trans.tx_data[0] = data;
    trans.flags = SPI_TRANS_USE_TXDATA;

    gpio_set_level(TFT_DC, 1);
    ESP_ERROR_CHECK(spi_device_transmit(spi, &trans));
}

void spi_write_data16(uint16_t data) {
    spi_transaction_t trans;
    memset(&trans, 0, sizeof(trans));
    trans.length = 16;
    trans.tx_data[0] = data >> 8;
    trans.tx_data[1] = data & 0xFF;
    trans.flags = SPI_TRANS_USE_TXDATA;

    gpio_set_level(TFT_DC, 1);
    ESP_ERROR_CHECK(spi_device_transmit(spi, &trans));
}

void ili9341_init(void) {
    ESP_LOGI(TAG, "Initializing ILI9341...");

    gpio_set_level(TFT_RST, 0);
    vTaskDelay(pdMS_TO_TICKS(20));
    gpio_set_level(TFT_RST, 1);
    vTaskDelay(pdMS_TO_TICKS(150));

    spi_write_cmd(ILI9341_SWRESET);
    vTaskDelay(pdMS_TO_TICKS(150));

    spi_write_cmd(ILI9341_SLPOUT);
    vTaskDelay(pdMS_TO_TICKS(500));

    spi_write_cmd(ILI9341_COLMOD);
    spi_write_data(0x55);

    spi_write_cmd(ILI9341_MADCTL);
    spi_write_data(0x20); // Landscape orientation

    spi_write_cmd(ILI9341_DISPON);
    vTaskDelay(pdMS_TO_TICKS(100));

    ESP_LOGI(TAG, "ILI9341 initialized");
}

void set_addr_window(uint16_t x0, uint16_t y0, uint16_t x1, uint16_t y1) {
    spi_write_cmd(ILI9341_CASET);
    spi_write_data16(x0);
    spi_write_data16(x1);

    spi_write_cmd(ILI9341_PASET);
    spi_write_data16(y0);
    spi_write_data16(y1);

    spi_write_cmd(ILI9341_RAMWR);
}

void fill_rect(uint16_t x, uint16_t y, uint16_t w, uint16_t h, uint16_t color) {
    set_addr_window(x, y, x + w - 1, y + h - 1);
    gpio_set_level(TFT_DC, 1);

    uint32_t pixel_count = (uint32_t)w * h;
    for (uint32_t i = 0; i < pixel_count; i++) {
        spi_write_data16(color);
    }
}

void draw_color_bars(void) {
    ESP_LOGI(TAG, "Drawing color bars...");

    const int w = 320;  // Landscape width
    const int h = 240;  // Landscape height
    const int bar = w / 6;

    fill_rect(0, 0, w, h, COLOR_BLACK);

    fill_rect(0*bar, 0, bar, h, COLOR_RED);
    fill_rect(1*bar, 0, bar, h, COLOR_GREEN);
    fill_rect(2*bar, 0, bar, h, COLOR_BLUE);
    fill_rect(3*bar, 0, bar, h, COLOR_YELLOW);
    fill_rect(4*bar, 0, bar, h, COLOR_CYAN);
    fill_rect(5*bar, 0, w-5*bar, h, COLOR_MAGENTA);

    ESP_LOGI(TAG, "Color bars complete!");
}

// Simple bitmap font patterns (5x7 pixels)
const uint8_t font_5x7[][7] = {
    // Space (32)
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    // ! (33)
    {0x04, 0x04, 0x04, 0x04, 0x00, 0x04, 0x00},
    // " (34)
    {0x0A, 0x0A, 0x0A, 0x00, 0x00, 0x00, 0x00},
    // # to , (35-44) - simplified
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}, {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}, {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}, {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}, {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}, {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    // - (45)
    {0x00, 0x00, 0x00, 0x0E, 0x00, 0x00, 0x00},
    // . (46)
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x04, 0x00},
    // / (47)
    {0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x00},
    // 0-9 (48-57)
    {0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E}, // 0
    {0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E}, // 1
    {0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F}, // 2
    {0x1F, 0x02, 0x04, 0x02, 0x01, 0x11, 0x0E}, // 3
    {0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02}, // 4
    {0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E}, // 5
    {0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E}, // 6
    {0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08}, // 7
    {0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E}, // 8
    {0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C}, // 9
    // : (58)
    {0x00, 0x04, 0x00, 0x00, 0x04, 0x00, 0x00},
    // ; to @ (59-64) - simplified
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}, {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}, {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}, {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    // A-Z (65-90)
    {0x0E, 0x11, 0x11, 0x11, 0x1F, 0x11, 0x11}, // A
    {0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E}, // B
    {0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E}, // C
    {0x1C, 0x12, 0x11, 0x11, 0x11, 0x12, 0x1C}, // D
    {0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F}, // E
    {0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10}, // F
    {0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0F}, // G
    {0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11}, // H
    {0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E}, // I
    {0x07, 0x02, 0x02, 0x02, 0x02, 0x12, 0x0C}, // J
    {0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11}, // K
    {0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F}, // L
    {0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11}, // M
    {0x11, 0x11, 0x19, 0x15, 0x13, 0x11, 0x11}, // N
    {0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E}, // O
    {0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10}, // P
    {0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D}, // Q
    {0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11}, // R
    {0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E}, // S
    {0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04}, // T
    {0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E}, // U
    {0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04}, // V
    {0x11, 0x11, 0x11, 0x15, 0x15, 0x1B, 0x11}, // W
    {0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11}, // X
    {0x11, 0x11, 0x11, 0x0A, 0x04, 0x04, 0x04}, // Y
    {0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F}, // Z
};

void draw_char(char c, uint16_t x, uint16_t y, uint16_t color, uint16_t bg_color) {
    if (c < 32 || c > 90) return; // Only support space to Z

    const uint8_t *bitmap = font_5x7[c - 32];

    for (int row = 0; row < 7; row++) {
        for (int col = 0; col < 5; col++) {
            if (bitmap[row] & (0x10 >> col)) {
                // Draw pixel
                fill_rect(x + col, y + row, 1, 1, color);
            } else {
                // Draw background pixel
                fill_rect(x + col, y + row, 1, 1, bg_color);
            }
        }
    }
}

void draw_text(const char* text, uint16_t x, uint16_t y, uint16_t color, uint16_t bg_color) {
    int len = strlen(text);
    for (int i = 0; i < len && i < 35; i++) { // Max 35 chars per line
        draw_char(text[i], x + i * 6, y, color, bg_color); // 6 pixel spacing for 5-pixel wide chars
    }
}

void draw_airtracker_ui(void) {
    ESP_LOGI(TAG, "Drawing AirTracker UI...");

    // Clear screen with dark background (landscape: 320x240)
    fill_rect(0, 0, 320, 240, COLOR_BLACK);

    // Header background
    fill_rect(0, 0, 320, 25, COLOR_BLUE);

    // Title
    draw_text("AIRTRACKER ESP32-C3", 10, 5, COLOR_WHITE, COLOR_BLUE);

    // Left column - Aircraft info
    fill_rect(5, 30, 150, 80, COLOR_BLUE);
    draw_text("AIRCRAFT INFO", 10, 35, COLOR_YELLOW, COLOR_BLUE);
    draw_text("REG: N734LQ", 10, 47, COLOR_WHITE, COLOR_BLUE);
    draw_text("TYPE: C172", 10, 59, COLOR_WHITE, COLOR_BLUE);
    draw_text("CALLSIGN: N734LQ", 10, 71, COLOR_WHITE, COLOR_BLUE);
    draw_text("ORIGIN: OLM", 10, 83, COLOR_WHITE, COLOR_BLUE);

    // Right column - Flight data
    fill_rect(165, 30, 150, 80, COLOR_GREEN);
    draw_text("FLIGHT DATA", 170, 35, COLOR_BLACK, COLOR_GREEN);
    draw_text("ALT: 3375 FT", 170, 47, COLOR_BLACK, COLOR_GREEN);
    draw_text("SPD: 122 KT", 170, 59, COLOR_BLACK, COLOR_GREEN);
    draw_text("HDG: 172 DEG", 170, 71, COLOR_BLACK, COLOR_GREEN);
    draw_text("DIST: 5.7 NM", 170, 83, COLOR_BLACK, COLOR_GREEN);

    // Bottom status section
    fill_rect(5, 120, 310, 20, COLOR_YELLOW);
    draw_text("STATUS: TRACKING", 10, 125, COLOR_BLACK, COLOR_YELLOW);

    // Additional info in remaining space
    fill_rect(5, 150, 310, 80, COLOR_CYAN);
    draw_text("RADAR DATA", 10, 155, COLOR_BLACK, COLOR_CYAN);
    draw_text("LAT: 46.088013", 10, 167, COLOR_BLACK, COLOR_CYAN);
    draw_text("LON: -122.675684", 10, 179, COLOR_BLACK, COLOR_CYAN);
    draw_text("SQUAWK: 3246", 10, 191, COLOR_BLACK, COLOR_CYAN);
    draw_text("VERTICAL RATE: -1856 FPM", 10, 203, COLOR_BLACK, COLOR_CYAN);

    ESP_LOGI(TAG, "AirTracker UI complete!");
}

void display_task(void *pvParameters) {
    int mode = 0;
    int counter = 0;

    while (1) {
        ESP_LOGI(TAG, "Display update cycle %d, mode %d", counter++, mode);

        // Clear any potential display issues
        vTaskDelay(pdMS_TO_TICKS(100));

        switch (mode) {
            case 0:
                ESP_LOGI(TAG, "Drawing color bars...");
                draw_color_bars();
                ESP_LOGI(TAG, "Color bars complete");
                break;

            case 1:
                ESP_LOGI(TAG, "Drawing AirTracker UI...");
                draw_airtracker_ui();
                ESP_LOGI(TAG, "AirTracker UI complete");
                break;
        }

        ESP_LOGI(TAG, "Display update finished, waiting 3 seconds...");
        mode = (mode + 1) % 2;

        // Shorter delay to reduce freezing, split into smaller chunks
        for (int i = 0; i < 30; i++) {
            vTaskDelay(pdMS_TO_TICKS(100)); // 100ms chunks for 3 seconds total
            if (i % 10 == 0) {
                ESP_LOGI(TAG, "Waiting... %d/30", i);
            }
        }

        ESP_LOGI(TAG, "Starting next display cycle...");
    }
}

void app_main(void) {
    ESP_LOGI(TAG, "=== ESP-IDF AirTracker Display ===");
    ESP_LOGI(TAG, "Pins: CLK=%d, MISO=%d, MOSI=%d, CS=%d, DC=%d, RST=%d",
             TFT_SCLK, TFT_MISO, TFT_MOSI, TFT_CS, TFT_DC, TFT_RST);

    // Configure GPIO pins
    gpio_config_t io_conf = {
        .intr_type = GPIO_INTR_DISABLE,
        .mode = GPIO_MODE_OUTPUT,
        .pin_bit_mask = (1ULL << TFT_DC) | (1ULL << TFT_RST),
        .pull_down_en = 0,
        .pull_up_en = 0,
    };
    ESP_ERROR_CHECK(gpio_config(&io_conf));

    gpio_set_level(TFT_CS, 1);

    // Configure SPI
    spi_bus_config_t buscfg = {
        .miso_io_num = TFT_MISO,
        .mosi_io_num = TFT_MOSI,
        .sclk_io_num = TFT_SCLK,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = 4096,
    };

    ESP_ERROR_CHECK(spi_bus_initialize(SPI2_HOST, &buscfg, SPI_DMA_CH_AUTO));

    spi_device_interface_config_t devcfg = {
        .clock_speed_hz = 40000000,
        .mode = 0,
        .spics_io_num = TFT_CS,
        .queue_size = 7,
    };

    ESP_ERROR_CHECK(spi_bus_add_device(SPI2_HOST, &devcfg, &spi));

    ESP_LOGI(TAG, "SPI configured: 40MHz, Mode 0");

    ili9341_init();
    draw_color_bars();

    xTaskCreate(display_task, "display_task", 8192, NULL, 5, NULL);

    ESP_LOGI(TAG, "Setup complete - display should show color bars!");
}