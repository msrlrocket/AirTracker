#include "json_loader.h"

#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

#include "../../third_party/parson/parson.h"

static void str_copy(char* dst, size_t cap, const char* src) {
  if(!dst || cap==0) return; if(!src) { dst[0]='\0'; return; }
  size_t n = strlen(src); if(n >= cap) n = cap - 1; memcpy(dst, src, n); dst[n] = '\0';
}

void json_loader_init(json_loader_t* jl, const char* path) {
  memset(jl, 0, sizeof(*jl));
  str_copy(jl->path, sizeof(jl->path), path ? path : "display/sim-lvgl/data/nearest.json");
  jl->last_mtime = 0;
  jl->active = false;
}

static void model_from_json(model_t* m, JSON_Object* root) {
  // route
  const char* ori = json_object_get_string(root, "origin_iata");
  const char* dst = json_object_get_string(root, "destination_iata");
  if(ori) str_copy(m->route_origin, sizeof(m->route_origin), ori);
  if(dst) str_copy(m->route_destination, sizeof(m->route_destination), dst);

  // airline/aircraft
  JSON_Object* lk = json_object_get_object(root, "lookups");
  if(lk){
    const char* al = NULL; const char* ac = NULL;
    JSON_Object* o_al = json_object_get_object(lk, "airline");
    JSON_Object* o_ac = json_object_get_object(lk, "aircraft");
    if(o_al) al = json_object_get_string(o_al, "name");
    if(o_ac) ac = json_object_get_string(o_ac, "name");
    if(al) str_copy(m->airline_name, sizeof(m->airline_name), al);
    if(ac) str_copy(m->aircraft_name, sizeof(m->aircraft_name), ac);
  }

  // callsign
  const char* cs = json_object_get_string(root, "callsign");
  str_copy(m->callsign, sizeof(m->callsign), cs ? cs : "");

  // numeric fields (unit conversions like YAML)
  if(json_object_has_value(root, "distance_nm")) {
    m->distance_now_km = (float)(json_object_get_number(root, "distance_nm") * 1.852);
  }
  if(json_object_has_value(root, "ground_speed_kt")) {
    m->ground_speed_kmh = (int)(json_object_get_number(root, "ground_speed_kt") * 1.852 + 0.5);
  }
  if(json_object_has_value(root, "altitude_ft")) m->altitude_ft = (int)json_object_get_number(root, "altitude_ft");
  if(json_object_has_value(root, "vertical_rate_fpm")) m->vertical_rate_fpm = (int)json_object_get_number(root, "vertical_rate_fpm");
  if(json_object_has_value(root, "remaining_nm")) m->distance_remaining_km = (float)(json_object_get_number(root, "remaining_nm") * 1.852);

  // ETA (mins to HH:MM) — we don't compute local time here; just approximate.
  if(json_object_has_value(root, "eta_min")) {
    int mins = (int)json_object_get_number(root, "eta_min");
    int hh = mins / 60; int mm = mins % 60;
    char buf[8]; snprintf(buf, sizeof(buf), "%02d:%02d", hh, mm);
    str_copy(m->eta_local_hhmm, sizeof(m->eta_local_hhmm), buf);
  }

  // direction: 8-point compass from bearing_deg
  if(json_object_has_value(root, "bearing_deg")) {
    int b = (int)json_object_get_number(root, "bearing_deg");
    static const char* dirs[8] = {"N","NE","E","SE","S","SW","W","NW"};
    int idx = ((b % 360) + 360) % 360; // normalize
    idx = (int)((idx + 22.5f) / 45.0f) % 8;
    str_copy(m->direction_cardinal, sizeof(m->direction_cardinal), dirs[idx]);
  }

  // souls_on_board - try multiple sources, prefer non-zero values
  m->souls_on_board = 0;
  if(json_object_has_value(root, "souls_on_board")) {
    m->souls_on_board = (int)json_object_get_number(root, "souls_on_board");
  }
  if(m->souls_on_board == 0 && json_object_has_value(root, "souls_on_board_max")) {
    m->souls_on_board = (int)json_object_get_number(root, "souls_on_board_max");
  }
  if(m->souls_on_board == 0 && lk) {
    // Try aircraft.seats_max from lookups
    JSON_Object* aircraft = json_object_get_object(lk, "aircraft");
    if(aircraft && json_object_has_value(aircraft, "seats_max")) {
      m->souls_on_board = (int)json_object_get_number(aircraft, "seats_max");
    }
  }

  // Airport information from lookups
  if(lk) {
    JSON_Object* origin_airport = json_object_get_object(lk, "origin_airport");
    JSON_Object* destination_airport = json_object_get_object(lk, "destination_airport");

    if(origin_airport) {
      const char* name = json_object_get_string(origin_airport, "name");
      const char* city = json_object_get_string(origin_airport, "city");
      const char* region = json_object_get_string(origin_airport, "region");
      if(name) str_copy(m->origin_airport_name, sizeof(m->origin_airport_name), name);
      if(city) str_copy(m->origin_city, sizeof(m->origin_city), city);
      if(region) str_copy(m->origin_region, sizeof(m->origin_region), region);
    }

    if(destination_airport) {
      const char* name = json_object_get_string(destination_airport, "name");
      const char* city = json_object_get_string(destination_airport, "city");
      const char* region = json_object_get_string(destination_airport, "region");
      if(name) str_copy(m->destination_airport_name, sizeof(m->destination_airport_name), name);
      if(city) str_copy(m->destination_city, sizeof(m->destination_city), city);
      if(region) str_copy(m->destination_region, sizeof(m->destination_region), region);
    }
  }

  // Images - airline logo and aircraft photo
  const char* airline_logo_url = json_object_get_string(root, "airline_logo_url");
  if(airline_logo_url) str_copy(m->airline_logo_url, sizeof(m->airline_logo_url), airline_logo_url);

  // Aircraft photo from media.plane_image
  JSON_Object* media = json_object_get_object(root, "media");
  if(media) {
    const char* plane_image = json_object_get_string(media, "plane_image");
    if(plane_image) str_copy(m->aircraft_photo_url, sizeof(m->aircraft_photo_url), plane_image);
  }

  // Radar
  if(json_object_has_value(root, "bearing_deg")) m->radar_bearing_deg = (int)json_object_get_number(root, "bearing_deg");
  if(json_object_has_value(root, "distance_nm")) m->radar_range_km = (float)(json_object_get_number(root, "distance_nm") * 1.852);
  if(json_object_has_value(root, "vertical_rate_fpm")) m->radar_rel_vertical_fpm = (int)json_object_get_number(root, "vertical_rate_fpm");
  if(json_object_has_value(root, "ground_speed_kt")) m->radar_gs_kmh = (int)(json_object_get_number(root, "ground_speed_kt") * 1.852 + 0.5);
  if(json_object_has_value(root, "track_deg")) m->radar_heading_deg = (int)json_object_get_number(root, "track_deg");
  if(json_object_has_value(root, "latitude")) m->radar_center_lat = (float)json_object_get_number(root, "latitude");
  if(json_object_has_value(root, "longitude")) m->radar_center_lon = (float)json_object_get_number(root, "longitude");

  // Optional: history[] → format inline into hist1..5
  JSON_Array* arr = json_object_get_array(root, "history");
  if(arr && json_array_get_count(arr) > 0) {
    for(size_t i=0;i<5;i++){
      if(i >= json_array_get_count(arr)) break;
      JSON_Object* row = json_array_get_object(arr, i); if(!row) break;
      const char* flight = json_object_get_string(row, "flight"); if(!flight) flight="";
      const char* origin = json_object_get_string(row, "origin"); if(!origin) origin="";
      const char* dest   = json_object_get_string(row, "destination"); if(!dest) dest="Unknown";
      const char* date   = json_object_get_string(row, "date_yyyy_mm_dd"); if(!date) date="";
      const char* block  = json_object_get_string(row, "block_time_hhmm"); if(!block) block="";
      const char* eta    = json_object_get_string(row, "arr_or_eta_hhmm"); if(!eta) eta="";
      char buf[128]; snprintf(buf, sizeof(buf), "%s  %s→%s  %s  %s  %s", flight, origin, dest, date, block, eta);
      switch(i){
        case 0: str_copy(m->hist1, sizeof(m->hist1), buf); break;
        case 1: str_copy(m->hist2, sizeof(m->hist2), buf); break;
        case 2: str_copy(m->hist3, sizeof(m->hist3), buf); break;
        case 3: str_copy(m->hist4, sizeof(m->hist4), buf); break;
        case 4: str_copy(m->hist5, sizeof(m->hist5), buf); break;
      }
    }
  }
}

bool json_loader_poll(json_loader_t* jl, model_t* m) {
  struct stat st; if(stat(jl->path, &st) != 0) return false;
  long mt = (long)st.st_mtime; if(mt == jl->last_mtime) return false;
  jl->last_mtime = mt;

  JSON_Value* v = json_parse_file(jl->path);
  if(!v) return false;
  JSON_Object* root = json_value_get_object(v);
  if(!root){ json_value_free(v); return false; }
  model_from_json(m, root);
  json_value_free(v);
  jl->active = true;
  return true;
}
