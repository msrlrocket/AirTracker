cmake_minimum_required(VERSION 3.16)

# Add LVGL as a component
set(EXTRA_COMPONENT_DIRS "components")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(esp32-idf-airtracker)