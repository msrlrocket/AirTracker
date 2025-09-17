#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <unistd.h>
#include <pthread.h>

#include <lvgl.h>

// lv_drivers (SDL display + input)
#include "sdl/sdl.h"

#include "ui/ui.h"
#include "model/model.h"
#include "io/json_loader.h"

static void* tick_thread(void* arg) {
  (void)arg;
  while(1) {
    lv_tick_inc(1);
    usleep(1000);
  }
  return NULL;
}

int main(void) {
  lv_init();

  // Configure SDL monitor
  sdl_init();

  // Draw buffer(s)
  static lv_color_t buf1[320 * 60]; // ~1/4 screen
  static lv_disp_draw_buf_t draw_buf;
  lv_disp_draw_buf_init(&draw_buf, buf1, NULL, sizeof(buf1)/sizeof(buf1[0]));

  // Display driver
  lv_disp_drv_t disp_drv;
  lv_disp_drv_init(&disp_drv);
  disp_drv.hor_res = 320;
  disp_drv.ver_res = 240;
  disp_drv.flush_cb = sdl_display_flush;
  disp_drv.draw_buf = &draw_buf;
  lv_disp_t* disp = lv_disp_drv_register(&disp_drv);
  (void) disp;

  // Mouse as touch
  lv_indev_drv_t indev_drv;
  lv_indev_drv_init(&indev_drv);
  indev_drv.type = LV_INDEV_TYPE_POINTER;
  indev_drv.read_cb = sdl_mouse_read;
  lv_indev_t* mouse_indev = lv_indev_drv_register(&indev_drv);
  (void)mouse_indev;

  // Keyboard (optional key nav)
  lv_indev_drv_t kb_drv;
  lv_indev_drv_init(&kb_drv);
  kb_drv.type = LV_INDEV_TYPE_KEYPAD;
  kb_drv.read_cb = sdl_keyboard_read;
  lv_indev_t* kb_indev = lv_indev_drv_register(&kb_drv);
  (void)kb_indev;

  // Mouse wheel for fun (not strictly needed)
  lv_indev_drv_t mw_drv;
  lv_indev_drv_init(&mw_drv);
  mw_drv.type = LV_INDEV_TYPE_ENCODER;
  mw_drv.read_cb = sdl_mousewheel_read;
  lv_indev_t* mw_indev = lv_indev_drv_register(&mw_drv);
  (void)mw_indev;

  // Start LVGL tick thread
  pthread_t th;
  pthread_create(&th, NULL, tick_thread, NULL);
  pthread_detach(th);

  // Model + UI
  model_t model;
  model_init(&model);
  // Optional JSON file updates
  const char* json_path = getenv("SIM_JSON_PATH");
  json_loader_t jl; json_loader_init(&jl, json_path);
  ui_init(&model);

  // Event loop
  uint64_t last = 0;
  // Slow UI/data refresh: default every 5000 ms (override with SIM_UPDATE_MS)
  int update_interval_ms = 5000;
  const char* upd_env = getenv("SIM_UPDATE_MS");
  if (upd_env) {
    int v = atoi(upd_env);
    if (v >= 1000 && v <= 20000) update_interval_ms = v;
  }
  int accum_ms = 0;
  while(1) {
    lv_timer_handler();
    usleep(5000);
    // crude dt; just tick model every ~50 ms
    last += 5;
    if(last >= 50) {
      last = 0;
      // Accumulate time; poll + update on interval
      accum_ms += 50;
      model_tick(&model, 50);
      if (accum_ms >= update_interval_ms) {
        accum_ms = 0;
        // Check file changes at the same cadence; still updates UI even if unchanged
        (void) json_loader_poll(&jl, &model);
        ui_update(&model);
      }
    }
  }

  return 0;
}
