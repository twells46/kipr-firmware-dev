#!/usr/bin/env python3
"""Analyse an E6 magnetometer rotation test (runs/*-e6-rot-*/raw.json).

The firmware (d9b8ade) publishes raw * ASA factor; unadjusted values are
recovered by dividing by the factors measured in E5. For the flat 90-degree
headings it reports the x/y centre (mean of the four points), each point's
distance from it, z spread and total magnitude. With a uniform field plus a
constant offset, flat rotation keeps z and the distance from the centre
constant, and the distance equals the horizontal field (~23 uT expected).
"""
import glob, json, math, os, sys

ASA = (1.1836, 1.1836, 1.1445)
UT = 0.15  # uT per count, 16-bit mode
here = os.path.dirname(os.path.abspath(__file__))
runs = sorted(glob.glob(os.path.join(here, "runs", "*-e6-rot-*")))
pts = []
for r in runs:
    d = json.load(open(os.path.join(r, "raw.json")))
    pts.append((os.path.basename(r).split("-e6-rot-")[1], [d["axes"][k]["mean"] for k in "xyz"], d.get("accel")))
out = {}
for name, scale in (("ASA-adjusted", (1, 1, 1)), ("unadjusted", ASA)):
    p = [(h, [m[k] / scale[k] * UT for k in range(3)], acc) for h, m, acc in pts]
    flat = [q for q in p if q[0] in ("000", "090", "180", "270")]
    cx = sum(q[1][0] for q in flat) / 4
    cy = sum(q[1][1] for q in flat) / 4
    print("== {} (uT)".format(name))
    print("{:>7} {:>8} {:>8} {:>8} {:>8} {:>10} {:>16}".format("heading", "x", "y", "z", "|B|", "r_xy-ctr", "accel x/y"))
    rad = []
    for h, (x, y, z), acc in p:
        r = math.hypot(x - cx, y - cy)
        if h in ("000", "090", "180", "270"):
            rad.append(r)
        print("{:>7} {:8.1f} {:8.1f} {:8.1f} {:8.1f} {:10.1f} {:>16}".format(
            h, x, y, z, math.sqrt(x * x + y * y + z * z), r, "{:.0f}/{:.0f}".format(acc["x"], acc["y"]) if acc else ""))
    zs = [q[1][2] for q in flat]
    print("centre x/y {:.1f}/{:.1f}; radius mean {:.1f} (min {:.1f}, max {:.1f}); z spread {:.1f}".format(
        cx, cy, sum(rad) / 4, min(rad), max(rad), max(zs) - min(zs)))
    out[name] = {"centre_xy_uT": [cx, cy], "radius_mean_uT": sum(rad) / 4, "radii_uT": rad, "z_spread_uT": max(zs) - min(zs)}
json.dump({"runs": [os.path.basename(r) for r in runs], "fit": out}, open(os.path.join(here, "runs", "e6-rotfit.json"), "w"), indent=1)
