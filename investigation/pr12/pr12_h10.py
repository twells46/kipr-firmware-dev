#!/usr/bin/env python3
"""H10: libkipr smoke test of every peripheral path (run ON the Wombat, botui stopped).

    sudo python3 -u pr12_h10.py <libkipr.so> <phase> [args]

    passive               nothing moves: battery, analog, digital, buttons,
                          motor/servo state, 5 s link check
    motor <port>...       MOVES the listed motors: motor, off, mav, mrp/mtp +
                          done bit, freeze, ao. Then injects 3 rejected frames
                          and checks the done bits and counter survive them.
    servo <port>...       MOVES the listed servos: enable, 3 positions, disable
    digout <port>...      makes the listed (EMPTY) digital ports outputs,
                          toggles them, checks the OUT/OE registers, restores
    jumper <out> <in>     with a wire from digital <out> to <in>: drives one
                          and reads the level on the other
    watch [seconds=20]    nothing moves: polls buttons, digital 0-9 and analog
                          0-5 while a person presses/changes them

Prints one PASS/FAIL line per check, each with its falsifier's evidence. Every
phase also fails if the reject counter (REG_RW_MOT_DONE bits 7:4, read raw
over spidev) moves when no bad frame was injected. Expected results are in
investigation/pr12/pr12.md.
"""
import ctypes, sys, time, spidev

lib = ctypes.CDLL(sys.argv[1])
lib.power_level.restype = ctypes.c_float
phase, args = sys.argv[2], sys.argv[3:]
s = spidev.SpiDev(); s.open(0, 0); s.max_speed_hz = 16000000
MOT_DONE, SERVO0, DIG_OUT, DIG_OE = 60, 78, 5, 9
ok_all = True

def raw(count=0, pairs=()):
    b = [0] * 89
    b[0], b[1], b[3], b[88] = ord('J'), 4, count, ord('S')
    for i, (a, v) in enumerate(pairs): b[4 + 2 * i], b[5 + 2 * i] = a, v
    rx = s.xfer2(b); time.sleep(50e-6)
    return rx

def reg60():
    raw(); return raw()[MOT_DONE]

def report(name, ok, detail):
    global ok_all
    ok_all &= bool(ok)
    print(f"{name}: {'PASS' if ok else 'FAIL'}  {detail}", flush=True)

def counter_check(name, before, injected=0):
    d = ((reg60() >> 4) - before) & 15
    report(f"{name} reject counter", d == injected, f"moved {d}, injected {injected}")

def wait_done(port, want, timeout):
    t = time.time()
    while time.time() - t < timeout:
        if lib.get_motor_done(port) == want: return time.time() - t
        time.sleep(0.01)
    return None

def passive():
    c0 = reg60() >> 4
    desync = sum(raw()[0] != ord('J') for _ in range(200))
    report("link", desync == 0, f"{desync}/200 raw frames without 'J'")
    v = [lib.power_level() for _ in range(10)]
    report("battery", all(0.0 <= x <= 1.5 for x in v) and max(v) - min(v) < 0.2,
           f"power_level min={min(v):.3f} max={max(v):.3f} charging={lib.battery_charging()}")
    an = {p: [lib.analog(p) for _ in range(20)] for p in range(6)}
    report("analog 0-5", all(0 <= x <= 4095 for r in an.values() for x in r),
           " ".join(f"a{p}={min(r)}..{max(r)}" for p, r in an.items()))
    dg = [lib.digital(p) for p in range(10)]
    report("digital 0-9", all(x in (0, 1) for x in dg), f"{dg}")
    bt = dict(side=lib.side_button(), left=lib.left_button(), right=lib.right_button())
    report("buttons", all(x in (0, 1) for x in bt.values()), f"{bt} (0 unless held)")
    en = [lib.get_servo_enabled(p) for p in range(4)]
    report("servos idle", en == [0] * 4,
           f"enabled={en} positions={[lib.get_servo_position(p) for p in range(4)]}")
    p0 = [lib.gmpc(p) for p in range(4)]; time.sleep(1)
    p1 = [lib.gmpc(p) for p in range(4)]
    report("motors idle", all(abs(a - b) <= 2 for a, b in zip(p0, p1)),
           f"gmpc {p0} -> {p1} over 1 s, done={[lib.get_motor_done(p) for p in range(4)]}")
    t = time.time(); n = 0
    while time.time() - t < 5:
        lib.analog(n % 6); lib.digital(n % 10); lib.gmpc(n % 4); n += 1
    report("5 s read loop", True, f"{n} rounds of analog/digital/gmpc")
    counter_check("passive", c0)

def motor(port):
    c0 = reg60() >> 4
    lib.cmpc(port); time.sleep(0.05)
    report(f"m{port} cmpc", abs(lib.gmpc(port)) <= 5, f"gmpc={lib.gmpc(port)}")
    lib.motor(port, 50); time.sleep(1.5); fwd = lib.gmpc(port)
    lib.off(port); time.sleep(0.7); a = lib.gmpc(port); time.sleep(0.5); b = lib.gmpc(port)
    report(f"m{port} motor(50)", abs(fwd) > 100, f"{fwd} ticks in 1.5 s")
    report(f"m{port} off", abs(b - a) <= 5, f"drift {b - a} ticks in 0.5 s after off")
    lib.motor(port, -50); time.sleep(1.5); lib.off(port); rev = lib.gmpc(port) - b
    report(f"m{port} motor(-50)", abs(rev) > 100 and (rev > 0) != (fwd > 0), f"{rev} ticks in 1.5 s")
    time.sleep(0.7)
    a = lib.gmpc(port); lib.mav(port, 500); time.sleep(2.0); d = lib.gmpc(port) - a
    lib.off(port); time.sleep(0.7)
    report(f"m{port} mav(500)", 600 <= d <= 1400, f"{d} ticks in 2 s (expect about 1000)")
    start = lib.gmpc(port)
    lib.mrp(port, 500, 1000)
    early = lib.get_motor_done(port)
    took = wait_done(port, 1, 8); time.sleep(0.5); end = lib.gmpc(port)
    report(f"m{port} mrp(500,1000)", early == 0 and took is not None and 1000 <= end - start <= 1300,
           f"done at start={early}, done after {took and round(took, 2)} s, moved {end - start}")
    # The fix republishes the done bits beside the reject counter on every
    # packet: rejected frames must bump the counter and leave the done bit set.
    hi = reg60() >> 4
    for _ in range(3): raw(3, [(SERVO0, 0x05)])
    r = reg60(); kept = lib.get_motor_done(port)
    report(f"m{port} done bit survives rejects", kept == 1 and ((r >> 4) - hi) & 15 == 3,
           f"get_motor_done={kept} reg60=0x{r:02x} counter moved {((r >> 4) - hi) & 15} (fix: 3, older firmware: 0)")
    raw(2, [(SERVO0, 0x05), (SERVO0 + 1, 0xDC)])
    lib.mtp(port, 500, start)
    early = lib.get_motor_done(port)
    took = wait_done(port, 1, 8); time.sleep(0.5); back = lib.gmpc(port)
    report(f"m{port} mtp back", early == 0 and took is not None and -300 <= back - start <= 0,
           f"done at start={early}, done after {took and round(took, 2)} s, ended {back - start} from start")
    lib.motor(port, 30); time.sleep(0.5); lib.freeze(port); time.sleep(0.7)
    a = lib.gmpc(port); time.sleep(0.5); b = lib.gmpc(port)
    report(f"m{port} freeze", abs(b - a) <= 5, f"drift {b - a} ticks in 0.5 s")
    lib.ao(); time.sleep(0.3)
    counter_check(f"m{port}", c0, injected=3)

def servo(ports):
    c0 = reg60() >> 4
    for p in ports: lib.set_servo_position(p, 1024)
    lib.enable_servos(); time.sleep(1.0)
    report("servos enabled", all(lib.get_servo_enabled(p) == 1 for p in ports),
           f"{[lib.get_servo_enabled(p) for p in range(4)]}")
    for pos in (600, 1500, 1024):
        for p in ports: lib.set_servo_position(p, pos)
        time.sleep(1.0)
        got = [lib.get_servo_position(p) for p in ports]
        report(f"servo -> {pos}", got == [pos] * len(ports), f"ports {ports} read back {got} (watch them move)")
    lib.disable_servos(); time.sleep(0.2)
    report("servos disabled", all(lib.get_servo_enabled(p) == 0 for p in range(4)),
           f"{[lib.get_servo_enabled(p) for p in range(4)]}")
    counter_check("servo", c0)

def digout(ports):
    c0 = reg60() >> 4
    # The firmware stops updating a pin's DIG_IN bit while it is an output
    # (wallaby_dig.c update_dig_pin), and libkipr's pullup calls are stubs, so
    # digital() can't loop the value back. What can be checked from here is
    # that the OUT and OE registers follow the calls and that the port reads
    # as an idle input again afterwards. The pin level itself needs a jumper
    # to another port: see the "jumper" phase.
    def regs16(addr):
        raw(); r = raw(); return r[addr] << 8 | r[addr + 1]
    for p in ports:
        others = regs16(DIG_OE) & ~(1 << p)
        lib.set_digital_output(p, 1); time.sleep(0.05)
        oe = regs16(DIG_OE) >> p & 1; flag = lib.get_digital_output(p)
        seen = []
        for v in (1, 0, 1, 0):
            lib.set_digital_value(p, v); time.sleep(0.05); seen.append(regs16(DIG_OUT) >> p & 1)
        lib.set_digital_output(p, 0); time.sleep(0.05)
        oe2 = regs16(DIG_OE); idle = lib.digital(p)
        report(f"d{p} output registers",
               oe == 1 and flag == 1 and seen == [1, 0, 1, 0] and oe2 == others and idle == 0,
               f"OE bit {oe}, get_digital_output {flag}, OUT bit followed {seen}, "
               f"OE after 0x{oe2:04x}, digital() back as input = {idle}")
    counter_check("digout", c0)

def jumper(out, inp):
    """Port `out` is wired to port `inp`: the driven level must show up on the input."""
    c0 = reg60() >> 4
    lib.set_digital_output(inp, 0); lib.set_digital_output(out, 1); time.sleep(0.05)
    seen = []
    for v in (1, 0, 1, 0, 1, 0):
        lib.set_digital_value(out, v); time.sleep(0.05); seen.append(lib.digital(inp))
    lib.set_digital_value(out, 0); lib.set_digital_output(out, 0); time.sleep(0.05)
    # DIG_IN is inverted (bit set when the pin is low), so a driven 1 reads 0.
    report(f"d{out} -> d{inp} jumper", seen in ([1, 0] * 3, [0, 1] * 3),
           f"drove [1,0,1,0,1,0] on d{out}, digital({inp}) read {seen}")
    counter_check("jumper", c0)

def watch(secs):
    c0 = reg60() >> 4
    names = ["side", "left", "right"] + [f"d{p}" for p in range(10)]
    read = lambda: [lib.side_button(), lib.left_button(), lib.right_button()] + [lib.digital(p) for p in range(10)]
    last = read(); edges = {n: 0 for n in names}
    lo = [4095] * 6; hi = [0] * 6
    print(f"watching for {secs:.0f} s: press buttons, trip digital sensors, change analog sensors", flush=True)
    t = time.time()
    while time.time() - t < secs:
        cur = read()
        for n, a, b in zip(names, last, cur):
            if a != b:
                edges[n] += 1
                print(f"  {time.time() - t:5.1f}s {n} {a}->{b}", flush=True)
        last = cur
        for p in range(6):
            v = lib.analog(p); lo[p] = min(lo[p], v); hi[p] = max(hi[p], v)
    report("watch edges", True, " ".join(f"{n}={e}" for n, e in edges.items() if e) or "none seen")
    report("watch analog", True, " ".join(f"a{p}={lo[p]}..{hi[p]}" for p in range(6)))
    counter_check("watch", c0)

print(f"pr12_h10 {phase} {args} {time.strftime('%FT%TZ', time.gmtime())} lib={sys.argv[1]}", flush=True)
lib.analog(0); time.sleep(1)
for _ in range(100): raw()   # warm-up: the first frames after an STM32 reset can slip
try:
    if phase == "passive": passive()
    elif phase == "motor": [motor(int(p)) for p in args]
    elif phase == "servo": servo([int(p) for p in args])
    elif phase == "digout": digout([int(p) for p in args])
    elif phase == "jumper": jumper(int(args[0]), int(args[1]))
    elif phase == "watch": watch(float(args[0]) if args else 20)
    else: sys.exit(f"unknown phase {phase}")
finally:
    lib.ao(); lib.disable_servos()
print(f"H10 {phase}: {'PASS' if ok_all else 'FAIL'}", flush=True)
sys.exit(0 if ok_all else 1)
