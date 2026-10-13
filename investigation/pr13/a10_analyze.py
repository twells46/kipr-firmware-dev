#!/usr/bin/env python3
"""Summarize 'INJ' lines from pr13_hw.py inj sweeps (a10.md).
    a10_analyze.py [--bytes N] [--delay] [--bad] run-file [...]
Default: one row per (stage, clock, phase), where phase is the (byte, bit) at
which the raced frame's reply shows the slave starting ('raced'); phases at
byte N or later (default 3) are pooled per byte. Columns: how many injections,
then class and l1 snapshot counts. --delay groups by delay instead. --bad lists
every injection that did not end healthy (for F1 images)."""
import re, sys, collections
args = sys.argv[1:]
nb = 3
if "--bytes" in args: i = args.index("--bytes"); nb = int(args[i + 1]); del args[i:i + 2]
bydelay = "--delay" in args; bad = "--bad" in args
args = [a for a in args if not a.startswith("--")]
rows = collections.OrderedDict(); n = 0; notok = []
for fn in args:
    for l in open(fn):
        if not l.startswith("INJ s="): continue
        g = dict(re.findall(r"(\S+?)=(\[.*?\]|\S+)", l)); n += 1
        m = re.search(r"l1=([^ \]]+)", g.get("snap", "")); l1 = m.group(1) if m else "?"
        m = re.match(r"\((\d+),(\d+)\)", g.get("raced", "")); ph = (int(m.group(1)), int(m.group(2))) if m else None
        if bydelay: key = (g["s"], g["hz"], int(g["d"]))
        elif ph is None: key = (g["s"], g["hz"], "none")
        elif ph[0] >= nb:
            rx = re.match(r"\d+/(\d+):([A-Za-z]*)", l1); l1 = "?" if not rx else f"RX {'= 89' if rx.group(1) == '89' else '< 89'}, flags {rx.group(2)}"
            key = (g["s"], g["hz"], f"byte {ph[0] if ph[0] > 85 else '%d-85' % nb}{'' if ph[1] == 0 and ph[0] > 85 else ', bit>0' if ph[0] > 85 else ''}")
        else: key = (g["s"], g["hz"], ph)
        cls = g["cls"] if g["cls"] in ("ok", "dead", "silent") else "rec"
        if cls in ("dead", "silent"): cls += f" off={g.get('off')} 1byte->{g.get('onebyte')}"
        d = " ".join(f"{k[1:]}{'+' + g[k]}" for k in ("+reset", "+retry", "+count", "+ovr") if k in g)
        rows.setdefault(key, collections.Counter())[f"{cls} | l1={l1} | {d}"] += 1
        if g["cls"] != "ok": notok.append(l.strip())
print(f"{n} injections")
def order(k): return (k[0], k[1], (9999, 0) if isinstance(k[2], str) else (k[2] if isinstance(k[2], tuple) else (k[2], 0)), str(k[2]))
for key in sorted(rows, key=order):
    c = rows[key]
    print(f"S{key[0]} {int(key[1]) / 1e6:g}MHz {key[2]}: n={sum(c.values())}")
    for k, v in c.most_common(): print(f"    {v:4d}  {k}")
if bad:
    print(f"not healthy on first frame: {len(notok)}")
    for l in notok[:40]: print("   ", l)
