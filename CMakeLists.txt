cmake_minimum_required(VERSION 3.13)

# initialize the SDK based on PICO_SDK_PATH
# note: this must happen before project()
include(pico_sdk_import.cmake)
include(FreeRTOS_Kernel_import.cmake)

project(computer_performance_monitor C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
set(PICO_FLASH_SIZE_BYTES "16 * 1024 * 1024" CACHE STRING "Board flash size" FORCE)

# initialize the Raspberry Pi Pico SDK
pico_sdk_init()

set(STARTUP_FRAMES_BIN ${CMAKE_CURRENT_SOURCE_DIR}/assets/startup_frames_rgb565.bin)
file(TO_CMAKE_PATH "${STARTUP_FRAMES_BIN}" STARTUP_FRAMES_BIN_ASM)
configure_file(${CMAKE_CURRENT_SOURCE_DIR}/startup_animation.S.in
    ${CMAKE_CURRENT_BINARY_DIR}/startup_animation.S
    @ONLY)

set(HOST_PACKAGE_DISK_BIN ${CMAKE_CURRENT_SOURCE_DIR}/assets/host_package_fat.img)
file(TO_CMAKE_PATH "${HOST_PACKAGE_DISK_BIN}" HOST_PACKAGE_DISK_BIN_ASM)
configure_file(${CMAKE_CURRENT_SOURCE_DIR}/host_package_disk.S.in
    ${CMAKE_CURRENT_BINARY_DIR}/host_package_disk.S
    @ONLY)

set(USB_MODE_IMAGE_BIN ${CMAKE_CURRENT_SOURCE_DIR}/assets/usb_mode_image_rgb565.bin)
file(TO_CMAKE_PATH "${USB_MODE_IMAGE_BIN}" USB_MODE_IMAGE_BIN_ASM)
configure_file(${CMAKE_CURRENT_SOURCE_DIR}/usb_mode_image.S.in
    ${CMAKE_CURRENT_BINARY_DIR}/usb_mode_image.S
    @ONLY)

# rest of your project
add_executable(computer_performance_monitor
    rtos_queue.c main.c rtos_task.c HarmonyOS_2bit.c usb_device.c usb_descriptors.c
    ${CMAKE_CURRENT_BINARY_DIR}/startup_animation.S
    ${CMAKE_CURRENT_BINARY_DIR}/host_package_disk.S
    ${CMAKE_CURRENT_BINARY_DIR}/usb_mode_image.S
)

# USB CDC and read-only MSC are handled by TinyUSB directly.
pico_enable_stdio_usb(computer_performance_monitor 0)
pico_enable_stdio_uart(computer_performance_monitor 0)

pico_generate_pio_header(computer_performance_monitor ${CMAKE_CURRENT_LIST_DIR}/i8080.pio)

target_include_directories(computer_performance_monitor PRIVATE
        ${CMAKE_CURRENT_LIST_DIR})

# Specify path to own LVGL config header
set(LV_CONF_PATH
    ${CMAKE_CURRENT_SOURCE_DIR}/src/lv_conf.h
    CACHE STRING "" FORCE)

add_subdirectory(lvgl-8.3.10)

# create map/bin/hex/uf2 file in addition to ELF.
pico_add_extra_outputs(computer_performance_monitor)

# Add pico_stdlib library which aggregates commonly used features
target_link_libraries(computer_performance_monitor pico_stdlib hardware_pio hardware_dma tinyusb_device tinyusb_board FreeRTOS-Kernel FreeRTOS-Kernel-Heap4 lvgl::lvgl lvgl::demos)
