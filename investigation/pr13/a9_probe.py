#!/usr/bin/env python3
"""Read-only link and motor state (run ON the Wombat). Sends only empty frames."""
import time, spidev
s = spidev.SpiDev(); s.open(0, 0); s.max_speed_hz = 16000000
def fr():
    b = [0] * 89; b[0], b[1], b[88] = ord('J'), 4, ord('S')
    r = s.xfer2(b); time.sleep(50e-6); return r
def pos(f, p): return int.from_bytes(bytes(f[42 + 4 * p:46 + 4 * p]), "big", signed=True)
rs = [fr() for _ in range(40)]
print("replies with 'J':", sum(r[0] == 74 for r in rs), "of 40; distinct:", len({tuple(r) for r in rs}))
a = fr(); time.sleep(0.5); b = fr()
print("first bytes:", b[:4], "modes/dirs/done/allstop:", b[58:62], "pwm:", [b[70 + 2 * p] << 8 | b[71 + 2 * p] for p in range(4)])
print("position change in 0.5 s:", [pos(b, p) - pos(a, p) for p in range(4)], "battery raw:", b[86] << 8 | b[87])
