#ifndef AIRTRACKER_SIM_UI_H
#define AIRTRACKER_SIM_UI_H

#include <lvgl.h>
#include "../model/model.h"

typedef enum {
  SCREEN_OVERVIEW = 0
} screen_id_t;

void ui_init(const model_t* m);
void ui_update(const model_t* m);
void ui_show_screen(screen_id_t id);
screen_id_t ui_current_screen(void);

#endif // AIRTRACKER_SIM_UI_H
