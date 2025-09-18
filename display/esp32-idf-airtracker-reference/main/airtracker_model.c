#include "airtracker_model.h"
#include <string.h>
#include <stdio.h>
#include <math.h>
#include <esp_log.h>

static const char* TAG = "Model";

static const char* bearing_to_cardinal(int deg) {
    static const char* dirs[8] = {"N","NE","E","SE","S","SW","W","NW"};
    int idx = ((deg % 360) + 360) % 360;
    idx = (int) floor((idx + 22.5) / 45.0) % 8;
    return dirs[idx];
}

static void safe_strncpy(char* dest, const char* src, size_t dest_size) {
    if (src && dest && dest_size > 0) {
        strncpy(dest, src, dest_size - 1);
        dest[dest_size - 1] = '\0';
    }
}

static void safe_json_string(cJSON* json, const char* key, char* dest, size_t dest_size) {
    cJSON* item = cJSON_GetObjectItem(json, key);
    if (cJSON_IsString(item) && item->valuestring) {
        safe_strncpy(dest, item->valuestring, dest_size);
    }
}

static double safe_json_number(cJSON* json, const char* key, double default_val) {
    cJSON* item = cJSON_GetObjectItem(json, key);
    if (cJSON_IsNumber(item)) {
        return item->valuedouble;
    }
    return default_val;
}

void airtracker_model_init(airtracker_model_t* m) {
    memset(m, 0, sizeof(airtracker_model_t));

    // Default values
    safe_strncpy(m->route_origin, "SEA", sizeof(m->route_origin));
    safe_strncpy(m->route_destination, "SFO", sizeof(m->route_destination));
    m->distance_remaining_km = 412.0f;
    safe_strncpy(m->eta_local_hhmm, "--:--", sizeof(m->eta_local_hhmm));

    safe_strncpy(m->airline_name, "Unknown", sizeof(m->airline_name));
    safe_strncpy(m->aircraft_name, "Aircraft", sizeof(m->aircraft_name));
    safe_strncpy(m->callsign, "N/A", sizeof(m->callsign));

    m->souls_on_board = 0;
    m->distance_now_km = 0.0f;
    safe_strncpy(m->direction_cardinal, "N", sizeof(m->direction_cardinal));
    m->ground_speed_kmh = 0;
    m->altitude_ft = 0;
    m->vertical_rate_fpm = 0;

    m->radar_range_scale_km = 10;
}

void airtracker_model_update_from_json(airtracker_model_t* m, cJSON* json) {
    if (!json || !m) return;

    ESP_LOGI(TAG, "Updating model from JSON");

    // Route information
    safe_json_string(json, "origin_iata", m->route_origin, sizeof(m->route_origin));
    safe_json_string(json, "destination_iata", m->route_destination, sizeof(m->route_destination));
    safe_json_string(json, "callsign", m->callsign, sizeof(m->callsign));
    safe_json_string(json, "registration", m->registration, sizeof(m->registration));

    // Convert nautical miles to kilometers
    double distance_nm = safe_json_number(json, "distance_nm", 0.0);
    m->distance_now_km = distance_nm * 1.852;

    double remaining_nm = safe_json_number(json, "remaining_nm", 0.0);
    m->distance_remaining_km = remaining_nm * 1.852;

    // Convert knots to km/h
    double ground_speed_kt = safe_json_number(json, "ground_speed_kt", 0.0);
    m->ground_speed_kmh = (int)(ground_speed_kt * 1.852);

    m->altitude_ft = (int)safe_json_number(json, "altitude_ft", 0.0);
    m->vertical_rate_fpm = (int)safe_json_number(json, "vertical_rate_fpm", 0.0);

    // Bearing to cardinal direction
    int bearing = (int)safe_json_number(json, "bearing_deg", 0.0);
    safe_strncpy(m->direction_cardinal, bearing_to_cardinal(bearing), sizeof(m->direction_cardinal));
    m->radar_bearing_deg = bearing;

    // Souls on board
    m->souls_on_board = (int)safe_json_number(json, "souls_on_board", 0.0);
    if (m->souls_on_board == 0) {
        m->souls_on_board = (int)safe_json_number(json, "souls_on_board_max", 0.0);
    }

    // Radar data
    m->radar_range_km = m->distance_now_km;
    m->radar_rel_vertical_fpm = m->vertical_rate_fpm;
    m->radar_gs_kmh = m->ground_speed_kmh;
    m->radar_heading_deg = (int)safe_json_number(json, "track_deg", 0.0);
    m->radar_center_lat = safe_json_number(json, "latitude", 0.0);
    m->radar_center_lon = safe_json_number(json, "longitude", 0.0);

    // ETA calculation (simple for now)
    double eta_min = safe_json_number(json, "eta_min", 0.0);
    if (eta_min > 0) {
        int hours = (int)(eta_min / 60);
        int mins = (int)(eta_min) % 60;
        snprintf(m->eta_local_hhmm, sizeof(m->eta_local_hhmm), "%02d:%02d", hours, mins);
    } else {
        safe_strncpy(m->eta_local_hhmm, "--:--", sizeof(m->eta_local_hhmm));
    }

    // Lookups
    cJSON* lookups = cJSON_GetObjectItem(json, "lookups");
    if (cJSON_IsObject(lookups)) {
        // Aircraft lookup
        cJSON* aircraft = cJSON_GetObjectItem(lookups, "aircraft");
        if (cJSON_IsObject(aircraft)) {
            safe_json_string(aircraft, "name", m->aircraft_name, sizeof(m->aircraft_name));
            safe_json_string(aircraft, "icao", m->short_type, sizeof(m->short_type));

            // Use aircraft max seats if no souls_on_board
            if (m->souls_on_board == 0) {
                m->souls_on_board = (int)safe_json_number(aircraft, "seats_max", 0.0);
            }
        }

        // Airline lookup
        cJSON* airline = cJSON_GetObjectItem(lookups, "airline");
        if (cJSON_IsObject(airline)) {
            safe_json_string(airline, "name", m->airline_name, sizeof(m->airline_name));
            safe_json_string(airline, "logo_url", m->airline_logo_url, sizeof(m->airline_logo_url));
        }

        // Origin airport
        cJSON* origin_airport = cJSON_GetObjectItem(lookups, "origin_airport");
        if (cJSON_IsObject(origin_airport)) {
            safe_json_string(origin_airport, "name", m->origin_airport_name, sizeof(m->origin_airport_name));
            safe_json_string(origin_airport, "city", m->origin_city, sizeof(m->origin_city));
            safe_json_string(origin_airport, "region", m->origin_region, sizeof(m->origin_region));
        }

        // Destination airport
        cJSON* dest_airport = cJSON_GetObjectItem(lookups, "destination_airport");
        if (cJSON_IsObject(dest_airport)) {
            safe_json_string(dest_airport, "name", m->destination_airport_name, sizeof(m->destination_airport_name));
            safe_json_string(dest_airport, "city", m->destination_city, sizeof(m->destination_city));
            safe_json_string(dest_airport, "region", m->destination_region, sizeof(m->destination_region));
        }
    }

    // Media URLs
    safe_json_string(json, "airline_logo_url", m->airline_logo_url, sizeof(m->airline_logo_url));

    cJSON* media = cJSON_GetObjectItem(json, "media");
    if (cJSON_IsObject(media)) {
        safe_json_string(media, "plane_image", m->aircraft_photo_url, sizeof(m->aircraft_photo_url));

        // Try thumbnails if no plane_image
        if (strlen(m->aircraft_photo_url) == 0) {
            cJSON* thumbnails = cJSON_GetObjectItem(media, "thumbnails");
            if (cJSON_IsArray(thumbnails) && cJSON_GetArraySize(thumbnails) > 0) {
                cJSON* first_thumb = cJSON_GetArrayItem(thumbnails, 0);
                if (cJSON_IsString(first_thumb)) {
                    safe_strncpy(m->aircraft_photo_url, first_thumb->valuestring, sizeof(m->aircraft_photo_url));
                }
            }
        }
    }

    ESP_LOGI(TAG, "Model updated: %s -> %s, %s, %.1f km, %d km/h, %d ft",
             m->route_origin, m->route_destination, m->callsign,
             m->distance_now_km, m->ground_speed_kmh, m->altitude_ft);
}