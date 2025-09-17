#ifndef AIRTRACKER_SIM_JSON_LOADER_H
#define AIRTRACKER_SIM_JSON_LOADER_H

#include <stdbool.h>
#include "../model/model.h"

typedef struct {
  char path[512];
  long last_mtime; // seconds
  bool active;     // set true after first successful parse
} json_loader_t;

void json_loader_init(json_loader_t* jl, const char* path);
// Returns true if model was updated from JSON (file changed & parsed)
bool json_loader_poll(json_loader_t* jl, model_t* m);

#endif // AIRTRACKER_SIM_JSON_LOADER_H

