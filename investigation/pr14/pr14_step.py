#!/usr/bin/env python3
"""Single steps for the at-the-robot tests (H in pr14.md), run ON the Wombat.

    sudo python3 pr14_step.py state
    sudo python3 pr14_step.py pos <port> <us>      write a raw pulse width (600-2400)
    sudo python3 pr14_step.py allstop <hex>        write REG_RW_MOT_SRV_ALLSTOP servo bits (motor bits kept)
    sudo python3 pr14_step.py reset                pulse the STM32 reset line

Imports pr14_hw.py from the same directory. Never commands a motor.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
argv = sys.argv[1:]; sys.argv = sys.argv[:1]
import pr14_hw as h

def show(tag=""):
    r = h.read()
    d = h.state() if h.pe10(r) is not None else None
    print(f"{tag}start={r[0]} ALLSTOP=0x{r[h.ALLSTOP]:02x} pos(us)=" +
          "/".join(str(r[h.SERVO0 + 2 * p] << 8 | r[h.SERVO0 + 2 * p + 1]) for p in range(4)) +
          ("" if d is None else f" power={h.power(d)} idr={d['idr']} ons={d['ons']} offs={d['offs']}"))

h.desyncs(20); h.VER = h.read()[1:3]
cmd = argv[0] if argv else "state"
if cmd == "pos": h.xfer(h.w16(h.SERVO0 + 2 * int(argv[1]), int(argv[2])))
elif cmd == "allstop": h.set_allstop(int(argv[1], 16))
elif cmd == "reset": h.stm_reset(); time.sleep(0.5); h.desyncs(100)
elif cmd != "state": sys.exit(__doc__)
time.sleep(0.1); show(f"{time.strftime('%TZ', time.gmtime())} {' '.join(argv)}: ")
