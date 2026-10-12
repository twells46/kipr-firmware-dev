I tested this on a Wombat. The recovery works for most slips and a healthy link is unaffected, but on hardware I found that a reset can occasionally leave the link stuck in a state the firmware doesn't leave by itself. I'm working on tracking that down and will follow up here.

## Setup

Master now has #8 and #12, so I tested `78637f2` merged onto master `2776fb2` (no conflicts) against master itself. I did not flash the branch head as it stands. The traffic was raw `spidev` frames shaped like libwallaby's: 89 bytes at 16 MHz with 50 µs between transfers, botui stopped. A third image added counters for each resync cause and a cycle-counter timing of the interrupts-off window.

## What works

| Test | master | this PR |
|---|---|---|
| 20,000-frame soak; 100 Hz for 30 s; 0.5/1/4 MHz clocks | 0 desync | 0 desync, no resync attempted |
| Wrong-length transfer (1, 10, 50, 87, 90, 200, 4096 bytes, 20 each), continuous traffic | never recovers | 2–3.5 transfers lost on average, 10 at worst |
| The same, with a 10 ms pause after the slip | never recovers | 0 lost |
| A write just before the slip | — | applied exactly once, 30 of 30 |
| 89-byte frame with version 3 | ignored | ignored, no reset |
| Slip every 50 frames for 15 s | — | interrupts off 5.5 µs at most, no pass over 700 µs, loop rate 1077/s against 1086/s quiet |
| #12's frame tests | pass | pass |

Those numbers are better than the description's simulation (3.0 / 7 / 20).

## What doesn't

**1. A transfer one byte short of a frame is never recovered.** After an 88- or 177-byte transfer the link stays desynchronized, 6 of 6 times; n = 88 is in your test list. The main loop is also starved: of 40 replies read 20 ms apart only 5–9 are distinct, against 40 on a healthy link, so sensors, back-EMF and PID are barely running. Master starves the same way after such a transfer, so that part isn't new.

My current reading, not yet proven: the TX stream runs one byte ahead of RX, so after 89k + 88 bytes TX has completed a frame and RX hasn't. `handle_dma()` only clears the transfer-complete flags when both are set, so `DMA1_Stream4_IRQHandler` re-enters until the next transfer's first byte arrives. The main loop then only runs while chip select is low, and `spi2_dma_check_sync()` needs it high.

**2. About 0.3% of resets leave the link stuck.** This is the one that's new with this PR. Sending one disturbance at a time under continuous traffic and checking the link after each (a write and a read-back), on the image with counters:

| Disturbance | master | this PR |
|---|---|---|
| 3,000 frames with no `'J'` | 0 stuck | 10 stuck, in each of two runs |
| 3,000 wrong-length transfers (1–87 bytes) | — | 7 and 9 stuck |

- Every stuck link had the starved main loop from point 1, and only an STM32 reset (or, once, a 1-byte transfer) brought it back.
- 31 of the 36 were plainly desynchronized.
- 5 were silent: every reply started with `'J'` and carried the right version, so libwallaby would log nothing, but every write was dropped and sensor values barely updated.
- On master a frame without `'J'` is simply ignored, so a single corrupted start or end byte goes from one dropped write to, occasionally, a dead link.
- The rate varies. On the image without counters one 3,000-frame run had none, but that image did end up stuck part-way through a 120-frame test of unframed frames.

The plainly desynchronized case looks like a reset racing the start of the next host transfer and landing in the state from point 1. I don't have a mechanism for the silent case yet.

## Smaller notes

- **libwallaby uses bad replies.** `r8`/`r16`/`r32` return the reply even when byte 0 isn't `'J'`, and the read-modify-write callers (`set_motor_mode`, `set_servo_enabled`, digital OUT/OE) write it back. Emulating that with raw frames on a servo position register, with a slip every 40 rounds, the register was corrupted about 150 times in 640 slips. On master the write-back can't land because the link never recovers. That's a libwallaby fix, not a firmware one.
- **Split frames.** One frame sent as two transfers with chip select released in between trips the count check about 1 time in 200. Nothing in libwallaby, botui or wombat-os does that.
- **`wallaby_reset_coproc` hangs** on the current image: with libgpiod 2.2.1, `gpioset` without `-t` holds the line until killed. Step 2 of the test plan can't be run as written. I used `gpioset -c 0 -t 100ms,100ms,0 23=1`, which is what `wallaby_flash` does.

Not tested: motors and servos through libkipr on this build, and real glitches on SCK or chip select.
