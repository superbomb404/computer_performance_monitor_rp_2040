#pragma once

#include <stdint.h>

#define USB_MODE_IMAGE_WIDTH 120u
#define USB_MODE_IMAGE_HEIGHT 64u
#define USB_MODE_IMAGE_SIZE_BYTES (USB_MODE_IMAGE_WIDTH * USB_MODE_IMAGE_HEIGHT * 2u)

extern const uint8_t usb_mode_image_rgb565[];
extern const uint8_t usb_mode_image_rgb565_end[];
