#!/usr/bin/env python3
"""Read the raw 16-bit magnetometer slots from SPI2 frames (no /16).

Runs on the Wombat next to regdump.py (shares its frame code). Reports per-axis
stats of distinct published frames and how often the published value changes,
which shows whether the firmware is delivering fresh AK8963 samples.
Also averages the accelerometer slots (raw/16, as libkipr) over every frame,
to check that the Wombat is flat.
"""
import argparse, json, math, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from regdump import Spi  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--seconds", type=float, default=10)
ap.add_argument("--out")
a = ap.parse_args()
spi = Spi("/dev/spidev0.0", 16000000)
rows, changes, frames, last = [], 0, 0, None
acc = []
start = time.time()
while time.time() - start < a.seconds:
    f = spi.transfer(); frames += 1
    if f[0] != ord("J"):
        continue
    v = tuple(int.from_bytes(f[24 + 2 * k:26 + 2 * k], "big", signed=True) for k in range(3))
    acc.append(tuple(int.from_bytes(f[30 + 2 * k:32 + 2 * k], "big", signed=True) / 16 for k in range(3)))
    if v != last:
        changes += 1; rows.append(v); last = v
    time.sleep(0.002)
el = time.time() - start
res = {"frames": frames, "seconds": round(el, 2), "changes": changes, "change_rate_hz": round(changes / el, 1), "axes": {}}
print("frames {} in {:.1f}s; published value changed {} times ({:.1f}/s)".format(frames, el, changes, changes / el))
for k, n in enumerate("xyz"):
    v = [r[k] for r in rows]
    m = sum(v) / len(v); sd = math.sqrt(sum((x - m) ** 2 for x in v) / max(1, len(v) - 1))
    res["axes"][n] = {"mean": round(m, 2), "std": round(sd, 2), "min": min(v), "max": max(v), "distinct": len(set(v))}
    print("mag {} raw mean {:8.2f} std {:6.2f} min {:6} max {:6} distinct {:4}  (~{:.1f} uT at 0.15 uT/LSB)".format(n, m, sd, min(v), max(v), len(set(v)), m * 0.15))
res["accel"] = {n: round(sum(r[k] for r in acc) / len(acc), 2) for k, n in enumerate("xyz")}
print("accel mean x {x} y {y} z {z} (raw/16)".format(**res["accel"]))
if a.out:
    json.dump(res, open(a.out, "w"), indent=1)
