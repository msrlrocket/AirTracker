#ifndef AIRTRACKER_UI_H
#define AIRTRACKER_UI_H

#include <lvgl.h>
#include "airtracker_model.h"

typedef enum {
    SCREEN_OVERVIEW = 0
} screen_id_t;

void airtracker_ui_init(const airtracker_model_t* m);
void airtracker_ui_update(const airtracker_model_t* m);
void airtracker_ui_show_screen(screen_id_t id);
screen_id_t airtracker_ui_current_screen(void);

#endif // AIRTRACKER_UI_H