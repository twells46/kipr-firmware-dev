# Gyro at-rest bias investigation

Source of truth for this investigation. Update it after every experiment, not
at the end. After a context compaction or a new session, re-read this file
first. The tools, Wombat access and rules of engagement are shared with
[investigation.md](investigation.md) (the PR #8 investigation). Its
[Tools](investigation.md#tools) section is still valid.

**Status: theories ranked (2026-09-30). No experiments run yet.** Waiting on
the user's answers to [Needs from the user](#needs-from-the-user).

## Goal

Coaches report that some Wombats are "unusable" because the gyro reads too far
from zero at rest. Different controllers do have different at-rest biases.
Find out why they differ and, if possible, fix it in firmware or libwallaby.
If the cause is hardware, say so and give the best software mitigation.

Units: "counts" are libwallaby user counts (raw/16). At ±250 dps that is
8.19 counts per dps. For heading, 1 count of residual bias drifts
7.3°/min.

## What we know before starting

- **Datasheet (U5, MPU-9250).**
  - Initial zero-rate offset (ZRO) at 25 °C: **±5 dps = ±41 counts**.
  - ZRO over −40 to 85 °C: ±30 dps (worst case about 0.24 dps/°C).
  - Gyro mechanical (drive) frequencies: **25–29 kHz**.
  - Sensitivity tolerance: ±3%.
  - The datasheet gives no figure for sensitivity to linear acceleration or
    for supply rejection.
  - (These numbers are as quoted by two brainstorm agents; they weren't
    re-checked here because pdftoppm isn't installed.)
- **Our one unit (PR8 investigation data).** Raw bias is 2.2 / 6.1 / 9.0
  counts (0.27 / 0.74 / 1.10 dps), 5–22% of the spec. It is the same across
  cold boots, both firmwares (DLPF on and off), and ±250 vs ±2000 dps (the
  same in dps). It moved by no more than 0.4 counts over 36 min after a cold
  boot, idle, with botui stopped:

  | Minutes after cold boot | Gyro x / y / z |
  |---|---|
  | 1.3 | 2.25 / 6.21 / 9.13 |
  | 8.6 | 2.22 / 6.12 / 8.98 |
  | 18.2 | 2.28 / 6.02 / 8.93 |
  | 36.4 | 2.27 / 5.96 / 8.70 |

  Temperature was not recorded (no firmware publishes TEMP_OUT).
- **Shipped libkipr 1.2.4 (`cf56155`) calibration defects,** confirmed in
  PR8 E2/E3:
  - Integer bias (S8): the residual is frac(bias), 0–1 count.
  - A second `gyro_calibrate()` call wipes the calibration (S11).
  - Both are fixed on `twells46/libwallaby` `fix-imu-calibration`
    (`2383007`), not yet released.
- **Board (from `.brd`, BOM).**
  - Location: U5 is 6 mm from the board edge and 15 mm from corner mounting
    hole U34.
  - Supply: VDD and VDDIO are on the shared 3V3 rail (LM3671 buck, 54 mm
    away), with no local ferrite or LDO.
  - VDDIO bypass (C71) is **10 pF C0G**; the datasheet table calls for
    10 nF.
  - The motor supply (VBATT_FUSE) and 5 V planes run under U5.
- **Motor PWM** (TIM1/TIM8): 180 MHz / 18 / 400 = **25.0 kHz**
  (`wallaby_motor.c:224-225`), inside the gyro's drive band.
- **Field practice.** KIPR's 2025 "Driving Using the Gyrometer" slides teach
  either a bias picked by eye ("hovers 3–5, pick 4") or a user-written
  average. A community library notes "conversions vary per wallaby".

## Brainstorm (2026-09-30)

Four parallel agents, one per angle: sensor physics, board hardware,
firmware/library data path, and field usage. They produced about 35
theories, which reduced to 14 after removing duplicates. The main loop agent
ranked them by four criteria:
1. prior probability of being a major contributor;
2. whether it explains *units differing*;
3. whether a fix is possible;
4. cost of testing with our setup.

| # | Theory | Prior | Status |
|---|---|---|---|
| G1 | Silicon ZRO spread (initial tolerance + reflow stress) | high | **top 5** |
| G2 | Shipped-libkipr calibration artifacts decide which units look "unusable" | high | **top 5** |
| G3 | Temperature coefficient / warm-up after calibration | med-high | **top 5** |
| G4 | 25 kHz motor PWM in the 25–29 kHz gyro drive band | med (in use) | **top 5** |
| G5 | Shipped firmware's init race makes the gyro config depend on history | med | **top 5** |
| — | Board flex / screw / cable stress near U5 (6 mm from edge) | med-low | reserve; try it if G1 shows drift across days or reassembly |
| — | Counterfeit / remarked MPU-9250 (EOL part) | med-low | piggybacks on G1 (register reads cost nothing) |
| — | Vibration rectification or aliasing (no DLPF in shipped firmware) | med-low | piggybacks on G4 (separate the motor turning from PWM alone) |
| — | Loop-timing (dt) and scale-factor errors mistaken for bias | med for complaint | not a bias cause; covered by questions to coaches |
| — | Temperature gradient stress (hysteresis vs TEMP_OUT) | low-med | piggybacks on G3 |
| — | 3V3 ripple / 10 pF VDDIO bypass | low | piggybacks on G4 (servo/load toggles) |
| — | Linear-g sensitivity (orientation) | low | 6-face test, only if cheap |
| — | Stale XG_OFFSET registers, SPI2 tearing, /16 deadband | low | already all 0x00 / negligible / removed by calibration |
| — | DLPF, FCHOICE or clock source shift the mean | low | already falsified on one unit (PR8 E2-A vs E2-B) |

## Top five and falsifiers

Each theory below states its falsifier. For each experiment, write the
thresholds down before running it.

### G1. Unit-to-unit bias is silicon ZRO: fixed per unit, within spec, not caused by anything we control

- **Claim:** each unit's at-rest bias is a constant of that chip, set at the
  factory and by reflow. The differences coaches see are this spread. The
  root cause is hardware and can't be fixed in hardware. It can only be
  calibrated out.
- **Falsified if either holds:**
  - (a) On one unit, the bias changes by more than 0.1 dps (0.8 counts)
    across power cycles, days, or firmware with the temperature held
    (then it isn't a per-unit constant);
  - (b) the spread between units at the same temperature is under 0.3 dps
    (then units don't really differ, and the complaint comes from elsewhere,
    G2).
- **Experiment:**
  - Units: 5 or more Wombats, including the ones coaches complained about.
  - Firmware: the same image on every unit.
  - For each unit: 3 cold boots × 2000 samples, on foam, after 20 min
    warm-up, with TEMP_OUT logged. Repeat the next day.
  - Also read: WHO_AM_I, AK8963 WIA, the SELF_TEST_*_GYRO factory codes,
    and the chip markings (photo).
  - Cost: needs units from the user.
- **Fix if it holds:** calibration done properly (G2's fixes), and possibly
  firmware that calibrates at boot and writes −bias to XG/YG/ZG_OFFSET, so
  raw reads, botui and every program start near 0.

### G2. Shipped libkipr's calibration, not the size of the bias, decides which units are "unusable"

- **Claim:** after `gyro_calibrate()` on 1.2.4, what's left depends on luck
  and usage, not on how big the bias is:
  - the residual is frac(bias), so 0–7°/min of drift that differs per unit
    and per axis;
  - a second call puts the full raw bias back.

  So "good" and "bad" controllers are largely arbitrary, and the unit's
  |bias| doesn't predict it. With the fixed library, residual drift is
  the same on every unit and small.
- **Falsified if either holds:**
  - (a) Over N ≥ 20 independent processes on one unit, the stock-library
    residual per axis does *not* match frac(raw mean) within ±0.2 counts;
  - (b) the fixed library's residual is not at least 3x smaller than
    stock's on the worst axis.
  - Also measure how much the residual scatters from one calibration to the
    next (the 50-sample window): if that scatter is itself ≥ 0.5 counts,
    the 0.5 s window is a problem of its own.
- **Experiment:**
  - One unit, cheap. Use `LIBKIPR=` for both libraries; no `/usr/lib`
    change.
  - Each process calibrates once, then records 2 min of 100 Hz samples,
    integrated to heading drift.
  - Add a repeat-call variant.
  - Add a "tap the screen during calibration" variant (stillness).
- **Fix if it holds:** release `fix-imu-calibration`. Consider a longer
  window and a stillness check.

### G3. Bias moves with temperature after calibration, by a different amount on each unit

- **Claim:** ZRO follows die temperature. Pi, STM32 and regulator heat, plus
  changes in room temperature, move the bias after calibration by more than
  0.5 counts in a realistic session.
- **Falsified if:** on one unit, over a TEMP_OUT span of at least 10 °C
  (cold boot → Pi CPU load → hair dryer on the case → cool down), the slope
  on every axis is below 0.01 dps/°C (0.08 counts/°C), so under 0.15 dps
  over 15 °C.
  - Our idle 36-min data (no more than 0.4 counts) is weak evidence
    against G3, because the temperature rise is unknown.
- **Experiment:**
  - One unit.
  - Needs a firmware image that publishes TEMP_OUT, e.g. the 14-byte burst
    read (0x3B–0x48) with temperature in the unused mag slots.
  - Log from cold boot for 60 min.
  - Add a 2nd unit if G1 provides units.
- **Fix if it holds:**
  - Calibrate just before the robot starts moving (docs/slides).
  - A stationary-bias tracker in firmware.
  - A per-unit linear temperature model, stored on the Pi.

### G4. 25 kHz motor PWM couples into the gyro's 25–29 kHz drive band

- **Claim:** energized motor PWM, either electrically (the VBATT plane under
  U5, ground bounce) or acoustically, shifts the gyro's mean. Units whose
  drive frequency is near 25 kHz shift much more than others. The shift is
  invisible to at-rest calibration (motors off), so the robot drifts when it
  drives.
- **Falsified if:** the gyro mean changes by less than 0.5 counts between
  duty 0 and 25/50/100%, on every axis, in both of these:
  - the motor unplugged, with PWM on the pins (electrical only);
  - the motor plugged in but not mechanically coupled to the Wombat (motor
    on the table, wheel free).

  A firmware build with PWM at about 40 kHz must then show the same means.
  - If the shift appears only when the motor is mechanically coupled, it's
    vibration (aliasing or rectification), not PWM. That theory is filed
    separately, and G4 is refuted.
- **Experiment:**
  - One unit plus one DC motor.
  - Command duty through libkipr `mav`/`motor` in the sampling script.
  - A 40 kHz build only if a shift is seen.
  - Toggle servos in the same session (3V3 load, the ripple theory).
- **Fix if it holds:** move PWM out of 20–35 kHz; the TB6612 allows up to
  100 kHz. Check the effect on back-EMF sampling and PID first.

### G5. The shipped firmware's init race makes the gyro config depend on the unit's history

- **Claim:** the shipped `wombat.bin.pre_pr8` issues H_RESET and then config
  writes with no reset wait and no CS gap (H3/H7 from PR8). The config
  therefore depends on whether the MPU was power-cycled and on timing. After
  any STM32 reset without a power cycle, some units run a different config,
  giving a different bias and noise. Such resets happen on firmware update,
  or on Pi boot if wombat-os resets the STM32. Examples:
  - ±2000 dps, where the bias reads 8x smaller and quantization is coarse;
  - self-test on, where the gyro reads huge and frozen.
- **Falsified if:** on one unit, starting cold and from the shipped firmware
  only, each of these field transitions leaves GYRO_CONFIG = CONFIG = 0x00
  (read back with `regdump2`), with bias and noise equal to cold, in 3/3
  trials:
  - reflash shipped over shipped;
  - STM32 reset via GPIO 23;
  - `sudo reboot`, with botui running as in the field.
  - Also find out whether wombat-os or botui resets the STM32 at boot.
- **Experiment:** one unit, cheap. Needs a power cycle at the start (the
  AK8963 is still running from PR8 candidate flashes, H10).
- **Fix if it holds:** the PR #8 fix branch already fixes init (reset wait,
  CS gap, history-independent, E2-A). Shipping that firmware is the fix.

## Suggested order

G5 and G2 first: one unit, cheap, and nothing new to build. Then G3 (one new
firmware image). Then G4 (needs a motor). G1 runs whenever the user can
gather several units; the G3 image makes that survey record temperature
too.

## Needs from the user

1. **How many Wombats can you gather for G1, and which ones do coaches
   complain about?** G1 is the central question (are units really
   different, and why), and one unit can't answer it.
2. **What did the coaches actually observe?**
   - Which numbers (botui sensor screen vs program printf)?
   - Raw or after `gyro_calibrate()` (how many calls)?
   - Which libkipr/firmware version?
   - Does "unusable" mean at rest, drift while driving, or wrong turn
     angles?
   - Does the problem follow the controller onto another robot?
3. **Hardware for later experiments:** a DC motor (G4), a hair dryer (G3).
4. **Wombat state:** has it been power-cycled or used since 2026-09-30
   21:10Z?

## Experiment log

(none yet)
