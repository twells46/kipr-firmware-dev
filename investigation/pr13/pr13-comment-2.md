Follow-up to my earlier comment: both failures have the same root and one small change fixes them. I pushed it to this branch as `4a731ea`.

## Cause

- **Point 1 (one byte short).** Confirmed as described. The TX stream completes a frame about two bytes before RX does. `handle_dma()` cleared the transfer-complete flags only when both were set, so after an 88-byte transfer the TX stream's interrupt re-entered until the host's next transfer. With counters in the handler: about 1.05 million lone-TX entries per idle second, and no main-loop passes.
- **Point 2 (0.3% of resets stuck).** The reset races the start of the next host frame. If SPI2 is enabled inside byte 0 or byte 1 of a frame, TX ends that frame ahead of RX and the link is in the state from point 1. That window is about 1 µs wide at 16 MHz.
- **The silent case is the same race.** Enabled inside byte 0, the slave sometimes starts its reply at once, which leaves TX two bytes ahead of RX: the reply lines up with the host's frames while the firmware sees every frame rotated by one byte. Otherwise the reply is rotated and the link looks dead.

I measured point 2 with an image that holds the reset at a chosen step until chip select falls, waits a set delay, and records both DMA counts afterwards. About 5,700 injected races on this PR without the fix: the link stuck only when the enable landed in bytes 0–1, always in one of three count states, and the 46 stuck links from random traffic on the same image showed the same three.

## The change

`4a731ea` makes `handle_dma()` treat the RX stream's flag alone as the frame boundary and no longer enables the TX stream's interrupt. Frames are processed at the same moment as before, since the RX flag was always the later one (the handler never saw RX set without TX in about 8,000 healthy frames).

## Results with the change

Tested as before: this branch merged onto master `2776fb2`, raw `spidev` frames, botui stopped.

| Test | Before | With `4a731ea` |
|---|---|---|
| 88-, 177-, 266-byte transfer, then 1 s idle | never recovers, main loop starved | first frame after the pause is good, loop rate unchanged through the pause |
| Injected reset races (all reset steps; 0.6, 4 and 16 MHz) | stuck whenever the enable lands in bytes 0–1 | 5,609 of 5,609 healthy on the next frame, one extra reset each |
| Unframed frames and wrong-length transfers, health check after each | 46 stuck in 12,000 | 0 stuck in 78,000 |
| Boot while the host polls | 1 of 5 failed | 35 of 35 pass |
| Motors running, 88-byte transfer, then `ao()` | not run | motors stop, 9 of 9 |
| Healthy soak, slow clocks, #12's frame tests | pass | pass |

The 78,000 includes back-to-back frames and gaps of 50 µs, 200 µs and random 0–1 ms, at 16 and 4 MHz.

## Still open

- **Worst-case recovery is 22 transfers**, seen with back-to-back frames; the description says 20. With a 200 µs gap the worst was 6.
- **One state the count check can't see.** A racing reset can leave RX aligned and TX off by a byte. In every case I produced (69) the reset's own `spi_resync = !spi2_cs_high()` line caught it, because chip select was still low. It would persist only if the host raised chip select within about 0.1 µs of the last clock, which I haven't seen and haven't ruled out at 16 MHz. Also checking the TX count at idle would close it.
- The libwallaby and split-frame notes from my earlier comment are unchanged.
