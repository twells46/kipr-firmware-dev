#!/usr/bin/env python3
"""H9 (pr14.md): does PR 14's servo rail power-up add undervoltage risk
when motors are loading the same battery? Run ON the Wombat, botui stopped,
servos on ports 0-3, motors on libkipr ports 0, 1, 3 (channels 0, 1, 2),
wheels off the ground.

    sudo python3 pr14_uv.py ident                     MOVES each motor channel 0-3 in turn
                                                      (PWM 100/400, 0.5 s) and prints which counters move
    sudo python3 pr14_uv.py run <tag> [reps=12] [powers=200,250,300] [cells=A0,AM,...] [nostress]
                                                      MOVES motors and servos; writes /tmp/uv-<tag>.jsonl
    python3 pr14_uv.py compare <a.jsonl> <b.jsonl>    (anywhere) per-cell rates and Fisher tests

Each power level P (raw PWM of 400) runs `reps` blocks. A block runs each
cell once in a shuffled order (seed fixed, so every image gets the same
sequence). The motors run at P the whole time. Each cycle settles for OFF s,
then the event; every event is a full 700<->2300 us servo swing except B:
  A0  servos disabled through OFF (PR 14: rail cut 40 ms in, collapsed),
      then enable all four AND reverse all motors, in one SPI frame
  C   as A0 without the reversal: the PR 14 power-up alone
  AM  servos enabled and holding through OFF (rail up on both images),
      then the new target AND the reversal in one frame: A0's control
  M   as AM without the reversal: C's control
  B   reverse the motors only, servos disabled: supply control
  D<ms> as A0, but the reversal comes <ms> after the enable (cells= only).
      On PR 14 servo current starts after U72's soft-start and the servos'
      own boot, so A0's single frame may miss the alignment (run p1).
On master C = M and A0 = AM (disabled servos still hold, rail up). On PR 14
the differences C - M and A0 - AM are the PR's added load, measured on the
same battery in the same minutes.

Per cycle it records any `vcgencmd get_throttled` reading with bit 0 set
(polled about every 3 ms in a thread) in the WIN s after the event,
lost SPI frames, and an STM32 reset (motor or servo registers no longer as
written). On the diag image it also checks that the rail cycled (`ons`
rose by one in A0 and C, none in AM, M and B). Four CPU busy loops at nice 19 raise the
Pi's own 5 V draw unless `nostress`.

Bit 0 stays set for seconds after one dip, so a cycle counts only an onset
(rising edge), and each event waits until bit 0 has cleared. Stops the
ladder early if onsets show in 10 cycles in a row or bit 0 stays set 15 s
(supply saturated). Always ends with PWM 0, directions
idle, servos disabled (ALLSTOP 0xF0). If the Pi itself resets, NOTHING stops
the motors: the STM32 keeps the last command. Be at the power switch.
"""
import json, os, random, signal, subprocess, sys, threading, time

MODE = sys.argv[1] if len(sys.argv) > 1 else ""
if MODE == "compare":
    from math import comb

    def load(p):
        return [json.loads(l) for l in open(p) if l.strip()]

    def fisher_greater(a, n1, b, n2):
        """One-sided P(X >= a) for X ~ hypergeometric: events a/n1 vs b/n2."""
        k, n = a + b, n1 + n2
        if k == 0: return 1.0
        tot = comb(n, k)
        return sum(comb(n1, x) * comb(n2, k - x) for x in range(a, min(k, n1) + 1)) / tot

    A, B = load(sys.argv[2]), load(sys.argv[3])
    ta, tb = A[0]["tag"], B[0]["tag"]
    cells = sorted({(r["power"], r["cell"]) for r in A + B})
    def rate(rs, pw, c):
        x = [r for r in rs if (pw is None or r["power"] == pw) and r["cell"] in c]
        return sum(r["uv"] for r in x), len(x), sum(r["reset"] for r in x), sum(r["lost"] > 0 for r in x)
    print(f"{'power':>5} {'cell':<5} {ta:>18} {tb:>18}   p({ta}>{tb})  p({tb}>{ta})")
    for pw, c in cells:
        a, na, ra, la = rate(A, pw, [c]); b, nb, rb, lb = rate(B, pw, [c])
        print(f"{pw:>5} {c:<5} {a:>4}/{na:<3} rst{ra} lost{la}  {b:>4}/{nb:<3} rst{rb} lost{lb}   "
              f"{fisher_greater(a, na, b, nb):9.3f}  {fisher_greater(b, nb, a, na):9.3f}")
    for name, c in (("A0+C", ["A0", "C"]), ("AM+M", ["AM", "M"]), ("B", ["B"])):
        a, na, _, _ = rate(A, None, c); b, nb, _, _ = rate(B, None, c)
        print(f"pooled {name:<4} {a:>4}/{na:<4} {b:>4}/{nb:<4}   {fisher_greater(a, na, b, nb):9.3f}  {fisher_greater(b, nb, a, na):9.3f}")
    for rs, t in ((A, ta), (B, tb)):
        for x, y in (("C", "M"), ("A0", "AM")):
            a, na, _, _ = rate(rs, None, [x]); b, nb, _, _ = rate(rs, None, [y])
            if na and nb:
                print(f"{t}: {x} {a}/{na} vs {y} {b}/{nb}   p({x}>{y}) {fisher_greater(a, na, b, nb):.3f}  p({y}>{x}) {fisher_greater(b, nb, a, na):.3f}")
    sys.exit(0)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
argv = sys.argv[2:]; sys.argv = sys.argv[:1]
import pr14_hw as h

ALLSTOP, MODES, DIRS = 61, 58, 59
PWM0, POS0 = 70, 42
CH = (0, 1, 2)            # libkipr ports 0, 1, 3 (libwallaby swaps 2 and 3)
LO, HI = 700, 2300
OFF, WIN = 0.7, 0.8       # settle before the event; observed after it
CELLS = ["A0", "AM", "B", "C", "M"]
FWD, REV = 1, 2

def dirs_byte(d): return sum(d << (2 * c) for c in CH)
def pwm_pairs(p): return [x for c in CH for x in h.w16(PWM0 + 2 * c, p)]
def servo_pairs(us): return [x for s_ in range(4) for x in h.w16(h.SERVO0 + 2 * s_, us)]
def motor_pos(r): return [int.from_bytes(bytes(r[POS0 + 4 * c:POS0 + 4 * c + 4]), "big", signed=True) for c in range(4)]

def motors_off():
    h.xfer([(DIRS, 0)] + [x for c in range(4) for x in h.w16(PWM0 + 2 * c, 0)] + [(ALLSTOP, 0xF0)])

def pi():
    uv = subprocess.run("dmesg | grep -ci undervolt", shell=True, capture_output=True, text=True).stdout.strip()
    th = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True).stdout.strip()
    return dict(undervolt=int(uv or 0), throttled=th, uptime=float(open("/proc/uptime").read().split()[0]))


class Throttle(threading.Thread):
    """Polls get_throttled. Bit 0 stays set for seconds after one dip (run
    master1), so only rising edges count: hits holds (t, value) at each onset,
    spans the (onset, clear) times."""
    def __init__(self):
        super().__init__(daemon=True); self.hits = []; self.spans = []; self.last = 0; self.n = 0; self.stop = False
        self.on_since = None
    def run(self):
        while not self.stop:
            out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True).stdout
            v = int(out.strip().split("=")[1], 16); t = time.monotonic(); self.n += 1; self.last = v
            if v & 1:
                if self.on_since is None: self.on_since = t; self.hits.append((t, v))
            elif self.on_since is not None:
                self.spans.append((self.on_since, t)); self.on_since = None
    def window(self, t0, t1):
        return [(t, v) for t, v in self.hits if t0 <= t < t1]
    def wait_clear(self, limit):
        """Block while bit 0 is set. Returns the seconds waited, or None if it didn't clear."""
        t0 = time.monotonic()
        while self.on_since is not None or self.last & 1:
            if time.monotonic() - t0 > limit: return None
            time.sleep(0.01)
        return time.monotonic() - t0


def ident():
    h.desyncs(20); h.VER = h.read()[1:3]
    h.xfer([(MODES, 0), (DIRS, 0), (ALLSTOP, 0xF0)])
    try:
        for c in range(4):
            a = motor_pos(h.read())
            h.xfer([(DIRS, FWD << (2 * c))] + h.w16(PWM0 + 2 * c, 100)); time.sleep(0.5)
            b = motor_pos(h.read()); motors_off(); time.sleep(0.5)
            print(f"channel {c}: counters moved {[y - x for x, y in zip(a, b)]}", flush=True)
    finally:
        motors_off()


TH = None   # the Throttle poller, shared with finish()

def run(tag, reps, powers, stress, cells=CELLS):
    random.seed(14)
    h.desyncs(20); h.VER = h.read()[1:3]
    diag = h.state() is not None
    try: os.nice(-10)
    except OSError: pass
    out = open(f"/tmp/uv-{tag}.jsonl", "w")
    global TH
    th = TH = Throttle(); th.start(); time.sleep(0.3)
    hogs = [subprocess.Popen(["nice", "-n", "19", "python3", "-c", "while True: pass"]) for _ in range(4)] if stress else []
    p0 = pi()
    print(f"H9 {tag} cells={cells} reps={reps} powers={powers} stress={stress} diag={diag} start {time.strftime('%FT%TZ', time.gmtime())} pi={p0}", flush=True)
    last_on = LO; d = FWD; saturated = None
    try:
        h.xfer([(MODES, 0), (ALLSTOP, 0xF0)] + servo_pairs(last_on))
        for P in powers:
            h.xfer([(DIRS, dirs_byte(d))] + pwm_pairs(P)); time.sleep(1.0)
            uv_lvl0 = pi()["undervolt"]; streak = 0; rows = []
            plan = [c for _ in range(reps) for c in random.sample(cells, len(cells))]
            for i, cell in enumerate(plan):
                delay = int(cell[1:]) / 1e3 if cell[0] == "D" else None   # D<ms>: A0 with the reversal <ms> later
                from_off = cell in ("A0", "C", "B") or delay is not None   # servos disabled through OFF (PR 14: rail cut)
                reverse = cell in ("A0", "AM", "B") or delay is not None
                target = HI if last_on == LO else LO
                if from_off: h.xfer([(ALLSTOP, 0xF0)] + servo_pairs(target if cell != "B" else last_on))
                else: h.xfer([(ALLSTOP, 0x00)] + servo_pairs(last_on))   # enabled, holding (rail up on both images)
                time.sleep(OFF)
                waited = th.wait_clear(15)
                if waited is None: saturated = P; print(f"  {P} #{i}: bit 0 set for 15 s", flush=True); break
                s0 = h.state() if diag else None
                nd = (REV if d == FWD else FWD) if reverse else d
                t0 = time.monotonic()
                if delay is not None:
                    h.xfer([(ALLSTOP, 0x00)])
                    while time.monotonic() - t0 < delay: pass
                    h.xfer([(DIRS, dirs_byte(nd))])
                elif cell == "A0": h.xfer([(ALLSTOP, 0x00), (DIRS, dirs_byte(nd))])
                elif cell == "C": h.xfer([(ALLSTOP, 0x00)])
                elif cell == "B": h.xfer([(DIRS, dirs_byte(nd))])
                elif cell == "AM": h.xfer(servo_pairs(target) + [(DIRS, dirs_byte(nd))])
                else: h.xfer(servo_pairs(target))
                d = nd; lost = 0; win = WIN + (delay or 0)
                while time.monotonic() - t0 < win: lost += not h.good(h.xfer()); time.sleep(0.005)
                r = h.read(); s1 = h.state() if diag else None
                pos = [r[h.SERVO0 + 2 * k] << 8 | r[h.SERVO0 + 2 * k + 1] for k in range(4)]
                pwm = [r[PWM0 + 2 * c] << 8 | r[PWM0 + 2 * c + 1] for c in CH]
                moved = cell != "B"
                reset = (r[ALLSTOP] != (0xF0 if cell == "B" else 0x00) or r[DIRS] != dirs_byte(d)
                         or pwm != [P] * len(CH) or pos != [target if moved else last_on] * 4)
                if moved: last_on = target
                ons = None if not (s0 and s1) else (s1["ons"] - s0["ons"]) & 0xFF
                rec = dict(tag=tag, power=P, cell=cell, i=i, t=round(t0, 3), lost=lost, reset=reset, ons=ons,
                           rail_ok=None if ons is None else ons == (1 if from_off and cell != "B" else 0), waited=round(waited, 2))
                rows.append((rec, t0, t0 + win)); finish(rows[-1], out)
                streak = streak + 1 if rec["uv"] else 0
                if reset:
                    print(f"  {P} #{i} {cell}: STM32 RESET? ALLSTOP=0x{r[ALLSTOP]:02x} DIRS=0x{r[DIRS]:02x} pwm={pwm} pos={pos}", flush=True)
                    h.xfer([(MODES, 0), (DIRS, dirs_byte(d))] + pwm_pairs(P))   # restore the motor command
                if streak >= 10: saturated = P; break
            uv_lvl = pi()["undervolt"] - uv_lvl0
            summ = {c: (sum(r["uv"] for r, _, _ in rows if r["cell"] == c), sum(r["cell"] == c for r, _, _ in rows)) for c in cells}
            print(f"P={P}: " + "  ".join(f"{c} {a}/{n}" for c, (a, n) in summ.items())
                  + f"  resets {sum(r['reset'] for r, _, _ in rows)}  lost-frame cycles {sum(r['lost'] > 0 for r, _, _ in rows)}"
                  + (f"  rail-not-cycled {sum(r['rail_ok'] is False for r, _, _ in rows)}" if diag else "")
                  + f"  new dmesg undervoltage {uv_lvl}  polls {th.n}", flush=True)
            if saturated is not None: print(f"SATURATED at P={P}: stopping the ladder", flush=True); break
    finally:
        motors_off()
        for g in hogs: g.kill()
        th.stop = True
    p1 = pi()
    att = sum(1 for l in open(f"/tmp/uv-{tag}.jsonl") if '"uv": true' in l)
    print(f"onsets {len(th.hits)}, attributed to an event window {att}, outside any window {len(th.hits) - att}", flush=True)
    print("bit 0 spans (s): " + " ".join(f"{b - a:.2f}" for a, b in th.spans), flush=True)
    print(f"H9 {tag} done {time.strftime('%FT%TZ', time.gmtime())} pi={p1} new dmesg undervoltage {p1['undervolt'] - p0['undervolt']}"
          f" rebooted={p1['uptime'] < p0['uptime']}", flush=True)


def finish(row, out):
    rec, t0, t1 = row
    hits = TH.window(t0, t1)
    rec["uv"] = bool(hits)
    rec["uv_ms"] = [round((t - t0) * 1e3) for t, _ in hits[:3]]
    rec["uv_vals"] = sorted({f"0x{v:x}" for _, v in hits})
    out.write(json.dumps(rec) + "\n"); out.flush()
    if hits: print(f"  {rec['power']} #{rec['i']} {rec['cell']}: UNDERVOLTAGE at +{rec['uv_ms']} ms {rec['uv_vals']}", flush=True)


def _term(*_): raise KeyboardInterrupt
for sg in (signal.SIGTERM, signal.SIGHUP): signal.signal(sg, _term)

if MODE == "ident": ident()
elif MODE == "run":
    tag = argv[0]; reps = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 12
    powers = next((list(map(int, a.split(","))) for a in argv[1:] if "," in a), [200, 250, 300])
    cells = next((a[6:].split(",") for a in argv[1:] if a.startswith("cells=")), CELLS)
    run(tag, reps, powers, "nostress" not in argv, cells)
else:
    print(__doc__); sys.exit(2)
