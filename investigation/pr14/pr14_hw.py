#!/usr/bin/env python3
"""PR 14 hardware tests (run ON the Wombat, with botui stopped).

    sudo python3 pr14_hw.py [--reset] [--enable] <test> [...]    tests: s1..s12, l1..l4, all

Talks to the STM32 with raw spidev frames shaped like libwallaby's (89 bytes,
zero padded, 16 MHz, 50 us between transfers).

Reads servo power from the PE10 diagnostics that pr14-diag.patch publishes in
the magnetometer slots (builds/pr14-merge-master+diag). On any other image the
power checks print "no diag"; s1 then reports only what the register map shows.

Nothing is enabled unless --enable is given: tests that clear a servo disable
bit (REG_RW_MOT_SRV_ALLSTOP bits 4-7) SKIP without it. With --enable, servo
pulses start on the cleared ports at the position already in the register
(set to 1500 first), and the 6 V rail comes on: an attached servo moves to
centre. Motors are never commanded (motor bits 0-3 are only ever set, never
cleared, and no PWM or mode is written).

--reset lets a test reset the STM32 (a pulse on GPIO 23); s1 needs it.
Expected results are in investigation/pr14/pr14.md.
"""
import random, signal, subprocess, sys, time, spidev

N = 89
SERVO0, ALLSTOP = 78, 61
SRV_BITS = 0xF0
RESET_CMD = ["gpioset", "-c", "0", "-t", "100ms,100ms,0", "23=1"]
GAP = 50e-6
CUT_US = 40000

s = spidev.SpiDev(); s.open(0, 0); s.max_speed_hz = 16000000
ctr = 0
VER = None
allow_reset = allow_enable = False
HAVE_DIAG = False


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
    time.sleep(GAP)
    return rx

def good(rx):
    return rx[0] == ord('J') and (VER is None or rx[1:3] == VER)

def read():
    xfer(); return xfer()

def desyncs(n):
    return sum(not good(xfer()) for _ in range(n))

def w16(addr, val):
    return [(addr, val >> 8), (addr + 1, val & 0xFF)]

def stm_reset():
    subprocess.run(RESET_CMD, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

def ensure_synced(name):
    if desyncs(30) == 0: return True
    time.sleep(0.05)
    if desyncs(30) == 0: return True
    if allow_reset:
        stm_reset(); time.sleep(1); desyncs(100)
        if desyncs(30) == 0: return True
    print(f"{name}: SKIP  link is desynchronized before the test (rerun with --reset)")
    return False

def report(name, ok, detail):
    print(f"{name}: {'PASS' if ok else 'FAIL'}  {detail}", flush=True)
    return ok

def skip(name, why):
    print(f"{name}: SKIP  {why}", flush=True)
    return True


# --- PE10 diagnostics -------------------------------------------------------

def pe10(rx):
    """Decoded diag bytes 24-29 from one reply, or None (no marker, no 'J')."""
    if not good(rx) or rx[24] != 0xE4: return None
    st = rx[25]
    return dict(idr=st & 1, odr=st >> 1 & 1, moder=st >> 2 & 3, od=st >> 4 & 1, alldis=st >> 5 & 1,
                offs=rx[26], ons=rx[27], delay=rx[28] << 8 | rx[29], allstop=rx[ALLSTOP])

def state(n=3):
    """n consecutive replies that agree (the main loop rewrites bytes 24-29
    while DMA may be sending them)."""
    for _ in range(200):
        a = [pe10(xfer()) for _ in range(n)]
        if a[0] is not None and all(x == a[0] for x in a): return a[0]
    return None

def power(d):
    """'on' if the regulator enable is released (ODR 1), 'off' if driven low."""
    return None if d is None else ("on" if d["odr"] else "off")

def wait_for(pred, timeout):
    """Poll at frame rate until pred(diag) holds. Returns (seconds, diag) or (None, last)."""
    t0 = time.monotonic(); d = None
    while time.monotonic() - t0 < timeout:
        d = pe10(xfer())
        if d is not None and pred(d): return time.monotonic() - t0, d
    return None, d

def set_allstop(v):
    r = read()
    motor = r[ALLSTOP] & 0x0F
    xfer([(ALLSTOP, (v & SRV_BITS) | motor)])

def need_diag(name):
    if HAVE_DIAG: return True
    print(f"{name}: SKIP  no diag (flash builds/pr14-merge-master+diag)")
    return False

def need_enable(name):
    if allow_enable: return True
    print(f"{name}: SKIP  clears a servo disable bit (rerun with --enable)")
    return False

def centre_all():
    xfer(w16(SERVO0, 1500) + w16(SERVO0 + 2, 1500) + w16(SERVO0 + 4, 1500) + w16(SERVO0 + 6, 1500))


# --- tests ------------------------------------------------------------------

def s1(reps=5):
    """Boot state. After each STM32 reset, the first diag frame shows PE10 as an
    open-drain output driven low (MODER 01, OTYPER 1, ODR 0, IDR 0), ALLSTOP
    0xF0, and no transitions yet. On master (no diag) it reports the register
    map only."""
    if not allow_reset: return skip("S1 boot state", "needs --reset")
    bad = []
    for i in range(reps):
        stm_reset(); time.sleep(0.5); desyncs(100)
        r = read()
        d = state() if HAVE_DIAG else None
        if r[ALLSTOP] & SRV_BITS != SRV_BITS: bad.append(f"#{i} ALLSTOP=0x{r[ALLSTOP]:02x}")
        if HAVE_DIAG and (d is None or (d["moder"], d["od"], d["odr"], d["idr"], d["offs"], d["ons"]) != (1, 1, 0, 0, 0, 0)):
            bad.append(f"#{i} {d}")
    return report("S1 boot state", not bad, f"{reps} resets; bad: {bad[:5]}" + ("" if HAVE_DIAG else " (no diag: ALLSTOP only)"))

def s2(reps=20):
    """Enable latency. Clearing one servo bit (all four, one at a time)
    releases PE10 within 3 ms and the pin reads high (R52 pulls EN up);
    setting it back cuts power after 40 ms. Fails if: latency > 3 ms; IDR
    stays 0 while released; 'ons' moves by other than 1 per enable."""
    name = "S2 enable latency"
    if not (need_diag(name) and need_enable(name) and ensure_synced(name)): return False
    centre_all(); set_allstop(0xF0)
    if wait_for(lambda d: d["odr"] == 0, 0.2)[0] is None: return report(name, False, "power never went off to start")
    lat = []; bad = []
    for i in range(reps):
        port = i % 4
        d0 = state()
        set_allstop(0xF0 & ~(0x10 << port))
        t, d = wait_for(lambda d: d["odr"] == 1, 0.05)
        if t is None: bad.append(f"#{i} never released"); continue
        lat.append(t * 1000)
        time.sleep(0.005); d1 = state()            # IDR is sampled at the start of a pass, so skip the releasing pass
        if d1["idr"] != 1: bad.append(f"#{i} released but IDR=0")
        if (d1["ons"] - d0["ons"]) & 0xFF != 1: bad.append(f"#{i} ons +{(d1['ons'] - d0['ons']) & 0xFF}")
        set_allstop(0xF0)
        if wait_for(lambda d: d["odr"] == 0, 0.2)[0] is None: bad.append(f"#{i} never cut")
    ok = not bad and lat and max(lat) <= 3
    return report(name, ok, f"latency ms min/mean/max {min(lat, default=0):.2f}/{sum(lat) / max(len(lat), 1):.2f}/{max(lat, default=0):.2f}; bad: {bad[:5]}")

def s3(reps=50):
    """Cut delay. From one servo enabled, setting all four bits cuts power
    after 40 ms: firmware-measured delay in [40000, 41500] us and host-seen
    delay in [38, 46] ms, every time."""
    name = "S3 cut delay"
    if not (need_diag(name) and need_enable(name) and ensure_synced(name)): return False
    centre_all(); fw = []; host = []; bad = []
    for i in range(reps):
        set_allstop(0xE0)
        if wait_for(lambda d: d["odr"] == 1, 0.05)[0] is None: bad.append(f"#{i} not on"); continue
        time.sleep(random.uniform(0.001, 0.025))     # random phase against the 20 ms servo period
        d0 = state(); motor = read()[ALLSTOP] & 0x0F
        xfer([(ALLSTOP, 0xF0 | motor)])               # applied when this frame ends
        t, d = wait_for(lambda d: d["odr"] == 0, 0.2)
        if t is None: bad.append(f"#{i} never cut"); continue
        d1 = state()
        host.append(t * 1000)
        fw.append(d1["delay"])
        if (d1["offs"] - d0["offs"]) & 0xFF != 1: bad.append(f"#{i} offs +{(d1['offs'] - d0['offs']) & 0xFF}")
    ok = not bad and fw and min(fw) >= CUT_US and max(fw) <= CUT_US + 1500 and min(host) >= 38 and max(host) <= 46
    return report(name, ok, f"fw us min/max {min(fw, default=0)}/{max(fw, default=0)}; host ms min/max {min(host, default=0):.1f}/{max(host, default=0):.1f}; bad: {bad[:5]}")

def s4():
    """Only all four servo bits cut power. Each of the 15 other servo-bit
    patterns keeps power on for 200 ms; motor bits 0-3 (set only) never
    change the power state."""
    name = "S4 partial disable"
    if not (need_diag(name) and need_enable(name) and ensure_synced(name)): return False
    centre_all(); bad = []
    for pat in range(16):
        v = pat << 4
        if v == 0xF0: continue
        set_allstop(v)
        if wait_for(lambda d: d["odr"] == 1, 0.05)[0] is None: bad.append(f"0x{v:02x} not on"); continue
        d0 = state(); time.sleep(0.2); d1 = state()
        if d1["odr"] != 1 or d1["offs"] != d0["offs"]: bad.append(f"0x{v:02x} went off")
    # all servos disabled; set motor stop bits too (stop is safe), power must still go off and stay off
    set_allstop(0xF0)
    if wait_for(lambda d: d["odr"] == 0, 0.2)[0] is None: bad.append("0xF0 never cut")
    d0 = state()
    r = read(); xfer([(ALLSTOP, 0xFF)]); time.sleep(0.1)
    d1 = state()
    if d1["odr"] != 0 or d1["ons"] != d0["ons"]: bad.append("motor bits changed power")
    xfer([(ALLSTOP, r[ALLSTOP])])
    return report(name, not bad, f"bad: {bad}")

def s5(reps=10):
    """Re-enable inside the window. Disable all, re-enable after 5/20/35 ms:
    power never goes off ('offs' unchanged), and the next full disable still
    waits the full 40 ms (the window restarts)."""
    name = "S5 re-enable inside 40 ms"
    if not (need_diag(name) and need_enable(name) and ensure_synced(name)): return False
    centre_all(); set_allstop(0xE0); wait_for(lambda d: d["odr"] == 1, 0.05)
    bad = []
    for i in range(reps):
        for ms in (5, 20, 35):
            d0 = state()
            set_allstop(0xF0); time.sleep(ms / 1000); set_allstop(0xE0)
            time.sleep(0.01); d1 = state()
            if d1["offs"] != d0["offs"] or d1["odr"] != 1: bad.append(f"#{i} {ms} ms: cut")
    set_allstop(0xF0); t, d = wait_for(lambda d: d["odr"] == 0, 0.2)
    if t is None or state()["delay"] < CUT_US: bad.append(f"final cut early or missing: {t} {d}")
    return report(name, not bad, f"bad: {bad[:5]}")

def s6(n=20000):
    """Healthy traffic, all servos disabled: power stays off, no transition,
    no reply without 'J'."""
    name = "S6 idle soak"
    if not (need_diag(name) and ensure_synced(name)): return False
    set_allstop(0xF0)
    if wait_for(lambda d: d["odr"] == 0, 0.2)[0] is None: return report(name, False, "power not off at start")
    d0 = state(); bad = 0; on = 0
    for i in range(n):
        rx = xfer(w16(SERVO0, 1500)) if i % 2 else xfer()
        bad += not good(rx)
        d = pe10(rx)
        on += d is not None and d["odr"] == 1
    d1 = state()
    ok = bad == 0 and on == 0 and d1["ons"] == d0["ons"] and d1["offs"] == d0["offs"]
    return report(name, ok, f"{bad}/{n} without 'J', {on} frames with power on, ons +{(d1['ons'] - d0['ons']) & 0xFF}, offs +{(d1['offs'] - d0['offs']) & 0xFF}")

def s7(secs=20):
    """Link slips (PR 13 resync) with all servos disabled and the host never
    clearing a servo bit: power never comes on. Random-length transfers and
    unframed frames mixed into traffic."""
    name = "S7 slips while disabled"
    if not (need_diag(name) and ensure_synced(name)): return False
    set_allstop(0xF0); wait_for(lambda d: d["odr"] == 0, 0.2)
    d0 = state(); t = time.time(); slips = 0; seen_on = 0
    while time.time() - t < secs:
        x = random.random()
        if x < 0.05: s.xfer2([random.randrange(256) for _ in range(random.randint(1, 200))]); slips += 1
        elif x < 0.08: xfer(start=0); slips += 1
        else:
            d = pe10(xfer())
            seen_on += d is not None and d["odr"] == 1
    time.sleep(0.05); desyncs(400)
    d1 = state()
    ok = d1 is not None and seen_on == 0 and d1["ons"] == d0["ons"] and d1["allstop"] & SRV_BITS == SRV_BITS
    return report(name, ok, f"{slips} slips, {seen_on} frames with power on, ons +{(d1['ons'] - d0['ons']) & 0xFF if d1 else '?'}, final {d1}")

def s8(secs=20):
    """libwallaby-style read-modify-write of ALLSTOP across slips, as
    disable_servo(0) does: read ALLSTOP, set bit 4, write it back, while the
    host only ever disables. Fails if power ever comes on (a bad read written
    back cleared a servo bit). Counts the bad reads that were written back."""
    name = "S8 RMW of ALLSTOP across slips"
    if not (need_diag(name) and need_enable(name) and ensure_synced(name)): return False
    centre_all(); set_allstop(0xF0); wait_for(lambda d: d["odr"] == 0, 0.2)
    d0 = state(); t = time.time(); i = slips = badread = seen_on = 0
    while time.time() - t < secs:
        i += 1
        if i % 40 == 0: s.xfer2([0] * random.randint(1, 87)); slips += 1; time.sleep(GAP)
        xfer(); r = xfer()
        if r[0] != ord('J'): badread += 1
        d = pe10(r); seen_on += d is not None and d["odr"] == 1
        xfer([(ALLSTOP, r[ALLSTOP] | 0x10)])          # disable_servo(0): r8, set bit, w8
    time.sleep(0.05); desyncs(400); set_allstop(0xF0)
    d1 = state()
    ons = (d1["ons"] - d0["ons"]) & 0xFF if d1 else None
    return report(name, seen_on == 0 and ons == 0, f"{slips} slips, {badread} bad reads written back, {seen_on} frames with power on, ons +{ons}")

def s9(reps=5):
    """STM32 reset while a servo is enabled and powered: after the reset
    power is off on the first diag frame and stays off for 1 s."""
    name = "S9 reset while powered"
    if not (need_diag(name) and need_enable(name) and allow_reset): return skip(name, "needs diag, --enable and --reset")
    bad = []
    for i in range(reps):
        ensure_synced(name); centre_all(); set_allstop(0xE0)
        if wait_for(lambda d: d["odr"] == 1, 0.05)[0] is None: bad.append(f"#{i} not on"); continue
        stm_reset(); time.sleep(0.3); desyncs(100)
        d = state(); time.sleep(1); d2 = state()
        if d is None or d["odr"] or d2["odr"] or d2["ons"]: bad.append(f"#{i} {d} {d2}")
    return report(name, not bad, f"bad: {bad}")

def s10(secs=20):
    """libwallaby-style read-modify-write toggling of servo 0 across slips while
    servos 1-3 stay enabled: power must never be cut. A misaligned read (e.g.
    register 60, whose high nibble is the reject count) written back with
    bits 4-7 all set would cut the rail and drop every arm."""
    name = "S10 RMW toggles never cut power"
    if not (need_diag(name) and need_enable(name) and ensure_synced(name)): return False
    centre_all(); set_allstop(0x10)
    if wait_for(lambda d: d["odr"] == 1, 0.05)[0] is None: return report(name, False, "power not on at start")
    d0 = state(); t = time.time(); i = slips = badread = seen_off = allset = 0
    while time.time() - t < secs:
        i += 1
        if i % 40 == 0: s.xfer2([random.randrange(256) for _ in range(random.randint(1, 87))]); slips += 1; time.sleep(GAP)
        xfer(); r = xfer()
        if r[0] != ord('J'): badread += 1
        d = pe10(r); seen_off += d is not None and d["odr"] == 0
        v = (r[ALLSTOP] | 0x10) if i % 2 else (r[ALLSTOP] & ~0x10)   # disable_servo(0) / enable_servo(0)
        allset += v & SRV_BITS == SRV_BITS
        xfer([(ALLSTOP, v & 0xFF)])
    time.sleep(0.05); desyncs(400)
    d1 = state(); set_allstop(0xF0)
    offs = (d1["offs"] - d0["offs"]) & 0xFF if d1 else None
    return report(name, seen_off == 0 and offs == 0,
                  f"{slips} slips, {badread} bad reads, {allset} write-backs with all four bits set, {seen_off} frames with power off, offs +{offs}")
def s12(secs=20):
    """C7 as a program would hit it: servos 1-3 enabled and holding, the
    program keeps calling disable_servo(0) (read-modify-write, idempotent on a
    good read) across slips. One bad read written back with bits 4-7 all set
    persists, because every later disable_servo(0) reads it and writes it back,
    so power is cut 40 ms later and every arm drops. Fails if power is ever
    cut. Each cut is undone (servos 1-3 re-enabled) and counted."""
    name = "S12 persistent disable_servo(0) across slips"
    if not (need_diag(name) and need_enable(name) and ensure_synced(name)): return False
    centre_all(); set_allstop(0x10)
    if wait_for(lambda d: d["odr"] == 1, 0.05)[0] is None: return report(name, False, "power not on at start")
    d0 = state(); t = time.time(); i = slips = badread = allset = cuts = 0
    while time.time() - t < secs:
        i += 1
        if i % 40 == 0: s.xfer2([random.randrange(256) for _ in range(random.randint(1, 87))]); slips += 1; time.sleep(GAP)
        xfer(); r = xfer()
        if r[0] != ord('J'): badread += 1
        v = (r[ALLSTOP] | 0x10) & 0xFF
        allset += v & SRV_BITS == SRV_BITS
        xfer([(ALLSTOP, v)])
        d = pe10(r)
        if d is not None and d["odr"] == 0:
            cuts += 1; xfer([(ALLSTOP, 0x10 | (r[ALLSTOP] & 0x0F))]); time.sleep(0.002)
    time.sleep(0.05); desyncs(400)
    d1 = state(); set_allstop(0xF0)
    offs = (d1["offs"] - d0["offs"]) & 0xFF if d1 else None
    return report(name, offs == 0, f"{slips} slips, {badread} bad reads, {allset} write-backs with all four bits set, {cuts} cuts seen, offs +{offs}")

def s11(n=2000):
    """Digital pin reconfiguration (update_dig_pin_configs via the pull-up
    registers only; no pin is made an output) and analog pull-up changes never
    touch PE10: MODER stays 01, OTYPER 1, and the power state and counters are
    unchanged. Run with servos disabled (power off)."""
    name = "S11 pin reconfig leaves PE10 alone"
    if not (need_diag(name) and ensure_synced(name)): return False
    set_allstop(0xF0); wait_for(lambda d: d["odr"] == 0, 0.2)
    r = read(); pe = (r[7], r[8]); d0 = state(); bad = 0
    for i in range(n):
        v = 0xFF if i % 2 else 0x00
        rx = xfer([(7, v), (8, v)])
        d = pe10(rx)
        bad += d is not None and (d["moder"] != 1 or d["od"] != 1 or d["odr"] != 0)
    xfer([(7, pe[0]), (8, pe[1])])
    d1 = state()
    ok = bad == 0 and (d1["moder"], d1["od"], d1["odr"], d1["ons"], d1["offs"]) == (1, 1, 0, d0["ons"], d0["offs"])
    return report(name, ok, f"{n} pull-up rewrites, {bad} frames with PE10 changed, final {d1}")


# --- libkipr-level tests ------------------------------------------------------
# Each scenario runs as a child process that loads /usr/lib/libkipr.so with
# ctypes; this process reads register 61 and the diag over raw spidev only
# after the child has exited (libkipr's own cleanup would disturb a probe
# that used it).

LIB = "/usr/lib/libkipr.so"
CHILD_HEAD = "import ctypes, os, signal, time; k = ctypes.CDLL(%r); " % LIB

def child(code, signal_after=None, sig=None, timeout=10):
    p = subprocess.Popen([sys.executable, "-c", CHILD_HEAD + code], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if signal_after is not None:
        time.sleep(signal_after); p.send_signal(sig)
    try: out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired: p.kill(); out, _ = p.communicate()
    return p.returncode, out.strip()

def after_child():
    time.sleep(0.1); desyncs(20)
    r = read(); d = state() if HAVE_DIAG else None
    return r[ALLSTOP], d

def l1():
    """Exit paths. A program enables all servos, then ends. Expected: return,
    sys.exit(1), SIGINT, SIGTERM and shut_down_in leave ALLSTOP bits 4-7 set
    and power off (diag); SIGKILL and os._exit leave them clear and power on.
    Any other combination falsifies the PR's 'limp when a program ends'."""
    name = "L1 exit paths"
    if not (need_enable(name) and ensure_synced(name)): return False
    centre_all()
    body = "k.enable_servos(); time.sleep(0.3); "
    cases = [("return", body, None, None, True), ("exit(1)", body + "raise SystemExit(1)", None, None, True),
             ("SIGINT", body + "time.sleep(5)", 0.6, signal.SIGINT, True), ("SIGTERM", body + "time.sleep(5)", 0.6, signal.SIGTERM, True),
             ("shut_down_in", "k.shut_down_in(ctypes.c_double(0.5)); " + body + "time.sleep(5)", None, None, True),
             ("SIGKILL", body + "time.sleep(5)", 0.6, signal.SIGKILL, False), ("os._exit", body + "os._exit(0)", None, None, False)]
    bad = []; rows = []
    for label, code, after, sig, limp in cases:
        set_allstop(0xF0); time.sleep(0.06)
        rc, out = child(code, after, sig)
        a, d = after_child()
        off = None if d is None else d["odr"] == 0
        rows.append(f"{label}: rc={rc} 61=0x{a:02x} power={'?' if d is None else ('off' if off else 'on')}")
        if (a & SRV_BITS == SRV_BITS) != limp or (off is not None and off != limp): bad.append(label)
    set_allstop(0xF0)
    for row in rows: print("   ", row)
    return report(name, not bad, f"unexpected: {bad}")

def l2():
    """Program start does not write register 61: with servo 0 enabled by the
    host, a libkipr program that reads analog(0) and leaves with os._exit
    (no cleanup) leaves 61 unchanged and causes no power transition."""
    name = "L2 program start leaves 61 alone"
    if not (need_enable(name) and ensure_synced(name)): return False
    centre_all(); set_allstop(0xE0); time.sleep(0.05)
    a0, d0 = after_child()
    rc, out = child("k.analog(0); k.digital(0); os._exit(0)")
    a1, d1 = after_child(); set_allstop(0xF0)
    trans = None if d0 is None else ((d1["ons"] - d0["ons"]) & 0xFF, (d1["offs"] - d0["offs"]) & 0xFF)
    return report(name, a1 == a0 and trans in (None, (0, 0)), f"61 0x{a0:02x} -> 0x{a1:02x}, (ons, offs) +{trans}, rc={rc}")

def l3(reps=100):
    """shut_down_in() racing a student loop that keeps calling enable_servos():
    after every run ALLSTOP bits 4-7 are all set. Falsifies the race in
    servo_p.cpp:34 (the lock guard there ends with its if statement)."""
    name = "L3 shut_down_in vs enable loop"
    if not (need_enable(name) and ensure_synced(name)): return False
    centre_all(); bad = []
    for i in range(reps):
        child("k.shut_down_in(ctypes.c_double(0.3))\nwhile True: k.enable_servos()", timeout=5)
        a, d = after_child()
        if a & SRV_BITS != SRV_BITS: bad.append(f"#{i} 0x{a:02x}")
        set_allstop(0xF0)
    return report(name, not bad, f"{len(bad)}/{reps} runs left a servo enabled: {bad[:10]}")

def l4():
    """Positions persist across programs (context for the stale-snap finding):
    the host writes servo 0 = 2100 us raw; a new libkipr program reads
    get_servo_position(0) about 1706 (not 1024)."""
    name = "L4 stale position across programs"
    if not ensure_synced(name): return False
    r = read(); old = r[SERVO0] << 8 | r[SERVO0 + 1]
    xfer(w16(SERVO0, 2100))
    rc, out = child("print(k.get_servo_position(0), flush=True); os._exit(0)")
    xfer(w16(SERVO0, old))
    try: v = int(out.split()[-1])
    except Exception: v = None
    return report(name, v is not None and abs(v - 1706) <= 2, f"get_servo_position(0) = {v} (1706 = stale value, 1024 = reset)")


TESTS = dict(s1=s1, s2=s2, s3=s3, s4=s4, s5=s5, s6=s6, s7=s7, s8=s8, s9=s9, s10=s10, s11=s11, s12=s12, l1=l1, l2=l2, l3=l3, l4=l4)
if __name__ == "__main__":
    names = sys.argv[1:]
    if "--reset" in names: allow_reset = True; names.remove("--reset")
    if "--enable" in names: allow_enable = True; names.remove("--enable")
    if not names or names == ["all"]: names = list(TESTS)
    print(f"pr14_hw {time.strftime('%FT%TZ', time.gmtime())} tests: {' '.join(names)} reset={allow_reset} enable={allow_enable}")
    time.sleep(0.2); desyncs(100)
    r = read(); VER = r[1:3]
    HAVE_DIAG = state() is not None
    print(f"start={r[0]} version=0x{r[1]:02x}{r[2]:02x} ALLSTOP=0x{r[ALLSTOP]:02x} diag={'yes ' + str(state()) if HAVE_DIAG else 'no'}")
    try:
        results = [TESTS[n]() for n in names]
    finally:
        if allow_enable:
            try: set_allstop(0xF0)                     # leave every servo disabled
            except Exception: pass
    sys.exit(0 if all(results) else 1)
