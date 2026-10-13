"""Generates a10-inj.patch (deterministic reset race + count snapshots), on
a8cd96c + pr13-diag.patch + a9-diag2.patch, with or without a9-f1.patch.
    python3 make-a10-patch.py <tree>
The patch itself is `diff -ru -U2` of the tree before and after; two lines of
context keep it applicable to both trees (a9-f1 changes lines near two hunks)."""
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

edit("Firmware/include/wallaby_dma.h", [
("D13_TX_LO, D13_TX_HI, D13_RX_LO, D13_RX_HI, D13_BOTH, D13_NONE, D13_N };",
 """D13_TX_LO, D13_TX_HI, D13_RX_LO, D13_RX_HI, D13_BOTH, D13_NONE,
       /* A10 injection (a10.md). *_C = TX count << 8 | RX count. *_S = SPI2 SR (9 bits)
        * | TX flag << 12 | RX flag << 13 | spi_resync << 14 | valid << 15.
        * INJ_* belong to the last armed reset, NAT_* to the last reset of any kind.
        * END: last thing inside the reset. L1: first look with chip select high
        * after it. L2: the same after one more chip-select-low period. */
       D13_INJ_DONE, D13_INJ_TIMEOUT, D13_INJ_EN_LO, D13_INJ_EN_HI,
       D13_INJ_END_C, D13_INJ_END_S, D13_INJ_L1_C, D13_INJ_L1_S, D13_INJ_L2_C, D13_INJ_L2_S,
       D13_NAT_END_C, D13_NAT_END_S, D13_NAT_L1_C, D13_NAT_L1_S, D13_NAT_L2_C, D13_NAT_L2_S, D13_N };"""),
])

edit("Firmware/src/wallaby_dma.c", [
# State, the hold and the snapshot, ahead of everything that uses them.
("""void SPI_DMA_Config(unsigned int buffer_len)
{
""", """/* A10 injection (investigation only), see investigation/pr13/a10.md.
 * An unframed frame with byte 0 = 0xA1 arms one injection: bytes 1..4 are the
 * stage and a 24-bit delay in CPU cycles. The reset that frame causes then
 * stops at that stage, interrupts off, until chip select falls, waits the
 * delay, and carries on. Nothing here runs unless armed, except the snapshots. */
#define INJ_NONE 0xFF
static volatile uint8_t inj_armed = INJ_NONE, inj_stage = INJ_NONE;
static volatile uint32_t inj_delay_armed, inj_delay, inj_t_cs;
static volatile uint8_t inj_this;            /* the reset in progress is the armed one */
static volatile uint8_t snap_state[2];       /* per record set (0 INJ, 1 NAT): 0 idle, 1 wait L1, 2 wait low, 3 wait L2 */
#define INJ_CS_HIGH() ((SPI2_CS0_PORT->IDR & SPI2_CS0) != 0)

static void inj_hold(uint8_t stage)
{
    if (inj_stage != stage) return;
    inj_stage = INJ_NONE;
    uint32_t t0 = DWT->CYCCNT;
    while (INJ_CS_HIGH())
        if (DWT->CYCCNT - t0 > 9000000u) { d13[D13_INJ_TIMEOUT]++; inj_this = 0; return; }   /* 50 ms */
    t0 = DWT->CYCCNT;
    inj_t_cs = t0;
    while (DWT->CYCCNT - t0 < inj_delay);
    d13[D13_INJ_DONE]++;
}

static void snap_put(uint8_t c)
{
    uint16_t s = (SPI2->SR & 0x1FF) | 0x8000;
    if (DMA_GetFlagStatus(DMA1_Stream4, DMA_FLAG_TCIF4) != RESET) s |= 0x1000;
    if (DMA_GetFlagStatus(DMA1_Stream3, DMA_FLAG_TCIF3) != RESET) s |= 0x2000;
    if (spi_resync) s |= 0x4000;
    d13[c] = (DMA_GetCurrDataCounter(DMA1_Stream4) << 8) | (DMA_GetCurrDataCounter(DMA1_Stream3) & 0xFF);
    d13[c + 1] = s;
}

/* Called at the end of every reset, interrupts off. */
static void snap_reset_done()
{
    uint32_t now = DWT->CYCCNT;
    uint8_t k;
    for (k = inj_this ? 0 : 1; k < 2; ++k)
    {
        uint8_t base = k ? D13_NAT_END_C : D13_INJ_END_C;
        snap_put(base);
        d13[base + 2] = d13[base + 3] = d13[base + 4] = d13[base + 5] = 0;
        snap_state[k] = 1;
    }
    if (inj_this)
    {
        uint32_t en = now - inj_t_cs;         /* chip select seen low -> SPI2 enabled, cycles */
        d13[D13_INJ_EN_LO] = en; d13[D13_INJ_EN_HI] = en >> 16;
        inj_this = 0;
    }
}

/* Called on every entry to spi2_dma_check_sync() and handle_dma(), and just
 * before a reset. In the starved state handle_dma() is the only one that
 * runs while chip select is high. */
static void snap_look()
{
    if (!(snap_state[0] | snap_state[1])) return;
    uint32_t pm = __get_PRIMASK();
    __disable_irq();
    uint8_t high = INJ_CS_HIGH(), k;
    for (k = 0; k < 2; ++k)
    {
        uint8_t base = k ? D13_NAT_END_C : D13_INJ_END_C, st = snap_state[k];
        if (st == 1 && high) { snap_put(base + 2); snap_state[k] = 2; }
        else if (st == 2 && !high) snap_state[k] = 3;
        else if (st == 3 && high) { snap_put(base + 4); snap_state[k] = 0; }
    }
    if (!pm) __enable_irq();
}

void SPI_DMA_Config(unsigned int buffer_len)
{
"""),
("""    // SPI configuration -------------------------------------------------------
    SPI_I2S_DeInit(SPI2);
""", """    // SPI configuration -------------------------------------------------------
    inj_hold(2);
    SPI_I2S_DeInit(SPI2);
"""),
("""    // Deinitialize DMA Streams
    DMA_DeInit(DMA1_Stream4); // TX stream
""", """    // Deinitialize DMA Streams
    inj_hold(3);
    DMA_DeInit(DMA1_Stream4); // TX stream
"""),
("""    SPI_InitStructure.SPI_Mode = SPI_Mode_Slave;
    SPI_Init(SPI2, &SPI_InitStructure);
""", """    SPI_InitStructure.SPI_Mode = SPI_Mode_Slave;
    inj_hold(4);
    SPI_Init(SPI2, &SPI_InitStructure);
"""),
("""    DMA_Cmd(DMA1_Stream4, ENABLE);
    DMA_Cmd(DMA1_Stream3, ENABLE);
    SPI_I2S_DMACmd(SPI2, SPI_I2S_DMAReq_Tx, ENABLE);
    SPI_I2S_DMACmd(SPI2, SPI_I2S_DMAReq_Rx, ENABLE);
    // Last, so both streams are ready to service SPI2 from its first byte.
    SPI_Cmd(SPI2, ENABLE);
""", """    DMA_Cmd(DMA1_Stream4, ENABLE);
    DMA_Cmd(DMA1_Stream3, ENABLE);
    inj_hold(6);
    SPI_I2S_DMACmd(SPI2, SPI_I2S_DMAReq_Tx, ENABLE);
    SPI_I2S_DMACmd(SPI2, SPI_I2S_DMAReq_Rx, ENABLE);
    // Last, so both streams are ready to service SPI2 from its first byte.
    inj_hold(7);
    SPI_Cmd(SPI2, ENABLE);
    inj_hold(8);
"""),
("""void spi2_dma_check_sync()
{
    uint32_t d_c0 = DWT->CYCCNT;
""", """void spi2_dma_check_sync()
{
    uint32_t d_c0 = DWT->CYCCNT;
    snap_look();
"""),
("""    uint32_t d_c1 = DWT->CYCCNT;
    if (!spi2_cs_high()) d13_inc(D13_CSLOW);
    if (spi2_cs_high())
    {
        DMA_Cmd(DMA1_Stream4, DISABLE);
        DMA_Cmd(DMA1_Stream3, DISABLE);
""", """    uint32_t d_c1 = DWT->CYCCNT;
    snap_look();
    if (!spi2_cs_high()) d13_inc(D13_CSLOW);
    if (spi2_cs_high())
    {
        if (inj_armed != INJ_NONE) { inj_stage = inj_armed; inj_delay = inj_delay_armed; inj_armed = INJ_NONE; inj_this = 1; }
        inj_hold(0);
        DMA_Cmd(DMA1_Stream4, DISABLE);
        inj_hold(1);
        DMA_Cmd(DMA1_Stream3, DISABLE);
"""),
("""            spi2_dma_init(BUFFERSIZE);
            spi2_dma_start();
""", """            spi2_dma_init(BUFFERSIZE);
            inj_hold(5);
            spi2_dma_start();
"""),
("""            if (spi_resync) d13_inc(D13_RETRY);
""", """            if (spi_resync) d13_inc(D13_RETRY);
            snap_reset_done();
"""),
("""        else d13_inc(D13_TRIES);
""", """        else { d13_inc(D13_TRIES); inj_stage = INJ_NONE; inj_this = 0; }
"""),
("""    static uint8_t rejected_packets = 0;
    {
        uint8_t d_t = """, """    static uint8_t rejected_packets = 0;
    snap_look();
    {
        uint8_t d_t = """),
("""            if (!framed) { spi_resync = 1; if (d13[D13_FRAME] != 0xFFFF) d13[D13_FRAME]++; }
""", """            if (!framed) { spi_resync = 1; if (d13[D13_FRAME] != 0xFFFF) d13[D13_FRAME]++; }
            if (aRxBuffer[0] == 0xA1 && aRxBuffer[1] <= 8)
            {
                inj_delay_armed = ((uint32_t)aRxBuffer[2] << 16) | ((uint32_t)aRxBuffer[3] << 8) | aRxBuffer[4];
                inj_armed = aRxBuffer[1];
            }
"""),
])
