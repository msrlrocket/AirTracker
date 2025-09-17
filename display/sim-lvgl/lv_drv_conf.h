#ifndef LV_DRV_CONF_H
#define LV_DRV_CONF_H

/* Enable the SDL driver and configure resolution/zoom for the simulator. */

#define USE_SDL           1

/* Display size and scaling for the SDL window */
#define SDL_HOR_RES       320
#define SDL_VER_RES       240
#define SDL_ZOOM          2

/* Tell the driver where to include SDL from */
#define SDL_INCLUDE_PATH  <SDL.h>

/* Optional: High-DPI behavior. Leave default for portability. */
/* #define SDL_HIGHDPI    1 */

#endif /* LV_DRV_CONF_H */
