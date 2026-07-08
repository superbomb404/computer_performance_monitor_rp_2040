#include "rtos_queue.h"

QueueHandle_t x_queue_lcd;

void queue_init()
{
    x_queue_lcd = xQueueCreate(16, sizeof(config_lcd));
}

void x_queue_lcd_send(LCD_COMMAND command, uint8_t data)
{
    config_lcd config_lcd_data;
    config_lcd_data.command = command;
    config_lcd_data.data = data;
    xQueueSend(x_queue_lcd, (void *)&config_lcd_data, 50);
}
