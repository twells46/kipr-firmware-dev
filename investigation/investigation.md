# PR #8 IMU investigation

Source of truth for this investigation. Update after every experiment, not at
the end. After a context compaction or a new session, re-read this file first.

**Status: concluded 2026-09-30.** The root cause and fixes are in
[Conclusion](#conclusion-2026-09-30-2100z). The fixes are in pull requests:
[kipr/Wombat-Firmware#8](https://github.com/kipr/Wombat-Firmware/pull/8)
(branch `oscar/mpu9250-imu-driver`, commits `35ef0a2`..`49cca43`), and
[twells46/libwallaby#2](https://github.com/twells46/libwallaby/pull/2) (branch
`fix-imu-calibration`, commits `de1c6f6` and `2383007`). The rest of this file is the experiment record. The
tools below still work for future IMU or firmware work.

**What's in this directory:**
- Tools: `build.sh`, `libbuild.sh`, `flash.sh`, `repro.sh`,
  `wombat_sample.py`, `regdump.sh`/`regdump.py`, `gyrobytes.py`.
- `patches/`: every firmware and library change tested.
- `builds/<label>/`: `wombat.bin` and `build-info.txt` (ref, patch md5s,
  toolchain, image md5) for every image flashed. `builds/e1-regdump2` is
  the register-readback tool.
- `libbuilds/<label>/build-info.txt`: records the sha256 of each tested
  libkipr.
- `runs/`: raw CSVs, summaries and provenance for every measurement.
- `flashes/`: every flash log. The first line names the source image and
  its md5.

Build scratch (`src/`, `build/`) and `libkipr.so` are git-ignored. To
regenerate any build, rerun `build.sh`/`libbuild.sh` with the ref and patches
in its `build-info.txt`. Toolchain and source are the same, so a rebuilt
`wombat.bin` should match the recorded md5.

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
  patch md5s, toolchain, image md5, warning count), and a copy of the
  patches (git-ignored, like `src/` and `build/`). Put
  experiment patches in `investigation/patches/`. Toolchain:
  arm-none-eabi-gcc 14.2.1 (Debian), CMake 3.31. Its build of `4baf206` is
  byte-identical to the host Docker build `wombat.bin.pr8`. Don't use
  `Wombat-Firmware/build/`: it holds a stale image (md5 `19e2a891…`) of
  unknown origin.
- `investigation/libbuild.sh <label> <git-ref> [patch ...]`: the same for
  libwallaby. It cross-compiles libkipr for aarch64 (about 90 s) into
  `investigation/libbuilds/<label>/`. Test a build without touching
  `/usr/lib` using `LIBKIPR=investigation/libbuilds/<label>/libkipr.so
  investigation/repro.sh <label>`.
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
- `investigation/regdump.sh <label>`: with `builds/e1-regdump2` flashed,
  reads 32 MPU registers from direct SPI2 frames (`regdump.py`) and saves
  them to `runs/`. "Entry" = the registers as the previously flashed
  firmware left them. Flashing regdump2 doesn't disturb the MPU (E2-0), so
  "flash X, then flash regdump2, then regdump.sh" shows X's real config.
  Don't use `builds/e1-regdump` (without the gap): its entry reads are
  garbage (H7).
- `investigation/gyrobytes.py [n]` (run on the Wombat next to
  `regdump.py`): classifies published gyro byte frames as aligned, shifted
  by one byte (H7), or other.

## Deployed state

| Item | Value |
|---|---|
| Wombat kernel | 6.18.50+rpt-rpi-v8, Debian 13.7 |
| libkipr on Wombat | deb `kipr` 1.2.4, `/usr/lib/libkipr.so` sha256 `8eafd26fdc6d0dc2…` |
| Flashed firmware | `builds/final-49cca43/wombat.bin` (Wombat-Firmware `49cca43`, md5 `2d941ad8…`), flashed 2026-09-30 21:10Z |
| IMU state | Final firmware (history-independent). The AK8963 is still in continuous mode from earlier candidate flashes until the next power cycle (H10). |
| Location | **Floor since about 20:15Z.** Compare accel x/y only with E2-B or later runs. |
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
- **S11. Both calibrate functions average the already-calibrated getters**, so
  calling them twice undoes the calibration (confirmed in E3).
- **S8. `gyro_calibrate()` truncates its biases to int** from only 50
  samples, leaving about ±1 count of residual bias.
- **S9. `d2d651e` pre-PR8 source aborts `setupIMU()` if WHO_AM_I ≠ 0x71**,
  read 200 µs into setup (about 5 ms after SPI3 init). At cold boot the
  MPU may not answer yet (datasheet start-up is milliseconds), which
  would leave power-on defaults (±250 dps, ±2g). A possible explanation of
  S4.
- **S10. `wombat.bin.pre_pr8` does not behave like `d2d651e` source.**
  `d2d651e`'s `main()` calls `readIMU()` only when `count % 1000 == 0`
  (about once per 0.7–1 s), but every baseline run shows a new IMU value on
  essentially every 10 ms sample (1948–1976 distinct of 2000). Either the
  shipped image was built from other source, or the loop is far faster than
  the source implies. Neither the strings nor the size match (debug strings
  are compiled out in both). The baseline stays the shipped image
  (it's what schools run), but its source is unknown, so its config must be
  measured, not read from source (E1).

## Hypotheses

Status: `open`, `testing`, `supported`, `confirmed`, `refuted`, `superseded`,
or `inconclusive`. Refuted count: **3 / 5** (H1, H8, H9).

| ID | Claim | Falsified if | Status |
|---|---|---|---|
| H1 | S1 (gyro self-test on and ±2000 dps) causes the gyro symptom | PR8 gyro stats are no worse than pre-PR8; or PR8 with only the one-line fix is still worse than baseline (from a clean IMU state) | **refuted** (E1-a, E2-1, E2-2): the symptom appears with GYRO_CONFIG 0x00, and PR8's 0xFC never reaches the chip (dropped after H_RESET). S1 is a latent bug that becomes live once init waits for the reset. |
| H2 | The accel symptom has a separate firmware cause | — | **superseded by H5**: raw accel under PR8 is not worse than baseline (E0-C) |
| H3 | MPU writes shortly after H_RESET are dropped (S3), so the real config differs from the source | A register readback after init equals the written values | **confirmed for PR8** (E2-1): writes at ~0.4 ms after H_RESET are dropped, writes at ~0.7 ms or later land |
| H8 | Leaving the MPU I2C master and AK8963 running (USER_CTRL 0x20) shifts accel z by about +11 counts | Same firmware with the I2C master off still reads −1021; or with it on reads −1032 | **refuted** as stated (E2-H8: I2C master off, accel z still −1022.7). Confounded: the AK8963 kept running from the previous flash. The real cause is H10. |
| H9 | Accel z reads about −1022 after an H_RESET since power-up and about −1032 after a power-on reset alone (the offset isn't visible in the dumped registers) | In the same cold session at one location, regdump2 (no reset) and the H_RESET-only regdump give the same accel z | **refuted** (E2-B: −1034.1 vs −1034.5; the reset did happen, SLV0 cleared) |
| H10 | The AK8963 in continuous-measurement mode (set by PR8's `setup_magnetometer()`; it survives the MPU H_RESET and only a power cycle clears it) shifts accel z by about +12 counts. x/y are unaffected | In one power session, with the AK8963 never enabled, the candidate without `setup_magnetometer()` reads the same z as the full candidate | **supported** (E2-B: −1033.7 without vs −1021.4 with; x/y equal). It also explains every earlier −1022 run, including H8-nomag (the AK8963 was still running from the previous flash). |
| H5 | The accel symptom students see comes from libwallaby `accel_calibrate()` (S6), independent of firmware | Calibrated accel is healthy under some firmware; or fixing S6 alone doesn't bring calibrated accel to target | **confirmed** (E3: patched calibration gives 0/0/−1024 at raw std) |
| H4 | SPI2 publication tearing (S5) causes the gyro variability | The frozen-snapshot diagnostic shows large values already in the raw SPI3 bytes, and the published bytes match them | open. Lower priority; test only if H1's fix leaves excess variance. |
| H7 | PR8's back-to-back accel and gyro SPI3 bursts merge (CS high too short), so published gyro = bytes 0x42–0x47, shifted one byte | A CS-high gap alone (same MPU state) doesn't remove the shift or restore baseline gyro stats | **supported**: E1-a 84% of frames shifted with GYRO_CONFIG 0x00; E1-b gap alone → 99.9% aligned, baseline means. The entry-snapshot garbage is the same effect. |
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

### E1: register readback (2026-09-30, started 19:50Z)

Resume check: the Wombat booted at 19:19Z (the E0-F power cycle), with no
reboot since, pre-PR8 flashed, and botui stopped. The container had been
rebuilt; `~/.ssh/config` was re-created from the README (without it `wombat`
resolves to a different host, `wombat.lan`).

| Step | Run | State | Raw gyro x/y/z | Raw accel x/y/z | Calibrated accel x/y/z |
|---|---|---|---|---|---|
| 0 | `…195000Z-e1-0-prepr8-stillclean` | pre-PR8, 31 min after E0-F's cold boot, untouched | 2.4 (1.5) / 6.1 (1.9) / 9.1 (1.2) | −0.3 (3.1) / 65.3 (2.6) / −1032.7 (4.5) | 1032 / −0.3 / −1544 |

Step 0 confirms the clean state still holds (it matches A/B/F). Gyro y std
1.91 and accel y 65.3 are slightly outside the three-run range. Counted
as a 4th baseline run.

Instrument: **regdump firmware** (`patches/e1-regdump.patch` on `4baf206`,
`builds/e1-regdump`, md5 `68e5860f…`). `setupIMU()` writes nothing. It
only reads 32 MPU registers ("entry" = as the previous firmware left them,
since they survive an STM32 reset, per H6). `readIMU()` reads accel/gyro
exactly as PR8 does. The mag slots publish (entry, live) register values
with a checksum. Read them with `regdump.sh <label>` (direct spidev
frames, majority vote per register). Because it writes nothing, flashing it
after image X shows X's actual MPU config.

Plan and falsifiers (set before running):
- **E1-a**: flash regdump now (after cold-boot shipped pre-PR8). H3/S9
  predicts power-on defaults: CONFIG 0x00, SMPLRT_DIV 0x00, GYRO_CONFIG
  0x00, ACCEL_CONFIG 0x00. **Falsified** if they equal what `d2d651e`
  writes (CONFIG 0x03, SMPLRT_DIV 0x04, GYRO_CONFIG 0x18, ACCEL_CONFIG
  0x08). Also run `repro.sh` under regdump: if the stats differ from baseline
  with the same MPU config, the readout path (not the config) matters.
- **E1-b**: flash `wombat.bin.pre_pr8` (warm, over a clean state), run
  `repro.sh` once, then flash regdump → warm pre-PR8 config. Separates
  "warm pre-PR8 setup differs from cold" from "PR8 leaves persistent state"
  as the cause of E0-D.
- **E1-c**: flash `wombat.bin.pr8`, then regdump → PR8 config. S1
  predicts GYRO_CONFIG 0xFC, ACCEL_CONFIG 0x00, CONFIG 0x03, SMPLRT_DIV
  0x04. **Falsified** if GYRO_CONFIG ≠ 0xFC.
- **E1-d**: flash pre_pr8 again (now after PR8), then regdump →
  explains E0-D.
- All of this leaves the IMU dirty. E2's acceptance runs need a power cycle
  afterwards anyway.

**E1-a results** (`…195520Z-e1-a-regdump-after-cold-prepr8`,
`…195627Z-e1-a-regdump-reread`, `…195634Z-e1-a-regdump-stats`; flashed
19:55Z):

- **Live registers are the MPU-9250 power-on defaults**: PWR_MGMT_1 0x01;
  SMPLRT_DIV, CONFIG, GYRO_CONFIG, ACCEL_CONFIG, ACCEL_CONFIG2 and USER_CTRL
  all 0x00 (±250 dps, ±2g, no DLPF). The exception is I2C_SLV0_ADDR/REG/CTRL
  = 0x8C/0x26/0x03 (magnetometer-read residue). WHO_AM_I 0x71. The prediction
  held (defaults, not `d2d651e`'s writes). This fits the baseline behaving
  like ±250/±2g.
- **Entry values are not trustworthy.** Factory-programmed registers
  (SELF_TEST_*_GYRO, XA/YA/ZA_OFFSET) differ between entry and live, and
  entry PWR_MGMT_1 = 0xED (H_RESET, SLEEP and CYCLE all set). At the moment
  the new firmware started, the MPU was mid-reset or had just taken random
  writes. Suspected cause: SPI3 lines float while the STM32 is held in
  reset or in the ROM bootloader during `wallaby_flash`, so the MPU can see
  garbage transactions (possibly including H_RESET). Not yet tested. The
  planned control is regdump flashed over regdump. So "entry" can't show
  what the previous firmware configured, and E1-b..d as designed are
  unreliable. Live values after a regdump flash show the post-flash state.
- **Under regdump the gyro is broken exactly like PR8**, with GYRO_CONFIG =
  0x00: raw gyro 617 (836) / 687 (310) / 1044 (1238), 3.3% saturated. Accel
  is normal: −1.0 (2.0) / 64.4 (2.3) / −1032.6 (3.7). **So the PR8 gyro
  symptom does not need S1.** Regdump shares only PR8's `readIMU()`
  accel/gyro path.
- **Raw published bytes (direct SPI2) show a one-byte shift**
  (`gyrobytes.py`, 3000 distinct frames): 84% "shifted", 10% aligned, 6%
  other (torn). Shifted frames re-read from byte 1 give x/y raw 46.7 (28.9) /
  108.1 (53.8), the same as aligned frames 47.1 (28.9) / 110.1 (57.2) and
  the baseline (≈38/98 raw). The published "gyro" is mostly
  [TEMP_L, GX_H, GX_L, GY_H, GY_L, GZ_H].

**H7 (new):** PR8's `readIMU()` reads accel (0x3B, 6 bytes) and then gyro
(0x43, 6 bytes) as two SPI3 transactions with only a few CPU cycles of CS
high between them. The MPU usually misses that CS pulse and continues the
accel burst. The gyro command byte clocks out TEMP_H (0x41), and the six
"gyro" bytes are 0x42–0x47. Occasionally an interrupt lengthens the gap and
the read is correct.
- Falsified if: adding only a CS-high gap (e.g. `delay_us(1)`) between the
  two bursts under regdump, in the same MPU state, leaves a substantial
  shifted fraction or leaves the gyro stats far from baseline.
- Fix candidate if it holds: read 0x3B–0x48 as one 14-byte burst (accel,
  temp, gyro from the same sample instant, with no inter-burst CS timing),
  or keep the gap.

**E1-b: H7 test** (`builds/e1-regdump-gap` = regdump + `patches/e1-gap.patch`,
a `delay_us(2)` between the bursts and nothing else; flashed 19:59Z;
`…200002Z-e1-b-regdump-gap`, `…200029Z-e1-b-regdump-gap-stats`):
- **H7 survived its falsification test.** 2997/3000 frames aligned, 0
  shifted. Raw gyro 2.5 (2.7) / 6.05 (1.7) / 9.0 (1.2): the means equal
  baseline. Gyro x std 2.7 comes from a vibration burst in samples
  1400–2000 (gyro and accel noise rise together; per-200-sample std before
  that is 1.0–1.5). The clean run `…195000Z` shows smaller bursts at
  600–800 and 1000–1200.
- Accel y is 51.3 for the whole run, against 64.4 in E1-a four minutes
  earlier under the same readout. It's constant, so a physical tilt of
  about 0.8°: the Wombat or the table was probably nudged. **Ask the
  user.** Future accel-y comparisons must use runs taken after 20:00Z,
  or take this into account.
- **The entry garbage is H7 too, not a flash disturbance.** Back-to-back
  `IMU_read()` calls merge, so each read returns the register two past the
  previous one: after WHO_AM_I (0x75), "PWR_MGMT_1" = 0xED = XA_OFFSET_H
  (0x77), "SMPLRT_DIV" = 0xFC = YA_OFFSET_L (0x7B), "CONFIG" = 0x20 =
  ZA_OFFSET_H (0x7D), "ACCEL_CONFIG" = 0xCE = SELF_TEST_Y_GYRO (0x01, after
  wrap). The same garbage appeared twice. The floating-bus suspicion is
  withdrawn.
- **Consequence for PR8's setup:** `setup_gyro()` and `setup_accel()` each
  do `IMU_read()` and then immediately `IMU_write()`. Under H7 the write
  merges into the read burst and is dropped, so **PR8's 0xFC (S1) probably
  never reaches the chip.** Once reads end properly, S1 would land
  (±2000 dps, self-test on). Only `IMU_write()` has a CS gap
  (`delay_us(10)`).

### E2: fix candidates (2026-09-30, from 20:05Z)

Patches on `4baf206`:
- `patches/fix-cs-gap.patch`: `delay_us(10)` after CS goes high in
  `IMU_read()` and `read_bytes()`, mirroring `IMU_write()`. 2 lines.
- `patches/fix-gyro-config.patch`: `regval |= (~GYRO_FCHOICE_BYTE) & 0x03;`
  (S1). 1 line.

Builds: `fix-cs-gap` (md5 `c7aa7a37…`), `fix-cs-gap+gyro-config`
(`d674e4e4…`), and `e1-regdump2` = regdump + fix-cs-gap (`55189f76…`;
valid entry reads).

Plan and falsifiers (set before running; all warm, so IMU not clean):
- **E2-0 (control):** flash regdump2 over regdump-gap. Entry must equal the
  E1-b live values (defaults, SLV0 0x8C/0x26/0x03, factory
  ST C5/CE/E2, accel offsets ED2E/EBFC/206E). Falsified (entry still
  unreliable, or the flash disturbs the MPU) otherwise.
- **E2-1:** flash `wombat.bin.pr8`, then regdump2 → PR8's real config. H7
  predicts CONFIG 0x03, SMPLRT_DIV 0x04 and USER_CTRL 0x20 land, while
  GYRO_CONFIG and ACCEL_CONFIG stay 0x00 (writes dropped). Falsified if
  GYRO_CONFIG = 0xFC.
- **E2-2:** flash `fix-cs-gap` → repro ×1 → regdump2. H1 predicts
  GYRO_CONFIG 0xFC and a gyro that is aligned but wrong (self-test offset,
  ±2000 scale). Falsified for H1 if the gyro is at baseline with 0xFC, or
  if GYRO_CONFIG ≠ 0xFC.
- **E2-3:** flash `fix-cs-gap+gyro-config` → repro ×1 → regdump2.
  Predicted: GYRO 0x00, ACCEL 0x00, CONFIG 0x03, SMPLRT 0x04; gyro/accel
  std ≤ baseline (DLPF 41 Hz should lower noise). Falsified if the config
  differs or the stats are worse than baseline.
- Then acceptance: `fix-cs-gap+gyro-config` from a power cycle, 3 runs.

**E2 results (20:03–20:08Z):**

| Step | Image | Config readback (regdump2 entry = live) | Raw gyro x/y/z | Raw accel x/y/z |
|---|---|---|---|---|
| E2-0 | regdump2 over regdump-gap | defaults: PWR_MGMT_1 0x01, all config 0x00, USER_CTRL 0x00, SLV0 0x8C/0x26/0x03, factory regs = E1-b live | — | — |
| E2-1 | `wombat.bin.pr8` | CONFIG **0x00**, SMPLRT_DIV **0x00**, GYRO_CONFIG **0x00**, ACCEL_CONFIG 0x00, USER_CTRL 0x20, I2C_MST_CTRL 0x0D, SLV0 0x8C/0x03/0x87 | — (E0-C) | — |
| E2-2 | `fix-cs-gap` | same as E2-1 | 2.7 (3.7) / 5.9 (2.5) / 8.5 (1.3) | −2.9 (5.2) / 50.4 (4.4) / −1021.1 (14.7) |
| E2-3 | `fix-cs-gap+gyro-config` | same as E2-1 | 2.4 (1.9) / 6.2 (1.7) / 8.7 (1.2) | −2.3 (4.8) / 50.4 (3.4) / −1022.2 (5.0) |

Runs: `…200526Z-e2-warm-fix-cs-gap`, `…200702Z-e2-warm-fix-cs-gap+gyro-config`,
readbacks `…e2-0-regdump2-control`, `…e2-1-pr8-config`, `…e2-cfg-*`.

- **E2-0 control passed.** The flash doesn't disturb the MPU, and regdump2
  entry reads are valid.
- **E2-1: in PR8 only the late magnetometer writes land.** CONFIG and
  SMPLRT_DIV (plain `IMU_write`s about 0.4 ms after H_RESET) are dropped, as
  are GYRO_CONFIG and ACCEL_CONFIG. USER_CTRL, I2C_MST_CTRL and SLV0
  (about 0.7 ms or more after H_RESET) land. **S3/H3 confirmed for PR8.** My
  sub-prediction that CONFIG and SMPLRT_DIV would land was wrong. PR8's
  effective config is power-on defaults plus the I2C master reading the
  AK8963. Its intended DLPF/200 Hz never applied.
- **E2-2: GYRO_CONFIG is still 0x00 with the CS gap.** S1's 0xFC never
  lands in `4baf206`, because it's still inside the post-reset window.
  **H1 refuted** as a cause of the symptom (together with E1-a). S1 is
  latent: it becomes live as soon as init waits for the reset.
- **Stats:** gyro means are at baseline for both. In quiet 250-sample
  segments the std is baseline-like (gyro 1.1–1.3, accel x 2.0–2.4, accel z
  3.5–3.8). Most of the E2-2 run and the ends of E2-3 were hit by
  vibration bursts (gyro and accel std rising together). The environment is
  intermittently noisy. **Acceptance runs need a quiet table; ask the
  user.**
- **Accel z is −1021/−1022 in every image that leaves the I2C master on**
  (E0-C/D/E, E2-2, E2-3), and −1032/−1033 when USER_CTRL = 0 (the baseline
  and all regdump runs). See H8.

**E2-4/E2-5: robust init** (`patches/fix-reset-wait.patch`:
`delay_us(100000)` instead of `delay_us(100)` after H_RESET). Builds
`cs-gap+reset-wait` (`ccad4e83…`) and `cs-gap+reset-wait+gyro-config`
(`37f7818e…`). Falsifiers set beforehand:
- E2-4 `cs-gap+reset-wait`: S1 predicts GYRO_CONFIG 0xFC, CONFIG 0x03,
  SMPLRT_DIV 0x04, and a broken gyro (self-test offset, ±2000 scale).
  Falsified if GYRO_CONFIG ≠ 0xFC (the writes still don't land) or the
  gyro is at baseline.
- E2-5 `cs-gap+reset-wait+gyro-config`: predicted CONFIG 0x03, SMPLRT_DIV
  0x04, GYRO_CONFIG 0x00, ACCEL_CONFIG 0x00. Gyro std below baseline (41 Hz
  DLPF). Accel std about the same (ACCEL_CONFIG2 is never written, so the
  accel DLPF is unchanged). Falsified if the config differs or the stats are
  worse than baseline.

| Step | Image | Config readback | Raw gyro x/y/z | Raw accel x/y/z | Calibrated gyro x/y/z |
|---|---|---|---|---|---|
| E2-4 | `cs-gap+reset-wait` | CONFIG 0x03, SMPLRT 0x04, **GYRO_CONFIG 0xFC**, ACCEL 0x00, USER_CTRL 0x20 | **140 (0) / 160 (0) / 194.5 (0.5)**, frozen | −0.7 (2.0) / 52.0 (2.3) / −1021.7 (3.7) | 0 / 0 / 0.6 (hides it) |
| E2-5 | `cs-gap+reset-wait+gyro-config` | CONFIG 0x03, SMPLRT 0x04, GYRO 0x00, ACCEL 0x00, USER_CTRL 0x20 (as intended) | 2.34 (**0.56**) / 5.93 (**0.62**) / 8.70 (**0.55**) | −0.7 (2.0) / 52.2 (2.3) / −1022.4 (3.6) | 0.36 (0.56) / **0.94** (0.62) / 0.83 (0.53) |

Runs `…e2-warm-cs-gap+reset-wait`, `…e2-warm-cs-gap+reset-wait+gyro-config`,
readbacks `…e2-cfg-*`. Flashes 20:09–20:12Z. Both runs were quiet.

- **Both predictions held.** With the reset wait, every config write lands,
  including S1's 0xFC, which freezes the gyro. So **S1 is required in the
  changeset once init is fixed**, and PR8's intended config gives **gyro
  noise about 2x lower than baseline** (0.55–0.62 vs 1.05–1.53) with the
  same means. Accel noise is within baseline (as expected: accel DLPF
  unchanged).
- **Criterion caveat, from libwallaby (S8):** calibrated gyro y mean 0.94 is
  outside baseline's 0.10–0.24. `gyro_calibrate()` truncates the bias to
  int (5.93 → 5). The residual is frac(bias), essentially luck; the
  baseline's 6.1 → 6 was lucky. With lower noise it's the dominant
  error. Fix in libwallaby (rounding or a float bias), alongside E3.
- Accel z −1022 is H8 (I2C master on). It's closer to 1g = 1024 counts
  than baseline's −1032.
- E2-5 is warm (after many flashes). The acceptance runs from a power
  cycle are still needed. If cold matches warm (config and stats), the
  candidate is history-independent, which would also allow unattended
  flash-and-test (H6 open question).

### E2-A: cold-boot acceptance of `cs-gap+reset-wait+gyro-config` (20:18–20:22Z)

The user power-cycled; the Wombat booted at 20:17:59Z. The user moved it
from the desk to the floor (stable, no more nudges or vibration), so
**accel level-axis means are not comparable with desk-era runs**. The
user confirmed the desk nudge around 20:00Z was plausible (the accel y
64 → 51 step).

| Run | Raw gyro x/y/z | Raw accel x/y/z | Calibrated gyro x/y/z |
|---|---|---|---|
| `…e2a-cold-candidate-run1` | 2.26 (0.49) / 6.05 (0.60) / 8.94 (0.52) | 10.4 (2.1) / 30.5 (2.1) / −1022.2 (3.5) | 0.24 / 0.02 / 0.92 |
| `…e2a-cold-candidate-run2` | 2.26 (0.50) / 6.04 (0.59) / 8.93 (0.52) | 10.5 (2.2) / 30.4 (2.2) / −1021.8 (3.5) | 0.27 / 0.05 / 0.93 |
| `…e2a-cold-candidate-run3` | 2.26 (0.49) / 6.03 (0.61) / 8.96 (0.50) | 10.5 (2.2) / 30.3 (2.3) / −1022.0 (3.4) | 0.28 / 0.02 / 0.99 |

Readback `…e2a-cold-candidate-config` (regdump2 flashed at 20:22Z): all 32
registers identical to warm E2-5. **The candidate is history-independent**
(H6 open question answered for this firmware): its variants can be tested
with flash alone, without power cycles.

Against the baseline reference (per axis):
- **Gyro: pass, better.** Raw std 0.49–0.61 vs 1.05–1.91 (about 2x
  lower). Raw means identical. Calibrated x and y are within or better than
  baseline; **calibrated z 0.92–0.99 is at or just above baseline's top
  (0.94)**. That's S8 truncation (8.94 → 8); libwallaby, E3.
- **Accel std: pass.** x 2.13–2.21 (baseline 1.93–3.90), y 2.12–2.27
  (2.22–2.87), z 3.35–3.50 (3.48–4.65).
- **Accel z mean −1022** vs baseline −1032.5. It's closer to 1g = 1024 and
  to −1000. H8 (I2C master on) is the suspected cause; the tilt effect on
  z is negligible (1.7°).
- **Accel x/y means: not assessable.** The location changed. That needs a
  pre-PR8 cold baseline on the floor (E2-B).
- Calibrated accel is still broken exactly as in baseline (S6, E3).

**E2-H8** (`patches/h8-nomag.patch`: candidate without the
`setup_magnetometer()` call; `builds/candidate+h8-nomag` `da426909…`;
flashed 20:23Z; `…e2-h8-nomag`, readback `…e2-h8-nomag-config`): USER_CTRL
0x00 and I2C_MST_CTRL 0x00 confirmed, the rest as in the candidate. Raw gyro
2.20 (0.49) / 5.98 (0.62) / 8.92 (0.51), accel 10.6 (2.1) / 30.2 (2.2) /
**−1022.7** (3.5). **H8 refuted.** The new correlation is H9: every image
that did an H_RESET since power-up reads about −1022; power-on-only states
(cold pre-PR8, and regdump over cold pre-PR8) read about −1032.

**E2-B: floor baseline, H9, H10** (the user power-cycled; booted
20:32:18Z with `wombat.bin.pre_pr8`; stock libkipr; nobody touched the
Wombat during the session; flashes 20:36–20:40Z).

| Step | Image | Raw gyro x/y/z | Raw accel x/y/z |
|---|---|---|---|
| 1 `…e2b-floor-prepr8-run1` | pre-PR8 cold | 2.25 (1.07) / 6.21 (1.23) / 9.13 (1.20) | 13.7 (2.2) / 25.6 (2.2) / −1034.8 (3.5) |
| 1 `…run2` | pre-PR8 cold | 2.19 (1.04) / 6.24 (1.24) / 9.06 (1.21) | 13.6 (2.2) / 25.7 (2.2) / −1034.6 (3.5) |
| 1 `…run3` | pre-PR8 cold | 2.22 (1.06) / 6.27 (1.24) / 9.06 (1.15) | 13.4 (2.2) / 25.6 (2.2) / −1034.4 (3.5) |
| 2 `…e2b-regdump2-noreset` | regdump2 (writes nothing) | 2.15 (1.07) / 6.29 (1.34) / 9.01 (1.18) | 13.9 (2.2) / 25.8 (2.2) / −1034.1 (3.5) |
| 3 `…e2b-hreset-only` | `e2-regdump2-hreset` | 2.14 (1.09) / 6.24 (1.36) / 9.05 (1.21) | 13.9 (2.2) / 25.8 (2.2) / −1034.5 (3.5) |
| 4 `…e2b-h10-candidate+h8-nomag` | candidate without `setup_magnetometer()` | 2.20 (0.49) / 6.05 (0.64) / 9.09 (0.53) | 14.3 (2.1) / 25.9 (2.2) / **−1033.7** (3.5) |
| 5 `…e2b-h10-cs-gap+reset-wait+gyro-config` | full candidate | 2.22 (0.49) / 6.12 (0.61) / 8.98 (0.52) | 13.6 (2.2) / 25.8 (2.2) / **−1021.4** (3.5) |

- **The floor baseline matches the desk baseline** in everything except
  the tilt (gyro std 1.04–1.24, accel std 2.2/2.2/3.5).
- **Step 2: the candidate's readout path (two bursts + CS gap) gives the
  same numbers as pre-PR8** when the chip is in the same state.
- **Step 3: H9 refuted.** The reset happened (regdump shows I2C_SLV0_*
  cleared to 0x00), and accel is unchanged.
- **Steps 4–5: H10 supported.** The AK8963 running (PR8's
  `setup_magnetometer()`) shifts accel z by +12.3 counts. x/y are
  unchanged. The E2-A x/y difference (10.4/30.4) was the Wombat shifting
  when the switch was toggled.
- **Candidate vs floor baseline, same session: pass on every raw axis.**
  Gyro means equal, gyro std about 2x lower. Accel x/y means equal. Accel
  std equal. Accel z −1021.4 vs −1034.6: closer to 1g = 1024 and to the
  criterion's "about −1000". The shift is caused by the magnetometer
  being on, which PR8 intends. Whether that's acceptable is the user's
  call. Dropping `setup_magnetometer()` gives accel identical to pre-PR8 and
  keeps the gyro improvement.
- State after E2-B: full candidate flashed (20:40Z). The AK8963 is in
  continuous mode until the next power cycle.

### E3: libwallaby calibration fixes (2026-09-30, from 20:44Z)

- **The deployed 1.2.4 is `cf56155`.** My aarch64 build of `cf56155`
  (`libbuilds/stock-cf56155`, via the new `libbuild.sh`) exports the same
  7443 dynamic symbols as `/usr/lib/libkipr.so`. The only `.rodata` string
  differences are OpenCV's embedded build host, path and timestamp.
- **S11 (new, code reading): both `accel_calibrate()` and
  `gyro_calibrate()` average the already-calibrated getters**, so a second
  call computes a bias of about 0 and silently undoes the calibration.
- Patches (`patches/lib-accel-calibrate.patch`,
  `patches/lib-gyro-calibrate.patch`; `libbuilds/e3-calib`, sha256
  `6414133584db…`):
  - accel: sum x→X and z→Z (S6); gravity term +1024 (±2g), so calibrated
    z at rest = −1024;
  - gyro: double biases instead of int (S8);
  - both: clear the biases before sampling (S11). Getters round
    (`std::lround`) instead of truncating toward zero. With a zero bias the
    value is the integer `raw/16` as before, so uncalibrated values don't
    change.
- Testing without touching `/usr/lib`: `LIBKIPR=<local .so> repro.sh`
  copies the library to `/tmp` and passes `--library` to
  `wombat_sample.py`. Provenance records the sha256.
- Falsifiers (set before running; candidate firmware, floor, same spot as
  E2-B): the raw pass must equal E2-B step 5 (the stock library)
  within run-to-run noise. Calibrated accel must be x ≈ 0, y ≈ 0,
  z ≈ −1024 (|error| < 1) with std ≈ raw std. Calibrated gyro |mean| < 0.5
  on every axis in all 3 runs. Falsified if any of these fails.

**E3 results** (candidate firmware, floor, 20:48–20:56Z):

| Run | Library | Raw accel x/y/z | Calibrated gyro x/y/z | Calibrated accel x/y/z (std) |
|---|---|---|---|---|
| `…e3-calib-run1` | e3-calib | 12.7 / 25.4 / −1021.9 | 0.24 / −0.01 / −0.08 | −0.45 (2.2) / 0.50 (2.1) / −1024.8 (3.4) |
| `…e3-calib-run2` | e3-calib | 12.6 / 25.6 / −1021.8 | 0.24 / −0.01 / −0.11 | −0.35 (2.2) / −0.31 (2.2) / −1023.8 (3.4) |
| `…e3-calib-run3` | e3-calib | 12.6 / 25.5 / −1021.7 | 0.27 / −0.01 / −0.08 | −0.34 (2.2) / 0.46 (2.2) / −1024.6 (3.4) |
| `…e3-bracket-stocklib` | stock | 12.4 / 25.5 / −1021.7 | — | — |

- **All falsifiers passed. H5 confirmed**: the fixed `accel_calibrate()`
  gives x ≈ 0, y ≈ 0, z ≈ −1024 at raw std. The fixed `gyro_calibrate()`
  gives |mean| ≤ 0.27 on every axis (baseline 0.01–1.29).
- **Raw pass is unchanged by the library**: the stock bracket run is equal
  within noise. Accel x drifts slowly after power-up (13.6 at 20:40Z →
  12.4 at 20:55Z), so compare raw accel x only between adjacent runs.
- **S11 confirmed** (`runs/…e3-recalibrate-twice.txt`, 300-sample means
  after each call). Stock library: a 2nd `gyro_calibrate()` sets the biases
  to 0 (gyro back to 2.30/6.01/8.96), and a 2nd `accel_calibrate()` gives
  1557 / 25.5 / −2567. Patched: stable (gyro 0.23/−0.01/−0.04, accel
  0.08/0.41/−1024.1).
- `/usr/lib/libkipr.so` was never modified (`/tmp` only).

## Conclusion (2026-09-30 21:00Z)

**Root cause of the PR8 gyro symptom: H7.** `readIMU()` reads accel and
gyro as two SPI3 transactions with only a few CPU cycles of CS high between
them. The MPU-9250 usually doesn't see the transaction end, so it
continues the accel burst, and the published gyro is bytes 0x42–0x47
(TEMP_L, GX_H, GX_L, GY_H, GY_L, GZ_H), one byte off. The same effect
breaks back-to-back `IMU_read()` → `IMU_write()` in setup. Separately
(H3), PR8's config writes land about 0.4 ms after H_RESET, before the chip
accepts writes, so they are dropped. That hid S1 (gyro self-test on,
±2000 dps).

**The students' "accel symptom" is libwallaby (S6), under any firmware.**

Recommended changeset:
- Wombat-Firmware on `4baf206` (4 lines):
  - `fix-cs-gap`: CS-high gap after reads (fixes H7);
  - `fix-reset-wait`: wait 100 ms after H_RESET (fixes H3; makes init
    history-independent, E2-A);
  - `fix-gyro-config`: S1 (required once the writes land, E2-4).
- libwallaby on `cf56155`: `lib-accel-calibrate` (S6, S11, rounding) and
  `lib-gyro-calibrate` (S8, S11, rounding).

Result against pre-PR8 (cold, same spot): gyro means equal, **gyro noise
about 2x lower** (0.49–0.61 vs 1.04–1.24) from PR8's intended 41 Hz DLPF.
Accel x/y means and all accel std equal. With the libwallaby fixes,
calibrated gyro is within ±0.3 and calibrated accel is 0/0/−1024.

`fix-cs-gap` alone brought raw gyro back to baseline in a warm test (E2-2),
but only because the other config writes are still dropped. It wasn't
cold-tested, and it's fragile, so it's not recommended alone.

For the user to decide: **H10**. With PR8's magnetometer setup, the AK8963
runs in continuous mode, and that shifts raw accel z by +12 counts (−1034 →
−1021.4; x/y unaffected). Calibration removes it. Dropping
`setup_magnetometer()` makes raw accel identical to pre-PR8.

Not addressed (no evidence of harm at rest): S5 publication tearing (3/3000
torn frames with the gap), S7 (no WHO_AM_I check), the unknown source of
`wombat.bin.pre_pr8` (S10), and H4.

### Commits (2026-09-30 21:05–21:15Z)

The user chose to drop `setup_magnetometer()` (H10).

- Wombat-Firmware, `oscar/mpu9250-imu-driver` (ahead of origin by 4, not
  pushed): `35ef0a2` CS gap, `61412c0` gyro self-test mask, `aebaa66` reset
  wait, `49cca43` no magnetometer. The last one removes the call plus the
  200 µs pre-AK8963 delay, and differs from the tested `candidate+h8-nomag`
  only by that delay. `builds/final-49cca43` (`2d941ad8…`, 13 warnings, as
  `4baf206`) was verified on hardware (`…final-49cca43`, readback
  `…final-49cca43-config`): gyro 2.27 (0.48) / 5.96 (0.63) / 8.70 (0.55),
  config as intended, USER_CTRL 0x00. Accel z −1021.6 because the AK8963
  was still running from an earlier flash (H10 persistence). It needs a
  power cycle to show −1034.
- libwallaby, new branch `fix-imu-calibration` from `master` `cf56155` (not
  pushed): `de1c6f6` accel, `2383007` gyro. The committed files are
  byte-identical to `libbuilds/e3-calib/src`.

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

The investigation is complete (see Conclusion). Possible follow-ups, if the user wants them:

- Decide on H10 (keep or drop `setup_magnetometer()`).
- The single 14-byte burst read (0x3B–0x48): accel and gyro from one
  sample instant, with fewer transactions. That would be a robustness
  improvement, not needed for the criterion.
- An independent review of the 5 patches (only if the user asks for
  agents).
- Turn the patches into commits or PRs on the two repos.

## Wombat changes

| When (UTC) | Change | Why |
|---|---|---|
| 2026-09-30 | `sudo apt-get install -y gdbserver` (16.3-1) | Remote debugging |
| 2026-09-30 19:11 | Flashed `wombat.bin.pr8` | E0-C |
| 2026-09-30 19:12 | Flashed `wombat.bin.pre_pr8` | E0-D |
| 2026-09-30 ~19:14 | `sudo reboot` | E0-E |
| 2026-09-30 ~19:20 | Power cycle by the user (poweroff plus switch) | E0-F |
| 2026-09-30 19:55–20:12 | Flashed in turn: `e1-regdump`, `e1-regdump-gap`, `e1-regdump2`, `wombat.bin.pr8`, `fix-cs-gap`, `fix-cs-gap+gyro-config`, `cs-gap+reset-wait`, `cs-gap+reset-wait+gyro-config`, with `e1-regdump2` after each (logs in `flashes/`) | E1, E2 |
| 2026-09-30 20:13 | Flashed `cs-gap+reset-wait+gyro-config` (`37f7818e…`) | Ready for the cold-boot acceptance runs |
| 2026-09-30 ~20:15 | User moved the Wombat to the floor and power-cycled (booted 20:17:59Z) | E2-A |
| 2026-09-30 20:22–20:26 | Flashed `e1-regdump2`, `candidate+h8-nomag`, `e1-regdump2`, then `wombat.bin.pre_pr8` | E2-A readback, H8, E2-B prep |
| 2026-09-30 ~20:31 | Power cycle by the user (booted 20:32:18Z) | E2-B |
| 2026-09-30 20:36–20:40 | Flashed `e1-regdump2`, `e2-regdump2-hreset`, `candidate+h8-nomag`, `cs-gap+reset-wait+gyro-config` | E2-B, H9, H10 |
| 2026-09-30 21:08–21:10 | Flashed `final-49cca43`, `e1-regdump2`, `final-49cca43` | Verify the committed firmware |

State as of 2026-09-30 20:14Z: the candidate `cs-gap+reset-wait+gyro-config` is flashed and the IMU is warm. `kipr` 1.2.4
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
