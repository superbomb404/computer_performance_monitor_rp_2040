#pragma once

#include <stdint.h>

#define DORO_FRAME_WIDTH 320u
#define DORO_FRAME_HEIGHT 170u
#define DORO_FRAME_COUNT 34u
#define DORO_FRAME_REPEAT_COUNT 3u
#define DORO_FRAME_DELAY_MS 40u
#define DORO_FRAME_SIZE_BYTES (DORO_FRAME_WIDTH * DORO_FRAME_HEIGHT * 2u)
#define DORO_ANIMATION_SIZE_BYTES (DORO_FRAME_SIZE_BYTES * DORO_FRAME_COUNT)

extern const uint8_t doro_frames_rgb565[];
extern const uint8_t doro_frames_rgb565_end[];
