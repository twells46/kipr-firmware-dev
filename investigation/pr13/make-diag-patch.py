import sys, pathlib
root = pathlib.Path(sys.argv[1])
def edit(rel, subs):
    p = root / rel
    raw = p.read_bytes()
    crlf = b"\r\n" in raw
    t = raw.decode().replace("\r\n", "\n")
    for old, new in subs:
        assert t.count(old) == 1, (rel, old, t.count(old))
        t = t.replace(old, new)
    if crlf: t = t.replace("\n", "\r\n")
    p.write_bytes(t.encode())

edit("Firmware/include/wallaby_dma.h", [("void spi2_dma_check_sync();\n", """void spi2_dma_check_sync();

/* PR 13 diagnostics (investigation only), see investigation/pr13/pr13.md. */
#ifndef D13_DIAG
#define D13_DIAG
enum { D13_COUNT, D13_INFLIGHT, D13_OVR, D13_FRAME, D13_ATTEMPT, D13_CSLOW, D13_TRIES,
       D13_RESET, D13_RETRY, D13_IRQOFF_MAX, D13_CHECK_MAX, D13_NDTR_LAST,
       D13_SENS_MAX, D13_OVER700, D13_PASSES, D13_N };
extern volatile uint16_t d13[D13_N];
void d13_publish(uint32_t sensor_update_time);
#endif
""")])

edit("Firmware/src/wallaby_dma.c", [
("""void spi2_dma_check_sync()
{
""", """volatile uint16_t d13[D13_N];
static void d13_inc(uint8_t i) { if (d13[i] != 0xFFFF) d13[i]++; }
static void d13_max(uint8_t i, uint32_t cyc) { uint32_t v = cyc / 18; if (v > 0xFFFF) v = 0xFFFF; if (v > d13[i]) d13[i] = v; } /* 0.1 us at 180 MHz */

/* One item per main-loop pass in the magnetometer slots:
 * 22 marker 0xD3, 23 item, 24 value_h, 25 value_l, 26 ~item,
 * 27 checksum = 0x5A + 13*item + 31*value_h + 3*value_l */
void d13_publish(uint32_t sensor_update_time)
{
    static uint8_t item;
    if (sensor_update_time > d13[D13_SENS_MAX]) d13[D13_SENS_MAX] = sensor_update_time > 0xFFFF ? 0xFFFF : sensor_update_time;
    if (sensor_update_time >= 700) d13_inc(D13_OVER700);
    d13[D13_PASSES]++;
    uint8_t i = item, h = d13[i] >> 8, l = d13[i] & 0xFF;
    item = (item + 1) % D13_N;
    aTxBuffer[REG_RW_MAG_X_H] = 0xD3;
    aTxBuffer[REG_RW_MAG_X_L] = i;
    aTxBuffer[REG_RW_MAG_Y_H] = h;
    aTxBuffer[REG_RW_MAG_Y_L] = l;
    aTxBuffer[REG_RW_MAG_Z_H] = (uint8_t)~i;
    aTxBuffer[REG_RW_MAG_Z_L] = (uint8_t)(0x5A + 13 * i + 31 * h + 3 * l);
}

void spi2_dma_check_sync()
{
    uint32_t d_c0 = DWT->CYCCNT;
"""),
("""        delay_us(2);
        if (spi2_cs_high() && DMA_GetCurrDataCounter(DMA1_Stream3) != BUFFERSIZE) spi_resync = 1;
    }
""", """        delay_us(2);
        uint16_t d_ndtr = DMA_GetCurrDataCounter(DMA1_Stream3);
        if (spi2_cs_high() && DMA_GetCurrDataCounter(DMA1_Stream3) != BUFFERSIZE) { spi_resync = 1; d13_inc(D13_COUNT); d13[D13_NDTR_LAST] = d_ndtr; }
        else d13_inc(D13_INFLIGHT);
    }
"""),
("""    if (SPI_I2S_GetFlagStatus(SPI2, SPI_I2S_FLAG_OVR) != RESET) spi_resync = 1;

    if (!spi_resync) return;
""", """    if (SPI_I2S_GetFlagStatus(SPI2, SPI_I2S_FLAG_OVR) != RESET) { spi_resync = 1; d13_inc(D13_OVR); }

    if (!spi_resync) { d13_max(D13_CHECK_MAX, DWT->CYCCNT - d_c0); return; }
    d13_inc(D13_ATTEMPT);
"""),
("""    __disable_irq();
    if (spi2_cs_high())
    {
""", """    __disable_irq();
    uint32_t d_c1 = DWT->CYCCNT;
    if (!spi2_cs_high()) d13_inc(D13_CSLOW);
    if (spi2_cs_high())
    {
"""),
("""            spi_resync = !spi2_cs_high();
        }
    }
    __enable_irq();
""", """            spi_resync = !spi2_cs_high();
            d13_inc(D13_RESET);
            if (spi_resync) d13_inc(D13_RETRY);
        }
        else d13_inc(D13_TRIES);
    }
    d13_max(D13_IRQOFF_MAX, DWT->CYCCNT - d_c1);
    __enable_irq();
    d13_max(D13_CHECK_MAX, DWT->CYCCNT - d_c0);
"""),
("            if (!framed) spi_resync = 1;\n", "            if (!framed) { spi_resync = 1; if (d13[D13_FRAME] != 0xFFFF) d13[D13_FRAME]++; }\n"),
])

edit("Firmware/src/main.c", [
("""    // Loop until button is pressed
""", """    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;

    // Loop until button is pressed
"""),
("""            uint32_t sensor_update_time = usCount - before;
""", """            uint32_t sensor_update_time = usCount - before;
            d13_publish(sensor_update_time);
"""),
])
