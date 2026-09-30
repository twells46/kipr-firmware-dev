# PR #8 IMU investigation

Source of truth for this investigation. Update after every experiment, not at
the end. After a context compaction or a new session, re-read this file first.

## Resuming

1. Check access: `ssh wombat hostname`. If it fails, see `.devcontainer/README.md`
   ("Wombat SSH access"); `~/.ssh/config` is lost on container rebuild.
2. Read [Deployed state](#deployed-state). Confirm the flashed image with
   `ssh wombat md5sum ~/wombat-os/flashFiles/wombat.bin` and check uptime.
   Then ask the user whether the Wombat has been power-cycled or used since
   the last entry. The IMU state depends on history (H6).
3. Confirm botui and the IDE server are still stopped (`pgrep -a botui`),
   and the Wombat is flat and still.
4. Continue at [Next experiments](#next-experiments).

## Goal and acceptance criterion

Symptom: with PR #8, gyro and accel readings are extremely large, highly
variable, and inconsistent, so they are unusable in student programs.
Magnetometer is out of scope (broken for years).

Root cause = the minimal changeset to Wombat-Firmware and/or libwallaby, on
top of PR #8, that produces at-rest gyro/accel readings at least as good as
the pre-PR8 baseline. The user hopes the result is better than pre-PR8.

- **Measured with calibration.** `gyro_calibrate()` and `accel_calibrate()`
  run first, as a student program would. `wombat_sample.py` also records an
  uncalibrated pass for diagnosis.
- **Ranges fixed at ±250 dps and ±2g.** After libwallaby's `/16` that is
  about 8.2 counts per dps and 1024 counts per g. User programs must keep
  working unchanged or become more accurate.
- **Per axis, over more than 1000 readings:** the mean must be at least as
  close to the target (gyro 0; accel 0 on the level axes, about −1000 on the
  axis pointing down), and the standard deviation at least as small. No
  cherry-picked readings.
- **Comparison method:** 3 runs of 2000 samples per configuration. A
  candidate counts as "at least as good" when it falls within the baseline's
  run-to-run spread.
- **Known IMU state:** every run starts from a documented IMU state. Per E0,
  that means after a power cycle, unless the firmware under test is shown to
  reset the IMU completely.

## Rules of engagement

- Before testing a hypothesis, write down what result would falsify it, and
  design the experiment to try to falsify it.
- Stop after 5 refuted hypotheses and write a summary instead of continuing.
  Inconclusive experiments don't count toward the 5.
- Only one agent touches the Wombat. Parallel agents may generate hypotheses
  or attack conclusions, but never run anything on the Wombat.
- Flash plus reboot is allowed without asking only if a reboot (no power
  switch) is enough to apply new firmware and reset the IMU. E0 showed a
  reboot is **not** enough to reset the IMU, so runs that need a clean IMU
  need the user to power-cycle it.
- `shutdown`/`poweroff` always needs confirmation.
- Log every change under `/etc`, every `apt` command, and what's deployed
  (kernel, firmware, git SHAs) in [Wombat changes](#wombat-changes) and in
  each run's `provenance.txt`.
- botui and the IDE server are stopped for measurements (the user did this
  on 2026-09-30).
- The Wombat stays flat and still.
- Note: `Wombat-Firmware/AGENTS.md` says agents don't flash hardware. The
  user's rules above override that for this investigation only.

## Tools

- `investigation/repro.sh <label> [samples=2000] [interval_ms=10]`: records
  provenance, runs `wombat_sample.py` on the Wombat through the installed
  `/usr/lib/libkipr.so` getters, and saves the raw and calibrated CSVs, the
  summaries, and `provenance.txt` to `investigation/runs/<UTC>-<label>/`. It
  never flashes, reboots, or writes outside `/tmp` on the Wombat.
- `investigation/build.sh <label> <git-ref> [patch ...]`: exports the ref
  with `git archive` (the repo's working tree is untouched), applies the
  patches, and builds natively. The output goes to
  `investigation/builds/<label>/`: `wombat.bin`, `build-info.txt` (SHA,
  patch md5s, toolchain, image md5, warning count), and the patches. Put
  experiment patches in `investigation/patches/`. Toolchain:
  arm-none-eabi-gcc 14.2.1 (Debian), CMake 3.31. Its build of `4baf206` is
  byte-identical to the host Docker build `wombat.bin.pr8`. Don't use
  `Wombat-Firmware/build/`: it holds a stale image (md5 `19e2a891…`) of
  unknown origin.
- `investigation/flash.sh <image>`: flashes a local file, or a file already
  in `~/wombat-os/flashFiles`, and saves the log to `investigation/flashes/`.
  It fails unless stm32flash verifies the write. It does not reboot.
- Under the hood, `wallaby_flash` sets BOOT0 high, resets the STM32 through
  GPIO 23, programs it with `stm32flash -v` over `/dev/ttyAMA0`, sets BOOT0
  low, and resets it again. The new image runs immediately (E0). The STM32
  bootloader is in ROM, so a bad image can always be reflashed.
- Reboot: run `ssh wombat 'sudo reboot'`, then poll with
  `ssh -o ConnectTimeout=5 wombat true` until it answers (about 30 s).
- `~/gyro-diagnostics.tar.gz` on the Wombat is an earlier frozen-snapshot
  diagnostic (special firmware plus `gyro_snapshot.py`, built from 4baf206).
  It can separate MPU/SPI3 problems from SPI2 publication or libwallaby
  decoding problems. Its image repurposes the accel/mag registers.
- `gdbserver` 16.3 is installed on the Wombat.

## Deployed state

| Item | Value |
|---|---|
| Wombat kernel | 6.18.50+rpt-rpi-v8, Debian 13.7 |
| libkipr on Wombat | deb `kipr` 1.2.4, `/usr/lib/libkipr.so` sha256 `8eafd26fdc6d0dc2…` |
| Flashed firmware | `wombat.bin.pre_pr8` (md5 `43444cc7…`), flashed 2026-09-30 19:12Z |
| IMU state | **Clean**: user power-cycled at about 19:20Z. Since then only pre-PR8 has run and only E0-F has been measured. |
| botui / IDE server | Stopped by the user (running processes; unknown whether they come back after a power cycle; check `pgrep -a botui`) |
| `wombat.bin.pre_pr8` | md5 `43444cc7…`, 32152 bytes. The user believes it came from `d2d651e`, but it's unverified: my `d2d651e` build is 31476 bytes, md5 `b7005938…` (probably a different toolchain). No Firmware changes between `d2d651e` and master. |
| `wombat.bin.pr8` | md5 `a07b5eb4…`, 30876 bytes. Verified identical to my build of `4baf206` (`builds/pr8-unfixed`). |
| PR8 source | Wombat-Firmware `4baf206` (branch `oscar/mpu9250-imu-driver`, clean) |
| Local libwallaby | `cf56155` (master); unknown whether it matches the deployed 1.2.4 |

## Static findings (code reading)

- **S1. PR8 `setup_gyro()` enables gyro self-test on all axes.**
  `regval |= (~GYRO_FCHOICE_BYTE)`: `~0x03` promotes to int `0xFFFFFFFC`, and
  truncating to `uint8_t` gives `0xFC`. That writes GYRO_CONFIG = `0xFC`:
  XGYRO_Cten, YGYRO_Cten and ZGYRO_Cten all set (self-test on), GYRO_FS_SEL =
  `11` (±2000 dps, not the ±250 that `GYRO_DEFAULT_SENSITIVITY_BYTE` intends),
  and FCHOICE_B = `00`. The intended value was probably FCHOICE_B = `00` only,
  i.e. `~GYRO_FCHOICE_BYTE & 0x03`. This confirms the user's bitmask reading.
- **S2. PR8 `setup_accel()` does not enable accel self-test.** It clears
  bits 7:5 and sets ±2g. ACCEL_CONFIG2 is never written.
- **S3. Reset timing.** Both master and PR8 write PWR_MGMT_1 = `0x80`
  (H_RESET) and then configure the chip within about 1 ms (master has no
  delay at all). Writes issued before the reset completes may be dropped.
- **S4. Master (pre-PR8) asks for gyro ±2000 dps (`0x3 << 3`) and accel
  ±4g.** Its read-modify-write never clears the gyro self-test bits 7:5. Yet
  the cold-boot baseline behaves like ±250 dps and ±2g (the power-on
  defaults), which suggests master's config writes don't take effect at cold
  boot (S3). Unless `wombat.bin.pre_pr8` wasn't built from master.
- **S5. PR8 `readIMU()` reads accel and gyro as two separate SPI3 bursts**,
  writing byte-wise into `aTxBuffer` while SPI2 DMA may be transmitting it.
  H/L halves of one axis can come from different samples (tearing), which
  could produce large jumps. This path also existed before PR8.
- **S6. libwallaby `accel_calibrate()` is wrong** (`module/accel/src/
  accel_p.cpp`). It swaps the X and Z sums (`sumX += accel_z()`, `sumZ +=
  accel_x()`) and adds +512 to the Z bias, which assumes 512 counts/g
  (±4g). Confirmed on hardware (E0-A): calibration turns a healthy accel into
  x ≈ +1031 and z ≈ −1542.
- **S7. PR8 removed the WHO_AM_I check** that aborted setup when the MPU
  didn't respond.
- **S8. `gyro_calibrate()` truncates its biases to int** from only 50
  samples, leaving about ±1 count of residual bias.

## Hypotheses

Status: `open`, `testing`, `supported`, `confirmed`, `refuted`, `superseded`,
or `inconclusive`. Refuted count: **0 / 5**.

| ID | Claim | Falsified if | Status |
|---|---|---|---|
| H1 | S1 (gyro self-test on and ±2000 dps) causes the gyro symptom | PR8 gyro stats are no worse than pre-PR8; or PR8 with only the one-line fix is still worse than baseline (from a clean IMU state) | **supported**: E0-C shows PR8 gyro is far worse. The fix itself isn't tested yet. |
| H2 | The accel symptom has a separate firmware cause | — | **superseded by H5**: raw accel under PR8 is not worse than baseline (E0-C) |
| H3 | MPU writes shortly after H_RESET are dropped (S3), so the real config differs from the source | A register readback after init equals the written values | open. E0-D/E suggest config depends on prior state; not tested directly. |
| H5 | The accel symptom students see comes from libwallaby `accel_calibrate()` (S6), independent of firmware | Calibrated accel is healthy under some firmware; or fixing S6 alone doesn't bring calibrated accel to target | **supported**: broken identically under pre-PR8 and PR8 (E0-A/B/C). The fix isn't tested yet. |
| H4 | SPI2 publication tearing (S5) causes the gyro variability | The frozen-snapshot diagnostic shows large values already in the raw SPI3 bytes, and the published bytes match them | open. Lower priority; test only if H1's fix leaves excess variance. |
| H6 | IMU state survives STM32 reset, flash, and Pi reboot; only a power cycle clears it | Baseline returns after flash or reboot; or doesn't return after a power cycle | **confirmed** (for the shipped firmware): flash (E0-D) and reboot (E0-E) don't restore the baseline; a power cycle does (E0-F) |

## Experiment log

All runs are 2000 samples at 10 ms unless noted. Values are mean (std) per
axis, in counts after `/16`.

### E0: how firmware changes are applied (2026-09-30)

Falsifiers set beforehand:
- "Flash alone applies firmware" is falsified if PR8's stats don't change
  after the flash.
- "Reboot is enough" is falsified if the baseline doesn't return after
  reflashing pre-PR8 plus a reboot.

| Step | Run | State | Raw gyro x/y/z | Raw accel x/y/z | Calibrated accel x/y/z |
|---|---|---|---|---|---|
| — | `…185633Z-smoketest` (100 samples) | pre-PR8, after a power-up of unknown kind, botui running | 2.2 / 6.3 / 8.9 (≈1.2) | 0.6 / 61.4 / −1032.0 | — |
| A | `…190859Z-e0-a-prepr8-baseline1` | pre-PR8, same boot as the smoke test, botui stopped | 2.2 (1.1) / 6.1 (1.2) / 9.0 (1.2) | −0.8 (1.9) / 62.5 (2.2) / −1032.0 (3.5) | 1031 / −0.9 / −1542 |
| B | `…190957Z-e0-b-prepr8-baseline2` | same | 2.3 (1.3) / 6.1 (1.5) / 9.0 (1.2) | −1.1 (3.9) / 62.7 (2.9) / −1032.2 (4.7) | 1032 / −0.4 / −1542 |
| C | `…191136Z-e0-c-pr8-flashonly` | flashed `wombat.bin.pr8`, no reboot | −450 (792) / 619 (343) / 899 (1311), hits ±2048 | −1.4 (2.2) / 60.7 (2.2) / −1020.1 (3.6) | 1019 / 0.0 / −1531 |
| D | `…191258Z-e0-d-prepr8-reflash` | reflashed pre-PR8, no reboot | 0.5 (13.8) / 0.7 (12.9) / 1.3 (22.2) | −0.2 (5.4) / 61.6 (5.6) / −1021.4 (9.2) | 1020 / −1.3 / −1533 |
| E | `…191536Z-e0-e-prepr8-afterreboot` | D plus `sudo reboot` | 0.3 (13.7) / 1.0 (12.9) / 0.9 (22.5) | −0.5 (4.6) / 61.2 (4.6) / −1021.4 (7.8) | 1019 / −1.2 / −1533 |
| F | `…192725Z-e0-f-prepr8-powercycle` | E plus the user's poweroff and switch toggle | 2.4 (1.1) / 6.1 (1.3) / 9.0 (1.2) | −0.7 (2.0) / 64.7 (2.2) / −1032.9 (3.7) | 1030 / −0.5 / −1544 |

Conclusions:
- **A flash alone applies new firmware.** `wallaby_flash` resets the STM32,
  and the new image runs immediately. No reboot is needed.
- **The IMU keeps its state across STM32 reset, flash, and Pi reboot.** The
  same pre-PR8 image behaves differently after PR8 has run (D, E vs A, B).
- **The reboot rule's premise failed.** A reboot doesn't reset the IMU, so
  clean comparisons need a power cycle or firmware that fully resets the IMU.
- **In raw readings the PR8 symptom is gyro-only.** Raw accel under PR8 is
  within about 1% of baseline. The broken accel students see is S6, under
  every firmware.
- **In D and E the gyro biases shrank about 8x (2/6/9 → about 0.3/0.8/1.1)
  and the noise rose about 10x.** The 8x matches a switch from ±250 to ±2000
  dps, which master's source requests (S4) but which apparently didn't take
  effect at cold boot. Accel z shifted from −1032 to −1021 and its noise
  doubled. Not yet explained. Speculative, pending a register readback (H3).
- **E0-F: a power cycle restores the baseline** exactly (gyro std about
  1.2, biases 2/6/9; accel z −1033). H6 confirmed.
- **The baseline for comparisons is A, B, and F** (three cold-boot runs of
  pre-PR8).

### Baseline reference (pre-PR8, cold boot; E0-A/B/F)

Run-to-run range across the three runs, in counts after `/16`. A candidate
must be at least this good per axis (see the criterion).

| Axis | Raw mean | Raw std | Calibrated mean | Calibrated std |
|---|---|---|---|---|
| gyro_x | 2.2 to 2.4 | 1.05 to 1.34 | 0.26 to 1.29 | 1.06 to 1.25 |
| gyro_y | 6.1 | 1.23 to 1.53 | 0.10 to 0.24 | 1.26 to 1.36 |
| gyro_z | 9.0 | 1.18 to 1.22 | 0.06 to 0.94 | 1.14 to 1.19 |
| accel_x | −1.1 to −0.7 | 1.93 to 3.90 | 1030 to 1032 (S6 bug) | 2.01 to 2.38 |
| accel_y | 62.5 to 64.7 | 2.22 to 2.87 | −0.9 to −0.35 | 1.87 to 2.34 |
| accel_z | −1032.9 to −1032.0 | 3.48 to 4.65 | −1544 to −1542 (S6 bug) | 3.65 to 4.04 |

Calibrated accel x and z are wrong in the baseline itself (S6). For those,
the target is the criterion (x ≈ 0, z ≈ −1000), not the baseline's mean. The
baseline's std still applies.

## Next experiments

Measurement protocol for every configuration:
1. Flash with `flash.sh`.
2. Make sure the IMU is in a known state (see below).
3. Run `repro.sh <label>` 3 times. Compare against the baseline reference.

**IMU state.** With firmware that doesn't fully reset the IMU, the state
depends on history (H6). Ask the user for a power cycle before the runs.
Shutdown needs confirmation: either they confirm and I run
`ssh wombat 'sudo poweroff'`, or they do it themselves; then they toggle the
switch. If a candidate firmware provably resets the IMU (E1 readback shows
identical registers after a power cycle vs after a flash following PR8), it
may run without power cycles.

Planned order (the user said to pause before starting these):

- **E1: register readback (tests H3).** Build a diagnostic variant of
  `4baf206` that reads GYRO_CONFIG, ACCEL_CONFIG, ACCEL_CONFIG2, CONFIG,
  SMPLRT_DIV, PWR_MGMT_1 and WHO_AM_I right after `setupIMU()` and publishes
  them. The earlier `gyro-diagnostics` patch publishes bytes as
  `value << 4` in the accel/mag slots, and a libkipr getter then returns the
  byte; reuse that approach. Capture them after a power cycle and after a
  flash that follows other firmware. Also build the same readback on
  `d2d651e` to explain S4.
  - Predicted if H3 holds: at cold boot, the values differ from what the
    source writes.
  - Falsified if: the readback equals the written values in every state.
- **E2: H1 fix.** `4baf206` plus a one-line patch:
  `regval |= (~GYRO_FCHOICE_BYTE) & 0x03;`, or equivalently no OR at all,
  because FCHOICE_B = 00 is what `regval &= ~0x03` already leaves. From a
  clean IMU, 3 runs.
  - Falsified if: gyro doesn't reach the baseline reference.
  - Watch for accel changing, which it shouldn't.
- **E3: H5 fix.** libwallaby `accel_calibrate()` with the X/Z swap fixed and
  the gravity correction set for ±2g (1024 counts/g, and the right sign for
  a Z-down board). Deploy as a patched `/usr/lib/libkipr.so`: back up the
  original first and log it under Wombat changes. Build libkipr for aarch64
  per `.devcontainer/README.md`.
  - Falsified if: calibrated accel isn't x ≈ 0, y ≈ 0, z ≈ −1024 with
    baseline std.
  - Check whether the deployed 1.2.4 equals libwallaby `cf56155` before
    patching (compare the source of `accel_p.cpp`, or behavior).
- **E4 (if needed): robust init.** An H_RESET, a wait of about 100 ms
  (datasheet), then absolute writes. Aim: the firmware no longer depends on
  IMU history, which is what would allow unattended flash-and-test.
- Use parallel agents (no Wombat access) to review E1–E3 patches and to try
  to break the conclusions from the raw CSVs.

## Wombat changes

| When (UTC) | Change | Why |
|---|---|---|
| 2026-09-30 | `sudo apt-get install -y gdbserver` (16.3-1) | Remote debugging |
| 2026-09-30 19:11 | Flashed `wombat.bin.pr8` | E0-C |
| 2026-09-30 19:12 | Flashed `wombat.bin.pre_pr8` | E0-D |
| 2026-09-30 ~19:14 | `sudo reboot` | E0-E |
| 2026-09-30 ~19:20 | Power cycle by the user (poweroff plus switch) | E0-F |

State as of 2026-09-30 19:30Z: pre-PR8 flashed and IMU clean. `kipr` 1.2.4
and `/etc` are unmodified. The only package change is gdbserver.

## Open questions

- Can the firmware put the IMU in a clean state without a power cycle? A
  proper H_RESET, a wait of about 100 ms, then absolute (not
  read-modify-write) register writes. If so, that is both a candidate part
  of the fix and what would let flash-and-test run without the user (E4).
- `wombat.bin.pre_pr8` can't be reproduced from `d2d651e` with the current
  toolchain. It stays the baseline because it's what schools run. If a
  comparison ever needs a from-source pre-PR8, use `builds/prepr8-d2d651e`,
  and baseline it separately first.
