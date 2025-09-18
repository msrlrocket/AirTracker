#include "airtracker_ui.h"
#include <stdio.h>
#include <math.h>
#include <string.h>
#include <stdlib.h>
#include <esp_lvgl_port.h>

// Color scheme
#define UI_COLOR_BG_DARK lv_color_make(0x0a, 0x0c, 0x10)
#define UI_COLOR_BG_CARD lv_color_make(0x1a, 0x1e, 0x25)
#define UI_COLOR_ACCENT lv_color_make(0x00, 0x7a, 0xff)
#define UI_COLOR_SUCCESS lv_color_make(0x28, 0xa7, 0x45)
#define UI_COLOR_WARNING lv_color_make(0xff, 0x9f, 0x40)
#define UI_COLOR_DANGER lv_color_make(0xdc, 0x35, 0x45)
#define UI_COLOR_TEXT_PRIMARY lv_color_make(0xf8, 0xf9, 0xfa)
#define UI_COLOR_TEXT_SECONDARY lv_color_make(0x94, 0xa3, 0xb8)
#define UI_COLOR_BORDER lv_color_make(0x33, 0x3a, 0x44)

// Icons (using simple ASCII)
#define ICON_PLANE ">"
#define ICON_ALTITUDE "^"
#define ICON_SPEED "*"
#define ICON_DISTANCE "o"
#define ICON_PEOPLE "#"
#define ICON_ARROW_UP "^"
#define ICON_ARROW_DOWN "v"
#define ICON_ARROW_LEVEL "-"

// Screen
static lv_obj_t* scr_overview;

// Overview UI elements
static lv_obj_t* lb_route;
static lv_obj_t* lb_eta;
static lv_obj_t* lb_airline;
static lv_obj_t* lb_callsign;
static lv_obj_t* lb_distance;
static lv_obj_t* lb_souls;
static lv_obj_t* lb_altitude;

static screen_id_t current = SCREEN_OVERVIEW;

static char* format_int_comma(int value, char* buffer, size_t size) {
    snprintf(buffer, size, "%d", value);
    return buffer;
}

static void create_overview_screen(void) {
    // Create main screen
    scr_overview = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(scr_overview, UI_COLOR_BG_DARK, 0);

    // Header container
    lv_obj_t* header = lv_obj_create(scr_overview);
    lv_obj_set_size(header, LV_PCT(100), 40);
    lv_obj_align(header, LV_ALIGN_TOP_MID, 0, 0);
    lv_obj_set_style_bg_color(header, UI_COLOR_BG_CARD, 0);
    lv_obj_set_style_border_width(header, 0, 0);
    lv_obj_set_style_pad_all(header, 5, 0);

    // Route label (left side of header)
    lb_route = lv_label_create(header);
    lv_label_set_text(lb_route, "SEA -> SFO");
    lv_obj_set_style_text_color(lb_route, UI_COLOR_TEXT_PRIMARY, 0);
    lv_obj_align(lb_route, LV_ALIGN_LEFT_MID, 0, 0);

    // ETA label (right side of header)
    lb_eta = lv_label_create(header);
    lv_label_set_text(lb_eta, "412 km | ETA --:--");
    lv_obj_set_style_text_color(lb_eta, UI_COLOR_TEXT_SECONDARY, 0);
    lv_obj_align(lb_eta, LV_ALIGN_RIGHT_MID, 0, 0);

    // Main content container
    lv_obj_t* content = lv_obj_create(scr_overview);
    lv_obj_set_size(content, LV_PCT(100), LV_PCT(100) - 80);
    lv_obj_align(content, LV_ALIGN_CENTER, 0, 10);
    lv_obj_set_style_bg_color(content, UI_COLOR_BG_DARK, 0);
    lv_obj_set_style_border_width(content, 0, 0);
    lv_obj_set_style_pad_all(content, 10, 0);

    // Aircraft info section
    lv_obj_t* aircraft_section = lv_obj_create(content);
    lv_obj_set_size(aircraft_section, LV_PCT(100), 60);
    lv_obj_align(aircraft_section, LV_ALIGN_TOP_MID, 0, 0);
    lv_obj_set_style_bg_color(aircraft_section, UI_COLOR_BG_CARD, 0);
    lv_obj_set_style_border_color(aircraft_section, UI_COLOR_BORDER, 0);
    lv_obj_set_style_pad_all(aircraft_section, 8, 0);

    // Airline name
    lb_airline = lv_label_create(aircraft_section);
    lv_label_set_text(lb_airline, "Unknown Aircraft - Unknown Airline");
    lv_obj_set_style_text_color(lb_airline, UI_COLOR_TEXT_PRIMARY, 0);
    lv_obj_align(lb_airline, LV_ALIGN_TOP_LEFT, 0, 0);

    // Callsign
    lb_callsign = lv_label_create(aircraft_section);
    lv_label_set_text(lb_callsign, "Callsign: N/A");
    lv_obj_set_style_text_color(lb_callsign, UI_COLOR_TEXT_SECONDARY, 0);
    lv_obj_align(lb_callsign, LV_ALIGN_TOP_LEFT, 0, 20);

    // Stats container (bottom)
    lv_obj_t* stats = lv_obj_create(content);
    lv_obj_set_size(stats, LV_PCT(100), 40);
    lv_obj_align(stats, LV_ALIGN_BOTTOM_MID, 0, 0);
    lv_obj_set_style_bg_color(stats, UI_COLOR_BG_DARK, 0);
    lv_obj_set_style_border_width(stats, 0, 0);
    lv_obj_set_style_pad_all(stats, 5, 0);

    // Distance (left)
    lb_distance = lv_label_create(stats);
    lv_label_set_text(lb_distance, "0.0 km - N | 0 km/h");
    lv_obj_set_style_text_color(lb_distance, UI_COLOR_TEXT_PRIMARY, 0);
    lv_obj_align(lb_distance, LV_ALIGN_LEFT_MID, 0, -10);

    // Souls (center)
    lb_souls = lv_label_create(stats);
    lv_label_set_text(lb_souls, "0");
    lv_obj_set_style_text_color(lb_souls, UI_COLOR_TEXT_PRIMARY, 0);
    lv_obj_align(lb_souls, LV_ALIGN_CENTER, 0, -10);

    // Altitude (right)
    lb_altitude = lv_label_create(stats);
    lv_label_set_text(lb_altitude, "0 ft  - 0 fpm");
    lv_obj_set_style_text_color(lb_altitude, UI_COLOR_TEXT_PRIMARY, 0);
    lv_obj_align(lb_altitude, LV_ALIGN_RIGHT_MID, 0, -10);
}

void airtracker_ui_init(const airtracker_model_t* m) {
    create_overview_screen();
    lv_scr_load(scr_overview);
    airtracker_ui_update(m);
}

void airtracker_ui_update(const airtracker_model_t* m) {
    if (!m) return;

    // Lock LVGL for thread safety
    lvgl_port_lock(0);

    // Update route
    char route_text[32];
    snprintf(route_text, sizeof(route_text), "%s -> %s", m->route_origin, m->route_destination);
    lv_label_set_text(lb_route, route_text);

    // Update ETA
    char eta_text[64];
    snprintf(eta_text, sizeof(eta_text), "%.0f km | ETA %s", m->distance_remaining_km, m->eta_local_hhmm);
    lv_label_set_text(lb_eta, eta_text);

    // Update airline info
    char airline_text[200];  // Increased buffer size to prevent truncation
    if (strlen(m->aircraft_name) > 0 && strlen(m->airline_name) > 0) {
        snprintf(airline_text, sizeof(airline_text), "%.60s - %.60s", m->aircraft_name, m->airline_name);
    } else if (strlen(m->aircraft_name) > 0) {
        snprintf(airline_text, sizeof(airline_text), "%.60s", m->aircraft_name);
    } else if (strlen(m->airline_name) > 0) {
        snprintf(airline_text, sizeof(airline_text), "%.60s", m->airline_name);
    } else {
        snprintf(airline_text, sizeof(airline_text), "Unknown Aircraft");
    }
    lv_label_set_text(lb_airline, airline_text);

    // Update callsign
    char callsign_text[32];
    snprintf(callsign_text, sizeof(callsign_text), "Callsign: %s", m->callsign);
    lv_label_set_text(lb_callsign, callsign_text);

    // Update distance and direction
    char distance_text[64];
    snprintf(distance_text, sizeof(distance_text), "%.1f km - %s | %d km/h",
             m->distance_now_km, m->direction_cardinal, m->ground_speed_kmh);
    lv_label_set_text(lb_distance, distance_text);

    // Update souls
    char souls_text[16];
    snprintf(souls_text, sizeof(souls_text), "%d", m->souls_on_board);
    lv_label_set_text(lb_souls, souls_text);

    // Update altitude and vertical rate
    char altitude_text[64];
    char arrow = m->vertical_rate_fpm > 0 ? '^' : (m->vertical_rate_fpm < 0 ? 'v' : '-');
    int vmag = m->vertical_rate_fpm >= 0 ? m->vertical_rate_fpm : -m->vertical_rate_fpm;
    char alt_buffer[16], vv_buffer[16];
    snprintf(altitude_text, sizeof(altitude_text), "%s ft  %c %s fpm",
             format_int_comma(m->altitude_ft, alt_buffer, sizeof(alt_buffer)),
             arrow,
             format_int_comma(vmag, vv_buffer, sizeof(vv_buffer)));
    lv_label_set_text(lb_altitude, altitude_text);

    // Unlock LVGL
    lvgl_port_unlock();
}

void airtracker_ui_show_screen(screen_id_t id) {
    if (id == SCREEN_OVERVIEW) {
        lv_scr_load(scr_overview);
        current = id;
    }
}

screen_id_t airtracker_ui_current_screen(void) {
    return current;
}