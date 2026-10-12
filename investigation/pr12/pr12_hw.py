#!/usr/bin/env python3
"""PR 12 hardware tests (run ON the Wombat, with botui stopped).

    sudo python3 pr12_hw.py <test> [...]     tests: h1..h6 (all), h7 h8 (A9/A10 fix)

Talks to the STM32 with raw spidev frames shaped exactly like libwallaby's
(89 bytes, zero padded), so the result doesn't depend on the libkipr build.
Only touches registers that move nothing: servo position registers 78..85
(servos stay disabled by REG_RW_MOT_SRV_ALLSTOP) and, in h4, registers 0..2,
which it restores. Prints one PASS/FAIL line per test plus the evidence.
Expected results per firmware are in investigation/pr12/pr12.md.
"""
import sys, time, spidev

N = 89
SERVO0, ALLSTOP = 78, 61
s = spidev.SpiDev(); s.open(0, 0); s.max_speed_hz = 16000000
ctr = 0

def xfer(pairs=(), count=None):
    global ctr
    ctr = (ctr + 1) & 0xFF
    b = [0] * N
    b[0], b[1], b[2], b[88] = ord('J'), 4, ctr, ord('S')
    b[3] = len(pairs) if count is None else count
    for i, (a, v) in enumerate(pairs):
        b[4 + 2 * i], b[5 + 2 * i] = a, v
    rx = s.xfer2(b)
    time.sleep(50e-6)          # libwallaby's usleep(50)
    return rx

def read():
    xfer(); return xfer()      # the 2nd frame returns state after the 1st

def desyncs(n):
    return sum(xfer()[0] != ord('J') for _ in range(n))

def recover():
    # master only: put 'J' back so later tests start clean (PR 12 ignores it).
    xfer([(0, ord('J'))]); xfer()

def report(name, ok, detail):
    print(f"{name}: {'PASS' if ok else 'FAIL'}  {detail}")
    return ok

def h1():
    """PR's own repro: count=2 with no pairs must not desync."""
    assert desyncs(20) == 0, "link already desynchronized; reset the STM32 first"
    xfer(count=2)
    d = desyncs(200)
    recover()
    return report("H1 count>pairs desync", d == 0, f"{d}/200 frames without 'J'")

def h2():
    """Servo register round-trip with libwallaby w8/w16/w32 shapes."""
    bad = []
    for port in range(4):
        a = SERVO0 + 2 * port
        for val in (600, 1500, 2400, 0x0101, 0xFFFE):
            xfer([(a, val >> 8), (a + 1, val & 0xFF)])
            r = read(); got = r[a] << 8 | r[a + 1]
            if got != val: bad.append((a, val, got))
        xfer([(a, 0x12)]); r = read()
        if r[a] != 0x12: bad.append((a, 0x12, r[a]))
    v = [0x05, 0xDC, 0x05, 0xDD]
    xfer([(SERVO0 + i, v[i]) for i in range(4)]); r = read()
    if r[SERVO0:SERVO0 + 4] != v: bad.append(("w32", v, r[SERVO0:SERVO0 + 4]))
    xfer([(SERVO0 + i, (1500 >> 8, 1500 & 0xFF)[i % 2]) for i in range(8)])  # restore
    allstop = read()[ALLSTOP]
    return report("H2 servo round-trip", not bad and allstop & 0xF0 == 0xF0,
                  f"mismatches={bad} allstop=0x{allstop:02x}")

def h3():
    """Every single-bit flip of the count byte on a w16 to servo 0."""
    rows, fails = [], 0
    for bit in range(8):
        cnt = 2 ^ (1 << bit)
        xfer([(SERVO0, 0x05), (SERVO0 + 1, 0xDC)])           # known value 1500
        xfer([(SERVO0, 0x07), (SERVO0 + 1, 0xD0)], count=cnt)  # intended 2000
        r = read(); got = r[SERVO0] << 8 | r[SERVO0 + 1]
        j = desyncs(5)
        expect = 1500 if cnt == 0 else 2000
        rows.append(f"cnt={cnt}:{got},desync={j}")
        if j or got != expect: fails += 1
        if j: recover()
    xfer([(SERVO0, 0x05), (SERVO0 + 1, 0xDC)])
    return report("H3 count bit flips", fails == 0, " ".join(rows))

def h4():
    """Writes to 0..2 (what set_servo_position(-39, x) sends)."""
    before = read()[0:3]
    xfer([(0, 0x05), (1, 0xDC)]); xfer([(2, 0x00)])
    after = read()[0:3]
    d = desyncs(50)
    xfer([(0, ord('J')), (1, before[1]), (2, before[2])]); xfer()
    return report("H4 writes to 0..2 ignored", after == before and d == 0,
                  f"before={before} after={after} desync={d}/50 (master expected FAIL)")

def h5(n=20000):
    """Link soak at libwallaby cadence: mixed w16 writes and reads."""
    d = 0; t = time.time()
    for i in range(n):
        rx = xfer([(SERVO0, 0x05), (SERVO0 + 1, 0xDC)]) if i % 2 else xfer()
        d += rx[0] != ord('J')
    dt = time.time() - t
    return report("H5 soak", d == 0, f"{d}/{n} desync, {n/dt:.0f} frames/s")

def h6():
    """Firmware version registers are still readable and unchanged."""
    r = read()
    return report("H6 version regs", r[0] == ord('J'), f"start={r[0]} version=0x{r[1]:02x}{r[2]:02x}")

MOT_DONE = 60

def h7():
    """A9: count 128 over a body with no zero padding (42 x servo0=2000)."""
    xfer([(SERVO0, 0x05), (SERVO0 + 1, 0xDC)])
    xfer([(SERVO0, 0x07), (SERVO0 + 1, 0xD0)] * 21, count=128)
    r = read(); got = r[SERVO0] << 8 | r[SERVO0 + 1]
    d = desyncs(5)
    xfer([(SERVO0, 0x05), (SERVO0 + 1, 0xDC)])
    return report("H7 unpadded corrupt packet dropped", got == 1500 and d == 0,
                  f"servo0={got} desync={d} (master 1500 by wraparound, PR 12 unfixed 2000)")

def h8():
    """A10: reject counter in MOT_DONE bits 7:4 moves by 1 per rejected packet only."""
    hi = lambda: read()[MOT_DONE] >> 4
    c0 = hi()
    for _ in range(50): xfer([(SERVO0, 0x05), (SERVO0 + 1, 0xDC)]); xfer()
    c1 = hi()
    steps = []
    for frame in ([(SERVO0, 0x05)], 3), ([(0, 0x05)], None), ([(SERVO0, 0x05)], 200):
        before = hi(); xfer(frame[0], count=frame[1]); steps.append((hi() - before) & 15)
    xfer([(SERVO0, 0x05), (SERVO0 + 1, 0xDC)])
    lo = read()[MOT_DONE] & 0x0F
    return report("H8 reject counter", c1 == c0 and steps == [1, 1, 1],
                  f"clean drift={(c1 - c0) & 15} steps={steps} done-bits=0x{lo:x}")

TESTS = dict(h1=h1, h2=h2, h3=h3, h4=h4, h5=h5, h6=h6, h7=h7, h8=h8)
names = sys.argv[1:] or ["all"]
if names == ["all"]: names = ["h1", "h2", "h3", "h4", "h5", "h6"]
print(f"pr12_hw {time.strftime('%FT%TZ', time.gmtime())}")
time.sleep(1); desyncs(100)   # warm-up: the first frames after an STM32 reset can slip
sys.exit(0 if all([TESTS[n]() for n in names]) else 1)
