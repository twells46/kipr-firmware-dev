#!/usr/bin/env python3
"""PR 13 hardware tests (run ON the Wombat, with botui stopped).

    sudo python3 pr13_hw.py [--reset] <test> [...]    tests: p1..p14, all

Talks to the STM32 with raw spidev frames shaped like libwallaby's (89 bytes,
zero padded, 16 MHz, 50 us between transfers). It only writes servo position
registers 78..85 (servos stay disabled by REG_RW_MOT_SRV_ALLSTOP) and restores
them. Nothing moves.

With the diagnostics image (builds/pr13-merge-master+diag) the tests also read
the resync counters that pr13-diag.patch publishes in the magnetometer slots;
on any other image those checks print "no diag" and are skipped.

--reset lets a test reset the STM32 (a pulse on GPIO 23) to get the link
back on firmware that can't recover by itself, and enables p8.
Expected results per firmware are in investigation/pr13/pr13.md.
"""
import random, subprocess, sys, time, spidev

N = 89
SERVO0, ALLSTOP, MOT_DONE = 78, 61, 60
# wallaby_flash's reset pulse on GPIO 23 (high, low, high, release), shortened.
# wallaby_reset_coproc itself blocks forever with libgpiod v2's gpioset.
RESET_CMD = ["gpioset", "-c", "0", "-t", "100ms,100ms,0", "23=1"]
LOST_MAX = 25          # PR 13 claims at most 20 transfers lost after a slip
ITEMS = ("count", "inflight", "ovr", "frame", "attempt", "cslow", "tries", "reset", "retry",
         "irqoff_max", "check_max", "ndtr_last", "sens_max", "over700", "passes")
RESYNC_ITEMS = ("count", "ovr", "frame", "attempt", "reset")

s = spidev.SpiDev(); s.open(0, 0); s.max_speed_hz = 16000000
ctr = 0
VER = None
allow_reset = False


def frame(pairs=(), count=None, start=ord('J'), version=4, end=ord('S')):
    global ctr
    ctr = (ctr + 1) & 0xFF
    b = [0] * N
    b[0], b[1], b[2], b[88] = start, version, ctr, end
    b[3] = len(pairs) if count is None else count
    for i, (a, v) in enumerate(pairs):
        b[4 + 2 * i], b[5 + 2 * i] = a, v
    return b

def xfer(pairs=(), **kw):
    rx = s.xfer2(frame(pairs, **kw))
    time.sleep(50e-6)          # libwallaby's usleep(50)
    return rx

def good(rx):
    return rx[0] == ord('J') and (VER is None or rx[1:3] == VER)

def read():
    xfer(); return xfer()      # the 2nd frame returns state after the 1st

def desyncs(n):
    return sum(not good(xfer()) for _ in range(n))

def w16(addr, val):
    return [(addr, val >> 8), (addr + 1, val & 0xFF)]

def servo(r, port=0):
    a = SERVO0 + 2 * port
    return r[a] << 8 | r[a + 1]

def stm_reset():
    subprocess.run(RESET_CMD, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    time.sleep(1); desyncs(100)

def ensure_synced(name):
    """Every test starts from a working link, so a failure belongs to that test."""
    if desyncs(30) == 0: return True
    time.sleep(0.05)
    if desyncs(30) == 0: return True
    if allow_reset:
        stm_reset()
        if desyncs(30) == 0: return True
    print(f"{name}: SKIP  link is desynchronized before the test (rerun with --reset)")
    return False

def diag(settle=0.02):
    """Latest value of every diagnostic item, or None if this isn't the diag image."""
    time.sleep(settle)
    vals = {}
    for _ in range(400):
        f = xfer()
        m, i, h, l, ni, c = f[24:30]
        if good(f) and m == 0xD3 and i < len(ITEMS) and ni == (~i & 0xFF) and c == (0x5A + 13 * i + 31 * h + 3 * l) & 0xFF:
            vals[ITEMS[i]] = h << 8 | l
        time.sleep(0.0003)
        if len(vals) == len(ITEMS) and _ > 60: break
    return vals if len(vals) == len(ITEMS) else None

def ddelta(a, b, keys=RESYNC_ITEMS):
    if a is None or b is None: return None
    return {k: (b[k] - a[k]) & 0xFFFF for k in keys}

def dfmt(d):
    return "no diag" if d is None else " ".join(f"{k}={v}" for k, v in d.items())

def stable_snapshot(n=40):
    """Register bytes that don't change by themselves, to catch stray writes."""
    fr = [read() for _ in range(n)]
    # Start byte, version, and the host-written block (motor modes .. servo
    # positions). Sensor bytes drift even when they look stable for a while.
    keep = list(range(3)) + list(range(ALLSTOP, SERVO0 + 8))
    return {i: fr[0][i] for i in keep if all(f[i] == fr[0][i] for f in fr)}

def snapshot_diff(a, b):
    return [(i, a[i], b[i]) for i in a if i in b and a[i] != b[i]]

def after_slip(limit=400, pause=0.0):
    """Frames at libwallaby cadence after a disturbance. Returns (bad frames,
    index one past the last bad frame). Stops early after 100 good in a row."""
    if pause: time.sleep(pause)
    bad = last = run = 0
    for i in range(limit):
        if good(xfer()): run += 1
        else: bad += 1; last = i + 1; run = 0
        if run >= 100: break
    return bad, last

def rand_len():
    """1..300, never one byte short of a frame boundary: that case is P12."""
    while True:
        n = random.randint(1, 300)
        if n % N != N - 1: return n

def liveness(n=40, gap=0.02):
    """Distinct replies among n frames sent `gap` apart. The reply holds live
    accelerometer, gyro and ADC values, so it changes on nearly every frame
    while the main loop runs and repeats when the loop is starved."""
    seen = set()
    for _ in range(n):
        time.sleep(gap); seen.add(tuple(s.xfer2(frame())))
    return len(seen)

def report(name, ok, detail):
    print(f"{name}: {'PASS' if ok else 'FAIL'}  {detail}")
    return ok


def p1(n=20000):
    """Healthy link soak at libwallaby cadence: no desync and no resync activity."""
    if not ensure_synced("P1"): return False
    d0 = diag(); d = 0; t = time.time()
    for i in range(n):
        rx = xfer(w16(SERVO0, 1500)) if i % 2 else xfer()
        d += not good(rx)
    dt = time.time() - t
    d1 = diag(); dd = ddelta(d0, d1)
    extra = "" if d1 is None else f" inflight+{(d1['inflight'] - d0['inflight']) & 0xFFFF} check_max={d1['check_max'] / 10}us sens_max={d1['sens_max']}us"
    return report("P1 healthy soak", d == 0 and (dd is None or not any(dd.values())),
                  f"{d}/{n} desync, {n / dt:.0f} frames/s, resync deltas: {dfmt(dd)}{extra}")

def p2(secs=30):
    """Healthy link, light traffic (a frame every 10 ms) and slow clocks."""
    if not ensure_synced("P2"): return False
    d0 = diag(); d = n = 0; t = time.time()
    while time.time() - t < secs:
        d += not good(xfer()); n += 1; time.sleep(0.01)
    slow = 0
    for hz in (500000, 1000000, 4000000):
        s.max_speed_hz = hz
        slow += sum(not good(xfer()) for _ in range(200))
    s.max_speed_hz = 16000000
    dd = ddelta(d0, diag())
    return report("P2 light and slow traffic", d == 0 and slow == 0 and (dd is None or not any(dd.values())),
                  f"{d}/{n} desync at 100 Hz, {slow}/600 at 0.5/1/4 MHz, resync deltas: {dfmt(dd)}")

def p3(lengths=(1, 10, 50, 87, 90, 200, 4096), reps=20):
    """Wrong-length transfer under continuous traffic: the link comes back
    within LOST_MAX transfers and no register changes."""
    if not ensure_synced("P3"): return False
    xfer(w16(SERVO0, 1500)); snap = stable_snapshot()
    rows, ok = [], True
    for n in lengths:
        losts = []
        for _ in range(reps):
            s.xfer2([0] * n); time.sleep(50e-6)
            bad, last = after_slip()
            losts.append(last)
            if last >= 300:                      # didn't recover: firmware without resync
                break
        rows.append(f"n={n}: lost mean {sum(losts) / len(losts):.1f} max {max(losts)}")
        if max(losts) > LOST_MAX: ok = False
        if max(losts) >= 300:
            rows[-1] += " (no recovery)"
            if not allow_reset: break
            stm_reset()
    diff = snapshot_diff(snap, stable_snapshot()) if desyncs(30) == 0 else "link down"
    return report("P3 slip, continuous traffic", ok and not diff, "; ".join(rows) + f"; stray register changes: {diff}")

def p4(lengths=(1, 10, 50, 87, 90, 200), reps=20):
    """Wrong-length transfer, then the host pauses 10 ms: no transfer is lost."""
    if not ensure_synced("P4"): return False
    rows, ok = [], True
    for n in lengths:
        tot = 0
        for _ in range(reps):
            s.xfer2([0] * n)
            bad, last = after_slip(limit=150, pause=0.01)
            tot += bad
            if last >= 150: break
        rows.append(f"n={n}: {tot}")
        if tot: ok = False
        if last >= 150:
            rows[-1] += " (no recovery)"
            if not allow_reset: break
            stm_reset()
    return report("P4 slip, then 10 ms pause", ok, "bad frames after the pause, per length: " + "; ".join(rows))

def p5(reps=30):
    """Writes around a resync: the one before it is applied exactly once, and
    writes sent while the link is down are either dropped or applied whole."""
    if not ensure_synced("P5"): return False
    hi = lambda: read()[MOT_DONE] >> 4
    fails = []
    for k in range(reps):
        n = random.choice((1, 10, 50, 87, 90, 200))
        xfer(w16(SERVO0, 1500)); xfer(w16(SERVO0 + 2, 1500))
        c0 = hi()
        xfer([(0, 5)] + w16(SERVO0, 2000))            # rejected write: counter +1, servo0 = 2000
        s.xfer2([0] * n); time.sleep(50e-6)
        sent = []
        for i in range(60):                           # writes while the link may be down
            v = 600 + i; sent.append(v)
            xfer(w16(SERVO0 + 2, v))
        bad, last = after_slip()
        if last >= 300: fails.append((k, n, "no recovery")); break
        r = read(); c1 = r[MOT_DONE] >> 4
        if servo(r, 0) != 2000: fails.append((k, n, "servo0", servo(r, 0)))
        if (c1 - c0) & 15 != 1: fails.append((k, n, "reject counter step", (c1 - c0) & 15))
        if servo(r, 1) not in sent + [1500]: fails.append((k, n, "servo1 torn", servo(r, 1)))
        elif servo(r, 1) != sent[-1]: pass            # dropped writes are expected, not a failure
    xfer(w16(SERVO0, 1500)); xfer(w16(SERVO0 + 2, 1500))
    return report("P5 writes around a resync", not fails, f"failures={fails[:6]} ({len(fails)} of {reps})")

def p6(reps=30):
    """Full-length frames the firmware must reject. A bad start or end byte
    costs a resync on PR 13 (base: nothing); a wrong version must not."""
    if not ensure_synced("P6"): return False
    rows, ok = [], True
    for label, kw, resync in (("no 'J'", dict(start=0), True), ("no 'S'", dict(end=0), True),
                              ("version 3", dict(version=3), False), ("all zero", dict(start=0, version=0, end=0), True)):
        d0 = diag(); losts = []
        for _ in range(reps):
            xfer(w16(SERVO0, 2000), **kw)
            losts.append(after_slip(limit=150)[1])
        dd = ddelta(d0, diag())
        r = read()
        applied = servo(r) != 1500
        rows.append(f"{label}: lost mean {sum(losts) / reps:.1f} max {max(losts)}, applied={applied}, {dfmt(dd)}")
        if applied or max(losts) > LOST_MAX: ok = False
        if not resync and (max(losts) or (dd and dd["attempt"])): ok = False
        xfer(w16(SERVO0, 1500))
    return report("P6 rejected full-length frames", ok, "; ".join(rows))

def p7(secs=15):
    """Resync storm: a slip every 50 frames. The main loop must keep its
    cadence (needs the diag image for the timing numbers)."""
    if not ensure_synced("P7"): return False
    def rate():
        a = diag(); t0 = time.time(); time.sleep(1.0); b = diag(); t1 = time.time()
        return None if a is None else ((b["passes"] - a["passes"]) & 0xFFFF) / (t1 - t0)
    quiet = rate(); d0 = diag()
    t = time.time(); slips = i = 0; a = b = None
    while time.time() - t < secs:
        i += 1
        if i % 50 == 0: s.xfer2([0] * random.randint(1, 87)); slips += 1; time.sleep(50e-6)
        else: xfer()
        if d0 is not None and a is None and time.time() - t > 2:
            a = (diag(0), time.time())
        if d0 is not None and a is not None and b is None and time.time() - t > secs - 2:
            b = (diag(0), time.time())
    bad, last = after_slip()
    d1 = diag()
    if d1 is None:
        return report("P7 resync storm", last <= LOST_MAX, f"{slips} slips, recovered after {last}; no diag, timing not checked")
    busy = None if not (a and b and a[0] and b[0]) else ((b[0]["passes"] - a[0]["passes"]) & 0xFFFF) / (b[1] - a[1])
    over = (d1["over700"] - d0["over700"]) & 0xFFFF
    ok = last <= LOST_MAX and over == 0 and d1["irqoff_max"] <= 200 and busy is not None and busy >= 0.98 * quiet
    return report("P7 resync storm", ok,
                  f"{slips} slips, resets+{(d1['reset'] - d0['reset']) & 0xFFFF} retry+{(d1['retry'] - d0['retry']) & 0xFFFF} "
                  f"tries+{(d1['tries'] - d0['tries']) & 0xFFFF} cslow+{(d1['cslow'] - d0['cslow']) & 0xFFFF}; "
                  f"irq-off max {d1['irqoff_max'] / 10} us, check max {d1['check_max'] / 10} us, sensor section max {d1['sens_max']} us, "
                  f"passes over 700 us +{over}; loop rate quiet {quiet:.1f}/s, storm {busy and round(busy, 1)}/s")

def p8(reps=5):
    """STM32 reset while the host keeps polling: the link comes back aligned."""
    if not allow_reset:
        print("P8: SKIP  needs --reset"); return True
    rows, ok = [], True
    for _ in range(reps):
        p = subprocess.Popen(RESET_CMD, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        t = time.time(); run = 0; back = None
        while time.time() - t < 8:
            run = run + 1 if good(xfer()) else 0
            if p.poll() is not None and run >= 200 and back is None: back = time.time() - t; break
        p.wait()
        d = desyncs(500)
        rows.append(f"{'%.2fs' % back if back else 'never'}/{d}")
        if back is None or d: ok = False
    return report("P8 STM32 reset under polling", ok, "time to 200 good frames / desync in next 500: " + " ".join(rows))

def p9(secs=20):
    """Fuzz: random-length transfers mixed into valid traffic. Afterwards the
    link is aligned and no register changed."""
    if not ensure_synced("P9"): return False
    xfer(w16(SERVO0, 1500)); snap = stable_snapshot()
    t = time.time(); slips = 0
    while time.time() - t < secs:
        if random.random() < 0.1:
            s.xfer2([random.randrange(256) for _ in range(rand_len())]); slips += 1
        else: xfer()
        time.sleep(random.choice((0, 50e-6, 50e-6, 1e-3)))
    bad, last = after_slip(pause=0.05)
    diff = snapshot_diff(snap, stable_snapshot()) if last < 300 else "link down"
    return report("P9 random-length fuzz", last <= LOST_MAX and not diff,
                  f"{slips} random transfers; after 50 ms: {bad} bad, recovered after {last}; stray register changes: {diff}")

def p10(reps=200):
    """One 89-byte frame split into two transfers with chip select released
    between them (legal on the base firmware, which never looks at chip select)."""
    if not ensure_synced("P10"): return False
    d0 = diag(); bad = 0
    for _ in range(reps):
        b = frame()
        rx = s.xfer(b[:44]) + s.xfer(b[44:])       # xfer() releases chip select after each call
        time.sleep(50e-6)
        bad += rx[0] != ord('J')
        bad += after_slip(limit=5)[0] > 0
    dd = ddelta(d0, diag())
    return report("P10 frame split across chip select", bad == 0, f"{bad}/{reps} rounds with a bad frame, resync deltas: {dfmt(dd)}")


def p11(secs=20):
    """libwallaby-style read-modify-write across resyncs. libwallaby uses the
    reply even when it has no 'J' and never retries, so a bad read can be
    written back once the link recovers. Emulated on servo 0's position
    register (servos disabled): read its high byte, write the same value back.
    A corruption is a well-framed reply that shows the byte changed; the test
    then restores it and goes on."""
    if not ensure_synced("P11"): return False
    xfer(w16(SERVO0, 1500)); snap = stable_snapshot()
    want = 1500 >> 8
    t = time.time(); i = slips = badread = jwrong = corrupt = 0; landed = []
    while time.time() - t < secs:
        i += 1
        if i % 40 == 0:
            s.xfer2([0] * random.randint(1, 87)); slips += 1; time.sleep(50e-6)
        xfer(); r = xfer()                              # r8: the reply is used whatever it holds
        if r[0] != ord('J'): badread += 1
        elif r[SERVO0] != want:
            corrupt += 1; landed.append(r[SERVO0])
            xfer(w16(SERVO0, 1500)); continue
        elif any(r[k] != v for k, v in snap.items()): jwrong += 1
        xfer([(SERVO0, r[SERVO0])])                     # w8 of what was read
    bad, last = after_slip()
    head = f"{slips} slips, {badread} reads without 'J', {jwrong} replies with 'J' but other wrong contents"
    if last >= 300:
        if allow_reset: stm_reset()
        return report("P11 read-modify-write across resyncs", False, head + "; no recovery, so no write-back could land")
    xfer(w16(SERVO0, 1500))
    diff = snapshot_diff(snap, stable_snapshot())
    return report("P11 read-modify-write across resyncs", corrupt == 0 and not diff and jwrong == 0,
                  head + f"; register corrupted {corrupt} times (values {sorted(set(landed))[:16]}); stray changes: {diff}")


def p12(lengths=(88, 177), reps=3):
    """Transfer one byte short of a frame. Predicted (A1): the TX stream
    completes without the RX stream, DMA1_Stream4's interrupt re-enters until
    the next transfer, and the main loop only runs while chip select is low, so
    PR 13 never sees chip select high and cannot resync; on every firmware the
    main loop is starved while the host is idle."""
    if not ensure_synced("P12"): return False
    live0 = liveness(); rows, ok = [], True
    for n in lengths:
        for _ in range(reps):
            s.xfer2([0] * n)
            live = liveness()                          # light traffic: 50 frames/s
            bad, last = after_slip()
            rows.append(f"n={n}: distinct replies {live}/40, then lost {last}{' (no recovery)' if last >= 300 else ''}")
            if live < 0.8 * live0 or last > LOST_MAX: ok = False
            if last >= 300:
                if not allow_reset: break
                stm_reset()
    return report("P12 one byte short", ok, f"healthy: distinct replies {live0}/40; " + "; ".join(rows))


def health():
    """'ok', 'dead' (replies without 'J'), or 'silent' (replies look valid but
    a write isn't applied)."""
    if desyncs(6): return "dead"
    for v in (1400, 1500):
        xfer(w16(SERVO0 + 6, v))
        if servo(read(), 3) != v: return "silent" if desyncs(6) == 0 else "dead"
    return "ok"

def per_event(name, disturb, reps):
    """One disturbance at a time under continuous traffic, with a health check
    after each. Any state the link doesn't leave by itself is counted, examined
    (main-loop liveness, diag counters if readable) and cleared with an STM32
    reset."""
    if not allow_reset:
        print(f"{name}: SKIP  needs --reset"); return True
    if not ensure_synced(name.split()[0]): return False
    stuck, lost, done = [], [], 0
    for k in range(reps):
        disturb(); time.sleep(50e-6); done += 1
        bad, last = after_slip(limit=30)
        if last < 30: lost.append(last)
        h = health()
        if h != "ok":                                 # give it 300 more frames before calling it stuck
            after_slip(limit=300); h = health()
        if h == "ok": continue
        live = liveness()
        d = diag() if h == "silent" else None
        stuck.append((k, h, live, None if d is None else {x: d[x] for x in ("count", "frame", "attempt", "cslow", "reset", "retry", "ndtr_last", "passes")}))
        stm_reset()
        if desyncs(30): break
    kinds = {h: sum(1 for x in stuck if x[1] == h) for h in ("dead", "silent")}
    return report(name, not stuck,
                  f"{done} events: stuck dead {kinds['dead']}, stuck silent {kinds['silent']}; "
                  f"otherwise lost mean {sum(lost) / max(len(lost), 1):.2f} max {max(lost, default=0)}; "
                  f"stuck (event, kind, distinct replies of 40, diag): {stuck[:6]}")

def p13(reps=3000):
    """A10: each unframed 89-byte frame costs one reset, timed by the host's
    own traffic. If a reset races a host frame the link can end up in a state
    PR 13 can't leave (P12). Every transfer here is 89 bytes, so nothing else
    can knock the link out of such a state."""
    return per_event("P13 unframed frames, per-event health", lambda: s.xfer2(frame(start=0)), reps)

def p14(reps=3000):
    """The same per-event check for wrong-length transfers (1..87 bytes)."""
    return per_event("P14 wrong-length transfers, per-event health", lambda: s.xfer2([0] * random.randint(1, 87)), reps)


TESTS = dict(p1=p1, p2=p2, p3=p3, p4=p4, p5=p5, p6=p6, p7=p7, p8=p8, p9=p9, p10=p10, p11=p11, p12=p12, p13=p13, p14=p14)
names = sys.argv[1:]
if "--reset" in names: allow_reset = True; names.remove("--reset")
if not names or names == ["all"]: names = list(TESTS)
print(f"pr13_hw {time.strftime('%FT%TZ', time.gmtime())} tests: {' '.join(names)}")
time.sleep(1); desyncs(100)   # warm-up: the first frames after an STM32 reset can slip
r = read(); VER = r[1:3]
print(f"start={r[0]} version=0x{r[1]:02x}{r[2]:02x} diag={'yes' if diag() else 'no'}")
results = [TESTS[n]() for n in names]
sys.exit(0 if all(results) else 1)
