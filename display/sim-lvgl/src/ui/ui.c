#include "ui.h"

#include <stdio.h>
#include <math.h>
#include <string.h>
#include <stdlib.h>
#include <curl/curl.h>

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

// Icons (using Unicode symbols)
#define ICON_PLANE "✈"
#define ICON_ALTITUDE "🔺"
#define ICON_SPEED "⚡"
#define ICON_DISTANCE "📍"
#define ICON_PEOPLE "👥"
#define ICON_ARROW_UP "↗"
#define ICON_ARROW_DOWN "↘"
#define ICON_ARROW_LEVEL "→"

// Screens
static lv_obj_t* scr_overview;

// Overview refs
static lv_obj_t* lb_route;
static lv_obj_t* lb_eta;
static lv_obj_t* lb_dest_distance;
static lv_obj_t* lb_aircraft_bearing;
static lv_obj_t* lb_airline;
static lv_obj_t* lb_airline_name;
static lv_obj_t* lb_callsign;
static lv_obj_t* lb_plane_caption;
static lv_obj_t* lb_stats_left;
static lv_obj_t* lb_speed;
static lv_obj_t* lb_souls;
static lv_obj_t* lb_alt_vvi;
static lv_obj_t* lb_climb_rate;
static lv_obj_t* lb_origin_city;
static lv_obj_t* lb_dest_city;

// Text rotation state
static uint32_t last_text_change = 0;
static bool show_airport_name = true;
static lv_anim_t origin_fade_anim;
static lv_anim_t dest_fade_anim;

// Image widgets
static lv_obj_t* airline_logo_img;
static lv_obj_t* airline_logo_fallback;
static lv_obj_t* aircraft_photo_img;
static lv_obj_t* aircraft_photo_fallback;

// Image loading state
static char* downloaded_airline_logo = NULL;
static char* downloaded_aircraft_photo = NULL;
static lv_img_dsc_t airline_logo_dsc;
static lv_img_dsc_t aircraft_photo_dsc;


static screen_id_t current = SCREEN_OVERVIEW;

// Structure to hold downloaded image data
typedef struct {
  unsigned char* data;
  size_t size;
} image_data_t;

// Callback for curl to write downloaded data
static size_t write_image_data(void* contents, size_t size, size_t nmemb, void* userp) {
  image_data_t* img_data = (image_data_t*)userp;
  size_t total_size = size * nmemb;
  img_data->data = realloc(img_data->data, img_data->size + total_size);
  if (img_data->data) {
    memcpy(img_data->data + img_data->size, contents, total_size);
    img_data->size += total_size;
  }
  return total_size;
}

// Download image from URL
static bool download_image(const char* url, image_data_t* img_data) {
  CURL* curl;
  CURLcode res;
  bool success = false;

  img_data->data = NULL;
  img_data->size = 0;

  curl = curl_easy_init();
  if (curl) {
    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_image_data);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, img_data);
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 10L);
    curl_easy_setopt(curl, CURLOPT_USERAGENT, "AirTracker/1.0");

    res = curl_easy_perform(curl);
    if (res == CURLE_OK) {
      long response_code;
      curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &response_code);
      if (response_code == 200) {
        success = true;
      }
    }
    curl_easy_cleanup(curl);
  }

  if (!success && img_data->data) {
    free(img_data->data);
    img_data->data = NULL;
    img_data->size = 0;
  }

  return success;
}

// Function to load image from URL
static void load_image_from_url(lv_obj_t* img_widget, lv_obj_t* fallback_widget, const char* url) {
  if (!url || strlen(url) == 0) {
    // No URL provided, show fallback
    lv_obj_add_flag(img_widget, LV_OBJ_FLAG_HIDDEN);
    lv_obj_clear_flag(fallback_widget, LV_OBJ_FLAG_HIDDEN);
    return;
  }

  printf("Loading image from: %s\n", url);

  // Determine file extension from URL
  const char* ext = ".png";  // default
  if (strstr(url, ".jpg") || strstr(url, ".jpeg")) {
    ext = ".jpg";
  }

  // Create unique filename in current directory
  char local_filename[256];
  snprintf(local_filename, sizeof(local_filename), "img_%p%s", (void*)img_widget, ext);

  // Download the image
  image_data_t img_data;
  if (download_image(url, &img_data)) {
    printf("Downloaded %zu bytes, saving to %s\n", img_data.size, local_filename);

    // Save to local file
    FILE* local_file = fopen(local_filename, "wb");
    if (local_file) {
      fwrite(img_data.data, 1, img_data.size, local_file);
      fclose(local_file);

      // Set image source to local file
      lv_img_set_src(img_widget, local_filename);
      lv_obj_clear_flag(img_widget, LV_OBJ_FLAG_HIDDEN);
      lv_obj_add_flag(fallback_widget, LV_OBJ_FLAG_HIDDEN);

      printf("Image loaded successfully: %s\n", local_filename);
    } else {
      printf("Failed to save image to file\n");
      lv_obj_add_flag(img_widget, LV_OBJ_FLAG_HIDDEN);
      lv_obj_clear_flag(fallback_widget, LV_OBJ_FLAG_HIDDEN);
    }

    free(img_data.data);
  } else {
    printf("Failed to download image from %s\n", url);
    // Show fallback
    lv_obj_add_flag(img_widget, LV_OBJ_FLAG_HIDDEN);
    lv_obj_clear_flag(fallback_widget, LV_OBJ_FLAG_HIDDEN);
  }
}


static lv_obj_t* create_card(lv_obj_t* parent, int x, int y, int w, int h) {
  lv_obj_t* card = lv_obj_create(parent);
  lv_obj_set_pos(card, x, y);
  lv_obj_set_size(card, w, h);
  lv_obj_set_style_bg_color(card, UI_COLOR_BG_CARD, 0);
  lv_obj_set_style_bg_opa(card, LV_OPA_COVER, 0);
  lv_obj_set_style_border_color(card, UI_COLOR_BORDER, 0);
  lv_obj_set_style_border_width(card, 1, 0);
  lv_obj_set_style_radius(card, 8, 0);
  lv_obj_set_style_shadow_width(card, 8, 0);
  lv_obj_set_style_shadow_color(card, lv_color_black(), 0);
  lv_obj_set_style_shadow_opa(card, LV_OPA_30, 0);
  return card;
}

static lv_obj_t* create_stat_box(lv_obj_t* parent, int x, int y, const char* icon, const char* label, const char* value, lv_color_t accent_color) {
  lv_obj_t* box = create_card(parent, x, y, 92, 48);

  // Icon
  lv_obj_t* icon_label = lv_label_create(box);
  lv_label_set_text(icon_label, icon);
  lv_obj_set_style_text_font(icon_label, &lv_font_montserrat_16, 0);
  lv_obj_set_style_text_color(icon_label, accent_color, 0);
  lv_obj_set_pos(icon_label, 8, 6);

  // Label
  lv_obj_t* label_obj = lv_label_create(box);
  lv_label_set_text(label_obj, label);
  lv_obj_set_style_text_font(label_obj, &lv_font_montserrat_10, 0);
  lv_obj_set_style_text_color(label_obj, UI_COLOR_TEXT_SECONDARY, 0);
  lv_obj_set_pos(label_obj, 8, 20);

  // Value
  lv_obj_t* value_obj = lv_label_create(box);
  lv_label_set_text(value_obj, value);
  lv_obj_set_style_text_font(value_obj, &lv_font_montserrat_14, 0);
  lv_obj_set_style_text_color(value_obj, UI_COLOR_TEXT_PRIMARY, 0);
  lv_obj_set_pos(value_obj, 8, 30);

  return value_obj; // Return value label for updates
}

static void build_overview(const model_t* m) {
  scr_overview = lv_obj_create(NULL);
  lv_obj_set_size(scr_overview, 320, 240);
  lv_obj_set_style_bg_color(scr_overview, UI_COLOR_BG_DARK, 0);
  lv_obj_set_style_text_color(scr_overview, UI_COLOR_TEXT_PRIMARY, 0);
  lv_obj_set_style_border_width(scr_overview, 0, 0);

  // Top left: Route with airport details
  lb_route = lv_label_create(scr_overview);
  lv_obj_set_pos(lb_route, 5, 5);
  lv_label_set_text(lb_route, "SEA -> SFO");
  lv_obj_set_style_text_font(lb_route, &lv_font_montserrat_16, 0);
  lv_obj_set_style_text_color(lb_route, UI_COLOR_TEXT_PRIMARY, 0);

  // Origin city/state - fading text rotation
  lb_origin_city = lv_label_create(scr_overview);
  lv_obj_set_pos(lb_origin_city, 5, 23);
  lv_obj_set_width(lb_origin_city, 220);
  lv_label_set_text(lb_origin_city, "");
  lv_obj_set_style_text_font(lb_origin_city, &lv_font_montserrat_10, 0);
  lv_obj_set_style_text_color(lb_origin_city, UI_COLOR_TEXT_SECONDARY, 0);
  lv_label_set_long_mode(lb_origin_city, LV_LABEL_LONG_CLIP);

  // Destination city/state - fading text rotation
  lb_dest_city = lv_label_create(scr_overview);
  lv_obj_set_pos(lb_dest_city, 5, 33);
  lv_obj_set_width(lb_dest_city, 220);
  lv_label_set_text(lb_dest_city, "");
  lv_obj_set_style_text_font(lb_dest_city, &lv_font_montserrat_10, 0);
  lv_obj_set_style_text_color(lb_dest_city, UI_COLOR_TEXT_SECONDARY, 0);
  lv_label_set_long_mode(lb_dest_city, LV_LABEL_LONG_CLIP);

  // Top right: Distance to destination and ETA (matching font sizes)
  lb_dest_distance = lv_label_create(scr_overview);
  lv_obj_set_pos(lb_dest_distance, 220, 5);
  lv_obj_set_width(lb_dest_distance, 95);
  lv_obj_set_style_text_align(lb_dest_distance, LV_TEXT_ALIGN_RIGHT, 0);
  lv_label_set_text(lb_dest_distance, "412 km to dest");
  lv_obj_set_style_text_font(lb_dest_distance, &lv_font_montserrat_12, 0);
  lv_obj_set_style_text_color(lb_dest_distance, UI_COLOR_TEXT_PRIMARY, 0);

  lb_eta = lv_label_create(scr_overview);
  lv_obj_set_pos(lb_eta, 220, 20);
  lv_obj_set_width(lb_eta, 95);
  lv_obj_set_style_text_align(lb_eta, LV_TEXT_ALIGN_RIGHT, 0);
  lv_label_set_text(lb_eta, "ETA 18:23");
  lv_obj_set_style_text_font(lb_eta, &lv_font_montserrat_10, 0);
  lv_obj_set_style_text_color(lb_eta, UI_COLOR_TEXT_SECONDARY, 0);

  // Center layout: Airline logo | Aircraft info | Plane photo - adjusted for stacked cities

  // Airline logo image
  airline_logo_img = lv_img_create(scr_overview);
  lv_obj_set_pos(airline_logo_img, 5, 65);
  lv_obj_set_size(airline_logo_img, 70, 70);

  // Fallback square if no image available
  airline_logo_fallback = lv_obj_create(scr_overview);
  lv_obj_set_size(airline_logo_fallback, 70, 70);
  lv_obj_set_pos(airline_logo_fallback, 5, 65);
  lv_obj_set_style_bg_color(airline_logo_fallback, UI_COLOR_ACCENT, 0);
  lv_obj_set_style_bg_opa(airline_logo_fallback, LV_OPA_20, 0);
  lv_obj_set_style_border_width(airline_logo_fallback, 1, 0);
  lv_obj_set_style_border_color(airline_logo_fallback, UI_COLOR_ACCENT, 0);
  lv_obj_set_style_radius(airline_logo_fallback, 4, 0);

  lv_obj_t* logo_text = lv_label_create(airline_logo_fallback);
  lv_label_set_text(logo_text, "No\\ndata");
  lv_obj_set_style_text_font(logo_text, &lv_font_montserrat_12, 0);
  lv_obj_set_style_text_color(logo_text, UI_COLOR_TEXT_SECONDARY, 0);
  lv_obj_set_style_text_align(logo_text, LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_center(logo_text);

  // Initially hide the image and show the fallback
  lv_obj_add_flag(airline_logo_img, LV_OBJ_FLAG_HIDDEN);
  lv_obj_clear_flag(airline_logo_fallback, LV_OBJ_FLAG_HIDDEN);

  // Aircraft type - BIGGER text
  lb_airline = lv_label_create(scr_overview);
  lv_obj_set_pos(lb_airline, 85, 70);
  lv_obj_set_width(lb_airline, 150);
  lv_label_set_text(lb_airline, "Boeing 737-800");
  lv_obj_set_style_text_font(lb_airline, &lv_font_montserrat_16, 0);
  lv_obj_set_style_text_color(lb_airline, UI_COLOR_TEXT_PRIMARY, 0);

  // Airline name below
  lb_airline_name = lv_label_create(scr_overview);
  lv_obj_set_pos(lb_airline_name, 85, 92);
  lv_obj_set_width(lb_airline_name, 150);
  lv_label_set_text(lb_airline_name, "Alaska Airlines");
  lv_obj_set_style_text_font(lb_airline_name, &lv_font_montserrat_12, 0);
  lv_obj_set_style_text_color(lb_airline_name, UI_COLOR_ACCENT, 0);

  // Callsign below that
  lb_callsign = lv_label_create(scr_overview);
  lv_obj_set_pos(lb_callsign, 85, 110);
  lv_obj_set_width(lb_callsign, 150);
  lv_label_set_text(lb_callsign, "ASA345");
  lv_obj_set_style_text_font(lb_callsign, &lv_font_montserrat_10, 0);
  lv_obj_set_style_text_color(lb_callsign, UI_COLOR_TEXT_SECONDARY, 0);

  // Aircraft photo image
  aircraft_photo_img = lv_img_create(scr_overview);
  lv_obj_set_pos(aircraft_photo_img, 240, 65);
  lv_obj_set_size(aircraft_photo_img, 75, 70);

  // Fallback rectangle if no image available
  aircraft_photo_fallback = lv_obj_create(scr_overview);
  lv_obj_set_size(aircraft_photo_fallback, 75, 70);
  lv_obj_set_pos(aircraft_photo_fallback, 240, 65);
  lv_obj_set_style_bg_color(aircraft_photo_fallback, UI_COLOR_BG_DARK, 0);
  lv_obj_set_style_border_width(aircraft_photo_fallback, 1, 0);
  lv_obj_set_style_border_color(aircraft_photo_fallback, UI_COLOR_BORDER, 0);
  lv_obj_set_style_radius(aircraft_photo_fallback, 4, 0);

  lv_obj_t* plane_icon = lv_label_create(aircraft_photo_fallback);
  lv_label_set_text(plane_icon, "PLANE");
  lv_obj_set_style_text_font(plane_icon, &lv_font_montserrat_12, 0);
  lv_obj_set_style_text_color(plane_icon, UI_COLOR_TEXT_SECONDARY, 0);
  lv_obj_center(plane_icon);

  // Initially hide the image and show the fallback
  lv_obj_add_flag(aircraft_photo_img, LV_OBJ_FLAG_HIDDEN);
  lv_obj_clear_flag(aircraft_photo_fallback, LV_OBJ_FLAG_HIDDEN);

  // Bottom section: Three columns - adjusted

  // Left: Speed and distance from origin
  lb_speed = lv_label_create(scr_overview);
  lv_obj_set_pos(lb_speed, 5, 145);
  lv_obj_set_width(lb_speed, 100);
  lv_label_set_text(lb_speed, "713 km/h");
  lv_obj_set_style_text_font(lb_speed, &lv_font_montserrat_12, 0);
  lv_obj_set_style_text_color(lb_speed, UI_COLOR_TEXT_PRIMARY, 0);

  lb_stats_left = lv_label_create(scr_overview);
  lv_obj_set_pos(lb_stats_left, 5, 160);
  lv_obj_set_width(lb_stats_left, 100);
  lv_label_set_text(lb_stats_left, "34.2 km SW");
  lv_obj_set_style_text_font(lb_stats_left, &lv_font_montserrat_10, 0);
  lv_obj_set_style_text_color(lb_stats_left, UI_COLOR_TEXT_SECONDARY, 0);

  // Center: Souls count (smaller)
  lb_souls = lv_label_create(scr_overview);
  lv_obj_set_pos(lb_souls, 140, 150);
  lv_label_set_text(lb_souls, "178");
  lv_obj_set_style_text_font(lb_souls, &lv_font_montserrat_14, 0);
  lv_obj_set_style_text_color(lb_souls, UI_COLOR_TEXT_PRIMARY, 0);

  // Right: Altitude and climb rate (matching font sizes)
  lb_alt_vvi = lv_label_create(scr_overview);
  lv_obj_set_pos(lb_alt_vvi, 180, 145);
  lv_obj_set_width(lb_alt_vvi, 135);
  lv_obj_set_style_text_align(lb_alt_vvi, LV_TEXT_ALIGN_RIGHT, 0);
  lv_label_set_text(lb_alt_vvi, "10,975 ft ▲");
  lv_obj_set_style_text_font(lb_alt_vvi, &lv_font_montserrat_12, 0);
  lv_obj_set_style_text_color(lb_alt_vvi, UI_COLOR_TEXT_PRIMARY, 0);

  lb_climb_rate = lv_label_create(scr_overview);
  lv_obj_set_pos(lb_climb_rate, 180, 160);
  lv_obj_set_width(lb_climb_rate, 135);
  lv_obj_set_style_text_align(lb_climb_rate, LV_TEXT_ALIGN_RIGHT, 0);
  lv_label_set_text(lb_climb_rate, "+1,240 fpm");
  lv_obj_set_style_text_font(lb_climb_rate, &lv_font_montserrat_10, 0);
  lv_obj_set_style_text_color(lb_climb_rate, UI_COLOR_SUCCESS, 0);


  // Initial population
  (void)m;
}




void ui_init(const model_t* m) {
  // Initialize curl for image downloading
  curl_global_init(CURL_GLOBAL_DEFAULT);

  build_overview(m);
  ui_show_screen(SCREEN_OVERVIEW);
  ui_update(m);
}

static void set_label_fmt(lv_obj_t* lb, const char* fmt, ...) {
  static char buf[256];
  va_list ap; va_start(ap, fmt);
  vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  lv_label_set_text(lb, buf);
}

static const char* get_state_abbreviation(const char* state_name) {
  if (!state_name) return "";

  // Common US state name to abbreviation mapping
  static const struct {
    const char* name;
    const char* abbrev;
  } states[] = {
    {"Alabama", "AL"}, {"Alaska", "AK"}, {"Arizona", "AZ"}, {"Arkansas", "AR"},
    {"California", "CA"}, {"Colorado", "CO"}, {"Connecticut", "CT"}, {"Delaware", "DE"},
    {"Florida", "FL"}, {"Georgia", "GA"}, {"Hawaii", "HI"}, {"Idaho", "ID"},
    {"Illinois", "IL"}, {"Indiana", "IN"}, {"Iowa", "IA"}, {"Kansas", "KS"},
    {"Kentucky", "KY"}, {"Louisiana", "LA"}, {"Maine", "ME"}, {"Maryland", "MD"},
    {"Massachusetts", "MA"}, {"Michigan", "MI"}, {"Minnesota", "MN"}, {"Mississippi", "MS"},
    {"Missouri", "MO"}, {"Montana", "MT"}, {"Nebraska", "NE"}, {"Nevada", "NV"},
    {"New Hampshire", "NH"}, {"New Jersey", "NJ"}, {"New Mexico", "NM"}, {"New York", "NY"},
    {"North Carolina", "NC"}, {"North Dakota", "ND"}, {"Ohio", "OH"}, {"Oklahoma", "OK"},
    {"Oregon", "OR"}, {"Pennsylvania", "PA"}, {"Rhode Island", "RI"}, {"South Carolina", "SC"},
    {"South Dakota", "SD"}, {"Tennessee", "TN"}, {"Texas", "TX"}, {"Utah", "UT"},
    {"Vermont", "VT"}, {"Virginia", "VA"}, {"Washington", "WA"}, {"West Virginia", "WV"},
    {"Wisconsin", "WI"}, {"Wyoming", "WY"}
  };

  for (size_t i = 0; i < sizeof(states) / sizeof(states[0]); i++) {
    if (strcmp(state_name, states[i].name) == 0) {
      return states[i].abbrev;
    }
  }

  return state_name; // Return original if not found
}

static void fade_anim_cb(void* obj, int32_t value) {
  lv_obj_set_style_opa(obj, value, 0);
}

static void update_rotating_text(const model_t* m) {
  uint32_t now = lv_tick_get();

  // Change text every 3 seconds
  if (now - last_text_change > 3000) {
    show_airport_name = !show_airport_name;
    last_text_change = now;

    // Start fade out animation
    lv_anim_init(&origin_fade_anim);
    lv_anim_set_var(&origin_fade_anim, lb_origin_city);
    lv_anim_set_values(&origin_fade_anim, LV_OPA_COVER, LV_OPA_TRANSP);
    lv_anim_set_time(&origin_fade_anim, 300);
    lv_anim_set_exec_cb(&origin_fade_anim, fade_anim_cb);
    lv_anim_set_ready_cb(&origin_fade_anim, NULL);
    lv_anim_start(&origin_fade_anim);

    lv_anim_init(&dest_fade_anim);
    lv_anim_set_var(&dest_fade_anim, lb_dest_city);
    lv_anim_set_values(&dest_fade_anim, LV_OPA_COVER, LV_OPA_TRANSP);
    lv_anim_set_time(&dest_fade_anim, 300);
    lv_anim_set_exec_cb(&dest_fade_anim, fade_anim_cb);
    lv_anim_set_ready_cb(&dest_fade_anim, NULL);
    lv_anim_start(&dest_fade_anim);
  }

  // Update text content based on current state
  char origin_text[128] = "";
  char dest_text[128] = "";

  if (show_airport_name) {
    // Show airport names
    if (strlen(m->origin_airport_name) > 0) {
      snprintf(origin_text, sizeof(origin_text), "%s", m->origin_airport_name);
    }
    if (strlen(m->destination_airport_name) > 0) {
      snprintf(dest_text, sizeof(dest_text), "%s", m->destination_airport_name);
    }
  } else {
    // Show city, state
    if (strlen(m->origin_city) > 0) {
      snprintf(origin_text, sizeof(origin_text), "%s", m->origin_city);
      if (strlen(m->origin_region) > 0) {
        const char* state_abbrev = get_state_abbreviation(m->origin_region);
        strncat(origin_text, ", ", sizeof(origin_text) - strlen(origin_text) - 1);
        strncat(origin_text, state_abbrev, sizeof(origin_text) - strlen(origin_text) - 1);
      }
    }
    if (strlen(m->destination_city) > 0) {
      snprintf(dest_text, sizeof(dest_text), "%s", m->destination_city);
      if (strlen(m->destination_region) > 0) {
        const char* state_abbrev = get_state_abbreviation(m->destination_region);
        strncat(dest_text, ", ", sizeof(dest_text) - strlen(dest_text) - 1);
        strncat(dest_text, state_abbrev, sizeof(dest_text) - strlen(dest_text) - 1);
      }
    }
  }

  // Update labels if animation is not running or text changed
  if (now - last_text_change > 300) {
    lv_label_set_text(lb_origin_city, origin_text);
    lv_label_set_text(lb_dest_city, dest_text);

    // Fade back in
    lv_obj_set_style_opa(lb_origin_city, LV_OPA_COVER, 0);
    lv_obj_set_style_opa(lb_dest_city, LV_OPA_COVER, 0);
  }
}

void ui_update(const model_t* m) {
  // Top bar
  set_label_fmt(lb_route, "%s -> %s", m->route_origin, m->route_destination);
  set_label_fmt(lb_eta, "ETA %s", m->eta_local_hhmm);

  // Top right - distance to destination and ETA
  set_label_fmt(lb_dest_distance, "%.0f km to dest", m->distance_remaining_km);

  // Aircraft info - separate lines with adaptive font sizing
  set_label_fmt(lb_airline, "%s", m->aircraft_name);

  // Check if aircraft name is too long and use smaller font
  lv_point_t text_size;
  lv_txt_get_size(&text_size, m->aircraft_name, &lv_font_montserrat_16, 0, 0, LV_COORD_MAX, LV_TEXT_FLAG_NONE);
  if (text_size.x > 150) {
    // Text is too wide, use smaller font
    lv_obj_set_style_text_font(lb_airline, &lv_font_montserrat_12, 0);
  } else {
    // Text fits, use normal font
    lv_obj_set_style_text_font(lb_airline, &lv_font_montserrat_16, 0);
  }

  set_label_fmt(lb_airline_name, "%s", m->airline_name);
  set_label_fmt(lb_callsign, "%s", m->callsign);

  // Load images from URLs if available
  printf("Checking images: airline_logo_url='%s', aircraft_photo_url='%s'\n",
         m->airline_logo_url, m->aircraft_photo_url);
  load_image_from_url(airline_logo_img, airline_logo_fallback, m->airline_logo_url);
  load_image_from_url(aircraft_photo_img, aircraft_photo_fallback, m->aircraft_photo_url);

  // Bottom left - speed and distance from current location
  set_label_fmt(lb_speed, "%d km/h", m->ground_speed_kmh);
  set_label_fmt(lb_stats_left, "%.1f km %s", m->distance_now_km, m->direction_cardinal);

  // Bottom center/right
  set_label_fmt(lb_souls, "%d", m->souls_on_board);

  const char* vdir = (m->vertical_rate_fpm > 0) ? "▲" : (m->vertical_rate_fpm < 0 ? "▼" : "→");
  set_label_fmt(lb_alt_vvi, "%d ft %s", m->altitude_ft, vdir);
  set_label_fmt(lb_climb_rate, "%+d fpm", m->vertical_rate_fpm);

  // Update rotating airport/city text
  update_rotating_text(m);
}

void ui_show_screen(screen_id_t id) {
  current = id;
  switch (id) {
    case SCREEN_OVERVIEW: lv_scr_load(scr_overview); break;
    default: break;
  }
}

screen_id_t ui_current_screen(void) { return current; }
