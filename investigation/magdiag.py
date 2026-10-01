#!/usr/bin/env python3
"""Read the AK8963 diagnostics published by the E5 magdiag firmware.

Runs on the Wombat next to regdump.py (shares its frame code). Frame layout
and items: see patches/e5-magdiag.patch. Each item's value is the majority
of its checksum-valid observations.
"""
import argparse, collections, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from regdump import Spi  # noqa: E402

NAMES = ["ASAX (setup_magnetometer)", "ASAY (setup_magnetometer)", "ASAZ (setup_magnetometer)",
         "WIA (expect 0x48)", "CNTL1 as setup_magnetometer left it",
         "ASAX (proper)", "ASAY (proper)", "ASAZ (proper)", "CNTL1 after proper sequence",
         "ST2 (latest)", "reads with HOFL set, mod 256"]

ap = argparse.ArgumentParser()
ap.add_argument("--min-obs", type=int, default=5)
ap.add_argument("--timeout", type=float, default=30)
ap.add_argument("--out")
a = ap.parse_args()
spi = Spi("/dev/spidev0.0", 16000000)
obs = collections.defaultdict(collections.Counter)
frames = bad = 0
last = None
start = time.time()
while time.time() - start < a.timeout:
    f = spi.transfer(); frames += 1
    m, i, v, seq, nv, c = f[24:30]
    if f[0] != ord("J") or m != 0xD7 or i >= len(NAMES) or nv != (~v & 0xFF) or c != (0x2B + 7 * i + 13 * v + 31 * seq) & 0xFF:
        bad += 1; continue
    if seq == last:
        continue
    last = seq
    obs[i][v] += 1
    if all(sum(obs[k].values()) >= a.min_obs for k in range(len(NAMES))):
        break
    time.sleep(0.002)
print("frames {} in {:.1f}s, rejected {}".format(frames, time.time() - start, bad))
res = {}
for k, n in enumerate(NAMES):
    c = obs.get(k)
    if not c:
        print("{:<38} --".format(n)); continue
    v, cnt = c.most_common(1)[0]
    extra = ""
    if k in (0, 1, 2, 5, 6, 7):
        extra = "factor {:.4f}".format((v - 128) / 256 + 1)
    if k == 9:
        extra = "BITM(16-bit)={} HOFL={}".format(v >> 4 & 1, v >> 3 & 1)
    if k in (4, 8):
        extra = "BIT={} MODE={:04b}".format(v >> 4 & 1, v & 15)
    print("{:<38} 0x{:02X} ({:3d})  {}/{}  {}".format(n, v, v, cnt, sum(c.values()), extra))
    res[n] = {"value": v, "obs": dict((str(x), y) for x, y in c.items())}
if a.out:
    json.dump(res, open(a.out, "w"), indent=1)
