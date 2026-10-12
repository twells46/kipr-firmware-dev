#!/usr/bin/env python3
"""H9: libkipr's rate-limited reject warning (run ON the Wombat, botui stopped).

    sudo python3 pr12_warn.py <libkipr.so> <inject: 0|1> [seconds=12]

Calls analog(0) through libkipr in a loop. With inject=1, every 10th call is
followed by a raw spidev frame the firmware rejects (count 3 over one write).
Prints libkipr's output, then a summary line. Expected with the A9/A10
firmware and patched libkipr: inject=0 -> 0 warnings; inject=1 -> one warning
per 5 s, whose counts add up to the injected total minus at most the last
window. Run with stdout unbuffered (python3 -u) so the order is kept.
"""
import ctypes, sys, time, spidev
lib = ctypes.CDLL(sys.argv[1])
inject = sys.argv[2] == "1"
secs = float(sys.argv[3]) if len(sys.argv) > 3 else 12
s = spidev.SpiDev(); s.open(0, 0); s.max_speed_hz = 16000000
def bad():
    b = [0] * 89; b[0], b[1], b[3], b[4], b[5], b[88] = 74, 4, 3, 78, 5, 83
    s.xfer2(b); time.sleep(50e-6)
lib.analog(0)
n = calls = 0; t = time.time()
while time.time() - t < secs:
    lib.analog(0); calls += 1
    if inject and calls % 10 == 0: bad(); n += 1
    time.sleep(0.01)
lib.analog(0)
sys.stdout.flush()
print(f"SUMMARY inject={int(inject)} injected={n} calls={calls} seconds={secs}", flush=True)
