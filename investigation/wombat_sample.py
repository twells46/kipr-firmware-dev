#!/usr/bin/env python3
"""Sample the libkipr gyro/accel getters at rest and summarize them.

Runs on the Wombat and calls the installed libkipr.so exactly as a student
program would. Two passes run in one process, because libkipr keeps
calibration biases in process-local statics:

  raw   -- no calibration; shows what the firmware delivers
  cal   -- after gyro_calibrate() and accel_calibrate(); the primary result

Each pass writes <out>.<pass>.csv and <out>.<pass>.summary.json with per-axis
n/mean/std/min/max and the fraction of readings pinned at full scale.
"""

import argparse
import ctypes
import csv
import json
import math
import sys
import time

AXES = ("gyro_x", "gyro_y", "gyro_z", "accel_x", "accel_y", "accel_z")


def sample(getters, count, interval_ms):
    rows = []
    start = time.monotonic()
    for i in range(count):
        rows.append([i, round(time.monotonic() - start, 6)] + [fn() for fn in getters])
        time.sleep(interval_ms / 1000.0)
    return rows


def summarize(rows, interval_ms):
    summary = {"samples": len(rows), "duration_s": rows[-1][1], "interval_ms": interval_ms, "axes": {}}
    for col, name in enumerate(AXES, start=2):
        values = [row[col] for row in rows]
        mean = sum(values) / len(values)
        std = math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))
        # Getters return raw/16 minus bias, so |value| >= 2047 means pinned at full scale.
        saturated = sum(1 for v in values if abs(v) >= 2047) / len(values)
        summary["axes"][name] = {"mean": round(mean, 3), "std": round(std, 3),
                                 "min": min(values), "max": max(values),
                                 "saturated_fraction": round(saturated, 4)}
    return summary


def write(prefix, rows, summary):
    with open(prefix + ".csv", "w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("sample", "t_s") + AXES)
        writer.writerows(rows)
    with open(prefix + ".summary.json", "w") as stream:
        json.dump(summary, stream, indent=2)


def show(title, summary):
    print("[{}]".format(title))
    print("{:8} {:>10} {:>10} {:>7} {:>7} {:>6}".format("axis", "mean", "std", "min", "max", "sat"))
    for name, s in summary["axes"].items():
        print("{:8} {:10.2f} {:10.2f} {:7d} {:7d} {:6.1%}".format(
            name, s["mean"], s["std"], s["min"], s["max"], s["saturated_fraction"]))
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=2000)
    parser.add_argument("--interval-ms", type=float, default=10.0,
                        help="delay between samples; 10 ms is ~2 firmware updates at 200 Hz")
    parser.add_argument("--library", default="/usr/lib/libkipr.so")
    parser.add_argument("--out", required=True, help="output path prefix")
    args = parser.parse_args()

    lib = ctypes.CDLL(args.library)
    getters = []
    for name in AXES:
        fn = getattr(lib, name)
        fn.argtypes = ()
        fn.restype = ctypes.c_short
        getters.append(fn)
    calibrations = []
    for name in ("gyro_calibrate", "accel_calibrate"):
        fn = getattr(lib, name)
        fn.argtypes = ()
        fn.restype = ctypes.c_int
        calibrations.append(fn)

    rows = sample(getters, args.samples, args.interval_ms)
    summary = summarize(rows, args.interval_ms)
    write(args.out + ".raw", rows, summary)
    show("raw", summary)

    for fn in calibrations:
        fn()
    sys.stdout.flush()

    rows = sample(getters, args.samples, args.interval_ms)
    summary = summarize(rows, args.interval_ms)
    write(args.out + ".cal", rows, summary)
    show("cal", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
