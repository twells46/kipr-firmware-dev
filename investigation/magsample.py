#!/usr/bin/env python3
"""Sample libkipr magneto_x/y/z (and gyro_x as a liveness check) at rest.

Runs on the Wombat through the installed /usr/lib/libkipr.so (or --library).
Prints per-axis stats, distinct-value counts and the fraction of exact zeros.
"""
import argparse, ctypes, json, math, time

p = argparse.ArgumentParser()
p.add_argument("--library", default="/usr/lib/libkipr.so")
p.add_argument("-n", type=int, default=1000)
p.add_argument("--interval-ms", type=float, default=10)
p.add_argument("--out")
a = p.parse_args()
lib = ctypes.CDLL(a.library)
names = ("magneto_x", "magneto_y", "magneto_z", "gyro_x")
fns = []
for n in names:
    f = getattr(lib, n); f.restype = ctypes.c_short; f.argtypes = []; fns.append(f)
rows = []
for i in range(a.n):
    rows.append([f() for f in fns]); time.sleep(a.interval_ms / 1000)
res = {}
for c, n in enumerate(names):
    v = [r[c] for r in rows]; m = sum(v) / len(v)
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))
    res[n] = dict(mean=round(m, 2), std=round(sd, 2), min=min(v), max=max(v),
                  distinct=len(set(v)), zero_fraction=round(v.count(0) / len(v), 4))
    print("{:10} mean {:8.2f} std {:7.2f} min {:6} max {:6} distinct {:5} zeros {:.3f}".format(
        n, m, sd, min(v), max(v), len(set(v)), v.count(0) / len(v)))
if a.out:
    json.dump(dict(samples=a.n, interval_ms=a.interval_ms, axes=res, first=rows[:20]), open(a.out, "w"), indent=1)
