/* 解析器验收样本:覆盖结构体 / 位域 / 联合体 / 数组 / 指针 / 枚举 / typedef / static */
#include <stdint.h>

typedef volatile uint32_t vu32;

typedef enum {
    MODE_IDLE  = 0,
    MODE_RUN   = 1,
    MODE_FAULT = 0xFF
} work_mode_t;

typedef struct {
    uint8_t  pin;
    uint8_t  mode;
    uint16_t speed;
} gpio_cfg_t;

/* 位域:覆盖 1bit / 3bit / 跨字节 16bit 等 */
typedef struct {
    uint32_t enable         : 1;
    uint32_t irq_priority   : 3;
    uint32_t dma_en         : 1;
    uint32_t reserved       : 11;
    uint32_t baud_prescaler : 16;
} uart_ctrl_bits_t;

/* 联合体:成员共享起始地址 */
typedef union {
    uint32_t all;
    struct {
        uint32_t tx_empty    : 1;
        uint32_t rx_full     : 1;
        uint32_t parity_err  : 1;
        uint32_t framing_err : 1;
        uint32_t overrun     : 1;
        uint32_t reserved    : 27;
    } bits;
} uart_status_u;

typedef struct node_s {
    uint32_t id;
    struct node_s *next;
} node_t;

typedef struct {
    vu32               CR1;
    uart_ctrl_bits_t   CR1_BITS;
    uart_status_u      SR;
    uint8_t            tx_buf[16];
    gpio_cfg_t         pins[3];
    work_mode_t        mode;
    void              *user_ctx;
    node_t            *next;
} uart_handle_t;

uart_handle_t  g_uart1;
uart_handle_t  g_uart2;
static uint32_t s_counter = 42;
uint8_t        g_dma_buffer[64];
work_mode_t    g_mode = MODE_RUN;
const uint32_t g_version = 0x00010203u;
node_t         g_head;
uint16_t       g_flags;

int main(void)
{
    static uint32_t local_static = 7;
    local_static++;
    g_uart1.CR1_BITS.baud_prescaler = 1152;
    return (int)local_static;
}
