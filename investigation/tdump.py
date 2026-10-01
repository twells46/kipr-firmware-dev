#!/usr/bin/env python3
"""Read the main-loop timing stats published by the T1 firmware.

Runs on the Wombat. Reads raw SPI2 frames from /dev/spidev0.0 (same frame
code as regdump.py, no register writes) and decodes the magnetometer slots,
which patches/t1-loop-timing.patch repurposes:

    marker 0xC3, window, item, value_h, value_l,
    checksum = 0x3C + 7*window + 13*item + 31*value_h + 3*value_l (mod 256)

Each window is T_WIN = 4000 loop passes. Items are grouped per window; a
window counts once every item has been seen. Values: see the patch header.
"""
import argparse, collections, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from regdump import Spi  # noqa: E402

CLASSES = ("imu+mag (count%20==0)", "imu only (count%10==0)", "no imu, no bemf", "bemf pass (count%4==1)")
FIELDS = ("n", "imu_mean", "imu_max", "adc_mean", "adc_max", "sens_mean", "sens_max",
          "us_max", "over700", "per_mean", "per_max")
NITEM = 11 * len(CLASSES) + 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", type=int, default=5, help="complete windows to collect")
    ap.add_argument("--timeout", type=float, default=90)
    ap.add_argument("--out")
    a = ap.parse_args()
    spi = Spi("/dev/spidev0.0", 16000000)
    wins = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    frames = bad = 0
    first_win = None
    start = time.time()
    done = []
    while time.time() - start < a.timeout and len(done) < a.windows:
        f = spi.transfer()
        frames += 1
        if f[0] != ord("J"):
            bad += 1; continue
        m, w, i, h, l, c = f[24:30]
        if m != 0xC3 or i >= NITEM or c != (0x3C + 7 * w + 13 * i + 31 * h + 3 * l) & 0xFF:
            bad += 1; continue
        if first_win is None:
            first_win = w  # skip the window in progress at start (may predate us)
        if w == first_win or w == 0:
            continue
        wins[w][i][(h << 8) | l] += 1
        done = [k for k, v in wins.items() if len(v) == NITEM]
        time.sleep(0.002)
    print("frames {} in {:.1f}s, rejected {}, complete windows {}".format(frames, time.time() - start, bad, len(done)))
    if not done:
        print("no complete window: is the T1 firmware flashed?"); return 1
    per_win = []
    for w in sorted(done):
        vals = {i: wins[w][i].most_common(1)[0][0] for i in range(NITEM)}
        amb = [i for i in range(NITEM) if len(wins[w][i]) > 1]
        per_win.append({"window": w, "values": vals, "ambiguous_items": amb})
    res = {"frames": frames, "rejected": bad, "windows": per_win, "classes": {}}
    print("cyc/us x100 per window: {}".format([p["values"][44] for p in per_win]))
    print("times in us; mean = mean of window means, max = max over windows")
    print("{:<24} {:>5} {:>13} {:>13} {:>13} {:>8} {:>8} {:>13}".format(
        "class", "n/win", "readIMU", "adc_update", "sensor sect.", "usC max", ">=700", "period"))
    for c, name in enumerate(CLASSES):
        col = {f: [p["values"][11 * c + k] for p in per_win] for k, f in enumerate(FIELDS)}
        s = {}
        for f, v in col.items():
            if f.endswith("_max") or f == "us_max":
                s[f] = max(v) / (1 if f == "us_max" else 10)
            elif f in ("n", "over700"):
                s[f] = sum(v)
            else:
                s[f] = round(sum(v) / len(v) / 10, 1)
        res["classes"][name] = s
        print("{:<24} {:>5} {:>6.1f}/{:<6.1f} {:>6.1f}/{:<6.1f} {:>6.1f}/{:<6.1f} {:>8} {:>4}/{:<4} {:>6.1f}/{:<6.1f}".format(
            name, s["n"] // len(per_win), s["imu_mean"], s["imu_max"], s["adc_mean"], s["adc_max"],
            s["sens_mean"], s["sens_max"], int(s["us_max"]), s["over700"], s["n"], s["per_mean"], s["per_max"]))
    if a.out:
        json.dump(res, open(a.out, "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
