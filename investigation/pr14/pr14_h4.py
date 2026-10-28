#!/usr/bin/env python3
"""H4 (pr14.md): battery sag when all four servos power up and move at once.
Run ON the Wombat, botui stopped, servos on all four ports.

    sudo python3 pr14_h4.py <mode> [cycles=30] [lo_us=700] [hi_us=2300]

mode pu: power-up cycles. Each cycle sets all four positions to the far end
         from the last one, enables all four (on PR 14 this releases the
         rail, so the servos power up and travel together), holds 1.5 s,
         disables all four, waits 1.5 s (on PR 14 the rail is cut: limp).
mode mv: move-only cycles. All four stay enabled and alternate between the
         two ends every 1.5 s (the load master can already produce).

Each cycle checks that the STM32 did not reset (ALLSTOP and positions as
written). Before and after: Pi uptime, `vcgencmd get_throttled`, and the
count of "Undervoltage" lines in dmesg. Fails if the STM32 resets, the Pi
reports a new undervoltage or throttle bit, or the link loses frames.
Leaves every servo disabled. Never commands a motor.
"""
import os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
argv = sys.argv[1:]; sys.argv = sys.argv[:1]
import pr14_hw as h

mode = argv[0]; cycles = int(argv[1]) if len(argv) > 1 else 30
lo = int(argv[2]) if len(argv) > 2 else 700; hi = int(argv[3]) if len(argv) > 3 else 2300

def pi():
    uv = subprocess.run("dmesg | grep -ci undervolt", shell=True, capture_output=True, text=True).stdout.strip()
    th = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True).stdout.strip()
    up = open("/proc/uptime").read().split()[0]
    return dict(undervolt=int(uv or 0), throttled=th, uptime=float(up))

def positions(us):
    h.xfer(h.w16(h.SERVO0, us) + h.w16(h.SERVO0 + 2, us) + h.w16(h.SERVO0 + 4, us) + h.w16(h.SERVO0 + 6, us))

h.desyncs(20); h.VER = h.read()[1:3]
diag = h.state() is not None
p0 = pi(); print(f"H4 {mode} x{cycles} {lo}/{hi} us start {time.strftime('%FT%TZ', time.gmtime())} pi={p0} diag={diag}", flush=True)
bad = []; lost = 0
try:
    if mode == "mv": h.set_allstop(0x00)
    for c in range(cycles):
        us = hi if c % 2 == 0 else lo
        positions(us)
        if mode == "pu": h.set_allstop(0x00)
        t = time.time()
        while time.time() - t < 1.5: lost += not h.good(h.xfer()); time.sleep(0.005)
        r = h.read()
        got = [r[h.SERVO0 + 2 * p] << 8 | r[h.SERVO0 + 2 * p + 1] for p in range(4)]
        if r[h.ALLSTOP] & 0xF0 != 0x00 or got != [us] * 4: bad.append(f"#{c} STM32 reset? ALLSTOP=0x{r[h.ALLSTOP]:02x} pos={got}")
        if mode == "pu":
            h.set_allstop(0xF0); time.sleep(1.5)
        print(f"  cycle {c} -> {us} us ok" if not bad or not bad[-1].startswith(f"#{c} ") else f"  cycle {c}: {bad[-1]}", flush=True)
finally:
    h.set_allstop(0xF0)
p1 = pi()
new_uv = p1["undervolt"] - p0["undervolt"]
ok = not bad and lost == 0 and new_uv == 0 and p1["throttled"] == p0["throttled"] and p1["uptime"] > p0["uptime"]
print(f"H4 {mode}: {'PASS' if ok else 'FAIL'}  STM32 resets/mismatches: {bad[:5]}, frames lost {lost}, new undervoltage lines {new_uv}, throttled {p0['throttled']} -> {p1['throttled']}, pi={p1}")
sys.exit(0 if ok else 1)
