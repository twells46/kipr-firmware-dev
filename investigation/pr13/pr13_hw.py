#!/usr/bin/env python3
"""PR 13 hardware tests (run ON the Wombat, with botui stopped).

    sudo python3 pr13_hw.py [--reset] <test> [...]    tests: p1..p15, all
                                                      A9 (a9.md): e1, e2, mot
                                                      A10 (a10.md): b2, b7,
                                                      inj:STAGE:HZ:START:STOP:STEP:REPS

mot MOVES the motors on ports 0 and 3. Nothing else does.

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
import ctypes, random, subprocess, sys, time, spidev

N = 89
SERVO0, ALLSTOP, MOT_DONE = 78, 61, 60
# wallaby_flash's reset pulse on GPIO 23 (high, low, high, release), shortened.
# wallaby_reset_coproc itself blocks forever with libgpiod v2's gpioset.
RESET_CMD = ["gpioset", "-c", "0", "-t", "100ms,100ms,0", "23=1"]
LOST_MAX = 25          # PR 13 claims at most 20 transfers lost after a slip
ITEMS = ("count", "inflight", "ovr", "frame", "attempt", "cslow", "tries", "reset", "retry",
         "irqoff_max", "check_max", "ndtr_last", "sens_max", "over700", "passes")
RESYNC_ITEMS = ("count", "ovr", "frame", "attempt", "reset")
# Diag v2 (a9-diag2.patch): handle_dma() entries by which transfer-complete
# flags were set. tx and rx are 32-bit, published as two items.
ITEMS2 = ("tx_lo", "tx_hi", "rx_lo", "rx_hi", "both", "none")
# A10 injection image (a10-inj.patch): see the enum comment in wallaby_dma.h.
ITEMS3 = ("inj_done", "inj_timeout", "en_lo", "en_hi", "inj_end_c", "inj_end_s", "inj_l1_c", "inj_l1_s", "inj_l2_c", "inj_l2_s",
          "nat_end_c", "nat_end_s", "nat_l1_c", "nat_l1_s", "nat_l2_c", "nat_l2_s")
ALL_ITEMS = ITEMS + ITEMS2 + ITEMS3
GAP = lambda: 50e-6    # pause after each frame; libwallaby's usleep(50)
XFER_T = 0.0           # seconds the last diag() spent inside transfers
NITEMS = 0             # 15 (diag), 21 (diag v2), 37 (injection) or 99 (no diag); set at startup

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
    rx = s.xfer2(frame(pairs, **kw))   # a new list each time: xfer2 overwrites its argument with the reply
    time.sleep(GAP())
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

def ditem(f, rot=False):
    """(item, value) from a reply. rot=True looks at every rotation, for a link
    whose replies are offset (the one-byte-short state)."""
    for j in (range(N) if rot else (24,)):
        m, i, h, l, ni, c = (f[(j + k) % N] for k in range(6))
        if m == 0xD3 and i < len(ALL_ITEMS) and ni == (~i & 0xFF) and c == (0x5A + 13 * i + 31 * h + 3 * l) & 0xFF:
            return i, h << 8 | l
    return None

def diag(settle=0.02, rot=False, frames=400, fixed=False):
    """Latest value of every diagnostic item, or None if this isn't the diag
    image. fixed=True always sends `frames` frames, so two reads cost the main
    loop the same."""
    global XFER_T
    time.sleep(settle)
    vals = {}; XFER_T = 0.0
    for k in range(frames):
        t0 = time.perf_counter(); f = s.xfer2(frame()); XFER_T += time.perf_counter() - t0   # about the time chip select is low
        time.sleep(50e-6)
        it = ditem(f, rot) if rot or good(f) else None
        if it: vals[ALL_ITEMS[it[0]]] = it[1]
        if not rot: time.sleep(0.0003)
        if not fixed and len(vals) >= (NITEMS or len(ALL_ITEMS)) and k > 60: break
    if NITEMS == 0: return vals
    return vals if len(vals) >= NITEMS else None

def slow_diag(frames=None):
    """Counters from a link in the one-byte-short state. At 0.5 MHz chip select
    is low for 1.4 ms per frame, so the starved main loop still publishes."""
    hz = s.max_speed_hz; s.max_speed_hz = 500000
    try: return diag(0, rot=True, frames=frames or (260 if NITEMS == 37 else 120), fixed=True)
    finally: s.max_speed_hz = hz

def snap(d, who):
    """The reset snapshots of the injection image as 'end=TX/RX:flags:SR ...'.
    who is 'inj' (last armed reset) or 'nat' (last reset of any kind). Flags:
    T, R = the stream's transfer-complete flag, y = spi_resync set."""
    if d is None or f"{who}_end_c" not in d: return "no snapshot"
    out = []
    for tag in ("end", "l1", "l2"):
        c, st = d.get(f"{who}_{tag}_c"), d.get(f"{who}_{tag}_s")
        if c is None or st is None or not st & 0x8000: out.append(f"{tag}=-"); continue
        out.append(f"{tag}={c >> 8}/{c & 255}:{'T' if st & 0x1000 else ''}{'R' if st & 0x2000 else ''}{'y' if st & 0x4000 else ''}:{st & 0x1FF:03x}")
    return " ".join(out)

def bitrot(f):
    """(byte, bit) offset at which 'J' and the version start in the reply's bit
    stream, or None. (0, 0) is an aligned reply; (1, 0) is rotated one byte."""
    want = ord('J') << 16 | VER[0] << 8 | VER[1]
    v = int.from_bytes(bytes(f + f[:4]), "big"); nb = (N + 4) * 8
    for o in range(N * 8):
        if (v >> (nb - 24 - o)) & 0xFFFFFF == want: return divmod(o, 8)
    return None

def unrot(f):
    """The reply rotated so 'J' and the version are at 0..2, or None."""
    for j in range(N):
        if f[j] == ord('J') and [f[(j + 1) % N], f[(j + 2) % N]] == VER: return f[j:] + f[:j]
    return None

def u32(d, k):
    return d[k + "_hi"] << 16 | d[k + "_lo"]

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
        disturb(); time.sleep(GAP()); done += 1
        bad, last = after_slip(limit=30)
        if last < 30: lost.append(last)
        h = health()
        if h != "ok":                                 # give it 300 more frames before calling it stuck
            after_slip(limit=300); h = health()
        if h == "ok": continue
        live = liveness()
        d = diag() if h == "silent" else None
        row = (k, h, live, None if d is None else {x: d[x] for x in ("count", "frame", "attempt", "cslow", "reset", "retry", "ndtr_last", "passes")})
        if NITEMS == 37:                              # a10.md B2: counts at the reset that left it stuck
            off = bitrot(s.xfer2(frame())); sd = slow_diag()
            row += (f"reply offset {off}", snap(sd, "nat"))
            s.xfer2([0]); time.sleep(0.01); after_slip(limit=30)
            row += (f"after a 1-byte transfer: {health()}",)
        stuck.append(row)
        stm_reset()
        if desyncs(30): break
    kinds = {h: sum(1 for x in stuck if x[1] == h) for h in ("dead", "silent")}
    return report(name, not stuck,
                  f"{done} events: stuck dead {kinds['dead']}, stuck silent {kinds['silent']}; "
                  f"otherwise lost mean {sum(lost) / max(len(lost), 1):.2f} max {max(lost, default=0)}; "
                  f"stuck (event, kind, distinct replies of 40, diag): {stuck if NITEMS == 37 else stuck[:6]}")

def p13(reps=3000):
    """A10: each unframed 89-byte frame costs one reset, timed by the host's
    own traffic. If a reset races a host frame the link can end up in a state
    PR 13 can't leave (P12). Every transfer here is 89 bytes, so nothing else
    can knock the link out of such a state."""
    return per_event("P13 unframed frames, per-event health", lambda: s.xfer2(frame(start=0)), reps)

def p14(reps=3000):
    """The same per-event check for wrong-length transfers (1..87 bytes)."""
    return per_event("P14 wrong-length transfers, per-event health", lambda: s.xfer2([0] * random.randint(1, 87)), reps)


def e1():
    """A9 dose-response, any image. In the one-byte-short state the main loop
    should run only while chip select is low: distinct replies rise as the
    clock slows (longer frames) and don't depend on the gap between frames."""
    if not allow_reset:
        print("E1: SKIP  needs --reset"); return True
    rows, ok, byhz, bygap = [], True, {}, {}
    def one(hz, gap):
        stm_reset()
        if desyncs(30): return None
        s.max_speed_hz = hz; h = liveness(gap=gap)
        s.max_speed_hz = 16000000; s.xfer2([0] * 88); time.sleep(50e-6)
        s.max_speed_hz = hz; st = liveness(gap=gap); s.max_speed_hz = 16000000
        return h, st
    for hz in (16000000, 4000000, 1000000, 500000):
        byhz[hz] = one(hz, 0.02); rows.append(f"{hz / 1e6:g} MHz: healthy {byhz[hz][0]}, stuck {byhz[hz][1]}")
    for gap in (0.002, 0.02, 0.2):
        bygap[gap] = one(16000000, gap); rows.append(f"gap {gap * 1e3:g} ms: healthy {bygap[gap][0]}, stuck {bygap[gap][1]}")
    stm_reset()
    st = [byhz[h][1] for h in byhz]
    ok = st[0] <= 15 and st[2] >= 0.8 * byhz[1000000][0] and st[3] >= 0.8 * byhz[500000][0] \
        and max(v[1] for v in bygap.values()) <= 15
    return report("E1 stuck-state liveness vs clock and gap (of 40)", ok, "; ".join(rows))


def e2():
    """A9 mechanism, diag v2 image. Healthy: handle_dma() entries per frame by
    flag state at four clocks. Then the one-byte-short state with the host idle
    for 1 s: main-loop passes and lone-TX entries across the idle second."""
    if NITEMS != 21:
        print("E2: SKIP  needs the diag v2 image"); return True
    if not ensure_synced("E2"): return False
    rows, ok = [], True
    for hz, n in ((16000000, 4000), (4000000, 2000), (1000000, 1000), (500000, 600)):
        s.max_speed_hz = hz
        a = diag(); [xfer() for _ in range(n)]; b = diag()
        s.max_speed_hz = 16000000
        fr = (b["both"] - a["both"]) & 0xFFFF
        tx, rx, no = (u32(b, "tx") - u32(a, "tx")) & 0xFFFFFFFF, (u32(b, "rx") - u32(a, "rx")) & 0xFFFFFFFF, (b["none"] - a["none"]) & 0xFFFF
        rows.append(f"{hz / 1e6:g} MHz, >={n} frames: both {fr} tx_only {tx} rx_only {rx} none {no}")
        if rx: ok = False                              # tx_only > 0 is expected without the A9 fix, 0 with it
    report("E2a healthy handler entries", ok, "; ".join(rows))
    if not allow_reset:
        print("E2b: SKIP  needs --reset"); return ok
    a = diag(); t0 = time.time(); time.sleep(1.0); b = diag(); t1 = time.time()
    quiet = ((b["passes"] - a["passes"]) & 0xFFFF) / (t1 - t0)
    s.xfer2([0] * 88); time.sleep(50e-6)
    # The Pi's SPI clock can change with CPU frequency, so each read is
    # normalized by the time it spent inside transfers.
    rd = []
    for idle in (None, 0, 0, 1.0, 0, 3.0, 0):
        if idle: time.sleep(idle)
        rd.append((slow_diag(), XFER_T, idle))
    r0, r1, r2, r3 = rd[0][0], rd[2][0], rd[3][0], rd[5][0]
    live = liveness()
    stm_reset()
    if not all((r0, r1, r2, r3)):
        return report("E2b stuck and idle", False, f"couldn't read the counters in the stuck state: {[bool(x) for x in (r0, r1, r2, r3)]}") and ok
    dp = lambda x, y: (y["passes"] - x["passes"]) & 0xFFFF
    dh = lambda x, y: (y["tx_hi"] - x["tx_hi"]) & 0xFFFF
    if not all(x[0] for x in rd):
        return report("E2b stuck and idle", False, "a counter read failed in the stuck state") and ok
    # Passes between consecutive reads, against the passes a healthy loop would
    # make in the transfer time of the later read plus the idle time.
    rows, ok2 = [], True
    for (a, _, _), (b, xt, idle) in zip(rd, rd[1:]):
        got = dp(a, b); excess = got - quiet * xt
        rows.append(f"idle {idle or 0:g} s: {got} passes, {xt * 1e3:.0f} ms in transfers ({quiet * xt:.0f} passes' worth), excess {excess:+.0f}, lone-TX/65536 +{dh(a, b)}")
        if idle and (excess > 0.05 * quiet * idle or dh(a, b) == 0): ok2 = False
    last = rd[-1][0]; d = lambda k: (last[k] - r0[k]) & 0xFFFF
    return report("E2b stuck and idle", ok2 and d("reset") == 0,
                  f"healthy {quiet:.0f} passes/s; " + "; ".join(rows) + f"; over all reads: rx_only +{(u32(last, 'rx') - u32(r0, 'rx')) & 0xFFFFFFFF} "
                  f"frame +{d('frame')} attempt +{d('attempt')} cslow +{d('cslow')} tries +{d('tries')} reset +{d('reset')} count +{d('count')}; distinct replies {live}/40") and ok


def p15():
    """One byte short, then the host idle for 1 s. With the A9 fix on PR 13 the
    link must be back before the host's next frame and the main loop must have
    kept running through the pause."""
    if not ensure_synced("P15"): return False
    have = diag() is not None
    quiet = None
    if have:
        a = diag(); t0 = time.time(); time.sleep(1.0); b = diag(); t1 = time.time()
        quiet = ((b["passes"] - a["passes"]) & 0xFFFF) / (t1 - t0)
    rows, ok = [], True
    for n, hz in ((88, 16000000), (177, 16000000), (266, 16000000), (88, 4000000), (88, 1000000), (88, 500000)):
        d0 = diag() if have else None; t0 = time.time()
        s.max_speed_hz = hz; s.xfer2([0] * n); s.max_speed_hz = 16000000
        time.sleep(1.0)
        first = good(xfer()); bad, last = after_slip(limit=60)
        d1 = diag() if have and last < 60 else None; t1 = time.time()
        row = f"n={n} at {hz / 1e6:g} MHz: first frame {'good' if first else 'BAD'}, lost {bad}"
        if not first or bad: ok = False
        if d0 and d1:
            rate = ((d1["passes"] - d0["passes"]) & 0xFFFF) / (t1 - t0); rs = (d1["reset"] - d0["reset"]) & 0xFFFF
            row += f", {rate:.0f} passes/s, reset +{rs}"
            if rate < 0.95 * quiet or rs != 1: ok = False
        elif have: ok = False
        rows.append(row)
        if last >= 60:
            if not allow_reset: break
            stm_reset()
    return report("P15 one byte short, host idle", ok, (f"healthy {quiet:.0f} passes/s; " if quiet else "no diag; ") + "; ".join(rows))


def mot(ports=(0, 3), reps=3, power=25):
    """MOVES the motors on `ports`. Runs them, sends a one-byte-short transfer,
    asks libkipr to stop them (ao), leaves the host idle for 2 s, and then
    checks whether they stopped. Always ends with the motors off; a link that
    didn't recover is cleared with an STM32 reset, which stops them."""
    if not allow_reset:
        print("MOT: SKIP  needs --reset"); return True
    lib = ctypes.CDLL("/usr/lib/libkipr.so")
    # libwallaby swaps ports 2 and 3 (fix_port), and scales the raw counter
    # down for gmpc; positions here are raw counts.
    ch = [p if p < 2 else 5 - p for p in ports]
    def pos(f): return [int.from_bytes(bytes(f[42 + 4 * c:46 + 4 * c]), "big", signed=True) for c in ch]
    def cmd(f): return [f[58], f[59]] + [f[70 + 2 * c] << 8 | f[71 + 2 * c] for c in ch]
    rows, ok = [], True
    try:
        for r in range(reps):
            if not ensure_synced("MOT"): return False
            for p in ports: lib.cmpc(p)
            for p in ports: lib.motor(p, power)
            time.sleep(1.0); a = pos(read()); time.sleep(0.5); b = read()
            run = [(y - x) * 2 for x, y in zip(a, pos(b))]
            lk = [lib.gmpc(p) for p in ports]
            s.xfer2([0] * 88); time.sleep(50e-6)
            for _ in range(3): lib.ao(); time.sleep(0.01)
            time.sleep(2.0)
            f = xfer()
            if good(f) and desyncs(20) == 0:
                c = pos(read()); time.sleep(0.5); d = read()
                drift = [y - x for x, y in zip(c, pos(d))]
                stopped = all(abs(x) <= 0.02 * abs(v) for x, v in zip(drift, run)) and all(run)
                rows.append(f"rep {r}: running {run} raw counts/s (gmpc {lk}), cmd before {cmd(b)}; "
                            f"link recovered, drift {drift} raw counts in 0.5 s, cmd after {cmd(d)} -> {'stopped' if stopped else 'STILL RUNNING'}")
                ok &= stopped
            else:
                # Stuck: read at 0.5 MHz so the main loop gets time to sample back-EMF.
                s.max_speed_hz = 500000; t0 = time.time(); ser = []
                for _ in range(300):
                    u = unrot(s.xfer2(frame()))
                    if u: ser.append((time.time() - t0, pos(u), cmd(u)))
                s.max_speed_hz = 16000000
                if len(ser) > 20:
                    early = [y - x for x, y in zip(ser[0][1], ser[10][1])]; dt_e = ser[10][0] - ser[0][0]
                    late = [y - x for x, y in zip(ser[-11][1], ser[-1][1])]; dt_l = ser[-1][0] - ser[-11][0]
                    tot = [y - x for x, y in zip(ser[0][1], ser[-1][1])]
                    rows.append(f"rep {r}: running {run} ticks/s, cmd before {cmd(b)}; link STUCK after ao() and 2 s idle; "
                                f"read at 0.5 MHz for {ser[-1][0]:.2f} s: moved {tot} ticks, first 10 frames {early} in {dt_e * 1e3:.0f} ms, "
                                f"last 10 {late} in {dt_l * 1e3:.0f} ms, cmd still {ser[-1][2]} -> stop not applied")
                else:
                    rows.append(f"rep {r}: running {run} ticks/s; link STUCK, only {len(ser)} readable replies")
                ok = False
                stm_reset()
            lib.ao(); time.sleep(0.5)
    finally:
        s.max_speed_hz = 16000000
        if desyncs(10): subprocess.run(RESET_CMD, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(1); desyncs(100)
        lib.ao()
    return report("MOT one byte short with motors running", ok, "; ".join(rows))


INJ_KEYS = ("reset", "retry", "count", "frame", "ovr", "inj_done", "inj_timeout")

def inj_one(stage, delay, hz, base):
    """One injected race (a10.md). Arms the firmware, sends the frame its reset
    races at `hz`, and classifies the link afterwards. Returns (record, diag
    after), the latter being the next call's `base`."""
    arm = [0] * N
    arm[0], arm[1], arm[2], arm[3], arm[4] = 0xA1, stage, delay >> 16 & 255, delay >> 8 & 255, delay & 255
    s.xfer2(arm); time.sleep(0.005)
    s.max_speed_hz = hz; raced = s.xfer2(frame()); s.max_speed_hz = 16000000
    time.sleep(0.010)
    seq = [good(xfer()) for _ in range(31)]
    k = max((i + 1 for i, g in enumerate(seq) if not g), default=0)
    h = health()
    if h != "ok": after_slip(limit=300); h = health()
    rec = dict(s=stage, hz=hz, d=delay, raced=bitrot(raced))
    if h == "ok":
        d = diag(0)
        rec["cls"] = "ok" if k == 0 else f"rec{k}"
    else:
        rec["cls"] = h; rec["live"] = liveness(20, 0.005); rec["off"] = bitrot(s.xfer2(frame()))
        d = slow_diag()
        s.xfer2([0]); time.sleep(0.01); after_slip(limit=30)
        rec["onebyte"] = health()
    if d:
        rec["snap"] = snap(d, "inj"); rec["en"] = d["en_hi"] << 16 | d["en_lo"]
        if base: rec.update({"+" + x: (d[x] - base[x]) & 0xFFFF for x in INJ_KEYS})
    if h != "ok":
        stm_reset(); d = diag()
    return rec, d

def inj(stage, hz, start, stop, step, reps):
    """Sweep the delay of an injected race. One 'INJ' line per injection."""
    if NITEMS != 37:
        print("INJ: SKIP  needs the injection image"); return True
    if not allow_reset:
        print("INJ: SKIP  needs --reset"); return True
    if not ensure_synced("INJ"): return False
    base = diag(); tally = {}
    for delay in range(start, stop + 1, step):
        for _ in range(reps):
            rec, base = inj_one(stage, delay, hz, base)
            c = rec["cls"] if rec["cls"] in ("ok", "dead", "silent") else "recovered"
            tally[c] = tally.get(c, 0) + 1
            print("INJ " + " ".join(f"{a}={str(b).replace(' ', '') if a != 'snap' else '[' + b + ']'}" for a, b in rec.items()), flush=True)
            if base is None and not ensure_synced("INJ"): return False
            if base is None: base = diag()
    print(f"INJ stage {stage} at {hz / 1e6:g} MHz, delay {start}..{stop} step {step} x{reps}: {tally}")
    return True


def b2():
    """a10.md B2: the injection image, never armed, behaves like the diag image."""
    return all([p1(2000), p13(), p14()])

def b7():
    """a10.md B7: soak of the plain fix at several frame gaps and two clocks."""
    global GAP
    res = []
    try:
        for hz in (16000000, 4000000):
            for name, g in (("0", lambda: 0), ("50 us", lambda: 50e-6), ("200 us", lambda: 200e-6), ("random 0-1 ms", lambda: random.random() * 1e-3)):
                GAP = g; s.max_speed_hz = hz
                print(f"B7 clock {hz / 1e6:g} MHz, gap {name}:", flush=True)
                res += [p13(3750), p14(3750)]
    finally:
        GAP = lambda: 50e-6; s.max_speed_hz = 16000000
    for _ in range(10): res.append(p6())
    res.append(p8(20))
    return all(res)


TESTS = dict(b2=b2, b7=b7, e1=e1, e2=e2, p15=p15, mot=mot, mot0=lambda: mot((0,)), mot3=lambda: mot((3,)), p1=p1, p2=p2, p3=p3, p4=p4, p5=p5, p6=p6, p7=p7, p8=p8, p9=p9, p10=p10, p11=p11, p12=p12, p13=p13, p14=p14)
names = sys.argv[1:]
if "--reset" in names: allow_reset = True; names.remove("--reset")
if not names or names == ["all"]: names = [n for n in TESTS if n[0] == "p"]   # e1, e2 and mot only by name
print(f"pr13_hw {time.strftime('%FT%TZ', time.gmtime())} tests: {' '.join(names)}")
time.sleep(1); desyncs(100)   # warm-up: the first frames after an STM32 reset can slip
r = read(); VER = r[1:3]
probe = diag()
NITEMS = 37 if any(k in probe for k in ITEMS3) else 21 if any(k in probe for k in ITEMS2) else 15 if len(probe) == 15 else 99
print(f"start={r[0]} version=0x{r[1]:02x}{r[2]:02x} diag={ {37: 'injection', 21: 'v2', 15: 'yes', 99: 'no'}[NITEMS]}")
def run(n):
    if n.startswith("inj:"): return inj(*(int(float(x)) for x in n.split(":")[1:]))
    return TESTS[n]()
results = [run(n) for n in names]
sys.exit(0 if all(results) else 1)
