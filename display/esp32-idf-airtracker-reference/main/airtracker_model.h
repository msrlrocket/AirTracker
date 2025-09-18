#ifndef AIRTRACKER_MODEL_H
#define AIRTRACKER_MODEL_H

#include <stdbool.h>
#include <cJSON.h>

typedef struct {
    // Route / progress
    char route_origin[8];
    char route_destination[8];
    float distance_remaining_km;
    char eta_local_hhmm[8];

    // Airport information
    char origin_airport_name[64];
    char origin_city[32];
    char origin_region[32];
    char destination_airport_name[64];
    char destination_city[32];
    char destination_region[32];

    // Airline / aircraft
    char airline_name[64];
    char aircraft_name[64];
    char callsign[16];
    char airline_logo_url[256];
    char aircraft_photo_url[256];

    // Overview metrics
    int souls_on_board;
    float distance_now_km;
    char direction_cardinal[4];
    int ground_speed_kmh;
    int altitude_ft;
    int vertical_rate_fpm;

    // Gallery header
    char registration[16];
    char short_type[16];

    // History rows
    char hist1[128];
    char hist2[128];
    char hist3[128];
    char hist4[128];
    char hist5[128];

    // Radar model
    int radar_bearing_deg;
    float radar_range_km;
    int radar_rel_vertical_fpm;
    int radar_gs_kmh;
    int radar_heading_deg;
    float radar_center_lat;
    float radar_center_lon;
    int radar_range_scale_km;
} airtracker_model_t;

void airtracker_model_init(airtracker_model_t* m);
void airtracker_model_update_from_json(airtracker_model_t* m, cJSON* json);

#endif // AIRTRACKER_MODEL_H