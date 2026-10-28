I tested this on a Wombat. The firmware change does what it says, and disabled servos now go limp. I found four things worth knowing before merging. Two are libwallaby bugs that change what this PR delivers, and two are behaviour changes worth documenting.

## Setup

Master now has #13, which adds a call at the same spot in `main.c`, so I tested this PR merged onto master `b2ff45e` with `update_servo_power()` placed after `spi2_dma_check_sync()`. That merge is now on this branch as `10314cc`. Its images are byte-identical to the ones I tested, and a re-check on it gave the same results. A second build added diagnostics: the PE10 pin state and counts of rail on/off transitions, published in unused reply bytes. I drove it with raw `spidev` frames shaped like libwallaby's, with botui stopped, and with programs using the deployed libkipr 1.2.4. Servos were on all four ports, and for the battery tests motors were on ports 0, 1 and 3.

## What works

| Test | Result |
|---|---|
| Boot state, 5 resets | PE10 open-drain output, driven low, rail off, every time |
| Rail on after enabling any servo | within 1.1 ms |
| Rail off after disabling all four | 40.0–41.3 ms as measured by the firmware, 50 of 50 |
| Each of the 15 partial patterns, and the motor bits | rail never cut |
| Re-enable 5, 20 or 35 ms into the 40 ms window | rail never cut |
| 20,000 healthy frames, and link slips, with all servos disabled | rail never on |
| STM32 reset while the rail is on | rail off in the first frame after the reset |
| `disable_servos()` with a servo holding a position | servo goes limp (on master it keeps holding) |
| #13's healthy soak, slow clocks and boot while polling, on the merge | pass |

## What to know

**1. With libkipr 1.2.4, servos don't go limp when a program ends.** Return, `exit(1)`, SIGINT, SIGTERM and `shut_down_in()` all leave register 61 at 0x00, so the servos stay enabled and the rail stays on. Master behaves the same, so this predates the PR, but it means the "servos go limp when a program ends" part needs a libwallaby fix too.

In gdb, `register_servo_cleanup()` (`module/servo/src/init.cpp`, `constructor(2)`) does call `cleanup_add()`. At exit, though, `cleanup()` prints "Cleaning up 1" and calls only `ao()`, so the servo entry is lost. The likely cause is initialisation order. `cleanup_functions` is a namespace-scope `std::vector` in `module/core/src/cleanup.cpp`, constructed at default priority, so its constructor runs after the `constructor(2)` push and wipes it. A function-local static vector, or dropping the priority, should fix it.

**2. A misread over the SPI link can now cut the servo rail mid-run.** `set_servo_enabled()` is a read-modify-write of register 61 (`servo_p.cpp:21–35`), and `r8` returns the reply byte even when the transfer failed. If a read lands one byte off, it returns register 60 instead. Its high nibble is the count of rejected packets, which reads 0xF_ at 15, and that's all four disable bits set.

To test this, I enabled servos 1–3 and had a loop call `disable_servo(0)` the way libwallaby does, with a wrong-length transfer every 40 rounds. In 20 s there were 667 slips, 280 write-backs had all four disable bits set, and the rail was cut 5 times, dropping every arm. On master the same write-backs only stop the pulses, and the digital servos keep holding.

It needs a link slip; there were none in 20,000 healthy frames. The fix belongs in libwallaby: check the result of `transfer()` in `r8`/`r16`/`r32`, and don't write back a failed read. It's the same root as the write-back I noted on #13.

**3. A re-enabled servo snaps at full speed to its last commanded position.** Positions stay in the STM32 until it's reset, and enabling a servo writes only register 61. Before, a held digital servo was already at that position. Now it has gone limp and may have been moved by hand or by gravity. I confirmed it with a servo at 2300 µs: disabled it, moved the horn by hand, re-enabled it, and it snapped back at normal servo speed.

The same happens across programs. The next program's `enable_servo()` drives the servo to wherever the previous program left it, and `get_servo_position()` returns that stale value. Calling `set_servo_position()` before enabling avoids it. This is worth a line in the docs.

**4. The moment of highest undervoltage risk moves later.** I ran three motors at raw PWM up to 400, all four servos swinging the full 700↔2300 µs, and CPU load on the Pi, and polled `vcgencmd get_throttled` for the undervoltage flag. The flag trips when the servos' start-up current lands at the same moment as a motor reversal.

On master the servos are already powered, so the risky window is a reversal within about 50 ms of `enable_servos()`. With this PR the servos start drawing only about 100–200 ms after the enable (U72's soft-start, then the servos' own boot), and the window moves there. One older pack, at the threshold, master and this PR back to back:

| Motor reversal after `enable_servos()` | master | this PR |
|---|---|---|
| 0 or 50 ms | 22/24 | 0/24 |
| 100–300 ms | 1/48 | 10/48 |
| 200 ms only | 0/12 | 6/12 |
| All six delays together | 23/72 | 10/72 |
| Control: servos already enabled, new position + reversal | 12/12 | 12/12 |

So the peak risk is the same, and over the delays I tried this PR tripped less often. A program that starts or reverses motors 100–200 ms after enabling the servos can now trip the flag where it didn't before. It only shows on a weak pack: a fresh one never tripped in 840 cycles at full motor power on either build. There were no STM32 resets and no Pi reboots on either build. I'd add one sentence to the description: "Servo start-up current now arrives about 100–200 ms after `enable_servos()`, not straight away."

Not tested: anything that needs a meter or a scope (the rail voltage at idle, the U72 EN voltage), and heavily loaded or stalled servos.
