#include "usb_device.h"

#include <string.h>
#include "pico/time.h"
#include "tusb.h"

#define USB_DISK_BLOCK_SIZE 512u
#define USB_DISK_MODE_TIMEOUT_MS 30000u

extern const uint8_t host_package_disk[];
extern const uint8_t host_package_disk_end[];

static volatile bool g_host_app_connected = false;
static volatile bool g_disk_mode_active = false;
static volatile bool g_disk_unit_attention = false;
static volatile uint32_t g_disk_mode_generation = 0;
static uint32_t g_usb_started_ms = 0;

void usb_device_init(void)
{
    g_usb_started_ms = to_ms_since_boot(get_absolute_time());
    tusb_init();
}

void usb_device_task(void)
{
    tud_task();

    if (!g_host_app_connected && !g_disk_mode_active) {
        uint32_t now_ms = to_ms_since_boot(get_absolute_time());
        if ((uint32_t)(now_ms - g_usb_started_ms) >= USB_DISK_MODE_TIMEOUT_MS) {
            g_disk_mode_active = true;
            g_disk_unit_attention = true;
            g_disk_mode_generation++;
        }
    }
}

bool usb_device_disk_mode_is_active(void)
{
    return g_disk_mode_active;
}

uint32_t usb_device_disk_mode_generation(void)
{
    return g_disk_mode_generation;
}

void usb_device_note_host_app_connected(void)
{
    g_host_app_connected = true;
    if (g_disk_mode_active) {
        g_disk_mode_active = false;
        g_disk_unit_attention = false;
        g_disk_mode_generation++;
    }
}

void tud_msc_inquiry_cb(uint8_t lun, uint8_t vendor_id[8], uint8_t product_id[16], uint8_t product_rev[4])
{
    (void)lun;
    memcpy(vendor_id, "CPM     ", 8);
    memcpy(product_id, "Installer Disk  ", 16);
    memcpy(product_rev, "1.20", 4);
}

bool tud_msc_test_unit_ready_cb(uint8_t lun)
{
    if (!g_disk_mode_active) {
        tud_msc_set_sense(lun, SCSI_SENSE_NOT_READY, 0x3A, 0x00);
        return false;
    }

    if (g_disk_unit_attention) {
        g_disk_unit_attention = false;
        tud_msc_set_sense(lun, SCSI_SENSE_UNIT_ATTENTION, 0x28, 0x00);
        return false;
    }

    return true;
}

void tud_msc_capacity_cb(uint8_t lun, uint32_t *block_count, uint16_t *block_size)
{
    (void)lun;
    *block_size = USB_DISK_BLOCK_SIZE;
    *block_count = (uint32_t)((host_package_disk_end - host_package_disk) / USB_DISK_BLOCK_SIZE);
}

bool tud_msc_is_writable_cb(uint8_t lun)
{
    (void)lun;
    return false;
}

bool tud_msc_start_stop_cb(uint8_t lun, uint8_t power_condition, bool start, bool load_eject)
{
    (void)lun;
    (void)power_condition;

    if (load_eject && !start && g_disk_mode_active) {
        g_disk_mode_active = false;
        g_disk_unit_attention = false;
        g_disk_mode_generation++;
    }

    return true;
}

int32_t tud_msc_read10_cb(uint8_t lun, uint32_t lba, uint32_t offset, void *buffer, uint32_t bufsize)
{
    (void)lun;
    if (!g_disk_mode_active) {
        return -1;
    }

    uint32_t disk_size = (uint32_t)(host_package_disk_end - host_package_disk);
    uint32_t address = lba * USB_DISK_BLOCK_SIZE + offset;
    if (address >= disk_size) {
        return -1;
    }

    uint32_t readable = disk_size - address;
    if (bufsize > readable) {
        bufsize = readable;
    }

    memcpy(buffer, host_package_disk + address, bufsize);
    return (int32_t)bufsize;
}

int32_t tud_msc_write10_cb(uint8_t lun, uint32_t lba, uint32_t offset, uint8_t *buffer, uint32_t bufsize)
{
    (void)lba;
    (void)offset;
    (void)buffer;
    (void)bufsize;

    tud_msc_set_sense(lun, SCSI_SENSE_DATA_PROTECT, 0x27, 0x00);
    return -1;
}

int32_t tud_msc_scsi_cb(uint8_t lun, uint8_t const scsi_cmd[16], void *buffer, uint16_t bufsize)
{
    void const *response = NULL;
    int32_t response_len = 0;

    switch (scsi_cmd[0]) {
    case SCSI_CMD_PREVENT_ALLOW_MEDIUM_REMOVAL:
        response_len = 0;
        break;
    default:
        tud_msc_set_sense(lun, SCSI_SENSE_ILLEGAL_REQUEST, 0x20, 0x00);
        response_len = -1;
        break;
    }

    if (response_len > bufsize) {
        response_len = bufsize;
    }

    if (response && response_len > 0) {
        memcpy(buffer, response, (size_t)response_len);
    }

    return response_len;
}
