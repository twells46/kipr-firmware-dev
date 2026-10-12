#include <stdint.h>
#include <string.h>
#include "wallaby_spi_r4.h"
typedef struct { uint8_t rx[REG_ALL_COUNT]; uint8_t tx[REG_ALL_COUNT]; uint8_t guard[512]; } Mem;
#define CAT2(a,b) a##b
#define CAT(a,b) CAT2(a,b)
Mem CAT(mem_,V);
int CAT(adc_dirty_,V), CAT(dig_dirty_,V);
#define aRxBuffer CAT(mem_,V).rx
#define aTxBuffer CAT(mem_,V).tx
#define adc_dirty CAT(adc_dirty_,V)
#define dig_dirty CAT(dig_dirty_,V)
#define RESET 0
#define DMA_GetFlagStatus(a,b) 1
#define DMA_ClearFlag(a,b) ((void)0)
#define debug_printf(...) ((void)0)
#define handle_dma CAT(handle_dma_,V)
#include SRC
