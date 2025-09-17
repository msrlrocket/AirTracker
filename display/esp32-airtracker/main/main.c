#include <stdio.h>
#include <string.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <driver/spi_master.h>
#include <driver/gpio.h>
#include <esp_log.h>

static const char* TAG = "AirTracker";

// Pin definitions matching working ESPHome configuration
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
    esp_err_t ret;
    spi_transaction_t trans;
    memset(&trans, 0, sizeof(trans));
    trans.length = 8;
    trans.tx_data[0] = cmd;
    trans.flags = SPI_TRANS_USE_TXDATA;

    gpio_set_level(TFT_DC, 0);  // Command mode
    ret = spi_device_transmit(spi, &trans);
    assert(ret == ESP_OK);
}

void spi_write_data(uint8_t data) {
    esp_err_t ret;
    spi_transaction_t trans;
    memset(&trans, 0, sizeof(trans));
    trans.length = 8;
    trans.tx_data[0] = data;
    trans.flags = SPI_TRANS_USE_TXDATA;

    gpio_set_level(TFT_DC, 1);  // Data mode
    ret = spi_device_transmit(spi, &trans);
    assert(ret == ESP_OK);
}

void spi_write_data16(uint16_t data) {
    esp_err_t ret;
    spi_transaction_t trans;
    memset(&trans, 0, sizeof(trans));
    trans.length = 16;
    trans.tx_data[0] = data >> 8;
    trans.tx_data[1] = data & 0xFF;
    trans.flags = SPI_TRANS_USE_TXDATA;

    gpio_set_level(TFT_DC, 1);  // Data mode
    ret = spi_device_transmit(spi, &trans);
    assert(ret == ESP_OK);
}

void ili9341_init(void) {
    ESP_LOGI(TAG, "Initializing ILI9341...");

    // Hardware reset
    gpio_set_level(TFT_RST, 0);
    vTaskDelay(pdMS_TO_TICKS(20));
    gpio_set_level(TFT_RST, 1);
    vTaskDelay(pdMS_TO_TICKS(150));

    // Software reset
    spi_write_cmd(ILI9341_SWRESET);
    vTaskDelay(pdMS_TO_TICKS(150));

    // Exit sleep mode
    spi_write_cmd(ILI9341_SLPOUT);
    vTaskDelay(pdMS_TO_TICKS(500));

    // Set pixel format to 16-bit
    spi_write_cmd(ILI9341_COLMOD);
    spi_write_data(0x55);  // 16-bit RGB565

    // Set rotation (0 = portrait like ESPHome)
    spi_write_cmd(ILI9341_MADCTL);
    spi_write_data(0x40);  // MX=0, MY=1, MV=0, ML=0, BGR=0, MH=0

    // Turn on display
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

    gpio_set_level(TFT_DC, 1);  // Data mode

    uint32_t pixel_count = (uint32_t)w * h;

    // Send color data
    for (uint32_t i = 0; i < pixel_count; i++) {
        spi_write_data16(color);
    }
}

void draw_color_bars(void) {
    ESP_LOGI(TAG, "Drawing ESPHome P1 color bars...");

    const int w = 240;  // Portrait width
    const int h = 320;  // Portrait height
    const int bar = w / 6;  // ~40px per bar

    // Fill screen black first
    fill_rect(0, 0, w, h, COLOR_BLACK);

    // Draw color bars exactly like ESPHome P1
    fill_rect(0*bar, 0, bar, h, COLOR_RED);
    fill_rect(1*bar, 0, bar, h, COLOR_GREEN);
    fill_rect(2*bar, 0, bar, h, COLOR_BLUE);
    fill_rect(3*bar, 0, bar, h, COLOR_YELLOW);
    fill_rect(4*bar, 0, bar, h, COLOR_CYAN);
    fill_rect(5*bar, 0, w-5*bar, h, COLOR_MAGENTA);

    ESP_LOGI(TAG, "Color bars complete!");
}

void display_task(void *pvParameters) {
    int pattern = 0;

    while (1) {
        switch (pattern) {
            case 0:
                ESP_LOGI(TAG, "Drawing checkerboard...");
                // Simple checkerboard
                for (int y = 0; y < 320; y += 20) {
                    for (int x = 0; x < 240; x += 20) {
                        uint16_t color = ((x/20 + y/20) & 1) ? COLOR_WHITE : COLOR_BLACK;
                        fill_rect(x, y, 20, 20, color);
                    }
                }
                break;

            case 1:
                ESP_LOGI(TAG, "Back to color bars...");
                draw_color_bars();
                break;
        }

        pattern = (pattern + 1) % 2;
        vTaskDelay(pdMS_TO_TICKS(5000));  // 5 second cycle
    }
}

void app_main(void) {
    ESP_LOGI(TAG, "=== Pure ESP-IDF ILI9341 Test ===");
    ESP_LOGI(TAG, "ESPHome pins: CLK=%d, MISO=%d, MOSI=%d, CS=%d, DC=%d, RST=%d",
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

    // Set CS high initially
    gpio_set_level(TFT_CS, 1);

    // Configure SPI exactly like working ESPHome
    spi_bus_config_t buscfg = {
        .miso_io_num = TFT_MISO,
        .mosi_io_num = TFT_MOSI,
        .sclk_io_num = TFT_SCLK,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = 4096,
    };

    esp_err_t ret = spi_bus_initialize(SPI2_HOST, &buscfg, SPI_DMA_CH_AUTO);
    ESP_ERROR_CHECK(ret);

    spi_device_interface_config_t devcfg = {
        .clock_speed_hz = 40000000,  // 40MHz like ESPHome
        .mode = 0,                   // SPI mode 0
        .spics_io_num = TFT_CS,
        .queue_size = 7,
    };

    ret = spi_bus_add_device(SPI2_HOST, &devcfg, &spi);
    ESP_ERROR_CHECK(ret);

    ESP_LOGI(TAG, "SPI configured: 40MHz, Mode 0");

    // Initialize display
    ili9341_init();

    // Draw initial test pattern
    draw_color_bars();

    // Create display task for pattern cycling
    xTaskCreate(display_task, "display_task", 4096, NULL, 5, NULL);

    ESP_LOGI(TAG, "Setup complete - display should show color bars!");
}