#include <stdio.h>
#include <string.h>
#include <math.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/event_groups.h>
#include <driver/spi_master.h>
#include <driver/gpio.h>
#include <esp_log.h>
#include <esp_wifi.h>
#include <esp_event.h>
#include <esp_netif.h>
#include <esp_http_client.h>
#include <esp_crt_bundle.h>
#include <nvs_flash.h>
#include "jpeg_decoder.h"
#include "wifi_config.h"

static const char* TAG = "AirTracker";

// Global error tracking
int last_jpeg_error = 0;

// WiFi event group
static EventGroupHandle_t s_wifi_event_group;
#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT      BIT1

// Image download buffer
#define MAX_IMAGE_SIZE     (20 * 1024)  // 20KB max image size
static uint8_t image_buffer[MAX_IMAGE_SIZE];
static size_t image_size = 0;

// Decoded image buffer (RGB565 format)
#define MAX_DECODED_WIDTH  100
#define MAX_DECODED_HEIGHT 80
static uint16_t decoded_image[MAX_DECODED_WIDTH * MAX_DECODED_HEIGHT];
static uint16_t decoded_width = 0;
static uint16_t decoded_height = 0;
static bool show_fallback_image = false;

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
// WiFi event handler
static void event_handler(void* arg, esp_event_base_t event_base,
                          int32_t event_id, void* event_data) {
    static int s_retry_num = 0;
    const int max_retry = 5;

    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        if (s_retry_num < max_retry) {
            esp_wifi_connect();
            s_retry_num++;
            ESP_LOGI(TAG, "retry to connect to the AP");
        } else {
            xEventGroupSetBits(s_wifi_event_group, WIFI_FAIL_BIT);
        }
        ESP_LOGI(TAG,"connect to the AP fail");
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t* event = (ip_event_got_ip_t*) event_data;
        ESP_LOGI(TAG, "got ip:" IPSTR, IP2STR(&event->ip_info.ip));
        s_retry_num = 0;
        xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
    }
}

// Initialize WiFi
void wifi_init_sta(void) {
    s_wifi_event_group = xEventGroupCreate();

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT,
                                               ESP_EVENT_ANY_ID,
                                               &event_handler,
                                               NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT,
                                               IP_EVENT_STA_GOT_IP,
                                               &event_handler,
                                               NULL));

    wifi_config_t wifi_config = {
        .sta = {
            .ssid = WIFI_SSID,
            .password = WIFI_PASSWORD,
            .threshold.authmode = WIFI_AUTH_WPA2_PSK,
            .pmf_cfg = {
                .capable = true,
                .required = false
            },
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGI(TAG, "wifi_init_sta finished.");

    // Wait for connection
    EventBits_t bits = xEventGroupWaitBits(s_wifi_event_group,
                                           WIFI_CONNECTED_BIT | WIFI_FAIL_BIT,
                                           pdFALSE,
                                           pdFALSE,
                                           portMAX_DELAY);

    if (bits & WIFI_CONNECTED_BIT) {
        ESP_LOGI(TAG, "connected to ap SSID:%s", WIFI_SSID);
    } else if (bits & WIFI_FAIL_BIT) {
        ESP_LOGI(TAG, "Failed to connect to SSID:%s", WIFI_SSID);
    }
}

// HTTP client event handler
esp_err_t http_event_handler(esp_http_client_event_t *evt) {
    switch(evt->event_id) {
        case HTTP_EVENT_ERROR:
            ESP_LOGD(TAG, "HTTP_EVENT_ERROR");
            break;
        case HTTP_EVENT_ON_CONNECTED:
            ESP_LOGD(TAG, "HTTP_EVENT_ON_CONNECTED");
            break;
        case HTTP_EVENT_HEADERS_SENT:
            ESP_LOGD(TAG, "HTTP_EVENT_HEADERS_SENT");
            break;
        case HTTP_EVENT_ON_HEADER:
            ESP_LOGD(TAG, "HTTP_EVENT_ON_HEADER, key=%s, value=%s", evt->header_key, evt->header_value);
            break;
        case HTTP_EVENT_ON_DATA:
            ESP_LOGD(TAG, "HTTP_EVENT_ON_DATA, len=%d", evt->data_len);
            if (image_size + evt->data_len < MAX_IMAGE_SIZE) {
                memcpy(image_buffer + image_size, evt->data, evt->data_len);
                image_size += evt->data_len;
            }
            break;
        case HTTP_EVENT_ON_FINISH:
            ESP_LOGD(TAG, "HTTP_EVENT_ON_FINISH");
            break;
        case HTTP_EVENT_DISCONNECTED:
            ESP_LOGD(TAG, "HTTP_EVENT_DISCONNECTED");
            break;
        case HTTP_EVENT_REDIRECT:
            ESP_LOGD(TAG, "HTTP_EVENT_REDIRECT");
            break;
    }
    return ESP_OK;
}

// Download image from URL
bool download_image(const char* url) {
    ESP_LOGI(TAG, "Starting image download from: %s", url);

    // Check WiFi status first
    if (!s_wifi_event_group) {
        ESP_LOGE(TAG, "WiFi not initialized");
        return false;
    }

    EventBits_t bits = xEventGroupGetBits(s_wifi_event_group);
    if (!(bits & WIFI_CONNECTED_BIT)) {
        ESP_LOGE(TAG, "WiFi not connected - cannot download image");
        return false;
    }

    ESP_LOGI(TAG, "WiFi connected, proceeding with download");
    image_size = 0; // Reset buffer

    esp_http_client_config_t config = {
        .url = url,
        .event_handler = http_event_handler,
        .timeout_ms = 30000,  // Longer timeout for SSL
        .skip_cert_common_name_check = true,
        .use_global_ca_store = false,
        .crt_bundle_attach = esp_crt_bundle_attach,  // Use certificate bundle
        .is_async = false,
        .disable_auto_redirect = false,
    };

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
        ESP_LOGE(TAG, "Failed to initialize HTTP client");
        return false;
    }

    ESP_LOGI(TAG, "HTTP client initialized, starting download...");
    esp_err_t err = esp_http_client_perform(client);

    if (err == ESP_OK) {
        int status_code = esp_http_client_get_status_code(client);
        ESP_LOGI(TAG, "HTTP Status: %d, Downloaded: %d bytes", status_code, image_size);

        if (status_code == 200 && image_size > 0) {
            ESP_LOGI(TAG, "✅ Image download successful!");
        } else {
            ESP_LOGE(TAG, "❌ Download failed - Status: %d, Size: %d", status_code, image_size);
            err = ESP_FAIL;
        }
    } else {
        ESP_LOGE(TAG, "❌ HTTP request failed: %s", esp_err_to_name(err));
    }

    esp_http_client_cleanup(client);
    return (err == ESP_OK && image_size > 0);
}

// Forward declaration for display_downloaded_image (defined after display functions)
void display_downloaded_image(uint16_t x, uint16_t y, uint16_t max_width, uint16_t max_height);

// Color definitions (RGB565)
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

// Enhanced 8x16 font for better readability
const uint8_t font_8x16[][16] = {
    // Space (32)
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    // ! (33)
    {0x00, 0x00, 0x18, 0x3C, 0x3C, 0x3C, 0x18, 0x18, 0x18, 0x00, 0x18, 0x18, 0x00, 0x00, 0x00, 0x00},
    // " (34)
    {0x00, 0x00, 0x66, 0x66, 0x66, 0x24, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    // # to , (35-44) - basic patterns
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    // - (45)
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xFE, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    // . (46)
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x18, 0x18, 0x00, 0x00, 0x00},
    // / (47)
    {0x00, 0x00, 0x02, 0x06, 0x0C, 0x18, 0x30, 0x60, 0xC0, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    // 0-9 (48-57)
    {0x00, 0x00, 0x3C, 0x66, 0xC3, 0xC3, 0xDB, 0xDB, 0xC3, 0xC3, 0x66, 0x3C, 0x00, 0x00, 0x00, 0x00}, // 0
    {0x00, 0x00, 0x18, 0x38, 0x58, 0x18, 0x18, 0x18, 0x18, 0x18, 0x18, 0x7E, 0x00, 0x00, 0x00, 0x00}, // 1
    {0x00, 0x00, 0x3C, 0x66, 0xC3, 0x03, 0x06, 0x0C, 0x18, 0x30, 0x60, 0xFF, 0x00, 0x00, 0x00, 0x00}, // 2
    {0x00, 0x00, 0x3C, 0x66, 0xC3, 0x03, 0x0E, 0x0E, 0x03, 0xC3, 0x66, 0x3C, 0x00, 0x00, 0x00, 0x00}, // 3
    {0x00, 0x00, 0x06, 0x0E, 0x1E, 0x36, 0x66, 0xC6, 0xFF, 0x06, 0x06, 0x0F, 0x00, 0x00, 0x00, 0x00}, // 4
    {0x00, 0x00, 0xFF, 0xC0, 0xC0, 0xC0, 0xFC, 0x0E, 0x03, 0xC3, 0x66, 0x3C, 0x00, 0x00, 0x00, 0x00}, // 5
    {0x00, 0x00, 0x3C, 0x66, 0xC3, 0xC0, 0xFC, 0xCE, 0xC3, 0xC3, 0x66, 0x3C, 0x00, 0x00, 0x00, 0x00}, // 6
    {0x00, 0x00, 0xFF, 0x03, 0x06, 0x0C, 0x18, 0x30, 0x30, 0x30, 0x30, 0x30, 0x00, 0x00, 0x00, 0x00}, // 7
    {0x00, 0x00, 0x3C, 0x66, 0xC3, 0x66, 0x3C, 0x3C, 0x66, 0xC3, 0x66, 0x3C, 0x00, 0x00, 0x00, 0x00}, // 8
    {0x00, 0x00, 0x3C, 0x66, 0xC3, 0xC3, 0x67, 0x3F, 0x03, 0xC3, 0x66, 0x3C, 0x00, 0x00, 0x00, 0x00}, // 9
    // : (58)
    {0x00, 0x00, 0x00, 0x00, 0x18, 0x18, 0x00, 0x00, 0x00, 0x18, 0x18, 0x00, 0x00, 0x00, 0x00, 0x00},
    // ; to @ (59-64) - basic patterns
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    // A-Z (65-90)
    {0x00, 0x00, 0x10, 0x38, 0x6C, 0xC6, 0xC6, 0xFE, 0xC6, 0xC6, 0xC6, 0xC6, 0x00, 0x00, 0x00, 0x00}, // A
    {0x00, 0x00, 0xFC, 0x66, 0x66, 0x66, 0x7C, 0x7C, 0x66, 0x66, 0x66, 0xFC, 0x00, 0x00, 0x00, 0x00}, // B
    {0x00, 0x00, 0x3C, 0x66, 0xC2, 0xC0, 0xC0, 0xC0, 0xC0, 0xC2, 0x66, 0x3C, 0x00, 0x00, 0x00, 0x00}, // C
    {0x00, 0x00, 0xF8, 0x6C, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x6C, 0xF8, 0x00, 0x00, 0x00, 0x00}, // D
    {0x00, 0x00, 0xFE, 0x66, 0x62, 0x68, 0x78, 0x78, 0x68, 0x62, 0x66, 0xFE, 0x00, 0x00, 0x00, 0x00}, // E
    {0x00, 0x00, 0xFE, 0x66, 0x62, 0x68, 0x78, 0x78, 0x68, 0x60, 0x60, 0xF0, 0x00, 0x00, 0x00, 0x00}, // F
    {0x00, 0x00, 0x3C, 0x66, 0xC2, 0xC0, 0xC0, 0xDE, 0xC6, 0xC6, 0x66, 0x3A, 0x00, 0x00, 0x00, 0x00}, // G
    {0x00, 0x00, 0xC6, 0xC6, 0xC6, 0xC6, 0xFE, 0xFE, 0xC6, 0xC6, 0xC6, 0xC6, 0x00, 0x00, 0x00, 0x00}, // H
    {0x00, 0x00, 0x3C, 0x18, 0x18, 0x18, 0x18, 0x18, 0x18, 0x18, 0x18, 0x3C, 0x00, 0x00, 0x00, 0x00}, // I
    {0x00, 0x00, 0x1E, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0xCC, 0xCC, 0xCC, 0x78, 0x00, 0x00, 0x00, 0x00}, // J
    {0x00, 0x00, 0xE6, 0x66, 0x6C, 0x6C, 0x78, 0x78, 0x6C, 0x6C, 0x66, 0xE6, 0x00, 0x00, 0x00, 0x00}, // K
    {0x00, 0x00, 0xF0, 0x60, 0x60, 0x60, 0x60, 0x60, 0x60, 0x62, 0x66, 0xFE, 0x00, 0x00, 0x00, 0x00}, // L
    {0x00, 0x00, 0xC6, 0xEE, 0xFE, 0xFE, 0xD6, 0xC6, 0xC6, 0xC6, 0xC6, 0xC6, 0x00, 0x00, 0x00, 0x00}, // M
    {0x00, 0x00, 0xC6, 0xE6, 0xF6, 0xFE, 0xDE, 0xCE, 0xC6, 0xC6, 0xC6, 0xC6, 0x00, 0x00, 0x00, 0x00}, // N
    {0x00, 0x00, 0x38, 0x6C, 0xC6, 0xC6, 0xC6, 0xC6, 0xC6, 0xC6, 0x6C, 0x38, 0x00, 0x00, 0x00, 0x00}, // O
    {0x00, 0x00, 0xFC, 0x66, 0x66, 0x66, 0x7C, 0x60, 0x60, 0x60, 0x60, 0xF0, 0x00, 0x00, 0x00, 0x00}, // P
    {0x00, 0x00, 0x38, 0x6C, 0xC6, 0xC6, 0xC6, 0xC6, 0xC6, 0xD6, 0xDE, 0x7C, 0x0C, 0x0E, 0x00, 0x00}, // Q
    {0x00, 0x00, 0xFC, 0x66, 0x66, 0x66, 0x7C, 0x6C, 0x66, 0x66, 0x66, 0xE6, 0x00, 0x00, 0x00, 0x00}, // R
    {0x00, 0x00, 0x7C, 0xC6, 0xC6, 0x60, 0x38, 0x0C, 0x06, 0xC6, 0xC6, 0x7C, 0x00, 0x00, 0x00, 0x00}, // S
    {0x00, 0x00, 0x7E, 0x7E, 0x5A, 0x18, 0x18, 0x18, 0x18, 0x18, 0x18, 0x3C, 0x00, 0x00, 0x00, 0x00}, // T
    {0x00, 0x00, 0xC6, 0xC6, 0xC6, 0xC6, 0xC6, 0xC6, 0xC6, 0xC6, 0xC6, 0x7C, 0x00, 0x00, 0x00, 0x00}, // U
    {0x00, 0x00, 0xC6, 0xC6, 0xC6, 0xC6, 0xC6, 0xC6, 0xC6, 0x6C, 0x38, 0x10, 0x00, 0x00, 0x00, 0x00}, // V
    {0x00, 0x00, 0xC6, 0xC6, 0xC6, 0xC6, 0xD6, 0xD6, 0xD6, 0xFE, 0xEE, 0x6C, 0x00, 0x00, 0x00, 0x00}, // W
    {0x00, 0x00, 0xC6, 0xC6, 0x6C, 0x7C, 0x38, 0x38, 0x7C, 0x6C, 0xC6, 0xC6, 0x00, 0x00, 0x00, 0x00}, // X
    {0x00, 0x00, 0x66, 0x66, 0x66, 0x66, 0x3C, 0x18, 0x18, 0x18, 0x18, 0x3C, 0x00, 0x00, 0x00, 0x00}, // Y
    {0x00, 0x00, 0xFE, 0xC6, 0x86, 0x0C, 0x18, 0x30, 0x60, 0xC2, 0xC6, 0xFE, 0x00, 0x00, 0x00, 0x00}, // Z
};

// Keep original 5x7 font for compatibility
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

// Enhanced character drawing with 8x16 font
void draw_char_large(char c, uint16_t x, uint16_t y, uint16_t color, uint16_t bg_color) {
    if (c < 32 || c > 90) return; // Only support space to Z

    const uint8_t *bitmap = font_8x16[c - 32];

    for (int row = 0; row < 16; row++) {
        for (int col = 0; col < 8; col++) {
            if (bitmap[row] & (0x80 >> col)) {
                // Draw pixel
                fill_rect(x + col, y + row, 1, 1, color);
            } else if (bg_color != 0xFFFF) { // Skip transparent background
                // Draw background pixel
                fill_rect(x + col, y + row, 1, 1, bg_color);
            }
        }
    }
}

// Original 5x7 character drawing (preserved for compatibility)
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

// Enhanced text drawing with large font
void draw_text_large(const char* text, uint16_t x, uint16_t y, uint16_t color, uint16_t bg_color) {
    int len = strlen(text);
    for (int i = 0; i < len && i < 35; i++) { // Max chars per line
        draw_char_large(text[i], x + i * 9, y, color, bg_color); // 9 pixel spacing for 8-pixel wide chars
    }
}

// Original text drawing (preserved for compatibility)
void draw_text(const char* text, uint16_t x, uint16_t y, uint16_t color, uint16_t bg_color) {
    int len = strlen(text);
    for (int i = 0; i < len && i < 35; i++) { // Max 35 chars per line
        draw_char(text[i], x + i * 6, y, color, bg_color); // 6 pixel spacing for 5-pixel wide chars
    }
}

// Drawing primitives for enhanced graphics
void draw_line(uint16_t x0, uint16_t y0, uint16_t x1, uint16_t y1, uint16_t color) {
    int dx = abs(x1 - x0);
    int dy = abs(y1 - y0);
    int sx = (x0 < x1) ? 1 : -1;
    int sy = (y0 < y1) ? 1 : -1;
    int err = dx - dy;

    while (1) {
        fill_rect(x0, y0, 1, 1, color);

        if (x0 == x1 && y0 == y1) break;

        int e2 = 2 * err;
        if (e2 > -dy) {
            err -= dy;
            x0 += sx;
        }
        if (e2 < dx) {
            err += dx;
            y0 += sy;
        }
    }
}

void draw_circle(uint16_t cx, uint16_t cy, uint16_t radius, uint16_t color) {
    int x = radius;
    int y = 0;
    int err = 0;

    while (x >= y) {
        fill_rect(cx + x, cy + y, 1, 1, color);
        fill_rect(cx + y, cy + x, 1, 1, color);
        fill_rect(cx - y, cy + x, 1, 1, color);
        fill_rect(cx - x, cy + y, 1, 1, color);
        fill_rect(cx - x, cy - y, 1, 1, color);
        fill_rect(cx - y, cy - x, 1, 1, color);
        fill_rect(cx + y, cy - x, 1, 1, color);
        fill_rect(cx + x, cy - y, 1, 1, color);

        if (err <= 0) {
            y += 1;
            err += 2*y + 1;
        }
        if (err > 0) {
            x -= 1;
            err -= 2*x + 1;
        }
    }
}

void draw_rounded_rect(uint16_t x, uint16_t y, uint16_t w, uint16_t h, uint16_t radius, uint16_t color) {
    // Draw main rectangle
    fill_rect(x + radius, y, w - 2*radius, h, color);
    fill_rect(x, y + radius, w, h - 2*radius, color);

    // Draw corners (simplified)
    for (int i = 0; i < radius; i++) {
        for (int j = 0; j < radius; j++) {
            if ((i*i + j*j) <= (radius*radius)) {
                fill_rect(x + radius - i, y + radius - j, 1, 1, color); // Top-left
                fill_rect(x + w - radius + i, y + radius - j, 1, 1, color); // Top-right
                fill_rect(x + radius - i, y + h - radius + j, 1, 1, color); // Bottom-left
                fill_rect(x + w - radius + i, y + h - radius + j, 1, 1, color); // Bottom-right
            }
        }
    }
}

void draw_airtracker_ui(void) {
    ESP_LOGI(TAG, "Drawing Enhanced AirTracker UI...");

    // Clear screen with dark background (landscape: 320x240)
    fill_rect(0, 0, 320, 240, COLOR_BLACK);

    // Enhanced header with rounded corners
    draw_rounded_rect(0, 0, 320, 30, 5, COLOR_BLUE);

    // Title with large font
    draw_text_large("AIRTRACKER", 10, 8, COLOR_WHITE, 0xFFFF); // Transparent background

    // Draw airplane icon (simple)
    draw_line(280, 15, 300, 15, COLOR_WHITE);
    draw_line(290, 10, 290, 20, COLOR_WHITE);
    draw_circle(285, 15, 2, COLOR_WHITE);

    // Left column - Aircraft info with rounded corners
    draw_rounded_rect(5, 35, 150, 90, 8, COLOR_BLUE);
    draw_text("AIRCRAFT INFO", 12, 42, COLOR_YELLOW, COLOR_BLUE);

    // Enhanced aircraft data formatting
    draw_text("REG: N64942", 12, 54, COLOR_WHITE, COLOR_BLUE);
    draw_text("TYPE: C152", 12, 66, COLOR_WHITE, COLOR_BLUE);
    draw_text("CALL: N64942", 12, 78, COLOR_WHITE, COLOR_BLUE);
    draw_text("HIO -> CLS", 12, 90, COLOR_CYAN, COLOR_BLUE);

    // Add visual separator line
    draw_line(12, 100, 143, 100, COLOR_CYAN);
    draw_text("PRIVATE", 12, 105, COLOR_YELLOW, COLOR_BLUE);

    // Right column - Flight data with rounded corners
    draw_rounded_rect(165, 35, 150, 90, 8, COLOR_GREEN);
    draw_text("FLIGHT DATA", 172, 42, COLOR_BLACK, COLOR_GREEN);

    // Enhanced flight data with better formatting
    draw_text("ALT: 3400 FT", 172, 54, COLOR_BLACK, COLOR_GREEN);
    draw_text("SPD: 116 KT", 172, 66, COLOR_BLACK, COLOR_GREEN);
    draw_text("HDG: 180 DEG", 172, 78, COLOR_BLACK, COLOR_GREEN);
    draw_text("DIST: 7.3 NM", 172, 90, COLOR_BLACK, COLOR_GREEN);

    // Add visual elements
    draw_circle(172 + 130, 50, 3, COLOR_BLACK); // Speed indicator
    draw_line(172, 100, 305, 100, COLOR_BLACK);
    draw_text("LEVEL", 172, 105, COLOR_RED, COLOR_GREEN);

    // Enhanced status section with rounded corners
    draw_rounded_rect(5, 135, 310, 25, 6, COLOR_YELLOW);
    draw_text_large("TRACKING", 100, 143, COLOR_BLACK, 0xFFFF);

    // Add status indicators
    draw_circle(15, 147, 4, COLOR_GREEN); // Active indicator
    draw_circle(295, 147, 4, COLOR_RED);   // Alert indicator

    // Split bottom section: Position data + Aircraft image
    // Left side - Position data
    draw_rounded_rect(5, 170, 200, 65, 8, COLOR_CYAN);
    draw_text("POSITION DATA", 12, 177, COLOR_BLACK, COLOR_CYAN);

    // Better coordinate formatting
    draw_text("LAT: 46.22", 12, 189, COLOR_BLACK, COLOR_CYAN);
    draw_text("LON: -122.81", 12, 201, COLOR_BLACK, COLOR_CYAN);
    draw_text("SQ: 1200", 12, 213, COLOR_BLACK, COLOR_CYAN);
    draw_text("V/S: -128", 12, 225, COLOR_BLACK, COLOR_CYAN);

    // Right side - Aircraft image area
    draw_rounded_rect(215, 170, 100, 65, 8, COLOR_MAGENTA);
    draw_text("AIRCRAFT", 220, 177, COLOR_WHITE, COLOR_MAGENTA);

    // Display downloaded image or placeholder
    display_downloaded_image(220, 190, 90, 40);

    // Show WiFi status and download/decode status (spread out vertically)
    if (s_wifi_event_group) {
        EventBits_t bits = xEventGroupGetBits(s_wifi_event_group);
        if (bits & WIFI_CONNECTED_BIT) {
            draw_text("WIFI OK", 165, 205, COLOR_WHITE, COLOR_GREEN);

            // Show download and decode status
            if (image_size > 0) {
                char status[16];
                snprintf(status, sizeof(status), "%dB", image_size);
                draw_text(status, 165, 217, COLOR_WHITE, COLOR_CYAN);

                if (decoded_width > 0 && decoded_height > 0) {
                    char decode_status[16];
                    snprintf(decode_status, sizeof(decode_status), "%dx%d", decoded_width, decoded_height);
                    draw_text(decode_status, 165, 229, COLOR_WHITE, COLOR_GREEN);
                } else {
                    // Show last JPEG error code on screen
                    extern int last_jpeg_error;
                    char err_status[16];
                    snprintf(err_status, sizeof(err_status), "E:0x%X", last_jpeg_error);
                    draw_text(err_status, 165, 229, COLOR_WHITE, COLOR_RED);
                }
            } else {
                draw_text("NO DL", 165, 217, COLOR_WHITE, COLOR_RED);
            }
        } else {
            draw_text("NO WIFI", 165, 205, COLOR_WHITE, COLOR_RED);
        }
    }

    ESP_LOGI(TAG, "Enhanced AirTracker UI complete!");
}

// Decode JPEG image and store in RGB565 format
bool decode_jpeg_image() {
    if (image_size == 0) {
        ESP_LOGE(TAG, "No image data to decode");
        last_jpeg_error = ESP_ERR_INVALID_ARG;
        return false;
    }

    ESP_LOGI(TAG, "🔄 Starting decode: %lu bytes", (unsigned long)image_size);

    // Check if data looks like JPEG (starts with FF D8)
    if (image_size < 2 || image_buffer[0] != 0xFF || image_buffer[1] != 0xD8) {
        ESP_LOGE(TAG, "❌ Not valid JPEG data - header: %02X %02X %02X %02X",
                 image_size > 0 ? image_buffer[0] : 0,
                 image_size > 1 ? image_buffer[1] : 0,
                 image_size > 2 ? image_buffer[2] : 0,
                 image_size > 3 ? image_buffer[3] : 0);
        last_jpeg_error = ESP_ERR_INVALID_ARG;

        // For debugging: try to decode as text instead
        if (image_size > 10) {
            char text_sample[16] = {0};
            for (int i = 0; i < 15 && i < image_size; i++) {
                text_sample[i] = (image_buffer[i] >= 32 && image_buffer[i] < 127) ? image_buffer[i] : '.';
            }
            ESP_LOGI(TAG, "First 15 chars as text: '%s'", text_sample);
        }
        return false;
    }

    ESP_LOGI(TAG, "✅ JPEG header valid, proceeding with esp_jpeg decode...");

    // Try to get image info first (safer)
    esp_jpeg_image_cfg_t jpeg_cfg_info = {
        .indata = image_buffer,
        .indata_size = image_size,
        .outbuf = NULL,
        .outbuf_size = 0,
        .out_format = JPEG_IMAGE_FORMAT_RGB565,
        .out_scale = JPEG_IMAGE_SCALE_1_2,
    };

    esp_jpeg_image_output_t img_info;
    esp_err_t ret = esp_jpeg_get_image_info(&jpeg_cfg_info, &img_info);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "❌ JPEG get_info failed: %s (0x%x)", esp_err_to_name(ret), ret);
        last_jpeg_error = ret;
        return false;
    }

    ESP_LOGI(TAG, "📏 JPEG info: %dx%d pixels, will output %lu bytes",
             img_info.width, img_info.height, (unsigned long)img_info.output_len);

    // Check if output will fit in our buffer
    if (img_info.output_len > sizeof(decoded_image)) {
        ESP_LOGE(TAG, "❌ Output too large: %lu bytes (max %u)",
                 (unsigned long)img_info.output_len, sizeof(decoded_image));
        last_jpeg_error = ESP_ERR_NO_MEM;
        return false;
    }

    // Now do the actual decode
    esp_jpeg_image_cfg_t jpeg_cfg = {
        .indata = image_buffer,
        .indata_size = image_size,
        .outbuf = (uint8_t*)decoded_image,
        .outbuf_size = sizeof(decoded_image),
        .out_format = JPEG_IMAGE_FORMAT_RGB565,
        .out_scale = JPEG_IMAGE_SCALE_1_2,  // Scale down by 2 to fit buffer
        .flags = {
            .swap_color_bytes = 0,  // Keep RGB565 native format
        }
    };

    esp_jpeg_image_output_t outimg;
    ret = esp_jpeg_decode(&jpeg_cfg, &outimg);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "❌ JPEG decode failed: %s (0x%x)", esp_err_to_name(ret), ret);
        last_jpeg_error = ret;
        return false;
    }

    // Store decoded dimensions
    decoded_width = outimg.width;
    decoded_height = outimg.height;

    // Ensure we don't exceed our buffer limits
    if (decoded_width > MAX_DECODED_WIDTH) decoded_width = MAX_DECODED_WIDTH;
    if (decoded_height > MAX_DECODED_HEIGHT) decoded_height = MAX_DECODED_HEIGHT;

    ESP_LOGI(TAG, "✅ JPEG decode successful: %dx%d pixels, %lu bytes output",
             decoded_width, decoded_height, (unsigned long)outimg.output_len);

    last_jpeg_error = ESP_OK;
    return true;
}

// Draw RGB565 image data to screen
void draw_image(uint16_t x, uint16_t y, uint16_t width, uint16_t height, const uint16_t* image_data) {
    // Set display window
    set_addr_window(x, y, x + width - 1, y + height - 1);

    // Send image data
    gpio_set_level(TFT_DC, 1);  // Data mode
    gpio_set_level(TFT_CS, 0);  // Select display

    // Send pixel data in chunks to avoid SPI buffer overflow
    const size_t chunk_size = 256;  // 256 pixels at a time
    size_t total_pixels = width * height;

    for (size_t i = 0; i < total_pixels; i += chunk_size) {
        size_t pixels_to_send = (i + chunk_size < total_pixels) ? chunk_size : (total_pixels - i);

        spi_transaction_t t = {
            .length = pixels_to_send * 16,  // 16 bits per pixel
            .tx_buffer = &image_data[i],
            .flags = 0
        };

        esp_err_t ret = spi_device_polling_transmit(spi, &t);
        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "Failed to send image chunk: %s", esp_err_to_name(ret));
            break;
        }
    }

    gpio_set_level(TFT_CS, 1);  // Deselect display
}

// Function declarations
bool download_raw_rgb565_test();
bool download_and_decode_bmp();

// Generate a simple test pattern instead of decoding
void generate_test_pattern() {
    decoded_width = 64;
    decoded_height = 48;

    // Generate a simple aircraft-like pattern
    for (int y = 0; y < decoded_height; y++) {
        for (int x = 0; x < decoded_width; x++) {
            uint16_t color = COLOR_BLACK;

            // Create a simple aircraft silhouette
            int center_x = decoded_width / 2;
            int center_y = decoded_height / 2;

            // Fuselage (horizontal line)
            if (y >= center_y - 2 && y <= center_y + 2 && x >= 10 && x <= 54) {
                color = COLOR_WHITE;
            }

            // Wings (vertical line)
            if (x >= center_x - 2 && x <= center_x + 2 && y >= 15 && y <= 33) {
                color = COLOR_WHITE;
            }

            // Tail (small vertical line at back)
            if (x >= 50 && x <= 54 && y >= center_y - 6 && y <= center_y + 6) {
                color = COLOR_WHITE;
            }

            // Nose (triangle-ish)
            if (x >= 8 && x <= 12 && abs(y - center_y) <= (x - 8)) {
                color = COLOR_WHITE;
            }

            decoded_image[y * decoded_width + x] = color;
        }
    }

    ESP_LOGI(TAG, "✅ Generated test aircraft pattern: %dx%d", decoded_width, decoded_height);
}

// Download and decode raw RGB565 test data
bool download_raw_rgb565_test() {
    // Create a simple test pattern directly in RGB565 format
    decoded_width = 48;
    decoded_height = 32;

    ESP_LOGI(TAG, "Creating raw RGB565 test pattern...");

    // Create a simple gradient + checkerboard pattern
    for (int y = 0; y < decoded_height; y++) {
        for (int x = 0; x < decoded_width; x++) {
            uint16_t color;

            // Create different patterns in different quadrants
            if (y < 16 && x < 24) {
                // Top-left: Red gradient
                uint8_t intensity = (x * 255) / 23;
                color = ((intensity >> 3) << 11) | 0x0000; // Red only
            } else if (y < 16 && x >= 24) {
                // Top-right: Green gradient
                uint8_t intensity = ((x - 24) * 255) / 23;
                color = ((intensity >> 2) << 5) | 0x0000; // Green only
            } else if (y >= 16 && x < 24) {
                // Bottom-left: Blue gradient
                uint8_t intensity = ((y - 16) * 255) / 15;
                color = (intensity >> 3) | 0x0000; // Blue only
            } else {
                // Bottom-right: Checkerboard
                if ((x + y) % 4 < 2) {
                    color = COLOR_WHITE;
                } else {
                    color = COLOR_BLACK;
                }
            }

            decoded_image[y * decoded_width + x] = color;
        }
    }

    ESP_LOGI(TAG, "✅ Created RGB565 test pattern: %dx%d", decoded_width, decoded_height);
    return true;
}

// Simple BMP header structure
typedef struct {
    uint16_t type;          // "BM"
    uint32_t size;          // File size
    uint16_t reserved1;
    uint16_t reserved2;
    uint32_t offset;        // Offset to pixel data
    uint32_t header_size;   // DIB header size
    int32_t width;          // Image width
    int32_t height;         // Image height
    uint16_t planes;        // Color planes (must be 1)
    uint16_t bits_per_pixel; // Bits per pixel
    uint32_t compression;   // Compression type
    uint32_t image_size;    // Image size (can be 0)
    int32_t x_resolution;   // X resolution
    int32_t y_resolution;   // Y resolution
    uint32_t colors_used;   // Colors used
    uint32_t colors_important; // Important colors
} __attribute__((packed)) bmp_header_t;

// Convert RGB888 to RGB565
uint16_t rgb888_to_rgb565(uint8_t r, uint8_t g, uint8_t b) {
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3);
}

// Download and decode a real BMP image
bool download_and_decode_bmp() {
    ESP_LOGI(TAG, "Downloading real BMP image...");

    // Try to download a test BMP file
    // You can replace this URL with your own BMP file
    if (!download_image("https://www.w3.org/People/mimasa/test/imgformat/img/w3c_home.bmp")) {
        ESP_LOGE(TAG, "Failed to download BMP image");
        return false;
    }

    if (image_size < sizeof(bmp_header_t)) {
        ESP_LOGE(TAG, "Downloaded data too small for BMP: %lu bytes", (unsigned long)image_size);
        return false;
    }

    // Parse BMP header
    bmp_header_t* bmp = (bmp_header_t*)image_buffer;

    ESP_LOGI(TAG, "BMP file analysis:");
    ESP_LOGI(TAG, "  Type: 0x%04X (should be 0x4D42 for 'BM')", bmp->type);
    ESP_LOGI(TAG, "  File size: %lu bytes", (unsigned long)bmp->size);
    ESP_LOGI(TAG, "  Data offset: %lu", (unsigned long)bmp->offset);
    ESP_LOGI(TAG, "  Width: %ld pixels", (long)bmp->width);
    ESP_LOGI(TAG, "  Height: %ld pixels", (long)bmp->height);
    ESP_LOGI(TAG, "  Bits per pixel: %d", bmp->bits_per_pixel);
    ESP_LOGI(TAG, "  Compression: %lu", (unsigned long)bmp->compression);

    // Check if it's a valid BMP
    if (bmp->type != 0x4D42) { // "BM" in little endian
        ESP_LOGE(TAG, "❌ Not a valid BMP file (type: 0x%04X)", bmp->type);

        // Show what we actually got
        char sample[32] = {0};
        int sample_len = (image_size > 31) ? 31 : image_size;
        for (int i = 0; i < sample_len; i++) {
            sample[i] = (image_buffer[i] >= 32 && image_buffer[i] < 127) ? image_buffer[i] : '.';
        }
        ESP_LOGI(TAG, "First %d bytes as text: '%s'", sample_len, sample);
        return false;
    }

    // Check if we support this format
    if (bmp->compression != 0) {
        ESP_LOGE(TAG, "❌ Compressed BMP not supported (compression: %lu)", (unsigned long)bmp->compression);
        return false;
    }

    if (bmp->bits_per_pixel != 24 && bmp->bits_per_pixel != 16) {
        ESP_LOGE(TAG, "❌ Only 16-bit and 24-bit BMP supported (got %d-bit)", bmp->bits_per_pixel);
        return false;
    }

    // Get image dimensions (handle negative height = top-down)
    int32_t width = bmp->width;
    int32_t height = abs(bmp->height);
    bool top_down = (bmp->height < 0);

    // Scale down if too large
    decoded_width = (width > MAX_DECODED_WIDTH) ? MAX_DECODED_WIDTH : width;
    decoded_height = (height > MAX_DECODED_HEIGHT) ? MAX_DECODED_HEIGHT : height;

    ESP_LOGI(TAG, "✅ Valid BMP: %ldx%ld (%d-bit), scaled to %dx%d",
             (long)width, (long)height, bmp->bits_per_pixel, decoded_width, decoded_height);

    // Calculate row padding (BMP rows are padded to 4-byte boundaries)
    int bytes_per_pixel = bmp->bits_per_pixel / 8;
    int row_size = ((width * bytes_per_pixel + 3) / 4) * 4;

    // Point to pixel data
    uint8_t* pixel_data = image_buffer + bmp->offset;

    // Check if we have enough data
    size_t expected_data_size = bmp->offset + (row_size * height);
    if (image_size < expected_data_size) {
        ESP_LOGE(TAG, "❌ Not enough pixel data: got %lu, need %lu",
                 (unsigned long)image_size, (unsigned long)expected_data_size);
        return false;
    }

    ESP_LOGI(TAG, "🎨 Decoding pixels: %d bytes/pixel, %d bytes/row", bytes_per_pixel, row_size);

    // Decode pixel data
    for (int y = 0; y < decoded_height; y++) {
        for (int x = 0; x < decoded_width; x++) {
            // Scale coordinates to source image
            int src_x = (x * width) / decoded_width;
            int src_y = (y * height) / decoded_height;

            // BMP is usually bottom-up, but handle top-down too
            int row_index = top_down ? src_y : (height - 1 - src_y);

            // Calculate pixel offset
            size_t pixel_offset = (row_index * row_size) + (src_x * bytes_per_pixel);

            uint16_t color;

            if (bmp->bits_per_pixel == 24) {
                // 24-bit: BGR format
                uint8_t b = pixel_data[pixel_offset + 0];
                uint8_t g = pixel_data[pixel_offset + 1];
                uint8_t r = pixel_data[pixel_offset + 2];
                color = rgb888_to_rgb565(r, g, b);
            } else {
                // 16-bit: already RGB565 (little endian)
                color = pixel_data[pixel_offset] | (pixel_data[pixel_offset + 1] << 8);
            }

            decoded_image[y * decoded_width + x] = color;
        }
    }

    ESP_LOGI(TAG, "✅ BMP decode successful: %dx%d pixels", decoded_width, decoded_height);
    return true;
}

// Display downloaded and decoded image
void display_downloaded_image(uint16_t x, uint16_t y, uint16_t max_width, uint16_t max_height) {
    // Check if we have a valid decoded image
    if (decoded_width > 0 && decoded_height > 0) {
        // Display the decoded image (either RGB565 test or aircraft pattern)
        uint16_t img_x = x + (max_width - decoded_width) / 2;
        uint16_t img_y = y + (max_height - decoded_height) / 2;

        draw_rounded_rect(x, y, max_width, max_height, 5, COLOR_GREEN);
        draw_image(img_x, img_y, decoded_width, decoded_height, decoded_image);
        draw_text("SUCCESS", x + 5, y + 5, COLOR_BLACK, COLOR_GREEN);
        return;
    }

    // Fallback if no image
    if (show_fallback_image || image_size == 0) {
        generate_test_pattern();

        // Display the test pattern
        uint16_t img_x = x + (max_width - decoded_width) / 2;
        uint16_t img_y = y + (max_height - decoded_height) / 2;

        draw_rounded_rect(x, y, max_width, max_height, 5, COLOR_BLUE);
        draw_image(img_x, img_y, decoded_width, decoded_height, decoded_image);
        draw_text("FALLBACK", x + 5, y + 5, COLOR_WHITE, COLOR_BLUE);
        return;
    }

    // Try to decode the JPEG image
    if (decoded_width == 0 || decoded_height == 0) {
        // Image not decoded yet, try to decode it
        if (!decode_jpeg_image()) {
            // Decoding failed, show detailed error and try test pattern
            draw_rounded_rect(x, y, max_width, max_height, 5, COLOR_RED);

            extern int last_jpeg_error;
            char err_text[32];
            snprintf(err_text, sizeof(err_text), "ERR:0x%X", last_jpeg_error);
            draw_text(err_text, x + 5, y + 5, COLOR_WHITE, COLOR_RED);

            char size_text[32];
            snprintf(size_text, sizeof(size_text), "SZ:%lu", (unsigned long)image_size);
            draw_text(size_text, x + 5, y + 17, COLOR_WHITE, COLOR_RED);

            // Show first few bytes of image data for debugging
            char data_text[32];
            if (image_size >= 4) {
                snprintf(data_text, sizeof(data_text), "%02X%02X%02X%02X",
                         image_buffer[0], image_buffer[1], image_buffer[2], image_buffer[3]);
            } else {
                snprintf(data_text, sizeof(data_text), "NO DATA");
            }
            draw_text(data_text, x + 5, y + 29, COLOR_WHITE, COLOR_RED);

            // Set fallback mode for next refresh
            show_fallback_image = true;
            return;
        }
    }

    // Calculate display size to fit within available space
    uint16_t display_width = decoded_width;
    uint16_t display_height = decoded_height;

    if (display_width > max_width) {
        // Scale down proportionally
        display_height = (display_height * max_width) / display_width;
        display_width = max_width;
    }
    if (display_height > max_height) {
        // Scale down proportionally
        display_width = (display_width * max_height) / display_height;
        display_height = max_height;
    }

    // Center the image in the available space
    uint16_t img_x = x + (max_width - display_width) / 2;
    uint16_t img_y = y + (max_height - display_height) / 2;

    // Clear the background
    draw_rounded_rect(x, y, max_width, max_height, 5, COLOR_BLACK);

    // Display the decoded image
    if (display_width == decoded_width && display_height == decoded_height) {
        // No scaling needed, draw directly
        draw_image(img_x, img_y, decoded_width, decoded_height, decoded_image);
    } else {
        // Simple nearest-neighbor scaling (for now)
        // For simplicity, just draw the top-left portion if scaling is needed
        uint16_t crop_width = (display_width > decoded_width) ? decoded_width : display_width;
        uint16_t crop_height = (display_height > decoded_height) ? decoded_height : display_height;
        draw_image(img_x, img_y, crop_width, crop_height, decoded_image);
    }

    ESP_LOGI(TAG, "✅ Displayed aircraft image: %dx%d at (%d,%d)",
             display_width, display_height, img_x, img_y);
}

void display_task(void *pvParameters) {
    int counter = 0;
    bool color_bars_shown = false;

    while (1) {
        ESP_LOGI(TAG, "Display update cycle %d", counter++);

        // Show color bars only once at startup as a test
        if (!color_bars_shown) {
            ESP_LOGI(TAG, "Drawing startup color bars...");
            draw_color_bars();
            ESP_LOGI(TAG, "Color bars complete - waiting 2 seconds before main UI");
            vTaskDelay(pdMS_TO_TICKS(2000));
            color_bars_shown = true;
        }

        // Main UI display
        ESP_LOGI(TAG, "Drawing AirTracker UI...");
        draw_airtracker_ui();
        ESP_LOGI(TAG, "AirTracker UI complete");

        // Longer delay - update UI every 10 seconds to check for new images/status
        ESP_LOGI(TAG, "Waiting 10 seconds before next UI refresh...");
        vTaskDelay(pdMS_TO_TICKS(10000));
    }
}

void app_main(void) {
    ESP_LOGI(TAG, "=== ESP-IDF AirTracker Display with WiFi ===");
    ESP_LOGI(TAG, "Pins: CLK=%d, MISO=%d, MOSI=%d, CS=%d, DC=%d, RST=%d",
             TFT_SCLK, TFT_MISO, TFT_MOSI, TFT_CS, TFT_DC, TFT_RST);

    // Initialize NVS (required for WiFi)
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

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

    // Initialize display
    ili9341_init();
    draw_color_bars();

#ifdef ENABLE_WIFI_TEST
    // Initialize WiFi (optional - comment out if no WiFi)
    ESP_LOGI(TAG, "Initializing WiFi...");
    wifi_init_sta();

    // Test BMP image download
    ESP_LOGI(TAG, "Testing BMP image download...");
    if (download_and_decode_bmp()) {
        ESP_LOGI(TAG, "BMP download and decode successful!");
    } else {
        ESP_LOGI(TAG, "BMP failed, trying RGB565 test pattern...");
        if (download_raw_rgb565_test()) {
            ESP_LOGI(TAG, "RGB565 test pattern successful!");
        } else {
            ESP_LOGI(TAG, "All tests failed - using fallback pattern");
            show_fallback_image = true;
        }
    }
#else
    ESP_LOGI(TAG, "WiFi disabled - skipping image download test");
#endif

    xTaskCreate(display_task, "display_task", 8192, NULL, 5, NULL);

    ESP_LOGI(TAG, "Setup complete - display should show enhanced UI with image support!");
}