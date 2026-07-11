#pragma once

#include <stdbool.h>
#include <stdint.h>

void usb_device_init(void);
void usb_device_task(void);

bool usb_device_disk_mode_is_active(void);
uint32_t usb_device_disk_mode_generation(void);
void usb_device_note_host_app_connected(void);
