#!/usr/bin/env python3
"""Classify published gyro bytes as aligned or shifted by one byte (H7).

Runs on the Wombat next to regdump.py. Reads raw SPI2 frames (no writes) and
keeps frames whose gyro bytes changed. H7 predicts that a burst merged with
the preceding accel read publishes [TEMP_L, GX_H, GX_L, GY_H, GY_L, GZ_H].
A frame counts as "aligned" if all three big-endian words are small
(|v| < LIMIT raw) and as "shifted" if the words re-read from byte 1
(b1b2, b3b4) are small and b5 is 0x00/0xFF (GZ_H of a small value) while
the aligned read is not small. Anything else is "other" (tears, motion).
"""
import struct, sys, time, collections, json
import regdump

LIMIT = 1024  # raw LSB; at-rest bias is ~35/98/144 at ±250 dps
n_target = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
spi = regdump.Spi("/dev/spidev0.0", 16000000)
prev = None
kinds = collections.Counter()
aligned, shifted = [], []
while sum(kinds.values()) < n_target:
    f = spi.transfer()
    if f[0] != ord("J"):
        continue
    g = f[36:42]
    if g == prev:
        continue
    prev = g
    a = struct.unpack(">3h", g)
    s = struct.unpack(">2h", g[1:5])
    if all(abs(v) < LIMIT for v in a):
        kinds["aligned"] += 1
        aligned.append(a)
    elif all(abs(v) < LIMIT for v in s) and g[5] in (0x00, 0xFF):
        kinds["shifted"] += 1
        shifted.append(s)
    else:
        kinds["other"] += 1
    time.sleep(0.002)

def stats(rows, i):
    xs = [r[i] for r in rows]
    if not xs:
        return None
    m = sum(xs) / len(xs)
    return round(m, 1), round((sum((x - m) ** 2 for x in xs) / len(xs)) ** 0.5, 1)

print(dict(kinds))
print("aligned  x/y/z raw mean,std:", [stats(aligned, i) for i in range(3)])
print("shifted  x/y  raw mean,std (from bytes 1-4):", [stats(shifted, i) for i in range(2)])
