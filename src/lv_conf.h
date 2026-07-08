/**
 * LVGL configuration for the RP2040 performance monitor.
 *
 * Only project-specific options are defined here; LVGL fills the rest with
 * its v8.3 defaults from lv_conf_internal.h.
 */
#ifndef LV_CONF_H
#define LV_CONF_H

#include <stdint.h>

/* ST7789 panel over an 8-bit parallel bus, using RGB565 pixels. */
#define LV_COLOR_DEPTH 16
#define LV_COLOR_16_SWAP 1

/* Keep LVGL heap explicit for the Pico's limited SRAM. */
#define LV_MEM_SIZE (48U * 1024U)

/* The UI uses these core widgets/layouts directly. */
#define LV_FONT_MONTSERRAT_14 1
#define LV_USE_BAR 1
#define LV_USE_LABEL 1
#define LV_USE_FLEX 1
#define LV_USE_GRID 1

/* Demos are linked by the original CMake file but not used by the firmware. */
#define LV_USE_DEMO_WIDGETS 0
#define LV_USE_DEMO_KEYPAD_AND_ENCODER 0
#define LV_USE_DEMO_BENCHMARK 0
#define LV_USE_DEMO_STRESS 0
#define LV_USE_DEMO_MUSIC 0

#endif /* LV_CONF_H */
