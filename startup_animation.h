#pragma once

#include <stdint.h>

#define STARTUP_FRAME_WIDTH 320u
#define STARTUP_FRAME_HEIGHT 170u
#define STARTUP_FRAME_COUNT 65u
#define STARTUP_REPEAT_COUNT 1u
#define STARTUP_FRAME_DELAY_MS 40u
#define STARTUP_FINAL_FRAME_HOLD_MS 1600u
#define STARTUP_FRAME_SIZE_BYTES 108800u
#define STARTUP_ANIMATION_SIZE_BYTES 7072000u

extern const uint8_t startup_frames_rgb565[];
extern const uint8_t startup_frames_rgb565_end[];
