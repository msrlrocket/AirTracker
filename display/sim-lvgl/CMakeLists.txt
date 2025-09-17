cmake_minimum_required(VERSION 3.20)
project(airtracker_sim C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

# Options
option(LVGL_V8 "Use LVGL v8 (stable)" ON)

include(FetchContent)

# Avoid network updates on re-configure; use already-fetched sources
set(FETCHCONTENT_UPDATES_DISCONNECTED ON)

if(LVGL_V8)
  # Fetch LVGL v8 (stable) and lv_drivers for SDL
  FetchContent_Declare(
    lvgl
    GIT_REPOSITORY https://github.com/lvgl/lvgl.git
    GIT_TAG v8.3.11
  )
  FetchContent_MakeAvailable(lvgl)

  # lv_drivers does not always ship CMake; we add our own library
  FetchContent_Declare(
    lv_drivers
    GIT_REPOSITORY https://github.com/lvgl/lv_drivers.git
    GIT_TAG master
  )
  FetchContent_GetProperties(lv_drivers)
  if(NOT lv_drivers_POPULATED)
    FetchContent_Populate(lv_drivers)
  endif()
  set(LV_DRIVERS_DIR ${lv_drivers_SOURCE_DIR})
else()
  message(FATAL_ERROR "This template currently targets LVGL v8.")
endif()

# SDL2
# On macOS, Homebrew packages SDL2 as a CMake package config.
find_package(SDL2 CONFIG REQUIRED)

# curl for downloading images
# On macOS with Homebrew, curl is keg-only
set(CMAKE_PREFIX_PATH "/opt/homebrew/opt/curl;${CMAKE_PREFIX_PATH}")
find_package(CURL REQUIRED)

# Data is loaded from JSON files (live MQTT data via Python bridge)

# LVGL config: point to our lv_conf.h
add_compile_definitions(LV_CONF_INCLUDE_SIMPLE)
include_directories(${CMAKE_CURRENT_SOURCE_DIR})

# Build lv_drivers using the SDL backend (modern replacement for deprecated monitor+indev)
add_library(lvgl_drivers STATIC
  ${LV_DRIVERS_DIR}/sdl/sdl_common.c
  ${LV_DRIVERS_DIR}/sdl/sdl.c
)
target_include_directories(lvgl_drivers PUBLIC ${LV_DRIVERS_DIR} ${lvgl_SOURCE_DIR})
target_compile_definitions(lvgl_drivers PUBLIC LV_LVGL_H_INCLUDE_SIMPLE)
target_link_libraries(lvgl_drivers PUBLIC SDL2::SDL2 SDL2::SDL2main)

# Our simulator target
add_executable(airtracker_sim
  src/main.c
  src/ui/ui.c
  src/model/model.c
  src/io/json_loader.c
  third_party/parson/parson.c
)
target_include_directories(airtracker_sim PRIVATE
  src
  src/ui
  src/model
  src/io
  third_party/parson
)
target_link_libraries(airtracker_sim PRIVATE
  lvgl::lvgl
  lvgl_drivers
  CURL::libcurl
)

# Ensure lvgl finds our lv_conf.h via simple include
# Propagate lv_conf.h include/define to the actual lvgl target (alias can't be modified)
target_include_directories(lvgl PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_definitions(lvgl PUBLIC LV_CONF_INCLUDE_SIMPLE)

# Fonts/demos/examples can be enabled via lv_conf.h

# On macOS: make the app bundle off (simple CLI binary)
set_target_properties(airtracker_sim PROPERTIES MACOSX_BUNDLE OFF)
