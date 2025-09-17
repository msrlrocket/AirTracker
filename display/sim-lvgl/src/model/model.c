#include "model.h"

#include <stdio.h>
#include <string.h>

void model_init(model_t* m) {
  memset(m, 0, sizeof(*m));

  // Route / progress
  strcpy(m->route_origin, "SEA");
  strcpy(m->route_destination, "SFO");
  m->distance_remaining_km = 412.0f;
  strcpy(m->eta_local_hhmm, "18:23");

  // Airline / aircraft
  strcpy(m->airline_name, "Alaska Airlines");
  strcpy(m->aircraft_name, "Boeing 737-800");
  strcpy(m->callsign, "ASA345");
  strcpy(m->airline_logo_url, "https://example.com/logos/alaska_airlines.png");
  strcpy(m->aircraft_photo_url, "https://example.com/photos/boeing_737_800.jpg");

  // Overview metrics
  m->souls_on_board = 178;
  m->distance_now_km = 34.2f;
  strcpy(m->direction_cardinal, "SW");
  m->ground_speed_kmh = 713;
  m->altitude_ft = 10975;
  m->vertical_rate_fpm = 1240;

  // Gallery header
  strcpy(m->registration, "N123AS");
  strcpy(m->short_type, "B738");

  // History rows
  strcpy(m->hist1, "ASA345  SEA→SFO  2025-09-13  02:07  Arr 18:12");
  strcpy(m->hist2, "ASA862  PDX→SEA  2025-09-12  00:40  Arr 15:21");
  strcpy(m->hist3, "ASA217  SFO→SEA  2025-09-10  02:03  Arr 19:03");
  strcpy(m->hist4, "ASA1189 LAX→SFO  2025-09-08  01:18  Arr 11:47");
  strcpy(m->hist5, "ASA345  SEA→SFO  2025-09-05  02:05  Arr 17:59");

  // Radar
  m->radar_bearing_deg = 224;
  m->radar_range_km = 4.7f;
  m->radar_rel_vertical_fpm = 1200;
  m->radar_gs_kmh = 712;
  m->radar_heading_deg = 220;
  m->radar_center_lat = 47.61f;
  m->radar_center_lon = -122.33f;
  m->radar_range_scale_km = 10;
}

void model_tick(model_t* m, unsigned ms) {
  // In production mode, model data comes from JSON/MQTT - no animation needed
  (void)m;
  (void)ms;
}
