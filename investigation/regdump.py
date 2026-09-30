#!/usr/bin/env python3
"""Read the MPU9250 register dump published by the E1 regdump firmware.

Runs on the Wombat. Reads raw SPI2 frames from /dev/spidev0.0 (the same
protocol libwallaby uses, no register writes) and decodes the magnetometer
slots, which the regdump firmware repurposes:

    24 marker 0xA5, 25 seq, 26 kind (0 entry, 1 live), 27 addr, 28 value,
    29 checksum = 0x5A + 7*seq + 13*kind + 31*addr + 3*value (mod 256)

"entry" is the register as the previously running firmware left it (read
before this firmware touched anything). "live" is read periodically now.
Frames that fail the checksum (torn DMA reads) are dropped; each register's
value is the majority of its valid observations, and disagreements are
reported, not hidden.
"""
import argparse
import collections
import ctypes
import json
import os
import sys
import time

FRAME_SIZE = 89
NAMES = {
    0x75: "WHO_AM_I", 0x6B: "PWR_MGMT_1", 0x6C: "PWR_MGMT_2", 0x19: "SMPLRT_DIV",
    0x1A: "CONFIG", 0x1B: "GYRO_CONFIG", 0x1C: "ACCEL_CONFIG", 0x1D: "ACCEL_CONFIG2",
    0x1E: "LP_ACCEL_ODR", 0x6A: "USER_CTRL", 0x23: "FIFO_EN", 0x24: "I2C_MST_CTRL",
    0x25: "I2C_SLV0_ADDR", 0x26: "I2C_SLV0_REG", 0x27: "I2C_SLV0_CTRL",
    0x37: "INT_PIN_CFG", 0x38: "INT_ENABLE", 0x13: "XG_OFFSET_H", 0x14: "XG_OFFSET_L",
    0x15: "YG_OFFSET_H", 0x16: "YG_OFFSET_L", 0x17: "ZG_OFFSET_H", 0x18: "ZG_OFFSET_L",
    0x00: "SELF_TEST_X_GYRO", 0x01: "SELF_TEST_Y_GYRO", 0x02: "SELF_TEST_Z_GYRO",
    0x77: "XA_OFFSET_H", 0x78: "XA_OFFSET_L", 0x7A: "YA_OFFSET_H", 0x7B: "YA_OFFSET_L",
    0x7D: "ZA_OFFSET_H", 0x7E: "ZA_OFFSET_L",
}


def decode(addr, v):
    if addr == 0x1B:
        return "self-test xyz={}{}{} FS=±{} dps FCHOICE_B={:02b}".format(
            v >> 7 & 1, v >> 6 & 1, v >> 5 & 1, (250, 500, 1000, 2000)[v >> 3 & 3], v & 3)
    if addr == 0x1C:
        return "self-test xyz={}{}{} FS=±{}g".format(
            v >> 7 & 1, v >> 6 & 1, v >> 5 & 1, (2, 4, 8, 16)[v >> 3 & 3])
    if addr == 0x1D:
        return "ACCEL_FCHOICE_B={} A_DLPFCFG={}".format(v >> 3 & 1, v & 7)
    if addr == 0x1A:
        return "FIFO_MODE={} EXT_SYNC={} DLPF_CFG={}".format(v >> 6 & 1, v >> 3 & 7, v & 7)
    if addr == 0x6B:
        return "H_RESET={} SLEEP={} CYCLE={} GYRO_STBY={} PD_PTAT={} CLKSEL={}".format(
            v >> 7 & 1, v >> 6 & 1, v >> 5 & 1, v >> 4 & 1, v >> 3 & 1, v & 7)
    if addr == 0x19:
        return "sample rate = internal/{}".format(v + 1)
    return ""


class SpiTransfer(ctypes.Structure):
    _fields_ = [("tx_buf", ctypes.c_uint64), ("rx_buf", ctypes.c_uint64),
                ("len", ctypes.c_uint32), ("speed_hz", ctypes.c_uint32),
                ("delay_usecs", ctypes.c_uint16), ("bits_per_word", ctypes.c_uint8),
                ("cs_change", ctypes.c_uint8), ("tx_nbits", ctypes.c_uint8),
                ("rx_nbits", ctypes.c_uint8), ("word_delay_usecs", ctypes.c_uint8),
                ("pad", ctypes.c_uint8)]


class Spi:
    def __init__(self, path, speed):
        self.fd = os.open(path, os.O_RDWR)
        self.speed = speed
        self.count = 0
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.libc.ioctl.argtypes = (ctypes.c_int, ctypes.c_ulong, ctypes.c_void_p)
        self.libc.ioctl.restype = ctypes.c_int

    def transfer(self):
        tx = (ctypes.c_uint8 * FRAME_SIZE)()
        rx = (ctypes.c_uint8 * FRAME_SIZE)()
        self.count = (self.count + 1) & 255
        tx[0], tx[1], tx[2], tx[3], tx[88] = ord("J"), 4, self.count, 0, ord("S")
        xfer = SpiTransfer(tx_buf=ctypes.addressof(tx), rx_buf=ctypes.addressof(rx),
                           len=FRAME_SIZE, speed_hz=self.speed, bits_per_word=8)
        status = self.libc.ioctl(self.fd, 0x40206B00, ctypes.byref(xfer))
        time.sleep(0.00005)
        if status != FRAME_SIZE:
            raise OSError(ctypes.get_errno(), "SPI transfer failed")
        return bytes(rx)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-obs", type=int, default=5, help="valid observations per register and kind")
    ap.add_argument("--timeout", type=float, default=30)
    ap.add_argument("--device", default="/dev/spidev0.0")
    ap.add_argument("--speed", type=int, default=16000000)
    ap.add_argument("--out", help="write JSON here")
    args = ap.parse_args()

    spi = Spi(args.device, args.speed)
    obs = collections.defaultdict(collections.Counter)  # (kind, addr) -> Counter(value)
    frames = bad_marker = bad_sum = bad_start = 0
    last_seq = None
    start = time.time()
    while time.time() - start < args.timeout:
        f = spi.transfer()
        frames += 1
        if f[0] != ord("J"):
            bad_start += 1
            continue
        marker, seq, kind, addr, val, chk = f[24:30]
        if marker != 0xA5:
            bad_marker += 1
            continue
        if chk != (0x5A + 7 * seq + 13 * kind + 31 * addr + 3 * val) & 0xFF or kind > 1:
            bad_sum += 1
            continue
        if seq == last_seq:
            continue
        last_seq = seq
        obs[(kind, addr)][val] += 1
        seen = [k for k in obs if sum(obs[k].values()) >= args.min_obs]
        if len(seen) >= 2 * len(NAMES) and len({a for _, a in obs}) >= len(NAMES):
            break
        time.sleep(0.002)

    elapsed = time.time() - start
    print("frames {} in {:.1f}s; bad start {}, wrong marker {}, bad checksum {}".format(
        frames, elapsed, bad_start, bad_marker, bad_sum))
    if bad_marker and not obs:
        print("marker 0xA5 never seen: is the regdump firmware flashed?")
        return 1
    result = {"frames": frames, "bad_checksum": bad_sum, "bad_marker": bad_marker, "registers": {}}
    print("{:<17} {:>4}  {:>5} {:>5}  {:>8}  {}".format("register", "addr", "entry", "live", "consist", "decoded (entry; live if different)"))
    for addr in sorted(NAMES):
        row = {}
        cells = []
        for kind, label in ((0, "entry"), (1, "live")):
            c = obs.get((kind, addr), collections.Counter())
            if c:
                v, n = c.most_common(1)[0]
                row[label] = v
                row[label + "_obs"] = dict((str(k), m) for k, m in c.items())
                cells.append("0x{:02X}".format(v))
            else:
                row[label] = None
                cells.append("  -- ")
        consist = []
        for kind in (0, 1):
            c = obs.get((kind, addr), collections.Counter())
            consist.append("{}/{}".format(c.most_common(1)[0][1] if c else 0, sum(c.values())))
        e, l = row["entry"], row["live"]
        dec = decode(addr, e) if e is not None else ""
        if l is not None and l != e:
            dec += "  || live: " + decode(addr, l)
        print("{:<17} 0x{:02X}  {} {}  {:>8}  {}".format(NAMES[addr], addr, cells[0], cells[1], " ".join(consist), dec))
        result["registers"][NAMES[addr]] = row
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(result, fh, indent=1, sort_keys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
