I tested this on a Wombat and pushed one commit on top, `6896e00`.

## Hardware results for this PR as submitted (`80ad31a`)

Raw `spidev` frames shaped like libwallaby's, compared against master `4814ab8`:

| Test | master | this PR |
|---|---|---|
| Your repro (count 2, no pairs) | 199/200 frames desynced | 0/200 |
| Servo register round-trip (`w8`/`w16`/`w32`) | pass | pass |
| Every single-bit flip of the count byte on a `w16` | desync on 6 of 8 flips | real write applied, no desync |
| Writes to registers 0..2 | start byte overwritten, desync | ignored |
| 20,000-frame soak | 0 desync, 4796 frames/s | 0 desync, 4798 frames/s |

A host-compiled differential test of `handle_dma()` (master vs. this PR, `aRxBuffer`/`aTxBuffer` laid out as in the memory map) found no difference for any legitimate frame: all 65,536 single writes to 3..152, every `w16`/`w32` start address, and 200,000 random frames of 1..42 valid pairs.

## Two things the clamp made worse, fixed in `6896e00`

1. **A corrupt count over a non-zero body applied more writes than master.** With a count of 128..169, master's `stop = 2 * num_regs` wraps in `uint8_t`, so it applies n−128 pairs. Clamping to 42 applies all 42. With random bodies, the clamp changed more registers than master in 96% of such frames (22.8 vs. 11.7 bytes on average). On hardware, a count of 128 over an unpadded body moved servo 0's register to 2000 where master left it at 1500.

   Now a count above 42 is treated as corrupt and the real count is recovered from where the zero padding starts. If there is no padding before `'S'`, the body is as suspect as the count and nothing is applied. Single-bit flips of the count byte on libwallaby frames still apply exactly the real writes.

2. **Corruption became silent.** Master turned an inflated count into a permanent `DMA de-synchronized`, which is bad but visible. With the clamp there was no signal at all, and `debug_printf` is an empty stub.

   Packets with a corrupt count or a skipped write are now counted, mod 16, in bits 7:4 of `REG_RW_MOT_DONE`. Those bits were unused: libkipr and `wallaby_motor.c` both mask the low four. The one behaviour change is that a host write to register 60 can no longer set bits 7:4; nothing in libwallaby writes that register.

   The host side is a small libwallaby change that logs a rate-limited warning when the counter moves. I'll open that separately. Stock libkipr 1.2.4 ignores the nibble and works unchanged against this firmware.

## Hardware results with `6896e00`

- All of the tests above still pass.
- Count 128 over an unpadded body: servo 0 stays at 1500.
- Reject counter: moves by exactly 1 for each of three kinds of rejected frame, 0 drift over 100 clean frames.
- Regression check through libkipr, stock 1.2.4 and patched, motors and servos on ports 0 and 3:
  - `motor`, `off`, `freeze`, `mav`, `mrp`/`mtp` with the done bit, servo enable and positions, digital output registers on ports 0..9, analog, digital and button reads. All pass, and the motors and servos were watched moving.
  - The done bit stays set across three injected rejected frames while the counter moves by 3.
- Not tested: the electrical level on a driven digital output, and buttons or analog sensors being changed by hand.

`scripts/check-register-map.sh` passes and the files keep their CRLF line endings. #13 merges onto this with no conflict and builds; I haven't flashed that combination.
