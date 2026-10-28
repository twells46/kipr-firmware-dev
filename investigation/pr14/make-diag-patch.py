"""Write pr14-diag.patch: PE10 diagnostics on top of master + pr14-on-master.patch.

    python3 -I make-diag-patch.py   (from investigation/pr14)

The image publishes, once per main-loop pass from update_servo_power(), in the
magnetometer slots (so magneto_*() is meaningless on it):
  24 marker 0xE4
  25 status: b0 IDR10 (pin level at the start of the pass, before this pass
             writes the pin), b1 ODR10, b2-3 MODER10, b4 OTYPER10,
             b5 all_disabled, b7 pass parity
  26 off transitions (ODR10 1->0, after boot's init), mod 256
  27 on transitions (ODR10 0->1), mod 256
  28-29 µs from all-disabled to the last power cut (usCount), saturated at 65535
v2 (2026-10-27): readIMU() no longer writes the magnetometer slots (v1 let
real mag data through between readIMU() and update_servo_power(), and mag X
high byte can be 0xE4), and IDR is sampled before the pin is written (v1
could catch EN still rising in the pass that released it).
"""
import pathlib, subprocess, shutil, sys, tempfile
here = pathlib.Path(__file__).resolve().parent
repo = here.parent.parent / "Wombat-Firmware"
tmp = pathlib.Path(tempfile.mkdtemp())
for d in ("a", "b"):
    (tmp / d).mkdir()
    subprocess.run(f"git -C {repo} archive origin/master | tar -x -C {tmp/d}", shell=True, check=True)
    subprocess.run(["patch", "-s", "-d", str(tmp / d), "-p1", "--no-backup-if-mismatch", "-i", str(here / "pr14-on-master.patch")], check=True)

def edit(rel, subs):
    p = tmp / "b" / rel
    raw = p.read_bytes()
    crlf = b"\r\n" in raw
    t = raw.decode().replace("\r\n", "\n")
    for old, new in subs:
        assert t.count(old) == 1, (rel, old, t.count(old))
        t = t.replace(old, new)
    if crlf: t = t.replace("\n", "\r\n")
    p.write_bytes(t.encode())

edit("Firmware/src/wallaby_servo.c", [
("""    static uint32_t all_disabled_since;
""", """    static uint32_t all_disabled_since;
    /* PR 14 diagnostics (investigation only), see investigation/pr14/pr14.md */
    static uint8_t d14_offs, d14_ons, d14_pass;
    static uint16_t d14_delay;
    uint8_t d14_odr_before = (SRV_DISABLE_PORT->ODR & SRV_DISABLE) ? 1 : 0;
    uint8_t d14_idr = (SRV_DISABLE_PORT->IDR & SRV_DISABLE) ? 1 : 0;
"""),
("""            SRV_DISABLE_PORT->BSRRH |= SRV_DISABLE; // power off
        }
""", """            SRV_DISABLE_PORT->BSRRH |= SRV_DISABLE; // power off
            if (d14_odr_before)
            {
                uint32_t d = usCount - all_disabled_since;
                d14_delay = d > 0xFFFF ? 0xFFFF : d;
                d14_offs++;
            }
        }
"""),
("""        SRV_DISABLE_PORT->BSRRL |= SRV_DISABLE; // released, power on
    }
""", """        SRV_DISABLE_PORT->BSRRL |= SRV_DISABLE; // released, power on
        if (!d14_odr_before) d14_ons++;
    }

    d14_pass ^= 0x80;
    uint8_t st = d14_idr
               | ((SRV_DISABLE_PORT->ODR & SRV_DISABLE) ? 0x02 : 0)
               | (((SRV_DISABLE_PORT->MODER >> 20) & 0x3) << 2)
               | ((SRV_DISABLE_PORT->OTYPER & SRV_DISABLE) ? 0x10 : 0)
               | (all_disabled ? 0x20 : 0)
               | d14_pass;
    aTxBuffer[REG_RW_MAG_X_H] = 0xE4;
    aTxBuffer[REG_RW_MAG_X_L] = st;
    aTxBuffer[REG_RW_MAG_Y_H] = d14_offs;
    aTxBuffer[REG_RW_MAG_Y_L] = d14_ons;
    aTxBuffer[REG_RW_MAG_Z_H] = d14_delay >> 8;
    aTxBuffer[REG_RW_MAG_Z_L] = d14_delay & 0xFF;
"""),
])
edit("Firmware/src/wallaby_imu.c", [
("""            aTxBuffer[REG_RW_MAG_X_H + 2 * i] = (uint16_t)adj >> 8;
            aTxBuffer[REG_RW_MAG_X_L + 2 * i] = (uint16_t)adj & 0xFF;
""", """            (void)adj; /* PR 14 diag: the magnetometer slots carry PE10 diagnostics */
"""),
])
out = here / "pr14-diag.patch"
r = subprocess.run(["diff", "-ruN", "a", "b"], cwd=tmp, capture_output=True)
assert r.returncode == 1, r
out.write_bytes(r.stdout)
shutil.rmtree(tmp)
print(out)
