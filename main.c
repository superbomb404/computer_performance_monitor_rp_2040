#include "FreeRTOS.h"
#include <stdio.h>
#include "pico/stdlib.h"
#include "hardware/gpio.h"
#include "task.h"
#include "rtos_task.h"
#include "queue.h"
#include "rtos_queue.h"
#include "usb_device.h"

void vApplicationStackOverflowHook(TaskHandle_t pxTask, char *pcTaskName)
{
    (void)pcTaskName;
    (void)pxTask;

    /* Run time stack overflow checking is performed if
    configCHECK_FOR_STACK_OVERFLOW is defined to 1 or 2.  This hook
    function is called if a stack overflow is detected. */

    /* Force an assert. */
    configASSERT((volatile void *)NULL);
}

int main()
{
    stdio_init_all();
    usb_device_init();

    queue_init();

    xTaskCreate(v_task_lcd_Init, "lcd_init", 1000, NULL, 31, NULL);
    xTaskCreate(v_task_usb_uart, "usb_uart", 2048, NULL, 2, NULL);
    vTaskStartScheduler();

    while (1)
    {
    }
}
