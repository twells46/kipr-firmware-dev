"""Generates a9-f1.patch (the A9 fix candidate, on a8cd96c) and a9-diag2.patch
(handler-entry counters, on a8cd96c + pr13-diag.patch).
    python3 make-a9-patches.py f1|diag2 <tree>"""
import sys, pathlib
which, root = sys.argv[1], pathlib.Path(sys.argv[2])
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

if which == "f1":
    edit("Firmware/src/wallaby_dma.c", [
("""    DMA_ITConfig(DMA1_Stream3, DMA_IT_TC, ENABLE);
    DMA_ITConfig(DMA1_Stream4, DMA_IT_TC, ENABLE);
""", """    // Only the RX stream interrupts. The TX stream completes a frame about two
    // bytes before RX does, and its interrupt would stay pending until then.
    DMA_ITConfig(DMA1_Stream3, DMA_IT_TC, ENABLE);
"""),
("""    if ( (DMA_GetFlagStatus(DMA1_Stream4,DMA_FLAG_TCIF4)!=RESET) &&  (DMA_GetFlagStatus(DMA1_Stream3,DMA_FLAG_TCIF3)!=RESET))
    {
""", """    // A frame has arrived once the RX stream completes. Waiting for the TX flag
    // too is what let a transfer one byte short of a frame hang the firmware:
    // TX had completed, RX hadn't, and the TX interrupt re-entered until the
    // host's next transfer.
    if (DMA_GetFlagStatus(DMA1_Stream3,DMA_FLAG_TCIF3)!=RESET)
    {
"""),
    ])
else:
    edit("Firmware/include/wallaby_dma.h", [
("D13_SENS_MAX, D13_OVER700, D13_PASSES, D13_N };", "D13_SENS_MAX, D13_OVER700, D13_PASSES,\n       D13_TX_LO, D13_TX_HI, D13_RX_LO, D13_RX_HI, D13_BOTH, D13_NONE, D13_N };"),
    ])
    edit("Firmware/src/wallaby_dma.c", [
("volatile uint16_t d13[D13_N];\n", "volatile uint16_t d13[D13_N];\nstatic volatile uint32_t d13_tx, d13_rx; /* handle_dma() entries with only the TX / only the RX flag set */\n"),
("    d13[D13_PASSES]++;\n", """    d13[D13_PASSES]++;
    { uint32_t t = d13_tx, r = d13_rx; d13[D13_TX_LO] = t; d13[D13_TX_HI] = t >> 16; d13[D13_RX_LO] = r; d13[D13_RX_HI] = r >> 16; }
"""),
("    static uint8_t rejected_packets = 0;\n", """    static uint8_t rejected_packets = 0;
    {
        uint8_t d_t = DMA_GetFlagStatus(DMA1_Stream4,DMA_FLAG_TCIF4)!=RESET, d_r = DMA_GetFlagStatus(DMA1_Stream3,DMA_FLAG_TCIF3)!=RESET;
        if (d_t && d_r) d13[D13_BOTH]++; else if (d_t) d13_tx++; else if (d_r) d13_rx++; else d13[D13_NONE]++;
    }
"""),
    ])
