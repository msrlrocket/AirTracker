#ifndef LV_CONF_H
#define LV_CONF_H

/* Minimal LVGL v8 configuration for PC simulator */

#define LV_USE_LOG 1
#if LV_USE_LOG
#  define LV_LOG_LEVEL LV_LOG_LEVEL_WARN
#  define LV_LOG_PRINTF 1
#endif

/* Color depth */
#define LV_COLOR_DEPTH 16

/* Default fonts we use in the sample UI */
#define LV_FONT_MONTSERRAT_8 1
#define LV_FONT_MONTSERRAT_10 1
#define LV_FONT_UNSCII_8 1
#define LV_FONT_MONTSERRAT_12 1
#define LV_FONT_MONTSERRAT_14 1
#define LV_FONT_MONTSERRAT_16 1
#define LV_FONT_MONTSERRAT_18 1
#define LV_FONT_MONTSERRAT_20 1
#define LV_FONT_MONTSERRAT_26 1
#define LV_FONT_MONTSERRAT_48 1

/* Use image decoder built-ins for airline logos */
#define LV_USE_PNG 1
#define LV_USE_BMP 1
#define LV_USE_SJPG 1

/* We drive the tick manually in main.c (lv_tick_inc) */
#define LV_TICK_CUSTOM 0

#endif /* LV_CONF_H */
